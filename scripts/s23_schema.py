"""Project reviewed observations onto existing fixed slots, retaining all extras."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from game_records import empty_event
from board_config import load_template

ROOT=Path(__file__).resolve().parents[1]
FORMS={'狼人':'机械双刀狼','双刀狼':'机械双刀狼','通灵师':'机械通灵师',
       '女巫':'机械女巫','猎人':'机械猎人','守卫':'机械守卫','平民':'机械平民'}


def normalize_voting(voting,dossier):
    value=deepcopy(voting);notes=[]
    for b in value.get('ballots',[]):
        old=b.get('stage')
        if old in {'skill_revote','skill_rerun','prince_revote'}:b['stage']='revote'
        elif old=='delayed':b['stage']='initial'
        if b.get('stage')!=old:notes.append({'field':f"voting.{b['id']}.stage",'before':old,'after':b['stage'],'basis':'现有阶段枚举：延期竞选仍为初投，技能重投为revote。'})
        if isinstance(b.get('eligible_voters'),list):
            recorded={v['voter'] for v in b['votes']};eligible=set(b['eligible_voters'])
            if recorded<=eligible:
                missing=sorted(eligible-recorded)
                # Never manufacture an entirely absent round from a placeholder.
                if missing and b['votes']:
                    b['votes'] += [{'voter':n,'target':None,'state':'abstained','basis':'按既有用户口径：本轮票权明确但未播报投向，默认弃票'} for n in missing]
                    notes.append({'field':f"voting.{b['id']}.votes",'before':missing,'after':'默认弃票','basis':'已确认票轮及票权；沿用S22用户确认的未报投向默认弃票规则。'})
                unrecorded=sorted(eligible-{v['voter'] for v in b['votes']})
                b['unrecorded_voters']=unrecorded;b['status']='partial' if unrecorded else 'complete'
    for day in value.get('days',[]):
        n=day['day'];round_=next((r for r in dossier['rounds'] if r['number']==n),{'day':[]})
        boom=any(e['action']=='self_destruct' for e in round_['day'])
        for kind,valid in [('sheriff',{'recorded','unknown','deferred','badge_lost','not_applicable'}),
                           ('exile',{'recorded','unknown','interrupted_self_destruct'})]:
            old=day[kind]
            if old in valid:continue
            if any(b['day']==n and b['kind']==kind for b in value.get('ballots',[])):day[kind]='recorded'
            elif kind=='sheriff':
                day[kind]=('deferred' if n==1 else 'badge_lost') if ('interrupt' in old or 'defer' in old) else 'badge_lost' if old in {'lost','forfeited'} else 'not_applicable' if old=='not_held' else 'unknown'
            else:day[kind]='interrupted_self_destruct' if boom else 'unknown'
            notes.append({'field':f'voting.days[{n}].{kind}','before':old,'after':day[kind],'basis':'仅规范每日覆盖枚举；具体未投原因与终局仍保留在原AI档案、事件及拍刀记录中。'})
    return value,notes


def normalize(dossier,voting=None):
    d=deepcopy(dossier);notes=[];extra=[];models={}
    if 'voting' in d:
        embedded=d.pop('voting')
        notes.append({'field':'voting','before':embedded,'after':None,'basis':'投票使用同目录独立voting.candidate.json，移出对局固定字段；原AI档案保留。'})
    by_seat={s['seat']:s for s in d['seats']}
    for s in d['seats']:
        if s['role']=='混血儿' and s.get('learning_target'):
            models[s['seat']]=s['learning_target']
        if s['role']!='机械狼' and (s.get('learning_target') is not None or s.get('learned_role') is not None):
            notes.append({'field':f"seats[{s['seat']}].learning",'before':[s.get('learning_target'),s.get('learned_role')],
                          'after':[None,None],'basis':'学习字段仅属于机械狼；混血榜样保留在mixed_blood_model事件及页面映射。'})
            s['learning_target']=None;s['learned_role']=None
        if s['role']=='机械狼' and s.get('learned_role') in FORMS:
            old=s['learned_role'];s['learned_role']=FORMS[old]
            notes.append({'field':f"seats[{s['seat']}].learned_role",'before':old,'after':s['learned_role'],'basis':'现有机械狼形态的规范名称，底牌和模仿目标不变。'})
    # These S23-only boards already store explicit observations. The S22 slot
    # projection does not understand their actions (for example nine_tail_mark)
    # and would clear valid targets after a canonical template is added.
    # Their formal adapter owns template completion, as before consolidation.
    if d['board'] in {'qingqiu_night', 'magic_duel'}:
        return d,extra,notes,models
    try:
        board=load_template(d['board'],ROOT)
    except FileNotFoundError:
        return d,extra,notes,models
    event_fields=tuple(empty_event('example'))
    aliases={'magician_action':'magician_exchange','trickster_action':'guile_exchange',
             'prince_reveal':'sequential_prince_skill','mechanical_poison':'mechanical_action'}
    for r in d['rounds']:
        for ph in ['night','day']:
            specifications=board[ph+'_slots'];valid={s['code']:s for s in specifications};events={}
            for original in r[ph]:
                e=deepcopy(original);old=deepcopy(e);e['slot']=aliases.get(e['slot'],e['slot'])
                slot=e['slot'];action=e['action']
                if slot=='night_deaths' and action in {'death','deaths','double_death'}:e['action']='die'
                if slot=='badge' and action in {'lost','destroy'}:e['action']='none'
                if slot=='sheriff_result' and action in {'lost','badge_lost'}:e['action']='none';e['targets']=[]
                if slot=='sheriff_result' and action in {'postponed','interrupted'}:
                    e['action']='deferred' if r['number']==1 else 'none';e['targets']=[]
                if slot=='sheriff_candidates' and action=='candidates':e['action']='register'
                if slot=='sequential_prince_skill' and action=='activate':e['action']='reveal'
                if slot=='extra_speech' and action=='speech':e['action']='speak'
                if slot=='exile_vote' and action=='unavailable':e['action']='not_held'
                if slot=='exile_result' and action in {'unavailable','tie'}:
                    e['action']='none';e['targets']=[]
                if slot=='masquerade_mask' and action=='assign_mask':e['action']='give_mask'
                if slot=='dancer_dance' and action=='choose':e['action']='dance'
                if slot=='dance_resolution' and action in {'eliminate','die'}:e['action']='minority_dies'
                if slot=='dance_resolution' and action=='none':e['action']='no_death'
                if slot in {'magician_exchange','guile_exchange'} and action in {'exchange_numbers','exchange_exile_result'}:e['action']='exchange'
                if slot in {'mixed_blood_alignment','mixed_blood_victory','treasure_alignment'} and action in {'align','victory'}:
                    faction=by_seat.get(e.get('actor'),{}).get('faction')
                    if faction in {'good','werewolf'}:e['action']='wolf' if faction=='werewolf' else 'good';e['targets']=[]
                if slot=='mechanical_action' and action=='learn' and e.get('result') in FORMS:e['result']=FORMS[e['result']]
                if slot=='treasure_choice' and e['action']=='choose' and isinstance(e.get('result'),str):
                    role=e['result'].removesuffix('身份').removesuffix('牌')
                    if role in board.get('role_pool',{}):e['result']=role
                if slot=='mixed_blood_model' and e['action']=='choose' and e['targets'] and e.get('actor'):
                    models[e['actor']]=e['targets'][0]
                # Voting sidecars hold the authoritative independent rounds.
                # Legacy embedded votes use a different shape and are redundant.
                if e.get('votes'):e['votes']=[]
                if slot in {'sheriff_vote','exile_vote','second_exile_vote'} and e['action']=='vote':
                    kind='sheriff' if slot=='sheriff_vote' else 'exile'
                    ballots=[b for b in (voting or {}).get('ballots',[]) if b['day']==r['number'] and b['kind']==kind]
                    if slot=='second_exile_vote':ballots=[b for b in ballots if b['stage'] in {'revote','skill_revote','prince_revote'}]
                    elif slot=='exile_vote':ballots=[b for b in ballots if b['stage'] not in {'revote','skill_revote','prince_revote'}]
                    e['votes']=[{'round':n,'voter':v['voter'],'target':v.get('target'),'abstained':v.get('state')=='abstained'}
                                for n,b in enumerate(ballots,1) for v in b['votes'] if v.get('state') in {'cast','abstained'}]
                    if not e['votes']:
                        extra.append({'round':r['number'],'phase':ph,'event':old,'reason':'已发生投票但该固定槽无可编码逐票，独立投票档案及人工问题另存。'})
                        e['action']='unknown'
                if e['action'] in {'unknown','unavailable','pass','none','not_held'} and e.get('targets'):
                    e['targets']=[]
                targeted={'guard':{'guard'},'wolf_attack':{'attack'},'witch_save':{'save'},'witch_poison':{'poison'},
                          'seer_check':{'check'},'mechanical_action':{'learn','attack','guard','poison','check'},
                          'mechanical_day_skill':{'shoot'},'hunter_shot':{'shoot'},'wolf_king_shot':{'shoot'},
                          'dreamer_action':{'dream'},'treasure_card_skill':{'attack','guard','poison','check','dream','shoot'},
                          'treasure_extra_attack':{'attack'},'sheriff_result':{'elected'},'exile_result':{'exile'},
                          'second_exile_result':{'exile'},'badge':{'transfer','hold'},'mixed_blood_model':{'choose'},
                          'magician_exchange':{'exchange'},'guile_exchange':{'exchange','invalid_exchange'},
                          'masquerade_verify':{'verify'},'masquerade_mask':{'give_mask'},'dancer_dance':{'dance'},
                          'dance_resolution':{'minority_dies'},'masked_delayed_death':{'die_after_speech'},
                          'sheriff_candidates':{'register'},'night_deaths':{'die'}}
                if e.get('targets') and e['action'] not in targeted.get(slot,set()):e['targets']=[]
                if slot not in valid or e['action'] not in valid[slot]['actions']:
                    extra.append({'round':r['number'],'phase':ph,'event':old,'reason':'现有固定槽未覆盖的明确观察；保留供人工复核，未装作普通技能。'})
                    continue
                e={k:e.get(k,deepcopy(empty_event(slot)[k])) for k in event_fields}
                if slot in events:
                    extra.append({'round':r['number'],'phase':ph,'event':old,'reason':'重复固定槽保留原观察，不能无声覆盖。'})
                    continue
                events[slot]=e
                if old!=e:notes.append({'field':f"rounds[{r['number']}].{ph}.{slot}",'before':old,'after':e,'basis':'动作同义词、固定字段或独立投票格式规范化；原AI记录不改写。'})
            result=[]
            for spec in specifications:
                e=events.get(spec['code'])
                if e is None:
                    actor=next((s['seat'] for s in d['seats'] if s['role']==spec['actor_role']),None)
                    e=empty_event(spec['code'],actor)
                result.append(e)
            r[ph]=result
    return d,extra,notes,models
