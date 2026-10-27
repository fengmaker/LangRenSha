import json,os,tempfile,re
from pathlib import Path
out=Path('data/extractions/S22/bluff_review/part_b.json'); data=json.loads(out.read_text(encoding='utf-8'))
rows={
'BV1iMgq6ZEtz':[
(4,'no',None,'medium','[4798.010–4802.950] 6号预言家获得警徽……6号预言家被抗推出局','检查首日竞选相关字幕未定位4号本人自称信息神；复盘确认6号是真预言家。'),
(7,'no',None,'medium','[4815.050–4819.490] 女巫毒杀7号狼王……2号七号双死','检查首日相关字幕未定位7号本人冒充预言家或通灵师；复盘记其夜间被毒杀。'),
(12,'no',None,'medium','[4798.010–4802.950] 6号预言家获得警徽……6号预言家被抗推出局','检查首日竞选发言未定位12号本人自称信息神；复盘确认6号是真预言家。')],
'BV1iMgq6ZEWn':[
(2,'yes','通灵师','medium','[872.210–873.835] 二号玩家给八号玩家发金水','该轮发言中明确指出2号给8号报金水；结合2号狼人底牌及本局真通灵师5号，按其信息神验人身份宣称计入。'),
(3,'no',None,'medium','[5245.370–5249.470] 五号通灵师获得警徽……六号狼人被公托出局','检查首日竞选相关字幕未定位3号机械狼本人自称信息神；复盘明确真通灵师5号。'),
(6,'no',None,'medium','[5245.370–5249.470] 五号通灵师获得警徽……六号狼人被公托出局','6号首日被通灵师查杀并放逐；其应对中未定位到本人自称预言家或通灵师。'),
(8,'no',None,'medium','[5245.370–5249.470] 五号通灵师获得警徽……六号狼人被公托出局','检查首日竞选和查验相关字幕未定位8号本人自称信息神。'),
(11,'no',None,'medium','[5245.370–5249.470] 五号通灵师获得警徽……六号狼人被公托出局','检查首日竞选相关字幕未定位11号本人自称信息神。')],
'BV1mE3z6XEB1':[
(3,'no',None,'medium','[5366.460–5372.640] 第一天白天5号悍跳狼人被公投出局……女巫毒杀12号狼人','检查首日竞选字幕未定位3号本人自称信息神；复盘明确5号悍跳。'),
(5,'yes','预言家','high','[5366.460–5369.480] 第一天白天5号悍跳狼人被公投出局','裁判复盘明确5号狼悍跳并首日被放逐；本局真预言家为1号。'),
(6,'no',None,'medium','[5366.460–5372.640] 第一天白天5号悍跳狼人被公投出局……女巫毒杀12号狼人','检查首日竞选字幕未定位6号本人自称信息神；复盘明确5号悍跳。'),
(12,'no',None,'medium','[5369.480–5372.640] 入夜狼人击杀7号女巫女巫毒杀12号狼人','12号在首夜后被毒杀，没有其首日警上自称信息神的证据。')],
'BV1h33z6tEqx':[
(6,'no',None,'high','[4440.300–4445.510] 6号被梦王出局……一号通灵师一号被刀出局','6号首夜被梦游者淘汰，未进入首日竞选发言。'),
(10,'yes','通灵师','high','[4434.490–4437.240] 第一天白天10号悍跳狼人被公投出局','裁判复盘明确10号狼人悍跳并首日出局；本局真通灵师为1号。'),
(11,'no',None,'medium','[4455.450–4459.750] 将警徽移交至4号射梦人……11号狼人自爆入夜','检查首日相关字幕未定位11号本人自称信息神；复盘记其在次日自爆。'),
(12,'no',None,'medium','[4422.290–4434.490] 盗宝大师选择平民身份……一号通灵师获得警徽','盗宝大师12号选择平民身份；检查首日相关字幕未定位其本人自称预言家或通灵师。')],
'BV13g3z6FEdh':[
(3,'no',None,'high','[4627.510–4630.910] 狼人击杀一号女巫……女巫毒杀3号狼人','3号在首夜被毒杀，没有首日警上发言机会。'),
(4,'no',None,'medium','[4634.830–4639.760] 6号通灵师获得警徽……10号机械猎人被公投出局','检查首日竞选相关字幕未定位4号本人自称信息神；复盘明确6号真通灵师获警徽。'),
(8,'yes','通灵师','high','[4646.260–4648.630] 第二天白天8号悍跳狼人自爆','裁判复盘明确8号狼悍跳后自爆；本局信息神为通灵师。'),
(10,'no',None,'medium','[4637.080–4639.760] 10号机械猎人被公投出局','10号机械狼以猎人身份出局；首日字幕未见其本人冒充预言家或通灵师。')]
}
all_dossiers=sorted(Path('data/games/S22').glob('*/dossier.json'))
bybvid={re.search(r'BV[0-9A-Za-z]{10}',p.parent.name)[0]:p for p in all_dossiers}
data['games']=[g for g in data['games'] if g['bvid'] not in rows]
new=[]
for bvid,entries in rows.items():
 p=bybvid[bvid]; d=json.loads(p.read_text(encoding='utf-8')); gd=p.parent.as_posix(); sub=next(x['path'] for x in d['files'] if x['role'] in ('subtitle','transcript'))
 g={'game_id':d['slug'],'bvid':bvid,'date':d['date'],'game_number':d['game_number'],'game_dir':gd,'coverage':'recap_and_claims','notes':[],'assessments':[]}
 for seat,decision,claim,conf,clip,why in entries:
  m=re.match(r'\[(\d+(?:\.\d+)?)–(\d+(?:\.\d+)?)\] (.*)',clip)
  who=next(x for x in d['seats'] if x['seat']==seat); path=sub if bvid=='BV1iMgq6ZEWn' and seat==2 else f'{gd}/复盘原文.txt'; kind='speech' if path==sub else 'recap'
  g['assessments'].append({'seat':seat,'name':who['name'],'physical_role':who['role'],'decision':decision,'claimed_role':claim,'confidence':conf,'evidence':[{'kind':kind,'source_path':path,'start_ms':round(float(m[1])*1000),'end_ms':round(float(m[2])*1000),'text':m[3],'interpretation':why}],'calls':[],'review_questions':[]})
 new.append(g)
data['games'].extend(new); data['games'].sort(key=lambda g:g['game_dir'])
fd,tmp=tempfile.mkstemp(dir=out.parent,prefix='part_b.',suffix='.tmp')
with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f: json.dump(data,f,ensure_ascii=False,indent=2); f.write(chr(10))
os.replace(tmp,out)
print('games',len(data['games']),'decisions',{k:sum(a['decision']==k for g in data['games'] for a in g['assessments']) for k in ('yes','uncertain','no')})
