"""Materialize the primary reviewer's five source-read and visually checked games."""
from pathlib import Path
import hashlib
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from website.api.bluffs import physical_wolf


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def build(bvid,frame_sec,start,end,basis,decisions,extra_frames=None):
    folder=next((ROOT/'data/games/S23').glob('*'+bvid))
    dossier=json.loads((folder/'dossier.json').read_text(encoding='utf-8'))
    entry=json.loads((ROOT/'data/extractions/S23/game_reviews'/bvid/'entry.json').read_text(encoding='utf-8'))
    source=ROOT/entry['source_path']
    raw=json.loads(source.read_text(encoding='utf-8'))
    segments=[{'start_ms':r.get('start_ms',round(r.get('from',0)*1000)),
               'end_ms':r.get('end_ms',round(r.get('to',0)*1000)),
               'text':r.get('text',r.get('content',''))} for r in raw.get('body',raw.get('segments',[]))]
    def quote(lo,hi,interpretation):
        selected=[s for s in segments if round(lo*1000)<=s['start_ms']<round(hi*1000)]
        assert selected,(bvid,lo,hi)
        return {'kind':'transcript','source_path':entry['source_path'],'source_sha256':sha(source),
                'start_ms':selected[0]['start_ms'],'end_ms':selected[-1]['end_ms'],
                'text':'\n'.join(s['text'] for s in selected),'interpretation':interpretation}
    def frame(sec,text):
        path=ROOT/'data/extractions/S23/bluff_review/frames'/bvid/f'{bvid}_{sec:09.3f}.png'
        assert path.is_file(),path
        return {'kind':'video_frame','source_path':path.relative_to(ROOT).as_posix(),'source_sha256':sha(path),
                'start_ms':round(sec*1000),'end_ms':round(sec*1000),'frame_time_ms':round(sec*1000),
                'text':text,'interpretation':'主审已目视原帧；以正式底牌定位座位，并与本人原文和前后流程交叉判断。'}
    rows=[]
    seats={s['seat']:s for s in dossier['seats'] if physical_wolf(dossier,s)}
    assert set(seats)==set(decisions)
    for number,(decision,role,note,windows,overlay) in decisions.items():
        seat=seats[number]
        evidence=[quote(lo,hi,meaning) for lo,hi,meaning in windows]+[frame(frame_sec,overlay)]
        for sec,text in (extra_frames or {}).get(number,[]):evidence.append(frame(sec,text))
        rows.append({'seat':number,'name':seat['name'],'physical_role':seat['role'],'decision':decision,
                     'claimed_role':role,'claim_day':1 if decision=='yes' else None,
                     'first_day_claim':decision=='yes','verification_status':'assistant_inferred',
                     'decision_note':note,'evidence':evidence,'review_questions':[]})
    main=frame(frame_sec,'首日竞选末段原视频截图')
    return {'game_id':dossier['slug'],'bvid':bvid,'date':dossier['date'],'game_number':dossier['game_number'],
            'source_path':entry['source_path'],'source_sha256':sha(source),
            'first_day_window':{'start_ms':round(start*1000),'end_ms':round(end*1000),'basis':basis},
            'frame_selection':{'timestamp_ms':round(frame_sec*1000),'basis':basis,
                               'phase_verified':True,'visual_reviewed':True,'overlay_readable':True,
                               'frame_path':main['source_path'],'frame_sha256':main['source_sha256']},
            'assessments':rows,'separate_identity_claims':[],'notes':['全部判断为主审助手推断；未新增用户确认。']}


games=[]
games.append(build('BV1UNaQ6kEWR',1270,357.62,2825,
    '357.62s天亮、372.13s上警；1278.17s警上发言结束。选末位1号结束前约8秒；首日在2820.76s六号自爆后入夜。',{
 1:('no',None,'1号首日警上评论2/3/9/11的发言并倾向8号，没有把建议别人验9说成自己验9；结合其本人完整话轮和侧栏，不记信息神自称。',
    [(1175.24,1197.22,'1号评价十一号与其他玩家，没有自称信息神。'),(1248.33,1278.17,'1号明确表示偏向8号并结束发言。')],'1号假面侧栏为「2打11有些生硬」。'),
 5:('no',None,'5号警下明确以狼人身份讨论听神、传递信息和准备自爆，未自称预言家或通灵师。其认狼与6号已经作出的悍跳分开。',
    [(2563.82,2573.70,'5号公开认狼并说明听身份的意图。'),(2623.64,2638.22,'5号讨论与6号依次自爆，不是本人起跳。')],'5号物理底牌为狼人；本帧该行没有验人或警徽流摘要。'),
 6:('yes','预言家','6号在本人警上话轮明确说「因为我是预言家」，报9号查杀并安排警徽流；末位截图也保留相同验人摘要。之后认狼、自爆不抹去此前已经发生的尝试。',
    [(635.72,638.52,'本人报告9号为狼。'),(695.84,701.02,'本人明确自称预言家。'),(678.57,689.87,'本人安排验人与警徽流。')],'6号狼人侧栏显示「验9查杀」「警徽流12-10」。'),
 10:('no',None,'10号警上自称好人，主要抿2/5/6/9/12的身份；警下仍围绕狼坑和站边6号发言，未把他人报验说成自己查验。',
     [(463.17,480.99,'10号自己的首日发言是好人表水和抿身份。'),(1536.90,1542.58,'警下仍自称好人并讨论狼坑。'),(1652.60,1657.65,'警下给出站边，不是本人信息神起跳。')],'10号狼人侧栏为「2-5-6-9-12都像身份」。'),
}))
games.append(build('BV1K3aQ6zEB9',1626,566.01,3189,
    '566.01s首日天亮、599.46s上警，1634.39s警上发言结束；选末位1号结束前约8秒。3181.67s七号自爆中断首日。',{
 3:('no',None,'3号说「刚刚他要是不退水的话，哥们就原地跳一个通灵师」是在解释未执行的假设方案。警下实际自称的是猎人；不把条件句里的拟报金水计成已实施的悍跳。',
    [(1314.92,1333.20,'过去条件句中的起跳计划。'),(3052.23,3059.95,'当日警下实际自称猎人。'),(3144.37,3154.95,'本人再次说明猎人身份与警上要求听PK的意思。')],'3号狼人侧栏为听报身份及评价6/7发言，并非本人验人摘要。'),
 7:('no',None,'7号警上站边11号并评论9号给8号查杀；警下公开自称女巫。她的角色谎言不是预言家或通灵师自称，不计本项悍跳。',
    [(939.28,960.99,'7号对11号和9号发言作站边判断。'),(1815.01,1818.20,'本人警下自称女巫。')],'7号狼人侧栏显示「我站边11号」。'),
 9:('yes','通灵师','9号本人先报验8号为狼、留2/3/4警徽流，警下又解释「我给耀子发个查杀」「他们以为我是通灵师」。两轮本人发言互证，这是机械狼伪装查验神的尝试，并非仅公开自己获得技能。',
    [(765.17,770.00,'9号自己报8号为狼。'),(810.60,825.28,'自己的警徽流和验人。'),(2095.29,2104.12,'本人回顾先前报查杀是为让人认作通灵师。')],'9号机械狼侧栏保留「验8查杀」和警徽流；上方「学7机械双刀」是观众身份信息，未单独当作本人自称。'),
 11:('yes','通灵师','11号在首日首个本人话轮明确说「我是通灵师」，报5号金水；警下继续维持通灵师自称。末位截图中的摘要后来改为其他讨论，不能据此漏记前面的明确起跳。',
     [(613.59,624.00,'本人报验5号金水并给出验人顺序。'),(642.40,650.32,'本人明确自称通灵师。'),(2453.30,2455.80,'首日警下仍自称通灵师。')],'11号狼人末位截图摘要已变为讨论其他玩家；为避免单帧漏记，另附其首日首个话轮画面。'),
},extra_frames={11:[(651,'11号又又正在首日首个警上话轮发言；时间与其642.40s自称通灵师的转写相连。')]}))
games.append(build('BV123aQ6BEu2',1527,494.52,1538,
    '494.52s首日天亮；末位1号发言期间六号自爆，1533.39s宣布昨夜信息、1537.02s入夜。选自爆前约6秒原帧，并交叉次日十二号自爆前流程。',{
 6:('yes','通灵师','6号本人在警上报验12号、安排12/2的警徽流，画面最后留下「验12平民」的具体身份反馈。结合本局通灵师板型，推断为通灵师悍跳；随后自爆仍计这次尝试。',
    [(1013.54,1026.51,'本人实际报验12号。'),(1033.06,1059.91,'继续安排自己的警徽流。'),(1071.41,1078.97,'本人继续讨论查验信息及身份是否公开。')],'6号狼人末位侧栏可见「验12平民」。'),
 8:('yes','通灵师','8号本人在首日警上明确说「这把我是通灵师」，报4号金水，留12/9警徽流；画面摘要吻合。不能因其先前曾讨论别人身份而漏掉后面的直接自称。',
    [(777.26,791.13,'本人说通灵师验4号金水。'),(804.59,806.75,'本人直接说这把我是通灵师。'),(829.29,837.70,'本人留下12/9警徽流。')],'8号狼人摘要显示「验4金水」「警徽流12-9」。'),
 9:('no',None,'9号本轮讨论的是10号说法能排除哪些身份，并明确表示不站边任何自称通灵师的人。他没有把这些排除结论说成自己的夜间查验；与上一局9号实际报查杀的行为不同。',
    [(673.86,710.70,'9号是在评论10号的说法和由此得出的排除结论。'),(733.22,735.28,'本人自称好人。'),(755.77,769.94,'本人讨论别人是否应跳通灵师，而非自称。')],'9号机械狼侧栏为学习8号后的机械双刀和排除身份结论，没有本人查验/警徽流自称。'),
 12:('no',None,'12号首日在警下，六号在警上末位尚未结束时自爆；12号没有自己的首日发言轮。次日仍未开始常规发言便宣布12号自爆并再次入夜；结合两个完整中断流程，未观察到其信息神自称。',
     [(1531.77,1538.00,'六号自爆结束首日，警下十二号尚无本人话轮。'),(1871.27,1897,'次日十二号直接自爆、流徽并入夜。')],'12号狼人本帧在警下，无本人验人/警徽流摘要；此项同时依靠前后中断流程而非只凭空白摘要。'),
}))
games.append(build('BV17xpA6aE77',2028,1270.06,4993,
    '1270.06s首日天亮；2036.58s首轮警上发言结束，选末位7号末段。再核2373s起5号PK话轮、警下4号和4991.19s实际入夜前流程。',{
 2:('no',None,'2号首日警上解释要继续听后面的起跳，并自称好人；没有自己报验人。其站边和投票不能代替信息神自称。',
    [(1428.67,1469.61,'2号等后置位是否继续起跳，讨论5号是否退水。'),(1478.99,1491.59,'本人自称好人后结束发言。')],'2号狼人侧栏为「听听后面起跳的」。'),
 4:('no',None,'4号警下完整话轮3371–3536s解释第一票给5、PK后改站9，明确把9号认作预言家，自己表好人。建议别人验人或分析警徽流不等于本人起跳。',
    [(3371.36,3393.12,'本人解释站边9号预言家的判断。'),(3482.07,3486.59,'承认5号脱衣后自己在8/9里选9。'),(3533.86,3536.80,'本人最终站9、表好人。')],'首日末位警上帧中4号在警下；另以3450s本人警下发言画面核实其话轮。'),
 5:('yes','预言家','5号首日警上明确说自己抽到预言家，报3号金水并留4/11警徽流。后来脱衣改称混血儿，不抹去此前已经公开实施的预言家自称。',
    [(1354.57,1361.25,'本人明确说抽到预言家牌。'),(1367.63,1384.29,'本人报告3号金水。'),(1384.29,1423.02,'本人给出4/11警徽流，并重复起跳与验人。')],'5号狼人摘要可见「验3金水」「警徽流4-11」。'),
 8:('yes','预言家','8号本人首日警上报验6号金水、留10/3警徽流，并与9号预言家竞争警徽；PK继续保持同一验人。底牌为狼人，构成本局预言家悍跳。',
    [(1813.22,1825.74,'本人报6号金水和10/3验人顺序。'),(1874.28,1879.00,'再次以自己的查验说明6号不是狼混。')],'8号狼人首轮摘要显示「验6金水」「警徽流10-3」；PK尾部改留11-4但仍保留同一金水。'),
},extra_frames={4:[(3450,'4号徐言雨在警下发言，画面姓名牌和本局狼位对应；与其站9号及表好人的原文互证。')],8:[(2395,'8号PK后的侧栏仍为验6金水，警徽流改为11-4；当前发言画面是5号，未把中心人物误归给8号。')]}))
games.append(build('BV17xpA6aE7N',3008,1076.53,3569,
    '1076.53s法官确认全员上警；末位12号报验11后，11号接话讨论直到3017.47s发言结束。选该结束点前约9秒原帧；首日3567.01s入夜。',{
 1:('no',None,'1号在本人首日警上话轮明确说「我肯定不跳呀」，随后分析10号和后置11/12是否会对跳，没有本人信息神自称。',
    [(2453.56,2464.15,'本人明确不跳并说明与自己无关。'),(2481.23,2489.20,'本人等待11/12是否起跳。'),(2617.40,2626.03,'仍等待后置对跳、考虑6/7PK，而非自称。')],'1号狼人摘要为觉得4有点像狼枪、3不是很像狼，未出现自己的验人或警徽流。'),
 2:('no',None,'2号盗宝大师在本人话轮讨论后面谁可能与10号对跳，自称好人并要求后置位起跳；没有公开自称预言家或通灵师。盗宝本身及余牌技能不直接计作悍跳。',
    [(2277.57,2293.54,'本人等待其他人跳通灵师与10号对跳。'),(2394.19,2400.35,'本人以好人身份讨论局面。'),(2434.07,2448.82,'本人邀请后置位起跳而非自己起跳。')],'2号盗宝大师侧栏为「站边7号民」，并非验人/警徽流自称。'),
 6:('no',None,'6号本人首日话轮认可10号像通灵师，并表示大概率不投后置起跳者；提到通灵师的句子主体是10号，没有把他人的身份说成自己身份。',
    [(1667.80,1675.81,'本人把10号认作通灵师。'),(1713.10,1734.21,'本人解释对后置起跳的站边规则。'),(1793.25,1818.66,'本人点评其他座位，并明确仍称10号通灵师。')],'6号狼人侧栏为「我觉得10很像」。'),
 12:('yes','通灵师','12号狼王本人在首日末位报验11号金水并安排查验3/2，且明说要让大家判定自己是通灵师；截图侧栏与原文互证。不是只凭狼王身份或上警推定。',
     [(2630.98,2646.70,'本人报金水并判断10号是小狼。'),(2710.38,2719.53,'本人以自己的查验说明谁是通灵师。'),(2778.86,2786.04,'本人安排查验3/2。'),(2809.84,2818.90,'本人说以这些验人让大家判定自己是通灵师。')],'12号狼王摘要为「验11金水」，并把10划作狼、6判断为狼枪。'),
}))

out=ROOT/'data/extractions/S23/bluff_review/parts/audit_d.json'
out.write_text(json.dumps({'part':'d','reviewer':'primary_assistant','games':games},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'games':len(games),'assessments':sum(len(g['assessments']) for g in games)},ensure_ascii=False))
