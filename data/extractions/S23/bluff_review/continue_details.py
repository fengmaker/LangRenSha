"""Apply the primary reviewer's source-read and visually checked corrections."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[4]
PARTS = ROOT / 'data/extractions/S23/bluff_review/parts'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def helpers(bvid):
    entry = json.loads((ROOT / 'data/extractions/S23/game_reviews' / bvid / 'entry.json').read_text(encoding='utf-8'))
    source = ROOT / entry['source_path']
    rows = json.loads(source.read_text(encoding='utf-8'))['body']

    def quote(start, end, meaning):
        selected = [r for r in rows if start <= r['from'] < end]
        assert selected
        return {'kind': 'transcript', 'source_path': entry['source_path'], 'source_sha256': sha(source),
                'start_ms': round(selected[0]['from'] * 1000), 'end_ms': round(selected[-1]['to'] * 1000),
                'text': '\n'.join(r['content'] for r in selected), 'interpretation': meaning}

    def frame(second, meaning):
        path = ROOT / 'data/extractions/S23/bluff_review/frames' / bvid / f'{bvid}_{second:09.3f}.png'
        return {'kind': 'video_frame', 'source_path': path.relative_to(ROOT).as_posix(), 'source_sha256': sha(path),
                'start_ms': round(second * 1000), 'end_ms': round(second * 1000), 'frame_time_ms': round(second * 1000),
                'text': meaning, 'interpretation': '主审已目视原视频截图，并与法官流程和相邻本人话轮交叉核对。'}
    return quote, frame


def update(part, bvid, seat, note, evidence):
    path = PARTS / f'audit_{part}.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    game = next(g for g in data['games'] if g['bvid'] == bvid)
    row = next(a for a in game['assessments'] if a['seat'] == seat)
    row.update(decision='no', claimed_role=None, claim_day=None, actual_claim_day=None,
               first_day_claim=False, decision_note=note, evidence=evidence, review_questions=[], confidence='high')
    game['notes'] = [n for n in game.get('notes', []) if 'uncertain' not in n]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


q, f = helpers('BV1NBhU68EUy')
update('b', 'BV1NBhU68EUy', 4,
       '4号首日在警下；8号在首轮警上结束时自爆，次日11号又在延期竞选环节直接自爆，均未进入警下发言。第三天4号被宣布夜间毒杀出局、没有遗言，因此其整个在场阶段没有本人公开话轮，不存在信息神自称。原未决来自未定位话轮，现以连续流程确认未发言。',
       [q(2331, 2340, '首日警上结束即8号自爆、入夜，警下4号尚未发言。'),
        q(2501, 2523, '次日11号在延期竞选时自爆，流徽后再入夜，4号仍无话轮。'),
        q(2640, 2662, '第三天4号被宣布夜死、无遗言，随后从1号开始首轮常规发言。'),
        q(3661, 3675, '终局复盘确认11号自爆后入夜，4号被女巫毒杀，第三天出局。'),
        f(2643, '第三天法官宣布2号、4号双死且无遗言的原画面；4号在首次常规发言前已出局。')])

q, f = helpers('BV1VPaW66EZz')
update('b', 'BV1VPaW66EZz', 11,
       '11号首日在警下，参与警徽投票给5号；5/7平票后7号PK公开认狼，随后法官宣布11号自爆。此时尚未进入警下常规发言，11号没有自己的话轮。将其自爆和他人讨论11号查杀分开，未观察到本人信息神自称。',
       [q(1649, 1668, '11号投给5号，警徽5/7平票后开始7号PK，11号不是本轮发言者。'),
        q(1744, 1753, 'PK发言者7号公开以狼队视角说话，不能归给11号。'),
        q(1830, 1847, '7号要求队友自爆后，法官宣布11号自爆，再公布夜间死亡，未进入11号本人话轮。'),
        f(1839, '首日PK期间法官宣布11号选择自爆；侧栏11号只留下警徽票5，没有本人验人或警徽流摘要。')])

q, f = helpers('BV1zmpB6PEcF')
update('c', 'BV1zmpB6PEcF', 1,
       '纠正发言归属：2882.93秒“我确实是通灵师牌”处于2754.86至2960.97秒11号的完整警下话轮，随后才轮12号、1号，不能归给1号。1号首日警上只分析他人身份；其警下话轮明确讨论3号、11号谁是真通灵师，遗言自称平民。核对本人完整话轮及流程后，1号不记悍跳。',
       [q(2580, 2596, '法官明确交给1号警上发言，1号分析11号给2号身份的关系。'),
        q(2676, 2718, '1号警上结尾点狼坑、自称好人，随即全体警上结束。'),
        q(2751, 2763, '警长指定11号开始警下发言，11号报验2号。'),
        q(2881, 2887, '明确通灵师自称在11号话轮中，而非1号。'),
        q(2957, 2969, '11号结束后法官交12号，进一步封闭11号话轮边界。'),
        q(3166, 3188, '12号之后才交1号，1号自称好人并讨论是否存在盗宝通灵。'),
        q(3251, 3259, '1号说“我觉得三是真的通灵”，主体为3号，不是自己。'),
        q(5316, 5324, '1号遗言明确自称平民。'),
        f(2883, '第一天警下阶段，11号的报验2号、警徽流5-7仍列在侧栏；此时的通灵师自称须归11号。'),
        f(3255, '第一天警下1号本人话轮期间，1号侧栏仍为分析他人；原文把通灵师身份归给3号。'),
        f(5318, '1号第一天被公投后遗言自称平民，与其本人两轮分析他人身份的发言一致。')])

# The formal game snapshot did not record the explicitly announced badge loss.
# Keep this supplementary result in the evidence-bound review, not in the game.
q, f = helpers('BV14sY36hEPC')
path = PARTS / 'audit_a.json'
data = json.loads(path.read_text(encoding='utf-8'))
game = next(g for g in data['games'] if g['bvid'] == 'BV14sY36hEPC')
game['result_review'] = {'badge': 'lost', 'note': '首日7号自爆、次日8号在延期竞选时再自爆；法官和终局复盘均明确宣布本局警徽流失，无人竞选拿徽。',
                         'evidence': [q(1936, 1945, '8号自爆后法官明确宣布本局警徽流失。'),
                                      q(2139, 2152, '第三天再次明确警徽流失，依随机点数开始发言。'),
                                      q(2675, 2680, '终局复盘确认8号自爆、本局警徽流失。'),
                                      f(1939, '第二天8号自爆后法官宣布本局警徽流失的原画面。'),
                                      f(2677, '终局身份复盘画面，对应原文“本局游戏警徽流失”。')]}
row = next(a for a in game['assessments'] if a['seat'] == 8)
suffix = '续核已确认双爆后警徽流失，首日亦无放逐，不满足悍跳成功条件。'
if suffix not in row['decision_note']:
    row['decision_note'] += ' ' + suffix
seen = {(e['kind'], e.get('start_ms', e.get('frame_time_ms'))) for e in row['evidence']}
row['evidence'] += [e for e in game['result_review']['evidence']
                    if (e['kind'], e.get('start_ms', e.get('frame_time_ms'))) not in seen]
for ev in row['evidence']:
    if ev['kind'] == 'video_frame':
        ev['text'] = '8号狼人侧栏保留验12查杀及警徽流，与本人通灵师自称相符。'
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

q, f = helpers('BV1ZmHX6iEcx')
update('c', 'BV1ZmHX6iEcx', 6,
       '纠正侧栏误读：本局为假面舞会，6号KS底牌狼人，1732秒原帧中6号侧栏没有通灵师或验人摘要。法官932.42秒明确5/6/9在警下；首日7号在警上结束前自爆，第二天刚天亮6号即自爆，未曾轮到6号公开发言。结合连续流程，6号不记信息神悍跳。',
       [q(932, 942, '首日5、6、9号在警下。'),
        q(1730, 1741, '首日7号在警上结束前自爆并入夜，6号无警下话轮。'),
        q(2011, 2035, '第二天6号直接自爆，随即公布夜死并再次入夜，6号仍没有本人公开话轮。'),
        q(3086, 3094, '终局复盘确认6号狼人自爆。'),
        f(1732, '本局假面舞会首日警长竞选末段；6号KS狼人一栏没有验人或通灵师文字，原解释误读该栏。'),
        f(2013, '第二天天亮时6号直接自爆的画面，尚未进行6号本人常规发言。')])

q, f = helpers('BV1gBhn6dEEJ')
path = PARTS / 'audit_b.json'
data = json.loads(path.read_text(encoding='utf-8'))
game = next(g for g in data['games'] if g['bvid'] == 'BV1gBhn6dEEJ')
row = next(a for a in game['assessments'] if a['seat'] == 4)
row['evidence'] = [q(1287, 1309, '法官交4号后，4号本人报验6号金水。'),
                   q(1380, 1398, '4号本人留10号警徽流，称7/9与自己对跳；不是7号此前验2/5的原话。'),
                   f(1310, '4号彭彭本人首日警上发言；其侧栏记录6号金水，与本轮原文相符。')]
row['decision_note'] = '4号本人在1287秒被点名后报验6号金水，留10号警徽流并讨论7/9谁与自己对跳；确认通灵师悍跳。已将此前误归给4号的7号验2/5片段替换为4号本人的证据。'
row = next(a for a in game['assessments'] if a['seat'] == 7)
row['evidence'] = [q(949, 983, '7号本人接6号之后发言，回顾上一局后报本局验9号为狼，并安排验2号。'),
                   q(1087, 1094, '7号本人明确验2再验5，要求金水继承警徽。'),
                   f(984, '7号申屠本人首日警上发言；7号狼位摘要随后保留验9查杀、警徽流2-5。')]
row['decision_note'] = '7号本人首日警上在949至1110秒话轮报9号为狼、留2/5警徽流。以本人完整话轮和原帧佐证通灵师悍跳，另人与其讨论查杀的句子不再作为主要证据。'
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

q, f = helpers('BV15PaW66EjW')
path = PARTS / 'audit_b.json'
data = json.loads(path.read_text(encoding='utf-8'))
game = next(g for g in data['games'] if g['bvid'] == 'BV15PaW66EjW')
row = next(a for a in game['assessments'] if a['seat'] == 9)
row.update(claim_day='later', actual_claim_day=3, first_day_claim=False,
           decision_note='9号荣耀为机械狼；6号首日自爆、5号次日自爆后，第三天9号在本人话轮明确说“我是通灵师”，编报三晚验人。属于第三天实际悍跳，不是第二天，也不是仅说明已获得技能；此前首日结果不追溯计成功。')
row['evidence'] = [q(906, 915, '6号首日自爆，随后公布首夜双死。'),
                   q(1292, 1309, '第二天再公布夜死、流徽并入夜，与第三天话轮区分。'),
                   q(2364, 2398, '第三天9号本人明确自称通灵师并报三晚验人，随后结束发言。'),
                   f(2365, '9号荣耀本人在第三天发言、明确自称通灵师的原帧；底牌为机械狼。')]
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

path = PARTS / 'audit_a.json'
data = json.loads(path.read_text(encoding='utf-8'))
for bvid, seat, windows, note in [
    ('BV1ddY46sEzY', 6, [(554, 590, '6号本人说明验8号并给金水，字幕中的“现在”结合后文“验八”还原语义。'),
                        (619, 630, '6号本人明确9/5警徽流并以8金水结束。')],
     '6号在本人首日警上话轮讨论自己的验人及警徽流，558秒明确说“验八”，结尾再报8号金水；结合9/5验人顺序，构成通灵师自称。原单句“看8号像好人”不足单独证明起跳，已补齐本人上下文。'),
    ('BV12sY36hEdr', 5, [(870, 880, '法官交5号，5号本人直接报验8号为狼。'),
                        (944, 966, '5号本人明确说“因为我是通灵师嘛”，再次说明验8号为狼。'),
                        (988, 998, '5号本人汇总1/11警徽流与8号查杀，再交6号。')],
     '5号首日警上本人直接自称通灵师，报验8号查杀并留1/11警徽流。主要证据已改为明确自称和报验，避免仅用“6/8开狼”的狼坑分析证明起跳。'),
]:
    quote, _ = helpers(bvid)
    game = next(g for g in data['games'] if g['bvid'] == bvid)
    row = next(a for a in game['assessments'] if a['seat'] == seat)
    row['decision_note'] = note
    row['evidence'] = [quote(lo, hi, meaning) for lo, hi, meaning in windows] + [e for e in row['evidence'] if e['kind'] == 'video_frame']
game = next(g for g in data['games'] if g['bvid'] == 'BV12sY36hEQh')
row = next(a for a in game['assessments'] if a['seat'] == 6)
row['decision_note'] = row['decision_note'].replace('以通灵师身份', '以预言家身份')
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
path = PARTS / 'audit_b.json'
data = json.loads(path.read_text(encoding='utf-8'))
game = next(g for g in data['games'] if g['bvid'] == 'BV1NBhU68EyT')
row = next(a for a in game['assessments'] if a['seat'] == 6)
row['claimed_role'] = '通灵师'
row['decision_note'] = '6号首日警上报验5号平民，先泛称要跳预言家，随即在642.29秒改称通灵师；本局机械狼通灵师板型，按其完整发言记录通灵师悍跳。'
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

q, f = helpers('BV1g1YU6kERd')
update('a', 'BV1g1YU6kERd', 4,
       '纠正引用语误判：4号先说“预言家肯定是”，随后模拟真预言家面对查杀对象的立场“你是狼、我是预言家、阵营不一样”，这是反驳3号的引语。本人紧接着认1号预言家、自称平民，结尾仍让1号归票；没有自己的验人或警徽流。第二天仅说听7/8狼人怎样讲，终局发动九尾狐技能，未发现本人信息神自称，故改为未悍跳。',
       [q(1818, 1845, '完整上下文先引入“预言家肯定是”的模拟立场，随后本人明确认1号预言家、自称平民。'),
        q(1895, 1904, '交给自己所站边的预言家及其金水分析，不能截断成独立自称。'),
        q(1928, 1947, '本人末尾再次确认1号预言家，并把沉底归票交1号。'),
        q(2977, 3015, '第二天本人只说听7/8里的狼人怎样讲，随后交6号。'),
        f(1844, '第一天4号自称平民、站边1号；4号九尾狐侧栏为标记技能信息，没有本人查验或警徽流。'),
        f(1900, '4号华仔仔本人首日警下发言；该段谈自己站边的预言家及金水，结合前后平民自称解读。')])

q, f = helpers('BV18Bhn6dEJ6')
path = PARTS / 'audit_b.json'
data = json.loads(path.read_text(encoding='utf-8'))
game = next(g for g in data['games'] if g['bvid'] == 'BV18Bhn6dEJ6')
row = next(a for a in game['assessments'] if a['seat'] == 8)
row['decision_note'] = '8号首日PK本人报验10号查杀，并称自己是被10号狼人搏中的预言家、留1号警徽流；原帧与本人话轮相符。已移除2224秒交10号之后10号的两句自称，避免以对跳者原话证明8号悍跳。'
row['evidence'] = [q(2032, 2042, '首日PK法官先交8号本人发言。'),
                   q(2131, 2149, '8号本人明确将自己描述为被10号狼人搏中的预言家。'),
                   q(2214, 2226, '8号汇总验10查杀、警徽流1号，然后法官才交10号；后续10号的自称与8号区分。'),
                   f(2134, '8号华仔仔本人首日PK发言；8号狼位侧栏为验10查杀及警徽流。'),
                   f(2216, '8号本人PK结尾再报验10号查杀的原画面，尚未交10号发言。')]
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Updated original details, speech attribution, claim day and direct self-claim evidence.')
