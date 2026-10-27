import json,os,tempfile,re
from pathlib import Path
out=Path('data/extractions/S22/bluff_review/part_b.json')
data=json.loads(out.read_text(encoding='utf-8'))
rows={
'BV1oNKY6zE1Z':[
(6,'yes','预言家','high','[5262.535–5266.205] 将为狼人身份上警环节六号悍跳郎获得警徽','复盘确认6号狼悍跳并赢得警徽。'),
(9,'no',None,'medium','[5262.535–5266.205] 将为狼人身份上警环节六号悍跳郎获得警徽','复盘明确首日悍跳者为6号；检查首日竞选字幕未定位9号本人报预言家或通灵师。'),
(10,'no',None,'medium','[5262.535–5266.205] 将为狼人身份上警环节六号悍跳郎获得警徽','复盘明确首日悍跳者为6号；检查首日竞选字幕未定位10号本人报信息神。'),
(11,'no',None,'medium','[5279.455–5281.315] 六号将警徽撕掉十一号狼人','检查首日竞选及首轮相关字幕未定位11号本人报预言家或通灵师；复盘仅记其次日接警徽后自爆。')],
'BV1fPKY6gEFp':[
(4,'no',None,'medium','[2179.449–2182.169] 预言家验证4号玩家假面为狼人身份','检查首日发言与竞选相关字幕未定位4号本人自称信息神。'),
(5,'yes','预言家','high','[2202.870–2204.290] 5号悍跳狼人自爆','裁判复盘直接称5号为悍跳狼；本局信息神为预言家。'),
(7,'uncertain',None,'low','[2183.089–2184.250] 7号狼人自爆','7号在首轮警上环节自爆，但复盘及竞选转写尚未确认自爆前是否自称信息神。'),
(10,'no',None,'medium','[2222.869–2223.889] 10号狼人自爆','检查首日相关字幕未定位10号本人自称预言家或通灵师；复盘只记其后续自爆。')],
'BV1bWKY6tEri':[
(2,'no',None,'medium','[6933.940–6939.215] 三号玩家为猎人身份上警环节九号悍跳狼人获得警徽','检查首日相关字幕未定位2号本人自称信息神；复盘明确9号悍跳。'),
(6,'no',None,'medium','[6933.940–6939.215] 三号玩家为猎人身份上警环节九号悍跳狼人获得警徽','检查首日相关字幕未定位6号本人自称信息神；复盘明确9号悍跳。'),
(9,'yes','通灵师','high','[6933.940–6939.215] 三号玩家为猎人身份上警环节九号悍跳狼人获得警徽','裁判复盘明确9号狼悍跳并获得警徽；本局真通灵师7号首日出局。'),
(11,'no',None,'medium','[6933.940–6939.215] 三号玩家为猎人身份上警环节九号悍跳狼人获得警徽','检查首日竞选与身份神自称相关字幕未定位11号本人报身份；复盘明确9号悍跳。')],
'BV1Abgy6tEP8':[
(4,'no',None,'medium','[4926.520–4932.340] 12号通灵师获得警徽……9号警下跳起来的悍跳狼被公投出局','复盘明确9号为悍跳者；未定位4号本人自称信息神。'),
(8,'no',None,'medium','[4926.520–4932.340] 12号通灵师获得警徽……9号警下跳起来的悍跳狼被公投出局','检查首日竞选相关字幕未定位8号本人自称信息神；复盘明确9号悍跳。'),
(9,'yes','通灵师','high','[4928.700–4932.340] 9号警下跳起来的悍跳狼被公投出局','裁判复盘明确9号狼警下悍跳并首日出局；本局信息神为通灵师。'),
(10,'no',None,'medium','[4926.520–4932.340] 12号通灵师获得警徽……9号警下跳起来的悍跳狼被公投出局','检查首日竞选相关字幕未定位10号本人自称信息神；复盘明确9号悍跳。')],
'BV1Pxgy68EQC':[
(5,'no',None,'medium','[5203.790–5208.060] 9号悍跳狼获得警徽……3号预言家被抗推出局','检查首日竞选字幕未定位5号本人自称预言家或通灵师；复盘明确9号悍跳。'),
(8,'no',None,'medium','[5203.790–5208.060] 9号悍跳狼获得警徽……3号预言家被抗推出局','检查首日竞选字幕未定位8号本人自称信息神；复盘明确9号悍跳。'),
(9,'yes','预言家','high','[5203.790–5205.540] 9号悍跳狼获得警徽','裁判复盘明确9号悍跳且赢得警徽；真预言家3号首日被放逐。'),
(11,'no',None,'medium','[5203.790–5208.060] 9号悍跳狼获得警徽……3号预言家被抗推出局','检查首日竞选字幕未定位11号本人自称信息神；复盘明确9号悍跳。')],
'BV1Nsgy6cEiG':[
(2,'yes','通灵师','medium','[5541.420–5544.530] 盗宝大师选择通灵师身份验证','复盘记载狼阵营盗宝大师选择通灵师身份并报验；按狼底牌采用该身份作为信息神伪装计入。'),
(5,'no',None,'medium','[5541.420–5545.970] 盗宝大师选择通灵师身份验证……5号玩家为狼人同伴','检查首日发言及复盘未定位5号本人自称信息神；报验由盗宝大师2号执行。'),
(6,'no',None,'medium','[5547.870–5552.059] 7号猎人获得警徽……9号平民被抗推出局','检查首日竞选字幕未定位6号本人自称信息神。'),
(10,'no',None,'medium','[5547.870–5552.059] 7号猎人获得警徽……9号平民被抗推出局','检查首日竞选字幕未定位10号本人自称信息神。')],
'BV1RGgx6xEun':[
(1,'no',None,'medium','[5073.130–5077.719] 11号预言家自动当选……2号平民被抗推出局','检查首日竞选相关字幕未定位1号本人自称信息神；复盘记录真预言家11号自动当选。'),
(5,'yes','预言家','medium','[1116.145–1122.965] 我验了七号玩家是一个金水警徽流的话呢嗯留一个六号','5号发言轮报7号金水并讨论警徽流，构成预言家身份宣称；本局真预言家为11号。'),
(9,'no',None,'medium','[5073.130–5077.719] 11号预言家自动当选……2号平民被抗推出局','检查首日竞选相关字幕未定位9号本人自称信息神；复盘记录11号为真预言家。'),
(10,'no',None,'medium','[5073.130–5077.719] 11号预言家自动当选……2号平民被抗推出局','检查首日竞选相关字幕未定位10号本人自称信息神；复盘记录11号为真预言家。')],
'BV19Ggx6xEqE':[
(2,'no',None,'medium','[4053.635–4055.135] 八号悍跳狼人获得警徽','检查首日竞选相关字幕未定位2号本人自称信息神；复盘明确8号悍跳。'),
(7,'no',None,'medium','[4053.635–4055.135] 八号悍跳狼人获得警徽','检查首日竞选相关字幕未定位7号本人自称信息神；复盘明确8号悍跳。'),
(8,'yes','预言家','high','[4053.635–4055.135] 八号悍跳狼人获得警徽','裁判复盘明确8号狼人悍跳且赢得警徽；本局真预言家1号。'),
(9,'no',None,'medium','[4053.635–4055.135] 八号悍跳狼人获得警徽','检查首日竞选相关字幕未定位9号本人自称信息神；复盘明确8号悍跳。')],
'BV1RGgx6xEP9':[
(4,'no',None,'medium','[3601.780–3604.040] 通灵师验证六号玩家为狼人身份','检查首日竞选及身份神发言未定位4号本人自称；复盘指向6号红查杀。'),
(5,'yes','通灵师','medium','[3611.280–3614.785] 五号狼人通灵师查验十二号玩家为平民身份','复盘称5号狼以通灵师身份报验12号平民，按直接身份宣称计入。'),
(6,'yes','通灵师','high','[1109.455–1114.720] 因为我是通灵师虽然我被查杀到了……三也是红狼直接查杀','6号在发言中自称通灵师并报验人；物理底牌为狼人。'),
(10,'no',None,'medium','[3611.280–3614.785] 五号狼人通灵师查验十二号玩家为平民身份','检查首日和延迟竞选相关字幕未定位10号本人自称信息神。')],
'BV1iMgq6ZE5t':[
(3,'no',None,'medium','[3186.240–3191.480] 十号狼人选择自爆……狼队击杀九号预言家牛犊杀四号狼人','检查首日竞选字幕未定位3号本人自称信息神；复盘记其后续延期环节出狼。'),
(4,'no',None,'medium','[3191.480–3193.300] 四号九号双死','检查首日竞选及查验相关字幕未定位4号本人自称信息神；复盘记录夜间被毒杀。'),
(10,'no',None,'medium','[3186.240–3191.480] 十号狼人选择自爆……狼队击杀九号预言家牛犊杀四号狼人','检查首日竞选相关字幕未定位10号本人自称信息神；复盘只记其自爆。'),
(12,'no',None,'medium','[3196.320–3198.935] 十二号狼人选择自爆本游戏警徽流失','检查首日及延期竞选相关字幕未定位12号本人自称信息神；复盘记录其自爆。')]
}
bybvid={re.search(r'BV[0-9A-Za-z]{10}',p.parent.name)[0]:p for p in sorted(Path('data/games/S22').glob('*/dossier.json'))}
data['games']=[g for g in data['games'] if g['bvid'] not in rows]
for bvid,entries in rows.items():
 p=bybvid[bvid]; d=json.loads(p.read_text(encoding='utf-8')); sub=next(x['path'] for x in d['files'] if x['role'] in ('subtitle','transcript')); gd=p.parent.as_posix()
 game={'game_id':d['slug'],'bvid':bvid,'date':d['date'],'game_number':d['game_number'],'game_dir':gd,'coverage':'recap_and_claims','notes':[],'assessments':[]}
 for seat,decision,claim,conf,clip,why in entries:
  who=next(x for x in d['seats'] if x['seat']==seat); m=re.match(r'\[(\d+(?:\.\d+)?)–(\d+(?:\.\d+)?)\] (.*)',clip)
  path=sub if (bvid=='BV1RGgx6xEun' and seat==5) or (bvid=='BV1RGgx6xEP9' and seat==6) else f'{gd}/复盘原文.txt'
  kind='speech' if path==sub else 'recap'
  question=[]
  if bvid=='BV1fPKY6gEFp' and seat==7:
   decision='uncertain'; claim=None; conf='low'; question=['请复核7号首次自爆前是否已经明确自称预言家或通灵师。']
  game['assessments'].append({'seat':seat,'name':who['name'],'physical_role':who['role'],'decision':decision,'claimed_role':claim,'confidence':conf,'evidence':[{'kind':kind,'source_path':path,'start_ms':round(float(m[1])*1000),'end_ms':round(float(m[2])*1000),'text':m[3],'interpretation':why}],'calls':[],'review_questions':question})
 # add each dossier-specific record
 data['games'].append(game)
data['games'].sort(key=lambda g:g['game_dir'])
fd,tmp=tempfile.mkstemp(dir=out.parent,prefix='part_b.',suffix='.tmp')
with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
 json.dump(data,f,ensure_ascii=False,indent=2); f.write(chr(10))
os.replace(tmp,out)
print('games',len(data['games']),'decisions',{k:sum(a['decision']==k for g in data['games'] for a in g['assessments']) for k in ('yes','uncertain','no')})

