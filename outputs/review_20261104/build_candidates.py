"""2026-11-04: current-window fact transcription, no external model calls."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from analyze_incremental import normalized_segments, validate_candidate, sha256
from incremental_common import load_state, save_state, work_dir, write_json
from game_derivations import derive_game
from scripts.game_timeline import build_game_timeline

NAMES = ['橘子', '圈圈', '豆腐', '荣耀', '耿许儿', 'KS', '小苍', '牛肉干', '董鲸鱼', '陈明峻', '又又', 'Bobby']
STATE = load_state(ROOT, 'S23')
SUMMARY = []


def base(bvid, roles, winner, terminal):
    item = next(x for x in STATE['items'].values() if x['entry']['bvid'] == bvid)
    folder = work_dir(ROOT, 'S23', item['entry'])
    source = json.loads((folder / 'input.json').read_text(encoding='utf8'))
    c = deepcopy(source['skeleton'])
    d = c['dossier']
    d.update(roster=NAMES, commentators=['六六', '章亿阳'], referee='辉少', winner=winner)
    blank = deepcopy(d['rounds'][0])
    d['rounds'] = [{**deepcopy(blank), 'number': n} for n in range(1, 5)]
    d['_publication_context'] = {'terminal_observation': {'round': 4, 'phase': terminal}, 'supplemental_events': []}
    for seat, name, role in zip(d['seats'], NAMES, roles):
        seat.update(name=name, role=role, faction='werewolf' if role in ['狼人', '机械狼', '诡术师', '混血儿'] else 'good')
    for n in range(1, 5):
        e(c, n, 'day', 'self_destruct', 'none')
    return c, item, folder, source


def e(c, n, phase, slot, action, actor=None, targets=(), result=None):
    row = next(x for x in c['dossier']['rounds'][n-1][phase] if x['slot'] == slot)
    row.update(action=action, actor=actor, targets=list(targets), result=result)
    return row


def extra(c, n, phase, slot, title, text, action='note', actor=None, targets=()):
    c['dossier']['_publication_context']['supplemental_events'].append({
        'round': n, 'phase': phase, 'event': {'slot': slot, 'slot_label': title,
        'action': action, 'actor': actor, 'targets': list(targets), 'result': text}})


def proof(c, source, field, lo, hi, *, note=None):
    rows = [r for r in normalized_segments(ROOT/source['source_path']) if r['start_ms'] < hi and r['end_ms'] > lo]
    value = {'field': field, 'kind': 'text', 'source_path': source['source_path'],
             'start_ms': lo, 'end_ms': hi, 'quote': ''.join(r['text'] for r in rows)}
    if note:
        value['note'] = note
    c['evidence'].append(value)


def reg(c, off):
    on = sorted(set(range(1, 13))-set(off))
    c['voting']['registrations'] = [{'id': 'sheriff-registration-1', 'day': 1, 'on_police': on, 'off_police': off}]
    e(c, 1, 'day', 'sheriff_candidates', 'register', targets=on)


def ballot(c, day, kind, num, pairs, winner, *, stage='initial', candidates=None, tied=(), slot=None):
    votes = [{'voter': a, 'target': b, 'state': 'cast' if b is not None else 'abstained'} for a,b in pairs]
    b = {'id': f'{kind}-{day}-{num}', 'day': day, 'kind': kind, 'number': num,
         'stage': stage, 'status': 'complete', 'candidates': candidates,
         'eligible_voters': sorted(a for a,_ in pairs), 'votes': votes,
         'tied_candidates': list(tied), 'winner': winner, 'unrecorded_voters': []}
    c['voting']['ballots'].append(b)
    if slot is None:
        slot = 'sheriff_vote' if kind == 'sheriff' else 'exile_vote'
    event = e(c, day, 'day', slot, 'vote')
    # Sheriff PK shares its fixed slot, retaining both true rounds.
    event['votes'] = event['votes'] + [{'round': num, 'voter': a, 'target': b, 'abstained': b is None} for a,b in pairs]
    return b


def finish(c, item, folder, source, recap, frame_time):
    frame = folder / 'frames' / f"{item['entry']['bvid']}_{frame_time:09.3f}.png"
    c['evidence'].append({'field': 'dossier.seats[1..12].name/role', 'kind': 'image',
        'source_path': frame.relative_to(ROOT).as_posix(), 'start_ms': int(frame_time*1000),
        'note': '连续法官复盘时展示的12席姓名及真实身份总览；规范别名鲸鱼→董鲸鱼、BOBBY→Bobby。机械守卫是学习形态，物理底牌仍为机械狼。'})
    # This local text boundary validates ordinary same-game evidence. The explicit
    # cross-video official ruling is separately source-bound and checked below.
    c = validate_candidate(c, item['entry'], ROOT/source['source_path'], root=ROOT)
    rules = derive_game(c['dossier'], c['voting'], endgame=c.get('endgame'))
    write_json(folder/'candidate.json', c)
    write_json(folder/'rule_derivations.json', rules['derivations'])
    write_json(folder/'review_display.json', {'identity_frames': [{
        'source_path': frame.relative_to(ROOT).as_posix(), 'caption': '本局12席姓名与真实身份（机械形态另附在物理底牌后）'}],
        'recap': {'source_path': source['source_path'], 'start_ms': recap[0], 'end_ms': recap[1]}})
    item.update(analysis='ready', candidate_sha256=sha256(folder/'candidate.json'),
                source_path=source['source_path'], source_sha256=source['source_sha256'])
    item.pop('analysis_error', None)
    timeline = build_game_timeline({**rules['dossier'], 'endgame': c.get('endgame', {})}, rules['voting'])
    write_json(folder/'timeline_preview.json', timeline)
    SUMMARY.append({'bvid': item['entry']['bvid'], 'ballots': len(c['voting']['ballots']),
        'choices': sum(len(b['votes']) for b in c['voting']['ballots']),
        'issues': c['issues'], 'rule_issues': rules['derivations']['issues'],
        'gaps': rules['derivations']['gaps'], 'review_tasks': rules['derivations']['review_tasks'],
        'vote_review_tasks': rules['derivations']['vote_review_tasks'],
        'terminal': timeline['phases'][-1]['label']})


# Game 1: all-player signup, three actual exile ballots, binding at the last one.
c,item,folder,src = base('BV1zzxR6sEB6', ['平民','平民','白神','狼人','狼人','猎人','平民','女巫','混血儿','预言家','狼人','狼人'], 'werewolf', 'day')
e(c,1,'night','mixed_blood_model','choose',9,[4])
e(c,1,'night','mixed_blood_alignment','wolf',9)
e(c,1,'night','wolf_attack','attack',targets=[11])
e(c,1,'night','witch_save','save',8,[11])
e(c,1,'night','seer_check','check',10,[3],'good')
reg(c,[])
e(c,1,'day','sheriff_vote','not_held')
e(c,1,'day','sheriff_result','none',result='全员上警，警徽流失。')
e(c,1,'day','badge','none',result='全员上警，警徽流失。')
e(c,1,'day','night_deaths','peaceful')
ballot(c,1,'exile',1,[(n,10 if n in [4,8,9,12] else 4) for n in range(1,13)],4,candidates=list(range(1,13)))
e(c,1,'day','exile_result','exile',targets=[4],result='4号8票出局')
e(c,2,'night','wolf_attack','attack',targets=[10])
e(c,2,'night','witch_poison','poison',8,[10], '10号同刀同毒出局')
e(c,2,'night','seer_check','check',10,[12],'werewolf')
e(c,2,'day','night_deaths','die',targets=[10])
e(c,2,'day','self_destruct','self_destruct',12)
e(c,2,'day','exile_vote','not_held')
e(c,2,'day','exile_result','none',result='自爆中断，没有放逐')
e(c,3,'night','wolf_attack','attack',targets=[8])
e(c,3,'day','night_deaths','die',targets=[8])
ballot(c,3,'exile',1,[(1,7),(2,7),(3,9),(5,9),(6,5),(7,9),(9,7),(11,7)],7,candidates=[1,2,3,5,6,7,9,11])
e(c,3,'day','exile_result','exile',targets=[7],result='7号4票出局')
e(c,4,'night','wolf_attack','attack',targets=[3])
e(c,4,'day','night_deaths','die',targets=[3])
ballot(c,4,'exile',1,[(1,5),(2,5),(5,6),(6,5),(9,6),(11,6)],None,candidates=[1,2,5,6,9,11],tied=[5,6])
e(c,4,'day','exile_result','none',result='5号与6号各3票后游戏结束，未执行后续放逐。')
extra(c,4,'day','binding_victory','绑票终局','5号和6号各获3票。5号、11号狼人及9号狼混形成3对3票力，法官在本轮投票后宣布游戏结束，狼人阵营绑票获胜；没有进行PK或继续放逐。')
c['voting']['interruptions']=[{'day':2,'kind':'self_destruct','seat':12}]
c['voting']['days']=[{'day':n,'sheriff':'badge_lost' if n==1 else 'not_applicable','exile':'interrupted_self_destruct' if n==2 else 'recorded'} for n in range(1,5)]
for field,lo,hi in [
    ('dossier.rounds[1].night / mixed_blood',1260000,1529000),
    ('voting.registrations / first-night settlement',1530000,1540000),
    ('voting.exile-1-1 / exile_result',3140000,3173000),
    ('dossier.rounds[2].night',3430000,3514000),
    ('dossier.rounds[2].day.self_destruct',3514000,3550000),
    ('voting.exile-3-1 / exile_result',5147500,5176000),
    ('dossier.rounds[4].night_deaths',5350000,5374000),
    ('voting.exile-4-1 / dossier.winner',5735950,5760000),
    ('dossier.seats.role / all rounds recap',5771620,5819600)]: proof(c,src,field,lo,hi)
finish(c,item,folder,src,(5771620,5819600),5778)


# Game 2: ordinary process is retained; final official ruling appears in G3.
c,item,folder,src = base('BV1zzxR6sEos', ['狼人','狼人','平民','平民','诡术师','预言家','女巫','定序王子','魔术师','平民','平民','狼人'], 'good', 'day')
e(c,1,'night','wolf_attack','attack',targets=[1])
e(c,1,'night','witch_save','save',7,[1])
e(c,1,'night','seer_check','check',6,[11],'good')
e(c,1,'night','guile_exchange','exchange',5,[2,4])
e(c,1,'night','magician_exchange','unknown',9,result='首夜字幕“魔术师通过”疑似“空过”；当前画面不能排除曾有操作，保留未知。')
reg(c,[3,10])
e(c,1,'day','sheriff_candidates','register',targets=[2,4,5,6])
ballot(c,1,'sheriff',1,[(3,2),(10,6)],None,candidates=[2,4,5,6],tied=[2,6])
ballot(c,1,'sheriff',2,[(1,6),(3,2),(4,6),(5,6),(7,6),(8,6),(9,6),(10,6),(11,6),(12,2)],6,stage='pk',candidates=[2,6])
e(c,1,'day','sheriff_result','elected',targets=[6],result='6号8票当选')
e(c,1,'day','night_deaths','peaceful')
ballot(c,1,'exile',1,[(n,10 if n in [2,12] else 12) for n in range(1,13)],12,candidates=list(range(1,13)))
e(c,1,'day','exile_result','exile',targets=[12],result='12号10.5票出局')
e(c,2,'night','magician_exchange','exchange',9,[2,6])
e(c,2,'night','guile_exchange','exchange',5,[1,7])
e(c,2,'night','wolf_attack','attack',targets=[9])
e(c,2,'night','witch_poison','poison',7,[1])
e(c,2,'night','seer_check','check',6,[4],'good')
e(c,2,'day','night_deaths','die',targets=[1,9])
ballot(c,2,'exile',1,[(n,10 if n==2 else 2) for n in [2,3,4,5,6,7,8,10,11]],2,candidates=[2,3,4,5,6,7,8,10,11])
e(c,2,'day','exile_result','exile',targets=[2],result='2号8.5票出局')
e(c,3,'night','guile_exchange','pass',5)
e(c,3,'night','wolf_attack','attack',5,[6])
e(c,3,'night','seer_check','check',6,[10],'good')
e(c,3,'day','night_deaths','die',targets=[6])
e(c,3,'day','badge','transfer',6,[10])
ballot(c,3,'exile',1,[(3,None),(4,3),(5,3),(7,3),(8,3),(10,3),(11,3)],3,candidates=[3,4,5,7,8,10,11])
e(c,3,'day','exile_result','exile',targets=[3],result='3号6.5票出局')
e(c,4,'night','guile_exchange','exchange',5,[5,10],result='实际改为5号自己与10号交换放逐结果；原先尝试重复选择4号，法官当时允许更换后继续，赛后另行裁定。')
e(c,4,'night','wolf_attack','attack',5,[7])
e(c,4,'day','night_deaths','die',targets=[7])
ballot(c,4,'exile',1,[(4,8),(5,5),(8,5),(10,8),(11,8)],None,candidates=[4,5,8,10,11])
e(c,4,'day','exile_result','none',result='8号3.5票，翻牌后本轮作废，未放逐。')
e(c,4,'day','sequential_prince_skill','reveal',8)
e(c,4,'day','extra_speech','speak',8,result='翻牌后追加发言，随后重新进行放逐投票。')
ballot(c,4,'exile',2,[(4,5),(5,8),(8,5),(10,5),(11,5)],10,stage='revote',candidates=[4,5,8,10,11],slot='second_exile_vote')
e(c,4,'day','second_exile_result','exile',targets=[10],result='诡术师交换后实际10号出局，高票者为5号。')
e(c,4,'day','guile_exchange_result','apply',result='重投5号获得4张原始票，10号警长一票按1.5票计，合计4.5票；报票字幕记为“五票”，与完整逐票的加权总数不符。高票者为5号，因5号与10号交换放逐结果，实际出局的是10号平民。')
extra(c,4,'day','wolf_rush','狼人拍刀','法官当场宣布拍刀8号后游戏结束；当时暂报狼人胜，赛事组随后作出最终好人胜裁定。',action='rush',actor=5,targets=[8])
extra(c,4,'day','final_adjudication','赛后最终裁定','第三局结束后，法官代表赛事组补充公告：本日第二局最终结算好人阵营获胜，狼人阵营失利。第四夜的违规不因暂准继续而免除；本局最终胜方按该公告记录。')
c['endgame']={'schema_version':1,'game_slug':c['dossier']['slug'],'phases':[
    {'kind':'wolf_rush','day':4,'actor':5,'declared_targets':[8],'result':'good_win',
     'note':'实际拍刀8号并当场暂报狼胜；result记录赛事组赛后最终好人胜裁定，不表示8号未中刀。补充公告来自同日第三局录像2481.39–2518.72秒。'}]}
c['voting']['days']=[{'day':n,'sheriff':'recorded' if n==1 else 'not_applicable','exile':'recorded'} for n in range(1,5)]
c['issues']=['首夜9号魔术师是否空过：法官复盘字幕为“魔术师通过”，所取画面不能清晰确认；暂未知。']
for field,lo,hi in [
    ('dossier.rounds[1].night',560000,800000),
    ('voting.registrations',800000,831000),
    ('voting.sheriff-1-1',1950000,1984000),
    ('voting.sheriff-1-2',2360000,2401000),
    ('voting.exile-1-1',4312000,4370000),
    ('dossier.rounds[2].night',4720000,4880000),
    ('dossier.rounds[2].day.night_deaths',4880000,4910000),
    ('voting.exile-2-1',5926300,5970000),
    ('dossier.rounds[3].night / badge',5990000,6140000),
    ('voting.exile-3-1',7028000,7072000),
    ('dossier.rounds[4].night.guile_exchange / repeated target',7150000,7245000),
    ('voting.exile-4-1 / prince reveal',8085000,8125000),
    ('voting.exile-4-2 / actual exile / rush',8313439,8356950),
    ('dossier.seats / recap / provisional ruling',8371210,8552860)]:proof(c,src,field,lo,hi)
proof(c,src,'voting.exile-4-2.announced_tally',8322770,8338500,
      note='四张投向5号的真实选票包含10号警长，依本季1.5警长票重为4.5票。字幕“五票”与逐票不符；保持逐票与实际出局10号，不按字幕总票改票或增大警长权重。')
# Related evidence is kept explicit instead of presenting G3 text as G2 text.
related=ROOT/'data/raw/bilibili/BV16zxR6sEKG/p01/subtitle.01.raw.json'
rows=[r for r in normalized_segments(related) if r['start_ms']>=2481390 and r['end_ms']<=2518720]
related_ev={'field':'dossier.winner / final_adjudication','kind':'text','source_path':related.relative_to(ROOT).as_posix(),
    'bvid':'BV16zxR6sEKG','cid':43331489387,'page':1,'start_ms':2481390,'end_ms':2518720,
    'quote':''.join(r['text'] for r in rows),'sha256':sha256(related),
    'relation':'同日第三局结束后，赛事组对本第二局的最终裁定公告；不是第三局胜方。'}
assert '第二局游戏当中是结算为好人阵营获胜' in related_ev['quote']
c['supplementary_evidence']=[related_ev]
write_json(folder/'final_adjudication.json',related_ev)
finish(c,item,folder,src,(8371210,8552860),8379)


# Game 3: three self-destructs; a real uncontested election before the first.
c,item,folder,src = base('BV16zxR6sEKG', ['机械狼','狼人','猎人','女巫','通灵师','狼人','狼人','平民','平民','守卫','平民','平民'], 'werewolf', 'night')
c['dossier']['seats'][0].update(learning_target=10,learned_role='机械守卫')
e(c,1,'night','guard','guard',10,[1])
e(c,1,'night','wolf_attack','attack',targets=[4])
e(c,1,'night','witch_poison','poison',4,[9])
e(c,1,'night','mechanical_action','learn',1,[10],'机械守卫')
e(c,1,'night','seer_check','check',5,[10],'守卫')
reg(c,[8,9,10])
e(c,1,'day','sheriff_candidates','register',targets=[5,7])
e(c,1,'day','sheriff_vote','not_held')
e(c,1,'day','sheriff_result','elected',targets=[5],result='7号自爆后5号自动当选警长。')
e(c,1,'day','night_deaths','die',targets=[4,9],result='7号自爆后公布4号、9号双死。')
e(c,1,'day','self_destruct','self_destruct',7)
e(c,2,'night','guard','guard',10,[5])
e(c,2,'night','wolf_attack','attack',targets=[10])
e(c,2,'night','mechanical_action','guard',1,[1])
e(c,2,'night','seer_check','check',5,[6],'狼人')
e(c,2,'day','night_deaths','die',targets=[10])
e(c,2,'day','self_destruct','self_destruct',6)
e(c,3,'night','wolf_attack','attack',2,[5])
e(c,3,'night','mechanical_action','unknown',1,result='第二天夜晚机械守卫是否空守、是否守了其他目标未被字幕与所取画面说清，保留未知。')
e(c,3,'night','seer_check','check',5,[8],'平民')
e(c,3,'day','night_deaths','die',targets=[5])
e(c,3,'day','badge','transfer',5,[8])
e(c,3,'day','self_destruct','self_destruct',2)
e(c,4,'night','mechanical_knife_status','carrying',1)
e(c,4,'night','wolf_attack','attack',1,[3], '击杀最后一神3号猎人，游戏结束，狼人屠神获胜。')
e(c,4,'night','mechanical_action','unavailable',1,result='机械狼击杀最后一神即终局，后续守护不再执行。')
e(c,4,'day','night_deaths','die',targets=[3],result='本夜3号最后一神猎人被刀，游戏结束；第四天白天未开始。')
e(c,4,'day','hunter_shot','unavailable',3,result='末神猎人出局即终局，没有后续开枪窗口。')
for n in range(1,4):
    e(c,n,'day','exile_vote','not_held')
    e(c,n,'day','exile_result','none',result='自爆中断，无实际放逐票轮。')
c['voting']['interruptions']=[{'day':n,'kind':'self_destruct','seat':s} for n,s in [(1,7),(2,6),(3,2)]]
c['voting']['days']=[{'day':n,'sheriff':'recorded' if n==1 else 'not_applicable','exile':'interrupted_self_destruct'} for n in range(1,4)]
c['issues']=['第二天夜晚1号机械守卫的具体守护行动未知：字幕未明确，已取相应夜间画面但不足以定目标；不按未提及记空守。']
for field,lo,hi in [
    ('dossier.rounds[1].night',359000,570000),
    ('voting.registrations',570000,590820),
    ('dossier.rounds[1].day.sheriff_result / self_destruct / night_deaths',1445000,1478000),
    ('dossier.rounds[2].night',1650000,1894000),
    ('dossier.rounds[2].day',1900670,2018000),
    ('dossier.rounds[3].night / badge',2018000,2147219),
    ('dossier.rounds[3].day.self_destruct',2320000,2336820),
    ('dossier.rounds[4].night / dossier.winner',2377000,2411970),
    ('dossier.seats / full recap',2417380,2481390)]:proof(c,src,field,lo,hi)
finish(c,item,folder,src,(2417380,2481390),2428)

save_state(ROOT,'S23',STATE)
write_json(ROOT/'data/reports/S23/incremental/20261104_candidate_validation.json',SUMMARY)
write_json(ROOT/'data/reports/S23/incremental/analysis.json',{
    'season':'S23','analyzed':3,'prepared':3,'waiting_acquisition':[],'failures':[],
    'review_page':'data/manual_review/S23_新增对局人工复核.html',
    'database_written':False,'publication':False,'analysis_method':'current_conversation_model'})
print(json.dumps(SUMMARY,ensure_ascii=False,indent=2))
