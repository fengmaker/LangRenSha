import json,pathlib,sys
sys.stdout.reconfigure(encoding='utf-8')
target=pathlib.Path('data/extractions/S22/bluff_review/recheck_b.json')
payload=json.loads(target.read_text(encoding='utf-8'))
part=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_b.json').read_text(encoding='utf-8'))
old={g['bvid']:g for g in part['games']}
def dossier(b):return json.loads(next(pathlib.Path('data/games/S22').glob(f'*{b}/dossier.json')).read_text(encoding='utf-8'))
def source(b):
 d=dossier(b);f=next(x for x in d['files'] if x['role'] in ('subtitle','transcript'));return f['path'],d
def ev(kind,path,s,e,t,i):return {'kind':kind,'source_path':path,'start_ms':s,'end_ms':e,'text':t,'interpretation':i}
rows={}
def assessment(b,seat,decision,role,conf,note,review,evidence,claim_day=None,first=None):
 path,d=source(b);actual=next(x for x in d['seats'] if x['seat']==seat)
 es=[]
 for item in evidence:
  if len(item)==5:k,s,e,t,i=item;ep=path
  else:k,ep,s,e,t,i=item
  es.append(ev(k,ep,s,e,t,i))
 return {'seat':seat,'name':actual['name'],'physical_role':actual['role'],'decision':decision,'claimed_role':role,'first_day_claim':first,'claim_day':claim_day,'confidence':conf,'evidence':es,'review_questions':[review] if review else [],'decision_note':note}
# New first-day omissions discovered in the transcript; rest are old candidates rechecked.
rows['BV1hZMp63Esx']=[
 assessment('BV1hZMp63Esx',9,'yes','预言家','high','9号狼底牌在首日竞选警长发言中直接报5号金水并留警徽流，首日公开冒充预言家。',None,[('speech',1412680,1414660,'我验了五金水啊','9号首日竞选发言中的第一人称报验；视频同时间画面显示第二局竞选警长且9号发言。')],1,True),
 assessment('BV1hZMp63Esx',10,'yes','预言家','medium','10号首日警长竞选发言直接以7号金水和警徽流格式报验，作为警上信息神起跳；视频画面确认发言人是10号。',None,[('speech',1297000,1304170,'七金水警徽流…一号','10号竞选警长轮次的报验与警徽流。时间点画面显示10号本人发言，符合首日以预言家身份竞选。')],1,True)
]
rows['BV13ZMp63EEB']=[assessment('BV13ZMp63EEB',11,'yes','通灵师','high','11号首日公开自称通灵师；本局底牌狼人，复盘也明确记首日悍跳后自爆。',None,[('speech',1574555,1575735,'我说这把我是通灵师了','11号首日发言的第一人称身份主张；视频画面确认11号在麦。')],1,True)]
rows['BV1GxNH6YESw']=[assessment('BV1GxNH6YESw',6,'yes','预言家','high','6号首日发言明确自称预言家并报告验人，复盘另确认其获得警徽、首日真预言家出局。',None,[('speech',1550740,1551900,'我是预言家好吧','6号首日竞选发言中的直接自称。')],1,True)]
rows['BV1GxNH6YEht']=[assessment('BV1GxNH6YEht',8,'yes','预言家','high','8号首日竞选发言第一人称报告10号金水并留警徽流；真预言家为9号。',None,[('speech',641460,643020,'我验的十是金水','8号首日发言的第一人称报验。')],1,True)]
rows['BV1VxNH6YETC']=[assessment('BV1VxNH6YETC',5,'yes','通灵师','high','5号首日发言以第一人称报3号平民验人，并明确称自己是通灵师。',None,[('speech',951800,954420,'我就觉得我这个通灵师验狼太钢铁了','5号首日发言中直接以通灵师身份解释验人。')],1,True)]
rows['BV1YxNH6YEqY']=[assessment('BV1YxNH6YEqY',3,'uncertain',None,'low','复盘只记3号在延期竞选环节自爆，不能据此判定此前是否已公开跳预言家/通灵师；本次字幕没有可靠归到3号本人的首日主张。','需进一步回听3号首日延期竞选前后的个人发言，确认是否明确自称预言家或通灵师。',[('recap','data/games/S22/2026-07-10_g04_BV1YxNH6YEqY/复盘原文.txt',2962579,2965440,'延期竞选环节3号狼人选择自爆','复盘只说明延期竞选自爆，不证明信息神起跳。')],None,None)]
rows['BV1sEN86gEM2']=[
 assessment('BV1sEN86gEM2',6,'uncertain','预言家','low','复盘将6号判为悍跳狼，但本次首日6号个人字幕窗口虽有验人/警徽相关发言，未能定位到明确自称预言家或通灵师的完整句，不能仅凭复盘归类。','已定位6号首日约1269–1437秒发言；需确认该轮是否明确冒充预言家/通灵师。',[('recap','data/games/S22/2026-07-14_g01_BV1sEN86gEM2/复盘原文.txt',3466700,3468600,'6号悍跳狼人自爆','复盘支持其被认定悍跳，但不足以代替首日个人主张。')],None,None),
 assessment('BV1sEN86gEM2',8,'uncertain',None,'low','复盘记载8号被真预言家查出狼人并在延期竞选自爆；没有找到8号首日公开自称信息神的个人窗口。','请核对8号延期竞选自爆之前的首日发言是否有明确身份主张。',[('recap','data/games/S22/2026-07-14_g01_BV1sEN86gEM2/复盘原文.txt',3471140,3476010,'预言家验证8号玩家为狼人身份……8号狼人自爆','查杀与自爆不证明8号自己曾跳信息神。')],None,None)]
rows['BV1PEN863EXG']=[assessment('BV1PEN863EXG',5,'uncertain','通灵师','low','复盘明确将5号称为悍跳狼，但未能把已有首日字幕中的“通灵师”主张可靠归到5号本人；仅凭复盘不能确认首日动作。','请核对5号首日个人发言，尤其是报验及警徽流窗口。',[('recap','data/games/S22/2026-07-14_g02_BV1PEN863EXG/复盘原文.txt',4679090,4681490,'5号悍跳狼人被公投出局','复盘只确认悍跳并被放逐，当前未定位本人首日自称。')],None,None)]
rows['BV1WEN86gE1i']=[assessment('BV1WEN86gE1i',3,'yes','通灵师','high','3号首日个人发言报12号查杀并留验人视角，复盘明示其首日白天悍跳后自爆。',None,[('speech',1185740,1187600,'我验了12号玩家是查杀牌','3号首日发言中的第一人称报验；与复盘的首日悍跳记录相合。')],1,True)]
rows['BV1WEN86gERp']=[assessment('BV1WEN86gERp',7,'no',None,'high','视频确认7号在首日约1245秒和1550秒的本人发言轮次；两轮均在讨论他人验人/警徽，没有7号自称预言家或通灵师。字幕2422秒“我是通灵师”对应画面中的8号桃子，不能归到7号。',None,[('commentary','data/seasons/S22/第08周_正赛第07期/2026-07-14/2026-07-14_S22_第08周_正赛第07期_第04局_机械狼通灵师__BV1WEN86gERp_P01_CID39951731181.平台AI字幕_ai-zh_01.原始.json',1826349,1827670,'七就比较像悍跳','这是旁人对7号像悍跳的判断；逐帧核对其本人首日轮次未出现明确自称，故不据此判悍跳。')],None,False)]
rows['BV1BPNB6QE1s']=[assessment('BV1BPNB6QE1s',9,'yes','预言家','high','9号首日发言明确自称预言家，并报12号金水、留警徽流。',None,[('speech',1445500,1447160,'那我是预言家','9号首日发言中的第一人称自称。'),('speech',1455900,1457380,'我验的12金水我就直接就跳了','9号明确说明报验并起跳。')],1,True)]
rows['BV1BPNB6QE1V']=[assessment('BV1BPNB6QE1V',6,'yes','预言家','high','6号狼人底牌在首日警上发言中明确自称预言家并报验。',None,[('speech',585040,585700,'我是预言家','6号首日警上个人发言的直接自称。')],1,True)]
rows['BV1jYKV6SETU']=[assessment('BV1jYKV6SETU',7,'yes','预言家','high','7号首日警上接5号查杀后明确以预言家身份回应，并报8号金水及警徽流。',None,[('speech',1376920,1390270,'我现在8号是金水……我预言家5号悍跳给我发查杀','7号首日警上发言的第一人称报验和预言家自称。')],1,True)]
# Resolve all matching current old candidates in games66–80, plus the two omitted day-one wolves.
for g in old.values():
 b=g['bvid']
 if b in rows:continue
 if 66<=next(i for i,x in enumerate(part['games'],51) if x['bvid']==b)<=80 and any(a['decision'] in ('yes','uncertain') for a in g['assessments']):
  print('missing candidate game',b)
# merge subset into already written first batch
ordered=[]
for g in part['games']:
 idx=next(i for i,x in enumerate(part['games'],51) if x['bvid']==g['bvid'])
 if idx<66 or idx>80:continue
 if g['bvid'] not in rows:continue
 ordered.append({'game_id':g['game_id'],'bvid':g['bvid'],'first_day_end_ms':None,'assessments':rows[g['bvid']]})
by={g['bvid']:g for g in payload['games']}
by.update({g['bvid']:g for g in ordered})
new=[]
for g in part['games']:
 if g['bvid'] in by:new.append(by[g['bvid']])
payload['games']=new
tmp=target.with_suffix('.json.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(target)
print('updated',len(payload['games']),'games',sum(len(g['assessments']) for g in payload['games']),'total records')
