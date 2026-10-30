"""Assemble the accepted S23 records once for checks, previews and import."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import csv
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from urllib.parse import quote

from prepare_s23_review import segments
from read_s22_frame_labels import norm
from season_naming import digest
from s23_endgames import endgame_for
from s23_schema import normalize as normalize_schema, normalize_voting
from game_flow import replay as replay_flow
from board_catalog import canonical_board_name
from s23_phase_review import enrich as enrich_phase_review
from s23_daily_audit import load_audit, apply_events, apply_findings, recap_rows

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
# Reuse the website's pure display projection, without publishing a release.
from website.api.game_presentation import build_game_presentation
EXPORT=ROOT/'data/exports'
WOLVES={'狼人','机械狼','狼王','黑狼王','假面','诡术师','典狱长','盗宝大师','九尾狐','狼术师'}
KNOWN_HANDLES={'JY戴士':'JY','Ksssssss陈彬':'KS','BobbyJ波比儿':'Bobby','Qqqquan圈':'圈圈',
               '困困不六':'圈圈','小鲸鱼Whale-':'董鲸鱼','赵鑫华_HZz':'华仔仔',
               '其人的心事':'其人','陸慧霖_陆元箐小桃子':'桃子','pointy豆儿啵':'豆儿啵','萧亚辉':'辉少'}


def load_aliases():
    aliases=defaultdict(set)
    path=ROOT/'data/weibo/2026-05-26_2026-10-20/参赛名单/人名去重_照片映射.csv'
    with path.open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            if row.get('赛季')!='S23' or row.get('原人工确认状态') not in {'确认无误','已修正'}:continue
            canonical=row['去重后姓名']
            for k in ['原图名字','复核行名字','去重后姓名']:
                if row.get(k):aliases[norm(row[k])].add(canonical)
    for key,value in KNOWN_HANDLES.items():aliases[norm(key)].add(value)
    return aliases


def canonical(raw,aliases):
    if not raw:return None
    key=norm(raw)
    if len(aliases.get(key,[]))==1:return next(iter(aliases[key]))
    matches=[(len(alias),value) for alias,values in aliases.items() if len(alias)>=2 and alias in key for value in values]
    if matches:
        longest=max(n for n,_ in matches);values={value for n,value in matches if n==longest}
        if len(values)==1:return values.pop()
    return raw


def file_url(path,from_dir=EXPORT):
    if not path:return ''
    return quote(os.path.relpath(ROOT/path,from_dir).replace('\\','/'),safe='/.:_')


def load_effective_games(bvids=None, *, require_complete=False):
    """Load selected games and only load peer records for unresolved seat names.

    No original, candidate, report or database file is written here. Same-day
    roster reuse follows the existing agreement checks and is reported as a
    dependency. Peer source hashes are checked, but their text is not parsed.
    """
    started = perf_counter()
    base = ROOT / 'data/extractions/S23/game_reviews'
    cache = {}
    def read(path):
        if path not in cache:
            cache[path] = json.loads(path.read_text(encoding='utf-8'))
        return deepcopy(cache[path])
    plan = read(ROOT / 'data/reports/S23/S23_逐局复核计划.json')
    checkpoint_path = ROOT / 'data/reports/S23/S23_续核清单.json'
    checkpoint = read(checkpoint_path) if checkpoint_path.exists() else {}
    entries = [e for e in plan['entries'] if e['phase'] == 'regular']
    selected = set(bvids) if bvids is not None else {e['bvid'] for e in entries}
    unknown = selected - {e['bvid'] for e in entries}
    if unknown:
        raise ValueError('不在S23正赛复核计划中：' + ', '.join(sorted(unknown)))
    aliases = load_aliases()
    primary_notes = []
    def load_entry(entry):
        entry=deepcopy(entry)
        folder=base/entry['bvid']
        paths=[folder/p for p in ['dossier.reviewed.json','voting.reviewed.json','ai_review.json']]
        if not all(p.is_file() for p in paths):return None
        dossier,voting,review=[read(p) for p in paths]
        if review.get('bvid')!=entry['bvid'] or review.get('source_sha256')!=entry['source_sha256']:raise ValueError('来源绑定不匹配 '+entry['bvid'])
        primary_path=folder/'primary_review.json'
        if primary_path.exists():
            primary=read(primary_path)
            if primary.get('bvid')!=entry['bvid'] or primary.get('source_sha256')!=entry['source_sha256']:
                raise ValueError('主审补正来源绑定不匹配 '+entry['bvid'])
            for patch in primary.get('patches',[]):
                if patch['target']=='dossier':dossier=deepcopy(patch['value'])
                if patch['target']=='voting':voting=deepcopy(patch['value'])
            review['decisions']+=primary.get('decisions',[])
            resolved=set(primary.get('resolved_question_ids',[]))
            review['human_questions']=[q for q in review.get('human_questions',[]) if q['id'] not in resolved]
            review['primary_review']=primary
            for field,value in primary.get('dossier_field_overrides',{}).items():
                if field not in {'game_number','date'}:raise ValueError('不支持的主审字段 '+field)
                dossier[field]=value
            for item in primary.get('seat_name_overrides',[]):
                next(s for s in dossier['seats'] if s['seat']==item['seat'])['name']=item['name']
        # Collection titles may omit or mislabel a game number. The reviewed
        # in-video announcement is the candidate value; retain the raw entry.
        if dossier.get('date') != entry['date']:
            entry['collection_date']=entry['date']
            entry['date']=dossier['date']
        if dossier.get('game_number') != entry['game_number']:
            entry['collection_game_number']=entry['game_number']
            entry['game_number']=dossier.get('game_number')
        entry['output_dir']=f'data/games/S23/{entry["date"]}_g{entry["game_number"] or 0:02d}_{entry["bvid"]}'
        reviewed_board=canonical_board_name(dossier.get('board')) or {'qingqiu_night':'青丘夜影','magic_duel':'魔幻对决'}.get(dossier.get('board'))
        if reviewed_board and reviewed_board!=entry['board_name']:
            entry['collection_board_name']=entry['board_name']
            entry['board_name']=reviewed_board
        entry['board']=dossier['board']
        expected_slug=f'bili-{entry["bvid"]}-p01-g{entry["game_number"] or 0:02d}'
        dossier['slug']=expected_slug
        voting['game_slug']=expected_slug
        ocr_path=folder/'screen_ocr.json'
        ocr=read(ocr_path) if ocr_path.exists() else {}
        for seat in dossier['seats']:
            original=seat.get('name');name=canonical(original,aliases)
            screen=next((s for s in ocr.get('seats',[]) if s['seat']==seat['seat']),{})
            if not name and screen.get('name') and float(screen.get('confidence') or 0)>=.85:
                name=screen['name']
            if name!=original:
                primary_notes.append({'bvid':entry['bvid'],'field':f"seats[{seat['seat']}].name",'before':original,'after':name,
                                      'basis':'已复核S23人名别名与本局画面姓名候选'})
            seat['name']=name
            role=seat.get('role')
            if role in {'九尾','九尾妖狐'}:seat['role']='九尾狐';role='九尾狐'
            if role in {'狼术士'}:seat['role']='狼术师';role='狼术师'
            if role in WOLVES:seat['faction']='werewolf'
            elif role and role!='混血儿':seat['faction']='good'
        for key in ['roster','commentators']:
            dossier[key]=list(dict.fromkeys(canonical(s,aliases) for s in dossier.get(key,[]) if s))
        dossier['referee']=canonical(dossier.get('referee'),aliases)
        for seat in dossier['seats']:
            if seat.get('role')=='混血儿':
                models=[e for r in dossier.get('rounds',[]) for e in r.get('night',[]) if e.get('slot')=='mixed_blood_model' and e.get('action')=='choose' and e.get('targets')]
                targets={e['targets'][0] for e in models}
                if len(targets)==1:
                    target=next(s for s in dossier['seats'] if s['seat']==next(iter(targets)))
                    if target.get('faction') in {'good','werewolf'}:seat['faction']=target['faction']
        voting,voting_normalization=normalize_voting(voting,dossier)
        dossier,extra,normalization,models=normalize_schema(dossier,voting)
        normalization+=voting_normalization
        review['structural_normalizations']=normalization
        review['supplemental_events']=extra
        pending=checkpoint.get('game_followups',{}).get(entry['bvid'],{})
        if pending:
            if pending['source_sha256']!=entry['source_sha256']:raise ValueError('续核检查点来源已变化 '+entry['bvid'])
            review['open_ai_followups']=list(dict.fromkeys(review.get('open_ai_followups',[])+pending['items']))
            resolved=set(pending.get('resolved_human_question_ids',[]))
            review['human_questions']=[q for q in review.get('human_questions',[]) if q['id'] not in resolved]
        return {'entry':entry,'dossier':dossier,'voting':voting,'review':review,
                      'seat_models':models,'supplemental_events':extra,
                      'source_url':file_url(entry['source_path']),'audio_url':file_url(entry['audio_path']),
                      'frame_url':file_url(entry['frame']['frame_path']),
                      'raw_dossier_url':file_url((folder/'dossier.reviewed.json').relative_to(ROOT).as_posix()),
                      'video_url':f'https://www.bilibili.com/video/{entry["bvid"]}/'}

    loaded = {e['bvid']: load_entry(e) for e in entries if e['bvid'] in selected}
    missing = [bvid for bvid, game in loaded.items() if game is None]
    unresolved_dates = {g['entry']['date'] for g in loaded.values() if g and
                        any(not s.get('name') for s in g['dossier']['seats'])}
    if unresolved_dates and bvids is not None:
        # Find direct roster dependencies by reviewed date, including date
        # corrections. This reads only metadata, never peer transcripts.
        for entry in entries:
            if entry['bvid'] in loaded:
                continue
            folder = base / entry['bvid']
            raw = folder / 'dossier.reviewed.json'
            if not raw.is_file():
                continue
            date = read(raw).get('date')
            primary_path = folder / 'primary_review.json'
            if primary_path.is_file():
                primary = read(primary_path)
                for patch in primary.get('patches', []):
                    if patch['target'] == 'dossier':
                        date = patch['value'].get('date')
                date = primary.get('dossier_field_overrides', {}).get('date', date)
            if date in unresolved_dates:
                loaded[entry['bvid']] = load_entry(entry)
    games = [g for g in loaded.values() if g is not None]
    for game in games:
        entry = game['entry']
        if entry['bvid'] not in selected and digest(ROOT/entry['source_path']) != entry['source_sha256']:
            raise ValueError('姓名复用依赖来源已变化：' + entry['bvid'])
    # Reuse a same-day name only when every directly readable seat agrees and rosters match.
    games.sort(key=lambda g:(g['entry']['date'],g['entry']['game_number'] or 0,g['entry']['bvid']))
    schedule_keys=[(g['entry']['date'],g['entry']['game_number']) for g in games]
    if len(schedule_keys)!=len(set(schedule_keys)):
        raise ValueError('复核日期与局序仍有重复：'+str([k for k,n in Counter(schedule_keys).items() if n>1]))
    by_date=defaultdict(list)
    for g in games:by_date[g['entry']['date']].append(g)
    for date,day_games in by_date.items():
        for g in day_games:
            d=g['dossier'];known={s['seat']:s['name'] for s in d['seats'] if s.get('name')}
            for seat in d['seats']:
                if seat.get('name'):continue
                candidates=[]
                for peer in day_games:
                    pd=peer['dossier'];names={s['seat']:s.get('name') for s in pd['seats']}
                    if set(pd['roster'])!=set(d['roster']):continue
                    if any(names[n] and names[n]!=name for n,name in known.items()):continue
                    if names.get(seat['seat']):candidates.append((names[seat['seat']],peer['entry']['frame']['frame_path']))
                values={name for name,_ in candidates}
                if len(values)==1:
                    seat['name']=next(iter(values));primary_notes.append({'bvid':g['entry']['bvid'],'field':f"seats[{seat['seat']}].name",'after':seat['name'],'basis':'同日同阵容且所有已知座位相符的姓名复用','sources':[p for _,p in candidates]})
    dependencies = [g['entry']['bvid'] for g in games if g['entry']['bvid'] not in selected]
    games = [g for g in games if g['entry']['bvid'] in selected]
    assembled = perf_counter()
    source_segments = {}
    for g in games:
        entry = g['entry']
        g['transcript']=segments(ROOT/entry['source_path'])
        source_segments[(ROOT/entry['source_path']).resolve().as_posix()] = g['transcript']
        g['endgame']=endgame_for(entry,g['dossier'],rows=g['transcript'],root=ROOT)
        audit=load_audit(base/entry['bvid'],entry)
        if require_complete and not audit:
            raise ValueError('尚缺逐日复核与最终复盘窗口 '+entry['bvid'])
        if audit:
            apply_events(g,audit)
        if g['dossier']['board'] not in {'qingqiu_night','magic_duel'}:
            g['presentation']=build_game_presentation({**g['dossier'],'voting':g['voting']})
        else:
            g['presentation']={'version':'S23_new_board_explicit_events','rounds':deepcopy(g['dossier']['rounds']),'omitted_events':0}
        if g['dossier']['board'] not in {'qingqiu_night','magic_duel'}:
            flow_dossier=deepcopy(g['dossier'])
            if flow_dossier['board']=='masquerade':
                for seat in flow_dossier['seats']:
                    if seat['role']=='白神':seat['role']='白痴'
            g['flow']=replay_flow(flow_dossier,g['voting'],endgame_phases=g['endgame']['phases'])
        enrich_phase_review(g)
        if audit:
            apply_findings(g,audit)
            g['recap_window']=audit['recap_window']
            g['full_transcript_segments']=len(g['transcript'])
            g['transcript']=recap_rows(g['transcript'],audit)
    if require_complete and missing:
        raise ValueError('尚缺逐局AI复核：' + ', '.join(missing))
    return {'games': games, 'missing': missing, 'primary_notes': primary_notes,
            'checkpoint': checkpoint, 'dependency_bvids': dependencies,
            'source_segments': source_segments,
            'timings_seconds': {'record_assembly': assembled - started,
                                'evidence_and_projection': perf_counter() - assembled}}


def load_effective_game(bvid, *, require_complete=False):
    result = load_effective_games([bvid], require_complete=require_complete)
    if not result['games']:
        raise ValueError('尚缺逐局AI复核：' + bvid)
    return result['games'][0]


def candidate_values(game):
    entry = game['entry']
    binding = {'game_slug': game['dossier']['slug'], 'source_sha256': entry['source_sha256']}
    return {'dossier.candidate.json': game['dossier'], 'voting.candidate.json': game['voting'],
            'ai_review.json': game['review'], 'endgame.candidate.json': game['endgame'],
            'vote_control.candidate.json': {**binding, **game['vote_control']},
            'supplemental.candidate.json': {**binding, 'events': game['supplemental_events']}}


def verify_current_candidate(candidate_path, *, effective_game=None):
    """Reject stale materialized records before the formal adapter reads them."""
    candidate_path = Path(candidate_path)
    stored = json.loads(candidate_path.read_text(encoding='utf-8'))
    match = re.search(r'BV[0-9A-Za-z]+', stored['slug'])
    if not match:
        raise ValueError('候选slug缺少BV：' + stored['slug'])
    game = effective_game if effective_game is not None else load_effective_game(match[0], require_complete=True)
    if game['entry']['bvid'] != match[0]:
        raise ValueError('有效候选与目标BVID不匹配：' + match[0])
    changed = []
    for name, expected in candidate_values(game).items():
        path = candidate_path.with_name(name)
        if not path.is_file():
            changed.append(name)
            continue
        actual = json.loads(path.read_text(encoding='utf-8'))
        if actual != expected:
            changed.append(name)
    if changed:
        raise ValueError('候选材料已过期，请先运行 build_s23_review.py --bvid ' + match[0] + '：' + ', '.join(changed))
    return game
