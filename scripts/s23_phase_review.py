"""Attach explicit per-phase gaps and mixed-blood vote arithmetic to S23 reviews.

This projection never changes original transcripts or declares an early winner.
"""
from __future__ import annotations

from copy import deepcopy
import re

try:
    from .game_time import phase_label
except ImportError:
    from game_time import phase_label

WOLVES={'狼人','机械狼','狼王','黑狼王','假面','诡术师','典狱长','盗宝大师','九尾狐','狼术师'}
NIGHT_CRITICAL={'guard','wolf_attack','witch_save','witch_poison','seer_check',
                'mechanical_action','mechanical_knife_status','mixed_blood_model',
                'treasure_choice','treasure_card_skill','treasure_extra_attack',
                'dreamer_action','masquerade_verify','masquerade_mask','dancer_dance',
                'magician_exchange','guile_exchange','sorcerer_exchange',
                'fox_mark','nine_tail_mark','baize_clear','baize_purge'}
DAY_CRITICAL={'night_deaths','exile_result','second_exile_result'}
GUN_STATE={'hunter_state','wolf_king_state','puppet_hunter_eligibility'}
GUN_ACTION={'hunter_shot','wolf_king_shot','mechanical_day_skill'}
LABELS={'night_deaths':'夜间死亡结算','exile_result':'放逐结果','second_exile_result':'技能重投结果',
        'guard':'守卫目标','wolf_attack':'狼刀目标','witch_save':'女巫解药','witch_poison':'女巫毒药',
        'seer_check':'查验目标或反馈','mechanical_action':'机械狼行动','mechanical_knife_status':'机械狼接刀状态',
        'mixed_blood_model':'混血儿榜样','hunter_state':'猎人开枪资格','hunter_shot':'猎人开枪结算',
        'wolf_king_state':'狼王开枪资格','wolf_king_shot':'狼王开枪结算',
        'mechanical_day_skill':'机械猎人白天技能','registrations':'最初上警与警下名单',
        'sheriff_result':'警长竞选结果','vote_control':'狼混绑票票数',
        'masquerade_verify':'假面验证','masquerade_mask':'假面给予面具','dancer_dance':'舞池选择',
        'treasure_choice':'盗宝选牌','treasure_card_skill':'盗宝所选技能','treasure_extra_attack':'盗宝接刀',
        'dreamer_action':'摄梦目标','magician_exchange':'魔术师交换','guile_exchange':'诡术师交换',
        'sorcerer_exchange':'狼术师交换'}


def _unknown_value(value):
    return value is None or value=='' or isinstance(value,str) and bool(re.search(r'unknown|未知|待核|未核清|未明确|不明',value,re.I))


def vote_totals(seats,living,badge_holder=None,badge_known=True,half_vote=True):
    """Use victory faction, including a wolf-aligned mixed-blood seat."""
    indexed={s['seat']:s for s in seats}
    if living is None or any(n not in indexed or indexed[n].get('faction') not in {'good','werewolf'} for n in living):
        return {'werewolf_votes':None,'good_votes':None,'controls_vote':None,'reason':'存活名单或个人胜利阵营尚未核清'}
    wolf=[n for n in living if indexed[n]['faction']=='werewolf']
    good=[n for n in living if indexed[n]['faction']=='good']
    w,g=len(wolf),len(good)
    out={'werewolf_seats':wolf,'good_seats':good,'werewolf_count':w,'good_count':g,
         'badge_holder':badge_holder,'badge_known':badge_known}
    if not badge_known:
        # Unknown badge ownership cannot be silently treated as no badge.
        possible=[w>=g,w+.5>=g,w>=g+.5] if half_vote else [w>=g]
        controls=possible[0] if len(set(possible))==1 else None
        return {**out,'werewolf_votes':None,'good_votes':None,'controls_vote':controls,
                'reason':'警徽归属待核，不能把未知警徽按无徽处理'}
    if half_vote and badge_holder in wolf:w+=.5
    if half_vote and badge_holder in good:g+=.5
    return {**out,'werewolf_votes':w,'good_votes':g,'controls_vote':w>=g,
            'reason':'按已核存活玩家的可用票权及个人胜利阵营计算理论票力；狼混计入狼方，警长额外半票计入持徽者阵营'}


def _event(round_,slot):
    return next((e for ph in ['day','night'] for e in round_.get(ph,[]) if e.get('slot')==slot),None)


def _field_key(value):
    value=str(value or '')
    if value.endswith('seer_check.result'):return 'seer_check.result'
    parts=re.split(r'[.\[\]]+',value)
    return next((part for part in parts if part in NIGHT_CRITICAL|DAY_CRITICAL|GUN_STATE|GUN_ACTION),value)


def _input_note(dossier,number):
    r=next((r for r in dossier['rounds'] if r['number']==number),{'night':[]})
    inputs=[f"{e['slot']}={e['action']}，目标{e.get('targets',[])}" for e in r['night']
            if e.get('slot') in {'wolf_attack','witch_save','witch_poison','guard','mechanical_action'}
            and e.get('action') not in {'unknown','unavailable'}]
    return '；'.join(inputs)


def enrich(game):
    d,v,a=game['dossier'],game['voting'],game['review']
    flow=game.get('flow',{})
    rounds=d.get('rounds',[])
    presented=game['presentation']['rounds']
    findings=deepcopy(a.get('phase_findings',[]))
    for f in findings:
        if type(f.get('round')) is int and f.get('phase') in {'night','day'}:
            # A night death is announced in the following day slot. Field
            # anchors are explicit; recap wording such as "N2 night death"
            # must not move that announcement back into the action phase.
            field_phase=re.search(r'rounds\[\d+\]\.(night|day)\.',str(f.get('field','')))
            if field_phase:f['phase']=field_phase[1]
            f['phase_label']=phase_label(f['round'],f['phase'])
            title=str(f.get('title') or '')
            f['title']=re.sub(r'^(?:D\d+夜|N\d+(?:夜)?|第\d+夜)',f['phase_label']+' · ',title)
    signatures={(f.get('round'),f.get('phase'),_field_key(f.get('field'))) for f in findings if f.get('status')=='unresolved'}

    def add(number,phase,field,title,reason,status='unresolved',conclusion=None):
        key=(number,phase,_field_key(field))
        if key in signatures:return
        signatures.add(key)
        findings.append({'id':f'coverage-{number}-{phase}-{field}','round':number,'phase':phase,
                         'phase_label':phase_label(number,phase),'status':status,'field':field,
                         'title':title,'conclusion':conclusion or reason,'reasoning':reason,'evidence':[],
                         'origin':'phase_coverage_check','source_sha256':game['entry']['source_sha256']})

    # Replay already distinguishes recorded deaths from uniquely deducible
    # settlements.  Show the latter with their inputs instead of "unknown".
    for item in flow.get('deductions',[]):
        if item.get('slot')!='night_deaths':continue
        number=item['round'];pr=next((r for r in presented if r['number']==number),None)
        if pr is None:continue
        ev=next((e for e in pr['day'] if e['slot']=='night_deaths'),None)
        if ev is None:
            ev={'slot':'night_deaths','actor':None,'targets':[]};pr['day'].append(ev)
        if ev.get('action') not in {None,'unknown'}:continue
        ev.update(action='die' if item['targets'] else 'peaceful',targets=item['targets'],inferred=True,
                  inference_note='结合本夜刀口、药量和此前出局记录唯一推导；'+_input_note(d,number))
        add(number,'day','night_deaths','夜间死亡已作因果推导',ev['inference_note'],'inferred',
            ('本日夜死：'+ '、'.join(map(str,item['targets']))+'号') if item['targets'] else '本夜推导为平安夜')

    # Reproject a copy with those explicit deductions so a confirmed death
    # also reaches later role availability and poisoned-hunter qualification.
    if any(x.get('slot')=='night_deaths' for x in flow.get('deductions',[])) and d['board'] not in {'qingqiu_night','magic_duel'}:
        from website.api.game_presentation import build_game_presentation
        projected=deepcopy(d)
        for rr in projected['rounds']:
            shown=next((r for r in presented if r['number']==rr['number']),{})
            death=next((e for e in shown.get('day',[]) if e.get('slot')=='night_deaths' and e.get('inferred')),None)
            if death:
                rr['day']=[e for e in rr['day'] if e.get('slot')!='night_deaths']+[deepcopy(death)]
        game['presentation']=build_game_presentation({**projected,'voting':v})
        presented=game['presentation']['rounds']

    prior_dead=set()
    mechanical=next((s for s in d['seats'] if s.get('role')=='机械狼'),{})
    ordinary_wolves={s['seat'] for s in d['seats'] if s.get('role') in WOLVES and s.get('role')!='机械狼'}
    learns=[(r['number'],ev) for r in rounds for ev in r.get('night',[]) if ev.get('slot')=='mechanical_action' and ev.get('action')=='learn']
    learn_night=learns[0][0] if len(learns)==1 else None
    mechanical_form=mechanical.get('learned_role')
    mech_poison_nights=[r['number'] for r in rounds for ev in r.get('night',[]) if ev.get('slot')=='mechanical_action' and ev.get('action')=='poison']
    derived_states=[]
    inferred_absences={}
    spent_potions=set()
    witch=next((s['seat'] for s in d['seats'] if s.get('role')=='女巫'),None)
    for raw in rounds:
        n=raw['number']
        pr=next((r for r in presented if r['number']==n),raw)
        row=next((r for r in flow.get('rounds',[]) if r['day']==n),{})
        night_dead=set(row.get('night_deaths') or [])
        raw_death=_event(raw,'night_deaths')
        if raw_death and raw_death.get('action')=='die':night_dead.update(raw_death.get('targets',[]))
        expelled={t for e in raw.get('day',[]) if e.get('slot') in {'exile_result','second_exile_result'}
                  and e.get('action')=='exile' for t in e.get('targets',[])}
        prev=next((r for r in flow.get('rounds',[]) if r['day']==n-1),{})
        known_before=set(range(1,13)) if n==1 else set(prev['living_after_day']) if prev.get('living_after_day') is not None else None
        carrying=True if ordinary_wolves and ordinary_wolves<=prior_dead else False if known_before is not None and ordinary_wolves&known_before else None
        for ev in raw.get('night',[]):
            if ev.get('actor') in prior_dead:
                inferred_absences[(n,'night',ev['slot'])]='行动者已在此前日夜出局，本夜不再适用。'
        for ev in raw.get('day',[]):
            if ev.get('slot') in GUN_STATE|GUN_ACTION and ev.get('actor') in prior_dead:
                inferred_absences[(n,'day',ev['slot'])]='行动者已在此前日夜出局，不会在本日再次触发技能。'

        def infer_event(ev,action,note,result=None):
            ev.update(action=action,inferred=True,inference_note=note)
            if result is not None:ev['result']=result
            derived_states.append({'round':n,'phase':'night','slot':ev['slot'],'action':action,'basis':note})

        # In this board a live wolf-knife target survives only through the
        # ordinary witch's antidote. No guard, mask, exchange or immunity can
        # create the same observation. Use a recorded final death list only.
        if d['board']=='mixed_blood' and raw_death and raw_death.get('action') in {'die','peaceful'}:
            attack=_event(raw,'wolf_attack')
            save=next((e for e in pr['night'] if e.get('slot')=='witch_save'),None)
            if (attack and attack.get('action')=='attack' and len(attack.get('targets',[]))==1
                    and attack['targets'][0] not in prior_dead|night_dead
                    and known_before is not None and attack['targets'][0] in known_before
                    and witch is not None and witch not in prior_dead
                    and attack['targets'][0]!=witch and 'witch_save' not in spent_potions
                    and save and save.get('action') in {None,'unknown'} and not save.get('targets')):
                poison=_event(raw,'witch_poison')
                if not poison or poison.get('action')!='poison':
                    save.update(actor=witch,targets=attack['targets'])
                    infer_event(save,'save','本版没有守卫或转移刀口的技能；已核狼刀目标当夜未死且此前存活，唯一对应女巫解救。')
                    add(n,'night','witch_save','女巫解救由刀口与最终夜死互证',
                        save['inference_note'],'inferred',f"女巫救起{attack['targets'][0]}号。")
        used_now={e['slot'] for e in pr['night'] if e.get('slot') in {'witch_save','witch_poison'} and e.get('action') in {'save','poison'}}
        for ev in pr.get('night',[]):
            if ev.get('action') not in {None,'unknown'}:continue
            if any(ev.get(k) for k in ['targets','votes','effects','availability','result']):continue
            actor=ev.get('actor');slot=ev.get('slot')
            if slot in {'witch_save','witch_poison'} and (slot in spent_potions or used_now- {slot}):
                infer_event(ev,'unavailable','本瓶药已在此前使用。' if slot in spent_potions else '同一普通女巫每夜只能用一瓶药；本夜已使用另一瓶。');continue
            if actor in prior_dead:
                infer_event(ev,'unavailable','该行动者已在此前日夜出局，本夜不再适用。');continue
            if slot=='mechanical_knife_status' and carrying is not None:
                infer_event(ev,'carrying' if carrying else 'not_carrying',
                            '此前普通狼人已全部出局，机械狼接普通狼刀。' if carrying else '本夜开始仍有普通狼人存活，机械狼尚未接普通狼刀。');continue
            if slot=='mechanical_action' and learn_night is not None:
                if n<learn_night:
                    infer_event(ev,'pass',f'全局仅能学习一次，已明确在{phase_label(learn_night,"night")}学习，因此此前尚未发动学习。');continue
                if n>learn_night and mechanical_form in {'机械平民','机械猎人'}:
                    infer_event(ev,'unavailable',f'已学习{mechanical_form}；该形态没有额外夜间技能，普通狼刀与白天开枪另列。');continue
                if n>learn_night and mechanical_form=='机械双刀狼' and carrying is False:
                    infer_event(ev,'unavailable','机械双刀技能刀须学习后且接刀才解锁；本夜仍有普通狼人，尚未接刀。');continue
                if n>learn_night and mechanical_form=='机械女巫':
                    if any(x<n for x in mech_poison_nights):
                        infer_event(ev,'unavailable','复制的唯一毒药已在前夜用尽。');continue
                    if len(mech_poison_nights)==1 and n<mech_poison_nights[0]:
                        infer_event(ev,'pass',f'复制毒药只一瓶，已明确{phase_label(mech_poison_nights[0],"night")}才用毒，本夜保留毒药。');continue
            if slot=='witch_save':
                attack=_event(raw,'wolf_attack')
                if attack and attack.get('action')=='attack' and actor in attack.get('targets',[]):
                    infer_event(ev,'unavailable','普通女巫不能自救；本夜狼刀目标为女巫自己。');continue
        for ev in pr.get('day',[]):
            if (ev.get('slot')=='mechanical_day_skill' and ev.get('action') in {None,'unknown'}
                    and mechanical_form and mechanical_form!='机械猎人'):
                note=f'本局机械狼学习形态为{mechanical_form}，没有机械猎人的白天开枪技能。'
                ev.update(action='unavailable',inferred=True,inference_note=note)
                derived_states.append({'round':n,'phase':'day','slot':ev['slot'],'action':'unavailable','basis':note})
        if d['board'] in {'mixed_blood','masquerade'}:
            seats={s['seat']:s for s in d['seats']}
            for ev in pr.get('night',[]):
                targets=ev.get('targets',[])
                if ev.get('slot')=='seer_check' and ev.get('action')=='check' and not ev.get('result') and len(targets)==1 and targets[0] in seats:
                    target=seats[targets[0]]
                    result='狼人' if target.get('role') in WOLVES else '好人'
                    note='本版无查验目标交换；预言家验狼人反馈狼人，混血儿始终反馈好人，不能把狼混的胜利阵营当查验反馈。'
                    infer_event(ev,'check',note,result)
        for ph in ['night','day']:
            terminal=flow.get('terminal')
            if terminal and (n>terminal['round'] or n==terminal['round'] and terminal['phase']=='night' and ph=='day'):
                continue
            for ev in pr.get(ph,[]):
                slot=ev.get('slot');action=ev.get('action')
                important=slot in (NIGHT_CRITICAL if ph=='night' else DAY_CRITICAL)
                if slot in GUN_STATE|GUN_ACTION:
                    important=ev.get('actor') in night_dead|expelled
                if not important:continue
                if action in {None,'unknown'}:
                    label=LABELS.get(slot,slot)
                    add(n,ph,slot,label+'待核实','当前候选未明确此项；须结合相邻日夜、法官播报与视频继续核实。不能将未知当作空过或无事发生。')
                elif slot=='seer_check' and action=='check' and _unknown_value(ev.get('result')):
                    add(n,ph,slot+'.result','查验反馈待核实','已记查验行动，但本夜反馈仍未核清；实际底牌不能直接代替交换、学习等作用后的查验反馈。')
                required={'guard':{'guard'},'wolf_attack':{'attack'},'witch_save':{'save'},'witch_poison':{'poison'},
                          'seer_check':{'check'},'mechanical_action':{'learn','guard','poison','attack','check'},
                          'mixed_blood_model':{'choose'},'dreamer_action':{'dream'},
                          'masquerade_verify':{'verify'},'masquerade_mask':{'give_mask'},'dancer_dance':{'dance'},
                          'magician_exchange':{'exchange'},'guile_exchange':{'exchange'},'sorcerer_exchange':{'exchange'}}
                if action in required.get(slot,set()) and not ev.get('targets'):
                    add(n,ph,slot+'.targets',LABELS.get(slot,slot)+'的目标待核实','行动类型已记录，但目标仍缺失；须结合当夜结算和后续信息继续定位。')
        if not raw_death and not night_dead and not any(x.get('round')==n and x.get('slot')=='night_deaths' for x in flow.get('deductions',[])):
            add(n,'day','night_deaths','本日夜死公布待核实','当前档案缺少明确夜死或平安夜结果，需用法官公布和后续存活/投票交叉核对。')
        prior_dead.update(night_dead|expelled)
        spent_potions.update(used_now)
        for ev in raw.get('day',[]):
            if ev.get('action')=='self_destruct' and ev.get('actor'):prior_dead.add(ev['actor'])
            if ev.get('action') in {'shoot','die_after_speech','suicide'}:prior_dead.update(ev.get('targets',[]))

    if not v.get('registrations'):
        add(1,'day','registrations','最初上警与警下名单待核实','当前候选未保存完整初始报名；不能把退水后候选池的补集当成警下名单。')
    for b in v.get('ballots',[]):
        n=b.get('day')
        if type(n) is not int:continue
        if b.get('eligible_voters') is None or b.get('status')=='partial':
            add(n,'day','ballot.'+b['id'],('警徽票' if b['kind']=='sheriff' else '放逐票')+'轮次资料待核实',
                '本轮票权或逐人记录仍不完整；已知票权未报投向可按既定口径默认弃票，未知票权和整轮缺失不能自动补造。')
    for rr in rounds:
        n=rr['number'];exile=_event(rr,'exile_result')
        recorded=any(x.get('day')==n and x.get('kind')=='exile' for x in v.get('ballots',[]))
        day_status=next((x.get('exile') for x in v.get('days',[]) if x['day']==n),None)
        if not recorded and ((exile and exile.get('action')=='exile') or day_status=='recorded'):
            add(n,'day','ballot.missing','已发生的放逐票整轮待补录','已有放逐结果或投票已发生标记，但当前未保存本日逐人票型；应核对原文和视频补齐，不能把整轮自动记弃票。')
    for item in flow.get('issues',[]):
        n=item.get('day')
        if type(n) is int:add(n,'day','flow.'+item['code'],'日序或终局推导有冲突',item['reason'])

    # A newly proved death/resource state also resolves an older question
    # about that actor's missing target. Keep its original wording as history.
    for f in findings:
        if f.get('status')!='unresolved' or f.get('origin')=='human_question':continue
        key=_field_key(f.get('field'))
        if key not in NIGHT_CRITICAL|GUN_STATE|GUN_ACTION:continue
        rr=next((r for r in presented if r['number']==f.get('round')),None)
        ev=next((e for e in (rr or {}).get(f.get('phase'),[]) if e.get('slot')==key),None)
        absent=inferred_absences.get((f.get('round'),f.get('phase'),key))
        if absent or ev and ev.get('inferred') and ev.get('action')=='unavailable':
            f.update(status='inferred',previous_question=f.get('conclusion') or f.get('title'),
                     title=LABELS.get(key,key)+'已由前序状态排除',
                     conclusion='本轮不适用，无须补行动目标。',reasoning=absent or ev.get('inference_note'))

    # Human questions keep their original ids, but gain a phase anchor too.
    for q in a.get('human_questions',[]):
        n=q.get('round') or q.get('day')
        if type(n) is not int:
            m=re.search(r'(?:day|round|D|第)[\[.( ]*(\d+)',q.get('field',''),re.I)
            n=int(m[1]) if m else 1
        ph=q.get('phase') or ('night' if '.night' in q.get('field','') else 'day')
        q.update(round=n,phase=ph,phase_label=phase_label(n,ph))
        if not any(f.get('question_id')==q['id'] for f in findings):
            findings.append({'id':'question-'+q['id'],'question_id':q['id'],'round':n,'phase':ph,
                             'phase_label':phase_label(n,ph),'status':'unresolved','field':q.get('field'),
                             'title':q['question'],'conclusion':q.get('reason',''),'reasoning':q.get('reason',''),
                             'evidence':q.get('evidence',[]),'origin':'human_question'})

    wolf_mix=any(s.get('role')=='混血儿' and s.get('faction')=='werewolf' for s in d['seats'])
    control={'applicable':d['board']=='mixed_blood' and wolf_mix,'phases':[],
             'rule':'狼混按个人胜利阵营计入狼人方；比较双方可用票数，狼人方大于等于好人方构成绑票。人数相等时必须核对警徽，持徽者阵营计额外半票。',
             'rule_status':'user_confirmed','source_path':'data/extractions/S23/用户确认_20261026_日夜待核与绑票.txt'}
    if control['applicable']:
        holder=None;badge_known=False
        for raw in rounds:
            n=raw['number'];row=next((x for x in flow.get('rounds',[]) if x['day']==n),{})
            terminal=flow.get('terminal')
            if terminal and (n>terminal['round'] or n==terminal['round'] and terminal['phase']=='night'):continue
            living=row.get('living_before_vote')
            ordinary=[b for b in v.get('ballots',[]) if b.get('day')==n and b.get('kind')=='exile' and b.get('stage')=='initial']
            actual_ballots=[b for b in v.get('ballots',[]) if b.get('day')==n and b.get('kind')=='exile']
            exile_status=next((x.get('exile') for x in v.get('days',[]) if x['day']==n),None)
            basis='night_deaths_and_previous_departures'
            if living is None and ordinary and ordinary[0].get('eligible_voters') is not None:
                living=ordinary[0]['eligible_voters'];basis='recorded_initial_exile_electorate'
            exile=_event(raw,'exile_result');out=set(exile.get('targets',[])) if exile and exile.get('action')=='exile' else set()
            old_holder=holder
            statuses={x['sheriff'] for x in v.get('days',[]) if x['day']==n}
            if statuses & {'badge_lost','deferred'}:holder=None;badge_known=True
            elected=_event(raw,'sheriff_result')
            if elected:
                if elected.get('action')=='elected' and len(elected.get('targets',[]))==1:holder=elected['targets'][0];badge_known=True
                elif elected.get('action') in {'none','deferred','badge_lost'}:holder=None;badge_known=True
            transfers=[ev for ev in raw.get('day',[]) if ev.get('slot')=='badge']
            after=[]
            for ev in transfers:
                if (ev.get('actor') in out or ev.get('actor') is None and old_holder in out):
                    after.append(ev)
                elif ev.get('action') in {'none','badge_lost','destroy','lost'}:holder=None;badge_known=True
                elif ev.get('action') in {'hold','transfer'} and len(ev.get('targets',[]))==1:
                    holder=ev['targets'][0];badge_known=True
            # A dead holder without a recorded transfer does not become "no badge".
            if living is not None and holder is not None and holder not in living:holder=None;badge_known=False
            tally=vote_totals(d['seats'],living,holder,badge_known)
            control['phases'].append({'round':n,'phase':'day','phase_label':phase_label(n,'day'),
                                      'living':living,'basis':basis,'stage':'before_exile' if ordinary else 'day_start',
                                      'calculation_kind':'potential_vote_power','actual_ballot_exists':bool(actual_ballots),
                                      'exile_status':exile_status,**tally})
            if tally['controls_vote'] is None:
                add(n,'day','vote_control','本日狼混绑票票数待核实',tally['reason'])
            for ev in after:
                if ev.get('action') in {'none','badge_lost','destroy','lost'}:holder=None;badge_known=True
                elif ev.get('action') in {'hold','transfer'} and len(ev.get('targets',[]))==1:
                    holder=ev['targets'][0];badge_known=True
    # Announced vote-control victory is separate from a calculated condition.
    declared=[]
    if d['winner']=='werewolf' and control['applicable']:
        rows=game.get('transcript',[])
        for i,r in enumerate(rows):
            if '绑票获胜' in r['text']:
                part=rows[max(0,i-2):i+1]
                if any('游戏结束' in x['text'] for x in part):
                    declared.append({'source_path':game['entry']['source_path'],'start_ms':part[0]['start_ms'],
                                     'end_ms':part[-1]['end_ms'],'quote':'\n'.join(x['text'] for x in part)})
    control['victory_announced']=bool(declared);control['evidence']=declared
    if declared:control['winner_reason']='狼人阵营绑票获胜（法官明确宣布）'
    else:control['winner_reason']='票数条件与实际胜负分别记录；不根据达到条件就删除后续投票或改写当局宣布的胜方。'
    game['vote_control']=control
    a['phase_findings']=findings
    a['derived_event_states']=derived_states
    a['phase_review_counts']={'unresolved':sum(x['status']=='unresolved' for x in findings),
                              'confirmed':sum(x['status']=='confirmed' for x in findings),
                              'inferred':sum(x['status']=='inferred' for x in findings)}
    return game
