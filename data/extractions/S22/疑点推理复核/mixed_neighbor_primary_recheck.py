import pathlib,sys,json
ROOT=pathlib.Path('.').resolve();sys.path.insert(0,str(ROOT/'scripts'));import batch_s22 as batch
from s22_inference_review import changed_value
B=ROOT/'data/extractions/S22/疑点推理复核';plan=batch.read_json(B/'mixed_neighbor_plan.json');queue={x['bvid']:x for x in batch.read_json(B/'mixed_neighbor_queue.json')['items']}
def E(n,s,f,p='night'):return {'kind':'event','number':n,'phase':p,'slot':s,'fields':f}
def A(n,t):return E(n,'wolf_attack',{'action':'attack','targets':[t],'result':None})
def D(n,t):return E(n,'night_deaths',{'action':'die','targets':t,'result':None},'day')
def S(n,slot,actor,target):return E(n,slot,{'action':'shoot','actor':actor,'targets':[target],'result':None},'day')
def P(n,actor,slot='witch_poison'):return E(n,slot,{'action':'pass','actor':actor,'targets':[],'result':None})
def H(n):return E(n,'sheriff_result',{'action':'deferred','targets':[],'result':None},'day')
def fix(b,changes,why,start=None,end=None):
 g=next(g for g in plan['games'] if g['bvid']==b);x=queue[b];folder=ROOT/x['entry']['output_dir'];r=batch.read_json(folder/'复核记录.json');segs=r.get('recap_segments',[])
 if start is not None:segs=[s for s in batch.load_segments(ROOT/x['entry']['source_path']) if s['end_ms']>=start and s['start_ms']<=end]
 ev={'path':x['entry']['source_path'],'start_ms':segs[0]['start_ms'],'end_ms':segs[-1]['end_ms'],'quote':'\n'.join(s['text'] for s in segs)}
 for d in g['decisions']:
  if not d['resolved']:
   d.update(resolved=True,conclusion=why,reason=why,basis='context',confidence='high',evidence=[ev])
 g['changes']+=changes;g['summary']=g.get('summary','')+' 主代理二次核实：'+why
 changed_value(batch.read_json(folder/'dossier.json'),g['changes']);batch.atomic_json(B/'mixed_neighbor_plan.json',plan);print(b,'root verified',flush=True)
fix('BV1sKJ56PEey',[E(1,'mixed_blood_model',{'action':'choose','actor':8,'targets':[7],'result':None})], '身份名单明确混血儿8号，行动句明确“混血儿选择7号女巫为榜样”；旧候选把女巫7误作混血行动者、把被救狼人2误当榜样，应选择8→7。')
fix('BV18ijD6BExh',[D(2,[4,5])], '第二夜刀5号女巫、女巫毒4号狼人；首夜解药已救1号混血儿，本版无守卫、交换或机械盾，5号无法自救，4号中毒无其他保护，故当夜出局4/5，不能因为省略播报双死就保留未知。')
fix('BV1QAjo6sEEc',[S(1,'hunter_shot',8,5),E(1,'badge',{'actor':5},'day')], '第一天“8号猎人被抗推出局，发动技能带走。5号狼人警徽移交至7号狼人混”应跨行连读为8开枪带5，5原先持警徽并移交7，两个事实互相印证；目标并未真正缺失。')
fix('BV1Pt7v6XEP4',[P(2,4)], '原文“女巫技能通过4号带毒女巫单死”是女巫空过、4号带着尚未用出的毒药死去；只有4号单死，赛后也说“还没开毒”。不能把“带毒”误解成已经毒杀未知目标，应记毒药pass，不补毒杀。')
fix('BV1gvTi66EFF',[H(1)], '首日警上7号自爆后入夜，次日明确“在延期竞选环节”9号再次自爆、警徽流失，说明首日未完成竞选，应记录deferred，第二日才流失，不需要猜警长当选者。')
fix('BV1BjMh63EEK',[], '复盘明确“给出的道路是4号3号，狼人阵营屠神获胜”；身份名单4号白神、3号猎人，另两神6预言家已放逐、11女巫已中刀，故拍刀4/3是剩余两神的明确终局目标。道路是刀路的ASR误写，不是未知编号；拍刀不是狼王开枪，目标与胜方保留结论。')
fix('BV11uMG6PEkr',[A(2,3),D(2,[3,11]),A(3,10),D(3,[10])], '两次狼刀都只是跨字幕断开：第二夜“入夜狼人击杀，3号预言家牛毒杀11号平民”对应刀3毒11；第三夜“如夜郎击杀。10号女巫白天9号猎人被攻投”对应刀10，之后才白天放逐9。本版无保护，首夜已用解药，3/11和10出局可确定。')
fix('BV1sEN86gEM2',[H(1)], '首日6号警上自爆后入夜，原文次日明确“第二天延期…警长环节”且8自爆后警徽流失，首日结果是竞选延期而非当选或直接徽流失。')
fix('BV1BPNB6QE1s',[], '赛中终局播报“拍到3号4号…获胜”和赛后复盘“刀路3号平民和4号混血儿、拍刀成功、屠民赢”独立相互印证，目标与狼人胜均明确。其余平民2号已放逐、6号已中刀，剩余民3和好人混4的刀路与屠民终局一致；不写成狼枪。')
fix('BV1oNKY6zE1Z',[E(2,'badge',{'action':'none','actor':6,'targets':[],'result':None},'day'),E(2,'self_destruct',{'action':'self_destruct','actor':11,'targets':[],'result':None},'day'),E(3,'exile_result',{'action':'exile','targets':[9],'result':None},'day')], '第一天明确6号悍跳狼人获得警徽，7号预言家从未持徽；第二夜6号被毒，次日“6号将警徽撕掉”行动者6无冲突。随后11号自爆、入夜刀5女巫，第三天最后狼9被放逐，轮次和徽归属均可恢复。')
fix('BV1iMgq6ZE5t',[{'kind':'seat','seat':8,'fields':{'role':'女巫','faction':'good'}},E(1,'witch_save',{'action':'save','actor':8,'targets':[3],'result':None}),E(1,'night_deaths',{'action':'peaceful','targets':[],'result':None},'day')], '跨行身份表是预言家9、女巫8、猎人2、白神11；首夜狼刀3被8救、明确平安夜，本局对应复盘根本没有首夜2/3双死。第二夜4/9双死才是实际双死。终局拍刀2号猎人失败，而8号女巫仍在场，因此不能因失败推翻猎人2/女巫8的名单。')
fix('BV12m3J6wE3m',[P(1,11,'witch_save'),P(1,11,'witch_poison')], '首夜“女巫空过”明确没有用药，次夜才毒4，毒药不可能首夜已用；首夜刀3白神、本版无守卫且未救、也无其他药死，所以本夜解毒两药均未用，按空过记录，无需猜任何目标。')
fix('BV1hQ3t6hEbS',[E(1,'mixed_blood_model',{'action':'choose','actor':3,'targets':[6],'result':None})], '身份表明确混血儿3、狼人6；首夜行动直接说混血儿选择6号狼人为榜样。旧候选把6号当混血行动者、把被救平民8当目标，属于行动者/目标串行错配，应恢复3→6。')
fix('BV1iDGK61EYt',[P(2,9),P(3,9),H(1)], '全文稿有完整赛后法官复盘：首夜女巫救2，第二/三夜女巫技能空过/继续空过，故解药已耗、这两夜毒药未用；第二天明确“延期竞选环节”8自爆、警徽流失，首日5警上自爆只导致延期，首日竞选结果deferred。',3773715,3832175)
fix('BV1q9MB6FEhU',[H(1),E(2,'sheriff_result',{'action':'none','targets':[],'result':None},'day')], '首日警上查杀狼9自爆、第二天“延期竞选警长环节”4自爆后明确“本局警徽流失”，因此第一日延期、第二日无警长且徽流失；从未产生已当选警长，无需补造投票或转交对象。')
fix('BV1DFM26ME2R',[E(2,'self_destruct',{'action':'self_destruct','actor':12,'targets':[],'result':None},'day')], '第二夜毒12、刀7与第二天延期竞选阶段12“吞毒自爆”是复盘分别描述夜间命中和警上行为；警长竞选在夜死正式宣布之前可发生，记录一次12的自爆不意味着第二次12死亡。原文两处均明确，不能因复盘先说双死后说警上动作而删除动作。')
fix('BV1TDun6wEqw',[E(2,'witch_poison',{'action':'poison','actor':6,'targets':[12],'result':None}),D(2,[3,12])], '原句跨行“入夜狼队击杀3号预言家牛犊杀。12号狼人”，牛犊杀即女巫毒杀；随后直接播3/12双死，第二死因并未真正缺失，恢复女巫6毒12。')
fix('BV1GXgW6HEmA',[E(2,'self_destruct',{'action':'self_destruct','actor':4,'targets':[],'result':None},'day')], '原文第二夜刀9、毒4、夜间4/9双死，随后描述延期竞选阶段4吞毒自爆；这是同一轮毒口警上自爆的动作与夜间命中分别记述，不是第二次4死亡。明确保留一次自爆，不根据复盘口述顺序误判座位冲突。')
fix('BV1tj8p6REqy',[P(2,6),P(3,6)], '首夜女巫6已救2、解药耗尽；第二夜“女巫技能通过”、第三夜“继续通过”均为毒药空过，第四夜才毒9且6/9双死进一步印证。预言家验人是紧接的下一动作，不妨碍前句空过归女巫。')
fix('BV1GmTc61EMA',[A(2,12),E(2,'witch_poison',{'action':'poison','actor':12,'targets':[7],'result':None}),D(2,[7,12])], '第二夜先起头“狼队击杀七”随即重新报“狼队击杀12号女巫”，后者是完成的正式句；随后女巫毒7、7/12双死。本版只有一把狼刀、女巫解药首夜已用，无其他导致12死亡的技能，因此刀12、毒7由完整句和结果共同确定，前一“七”属报错改口。')
fix('BV1KuMG6NEez',[{'kind':'seat','seat':3,'fields':{'role':'女巫','faction':'good'}},{'kind':'seat','seat':12,'fields':{'role':'猎人','faction':'good'}},{'kind':'seat','seat':6,'fields':{'role':'守卫','faction':'good'}},S(1,'wolf_king_shot',9,6)], '名单需跨行连读为女巫3、猎人12、守卫6、狼王9；首日明确“9号狼王被公投出局，发动技能带走。6号守卫入夜…”独立印证狼王9与守卫6，技能目标6没有缺失。11号位于平民尾段，8号保留底牌预言家，作为傀儡后对好人7反馈狼人、对狼人5反馈好人是反向查验，不能改成狼人底牌。')
print('ALL',len(plan['games']),'pending',sum(not d['resolved'] for g in plan['games'] for d in g['decisions']))
