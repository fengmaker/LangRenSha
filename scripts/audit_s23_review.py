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

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/extractions/S23/game_reviews'
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


def audit():
    plan=json.loads((ROOT/'data/reports/S23_逐局复核计划.json').read_text(encoding='utf-8'))
    errors=[];warnings=[];games=[];source_cache={};proof_count=0
    for entry in plan['entries']:
        bvid=entry['bvid'];folder=BASE/bvid
        def add(code,detail,severity='error'):
            (errors if severity=='error' else warnings).append({'bvid':bvid,'index':entry['index'],'code':code,'detail':detail})
        required=[folder/name for name in ['dossier.reviewed.json','voting.reviewed.json','ai_review.json']]
        if not all(p.is_file() for p in required):
            add('review_incomplete','尚缺逐局AI输出');continue
        dossier,voting,review=[json.loads(p.read_text(encoding='utf-8')) for p in required]
        primary_path=folder/'primary_review.json'
        primary=json.loads(primary_path.read_text(encoding='utf-8')) if primary_path.exists() else {}
        if primary and (primary.get('bvid')!=bvid or primary.get('source_sha256')!=entry['source_sha256']):
            add('primary_source_binding','主审补正与本局来源绑定不一致')
        if review.get('bvid')!=bvid or review.get('source_sha256')!=entry['source_sha256']:
            add('source_binding','AI复核与本局源文件绑定不一致')
        if digest(ROOT/entry['source_path'])!=entry['source_sha256']:
            add('source_changed','完整转写字节发生变化')
        if dossier.get('season')!='S23' or dossier.get('phase')!='regular':add('scope','非S23正赛')
        if bvid not in dossier.get('slug',''):add('slug_source','对局slug与BV不一致')
        seats=dossier.get('seats',[])
        roles_by_seat={s.get('seat'):s.get('role') for s in seats}
        if sorted(s.get('seat') for s in seats)!=list(range(1,13)):add('seat_set','座位必须为1到12各一次')
        roles=Counter(s.get('role') for s in seats if s.get('role'))
        code=dossier.get('board')
        rules=NEW_COUNTS.get(code)
        template=ROOT/f'config/board_templates/{code}.json'
        if template.is_file():
            board=json.loads(template.read_text(encoding='utf-8'))
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
        evidence_errors=0
        for proof in evidence_objects([review,primary]):
            proof_count+=1
            path=proof.get('source_path') or proof.get('source')
            if not isinstance(path,str):add('evidence_path',str(proof));evidence_errors+=1;continue
            resolved=(ROOT/path).resolve()
            if not resolved.is_relative_to((ROOT/'data').resolve()) and not resolved.is_relative_to((ROOT/'config').resolve()) and not resolved.is_relative_to((ROOT/'docs').resolve()):
                add('evidence_outside_project',path);evidence_errors+=1;continue
            if not resolved.is_file():add('evidence_missing',path);evidence_errors+=1;continue
            if proof.get('kind')=='video_frame' or resolved.suffix.lower() in {'.png','.jpg','.jpeg'}:continue
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
        if not all(coverage.get(k) is True for k in ['recap_read','voting_checked','bluff_checked','frame_checked']):
            add('coverage_incomplete',coverage,'warning')
        games.append({'index':entry['index'],'bvid':bvid,'known_roles':sum(s.get('role') is not None for s in seats),
                      'named_seats':sum(bool(s.get('name')) for s in seats),'rounds':len(rounds),
                      'ballots':len(voting.get('ballots',[])),'human_questions':len(review.get('human_questions',[])),
                      'source_sha256':entry['source_sha256'],'review_sha256':digest(required[2]),'evidence_errors':evidence_errors})
    result={'season':'S23','audited_at_utc':datetime.now(timezone.utc).isoformat(),'planned':75,
            'review_outputs':len(games),'excluded_showmatches':12,'evidence_items':proof_count,
            'errors':errors,'warnings':warnings,'games':games,'formal_database_writes':False}
    save_json(ROOT/'data/reports/S23_逐局复核校验.json',result)
    return result


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result=audit();print(json.dumps({k:v for k,v in result.items() if k not in {'games','errors','warnings'}},ensure_ascii=False,indent=2))
    print('Errors:',len(result['errors']),'Warnings:',len(result['warnings']))
    for item in result['errors'][:15]:print(json.dumps(item,ensure_ascii=False))
    raise SystemExit(1 if result['errors'] else 0)
