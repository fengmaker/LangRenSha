"""Assemble S23 AI candidates and a local human-review workspace; no DB import."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote

from collect_bilibili_audio import save_json
from prepare_s23_review import segments
from read_s22_frame_labels import norm
from season_naming import digest
from s23_endgames import endgame_for
from s23_schema import normalize as normalize_schema, normalize_voting
from game_flow import replay as replay_flow
from board_catalog import canonical_board_name
from s23_phase_review import enrich as enrich_phase_review

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
# Reuse the website's pure display projection, without publishing a release.
from website.api.game_presentation import build_game_presentation
BASE=ROOT/'data/extractions/S23/game_reviews'
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


def build(require_complete=False):
    plan=json.loads((ROOT/'data/reports/S23_逐局复核计划.json').read_text(encoding='utf-8'))
    checkpoint_path=ROOT/'data/reports/S23_续核清单.json'
    checkpoint=json.loads(checkpoint_path.read_text(encoding='utf-8')) if checkpoint_path.exists() else {}
    aliases=load_aliases();games=[];missing=[];questions=[];primary_notes=[]
    for entry in plan['entries']:
        if entry['phase']!='regular':continue
        entry=deepcopy(entry)
        folder=BASE/entry['bvid']
        paths=[folder/p for p in ['dossier.reviewed.json','voting.reviewed.json','ai_review.json']]
        if not all(p.is_file() for p in paths):missing.append(entry['bvid']);continue
        dossier,voting,review=[json.loads(p.read_text(encoding='utf-8')) for p in paths]
        if review.get('source_sha256')!=entry['source_sha256']:raise ValueError('来源绑定不匹配 '+entry['bvid'])
        primary_path=folder/'primary_review.json'
        if primary_path.exists():
            primary=json.loads(primary_path.read_text(encoding='utf-8'))
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
        ocr=json.loads(ocr_path.read_text(encoding='utf-8')) if ocr_path.exists() else {}
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
        games.append({'entry':entry,'dossier':dossier,'voting':voting,'review':review,'endgame':endgame_for(entry,dossier),
                      'seat_models':models,'supplemental_events':extra,
                      'source_url':file_url(entry['source_path']),'audio_url':file_url(entry['audio_path']),
                      'frame_url':file_url(entry['frame']['frame_path']),
                      'raw_dossier_url':file_url((folder/'dossier.reviewed.json').relative_to(ROOT).as_posix()),
                      'video_url':f'https://www.bilibili.com/video/{entry["bvid"]}/'})
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
    EXPORT.mkdir(parents=True,exist_ok=True)
    for g in games:
        entry=g['entry'];out=ROOT/entry['output_dir'];out.mkdir(parents=True,exist_ok=True)
        g['transcript']=segments(ROOT/entry['source_path'])
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
        save_json(out/'dossier.candidate.json',g['dossier']);save_json(out/'voting.candidate.json',g['voting']);save_json(out/'ai_review.json',g['review'])
        save_json(out/'endgame.candidate.json',g['endgame'])
        save_json(out/'vote_control.candidate.json',{'game_slug':g['dossier']['slug'],'source_sha256':entry['source_sha256'],**g['vote_control']})
        save_json(out/'supplemental.candidate.json',{'game_slug':g['dossier']['slug'],'source_sha256':entry['source_sha256'],'events':g['supplemental_events']})
        g['candidate_sha256']=digest(out/'dossier.candidate.json')
        g['dossier_url']=file_url((out/'dossier.candidate.json').relative_to(ROOT).as_posix())
        for proof in walk_evidence(g['review']):
            if isinstance(proof.get('source_path'),str):proof['file_url']=file_url(proof['source_path'])
        for proof in walk_evidence(g['endgame']):
            proof['file_url']=file_url(proof['source_path'])
        for proof in walk_evidence(g['vote_control']):
            proof['file_url']=file_url(proof['source_path'])
        for i,q in enumerate(g['review'].get('human_questions',[])):
            questions.append({'日期':entry['date'],'局次':entry['game_number'],'版型':entry['board_name'],'BVID':entry['bvid'],
                              '轮次':q.get('round'),'阶段':q.get('phase'),'日夜':q.get('phase_label'),
                              '问题ID':q.get('id',str(i)),'字段':q.get('field'),'问题':q.get('question'),
                              '选项':' | '.join(q.get('options',[])),'原因':q.get('reason'),'证据':json.dumps(q.get('evidence',[]),ensure_ascii=False)})
    snapshot=hashlib.sha256('\n'.join(g['entry']['bvid']+g['entry']['source_sha256']+g['candidate_sha256']+
                                    hashlib.sha256(json.dumps(g['voting'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()+
                                    hashlib.sha256(json.dumps(g['endgame'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()+
                                    hashlib.sha256(json.dumps(g['vote_control'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()+
                                    hashlib.sha256(json.dumps(g['review'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                                    for g in games).encode()).hexdigest()
    labels={}
    for path in (ROOT/'config/board_templates').glob('*.json'):
        board=json.loads(path.read_text(encoding='utf-8'))
        for phase in ['night','day']:
            for slot in board.get(phase+'_slots',[]):labels[slot['code']]=slot['label']
    labels.update({'fox_mark':'九尾狐标记','fox_hunt':'九尾狐猎杀时刻','baize_purge':'白泽清除标记',
                   'baize_inherit':'白泽传承','wolf_sorcerer_exchange':'狼术师交换','fox_knife':'九尾狐带刀',
                   'nine_tail_mark':'九尾狐标记','nine_tail_hunt':'九尾狐猎杀时刻','baize_clear':'白泽清除标记'})
    labels.update({'whiteze_clear_mark':'白泽清除标记','whiteze_clear':'白泽清除标记',
                   'nine_tail_kill':'九尾狐猎杀结算','nine_tail_skill':'九尾狐猎杀时刻',
                   'nine_tail_vote_mark':'九尾狐警徽票标记','game_end':'游戏结束',
                   'magic_duel_wolf_sorcerer_swap':'狼术师交换','magic_duel_magician_swap':'魔术师交换',
                   'disqualification':'违规判离（DQ）','sheriff_vote':'警长竞选投票'})
    labels.update({'concession':'交牌认输','werewolf_surrender':'狼人交牌','treasure_master_change':'盗宝大师切换身份',
                   'magician_death_exchange':'魔术师出局交换','sorcerer_exchange':'狼术师交换','game_end':'游戏结束'})
    summary={'planned':75,'ai_reviewed':len(games),'human_questions':len(questions),
             'games_with_human_questions':sum(bool(g['review'].get('human_questions')) for g in games),
             'known_roles':sum(bool(s.get('role')) for g in games for s in g['dossier']['seats']),
             'named_seats':sum(bool(s.get('name')) for g in games for s in g['dossier']['seats']),
             'ballots':sum(len(g['voting'].get('ballots',[])) for g in games),
             'votes':sum(len(b.get('votes',[])) for g in games for b in g['voting'].get('ballots',[])),
             'wolf_rush_phases':sum(len(g['endgame']['phases']) for g in games),
             'ai_followup_games':sum(bool(g['review'].get('open_ai_followups')) or g['review']['phase_review_counts']['unresolved']>0 for g in games),
             'phase_pending_items':sum(g['review']['phase_review_counts']['unresolved'] for g in games),
             'phase_pending_games':sum(g['review']['phase_review_counts']['unresolved']>0 for g in games),
             'phase_inferred_items':sum(g['review']['phase_review_counts']['inferred'] for g in games),
             'remaining_games':len(missing),'delivery_status':checkpoint.get('status','in_progress'),
             'excluded_showmatches':12,'formal_database_writes':False,
             'display_rule_inferences':sum(bool(e.get('inferred')) for g in games for r in g['presentation']['rounds'] for phase in ['night','day'] for e in r[phase]),
             'omitted_inapplicable_slots':sum(g['presentation']['omitted_events'] for g in games)}
    payload={'schema_version':1,'snapshot_id':snapshot,'generated_at_utc':datetime.now(timezone.utc).isoformat(),
             'summary':summary,'slot_labels':labels,'games':games}
    summary['delivery_status']='phase_gaps_pending' if summary['phase_pending_items'] else 'phase_reviewed_pending_user_confirmation'
    template=(ROOT/'scripts/templates/s23_review.html').read_text(encoding='utf-8')
    script=(ROOT/'scripts/templates/s23_review.js').read_text(encoding='utf-8')
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    html=template.replace('__DATA__',encoded).replace('__SCRIPT__',script)
    html_path=EXPORT/'S23_逐局推导与复核.html';html_path.write_text(html,encoding='utf-8')
    fields=['日期','局次','版型','BVID','轮次','阶段','日夜','问题ID','字段','问题','选项','原因','证据']
    with (EXPORT/'S23_必须人工复核.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(questions)
    phase_rows=[]
    for g in games:
        for finding in g['review']['phase_findings']:
            if finding['status']!='unresolved':continue
            phase_rows.append({'日期':g['entry']['date'],'局次':g['entry']['game_number'],'版型':g['entry']['board_name'],
                               'BVID':g['entry']['bvid'],'轮次':finding['round'],'阶段':finding['phase'],
                               '日夜':finding['phase_label'],'问题ID':finding['id'],'字段':finding['field'],
                               '问题':finding['title'],'原因':finding.get('reasoning',''),
                               '证据':json.dumps(finding.get('evidence',[]),ensure_ascii=False)})
    with (EXPORT/'S23_日夜待核清单.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        fields2=['日期','局次','版型','BVID','轮次','阶段','日夜','问题ID','字段','问题','原因','证据']
        writer=csv.DictWriter(stream,fieldnames=fields2);writer.writeheader();writer.writerows(phase_rows)
    save_json(ROOT/'data/reports/S23_日夜待核定位.json',{'generated_at_utc':payload['generated_at_utc'],
              'pending_items':summary['phase_pending_items'],'pending_games':summary['phase_pending_games'],
              'games':[{'bvid':g['entry']['bvid'],'date':g['entry']['date'],'game_number':g['entry']['game_number'],
                        'findings':g['review']['phase_findings']} for g in games],'formal_database_writes':False})
    save_json(ROOT/'data/reports/S23_人员规范化依据.json',{'items':primary_notes})
    save_json(ROOT/'data/reports/S23_结构规范化依据.json',{'games':[{'bvid':g['entry']['bvid'],'changes':g['review']['structural_normalizations'],'supplemental_events':g['supplemental_events']} for g in games]})
    report={**summary,'snapshot_id':snapshot,'generated_at_utc':payload['generated_at_utc'],
            'missing_ai_reviews':missing,'review_page':html_path.relative_to(ROOT).as_posix(),
            'human_review_csv':'data/exports/S23_必须人工复核.csv','phase_review_csv':'data/exports/S23_日夜待核清单.csv',
            'candidate_dossiers':[g['entry']['output_dir']+'/dossier.candidate.json' for g in games]}
    save_json(ROOT/'data/reports/S23_逐局复核进度.json',report)
    if require_complete and missing:raise ValueError(f'仍缺{len(missing)}局AI逐局复核，未报告完成')
    return report


def walk_evidence(value):
    if isinstance(value,dict):
        if 'source_path' in value and ('quote' in value or value.get('kind')=='video_frame'):yield value
        for child in value.values():yield from walk_evidence(child)
    elif isinstance(value,list):
        for child in value:yield from walk_evidence(child)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--require-complete',action='store_true');args=parser.parse_args()
    result=build(args.require_complete);print(json.dumps({k:v for k,v in result.items() if k not in {'candidate_dossiers','missing_ai_reviews'}},ensure_ascii=False,indent=2))
