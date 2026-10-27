import json,collections
from pathlib import Path
O=Path('/workspace/scratch/a7edd912716e/audit-published/S22');B=json.loads((O/'review_bundle.json').read_text());find=[];timelines=[]
for bv,x in B.items():
 d=x['dossier'];dead=set();days=[]
 for rr in d['rounds']:
  n=rr['number'];nd=set();before_night=sorted(set(range(1,13))-dead)
  def add(code,path,old,candidate,note):find.append({'bvid':bv,'game_id':d['slug'],'date':d['date'],'code':code,'field':path,'old':old,'candidate':candidate,'note':note,'status':'candidate_only_special_settlement_not_fully_replayed'})
  for e in rr['night']:
   if e['action'] not in ['unknown','unavailable','forbidden','pass']:
    if e.get('actor') in dead:add('active_actor_already_departed',f'rounds[{n}].night.{e["slot"]}',e,None,'此前正式明确出局者在后夜有非空操作；需复核先前出局和行动时点，不能自动删行动。')
    if any(t in dead for t in e['targets']):add('night_target_already_departed',f'rounds[{n}].night.{e["slot"]}',e,None,'夜行动目标此前已出局；选榜样或结算历史引用可能例外，需读原文。')
  for e in rr['day']:
   if e['slot']=='night_deaths' and e['action']=='die':nd.update(e['targets'])
  # no inference from a calm night; supplemental sources kept separate
  supp=set()
  for z in x['extraction'].get('night_death_supplements',[]):
   if z.get('day')==n:supp.update(z.get('targets',z.get('seats',[])))
  dead.update(nd|supp)
  shots_before=[];shots_after=[]
  for e in rr['day']:
   if e['action']=='shoot':
    (shots_before if e.get('actor') in nd else shots_after).extend(e['targets'])
   if e['slot']=='masked_delayed_death' and e['action']=='die_after_speech':dead.update(e['targets'])
  dead.update(shots_before);expected=set(range(1,13))-dead
  ballots=[b for b in x['voting']['ballots'] if b['day']==n and b['kind']=='exile']
  for b in ballots:
   if b.get('eligible_voters') is not None:
    actual=set(b['eligible_voters']);illegal=actual&dead
    if illegal:add('eligible_player_already_departed',f'voting.{b["id"]}.eligible_voters',sorted(actual),sorted(actual-illegal),'按正式已知出局重放仍含已出局者；特殊延迟和白痴失票等需另核。')
  # consistent only with known explicit departure fields; skill order is simplified
  exiles=[];sd=[]
  for e in rr['day']:
   if e['slot'] in ['exile_result','second_exile_result'] and e['action']=='exile':exiles.extend(e['targets'])
   if e['slot']=='self_destruct' and e['action']=='self_destruct':sd.extend(e['targets'] or [e['actor']])
  if ballots:
   last=ballots[-1]
   if last.get('winner') and exiles and last['winner'] not in exiles:add('voting_vs_dossier_exile_result',f'voting.{last["id"]}.winner',last['winner'],exiles,'最终票轮winner与当日正式放逐结果不同；需区分换位、技能复投和口头纠正。')
  dead.update(exiles+sd+shots_after)
  days.append({'round':n,'known_living_before_night':before_night,'night_deaths_recorded':sorted(nd),'night_death_supplements':sorted(supp),'shots_before_vote':shots_before,'known_living_before_exile':sorted(expected),'exiles':exiles,'self_destruct':sd,'shots_after_vote':shots_after,'known_living_after_day':sorted(set(range(1,13))-dead)})
 timelines.append({'bvid':bv,'game_id':d['slug'],'method':'independent limited replay of explicit official exits; not a full role/skill simulator','days':days})
(O/'independent_timeline_candidates.json').write_text(json.dumps(find,ensure_ascii=False,indent=2));(O/'independent_timeline.json').write_text(json.dumps(timelines,ensure_ascii=False,indent=2));print('FIND',len(find),collections.Counter(x['code'] for x in find));print(json.dumps(find,ensure_ascii=False,indent=2))
