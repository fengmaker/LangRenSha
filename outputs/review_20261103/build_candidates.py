"""Materialize facts read by the current conversation model on 2026-11-04.

This one-off script only saves the three explicit decisions below. It does not
extract facts, invoke a model, apply review feedback, import or publish games.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
from incremental_common import read_json, write_json, work_dir, load_state, save_state
from analyze_incremental import normalized_segments, sha256, validate_candidate
from game_derivations import derive_game
from scripts.game_timeline import build_game_timeline

NAMES = ['二妖', '徐言雨', '苏打', '亚亚', '彭彭', 'KS', '小苍', '牛肉干', '果冻', '章亿阳', '申屠', '大卫']
WOLF_ROLES = {'狼人', '狼女孩', '假面', '机械狼'}
WEIBO = ('data/raw/weibo/2026-11-01_2026-11-04_京城大师赛_UID7525583841/'
         'long_text/2026-11/2026-11-03_15-30-39_S23_第08期_阵容公告__WB5361191150420139.长文原始.json')


def make(bvid, roles, rounds, winner, frame_time, recap):
    item = next(i for i in STATE['items'].values() if i['entry']['bvid'] == bvid)
    folder = work_dir(ROOT, 'S23', item['entry'])
    source = read_json(folder / 'input.json')
    candidate = deepcopy(source['skeleton'])
    game = candidate['dossier']
    blank = deepcopy(game['rounds'][0])
    game['rounds'] = []
    for number in range(1, rounds + 1):
        row = deepcopy(blank)
        row['number'] = number
        game['rounds'].append(row)
    game.update(winner=winner, roster=NAMES, commentators=['鬼鬼', '盛宝'], referee='辉少')
    for seat, name, role in zip(game['seats'], NAMES, roles):
        seat.update(name=name, role=role, faction='werewolf' if role in WOLF_ROLES else 'good')
    frame = folder / 'frames' / f'{bvid}_{frame_time:09.3f}.png'
    candidate['evidence'].extend([
        {'field': 'dossier.seats[].name/role', 'kind': 'image',
         'source_path': frame.relative_to(ROOT).as_posix(),
         'note': '本局连续法官复盘12席真实身份总览；逐格读取座位、名牌和底牌；不是奇幻视角。'},
        {'field': 'dossier.date/roster/commentators/referee', 'kind': 'weibo',
         'source_path': WEIBO,
         'note': '11月3日官方第八期阵容公告，与当局自我介绍和身份页交叉；全部姓名复用既有规范映射，法官萧亚辉使用既有规范名辉少。'}])
    display = {'identity_frames': [{'source_path': frame.relative_to(ROOT).as_posix(),
                'caption': '本局12席姓名与真实物理底牌（法官复盘身份总览）'}],
               'recap': {'source_path': source['source_path'], 'start_ms': recap[0], 'end_ms': recap[1]}}
    write_json(folder / 'review_display.json', display)
    write_json(folder / 'frame_plan.json', {'source_sha256': source['source_sha256'],
               'frame_times_seconds': [frame_time], 'notes': ['全文定位连续法官复盘，选取真实12席身份总览。']})
    return item, folder, source, candidate


def event(c, number, phase, slot, action, actor=None, targets=(), result=None):
    e = next(e for e in c['dossier']['rounds'][number-1][phase] if e['slot'] == slot)
    e.update(action=action, actor=actor, targets=list(targets), result=result)
    return e


def evidence(c, src, field, start, end, note=None):
    rows = normalized_segments(ROOT / src['source_path'])
    quote = ''.join(r['text'] for r in rows if r['end_ms'] >= start and r['start_ms'] <= end)
    e = {'field': field, 'kind': 'text', 'source_path': src['source_path'],
         'start_ms': start, 'end_ms': end, 'quote': quote}
    if note:
        e['note'] = note
    c['evidence'].append(e)


def ballot(c, day, kind, number, votes, *, candidates=None, tied=(), winner=None):
    rows = [{'voter': voter, 'target': target, 'state': 'cast' if target else 'abstained'}
            for voter, target in votes]
    b = {'id': f'{kind}-{day}-{number}', 'day': day, 'kind': kind, 'number': number,
         'stage': 'initial' if number == 1 else 'pk', 'status': 'complete',
         'candidates': candidates, 'eligible_voters': [v[0] for v in votes],
         'votes': rows, 'tied_candidates': list(tied), 'winner': winner, 'unrecorded_voters': []}
    c['voting']['ballots'].append(b)
    slot = 'sheriff_vote' if kind == 'sheriff' else 'exile_vote'
    e = next(e for e in c['dossier']['rounds'][day-1]['day'] if e['slot'] == slot)
    e['action'] = 'vote'
    e['votes'].extend({'round': number, 'voter': r['voter'], 'target': r['target'],
                       'abstained': r['state'] == 'abstained'} for r in rows)


def registration(c, off):
    on = [n for n in range(1, 13) if n not in off]
    event(c, 1, 'day', 'sheriff_candidates', 'register', targets=on)
    c['voting']['registrations'] = [{'id': 'registration-1', 'day': 1, 'on_police': on, 'off_police': off}]


def interruption(c, day, actor):
    event(c, day, 'day', 'self_destruct', 'self_destruct', actor=actor, result='自爆中断当日流程')
    event(c, day, 'day', 'exile_vote', 'not_held', result='自爆中断，未举行放逐投票')
    event(c, day, 'day', 'exile_result', 'none', result='自爆中断，未进行放逐')
    c['voting']['interruptions'].append({'id': f'interruption-{day}', 'day': day,
                                       'actor': actor, 'reason': 'self_destruct', 'ends_day': True})


def wolf_girl():
    item, folder, src, c = make('BV1Gnxm6sEjQ',
        ['守卫','平民','平民','狼人','猎人','狼人','毒师','平民','平民','预言家','狼人','狼女孩'],
        4, 'good', 6860, (6845940, 6901050))
    c['dossier']['seats'][7]['faction'] = 'werewolf'
    c['dossier']['_publication_context'] = {'terminal_observation': {'round': 4, 'phase': 'day', 'basis': 'judge_final_exile'}}
    event(c, 1, 'night', 'wolf_girl_confession', 'confess', 12, [8],
          '表白成功；8号物理底牌仍为平民，成为狼伴侣，个人胜利阵营跟随狼人，不带刀')
    event(c, 1, 'night', 'guard', 'pass', 1, result='首夜明确空守')
    event(c, 1, 'night', 'wolf_attack', 'forbidden', result='狼女孩版型首夜禁止狼刀')
    event(c, 1, 'night', 'witch_poison', 'pass', 7, result='第二夜首次使用唯一毒药，首夜保留')
    event(c, 1, 'night', 'seer_check', 'check', 10, [2], 'good')
    registration(c, [1,4,5,8])
    ballot(c, 1, 'sheriff', 1, [(1,10),(4,10),(5,10),(8,6)], candidates=[6,10,12], winner=10)
    event(c, 1, 'day', 'sheriff_result', 'elected', targets=[10], result='10号三票当选警长')
    event(c, 1, 'day', 'night_deaths', 'peaceful')
    event(c, 1, 'day', 'badge', 'hold', 10)
    interruption(c, 1, 6)
    event(c, 2, 'night', 'guard', 'guard', 1, [2])
    event(c, 2, 'night', 'wolf_attack', 'attack', targets=[1])
    event(c, 2, 'night', 'witch_poison', 'poison', 7, [8], '毒杀8号狼伴侣平民')
    event(c, 2, 'night', 'seer_check', 'check', 10, [5], 'good')
    event(c, 2, 'day', 'night_deaths', 'die', targets=[1,8], result='1号守卫刀死、8号狼伴侣平民毒死')
    event(c, 2, 'day', 'badge', 'hold', 10)
    ballot(c, 2, 'exile', 1, [(2,11),(3,11),(4,11),(5,11),(7,12),(9,11),(10,11),(11,7),(12,11)], winner=11)
    event(c, 2, 'day', 'exile_result', 'exile', targets=[11], result='11号7.5票出局（7张原始票，10号警长另有半票）')
    event(c, 2, 'day', 'self_destruct', 'none')
    event(c, 3, 'night', 'wolf_attack', 'attack', targets=[10])
    event(c, 3, 'night', 'seer_check', 'check', 10, [7], 'good')
    event(c, 3, 'day', 'night_deaths', 'die', targets=[10], result='10号预言家刀死')
    event(c, 3, 'day', 'badge', 'transfer', 10, [7])
    interruption(c, 3, 12)
    event(c, 4, 'night', 'wolf_attack', 'pass', 4, result='法官连续复盘明确狼人空刀')
    event(c, 4, 'day', 'night_deaths', 'peaceful', result='狼人主动空刀，平安夜')
    event(c, 4, 'day', 'badge', 'hold', 7)
    ballot(c, 4, 'exile', 1, [(2,4),(3,4),(4,3),(5,4),(7,4),(9,4)], winner=4)
    event(c, 4, 'day', 'exile_result', 'exile', targets=[4], result='4号5.5票出局，最后一张狼人淘汰，游戏结束，好人阵营获胜')
    event(c, 4, 'day', 'self_destruct', 'none')
    for number in range(1,5):
        event(c, number, 'day', 'game_end', 'none')
    c['voting']['days'] = [
        {'day': 1, 'sheriff': 'recorded', 'exile': 'interrupted_self_destruct'},
        {'day': 2, 'sheriff': 'not_applicable', 'exile': 'recorded'},
        {'day': 3, 'sheriff': 'not_applicable', 'exile': 'interrupted_self_destruct'},
        {'day': 4, 'sheriff': 'not_applicable', 'exile': 'recorded'}]
    for field, a, b in [
        ('dossier.rounds[1].night.guard',1122000,1145000),
        ('dossier.rounds[1].night.wolf_girl_confession/seats[8].faction',6853220,6867440),
        ('dossier.rounds[1].night.seer_check',6863040,6867440),
        ('voting.registrations',1395000,1411420),
        ('voting.ballots.sheriff-1-1/dossier.rounds[1].day.sheriff_result',2284000,2320000),
        ('dossier.rounds[1].day.self_destruct',3770000,3810000),
        ('dossier.rounds[2].night',6871910,6881050),
        ('dossier.rounds[2].day.night_deaths',4020000,4060000),
        ('voting.ballots.exile-2-1',5550000,5600000),
        ('dossier.rounds[3].night/seer_check',6884070,6891650),
        ('dossier.rounds[3].day.night_deaths/badge/self_destruct',5815000,5866000),
        ('dossier.rounds[4].night.wolf_attack',6891650,6898710),
        ('voting.ballots.exile-4-1/dossier.winner',6798000,6833810)]:
        evidence(c, src, field, a, b)
    c['issues'] = []
    return item, folder, src, c


def masquerade():
    item, folder, src, c = make('BV1Qnxm6sEQq',
        ['假面','狼人','预言家','白神','平民','狼人','女巫','平民','平民','狼人','平民','舞者'],
        3, 'good', 5035, (5019800,5062370))
    c['dossier']['_publication_context'] = {
        'terminal_observation': {'round': 3, 'phase': 'night', 'basis': 'observed_surrender'},
        'supplemental_events': [{'round': 3, 'phase': 'night',
            'event': {'slot': 'werewolf_surrender', 'action': 'surrender', 'actor': 1,
                      'targets': [], 'result': '1号假面选择交牌，游戏结束，好人阵营获胜'}}]}
    event(c, 1, 'night', 'wolf_attack', 'attack', targets=[4])
    event(c, 1, 'night', 'witch_save', 'save', 7, [4])
    event(c, 1, 'night', 'seer_check', 'check', 3, [11], 'good')
    event(c, 1, 'night', 'dance_resolution', 'unavailable', result='首夜尚无共舞窗口')
    registration(c, [1,6,8,9])
    ballot(c, 1, 'sheriff', 1, [(1,2),(6,2),(8,3),(9,3)], candidates=[2,3,12], tied=[2,3])
    ballot(c, 1, 'sheriff', 2, [(1,None),(4,3),(5,2),(6,2),(7,3),(8,3),(9,2),(10,3),(11,3),(12,3)],
           candidates=[2,3], winner=3)
    event(c, 1, 'day', 'sheriff_result', 'elected', targets=[3], result='首轮2号、3号各两票平票，PK复投后3号六票当选')
    event(c, 1, 'day', 'night_deaths', 'peaceful', result='4号白神被女巫救起')
    event(c, 1, 'day', 'badge', 'hold', 3)
    ballot(c, 1, 'exile', 1, [(1,2),(2,7),(3,2),(4,2),(5,2),(6,7),(7,2),(8,2),(9,7),(10,7),(11,2),(12,2)], winner=2)
    event(c, 1, 'day', 'exile_result', 'exile', targets=[2], result='2号8.5票出局（8张原始票，3号警长另有半票）')
    event(c, 1, 'day', 'self_destruct', 'none')
    event(c, 2, 'night', 'dancer_dance', 'dance', 12, [1,6,10], '1号假面、6号狼人、10号狼人共舞')
    event(c, 2, 'night', 'masquerade_verify', 'verify', 1, [3], '3号不在舞池内')
    event(c, 2, 'night', 'masquerade_mask', 'give_mask', 1, [8], '给8号平民面具，8号不在舞池内')
    event(c, 2, 'night', 'dance_resolution', 'no_death', result='舞池内三人均为狼人阵营，无人因共舞出局')
    event(c, 2, 'night', 'wolf_attack', 'attack', targets=[11])
    event(c, 2, 'night', 'witch_poison', 'poison', 7, [6])
    event(c, 2, 'night', 'seer_check', 'check', 3, [12], 'good')
    event(c, 2, 'day', 'night_deaths', 'die', targets=[6,11], result='6号狼人毒死、11号平民刀死')
    event(c, 2, 'day', 'badge', 'hold', 3)
    ballot(c, 2, 'exile', 1, [(1,9),(3,10),(4,1),(5,10),(7,1),(8,10),(9,None),(10,9),(12,10)], winner=10)
    event(c, 2, 'day', 'exile_result', 'exile', targets=[10], result='10号4.5票出局（4张原始票，3号警长另有半票）')
    event(c, 2, 'day', 'self_destruct', 'none')
    for number in (1,2):
        event(c, number, 'day', 'idiot_reveal', 'unavailable', 4, result='4号白神未被公投出局，无翻牌窗口')
    for slot in ('witch_save','witch_poison','seer_check','masquerade_verify','masquerade_mask','dancer_dance','dance_resolution'):
        event(c, 3, 'night', slot, 'unavailable', result='1号假面入夜立即交牌，本夜行动未开始')
    event(c, 3, 'night', 'wolf_attack', 'unknown', result='1号假面选择交牌，游戏结束；D3未开始，未执行夜间行动')
    event(c, 3, 'day', 'exile_vote', 'not_held', result='交牌后D3未开始，无放逐投票')
    event(c, 3, 'day', 'exile_result', 'none', result='入夜1号假面交牌，游戏结束；D3未开始')
    c['voting']['days'] = [{'day':1,'sheriff':'recorded','exile':'recorded'},
                            {'day':2,'sheriff':'not_applicable','exile':'recorded'}]
    for field, a, b, note in [
        ('dossier.rounds[1].night',5026920,5033610,None),
        ('voting.registrations',388000,410000,None),
        ('voting.ballots.sheriff-1-1',1216170,1240540,
         '逐人票型1/6→2、8/9→3，各两票；字幕“各一票”为识别错误，按四张票与真实PK处理。'),
        ('voting.ballots.sheriff-1-2',1499700,1540940,
         '1号“七票”为弃票识别错误：1号随后明确自述斟酌后弃票；PK目标仅2、3。'),
        ('voting.ballots.sheriff-1-2.votes[1]',3050000,3110000,
         '1号本人连续解释首轮投2、PK轮弃票，与法官逐票交叉。'),
        ('voting.ballots.exile-1-1',3570000,3630000,None),
        ('dossier.rounds[2].night',5039270,5055150,None),
        ('dossier.rounds[2].day.night_deaths',4030000,4070000,None),
        ('voting.ballots.exile-2-1',4940000,4987000,None),
        ('dossier._publication_context.terminal_observation',4999000,5007200,
         '放逐10号后法官先宣布天黑，随后1号交牌；按实际入夜终局，不补D3白天。'),
        ('dossier.winner',5055150,5062370,None)]:
        evidence(c, src, field, a, b, note)
    return item, folder, src, c


def mechanical():
    item, folder, src, c = make('BV1anxm6sEWy',
        ['守卫','通灵师','平民','平民','狼人','狼人','平民','机械狼','平民','猎人','狼人','女巫'],
        4, 'werewolf', 2880, (2861500,2917460))
    c['dossier']['seats'][7].update(learning_target=12, learned_role='机械女巫')
    c['dossier']['_publication_context'] = {'terminal_observation': {'round':4,'phase':'night','basis':'judge_final_night_settlement'}}
    event(c, 1, 'night', 'guard', 'guard', 1, [4])
    event(c, 1, 'night', 'wolf_attack', 'attack', targets=[12])
    event(c, 1, 'night', 'witch_save', 'pass', 12, result='女巫12号首夜自中刀，选择开毒未自救')
    event(c, 1, 'night', 'witch_poison', 'poison', 12, [5])
    event(c, 1, 'night', 'mechanical_action', 'learn', 8, [12], '机械女巫')
    event(c, 1, 'night', 'seer_check', 'check', 2, [3], '平民')
    registration(c, [4,8,9])
    interruption(c, 1, 5)
    event(c, 1, 'day', 'sheriff_vote', 'not_held', result='5号在上警竞选阶段吞毒自爆，未举行警长投票')
    event(c, 1, 'day', 'sheriff_result', 'deferred', result='首日竞选被5号自爆中断，延期次日')
    event(c, 1, 'day', 'night_deaths', 'die', targets=[5,12], result='5号吞毒自爆后公布5号、12号倒牌；12号刀死，5号毒口与自爆为同一座位')
    event(c, 1, 'day', 'badge', 'none', result='尚未产生警徽')
    event(c, 2, 'night', 'guard', 'guard', 1, [1])
    event(c, 2, 'night', 'wolf_attack', 'attack', targets=[2])
    event(c, 2, 'night', 'mechanical_action', 'pass', 8, result='机械女巫本夜空过')
    event(c, 2, 'night', 'seer_check', 'check', 2, [6], '狼人')
    event(c, 2, 'day', 'sheriff_candidates', 'continued', result='继续首日未完成的警长竞选')
    interruption(c, 2, 11)
    event(c, 2, 'day', 'sheriff_vote', 'not_held', result='延期竞选中11号自爆，未举行警长投票')
    event(c, 2, 'day', 'sheriff_result', 'none', result='次日再次自爆，警徽流失')
    event(c, 2, 'day', 'night_deaths', 'die', targets=[2], result='11号自爆后公布昨夜2号通灵师刀死')
    event(c, 2, 'day', 'badge', 'none', result='badge_lost')
    event(c, 3, 'night', 'guard', 'guard', 1, [3])
    event(c, 3, 'night', 'wolf_attack', 'attack', targets=[1])
    event(c, 3, 'night', 'mechanical_action', 'pass', 8, result='机械女巫本夜空过')
    event(c, 3, 'day', 'night_deaths', 'die', targets=[1], result='1号守卫刀死')
    event(c, 3, 'day', 'badge', 'none', result='badge_lost')
    interruption(c, 3, 6)
    event(c, 4, 'night', 'wolf_attack', 'attack', 8, [4], '普通狼人5号、11号、6号均已出局，8号机械女巫接刀，击杀4号平民')
    event(c, 4, 'night', 'mechanical_knife_status', 'carrying', 8, result='普通狼人全部出局，8号机械狼接刀')
    event(c, 4, 'night', 'mechanical_action', 'poison', 8, [10], '机械女巫毒杀最后一神10号猎人')
    event(c, 4, 'day', 'night_deaths', 'die', targets=[4,10], result='4号平民刀死、10号猎人中机械女巫毒；本夜屠神终局，D4未开始')
    event(c, 4, 'day', 'hunter_shot', 'unavailable', 10, result='末神猎人被机械女巫毒杀，夜间直接终局，没有开枪窗口')
    event(c, 4, 'day', 'exile_vote', 'not_held', result='夜间结束，D4未开始')
    event(c, 4, 'day', 'exile_result', 'none', result='夜间屠神，游戏结束，狼人阵营获胜；D4未开始')
    c['voting']['days'] = [
        {'day':1,'sheriff':'deferred','exile':'interrupted_self_destruct'},
        {'day':2,'sheriff':'badge_lost','exile':'interrupted_self_destruct'},
        {'day':3,'sheriff':'badge_lost','exile':'interrupted_self_destruct'}]
    for field, a, b in [
        ('dossier.seats[8].learning_target/learned_role/rounds[1].night',2870850,2884530),
        ('voting.registrations',817000,838000),
        ('dossier.rounds[1].day.self_destruct/night_deaths',1631340,1680000),
        ('dossier.rounds[2].night',2888300,2896400),
        ('dossier.rounds[2].day.self_destruct/sheriff_result/night_deaths',1990000,2030000),
        ('dossier.rounds[3].night',2901529,2907690),
        ('dossier.rounds[3].day.night_deaths',2220000,2250000),
        ('dossier.rounds[3].day.self_destruct',2699000,2724000),
        ('dossier.rounds[4].night.wolf_attack/mechanical_action',2908010,2917460),
        ('dossier.rounds[4].day.night_deaths/dossier.winner',2848970,2855530)]:
        evidence(c, src, field, a, b)
    return item, folder, src, c


def materialize():
    reports = []
    for factory in [wolf_girl, masquerade, mechanical]:
        item, folder, src, c = factory()
        write_json(folder / 'candidate.json', c)
        reports.append((item, folder, src, c))
    return reports


def validate(reports):
    summary = []
    for item, folder, src, c in reports:
        checked = validate_candidate(c, item['entry'], ROOT / src['source_path'])
        rules = derive_game(checked['dossier'], checked['voting'])
        write_json(folder / 'candidate.json', checked)
        write_json(folder / 'rule_derivations.json', rules['derivations'])
        timeline = build_game_timeline(rules['dossier'], rules['voting'])
        write_json(folder / 'timeline.preview.json', timeline)
        item.update(analysis='ready', source_path=src['source_path'], source_sha256=src['source_sha256'],
                    candidate_sha256=sha256(folder / 'candidate.json'))
        item.pop('analysis_error', None)
        summary.append({'bvid': item['entry']['bvid'], 'cid': item['entry']['cid'],
                        'game_number':checked['dossier']['game_number'], 'board':checked['dossier']['board'],
                        'winner':checked['dossier']['winner'], 'ballots':len(checked['voting']['ballots']),
                        'choices':sum(len(b['votes']) for b in checked['voting']['ballots']),
                        'candidate_sha256':item['candidate_sha256'],
                        'rule_issues':rules['derivations'].get('issues',[]),
                        'review_tasks':rules['derivations'].get('review_tasks',[]),
                        'vote_review_tasks':rules['derivations'].get('vote_review_tasks',[]),
                        'phases':[{k:v for k,v in p.items() if k != 'items'} for p in timeline['phases']]})
    save_state(ROOT,'S23',STATE)
    return summary


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    STATE = load_state(ROOT,'S23')
    reports = materialize()
    if '--materialize-only' not in sys.argv:
        summary = validate(reports)
        write_json(ROOT/'data/reports/S23/incremental/20261103_candidate_validation.json', summary)
        print(json.dumps(summary,ensure_ascii=False,indent=2))
    else:
        print('Saved three current-window candidates; validation pending.')
