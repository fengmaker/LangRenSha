import json, pathlib, re

ROOT=pathlib.Path('.')
PA=json.loads((ROOT/'data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig'))

# (game index, seat): decision, role, evidence needle, center_ms, note, review question
C={}
def setc(i,s,d,r=None,n='',q=None,needle=None,t=None,vis=None):
    C[(i,s)]={'decision':d,'role':r,'needle':needle,'t':t,'note':n,'question':q,'visual':vis or []}
V=lambda b,t,o:{'path':f'data/extractions/S22/bluff_review/video_recheck/{b}_{t//1000:05d}.000.png','time_ms':t,'observation':o}
# First-day claimant evidence confirmed in their own speech turn.
setc(1,1,'no',None,'首日警下轮次核对至第一夜转换；1号在3031320–3068790谈警徽票与站边，没有自称预言家/通灵师。',needle='我把警徽票呢投给的是8号',t=3031320,vis=[V('BV1kGVC6cEyg',3030000,'画面顶部标注第一天，当前发言位为1号；内容是警徽票及站边。')])
setc(1,8,'yes','预言家','首日8号发言直接报验人与警徽信息，后续继续自称预言家。',needle='我验的12是金水啊',t=1436220)
setc(2,5,'yes','通灵师','首日5号发言报验人与警徽流；其底牌为盗宝大师，公开冒称通灵师。',needle='我验的6号玩家是金水嗯',t=1291440)
setc(3,5,'yes','通灵师','首日5号在本人发言中自称通灵师。',needle='我这个通灵师',t=794240)
setc(4,7,'uncertain','预言家','首日复盘/旁人后述指向7号警上起跳，但尚未在逐字稿中锁定7号本人的起跳发言轮次。',q='首日警上竞选中7号是否本人公开报验人或警徽流？需要确认对应发言轮。',needle='然后七号员是补跳的这个位置',t=2026795)
setc(4,5,'yes','预言家','首日警下本人发言直接自称预言家；视频帧确认该发言人为5号。',needle='其实我本就是预言家',t=2295365,vis=[V('BV1hb7R6XEtD',2295000,'顶部标注第一局第一天，当前名牌为5号耿许儿。')])
for s in (5,7,10,12): setc(5,s,'no','预言家','旧引用224500早于首日天亮；检查了首日发言段及竞选/警下轮次，没有发现该狼人本人首日自称信息神。')
for s in (1,9,11): setc(6,s,'no',None,'首日候选“我通灵师熬夜了”经视频定位为7号好人发言；检索这三名狼的首日发言未见本人跳信息神。',needle='我通灵师熬夜了',t=473730,vis=[V('BV1dJ7R6fEUw',473000,'当前大名牌为7号；非1/9/11号。')])
setc(6,10,'no','通灵师','“我底牌是一个通灵师”是4号本人发言，不是10号机械狼；10号首日发言未见公开冒称信息神。',needle='我底牌是一个通灵师',t=549550,vis=[V('BV1dJ7R6fEUw',549000,'当前大名牌为4号；非10号。')])
for s in (5,8,11): setc(7,s,'no','预言家','“我呢是预言家啊”属于6号发言；视频名牌确认，非这三名狼人。首日其余本人轮次未发现起跳。',needle='我呢是预言家啊',t=1243515,vis=[V('BV12GEA6iEx5',1244000,'当前名牌显示6号KS，非5/8/11号。')])
setc(7,7,'uncertain','预言家','复盘确认7号曾在警上悍跳并获警徽，但可用逐字稿片段尚未独立锁定7号本人首日发言。',q='需确认7号在首日警上竞选中的本人发言窗口及是否报验人/警徽流。')
for s in (1,2,6,9): setc(8,s,'uncertain','通灵师','首日844735附近有“我是通灵师”并接着报验人；视频确认是第一天，但当前镜头不能可靠辨认说话座位，不能据此在四狼间排除或硬判。',q='请确认844735–900145ms这一首日发言轮对应的座位；此归属决定狼人1/2/6/9是否悍跳。',needle='有一个第二啊我是通灵师',t=844735,vis=[V('BV117EA6AEcV',845000,'顶部为第二局第一天；当前画面没有可读的发言者名牌，侧栏无法单独确认座位。')])
setc(9,2,'yes','预言家','首日2号本人连续自称预言家并报验人；视频名牌确认该窗口为狼人2号。',needle='我是预言家',t=1486710,vis=[V('BV1FX7C6BEAC',1487000,'画面名牌清晰显示2号桃子。')])
for s in (5,6,12): setc(9,s,'no','预言家','旧候选“就决定我本局一定要跳预言家”属于4号的计划/转述，不是这名狼人本人首日宣称；首日本人轮次未找到其他起跳。',needle='就决定我本局一定要跳预言家',t=1413370)
setc(10,3,'yes','预言家','首日3号本人轮次报验人并接续解释好人身份，视频名牌确认为狼人3号；上下文是信息神发言。',needle='我说我验了他是个好人啊',t=657710,vis=[V('BV1fX7C6qESY',653000,'第一天当前发言名牌显示3号翼风。')])
for s in (4,5,8): setc(10,s,'no','预言家','旧引用328920在首日天亮之前；首日本人发言轮次未发现狼人4/5/8自称预言家或通灵师。')
for s in (3,9,10): setc(11,s,'no',None,'首日逐字稿中未找到该座位本人公开报验人/警徽流的起跳；“12号悍跳”指向12号，不支持3/9/10。')
setc(11,12,'uncertain','预言家','后述明确将12号称作悍跳，但首日逐字稿尚未锁定12号本人信息神起跳窗口。',q='首日12号是否公开自称预言家/通灵师？目前只能确认旁述指向，需精确对齐本人轮次。',needle='我的底牌跟通灵师没有关系啊',t=1461560)
setc(12,2,'uncertain','预言家','首日出现“我是预言家”及验人/警徽流连续内容；前置法官提示的座位与自报验人号码存在冲突，不能仅凭转写确定发言人为狼人2号。',q='核实1330070–1368360ms发言轮的实际座位，尤其转写“验了12号是金水”与法官前置点名之间的轮次矛盾。',needle='我是预言家',t=1330070)
setc(13,7,'uncertain','通灵师','首日复盘称7号狼王悍跳并拿到警徽；现有逐字稿证据未精确落到7号本人发言。',q='需核实首日7号自己的发言是否冒称通灵师/预言家及是否退水。')
setc(14,9,'uncertain','通灵师','复盘称9号悍跳后出局，但尚未确认9号首日本人起跳发言窗口。',q='需核对首日9号发言是否本人报验/警徽流。')
setc(14,10,'yes','预言家','首日10号本人自称预言家，且前一轮说明自己为通灵师并谈验人。',needle='我是预言家',t=1943660)
setc(15,12,'yes','预言家','首日12号本人发言称拿到预言家牌，并在发言中报验人与警徽流。',needle='我摸到了一张预言家牌',t=1427600)
setc(16,4,'no','预言家','旧证据“我认为8号玩家呢是一个真的预言家”是评述8号身份，不是4号自称；首日4号本人轮次未见起跳。',needle='我认为8号玩家呢是一个真的预言家',t=2204740)
setc(16,6,'uncertain','预言家','复盘称6号狼人悍跳并获警徽，但尚未从首日逐字稿中定位6号本人起跳的连续原话。',q='需确认首日6号警上本人发言是否公开报验/警徽流。')
for s in (2,5,10): setc(17,s,'no','通灵师','旧候选“然后我是通灵师好吧”由6号KS真通灵师说出，视频名牌确认；2/5/10号本人首日轮次未发现信息神主张。',needle='然后我是通灵师好吧',t=1805030,vis=[V('BV1sYEo6QEyS',1805000,'画面名牌为6号KS，非狼人2/5/10。')])
setc(18,12,'uncertain','通灵师','复盘明确12号悍跳并自爆，但首日逐字稿出现的通灵师候选尚不能稳妥归到12号本人。',q='需将首日“我是通灵师牌”附近发言轮与12号座位/视频画面对应。',needle='我是通灵师牌',t=734000)
setc(19,7,'yes','预言家','首日7号被法官点名发言后直接自称预言家。',needle='我是预言家',t=1282780)
setc(20,11,'yes','预言家','首日11号本人发言报10号金水并留验人/警徽安排；旧“11号悍跳”旁述仅作辅助。',needle='因为我验了10号是金水',t=622190)
setc(21,12,'yes','通灵师','首日12号机械狼公开称拿到通灵师身份并以该身份解释发言。',needle='我拿通灵师确实发言不太好',t=1106870)
setc(22,6,'yes','通灵师','首日6号本人明确称自己是通灵师，并报验人。',needle='我现在是通灵师',t=642119)
setc(23,2,'yes','预言家','首日2号本人报验人、金水和警徽流，且处于2号发言轮。',needle='警徽流12号',t=1231550)
setc(24,7,'yes','通灵师','首日7号本人以通灵师身份解释为何要验人。',needle='那我也想我通灵师不得验一下啊',t=970620)
setc(26,3,'no','预言家','旧引用“我是预言家牌啊”属于12号发言轮；视频/法官轮次交叉后不支持3号本人首日跳神。',needle='我是预言家牌啊',t=1896220)
setc(26,12,'yes','预言家','首日12号本人报验人、金水并直接自称预言家；原先被重复归到3号的字幕实际属于12号轮次。',needle='我验了80金水啊',t=1812510)
setc(29,11,'yes','预言家','首日11号本人发言称“我是一张预言家牌”，并报验人。',needle='我是一张预言家牌',t=1602470)
setc(30,8,'uncertain','预言家','复盘称8号在首日悍跳后自爆，但暂未锁定其本人首日claim发言窗口。',q='需核实首日8号在本人轮次是否自称预言家/通灵师。')
setc(30,11,'no','预言家','旧引用“我是一张预言家”对应1号发言窗口，不是11号；核对11号本人首日轮次未发现信息神起跳。',needle='我是一张预言家',t=1006690)
setc(31,3,'no','通灵师','旧“我是预言家牌啊”引用经视频/法官轮次核对属于8号发言，不是3号；3号首日本人轮次未找到其他信息神自称。',needle='我是预言家牌啊',t=1401380,vis=[V('BV1xkL96MEsd',1401000,'画面名牌显示8号，非3号。')])
setc(32,2,'yes','预言家','首日2号本人发言明确自称预言家，随后报8号金水。',needle='我是预言家',t=1118220)
setc(33,6,'yes','预言家','首日6号本人发言报验人并以预言家视角留警徽流；法官轮次与连续语义指向6号。',needle='然后验了四是个狼',t=818180)
setc(34,7,'uncertain','通灵师','旧证据是旁人描述“7号到目前为止是一个起跳通灵师的状态”，未锁定7号本人首日claim窗口。',q='需核实首日7号本人是否自称通灵师/预言家。',needle='就是7号到目前为止是一个起跳通灵师的状态',t=2776450)
setc(35,2,'yes','预言家','首日2号本人发言称验出查杀并说明自己起跳，属于信息神claim语境。',needle='我都验的查杀跟我起跳了',t=1539930)
setc(37,4,'uncertain','通灵师','复盘称4号悍跳后自爆，但当前逐字稿尚未定位到4号本人首日claim窗口。',q='需核实首日4号本人发言是否公开冒称通灵师/预言家。')
setc(38,12,'yes','预言家','首日12号本人报第一夜验人并自称预言家。',needle='我第一天晚上验了八',t=2068740)
setc(39,3,'no','预言家','旧字幕“反正我是预言家”经视频名牌定位为7号本人发言；不属于3号，3号其他首日轮次未发现claim。',needle='反正我是预言家',t=1278970,vis=[V('BV1DijD6BE4g',1279000,'画面名牌显示7号小苍，非3号。')])
setc(39,7,'yes','预言家','首日7号本人直接自称预言家；视频名牌确认发言者为7号。',needle='反正我是预言家',t=1278970,vis=[V('BV1DijD6BE4g',1279000,'画面名牌显示7号小苍。')])
setc(40,1,'yes','通灵师','首日1号本人自称通灵师并说明验人。',needle='反正我是通灵师验的',t=1048880)
setc(41,5,'uncertain','预言家','复盘称5号狼警上悍跳并取得警徽；未锁定5号本人首日原始发言窗口。',q='需核实首日5号本人是否报验/警徽流，及是否在警上/警下起跳。')
setc(41,12,'yes','预言家','首日12号本人连续说预言家、报第一天验人并留警徽流；错别字不影响发言语义。',needle='我是预言家票',t=1371520)
setc(42,6,'uncertain','预言家','复盘称6号悍跳后自爆，但尚未定位6号本人首日claim发言。',q='需核实首日6号本人轮次是否冒称预言家/通灵师。')
for s in (1,2,9,11): setc(43,s,'no','通灵师','旧候选“他说如果我跳通灵师”是4号的条件转述，视频确认说话者为好人4号；逐一核对四狼首日轮次未发现本人信息神claim。',needle='他说如果我跳通灵师',t=2274105,vis=[V('BV13Ajo6xEY8',2274000,'第一天，画面名牌显示4号贝拉爷，所说为条件句。')])
setc(44,7,'yes','预言家','首日7号本人明确自称预言家。',needle='我是预言家',t=2007830)
setc(44,12,'yes','预言家','首日12号本人报第一天验人并交代金水，处于12号发言轮。',needle='然后第一天验的4号玩家是金水',t=1522970)
setc(45,7,'uncertain','预言家','复盘明确7号狼获得警徽，倾向竞选中起跳；未在首日逐字稿锁定7号本人claim轮次。',q='需确认首日7号本人是否公开报验/警徽流。')
setc(46,12,'yes','预言家','首日12号本人报验金水并继续发言，符合预言家claim。',needle='我验的干干是金水啊',t=943960)
setc(48,6,'yes','通灵师','首日6号本人在6号发言轮报查杀与验人，并以通灵师身份发言。',needle='我验了2号玩家是查杀双抓狼',t=953280)
setc(48,7,'yes','通灵师','首日7号盗宝大师本人称自己是通灵师；属冒称信息神。',needle='那我是通灵师',t=1342960)
setc(49,9,'yes','通灵师','首日9号本人明确自称通灵师并报金水。',needle='我是通灵师牌',t=918960)
setc(49,12,'yes','预言家','首日12号本人报11号查杀，前置法官提示为12号发言。',needle='我验的11号是查杀',t=1637780)
setc(50,8,'no','预言家','核对8号首日本人发言段993680–1075700，内容是回应10号查杀/原始跳位，没有8号自称预言家或通灵师；旧证据是旁人讨论8查杀7。',needle='确实验的',t=1007280)
setc(50,10,'yes','预言家','首日10号本人发言自称预言家并报8号查杀；视频名牌确认10号陈明峻。',needle='我是预言家呀',t=1373300,vis=[V('BV1cJ7L64EBW',1373000,'第一天画面中当前名牌为10号陈明峻。')])

def load_segments(g):
    p=ROOT/g['game_dir']; d=json.loads((p/'dossier.json').read_text(encoding='utf-8-sig'))
    f=next((x for x in d.get('files',[]) if x.get('role')=='subtitle'),None) or next((x for x in d.get('files',[]) if x.get('role')=='transcript'),None)
    if not f:return d,None,[]
    j=json.loads((ROOT/f['path']).read_text(encoding='utf-8-sig')); raw=j.get('body',j.get('segments',[])); arr=[]
    for x in raw:
        if 'from' in x:a=round(float(x.get('from',0))*1000);b=round(float(x.get('to',x.get('from',0)))*1000);t=x.get('content','')
        else:a=int(x.get('start_ms',0));b=int(x.get('end_ms',a));t=x.get('text','')
        arr.append((a,b,t))
    return d,f['path'],arr

out={'schema_version':1,'scope':'first_day','games':[]}
for idx,g in enumerate(PA['games'],1):
    old={a['seat']:a for a in g['assessments'] if a['decision']!='no'}
    cases={s:x for (i,s),x in C.items() if i==idx}
    # include only old yes/uncertain plus newly found omissions
    if not cases: continue
    d,source,arr=load_segments(g)
    dawn=next((a for a,b,t in arr if '天亮' in t),None)
    end=None
    if dawn is not None:
        later=[(a,t) for a,b,t in arr if a>dawn and ('选择自爆' in t or '天黑请闭眼' in t)]
        if later:end=later[0][0]
    roster={s['seat']:s for s in d['seats']}
    assessments=[]
    for seat,c in sorted(cases.items()):
        s=roster[seat]; role=c['role']; needle=c['needle']; center=c['t']; ev=[]
        if needle and source:
            matches=[(a,b,t) for a,b,t in arr if needle in t and (center is None or abs(a-center)<=90000)]
            if not matches: matches=[(a,b,t) for a,b,t in arr if needle in t]
            if matches:
                a,b,t=matches[0]
                ev=[{'kind':'speech','source_path':source,'start_ms':a,'end_ms':b,'text':t,
                     'interpretation':c['note']}]
        if c['decision']=='yes' and not ev:
            raise RuntimeError(f'missing evidence for yes game {idx} seat {seat}: {needle}')
        questions=[c['question']] if c['question'] else []
        x={'seat':seat,'name':s['name'],'physical_role':s.get('role'),'decision':c['decision'],
           'claimed_role':role,'first_day_claim':True if c['decision']=='yes' else (False if c['decision']=='no' else None),
           'claim_day':1 if c['decision']=='yes' else None,'confidence':'high' if c['decision']=='yes' else ('medium' if c['decision']=='no' else 'low'),
           'evidence':ev,'review_questions':questions,'decision_note':c['note']}
        if c['visual']:x['visual_checks']=c['visual']
        assessments.append(x)
    out['games'].append({'game_id':d['slug'],'bvid':g['bvid'],'first_day_end_ms':end,'assessments':assessments})
dest=ROOT/'data/extractions/S22/bluff_review/recheck_a.json'; tmp=dest.with_suffix('.json.tmp')
tmp.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); tmp.replace(dest)
print('wrote',dest,'games',len(out['games']),'assessments',sum(len(g['assessments']) for g in out['games']))
print('counts', {x:sum(a['decision']==x for g in out['games'] for a in g['assessments']) for x in ('yes','no','uncertain')})
