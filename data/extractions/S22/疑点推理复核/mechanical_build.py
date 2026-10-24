"""Primary-agent reconstruction of reviewed mechanical decisions; original sources stay intact."""
import sys,pathlib,json,hashlib,re
ROOT=pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'scripts'))
import batch_s22 as batch
from s22_inference_review import changed_value
BASE=ROOT/'data/extractions/S22/疑点推理复核'
QUEUE={x['bvid']:x for x in batch.read_json(BASE/'mechanical_queue.json')['items']}
PLAN=batch.read_json(BASE/'mechanical_plan.json') if (BASE/'mechanical_plan.json').exists() else {'group':'mechanical','games':[]}

def E(n,slot,fields,phase='night'):
 return {'kind':'event','number':n,'phase':phase,'slot':slot,'fields':fields}

def D(n,targets):return E(n,'night_deaths',{'action':'die','targets':targets,'result':None},'day')
def C(n,target,result,actor=None):return E(n,'seer_check',{'action':'check','targets':[target],'result':result,**({'actor':actor} if actor else {})})
def A(n,target):return E(n,'wolf_attack',{'action':'attack','targets':[target],'result':None})
def G(n,target,actor=None):return E(n,'guard',{'action':'guard','targets':[target],'result':None,**({'actor':actor} if actor else {})})
def P(n,slot='guard',actor=None):return E(n,slot,{'action':'pass','targets':[],'result':None,**({'actor':actor} if actor else {})})
def X(n):return E(n,'mechanical_action',{'action':'unavailable','targets':[],'result':None,'availability':'dead','effects':[]})

def add(b,changes,reason,pending=None,conclusions=None):
 x=QUEUE[b];folder=ROOT/x['entry']['output_dir'];d=batch.read_json(folder/'dossier.json');review=batch.read_json(folder/'复核记录.json');segments=review.get('recap_segments',[])
 if not segments:segments=batch.load_segments(ROOT/x['entry']['source_path'])[-70:]
 evidence={'path':x['entry']['source_path'],'start_ms':segments[0]['start_ms'],'end_ms':segments[-1]['end_ms'],'quote':'\n'.join(s['text'] for s in segments)}
 decisions=[]
 for q in x['questions']:
  why=(pending or {}).get(q['id'])
  decisions.append({'id':q['id'],'resolved':not bool(why),'conclusion':(why if why else (conclusions or {}).get(q['id'],reason)),'reason':why or reason,'basis':'insufficient' if why else 'context','confidence':'low' if why else 'high','evidence':[evidence]})
 final=changed_value(d,changes)
 additions=[]
 if final!=d:
  additions=[{'id':'additional:related_record_corrections','resolved':True,'conclusion':'同段关联字段已按复盘及规则一并更正。','reason':reason,'basis':'context','confidence':'high','evidence':[evidence]}]
 g={'bvid':b,'dossier_sha256':batch.digest(folder/'dossier.json'),'decisions':decisions+additions,'changes':changes,'summary':reason}
 PLAN['games']=[z for z in PLAN['games'] if z['bvid']!=b]+[g];batch.atomic_json(BASE/'mechanical_plan.json',PLAN)
 print(b,len(decisions),'questions',len(changes),'proposals',flush=True)

add('BV1pGVC6cEbW',[], '跨行身份表明确守卫2号、机械狼6号、12号平民；第二夜守护8号的行动者只能是2号。当前记录2号守8有原文依据，拒绝把12号平民当守卫的旧候选。')
add('BV1dJ7R6fEUw',[C(1,2,'守卫'),A(2,2),D(2,[2,9]),C(2,10,'通灵师',4),A(3,4),D(3,[4])], '第二夜“狼人击杀。二号守卫”应跨行连读为刀2，普通女巫毒9，首夜解药已救10且守卫当夜守4，故2/9出局；第三夜“击杀。四号通灵师通灵师，验证一号”对应刀4、通灵师验1，守卫2已死无保护，4出局。首夜验2反馈守卫，次夜验学通灵的机械狼10反馈通灵师。')
add('BV1zX7C6qEmR',[P(2,'mechanical_action',3),C(2,9,'狼人',7),A(3,6),E(3,'mechanical_action',{'action':'poison','actor':3,'targets':[7],'result':None}),C(3,4,'平民',7),D(3,[6,7])], '第二夜“机械女巫技能通过”是空过，后句普通通灵师7号查9反馈狼人。第三夜刀口先说7后“呃”改说6号女巫，继而毒7且6/7双死；普通女巫第二夜已毒9、毒药一次性，故本夜毒7归机械女巫3号。通灵师同夜中毒仍完成验4平民，不能因同夜死亡删除查验。')
add('BV1xYEo6QEGV',[C(2,10,'狼人',7),E(2,'mechanical_action',{'action':'check','actor':1,'targets':[9],'result':'猎人'})], '第二夜普通通灵师验10狼人，机械通灵师验9猎人，两个查验各归实际行动者；第三夜守卫先说自守5又说空过，两句存在改口歧义，当前不足以唯一确定。',pending={'9bba2f0b026691':'第三夜先说“守卫守护5号自首呃”，随后又说“入夜守卫空过”，可能是自我纠正，也可能重复播报；刀7且守卫白天被放逐无法区分两种守护状态，需核录音改口含义。'})
add('BV1sYEo6QEyS',[], '复盘明确解释当夜机械狼刀6、机械毒11、女巫毒5最后一狼；双方同夜达成条件按狼刀在先结算，且法官直接宣布狼人屠神获胜。5号同夜中毒与狼胜不冲突，无需改胜方。')
add('BV1uaEB66E7q',[A(4,10),E(4,'mechanical_action',{'action':'attack','actor':12,'targets':[7],'result':None}),D(4,[7])], '第四夜守卫7号护10，小刀（普通狼刀）刀10形成平安；大刀破盾刀击杀7号，原文随后明确7号单死。原死亡名单应为7，不含被盾挡住的10。')
add('BV1wmEB68Exu',[D(1,[12]),G(3,3,4)], '首夜复盘明确“12号狼人被奶穿身亡”，同守同救导致死亡，不能把解救写成最终存活；第三夜跨行“守护山。3号平民”是守3，后句狼刀4守卫并单死，目标3可直接恢复。')
add('BV1W6jG6HEkC',[P(1,'guard',1),C(1,10,'女巫',2),C(3,7,'猎人',2)], '跨行身份揭晓为守卫1号、机械狼8号，机械狼模仿3号狼人同伴、成为机械双刀狼；旧候选把1号误作机械狼，应拒绝，现有8学3正确。首夜明确守卫空过，验10女巫；第三夜验7猎人，纠正角色前缀误作反馈。')
add('BV1xkL96MEsd',[D(1,[5]),C(2,1,'猎人',12),C(3,7,'平民',12)], '首夜守卫护4挡刀，女巫毒5且直接宣布5被毒出局，“形成平安夜”只描述狼刀未死人，不能覆盖毒死5的结算。次夜查1猎人、第三夜查7平民，原句反馈明确。')
add('BV1Wjja66EFz',[D(1,[1]),G(2,10,4),D(2,[6]),C(1,3,'平民',5),C(3,8,'平民',5),C(4,10,'女巫',5)], '首夜明确1号猎人同守同救奶穿身亡并开枪带12；次夜守卫护10挡狼刀，毒6且原文明确6单死，应保留守10、拒绝空过旧候选。各夜查验反馈原文分别为3平民、8平民、10女巫，修正错值。')
add('BV1nBj664EFS',[D(1,[7]),P(2,'guard',5),C(1,11,'平民',9),C(2,1,'狼人',9),A(3,10),D(3,[10]),C(3,12,'平民',9),X(2),X(3)], '原文明确女巫2号毒7号机械狼、机械狼学10猎人成为吃毒机械猎人；7首夜死亡，后续机械技能不适用。第二夜守卫明确空过、验1狼人；第三夜“狼队击杀。十号猎人”跨行连读，随后10出局开枪带最后狼1，刀口及出局均可确定；查12反馈平民归普通通灵师9号。')
add('BV13Ajo6xEY8',[D(2,[5,7,11]),C(1,7,'平民',6),C(2,5,'女巫',6),C(3,3,'猎人',6)], '第二夜狼刀7、普通女巫毒11、机械女巫毒5，原句“五七十一三四”应为5/7/11三死；通灵师随后查5反馈女巫，与三名死者无冲突。其余查验原句分别首夜7平民、第三夜3猎人，按实际反馈修正。')
add('BV1d47L6DEoo',[E(2,'mechanical_action',{'action':'check','actor':3,'targets':[8],'result':'守卫'}),C(2,3,'通灵师',11),X(3)], '第二夜机械通灵师3号验8反馈守卫，普通通灵师11号验3；3号首夜已学通灵师，标准通灵反馈应为通灵师，“OK手势”属反馈词误写，可由确定的学习结果及查验规则唯一校正。3号第二天被放逐，第三夜机械技能不适用，不影响第三夜普通通灵师验1平民。')
add('BV1Y2Tc6LEt4',[X(2),C(2,3,'猎人',11)], '首夜原文明确2号机械狼学6号狼人、机械双刀形态，并在第一天被放逐；学习11号通灵师的旧候选与两次明确描述矛盾，应拒绝。第二夜11号普通通灵师验3反馈猎人，机械狼早已出局不可能提供该查验，夜死5/11有明文。')
add('BV18vTi66EnN',[D(2,[4]),P(3,'guard',9),A(3,9),D(3,[9])], '第二夜守卫9自守挡刀、女巫毒4，原文明确4号单死；“平安夜”只指狼刀被挡。第三夜守卫技能空过、机械平民追刀9号守卫且原文明确9单死，普通刀与机械无技能形态不冲突。')
add('BV1BjMh63EDf',[D(2,[9]),A(3,10),D(3,[10]),X(3)], '第二夜守卫10自守挡狼刀、女巫毒9机械狼，毒死9。第三夜跨行“狼人追刀。10号守卫”直接给出狼刀目标10，后文10出局移交警徽进一步确认死亡，守卫当夜守7。9号已死，第三夜不能发动机械技能。')
add('BV1suMG6PEYP',[{'kind':'seat','seat':9,'fields':{'role':'通灵师','faction':'good'}},C(1,3,'平民',9),C(2,1,'平民',9),A(3,2),D(3,[2])], '复盘名单直接说“通力师九号女巫五号”，应对应通灵师9号、女巫5号，后文第二夜“狼人击杀九号通灵师”独立印证；不能将9补为平民（已有1/3/7/11四平民）。第三夜跨行刀2守卫，守卫本夜守3且女巫5首日已被放逐无解救，故2出局。')
add('BV13ZMp63EEB',[G(2,9,10),P(3,'guard',10),A(3,9),D(3,[9])], '第二夜“入夜守卫守护。九号猎人”跨行直接给出守9；第三夜守卫技能空过，随后“狼队击杀。九号猎人”给出刀9且9出局开枪。普通女巫第二夜已毒7，不能再毒9，机械狼亦第二夜已死，故刀口及死亡原因唯一，不需保留原文断句疑点。')
add('BV1VxNH6YETC',[{'kind':'seat','seat':9,'fields':{'role':'守卫','faction':'good'}},P(1,'guard',9),G(2,7,9),C(2,9,'守卫',7)], '身份名单“10号首尾9号狼人”按角色顺序对应猎人10、守卫9；第二夜通灵师验9反馈“首位身份”及守护7的行动共同印证守卫9。首夜“守卫技能空过”直接明确，不单靠剩余角色数猜补。')
add('BV1YxNH6YEqY',[G(2,6,6)], '第二夜完整原句“入夜守卫守护6号自首”，守卫本身为6号，“自首”是自守的同音误写，行动与座号可同时确定；紧接狼人刀10，并非守护6的结果描述。')
add('BV1WEN86gE1i',[D(1,[8]),A(3,5),E(3,'mechanical_action',{'action':'attack','actor':6,'targets':[12],'result':None}),D(3,[5,12])], '首夜8号“同守同救奶穿出局”是明确出局事实；第三夜普通狼人3/2/10此前已全部出局，机械双刀6号带刀，普通刀5、技能刀12且原文明说5/12双死，破盾刀无视守卫对12的守护。结尾“选择交牌”是认输和好人胜的明确表述，不需为它伪造毒药/自爆事件。')
add('BV1BPNB6QE4z',[A(4,11),D(4,[4]),X(3),X(4)], '第四夜守卫护11挡普通狼刀，女巫毒4，死亡名单应只有4。原文第二天12号猎人开枪带走机械狼1，后续机械技能已不适用，不能为形成平安夜虚构额外机械操作。')
add('BV1dYKV6UEYM',[E(2,'witch_poison',{'action':'poison','actor':7,'targets':[12],'result':None}),E(2,'mechanical_action',{'action':'poison','actor':10,'targets':[1],'result':None}),D(2,[1,11,12])], '第二夜依次报“狼队偷刀11号守卫”“女巫毒杀12号狼人”“机械女巫毒杀1号猎人”，并明确1/11/12倒牌；偷刀是普通刀的战术称谓，机械狼学女巫只有药技能，且普通狼人仍活，不能把刀11改为机械技能刀。')
add('BV12pNo6HEiz',[C(2,11,'守卫',6),E(2,'badge',{'actor':6},'day')], '第二夜通灵师6号查11号反馈“首位身份”，身份名单及守卫11当夜自守均印证守卫。6号是首日警长、第二夜中刀后移交警徽11号，故移交者6，不能把前面“6/7双死”中的7号狼人误当警长或查验反馈。')
add('BV1bWKY6tEri',[D(2,[10,11])], '第二夜刀10守卫、毒11机械平民，守卫当夜守4且首夜解药已救3，故夜死10/11；接着第二天放逐8、第三夜刀12、第三天放逐9，再入夜终局拍刀1/3，四轮顺序明确，不接受删成3轮。终局“拍刀”不是狼王开枪（本版无狼王），拍刀路径1/3保留结论，胜方依据明确狼胜，不凭损坏尾句补枪击。')
add('BV1Abgy6tEP8',[G(3,12,5),A(3,5),D(3,[5])], '第三夜跨行完整“守卫守护。12号通灵师狼人追刀。5号守卫通灵师验证10号”，对应守12、狼刀5、通灵师验10狼人。5不自守且机械狼8前夜被毒死，女巫首夜已用解药，故5死亡，无其他免死分支。旧候选unknown和守5均应拒绝。')
add('BV1RGgx6xEP9',[E(1,'exile_result',{'action':'none','targets':[],'result':None},'day'),E(1,'sheriff_result',{'action':'deferred','targets':[],'result':None},'day'),E(1,'self_destruct',{'action':'self_destruct','actor':6,'targets':[],'result':None},'day'),E(2,'witch_poison',{'action':'poison','actor':9,'targets':[5],'result':None}),P(3,'guard',7),D(4,[9])], '跨行名单直接给出通灵师8、守卫7，第三天才明确放逐7；第一天为警上6号自爆，原疑点所谓首日7通灵师放逐并不存在于本次原文。第二夜毒5且竞选阶段5号“吞毒自爆”是对同一轮警上爆毒口的表述，不代表新增第二个死者；第三夜追刀8明确单死、第三天放逐7、第四夜刀9女巫、第五夜机械平民刀1猎人，轮次和人物可连贯恢复。')
add('BV1iMgq6ZEWn',[G(2,5,11),A(3,5),D(3,[5])], '第二夜“入夜守卫守护。5号通灵师狼人击杀11号守卫”跨行给出守5；随后刀11毒8且两者双死、第二天2号狼自爆，普通狼人6/8/2已全出局。第三夜机械守卫3接普通狼刀，跨行“击杀。5号通灵师”及5号出局移交警徽证实刀5，不是机械守卫额外技能刀。')
add('BV13g3z6FEdh',[E(1,'mechanical_day_skill',{'action':'shoot','actor':10,'targets':[2],'result':None},'day'),E(2,'guard',{'action':'unavailable','actor':2,'targets':[],'result':None})], '首日“10号机械猎人被公投出局，发动技能带走。2号守卫入夜狼人击杀7号”应跨行连读为带走2号守卫，随后才入夜刀7；第二夜守卫2已经被带走，故不是缺少守护目标，而是守护不适用。')
add('BV1aQ3t6hEcB',[{'kind':'seat','seat':10,'fields':{'learning_target':6,'learned_role':'机械守卫'}},P(1,'guard',6),C(1,10,'守卫',8)], '首夜“首位技能空过”对应普通守卫6；机械狼10在学习当夜不能使用新守卫技能，故不可能把空过归机械技能。原文明说模仿6号守卫、两次机械守卫形态，验10反馈“首位身份”可规范为守卫，座位和角色相互印证。')
add('BV1iDGK61E1c',[G(2,2,2)], '第二夜原句“守卫守护2号自首”，身份名单也明确守卫2号，故自首为自守误写、行动者和目标同为2，不需要额外人工作读音判断。第三夜才守女巫1并被刀2，轮次不混淆。')
add('BV179MB6FEne',[P(1,'witch_save',4),P(1,'witch_poison',4),C(3,9,'守卫',7)], '首夜完整“女巫空过”明确未用药而非缺少信息，可记录两种药本夜均未使用（不虚构任何目标）；第二夜才开解药救7证明首夜解药未耗。第三夜查9反馈“首位身份”，名单守卫9、各夜9自守/护12共同印证为守卫，两个重复反馈疑点可同时结案。')
add('BV1oXMB6fEQ4',[D(1,[11]),C(3,8,'平民',9)], '首夜11号明确被毒出局。第三夜先说验1平民，随后“而通灵师验证8号…实际验证到机械平民”是对查验对象的后续澄清；本局机械狼8学平民无查验能力，普通通灵师9每夜一次，采用最终明确澄清的8号，不合并成两次查验。终局普通狼人2/5/7已全死，机械平民8可接普通狼刀；明确拍刀4号猎人是终局刀路，不是机械白天技能，记录在结论并保留普通夜刀6号原槽不覆盖。')
add('BV1DFM26MEWR',[P(2,'witch_poison',4),P(3,'guard',10),A(3,9),C(3,7,'狼人',9)], '女巫首夜解药已救1，第二夜“女巫空过”只能涉及尚可用的毒药，故毒药pass；第三夜“首位通过狼人追刀9”是守卫空过后狼刀9、普通通灵师查7反馈狼人，后句不得把守卫角色词串进查验反馈。')
add('BV1DFM26ME2o',[D(1,[12]),P(1,'witch_save',6),P(1,'witch_poison',6),G(3,4,4),A(3,2),D(3,[2])], '首夜刀12通灵师、守卫只守6、女巫明确空过；机械狼学平民无保护，故12必死。女巫首夜空过表示两药均未使用，第二夜才救2。第三夜原文明确守卫4自守、狼刀2且女巫空过，第二夜已耗解药，故2死亡；守6/刀3属于第四夜，旧候选错挪轮次。')
add('BV1mDun6wE3m',[P(1,'guard',2)], '首夜“守信的空过”按紧邻身份和固定口令对应守卫技能空过；空过本就没有目标，不应因未报目标再把pass当疑点。机械狼首夜在学习且形态为双刀，不能承担守卫操作，行动者唯一为普通守卫2。')
add('BV1CSuN62Ee2',[], '原句机械双刀狼7在普通末狼11自爆后拍刀12号女巫与2号猎人并获胜；这是已解锁的双刀终局路径，不是机械猎人开枪。明确拒绝把两个目标塞入mechanical_day_skill/shoot的旧候选；本轮保留拍刀两目标及胜方在核查结论，已有第三夜刀1不被覆盖，不虚构两次白天枪击。')
add('BV1CSuN62Eey',[E(1,'sheriff_result',{'action':'deferred','targets':[],'result':None},'day')], '首日竞选环节9号自爆，次夜后明确称“延期”竞选且8号再次自爆、警徽流失；能据上下文判定首日竞选未完成，应为deferred，而非选出未知警长。不能把第二天才学习的机械狼操作挪到首夜。')
add('BV12Mur6nEns',[], '末尾“最后一张12号选择招牌，游戏结束，好人获胜”按败方主动结束比赛的完整语境是交牌，不是查验、开枪或自爆。12号学通灵师的身份与第二夜查验反馈一致；既然没有报告新技能，不增添事件，保留终局交牌说明即可。')
add('BV1JNgj6gEta',[G(3,5,11),A(3,5),E(3,'night_deaths',{'action':'peaceful','targets':[],'result':None},'day'),E(2,'witch_save',{'action':'unavailable','actor':8,'targets':[],'result':None}),E(2,'witch_poison',{'action':'unavailable','actor':8,'targets':[],'result':None})], '第三夜完整原句“守卫守护。5号通灵师机械平民开刀击杀。5号通灵师形成。平安夜”，对应守5、普通刀5被挡，接着查1平民；不是目标缺失。第二夜女巫8被追刀且不能自救，解药不可用，首夜毒药已毒2，故毒药也不可用；“无法自救空过”不应误填两项主动pass。')
add('BV1XXgW6nEZ5',[], '复盘前段实际终局播报和末段复盘均明确拍刀2号女巫、拍刀成功且狼人屠神获胜。机械女巫7的普通狼人同伴已全部出局，接普通狼刀的终局路径不等于再次用毒，更不等于机械猎人开枪；拒绝旧错误槽位即可，明确目标2和胜方保留结论。')
add('BV1WigN6JEVS',[E(2,'mechanical_action',{'action':'check','actor':1,'targets':[3],'result':'守卫'}),E(3,'wolf_attack',{'action':'attack','actor':1,'targets':[8],'result':None}),E(3,'mechanical_action',{'action':'unknown','actor':1,'targets':[],'result':None,'effects':[]}),D(3,[8])], '第二夜机械通灵1查3反馈“首位”是守卫，身份表及当夜3号守卫中刀印证。普通狼人6首日放逐、10第二夜毒死、9第二日自爆后，第三夜机械狼1接普通狼刀击杀8，不能写为机械通灵技能attack。第三天1号交牌结束是同一局末狼身份表述，不增添自爆或多一轮；未报第三夜查验则机械查验保持未知。')
add('BV17f8g6BEFQ',[P(2,'witch_poison',9),P(3,'witch_poison',9),P(4,'witch_poison',9)], '女巫首夜已解救10号通灵师，后续解药已耗；第二、三、四夜分别明确技能空过/继续空过，能确定剩余毒药各夜未用。第三夜口令清楚位于入夜守10、刀10平安之后、第三天11自爆之前，因此归第三夜；不是第二夜总结。')
add('BV1tj8p6RE1V',[G(1,4,2),A(1,9),C(1,7,'平民',1),G(2,7,2),A(2,12),C(2,4,'狼人',1),P(2,'mechanical_action',6),P(3,'mechanical_action',6),E(4,'mechanical_action',{'action':'poison','actor':6,'targets':[8],'result':None}),D(4,[8]),E(1,'self_destruct',{'action':'self_destruct','actor':3,'targets':[],'result':None},'day')], '首夜原文守4、刀9、毒3、验7平民；第二夜守7、刀12、机械女巫空过、验4狼人，旧候选与现档互串轮次应逐夜恢复。第三夜机械女巫继续空过明确，第四夜才毒8猎人、8单死。3号在警上“吞毒自爆”是同一毒口在竞选尚未结束时的自爆动作，记录一次自爆并不重复制造第二个3号死亡；夜间命中与白天动作分开保留。')
add('BV1kG8A6dE7A',[C(2,4,'通灵师',9),E(2,'mechanical_action',{'action':'check','actor':4,'targets':[11],'result':'守卫'})], '第二夜普通通灵师9查4反馈通灵师，4是首夜学9的机械通灵，反馈学成身份合法，不与机械狼底牌矛盾；机械通灵4查11反馈“首位”，身份表与11普通守护行动印证为守卫，两个查验各归对应行动者。')
add('BV18W8B6KE7C',[D(2,[7]),P(3,'guard',1),X(3)], '机械狼首夜空过、第二夜才学1守卫，学习当夜不能自守，法官明确“想自守没让他守”；随后女巫毒7，故7第二夜死亡，第三夜机械技能不适用。第三夜“首位通过”指仍存活的普通守卫1号空过，不是机械守卫的未知守护目标。')
