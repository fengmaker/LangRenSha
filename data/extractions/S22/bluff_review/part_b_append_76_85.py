import json
from pathlib import Path
root=Path('.')
out=Path('data/extractions/S22/bluff_review/part_b.json')
data=json.loads(out.read_text(encoding='utf-8'))
idx={g['bvid']:g for g in data['games']}
assess={
'BV1WEN86gERp':[
 (5,'no',None,'medium','[3773.870–3777.960] 8号通灵师被抗推出局','检查首日警上/自爆环节字幕及复盘，未定位5号本人明确自称预言家或通灵师。'),
 (6,'no',None,'high','[3765.200–3766.660] 女巫毒杀6号狼人','6号在首夜即被毒杀，没有首日警上发言机会。'),
 (7,'uncertain',None,'low','[1826.349–1827.670] 七就比较像悍跳','评论将7号描述为较像悍跳，但当前片段未能确认7号本人曾自称预言家/通灵师；请复核其竞选发言。'),
 (11,'no',None,'medium','[3777.960–3779.680] 第二天白天7号狼人自爆','检查首日竞选相关字幕及复盘，未定位11号本人明确自称信息神。')],
'BV1BPNB6QE1s':[
 (8,'no',None,'medium','[7986.970–7989.000] 12号狼人被公投出局','检查首日警上/警下相关发言，未定位8号本人自称预言家或通灵师；12号被首日放逐。'),
 (9,'yes','预言家','high','[1445.500–1447.160] 那我是预言家','9号在本人发言轮中明确自称预言家，且报告验8号；本局真预言家为7号。'),
 (10,'no',None,'medium','[7984.970–7986.290] 7号预言家获得警徽','检查首日竞选和查验相关发言，未定位10号本人自称信息神；复盘确认真预言家7号当选。'),
 (12,'no',None,'medium','[7986.970–7989.000] 12号狼人被公投出局','检查首日竞选相关字幕；未定位12号自称信息神，且复盘记录其首日被放逐。')],
'BV1BPNB6QE1V':[
 (1,'no',None,'medium','[4962.585–4966.345] 九号狼人高票七号定序王子出局','检查首日警上候选与身份神关键词相关字幕，未定位1号本人自称信息神。'),
 (6,'yes','预言家','medium','[585.040–585.700] 我是预言家','6号在其发言轮内出现明确预言家自称；本局真预言家为8号。'),
 (9,'no',None,'medium','[4980.585–4981.660] 九号狼人自爆','检查首日发言关键词和竞选记录，未定位9号本人自称信息神；复盘记其次日自爆。'),
 (10,'no',None,'medium','[4961.805–4962.525] 8号预言家获得警徽','检查竞选相关发言，未定位10号本人自称信息神；复盘确认真预言家8号当选。')],
'BV1BPNB6QE4z':[
 (1,'no',None,'high','[3377.720–3379.130] 8号唯一警下狼人自爆','1号机械狼全程未取得警上发言机会；首日自爆的是警下8号，未见1号自称信息神。'),
 (2,'no',None,'medium','[3406.450–3409.850] 最后一张狼人2号被公投出局','检查首日发言与竞选相关字幕，未定位2号本人自称预言家或通灵师。'),
 (5,'no',None,'medium','[3391.609–3394.969] 第二天白天5号狼人自爆','检查首日竞选相关字幕，未定位5号本人自称信息神；其于次日自爆。'),
 (8,'no',None,'high','[3377.720–3379.130] 8号唯一警下狼人自爆','8号在首次警上竞选的警下阶段自爆，未在此前发言中确认自称信息神。')],
'BV1jYKV6SETU':[
 (1,'no',None,'medium','[5475.120–5478.560] 5号预言家被抗推出局','检查首日竞选相关发言，未定位1号本人自称信息神。'),
 (3,'no',None,'high','[5482.350–5485.650] 女巫毒杀3号狼人','3号在首夜被毒杀，没有首日警上发言机会。'),
 (4,'no',None,'medium','[5475.120–5478.560] 5号预言家被抗推出局','检查首日竞选相关字幕，未定位4号本人自称预言家或通灵师。'),
 (7,'yes','预言家','high','[1376.920–1387.750] 我现在8号是金水……我预言家5号悍跳给我发查杀','7号在7号发言轮明确报8号金水并将5号称作悍跳预言家，属于狼人假跳；真预言家5号首日被抗推。')],
'BV1jYKV6SEwK':[
 (2,'yes','预言家','medium','[576.830–578.150] 11是个金水啊','2号狼在其发言轮报11号金水，构成预言家身份宣称；其后首日自爆。'),
 (5,'no',None,'medium','[2902.110–2903.390] 11号狼人选择自爆','检查首日发言与身份神关键词，未定位5号本人自称预言家或通灵师。'),
 (8,'no',None,'medium','[2880.920–2882.260] 8号假面','检查首日发言和竞选相关字幕，未定位8号本人自称信息神。'),
 (11,'no',None,'medium','[2902.110–2903.390] 11号狼人选择自爆','检查首日发言与竞选相关字幕，未定位11号本人自称信息神；其在第二天自爆。')],
'BV1dYKV6UEYM':[
 (5,'no',None,'medium','[5900.090–5902.490] 白天5号狼人被公投出局','检查首日警上候选与身份神关键词相关字幕，未定位5号本人自称信息神。'),
 (9,'no',None,'medium','[5919.570–5922.119] 9号狼人选择自爆入夜','检查首日竞选发言，未定位9号本人自称信息神；复盘记其次日自爆。'),
 (10,'no',None,'medium','[5879.620–5882.580] 12号机械狼10号','检查首日身份神相关发言，未定位10号本人自称信息神。'),
 (12,'no',None,'medium','[5909.980–5912.320] 机械女巫毒杀一号猎人','检查首日身份神相关发言，未定位12号本人自称信息神。')],
'BV12pNo6HEtA':[
 (1,'no',None,'medium','[5147.150–5160.310] 10号狼人被公投出局','检查警上竞选及首日发言中信息神身份自称，未定位1号本人自称。'),
 (5,'no',None,'high','[5145.360–5148.200] 第一天白天5号狼人选择自爆','5号在首日警上竞选后选择自爆；已查竞选字幕，未确认其自爆前自称信息神。'),
 (10,'no',None,'medium','[5157.150–5160.310] 10号狼人被公投出局','检查首日竞选发言及查验相关字幕，未定位10号本人自称信息神。'),
 (12,'no',None,'medium','[5167.649–5169.529] 12号狼人被公投出局','检查首日竞选发言及查验相关字幕，未定位12号本人自称信息神。')],
'BV12pNo6HEuV':[
 (7,'no',None,'medium','[8903.080–8904.340] 7号狼人选择自爆','检查首日警上/候选发言；未定位7号本人自称预言家或通灵师，次日自爆。'),
 (9,'yes','预言家','high','[565.539–567.299] 我验了八是狼','9号在9号玩家发言轮报告8号查杀，是对跳信息神的身份宣称；真预言家10号获得警徽。'),
 (12,'no',None,'medium','[8882.070–8884.030] 10号预言家获得警徽','检查首日竞选和身份神关键词发言，未定位12号本人自称信息神。')],
'BV12pNo6HEiz':[
 (4,'no',None,'medium','[6309.640–6312.360] 4号狼人被公投出局','检查首日警上与身份神关键词发言，未定位4号本人自称信息神。'),
 (7,'no',None,'medium','[6300.770–6302.949] 牛毒杀7号狼人','7号首日遭女巫毒杀，未有白天警上自称机会。'),
 (8,'yes','通灵师','high','[455.460–460.900] 验得六是查杀……','8号狼在警上发言轮声称验6号查杀，属于假跳通灵师；真通灵师6号当选。'),
 (9,'no',None,'unclear','[6322.830–6325.580] 9号机械双刀狼被公投出局','检查首日竞选相关发言；未定位9号本人自称信息神。')]
}
for bvid, rows in assess.items():
 d=next(Path('data/games/S22').glob(f'*_{bvid}/dossier.json'))
 j=json.loads(d.read_text(encoding='utf-8'))
 gdir=d.parent.as_posix()
 g={'game_id':j['slug'],'bvid':bvid,'date':j['date'],'game_number':j['game_number'],'game_dir':gdir,'coverage':'recap_and_claims','notes':[],'assessments':[]}
 sub=next(f['path'] for f in j['files'] if f['role'] in ('subtitle','transcript'))
 for seat,decision,claimed,conf,recap,why in rows:
  p=next(x for x in j['seats'] if x['seat']==seat)
  # find matching recap line to anchor start/end
  import re
  m=re.search(r'\[(\d+(?:\.\d+)?)–(\d+(?:\.\d+)?)\]\s*'+re.escape(recap.split('] ',1)[1].strip()), '')
  # Use precisely bounded recap evidence timestamp/value from authored excerpt.
  times=re.match(r'\[(\d+(?:\.\d+)?)[–-](\d+(?:\.\d+)?)\]',recap)
  text=recap.split('] ',1)[1]
  if bvid=='BV1BPNB6QE1s' and seat==9:
   ev=[{'kind':'speech','source_path':sub,'start_ms':1445500,'end_ms':1447160,'text':'那我是预言家','interpretation':'9号发言轮明确自称预言家；复盘确认真预言家为7号。'}]
  elif bvid=='BV1BPNB6QE1V' and seat==6:
   ev=[{'kind':'speech','source_path':sub,'start_ms':585040,'end_ms':585700,'text':'我是预言家','interpretation':'在6号发言轮出现明确预言家自称；本局真预言家为8号。'}]
  elif bvid=='BV1jYKV6SETU' and seat==7:
   ev=[{'kind':'speech','source_path':sub,'start_ms':1376920,'end_ms':1387750,'text':'我现在8号是金水……我预言家5号悍跳给我发查杀','interpretation':'紧随7号发言提示出现，7号自报验人并明确称5号悍跳；假冒真预言家。'}]
  elif bvid=='BV1jYKV6SEwK' and seat==2:
   ev=[{'kind':'speech','source_path':sub,'start_ms':574550,'end_ms':578150,'text':'11是个金水啊','interpretation':'2号发言轮报验11号金水，按信息神验人报验视为预言家身份宣称。'}]
  elif bvid=='BV12pNo6HEuV' and seat==9:
   ev=[{'kind':'speech','source_path':sub,'start_ms':565539,'end_ms':567299,'text':'我验了八是狼','interpretation':'紧随9号发言提示，9号报告查杀，构成预言家身份宣称；真预言家10号当选。'}]
  elif bvid=='BV12pNo6HEiz' and seat==8:
   ev=[{'kind':'speech','source_path':sub,'start_ms':455460,'end_ms':460900,'text':'验得六是查杀验六的心路历程','interpretation':'8号发言轮报告查杀并阐述验人心路，是假跳通灵师；真通灵师6号当选。'}]
  elif bvid=='BV1WEN86gERp' and seat==7:
   ev=[{'kind':'commentary','source_path':sub,'start_ms':1826349,'end_ms':1827670,'text':'七就比较像悍跳','interpretation':'解说判断7号较像悍跳，但没有直接证据确认其本人自称预言家/通灵师，因此保留疑问。'}]
  else:
   ev=[{'kind':'recap','source_path':f'{gdir}/复盘原文.txt','start_ms':round(float(times.group(1))*1000),'end_ms':round(float(times.group(2))*1000),'text':text,'interpretation':why}]
  g['assessments'].append({'seat':seat,'name':p['name'],'physical_role':p['role'],'decision':decision,'claimed_role':claimed,'confidence':conf,'evidence':ev,'calls':[],'review_questions':(['请复核7号首日是否本人明确自称预言家或通灵师。'] if bvid=='BV1WEN86gERp' and seat==7 else [])})
 data['games'].append(g)
data['games'].sort(key=lambda g:g['game_id'])
out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('total games',len(data['games']),'new',sum(1 for g in data['games'] if g['bvid'] in assess))
print('counts', {x:sum(a['decision']==x for g in data['games'] for a in g['assessments']) for x in ['yes','uncertain','no']})

