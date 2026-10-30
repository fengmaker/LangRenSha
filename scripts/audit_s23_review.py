"""Validate review candidates and evidence, without writing formal game tables."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from collect_bilibili_audio import save_json
from prepare_s23_review import segments
from season_naming import digest
from board_config import load_template
import s23_effective_game

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/extractions/S23/game_reviews'
HISTORICAL_EVIDENCE_PATHS={
    'docs/12_S22正式版型规则与录入流程.md': 'docs/archive/S22/正式版型规则与录入流程.md',
}
NEW_COUNTS={
 'qingqiu_night':{'狼人':3,'九尾狐':1,'预言家':1,'女巫':1,'守卫':1,'白泽':1,'平民':4},
 'magic_duel':{'狼人':3,'狼术师':1,'预言家':1,'女巫':1,'猎人':1,'魔术师':1,'平民':4},
}


def evidence_objects(value):
    if isinstance(value,dict):
        if ('quote' in value or 'kind' in value) and ('source_path' in value or 'source' in value):
            yield value
        for child in value.values():yield from evidence_objects(child)
    elif isinstance(value,list):
        for child in value:yield from evidence_objects(child)


def normalized(value):
    return re.sub(r'\s+','',str(value or ''))


def resolve_evidence_path(root, value):
    """Resolve project evidence, including the one documented S22 path move."""
    if not isinstance(value, str):
        return None, 'evidence_path'
    root = Path(root).resolve()
    requested = (root / value).resolve()
    allowed = (root / 'data').resolve(), (root / 'config').resolve(), (root / 'docs').resolve()
    if not any(requested.is_relative_to(base) for base in allowed):
        return None, 'evidence_outside_project'
    if requested.is_file():
        return requested, None
    key = value.replace('\\', '/').removeprefix('./')
    migrated = HISTORICAL_EVIDENCE_PATHS.get(key)
    if migrated:
        resolved = (root / migrated).resolve()
        if resolved.is_relative_to((root / 'docs').resolve()) and resolved.is_file():
            return resolved, None
    return None, 'evidence_missing'


def audio_asr_evidence_errors(root, proof, transcript_path):
    """Validate a narrow ASR clip against its own source window and provenance."""
    root = Path(root).resolve()
    errors = []
    try:
        source = json.loads(Path(transcript_path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return [('evidence_asr_format', str(transcript_path))]
    if not isinstance(source, dict) or source.get('status') != 'machine_generated_unverified':
        return [('evidence_asr_format', 'audio_asr 引用缺少未核实机器稿结构')]

    start, end = proof.get('start_ms'), proof.get('end_ms')
    source_start, source_end = source.get('start_ms'), source.get('end_ms')
    if (type(start) is not int or type(end) is not int or start < 0 or end <= start or
            type(source_start) is not int or type(source_end) is not int or
            source_start < 0 or source_end <= source_start or (start, end) != (source_start, source_end)):
        errors.append(('evidence_time_mismatch', {
            'proof': [start, end], 'source': [source_start, source_end]}))

    expected_source_sha = proof.get('source_sha256')
    if not isinstance(expected_source_sha, str) or digest(Path(transcript_path)) != expected_source_sha:
        errors.append(('evidence_sha256_mismatch', str(transcript_path)))

    source_audio = source.get('source_audio')
    proof_audio = proof.get('source_audio_path')
    if not isinstance(source_audio, str) or not isinstance(proof_audio, str):
        errors.append(('evidence_asr_source_mismatch', 'ASR片段缺少原音频路径绑定'))
    else:
        source_audio_path = Path(source_audio).resolve()
        proof_audio_path = Path(proof_audio).resolve()
        if source_audio_path != proof_audio_path:
            errors.append(('evidence_asr_source_mismatch', {
                'proof': proof_audio, 'source': source_audio}))
        if not source_audio_path.is_relative_to(root):
            errors.append(('evidence_outside_project', source_audio))
        elif not source_audio_path.is_file():
            errors.append(('evidence_missing', source_audio))
        else:
            expected_audio_sha = source.get('source_audio_sha256')
            if (not isinstance(expected_audio_sha, str) or
                    proof.get('source_audio_sha256') != expected_audio_sha or
                    digest(source_audio_path) != expected_audio_sha):
                errors.append(('evidence_sha256_mismatch', source_audio))

    candidates = []
    if isinstance(source.get('text'), str):
        candidates.append(source['text'])
    raw_result = source.get('raw_result')
    if isinstance(raw_result, list):
        candidates.extend(item.get('text', '') for item in raw_result
                          if isinstance(item, dict) and isinstance(item.get('text'), str))
    quote = normalized(proof.get('quote'))
    if quote and not any(quote in normalized(text) for text in candidates):
        errors.append(('quote_mismatch', {
            'source_path': proof.get('source_path'), 'start_ms': start,
            'end_ms': end, 'quote': proof.get('quote')}))
    return errors


def check_structure(dossier, voting, add):
    if dossier.get('season')!='S23' or dossier.get('phase')!='regular':add('scope','非S23正赛')
    seats=dossier.get('seats',[])
    roles_by_seat={s.get('seat'):s.get('role') for s in seats}
    if sorted(s.get('seat') for s in seats)!=list(range(1,13)):add('seat_set','座位必须为1到12各一次')
    roles=Counter(s.get('role') for s in seats if s.get('role'))
    code=dossier.get('board')
    rules=NEW_COUNTS.get(code)
    try:
        board=load_template(code,ROOT)
    except FileNotFoundError:
        board=None
    if board is not None:
        if not board.get('dynamic_roles'):rules=board['role_counts']
    # The S23 broadcast labels the masquerade white role as 白神. Keep that
    # literal label in candidates; this count-only alias does not infer skills.
    if code=='masquerade' and '白痴' in (rules or {}) and roles.get('白神'):
        roles['白痴']+=roles.pop('白神')
    if rules:
        for role,count in roles.items():
            if role not in rules or count>rules[role]:add('role_count',f'{role}: {count} 与配置 {rules.get(role,0)} 不符')
        if sum(roles.values())==12 and roles!=Counter(rules):add('complete_role_counts','12座身份齐全但与配置不符')
    if dossier.get('winner') not in {'good','werewolf','third_party'}:add('winner_unknown','胜方尚未核清','warning')
    rounds=dossier.get('rounds',[])
    numbers=[r.get('number') for r in rounds]
    if numbers!=list(range(1,len(rounds)+1)):add('round_sequence',f'轮次不连续: {numbers}')
    potions=Counter()
    for round_ in rounds:
        night={e.get('slot'):e for e in round_.get('night',[])}
        save,poison=night.get('witch_save',{}),night.get('witch_poison',{})
        if save.get('action')=='save' and save.get('actor') in save.get('targets',[]):
            add('witch_self_save',f"第{round_['number']}夜普通女巫不能自救")
        if save.get('action')=='save' and poison.get('action')=='poison':
            add('witch_two_potions_same_night',f"第{round_['number']}夜普通女巫同时使用两药")
        for phase in ['night','day']:
            seen=set()
            for event in round_.get(phase,[]):
                slot=event.get('slot')
                if slot in seen:add('duplicate_slot',f"第{round_['number']}{phase}重复槽{slot}")
                seen.add(slot)
                actor=event.get('actor')
                if actor is not None and (type(actor)!=int or not 1<=actor<=12):add('actor_range',str(event))
                expected_roles={'witch_save':{'女巫'},'witch_poison':{'女巫'},'guard':{'守卫'},
                                'seer_check':{'预言家','通灵师'},'mechanical_action':{'机械狼'},
                                'mechanical_day_skill':{'机械狼'}}
                if code=='treasure_master':expected_roles['witch_poison']={'毒师'}
                if (actor is not None and event.get('action') not in {'unknown','unavailable','none'} and
                        slot in expected_roles and roles_by_seat.get(actor) not in expected_roles[slot]):
                    add('slot_actor_role',f"第{round_['number']}{phase} {slot}由{actor}号{roles_by_seat.get(actor)}行动")
                targets=event.get('targets',[])
                if not isinstance(targets,list) or any(type(t)!=int or not 1<=t<=12 for t in targets):add('target_range',str(event))
                if slot=='night_deaths' and event.get('action')=='peaceful' and targets:
                    add('peaceful_with_deaths',f"第{round_['number']}天平安夜仍列死者{targets}")
                if slot in {'witch_save','witch_poison'} and event.get('action') in {'save','poison'}:potions[slot]+=1
    for potion,count in potions.items():
        if count>1:add('potion_reuse',f'{potion}实际使用{count}次')
    ids=[]
    for ballot in voting.get('ballots',[]):
        ids.append(ballot.get('id'));votes=ballot.get('votes',[])
        voters=[v.get('voter') for v in votes]
        if len(voters)!=len(set(voters)):add('duplicate_voter',f"{ballot.get('id')}重叠投票者{voters}")
        if ballot.get('day') is None:add('ballot_day_unknown',ballot.get('id'),'warning')
        for vote in votes:
            if type(vote.get('voter'))!=int or not 1<=vote['voter']<=12:add('vote_voter_range',str(vote))
            if vote.get('target') is not None and (type(vote['target'])!=int or not 1<=vote['target']<=12):add('vote_target_range',str(vote))
    if len(ids)!=len(set(ids)):add('ballot_ids','投票轮ID重复')


def audit(bvids=None, *, checks=('structure', 'evidence'), write_report=True, loaded=None,
          evidence_context=None):
    plan=json.loads((ROOT/'data/reports/S23/S23_逐局复核计划.json').read_text(encoding='utf-8'))
    entries = [e for e in plan['entries'] if e['phase']=='regular' and
               (bvids is None or e['bvid'] in bvids)]
    loaded = loaded if loaded is not None else s23_effective_game.load_effective_games(bvids)
    effective = {g['entry']['bvid']: g for g in loaded['games']}
    errors=[];warnings=[];games=[];source_cache=dict(loaded['source_segments']);proof_count=0
    for original_entry in entries:
        entry = effective.get(original_entry['bvid'], {}).get('entry', original_entry)
        bvid=entry['bvid'];folder=BASE/bvid
        def add(code,detail,severity='error'):
            (errors if severity=='error' else warnings).append({'bvid':bvid,'index':entry['index'],'code':code,'detail':detail})
        required=[folder/name for name in ['dossier.reviewed.json','voting.reviewed.json','ai_review.json']]
        if not all(p.is_file() for p in required):
            add('review_incomplete','尚缺逐局AI输出');continue
        game=effective[bvid]
        dossier,voting,review=game['dossier'],game['voting'],game['review']
        seats, rounds = dossier.get('seats', []), dossier.get('rounds', [])
        if 'structure' in checks:
            check_structure(dossier, voting, add)
        evidence_errors=0
        for proof in evidence_objects(review if evidence_context is None else evidence_context) if 'evidence' in checks else []:
            proof_count+=1
            path=proof.get('source_path') or proof.get('source')
            resolved,path_error=resolve_evidence_path(ROOT,path)
            if path_error:
                add(path_error,path if isinstance(path,str) else str(proof));evidence_errors+=1;continue
            if proof.get('kind')=='video_frame' or resolved.suffix.lower() in {'.png','.jpg','.jpeg'}:continue
            if proof.get('kind')=='audio_asr':
                if bvid not in resolved.as_posix():
                    add('evidence_wrong_source',path);evidence_errors+=1;continue
                errors_for_proof=audio_asr_evidence_errors(ROOT,proof,resolved)
                for code,detail in errors_for_proof:
                    add(code,detail);evidence_errors+=1
                continue
            quote=normalized(proof.get('quote'))
            if not quote:continue
            if resolved.suffix=='.json':
                key=resolved.as_posix()
                if key not in source_cache:
                    try:source_cache[key]=segments(resolved)
                    except (ValueError,KeyError,TypeError):source_cache[key]=[]
                rows=source_cache[key]
                start,end=proof.get('start_ms'),proof.get('end_ms')
                if type(start) not in {int,float} or type(end) not in {int,float}:
                    add('evidence_time_missing',path,'warning');continue
                text=''.join(r['text'] for r in rows if r['end_ms']>=start and r['start_ms']<=end)
                if quote not in normalized(text):
                    add('quote_mismatch',{'source_path':path,'start_ms':start,'end_ms':end,'quote':proof.get('quote')});evidence_errors+=1
        coverage=review.get('coverage',{})
        if 'evidence' in checks and not all(coverage.get(k) is True for k in ['recap_read','voting_checked','bluff_checked','frame_checked']):
            add('coverage_incomplete',coverage,'warning')
        games.append({'index':entry['index'],'bvid':bvid,'known_roles':sum(s.get('role') is not None for s in seats),
                      'named_seats':sum(bool(s.get('name')) for s in seats),'rounds':len(rounds),
                      'ballots':len(voting.get('ballots',[])),'human_questions':len(review.get('human_questions',[])),
                      'source_sha256':entry['source_sha256'],'review_sha256':digest(required[2]),'evidence_errors':evidence_errors})
    result={'season':'S23','audited_at_utc':datetime.now(timezone.utc).isoformat(),'planned':len(entries),
            'mode':'full' if bvids is None else 'partial','selected_checks':list(checks),
            'review_outputs':len(games),'excluded_showmatches':12,'evidence_items':proof_count,
            'errors':errors,'warnings':warnings,'games':games,'formal_database_writes':False}
    if write_report:
        filename='S23_逐局复核校验.json' if bvids is None else 'S23_局部复核校验.json'
        save_json(ROOT/'data/reports/S23'/filename,result)
    return result


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result=audit();print(json.dumps({k:v for k,v in result.items() if k not in {'games','errors','warnings'}},ensure_ascii=False,indent=2))
    print('Errors:',len(result['errors']),'Warnings:',len(result['warnings']))
    for item in result['errors'][:15]:print(json.dumps(item,ensure_ascii=False))
    raise SystemExit(1 if result['errors'] else 0)
