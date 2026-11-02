"""Facts read by the current conversation model; no model or database calls."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts'))
from analyze_incremental import normalized_segments, validate_candidate, sha256
from game_derivations import derive_game
from incremental_common import load_state, save_state, work_dir, write_json
from game_records import empty_event

NAMES = ['陈俊洁', '小鱼丸', '阿铖', '徐言雨', '耿许儿', '华仔仔',
         '董鲸鱼', '牛肉干', '葛小舞', 'Ted', '二妖', '小猪']
STATE = load_state(ROOT, 'S23')


class Game:
    def __init__(self, bv, roles, rounds, winner, identity_time, recap):
        self.item = next(x for x in STATE['items'].values() if x['entry']['bvid'] == bv)
        self.entry = self.item['entry']
        self.folder = work_dir(ROOT, 'S23', self.entry)
        self.input = json.loads((self.folder / 'input.json').read_text(encoding='utf-8'))
        self.c = deepcopy(self.input['skeleton'])
        self.g, self.v = self.c['dossier'], self.c['voting']
        self.source = ROOT / self.input['source_path']
        self.rows = normalized_segments(self.source)
        self.recap = recap
        blank = deepcopy(self.g['rounds'][0])
        self.g['rounds'] = [{**deepcopy(blank), 'number': n} for n in range(1, rounds + 1)]
        for round_ in self.g['rounds']:
            for phase in ('night','day'):
                for event in round_[phase]:
                    if event['slot'] == 'game_end': event['action'] = 'none'
        for seat, name, role in zip(self.g['seats'], NAMES, roles):
            seat.update(name=name, role=role, faction='werewolf' if role in {'狼人', '机械狼', '狼女孩', '捣蛋鬼'} else 'good')
        self.g.update(roster=NAMES, commentators=['大卫', '李舒服'], referee='豆儿啵', winner=winner)
        image = self.frame(identity_time)
        self.c['evidence'].append({'field': 'dossier.seats[1..12].name,role,faction', 'kind': 'image',
            'source_path': image, 'seconds': identity_time,
            'note': '连续法官复盘的全席真实身份页；按左至右、上至下逐座核对，与本局白天侧栏一致。机械平民为学习形态，物理底牌仍是机械狼。鲸鱼复用董鲸鱼、TED复用Ted。'})
        self.proof('dossier.seats[1..12].role; dossier.rounds; dossier.winner', *recap)
        post = next(x for x in self.input['weibo_sources'] if x['post_id'] == '5359741557277067')
        self.c['evidence'].append({'field': 'dossier.date,roster,commentators,referee,board',
            'kind': 'weibo', 'source_path': post['text_sources'][0],
            'note': '官方10月30日第七期阵容公告：12位选手、解说大卫/李舒服、法官豆儿啵，三局版型狼女孩/捣蛋鬼/机械狼通灵师。未按微博名单顺序分座。第三局跨午夜，按该节目比赛日10月30日归档。'})
        write_json(self.folder / 'review_display.json', {
            'identity_frames': [{'source_path': image, 'caption': '本局法官连续复盘 · 全部12席姓名与真实底牌（机械形态不改物理底牌）' if bv == 'BV17ox662EYG' else '本局法官连续复盘 · 全部12席姓名与真实底牌'}],
            'recap': {'source_path': self.input['source_path'], 'start_ms': int(recap[0]*1000), 'end_ms': int(recap[1]*1000)}})

    def frame(self, t):
        return (self.folder / 'frames' / f"{self.entry['bvid']}_{t:09.3f}.png").relative_to(ROOT).as_posix()

    def proof(self, field, a, b, note=None):
        rows = [r for r in self.rows if r['start_ms'] < b*1000 and r['end_ms'] > a*1000]
        assert rows, (field, a, b)
        e = {'field': field, 'kind': 'text', 'source_path': self.input['source_path'],
             'start_ms': rows[0]['start_ms'], 'end_ms': rows[-1]['end_ms'], 'quote': ''.join(r['text'] for r in rows)}
        if note: e['note'] = note
        self.c['evidence'].append(e)

    def event(self, n, phase, slot, action, actor=None, targets=(), result=None, votes=None, time=None):
        e = next(e for e in self.g['rounds'][n-1][phase] if e['slot'] == slot)
        e.update(action=action, actor=actor, targets=list(targets), result=result, votes=votes or [])
        if time: self.proof(f'dossier.rounds[{n}].{phase}.{slot}', *time)
        return e

    def signup(self, on, off, time):
        self.event(1, 'day', 'sheriff_candidates', 'register', targets=on, time=time)
        self.v['registrations'] = [{'id': 'registration-1', 'day': 1, 'on_police': on, 'off_police': off}]

    def ballot(self, n, kind, pairs, winner, time, candidates=None, number=1, stage='initial', tied=()):
        votes = [{'voter': voter, 'target': target, 'state': 'abstained' if target is None else 'cast'} for voter,target in pairs]
        self.v['ballots'].append({'id': f'{kind}-{n}-{number}', 'day': n, 'kind': kind,
            'number': number, 'stage': stage, 'status': 'complete', 'candidates': candidates,
            'eligible_voters': sorted(voter for voter,target in pairs), 'votes': votes,
            'tied_candidates': list(tied), 'winner': winner, 'unrecorded_voters': []})
        e = next(e for e in self.g['rounds'][n-1]['day'] if e['slot'] == f'{kind}_vote')
        e['action'] = 'vote'
        e['votes'].extend({'round': number, 'voter': voter, 'target': target, 'abstained': target is None} for voter,target in pairs)
        self.proof(f'voting.ballots.{kind}-{n}-{number}', *time)

    def blow(self, n, actor, time):
        self.event(n,'day','self_destruct','self_destruct',actor,result='自爆中断当日流程',time=time)
        self.event(n,'day','exile_vote','not_held',result='自爆中断，未举行放逐投票')
        self.event(n,'day','exile_result','none',result='自爆中断，未进行放逐')
        self.v['interruptions'].append({'id': f'interruption-{n}', 'day':n, 'actor':actor, 'reason':'self_destruct','ends_day':True})

    def finish(self):
        self.c = validate_candidate(self.c, self.entry, self.source)
        rules = derive_game(self.c['dossier'], self.c['voting'])
        write_json(self.folder / 'rule_derivations.json', rules['derivations'])
        write_json(self.folder / 'candidate.json', self.c)
        self.item.update(analysis='ready', candidate_sha256=sha256(self.folder/'candidate.json'),
                         source_path=self.input['source_path'], source_sha256=self.input['source_sha256'])
        self.item.pop('analysis_error', None)
        d = rules['derivations']
        print(self.entry['bvid'], 'ballots', len(self.v['ballots']), 'issues', json.dumps(d.get('issues'),ensure_ascii=False),
              'review_tasks',json.dumps(d.get('review_tasks'),ensure_ascii=False), 'vote_tasks',json.dumps(d.get('vote_review_tasks'),ensure_ascii=False))


def wolf_girl():
    x=Game('BV1Eox662EE8', ['狼女孩','狼人','平民','平民','狼人','平民','预言家','毒师','狼人','平民','守卫','猎人'],4,'good',8248,(8238,8316.5))
    x.proof('dossier.board; rules.wolf_girl',1264.2,1356.9,'标题误写预女猎白混；官方公告、规则片与法官复盘一致确认狼女孩。')
    x.event(1,'night','wolf_girl_confession','confess',1,[8],'表白失败；8号为毒师，保持好人阵营，未成为狼伴侣',time=(8254,8264))
    x.event(1,'night','wolf_attack','forbidden',result='狼女孩版型首夜狼队不得刀人',time=(1264.2,1295.6))
    x.event(1,'night','guard','pass',11,time=(8262,8267))
    x.event(1,'night','witch_poison','pass',8,result='首夜未用毒；第二夜首次用毒杀1号，单次资源唯一确定首夜保留')
    x.event(1,'night','seer_check','check',7,[10],'good',time=(8265,8271))
    x.signup([1,2,3,4,5,6,7,8,10,11,12],[9],(1888.9,1910))
    x.ballot(1,'sheriff',[(9,1)],1,(3140,3184),candidates=[1,7,8,12])
    x.event(1,'day','sheriff_result','elected',targets=[1],result='1号当选警长')
    x.event(1,'day','badge','hold',1)
    x.event(1,'day','night_deaths','peaceful',time=(3160,3191))
    x.ballot(1,'exile',[(n,7 if n in [1,2,3,5,6,8,9,12] else 1) for n in range(1,13)],7,(5172,5218))
    x.event(1,'day','exile_result','exile',targets=[7],result='7号8.5票出局；狼女孩未发动投票后自爆',time=(5194,5220))
    x.event(1,'day','self_destruct','none')
    x.event(2,'night','guard','guard',11,[3],time=(8274,8282))
    x.event(2,'night','wolf_attack','attack',targets=[6],time=(8274,8282))
    x.event(2,'night','witch_poison','poison',8,[1],'毒杀1号狼女孩',time=(8278,8285))
    x.event(2,'day','night_deaths','die',targets=[1,6],result='1号毒死、6号刀死',time=(5627,5645))
    x.event(2,'day','badge','transfer',1,[5],time=(5642,5654))
    extra=empty_event('badge',5);extra.update(action='transfer',targets=[3],result='5号被放逐后将警徽移交3号')
    x.g['_publication_context']={'supplemental_events':[{'round':2,'phase':'day','event':extra}]}
    x.proof('dossier._publication_context.supplemental_events.badge',7180,7204)
    x.ballot(2,'exile',[(2,10),(3,10),(4,5),(5,10),(8,5),(9,10),(10,5),(11,5),(12,5)],5,(6998,7037))
    x.event(2,'day','exile_result','exile',targets=[5],result='5号5票出局')
    x.event(2,'day','self_destruct','none')
    x.event(3,'night','guard','guard',11,[11],time=(8291,8298))
    x.event(3,'night','wolf_attack','attack',targets=[8],time=(8291,8300))
    x.event(3,'day','night_deaths','die',targets=[8],result='8号毒师刀死',time=(7356,7379))
    x.event(3,'day','badge','hold',3)
    x.blow(3,9,(8074,8093))
    x.event(4,'night','guard','guard',11,[4],time=(8300,8309))
    x.event(4,'night','wolf_attack','attack',2,[3],time=(8300,8310))
    x.event(4,'day','night_deaths','die',targets=[3],result='3号平民刀死',time=(8207,8220))
    x.event(4,'day','game_end','surrender',2,result='2号狼人选择交牌，游戏结束，好人阵营获胜',time=(8308,8316.5))
    x.event(4,'day','exile_vote','not_held',result='交牌结束，未举行放逐投票')
    x.event(4,'day','exile_result','none',result='交牌结束，未进行放逐')
    x.event(4,'day','self_destruct','none',result='本日直接交牌')
    x.g['_publication_context']['terminal_observation']={'round':4,'phase':'day','basis':'judge_recap_and_observed_surrender'}
    x.v['days']=[{'day':n,'sheriff':'recorded' if n==1 else 'not_applicable','exile':'recorded' if n<3 else 'interrupted_self_destruct' if n==3 else 'none'} for n in range(1,5)]
    x.finish()


def troublemaker():
    x=Game('BV1Eox662EVZ',['女巫','狼人','守卫','捣蛋鬼','预言家','猎人','平民','平民','狼人','狼人','平民','平民'],4,'werewolf',5800,(5797,5904.3))
    x.proof('rules.troublemaker',350,660.6)
    x.event(1,'night','troublemaker_action','trouble',4,[7],'目标为平民，无主动技能',time=(5814,5823))
    x.event(1,'night','guard','pass',3,time=(5814,5825))
    x.event(1,'night','wolf_attack','attack',targets=[6],time=(5820,5826))
    x.event(1,'night','witch_save','save',1,[6],time=(5820,5826))
    x.event(1,'night','witch_poison','pass',1,result='毒药后夜仍未使用，首夜保留')
    x.event(1,'night','seer_check','check',5,[3],'good',time=(5825,5834))
    x.signup([1,2,3,4,5,6,8,10,12],[7,9,11],(1208,1235))
    x.ballot(1,'sheriff',[(7,5),(9,5),(11,5)],5,(2843,2893),candidates=[2,5,10,12])
    x.event(1,'day','sheriff_result','elected',targets=[5],result='5号三票当选警长')
    x.event(1,'day','night_deaths','peaceful',time=(2880,2900))
    x.ballot(1,'exile',[(1,2),(2,5),(3,5),(4,2),(5,2),(6,5),(7,2),(8,5),(9,5),(10,None),(11,2),(12,5)],5,(4930,4968))
    x.event(1,'day','exile_result','exile',targets=[5],result='5号六票出局；10号原文明确弃票',time=(4950,4970))
    x.event(1,'day','badge','transfer',5,[6],time=(5096,5124))
    x.event(1,'day','self_destruct','none')
    x.event(2,'night','troublemaker_action','trouble',4,[1],'女巫当夜未用药',time=(5839,5854))
    x.event(2,'night','guard','guard',3,[1],time=(5841,5853))
    x.event(2,'night','wolf_attack','attack',targets=[1],result='实际击杀被守护的1号，狼刀未造成死亡',time=(5841,5853))
    x.event(2,'night','witch_poison','pass',1,time=(5849,5853))
    x.event(2,'day','night_deaths','peaceful',time=(5380,5399))
    x.blow(2,10,(5384,5411))
    x.event(3,'night','troublemaker_action','trouble',4,[3],'本次守护实际作用于守卫本人',time=(5853,5872))
    x.event(3,'night','guard','guard',3,[2],'原守护2号狼人；因捣蛋实际守护3号守卫自己',time=(5856,5869))
    x.event(3,'night','wolf_attack','attack',targets=[1],time=(5867,5875))
    x.event(3,'night','witch_poison','pass',1,result='法官复盘确认继续空过；局中叫醒有争议，未补造用毒',time=(5867,5874))
    x.event(3,'day','night_deaths','die',targets=[1],result='1号女巫刀死',time=(5611,5631))
    x.blow(3,2,(5625,5643))
    x.event(4,'night','troublemaker_action','trouble',4,[6],'当夜屠神终局，未进入猎人开枪窗口',time=(5874,5903))
    x.event(4,'night','guard','guard',3,[3],'3号守卫主动自守；前夜受捣蛋实际自守，本夜连续实际两夜自守，被法官判定当夜倒牌（本局特殊结算）',time=(5881,5898))
    x.event(4,'night','wolf_attack','attack',9,[6],result='击杀6号猎人',time=(5894,5903))
    x.event(4,'night','game_end','end',result='3号守卫因连续实际自守倒牌、6号猎人刀死，3号6号双死；狼队屠神，游戏结束，未进入第四天白天',time=(5881,5904.3))
    x.event(4,'day','night_deaths','die',targets=[3,6],result='3号特殊结算倒牌、6号刀死；夜间游戏结束，未进入第四天白天',time=(5894,5904.3))
    x.event(4,'day','hunter_shot','unavailable',6,result='末神出局夜间直接终局，无后续开枪窗口')
    x.g['_publication_context']={'terminal_observation':{'round':4,'phase':'night','basis':'judge_special_resolution'}}
    x.v['days']=[{'day':n,'sheriff':'recorded' if n==1 else 'not_applicable','exile':'recorded' if n==1 else 'interrupted_self_destruct'} for n in range(1,4)]
    x.finish()


def mechanical():
    x=Game('BV17ox662EYG',['平民','机械狼','守卫','女巫','通灵师','平民','平民','狼人','平民','猎人','狼人','狼人'],5,'good',6158,(6153,6226.4))
    x.g['seats'][1].update(learning_target=7,learned_role='机械平民')
    x.event(1,'night','guard','pass',3,time=(6165,6173))
    x.event(1,'night','wolf_attack','attack',targets=[2],time=(6169,6175))
    x.event(1,'night','witch_save','save',4,[2],time=(6169,6175))
    x.event(1,'night','witch_poison','pass',4,result='第二夜首次用毒，首夜保留毒药')
    x.event(1,'night','mechanical_action','learn',2,[7],'机械平民',time=(6172,6178))
    x.event(1,'night','seer_check','check',5,[10],'猎人',time=(6175,6181))
    x.signup([1,2,3,5,7,8,9,10,12],[4,6,11],(1048,1074))
    x.event(1,'day','night_deaths','peaceful',result='现场在12号自爆后公布首夜平安夜',time=(1776,1797))
    x.blow(1,12,(1749,1798))
    x.event(1,'day','sheriff_result','deferred',result='首日警长竞选被12号自爆中断，延期次日')
    x.event(1,'day','sheriff_vote','not_held')
    x.event(1,'day','badge','none',result='竞选延期，警徽尚未产生')
    x.event(2,'night','guard','guard',3,[4],time=(6181,6189))
    x.event(2,'night','wolf_attack','attack',targets=[5],time=(6182,6190))
    x.event(2,'night','witch_poison','poison',4,[11],'毒杀11号狼人',time=(6185,6191))
    x.event(2,'night','seer_check','check',5,[6],'平民',time=(6188,6194))
    x.event(2,'day','sheriff_candidates','continued',result='继续首日未完成的警长竞选')
    x.event(2,'day','night_deaths','die',targets=[5,11],result='5号刀死、11号毒死；现场在8号自爆后公布',time=(2029,2054))
    x.blow(2,8,(2022,2034))
    x.event(2,'day','badge','none',result='badge_lost')
    x.event(2,'day','sheriff_result','none',result='次日再次自爆，警徽流失')
    x.event(2,'day','sheriff_vote','not_held')
    x.event(3,'night','guard','guard',3,[3],time=(6194,6202))
    x.event(3,'night','wolf_attack','attack',2,[3],result='机械狼接刀后击杀3号；目标被自守，实际未死亡',time=(6194,6203))
    x.event(3,'night','mechanical_knife_status','carrying',2,result='普通狼8号、11号、12号均已出局，2号机械狼接刀')
    x.event(3,'day','night_deaths','peaceful',time=(2230,2253))
    x.ballot(3,'exile',[(1,9),(2,7),(3,1),(4,1),(6,9),(7,1),(9,7),(10,7)],None,(3540,3584),tied=[1,7])
    x.ballot(3,'exile',[(2,1),(3,7),(4,None),(6,7),(9,7),(10,7)],7,(3963,3996),candidates=[1,7],number=2,stage='pk')
    x.event(3,'day','exile_result','exile',targets=[7],result='首轮1号7号各三票平票，PK复投7号四票出局')
    x.event(3,'day','self_destruct','none')
    x.event(4,'night','guard','guard',3,[6],time=(6203,6213))
    x.event(4,'night','wolf_attack','attack',2,[3],time=(6205,6215))
    x.event(4,'day','night_deaths','die',targets=[3],result='3号守卫刀死',time=(4291,4310))
    x.ballot(4,'exile',[(1,9),(2,9),(4,2),(6,9),(9,2),(10,9)],9,(5360,5389))
    x.event(4,'day','exile_result','exile',targets=[9],result='9号四票出局')
    x.event(4,'day','self_destruct','none')
    x.event(5,'night','wolf_attack','attack',2,[4],time=(6213,6221))
    x.event(5,'day','night_deaths','die',targets=[4],result='4号女巫刀死',time=(5525,5554))
    x.ballot(5,'exile',[(1,2),(2,1),(6,2),(10,2)],2,(6110,6130))
    x.event(5,'day','exile_result','exile',targets=[2],result='2号机械狼三票出局，游戏结束，好人阵营获胜',time=(6122,6130))
    x.event(5,'day','self_destruct','none')
    x.g['_publication_context']={'terminal_observation':{'round':5,'phase':'day','basis':'judge_last_wolf_exiled'}}
    x.v['days']=[{'day':n,'sheriff':'deferred' if n==1 else 'badge_lost','exile':'interrupted_self_destruct' if n<3 else 'recorded'} for n in range(1,6)]
    x.finish()


if __name__ == '__main__':
    wolf_girl()
    troublemaker()
    mechanical()
    save_state(ROOT, 'S23', STATE)
