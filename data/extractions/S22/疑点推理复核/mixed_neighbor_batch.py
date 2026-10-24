import json, re, hashlib, sys
from pathlib import Path
base=Path('data/extractions/S22/疑点推理复核')
queue=json.load(open(base/'mixed_neighbor_queue.json',encoding='utf-8'))['items']
idx=json.load(open(base/'mixed_neighbor_review_index.json',encoding='utf-8'))['items']
idx_by_id={x['id']:x for x in idx}
raw=json.load(open(base/'mixed_neighbor_raw_context.json',encoding='utf-8'))
raw_by_id={x['id']:x for x in raw}
plan_path=base/'mixed_neighbor_plan.json'
plan=json.load(open(plan_path,encoding='utf-8')) if plan_path.exists() and plan_path.stat().st_size else {'group':'mixed_neighbor','games':[]}
games={g['bvid']:g for g in plan['games']}
sys.path.insert(0,'scripts')
import batch_s22 as batch
seg_cache={}

def ev_segments(x):
    p=(Path(x['entry']['source_path']))
    if p not in seg_cache:
        try: seg_cache[p]=batch.load_segments(p)
        except Exception: seg_cache[p]=[]
    return seg_cache[p]

def slot_terms(x):
    f=x.get('field','').lower()
    q=x.get('queue_quote','')
    if 'learning_target' in f or 'learned_role' in f or 'mixed_blood_model' in f: return ['混血儿','榜样','选择']
    if 'puppet' in f or '傀儡' in q: return ['傀儡','技能失效','狼人身份']
    if 'sheriff' in f or '警长' in q or '警徽' in q: return ['警上','警长','警徽','自爆']
    if 'wolf_shoot' in f or '拍刀' in q: return ['拍刀','游戏结束','获胜']
    if 'witch' in f or '女巫' in q: return ['女巫','毒杀','救起','空过']
    if 'seer' in f or '预言家' in q: return ['预言家','验证','查验']
    if 'hunter' in f or '猎人' in q: return ['猎人','带走','开枪']
    if 'night_deaths' in f or 'death' in f or '双死' in q: return ['平安夜','双死','单死','出局']
    if 'wolf_attack' in f or '击杀' in q: return ['狼人击杀','狼队击杀','击杀','入夜']
    if 'rounds' in f: return ['第一天','第二天','第三天','第四天','游戏结束']
    if 'winner' in f or 'win_condition' in f: return ['游戏结束','获胜','绑票']
    return [w for w in ['选择','榜样','傀儡','击杀','毒杀','验证','双死','拍刀','游戏结束','自爆'] if w in q] or ['游戏结束']

def evidence_for(x, explicit=None):
    evs=[]
    src=x['entry']['source_path']
    segs=ev_segments(x)
    start,end=x.get('start_ms'),x.get('end_ms')
    selected=[]
    if explicit:
        for s in segs:
            if any(t in s['text'] for t in explicit):
                selected.append(s)
    if not selected and start is not None:
        selected=[s for s in segs if s['end_ms']>=start-1200 and s['start_ms']<= (end or start)+1200]
    if not selected:
        terms=slot_terms(x)
        # Favor exact source excerpts about the operation, plus the relevant seat numbers.
        cand=x.get('candidate')
        seats=set()
        if isinstance(cand,dict):
            for k in ('actor','targets','start_seat'):
                v=cand.get(k)
                if isinstance(v,int): seats.add(v)
                elif isinstance(v,list): seats.update(y for y in v if isinstance(y,int))
        elif isinstance(cand,int): seats.add(cand)
        m=re.search(r'seats?\[(\d+)\]',x.get('field',''))
        if m: seats.add(int(m.group(1)))
        for s in segs:
            text=s['text']
            score=sum(2 for t in terms if t in text)
            score+=sum(1 for n in seats if f'{n}号' in text)
            if score>0: selected.append((score,s))
        selected= [s for score,s in sorted(selected,key=lambda v:(-v[0],v[1]['start_ms']))[:4]]
    # Add adjacent lines around the strongest selected segment when they are direct continuation.
    if not selected:
        rc=raw_by_id.get(x['id'],{}).get('segments',[])
        selected=rc[:2]
    selected=sorted({(s['start_ms'],s['end_ms']):s for s in selected}.values(),key=lambda s:s['start_ms'])[:5]
    for s in selected:
        evs.append({'path':src,'start_ms':int(s['start_ms']),'end_ms':int(s['end_ms']),'quote':s['text']})
    return evs

def event(n,phase,slot,fields):
    return {'kind':'event','number':n,'phase':phase,'slot':slot,'fields':fields}
def seat(n,fields): return {'kind':'seat','seat':n,'fields':fields}

# Direct, source-backed mixed-blood exemplar selections. These always become mixed_blood_model events,
# never seat.learning_target/learned_role.
mix_targets={
'547ff9585a152a':(2,12),'56133d08bd3c47':(3,6),
'afc2935e797e39':(10,8),'6422cf96b00922':(10,8),
'e3ef35a932ac28':(11,7),'996fa26663f3b1':(11,7),
'c18d88dc8c1bda':(3,8),'2800273471db1d__M':(8,4),
'af4a157f2d1d0a':(6,7),'26fb5b55822aca':(12,1),'48fcb31279dec3':(12,1),
'7664de3315ead1':(10,6),'6076c4eced5a2a':(10,6),
'310882c477dcc1':(1,12),'3d1220712302f5':(1,12),
'7707d70e0a5475':(4,6),'5372fcdd781777':(12,7),'24d8c0ac72b68a':(12,7),
'd97764fe8d9073':(6,4),'c0c20ac993c291':(6,4),
'871f4b77d9283c':(4,5),'0f34a849ca475a':(12,9),
'c32a7bb32e937d':(8,5),'cb1fe5d8f6f6df':(8,5),
'e5085b01712179':(1,7),'1392fe9985e401':(1,5),
'60df7ae528bcac':(10,7),'c5040517b99b40':(10,7),'fdc2d5ff207379':(10,7),
'48fb1915af079b':(1,5),'dd654ecc7b9b1b':(1,5),
'c35ef9b9d129cb':(7,5),'8f001c4112c493':(7,5),
'ff810e8ccd71e5':(11,12),'8e367fb515bcb9':(9,3),
'05f7be95cb32dd':(10,6),'a03a76dd775efd__M':(9,3)
}
custom={
# Resolved issues outside the exemplar mapping: status, short conclusion, basis, reason, confidence, changes.
'0705e28790e56c':(True,'终局狼队拍刀点名2号女巫与11号白神；这是拍刀结算，不是第三夜常规狼刀双目标。','transcription','复盘先说拍刀，随后列出2号、11号并宣布游戏结束。该版型狼刀事件每夜单目标，且白天终局拍刀没有对应狼刀槽，因此保留叙述，不把两目标塞进普通wolf_attack。','high',[]),
'c66546b3365251':(True,'首夜狼刀目标为2号，女巫救起。','transcription','原句在首夜复盘中直接点名狼队击杀2号，随后说女巫救起、形成平安夜。','high',[event(1,'night','wolf_attack',{'action':'attack','actor':None,'targets':[2],'result':'狼队击杀2号，女巫救起'})]),
'176af023689cad':(True,'首夜预言家2号查验7号为狼人。','transcription','复盘直接给出预言家验证7号狼人身份；首夜角色名单确认2号为预言家。','high',[event(1,'night','seer_check',{'action':'check','actor':2,'targets':[7],'result':'狼人'})]),
'64efdb27d6c5af':(True,'第二夜狼刀目标为6号猎人。','transcription','复盘在第二夜直接称狼队击杀6号猎人；本项只补狼刀目标，不从后来猎人行动推断其他事实。','high',[event(2,'night','wolf_attack',{'action':'attack','actor':None,'targets':[6],'result':'狼队击杀6号猎人'})]),
'd958c1eb966ca3':(True,'第3轮夜死应只有10号；5号女巫是第4夜狼刀目标，不是第3夜死亡。','transcription','完整时间顺序先记第二天放逐9号，随后狼队击杀10号；再到第三天放逐混血儿3号后才说狼队击杀5号女巫。5号对应第4夜。','high',[event(3,'day','night_deaths',{'action':'die','actor':None,'targets':[10],'result':'第3夜出局10号；5号女巫在第4夜被击杀'})]),
'86723a87744046':(True,'复盘明确出现第三天白天，随后狼队夜杀5号、末狼6号交牌，当前4轮计数正确。','transcription','候选3轮把“第三天白天”误当成只有三轮；源稿在第三天放逐后仍记一夜并宣布结束，现有4轮没有额外空轮可删。','high',[]),
'36d8c630__none':(True,'','context','', 'medium',[]),
'6dcbc63068b500':(True,'复盘明确狼队最终获胜并称达成绑票条件；不再补写未明确的票型阈值。','transcription','源稿点名9号猎人被投后狼队达成绑票条件并获胜；具体人数/阈值没有清晰说明，因此只保留明说的结算。','medium',[]),
'1169f3e471b8f3':(True,'狼队在第三天8号平民被放逐后绑票获胜。','transcription','原文连续说明第三天8号平民被抗推、游戏结束、狼队绑票获胜；只记直接胜方和触发情境，不补人数阈值。','high',[{'kind':'winner','value':'werewolf'}]),
'31d2b2a01a1385':(False,'最可能终局拍刀选3号平民与4号混血儿；源稿“拍刀成功”后胜方一词被识别成“图米赢”，无法仅据当前ASR确认最终胜方。','insufficient','终局目标和拍刀成功在复盘中清楚，但“图米赢获胜”疑为ASR错词。仍缺该短句的可辨听写或另一份可靠转写，故不把胜方写成事实。','medium',[]),
'4140f599a47c92':(True,'狼队终局拍刀直接命中11号猎人；混血儿12号榜样7号狼人，且狼队获胜，因此其个人胜利阵营随榜样为狼人。','context','复盘清楚点名终局最后一神11号猎人并称狼队屠神获胜；榜样选择原句直接点名7号狼人。规则说明混血个人胜负跟随榜样阵营，故可据确切榜样和胜方推得狼人个人胜利。','high',[event(2,'day','mixed_blood_victory',{'action':'wolf','actor':12,'targets':[],'result':'榜样7号狼人，狼队获胜，个人胜利随榜样阵营为狼人'})]),
'200a520351d8bf':(True,'6号混血儿为好人阵营；第三天11号白神出局后警徽由11号移交给9号。','transcription','身份复盘直接称“好人混”；原档已有6号阵营空缺。该局第三天警徽事件已经记录11号移交到9号，原文支持其准确性。','high',[seat(6,{'faction':'good'})]),
'18b000573fb05d':(True,'狼队终局选择12号与7号拍刀，复盘明确拍刀失败且好人胜利；这些属于终局叙述，没有可对应的普通狼刀事件槽。','transcription','原文逐项给出12号、7号为拍刀对象、拍刀失败、好人获胜。模板没有终局狼队拍刀槽，故只记录游戏胜方。','high',[{'kind':'winner','value':'good'}]),
'33241a13bac27d':(True,'狼队终局拍刀目标为4号平民与8号混血儿，拍刀成功后狼队获胜；该终局动作无对应普通狼刀槽。','transcription','复盘直接点名4号与8号并称拍刀成功、狼队获胜。没有把终局目标错写成夜间单目标狼刀。','high',[{'kind':'winner','value':'werewolf'}]),
'947e5347b351a4':(False,'最可能按首夜狼刀3号、女巫救起为平安夜；但身份名单把8/9/2错位，后续又称2/3双死且第三天拍刀猎人身份不符，无法安全合并修订。','insufficient','该复盘中首夜平安夜与2/3双死相冲突，多个角色称谓也互相错位；还缺一份能厘清死因、角色底牌和终局拍刀顺序的完整可核源句。','low',[]),
'852dc29a6196a8':(False,'源稿一处说首夜因女巫救起而平安，之后又提2号与3号双死；未能证明双死对应首夜，保留未知。','insufficient','原文对首夜结算存在直接冲突，也没有说明2号的死因和时点；需要核听相关完整原句。','low',[]),
'3c62a85f163979':(False,'“女巫空过”可确认，但无法判断是解药、毒药都未用，还是仅其中一项空过。','insufficient','转写只概括女巫空过，没有把两种药剂分开说明。缺少女巫行动逐项播报；不自动生成两个pass。','medium',[]),
'5c93d8c10d20b8':(True,'终局狼队拍刀对象为8号平民和12号女巫，拍刀失败，最终好人获胜；不追加普通夜刀。','transcription','复盘明说狼队选择拍刀并列出8号、12号，随后说拍刀失败；局末胜方为好人。','high',[{'kind':'winner','value':'good'}]),
'6152d1285adc68':(False,'第2、3夜女巫都被复盘概括为“空过”，但不能区分解药与毒药是否分别pass。','insufficient','源稿对女巫行动只给总括词“空过/继续空过”，没有逐药明示；缺少分药的行动播报。','medium',[]),
'2abccc13d07e99':(False,'第1天警上竞选后5号狼人自爆，未听到警长当选、延期或警徽流失的明确结果。','insufficient','原文到“竞选环节”后马上记5号自爆，未交代竞选结果。缺少自爆前后的警徽播报。','medium',[]),
'b7f1d3904243f4':(False,'最可能警上9号自爆造成延期；警徽流失的具体日期、原持有人与是否转交均未被原句唯一说明。','insufficient','复盘只提供警上、第二天和“警长环节/警徽流失”等概括，没报当选者或徽物流向；需要完整警长流程原句。','low',[]),
'202bbac751fd7a':(False,'源稿先把7号与12号列为夜间双死，后又称12号狼人吞毒自爆；不能把两种时序合并成两次死亡。','insufficient','同一12号在紧邻叙述中既属双死名单又被称吞毒自爆，顺序或ASR存在冲突；缺少原始完整播报确认12号在夜间前是否仍存活。','low',[]),
'd4a64233fbfaf0':(False,'夜间狼队击杀3号预言家，复盘称3号和12号双死；12号的第二死因未明。','insufficient','直接原句仅将狼击杀指向3号，没有指出12号是否被女巫毒杀或由其他技能造成；缺少12号死因。','medium',[]),
'18b000573fb05d__dup':(False,'','insufficient','','low',[]),
'6152d1285adc68__dup':(False,'','insufficient','','low',[]),
'54d0659108ebe248':(False,'最可能11号狼人自爆发生于延期竞选，第三天9号末狼被放逐；“6号撕警徽”主语可能有ASR错位，警徽去向不明确。','insufficient','合段转写把“六号将警徽撕掉”与“十一号狼人自爆”连读，和既有警徽轨迹可能冲突；缺少警徽流失的清晰完整播报，保留该组疑点。','low',[]),
'c006eb779e4902':(True,'狼队终局拍刀两个目标为9号与10号，狼队获胜；这是终局双目标叙述，不拆成常规狼刀。','transcription','复盘原句在“狼人可拍两刀”后直接点名9号、10号，随后宣布狼队获胜。板型没有终局拍刀槽位，因此只修正胜方。','high',[{'kind':'winner','value':'werewolf'}]),
'1392fe9985e401':(True,'混血儿1号首夜选择5号狼人为榜样。','transcription','身份名单和紧接的“混血儿选择5号狼人为榜样”原句直接确定选择者与座号。','high',[]),
'60df7ae528bcac':(True,'混血儿10号首夜选择7号女巫为榜样。','transcription','复盘先称本局为好人混血，随后明确混血儿选7号女巫为榜样；第10号是底牌混血儿。','high',[]),
'c5040517b99b40':(True,'10号混血儿榜样的底牌是女巫；榜样只应记在首夜选择事件中。','transcription','原句直接称混血儿选择7号女巫为榜样，足以得出榜样底牌；不把它写回混血儿seat.learned_role。','high',[]),
'48fb1915af079b':(True,'混血儿1号选择5号女巫为榜样。','transcription','复盘直接给出“混血儿一号、榜样是5号女巫”，且随后称好人混。','high',[]),
'dd654ecc7b9b1b':(True,'1号混血儿的榜样底牌为女巫；只用选择事件记录。','transcription','同一原句明确榜样座位5号且底牌女巫；不应再写seat.learned_role。','high',[]),
'c35ef9b9d129cb':(True,'混血儿7号选择5号狼人为榜样。','transcription','复盘身份名单称混血儿7号，紧接着原句称榜样是5号狼人。','high',[]),
'8f001c4112c493':(True,'7号混血儿选择的榜样底牌为狼人；只记首夜选择事件。','transcription','原文直接点名7号混血儿选择5号狼人为榜样；不把榜样复制到seat.learned_role。','high',[]),
'ca033db8e706c7':(True,'终局狼队拍刀选择1号平民和7号混血儿，拍刀成功并由狼队获胜；模板无此终局动作槽，不误记为猎人开枪。','transcription','完整终局转写出现狼人选择拍刀、双目标1和7，并在后文结算狼队胜利。此为终局战术，不应塞入普通角色技能事件。','high',[{'kind':'winner','value':'werewolf'}]),
'14a59ce2e9a2d5':(True,'该局只有两轮；第二天自爆后当夜终局拍刀，现有第3轮为空轮，应裁为2轮。','transcription','复盘依次报告第一天放逐、第二天狼队击杀后第二天放逐/自爆并结束；当前第3轮没有新事件，故按source时间序列计两轮。','high',[{'kind':'round_count','value':2}]),
'7fa22938b7de8b':(False,'夜间播报4号与9号双死，延期竞选又提4号吞毒自爆；无法仅凭叙述先后确定是延后宣布还是ASR时序错位。','insufficient','原文确实把双死和吞毒自爆放在相邻阶段，但不足以证明同一4号被重复死亡；缺少明确结算时点的原始播报。','low',[]),
'168de5210085b8':(True,'终局狼队拍刀命中2号白神，狼队获胜；不改记为白神主动公开身份。','transcription','复盘明确说狼队拍刀、2号白神拍刀成功，随后游戏结束并报告狼队胜利。没有白神主动公开身份的播报。','high',[{'kind':'winner','value':'werewolf'}]),
'4b9bfad64a2394':(True,'记录为预言家对6号傀儡猎人的查验反馈“狼人”；6号底牌仍是猎人、阵营仍是好人。','transcription','原文先称预言家验证6号玩家，下一句明确称傀儡猎人为狼人身份。该语句是查验反馈而非底牌名单，故不把6号实际角色改成狼人。','high',[]),
'55d7f208de6d2d':(False,'狼队击杀播报分别提到7号、12号，女巫又毒杀7号，结算7/12双死；普通狼刀唯一目标仍无法确定。','insufficient','同一夜出现两个狼队击杀片段、女巫毒7和7/12双死。现有文本不足以区分重复ASR、保护结算或第二个狼刀；缺少连续原始夜间行动播报。','low',[]),
'397c063b5a9ba7':(False,'最可能候选狼刀7号，但原文还另有“狼队击杀12号”且7被女巫毒杀，不能唯一分配两个夜死来源。','insufficient','转写中的两处狼队击杀和女巫毒杀7号无法同时映射到一个标准狼刀目标；缺少更清晰的夜间行动与结算播报。','low',[]),
'81e3aac9695888':(False,'身份名单与后续称谓对6号、9号狼王互相冲突；8号预言家被选为傀儡可确认，但其傀儡后阵营/技能状态仍待规则与播报拆分。','insufficient','名单称6号狼王而后文称9号狼王，11号身份指代也含糊。现有原句不足以安全更正6/11身份或全部傀儡状态；缺少清晰身份名单与角色技能播报。','low',[]),
'109c9987f946c0':(False,'9号狼王被放逐后发动技能带走，但带走目标没有出现在转写中。','insufficient','原文只有狼王被放逐和发动技能带走，没有目标座号；缺少目标播报，不能凭后续结果倒推。','medium',[]),
'550378926d24f0':(True,'6号猎人被狼队选为傀儡；按傀儡猎人规则其猎人技能失效。查验9号为狼王不改变6号底牌。','constraint','原文明确狼队选6号猎人为傀儡，且该板型记录傀儡猎人技能失效；复盘所说查验9号并称狼王唯一狼人，是对9号的反馈，不是6号阵营变化。','high',[event(1,'night','puppet_skill_effect',{'action':'skill_disabled','actor':None,'targets':[],'result':'6号猎人被选为傀儡，猎人技能失效'})]),
'84eb41f518746f':(True,'查验反馈原句称5号傀儡守卫为狼人身份；5号底牌仍为守卫好人，不能把反馈改写成底牌。','transcription','身份名单直接给出5号守卫，行动播报又说其守护技能失效；预言家验证5号后单独播报其傀儡反馈为狼人。','high',[]),
'd6905bc95facef':(True,'首夜5号傀儡守卫守护1号的技能失效；技能效果事件不填目标座号。','transcription','原句直接称5号守护1号的技能失效。该事实在puppet_skill_effect.result中说明；无targets/action为skill_disabled。','high',[event(1,'night','puppet_skill_effect',{'action':'skill_disabled','actor':None,'targets':[],'result':'5号傀儡守卫守护1号的技能失效'})]),
'04d0f3e5577d85':(True,'第二夜5号傀儡守卫守护7号狼王的技能失效；技能效果事件不填目标座号。','transcription','原句直接称“傀儡首位选择守护7号狼王，守护技能失效”；按事件字段语义，将守护对象保留在result文字而不填puppet_skill_effect.targets。','high',[event(2,'night','puppet_skill_effect',{'action':'skill_disabled','actor':None,'targets':[],'result':'5号傀儡守卫守护7号狼王的技能失效'})])
}
# Keys that need an explicit pending note rather than a generic hold.
pending={
'8cb1a2bde35bf8':('狼队击杀5号女巫、女巫毒杀4号狼人都在复盘中明确，但次日死亡名单没点名；最可能二者均死，仍缺结算播报排除保护/救药分支。','insufficient'),
'1230d15e92eb10':('8号猎人发动技能带走目标未识别；不能从胜负或后续名单反推座位，缺少带走目标播报。','insufficient'),
'2e1564e1750164':('动作是8号猎人被放逐后发动技能，目标座位仍未知；缺少技能播报中的目标词。','insufficient'),
'330d565386cc56':('女巫行动确实发动但目标未转写；最可能存在毒药使用，仍缺目标座号与次日死亡/毒杀播报。','insufficient'),
'7dab6591f6dd99':('第二夜女巫技能发动的候选目标未知；源稿只说明行动，不足以补目标座号。','insufficient'),
'c9627fbdf53ebd':('7号狼自爆发生在警上流程；竞选结果或徽流失未知，缺少警长结算句。','insufficient'),
'c3d0d6d90073a0':('第2、3夜狼队击杀目标都未转写；缺少两次夜刀座号播报，不能用后续放逐反推。','insufficient'),
'5b0be6f2858e09':('6号悍跳狼人在警上自爆，但该轮警长是否当选/流失未说明；缺少警长结算句。','insufficient'),
'd0659108ebe248':('“六号撕警徽”与11号自爆、第三天9号末狼被投的顺序和主语仍不清；缺少警徽流失完整播报。','insufficient'),
'947e5347b351a4':('复盘中首夜平安夜与后文2/3双死、角色名单错位相冲突，无法安全更正角色、首夜结算或拍刀失败原因。','insufficient'),
'852dc29a6196a8':('首夜平安夜和2/3双死的轮次对不上，死亡名单与死因尚不能确定。','insufficient'),
'3c62a85f163979':('“女巫空过”未区分解药和毒药；不把一个总括词拆成两个pass。','insufficient'),
'6152d1285adc68':('第二、三夜女巫都被概括为空过，但不清楚每种药剂分别是否pass。','insufficient'),
'2abccc13d07e99':('警上流程随后5号狼自爆，警长竞选结果没有被播报。','insufficient'),
'b7f1d3904243f4':('警上/次日警长流程及警徽流失的日期与归属不清，未找到当选者、转交者的完整原句。','insufficient'),
'202bbac751fd7a':('7/12已在夜间双死名单，之后却称12号吞毒自爆；时序无法定，不能重复登记死亡。','insufficient'),
'd4a64233fbfaf0':('3号狼刀与3/12双死被点名，但12号第二死因没有转写。','insufficient'),
'18b000573fb05d':None,
'947e5347b351a4':None,
'54d0659108ebe248':None,
'a03a76dd775efd':('“女巫技能通过预言家验证4号”不能确定女巫行动是用药还是空过。','insufficient'),
'e33dc3154fc0bb':('“女巫技能继续通过预言家验证7号”行动含义不清，不能补用药或pass。','insufficient')
}

# Candidate source excerpts by evidence keywords for each issue (most selection is automatic).
evidence_terms={
'8cb1a2bde35bf8':['狼队击杀5号女巫','女巫毒杀4号狼人','第二天白天'],
'1230d15e92eb10':['8号猎人被抗推出局','发动技能带走'],
'2e1564e1750164':['8号猎人被抗推出局','发动技能带走'],
'330d565386cc56':['狼队击杀4号女巫','女巫技能','通过4号带毒女巫单死'],
'7dab6591f6dd99':['女巫技能','4号带毒女巫'],
'0705e28790e56c':['狼人拍刀','2号女巫','11号白神游戏结束'],
'c66546b3365251':['狼队击杀2号','女巫救起'],
'176af023689cad':['预言家验证了7号'],
'64efdb27d6c5af':['狼队击杀6号猎人'],
'c9627fbdf53ebd':['警上竞选环节','7号狼人选择自爆'],
'd958c1eb966ca3':['入夜狼人击杀10号平民','3号混血儿被抗推入夜狼人击杀5号女巫'],
'c18d88dc8c1bda':['本游戏的混血是3号','榜样是8号白神'],
'86723a87744046':['第三天白天','狼人击杀5号女巫','最后一张狼人交牌游戏结束'],
'2800273471db1d':['狼人建议决定拍刀','给出的道路是4号三号游戏结束'],
'e6c9edec99e148':['8号榜样是4号白神'],
'6dcbc63068b500':['9号猎人被攻投','达成绑票条件','阵营绑票获胜'],
'1169f3e471b8f3':['第三天白天8号平民被抗推出局','狼队阵营绑票获胜'],
'5b0be6f2858e09':['上警环节','6号悍跳狼人自爆'],
'31d2b2a01a1385':['狼人阵营拍刀成功','3号四号游戏结束','图米赢获胜'],
'4140f599a47c92':['最后一神11号猎人','狼队阵营屠神获胜','选择7号狼人为榜样'],
'200a520351d8bf':['本局为好人混','警徽移交至9号平民'],
'18b000573fb05d':['给出的道路是12号和7号','拍刀失败','好人阵营获胜'],
'33241a13bac27d':['4号平民8号混血儿拍刀成功','狼队阵营获胜'],
'947e5347b351a4':['狼人击杀3号','形成平安夜','2号3号双死','拍刀二号猎人拍刀失败'],
'852dc29a6196a8':['形成平安夜','2号3号双死'],
'3c62a85f163979':['空过当夜预言家验证11号'],
'5c93d8c10d20b8':['8号平民以及12号女巫拍刀失败','好人阵营获胜'],
'6152d1285adc68':['女巫就能空过','女巫技能继续空过'],
'2abccc13d07e99':['请车竞选环节','五号狼人选择自爆'],
'b7f1d3904243f4':['上警环节','9号查杀狼人自爆','警徽流失'],
'202bbac751fd7a':['入夜狼人击杀7号平民','毒杀12号狼人','72双死','12号狼人吞毒自爆'],
'd4a64233fbfaf0':['狼队击杀3号预言家','12号狼人','3号12号双死'],
'd0659108ebe248':['六号将警徽撕掉','十一号狼人','自爆'],
'c006eb779e4902':['狼人决定拍刀','给出的道路是9号十号','狼人阵营图名获胜'],
'18b000573fb05d':['拍刀失败','好人阵营获胜'],
'ca033db8e706c7':['狼人选择拍刀','狼人可拍两刀'],
'14a59ce2e9a2d5':['第一天白天','第二天白天','游戏结束'],
'7fa22938b7de8b':['4号九号双死','4号狼人吞毒自爆'],
'168de5210085b8':['狼队拍刀','2号白神拍刀成功','狼队阵营屠神获胜'],
'4b9bfad64a2394':['预言家验证了6号玩家','傀儡猎人为狼人身份'],
'55d7f208de6d2d':['狼队击杀七','狼队击杀12号女巫','女巫毒杀7号守卫','7号12号双死'],
'397c063b5a9ba7':['狼队击杀七','狼队击杀12号女巫','女巫毒杀7号守卫'],
'81e3aac9695888':['6号狼王','本游戏的傀儡是8号','11号选择8号为傀儡'],
'109c9987f946c0':['9号狼王被公投出局','发动技能带走'],
'550378926d24f0':['狼人选择6号猎人为傀儡','傀儡猎人'],
'84eb41f518746f':['预言家验证了5号玩家','傀儡首位为狼人身份'],
'd6905bc95facef':['5号守卫守护一号平民的技能失效'],
'04d0f3e5577d85':['傀儡首位选择守护7号狼王守护技能失效']
}
# Resolve identifiers that are identical across games by the common grounded seat pair.
mix_targets['e6c9edec99e148']=(8,4)
mix_targets['8e367fb515bcb9']=(9,3)
# Fix an accidental duplicate placeholder rule from the seed section.
mix_targets.pop('2800273471db1d__M',None)
mix_targets.pop('a03a76dd775efd__M',None)
# Additional explicit corrections and bounded interpretations.
custom.update({
'f45706c7083c41':(True,'首夜7号傀儡底牌为猎人，猎人技能失效；查验反馈“狼人”单列记录，不能把底牌改成预言家或狼人。','constraint','原文称7号猎人被选为傀儡，随后“预言家验证7号”并明确反馈其傀儡为狼人身份。唯邻是从规则规定猎人傀儡技能失效、只有预言家傀儡反验，因此本条不应将该反馈误抽成reverse_check；技能效果记disabled，查验反馈改由独立decision记录。','high',[event(1,'night','puppet_skill_effect',{'action':'skill_disabled','actor':None,'targets':[],'result':'7号底牌为猎人，成为傀儡后猎人技能失效'})]),
})
evidence_terms['f45706c7083c41']=['狼队当夜选择了7号猎人成为傀儡','猎人实际验证为7号傀儡为狼人身份']
# Prior auto-generated duplicate-key error: remove any accidental placeholder entry.
custom.pop('36d8c630__none',None)
custom.pop('18b000573fb05d__dup',None)
custom.pop('6152d1285adc68__dup',None)
# The first issue for this game corrects the third-night death list only; remaining death effects are not inferred.
custom['d958c1eb966ca3']=(True,'第3轮夜死应只有10号；5号女巫是第4夜狼刀目标，不是第3夜死亡。','transcription','源稿先记第二天放逐9号，狼队随后击杀10号；第三天放逐混血儿3号后才记狼队击杀5号女巫。该句把5号明确放在下一夜，因此从第3轮夜死中移除。','high',[event(3,'day','night_deaths',{'action':'die','actor':None,'targets':[10],'result':'第3夜出局10号；5号女巫在第4夜被击杀'})])

def normalized(s): return re.sub(r'[\W_]+','',str(s))
def choose_evidence(x, terms=None):
    src=x['entry']['source_path']; segs=ev_segments(x); sel=[]
    terms=terms or []
    if terms:
        for t in terms:
            matches=[s for s in segs if t in s['text']]
            if matches: sel.append(matches[0])
    if not sel and x.get('start_ms') is not None:
        st,en=x.get('start_ms'),x.get('end_ms')
        sel=[s for s in segs if s['end_ms']>=st-500 and s['start_ms']<=(en or st)+500]
    if not sel:
        ts=slot_terms(x)
        cand=x.get('candidate'); nums=set()
        if isinstance(cand,int): nums.add(cand)
        elif isinstance(cand,dict):
            for k in ('actor','targets'):
                v=cand.get(k)
                if isinstance(v,int): nums.add(v)
                elif isinstance(v,list): nums.update(y for y in v if isinstance(y,int))
        m=re.search(r'seats?\[(\d+)\]',x.get('field',''))
        if m: nums.add(int(m.group(1)))
        scored=[]
        for s in segs:
            text=s['text']
            score=sum(2 for t in ts if t in text)+sum(1 for n in nums if f'{n}号' in text)
            if score: scored.append((score,s))
        sel=[s for _,s in sorted(scored,key=lambda v:(-v[0],v[1]['start_ms']))[:4]]
    if not sel:
        sel=raw_by_id.get(x['id'],{}).get('segments',[])[:3]
    sel=sorted({(s['start_ms'],s['end_ms']):s for s in sel}.values(),key=lambda s:s['start_ms'])[:5]
    return [{'path':src,'start_ms':int(s['start_ms']),'end_ms':int(s['end_ms']),'quote':s['text']} for s in sel]

def make_mix_decision(x, pair):
    actor,target=pair
    seats={s['seat']:s for s in x.get('seats',[])}
    role=(seats.get(target,{ }).get('role') or '未知底牌')
    result=f'混血儿{actor}号选择{target}号{role}为榜样'
    changes=[event(1,'night','mixed_blood_model',{'action':'choose','actor':actor,'targets':[target],'result':result})]
    return {'id':x['id'],'resolved':True,'conclusion':result+'；榜样只记在选择事件中，不写入混血儿座位属性。','basis':'transcription','evidence':choose_evidence(x,evidence_terms.get(x['id'],['榜样','选择'])),'reason':'身份名单/后续称谓确认混血儿座位，复盘原句直接给出其选择对象；因此在mixed_blood_model事件记录唯一榜样，不把榜样复制成混血儿底牌、learning_target或learned_role。','confidence':'high'},changes

def make_decision(x):
    qid=x['id']
    if qid in mix_targets:
        return make_mix_decision(x,mix_targets[qid])
    if qid in custom:
        resolved,conclusion,basis,reason,confidence,changes=custom[qid]
        return {'id':qid,'resolved':resolved,'conclusion':conclusion,'basis':basis,'evidence':choose_evidence(x,evidence_terms.get(qid)),'reason':reason,'confidence':confidence},changes
    # No evidence-backed unique resolution: state a likely candidate and the missing discriminator.
    quote=x.get('queue_quote') or x.get('context_quote') or ''
    field=x.get('field','')
    reason=x.get('reason','本地转写不足以唯一确认该疑点。')
    cand=x.get('candidate')
    likely=''
    if isinstance(cand,dict):
        likely='当前最可能候选为'+str(cand.get('result') or cand.get('action') or cand.get('targets') or cand)
    elif cand is not None:
        likely='当前最可能候选为'+str(cand)
    conclusion=(f'原句片段“{quote}”所涉{field}仍不能由上下文唯一确定。'+(likely+'；' if likely else '')+'仍缺可辨认的完整行动或结算播报。')
    return {'id':qid,'resolved':False,'conclusion':conclusion,'basis':'insufficient','evidence':choose_evidence(x,evidence_terms.get(qid)),'reason':reason+' 不用当前候选或已有值充当独立事实证据。','confidence':'medium'},[]

def extra_decision(bvid,qid,conclusion,basis,reason,terms,changes,confidence='high'):
    x=next(z for z in idx if z['bvid']==bvid and z['id']==qid)
    return {'id':'additional_'+qid,'resolved':True,'conclusion':conclusion,'basis':basis,'evidence':choose_evidence(x,terms),'reason':reason,'confidence':confidence},changes

by_bvid={}
for x in idx: by_bvid.setdefault(x['bvid'],[]).append(x)
question_counts={}

# Include explicitly requested check-result corrections, separately from the queued puppet-slot doubt.
additional={
'BV1yKJ56PEak':[
 extra_decision('BV1yKJ56PEak','f45706c7083c41','首夜预言家查验7号傀儡猎人，转写给出的反馈是“狼人身份”；该反馈不改变7号猎人底牌。','transcription','原句把“预言家验证7号”与“傀儡为狼人身份”连续播报；模板规则下猎人傀儡失效，而非预言家反验。','猎人实际验证为7号傀儡为狼人身份',[event(1,'night','seer_check',{'action':'check','actor':6,'targets':[7],'result':'狼人'})]),
 extra_decision('BV1yKJ56PEak','f45706c7083c41','第二夜预言家查验8号狼人；应把反馈记为“狼人”，原档“预言家”是误抽到的前缀词。','transcription','紧邻8号自爆前的原句明确说预言家验证8号玩家为狼人身份，原结果字段“预言家”不是查验反馈。','预言家验证8号玩家为狼人身份',[event(2,'night','seer_check',{'action':'check','actor':6,'targets':[8],'result':'狼人'})])
]
}


# Reconstruct first eight saved games from the same question queue and source evidence.
mix_targets.update({
'55f0348e264164':(9,7),'42ff0d70455e7e':(7,5),'47db9559f4a945':(4,7),
'e663f7815fe61b':(8,5)
})
custom.update({
'a4d43860ece6c9':(True,'第二夜狼队击杀11号预言家；首夜解药已救9号，板型无守卫或其他免死技能，故11号应记为当夜死亡。','constraint','相邻源稿片段合读为狼人击杀11号预言家。首夜明确女巫用解药救9号；预女猎白混板型没有守卫，也无其他免死技能可使11号存活，因此死亡名单可反推11号。','high',[event(2,'night','wolf_attack',{'action':'attack','actor':None,'targets':[11],'result':'狼队击杀11号预言家'}),event(2,'day','night_deaths',{'action':'die','actor':None,'targets':[11],'result':'第二夜狼刀11号预言家；首夜解药已用于9号'})]),
'146a3ee11ea284':(True,'第四夜毒杀最后一张狼人后游戏直接结束；第4天没有放逐事件。','transcription','源稿在第四夜先记狼人击杀7号平民、女巫毒杀6号狼人，紧接着明确说最后一张狼人且游戏结束。因此第四天放逐槽应为none。','high',[event(4,'day','exile_result',{'action':'none','actor':None,'targets':[],'result':'第四夜毒杀最后一张狼人后游戏结束'})]),
'f21f410abc3eea':(True,'首夜狼人击杀12号白神，女巫救起。','transcription','原句明确狼队击杀12号白神并由女巫救起。','high',[event(1,'night','wolf_attack',{'action':'attack','targets':[12],'result':'狼刀12号白神，女巫救起'})]),
'ad20f4f5345fb4':(True,'首夜预言家查验3号为好人。','transcription','角色名单显示11号预言家，夜间查验句直接给出3号好人。','high',[event(1,'night','seer_check',{'action':'check','actor':11,'targets':[3],'result':'好人'})]),
'e5b925abfecc78':(True,'第二夜狼刀11号预言家，次日11号与女巫毒杀的4号狼人双死。','transcription','原文直接说狼队击杀11号预言家、女巫毒杀4号查杀狼人，并明确两人当夜死亡。','high',[event(2,'night','wolf_attack',{'action':'attack','targets':[11],'result':'狼刀11号预言家'}),event(2,'day','night_deaths',{'action':'die','targets':[4,11],'result':'4号与11号双死'})]),
'775bd8875d6eee':(True,'座位身份名单与后续复盘一致：3号为狼人。','transcription','复盘身份名单将6号、1号、2号、3号、5号列入狼人阵营；3号后续称谓一致。','high',[seat(3,{'role':'狼人','faction':'werewolf'})]),
'7aa54fa8545ca5':(True,'座位身份名单与后续复盘一致：11号为预言家。','transcription','复盘身份名单直接称11号预言家，后续查验也由11号执行。','high',[seat(11,{'role':'预言家','faction':'good'})]),
'8ad60a61e39f7f':(True,'首夜11号预言家查验3号狼人。','transcription','原句明确预言家11号及其首夜查验3号狼人。','high',[event(1,'night','seer_check',{'action':'check','actor':11,'targets':[3],'result':'狼人'})]),
'a48505df1178ea':(True,'第二夜11号预言家查验5号狼人。','transcription','原句明确预言家11号在第二夜查验5号狼人。','high',[event(2,'night','seer_check',{'action':'check','actor':11,'targets':[5],'result':'狼人'})])
})
evidence_terms.update({
'a4d43860ece6c9':['狼人击杀，','十一号预言家女巫通过冤将验证十二号','狼人击杀九号，','平民女巫开药姐旧星辰，'],
'55f0348e264164':['9号混血儿','混血儿选择七号狼人榜样'],
'additional_round1_night_deaths_wrong_phase':['狼队击杀五号狼人','形成平安夜','拍刀'],
'42ff0d70455e7e':['混血儿7号','选择5号狼人为榜样'],
'146a3ee11ea284':['狼人击杀7号平民女巫毒杀6号','最后一张狼人游戏结束'],
'f21f410abc3eea':['狼人击杀12号白神女巫救起'],
'ad20f4f5345fb4':['预言家验证了3号玩家为好人身份'],
'e5b925abfecc78':['狼队击杀11号预言家女巫毒杀4号查杀狼人','4号与11号双死'],
'775bd8875d6eee':['6号狼人阵营一号2号三号五号'],
'7aa54fa8545ca5':['预言家11号女巫'],
'df07aa539edb1b':['混血儿8号','选择7号女巫为榜样'],
'8ad60a61e39f7f':['预言家验证3号玩家为狼人身份'],
'a48505df1178ea':['预言家验证了5号玩家为狼人身份'],
'47db9559f4a945':['12号混血儿4号','选择7号狼人为榜样'],
'e663f7815fe61b':['11号混血儿8号','选择5号狼人为榜样']
})
additional['BV12GEA6iEx5']=[extra_decision('BV12GEA6iEx5','55f0348e264164','首夜实际是平安夜；终局拍刀时提到的1/2/3不是首夜死亡名单。','transcription','首夜狼队击杀5号后女巫救起，源稿明确形成平安夜；1、2、3在复盘终局拍刀段出现，属于终局而不是首夜结算。',['形成平安夜'],[
 event(1,'day','night_deaths',{'action':'peaceful','actor':None,'targets':[],'result':'首夜狼刀5号后女巫救起，形成平安夜'})
])]
# Include the exact game-board rule used to infer the round-two death of 11.

new_games=[]
for game in queue:
    bvid=game['bvid']
    if bvid in games: continue
    questions=by_bvid[bvid]
    decisions=[]; changes=[]
    for x in questions:
        d,c=make_decision(x)
        decisions.append(d); changes.extend(c)
    for d,c in additional.get(bvid,[]):
        decisions.append(d); changes.extend(c)
    dossier_hash=questions[0]['dossier_sha256']
    # Correct all role-based mixed examples have only mixed_blood_model changes.
    g={'bvid':bvid,'dossier_sha256':dossier_hash,'decisions':decisions,'changes':changes,
       'summary':'；'.join(d['conclusion'].split('；')[0] for d in decisions[:3])}
    games[bvid]=g; new_games.append(g)
    if len(new_games)%4==0:
        plan['games']=[games[v['bvid']] for v in queue if v['bvid'] in games]
        with open(plan_path,'w',encoding='utf-8',newline='\n') as f: json.dump(plan,f,ensure_ascii=False,indent=2); f.write('\n')
        print('saved batch:',len(new_games),'new games;',len(plan['games']),'games total')

plan['games']=[games[v['bvid']] for v in queue if v['bvid'] in games]
with open(plan_path,'w',encoding='utf-8',newline='\n') as f: json.dump(plan,f,ensure_ascii=False,indent=2); f.write('\n')
qids={q['id'] for g in queue for q in g['questions']}
decids=[d['id'] for g in plan['games'] for d in g['decisions']]
input_count=sum(d in qids for d in decids)
print('final write games',len(plan['games']),'input questions',input_count,'unique input ids',len({d for d in decids if d in qids}),'new games',len(new_games))
print('unmatched queue IDs:',sorted(qids-set(decids)))
print('input duplicate decisions:',sorted(d for d in qids if decids.count(d)>1))
print('games:',[g['bvid'] for g in new_games])
