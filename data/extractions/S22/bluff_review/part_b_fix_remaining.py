import json,os,tempfile
from pathlib import Path
p=Path('data/extractions/S22/bluff_review/part_b.json'); d=json.loads(p.read_text(encoding='utf-8'))
updates={
'BV1YmTc6yEFd':{
6:{'decision':'uncertain','claimed_role':None,'confidence':'low','start_ms':2742130,'end_ms':2748780,'text':'我不跳一会他跳我的身份……我就得跳……因为我是猎人','interpretation':'该处原文说“我就得跳，因为我是猎人”，并非“6号/7号说8号像预言家”；这段语音未能可靠归属到具体狼人座位，故不作否定或肯定。','review_questions':['请复核该猎人身份发言的实际座位；目前不能由此确认6号是否公开跳过预言家或通灵师。']},
7:{'decision':'uncertain','claimed_role':None,'confidence':'low','start_ms':2742130,'end_ms':2748780,'text':'我不跳一会他跳我的身份……我就得跳……因为我是猎人','interpretation':'该处原文说“我就得跳，因为我是猎人”，并非“6号/7号说8号像预言家”；这段语音未能可靠归属到具体狼人座位，故不作否定或肯定。','review_questions':['请复核该猎人身份发言的实际座位；目前不能由此确认7号是否公开跳过预言家或通灵师。']}},
'BV1gvTi66EFF':{9:{'start_ms':3613760,'end_ms':3616060,'text':'9号狼人选择自爆……本九游戏警徽流失'}},
'BV1gvTi66E7y':{
4:{'start_ms':4202990,'end_ms':4207470,'text':'10号狼人阵营……6号九号……12号鬼术师'},
6:{'start_ms':1512620,'end_ms':1515810,'text':'这把应该是没有什么发挥的空间了啊','interpretation':'核查6号相关首日发言及复盘文本，未发现其本人自称预言家或通灵师；仅找到对无发挥空间的讨论。'}},
'BV1BjMh63EDf':{
5:{'start_ms':4384640,'end_ms':4389540,'text':'12号悍跳狼后的警徽……12号悍跳狼被公投出局'},
9:{'start_ms':4394520,'end_ms':4399440,'text':'女巫毒杀9号机械双刀狼人……9号角为狼人身份'},
12:{'start_ms':4384640,'end_ms':4386420,'text':'12号悍跳狼后的警徽'}},
'BV11uMG6PEkr':{
2:{'start_ms':6309335,'end_ms':6313895,'text':'六号混血而获得警徽……八号，狼人自爆'},
7:{'start_ms':6309335,'end_ms':6313895,'text':'六号混血而获得警徽……八号，狼人自爆'},
8:{'start_ms':6307075,'end_ms':6313895,'text':'平安夜愿将验证八号两位狼人身份……八号，狼人自爆'},
12:{'start_ms':6307075,'end_ms':6313895,'text':'平安夜愿将验证八号两位狼人身份……八号，狼人自爆'}},
'BV1suMG6PEYP':{4:{'start_ms':6315785,'end_ms':6319725,'text':'五号女巫获得警徽……女巫被抗退出'}},
'BV1hZMp63Esx':{1:{'start_ms':7059270,'end_ms':7061170,'text':'4号狼人阵营5号九号'}},
'BV13ZMp63EEB':{6:{'start_ms':3833665,'end_ms':3838970,'text':'叶娟通灵师验证六号玩家为狼人身份……狼人选择自爆'}},
'BV1GxNH6YESw':{
5:{'start_ms':6418980,'end_ms':6427190,'text':'6号悍跳狼人获得警徽……地天白天一号预言家被抗推出局……毒杀7号狼人'},
6:{'start_ms':6418980,'end_ms':6420860,'text':'6号悍跳狼人获得警徽'}},
'BV1GxNH6YEht':{
2:{'start_ms':2662680,'end_ms':2676610,'text':'8号狼人选择自爆入夜舞者的舞池……5号白神被五出局'},
8:{'start_ms':628700,'end_ms':643020,'text':'那win的十是金水啊……我验的十是金水','interpretation':'8号发言轮中的第一人称报验；其称10号为金水并说自己验了10号，本局真预言家为9号。'},
10:{'start_ms':2650570,'end_ms':2651650,'text':'10号平民阵营'}},
'BV1VxNH6YETC':{11:{'start_ms':2896540,'end_ms':2899340,'text':'空过狼队击杀4号女巫女巫毒杀11号狼人'}},
'BV1PEN863EXG':{8:{'start_ms':4681490,'end_ms':4684580,'text':'入夜圣梦人梦游8号狼人'}},
'BV1WEN86gE1i':{6:{'start_ms':4044950,'end_ms':4049120,'text':'当夜通灵师验证6号玩家机械双刀……狼人为狼人身份'}},
'BV1BPNB6QE1V':{
1:{'start_ms':4962585,'end_ms':4966345,'text':'九号狼人高票七号定绪王子出局'},
10:{'start_ms':4956665,'end_ms':4961805,'text':'上警环节八号预言家获得警徽。'}},
'BV1Nsgy6cEiG':{2:{'decision':'yes','claimed_role':'通灵师','confidence':'high','start_ms':1135760,'end_ms':1138560,'text':'但其实本局游戏我自己底牌是张通灵师牌','interpretation':'2号发言轮先报验9号，继而第一人称称“我自己底牌是张通灵师牌”，是公开自称；其真实底牌为狼人阵营盗宝大师。'}},
'BV1iMgq6ZEWn':{2:{'decision':'yes','claimed_role':'通灵师','confidence':'medium','start_ms':872210,'end_ms':876720,'text':'二号玩家给八号玩家发金水……然后他说八号家肯定不会反他水嘛','interpretation':'5号等人的公开发言以事实句复述“二号玩家给八号玩家发金水”，后面解释2号为什么这样做；该段没有“如果/假设”等条件词，视为2号公开报金水的证据，结合狼底牌与真通灵师5号推断为身份宣称。'}}
}
byid={g['bvid']:g for g in d['games']}
for bvid, entries in updates.items():
 g=byid[bvid]
 for seat, vals in entries.items():
  a=next(a for a in g['assessments'] if a['seat']==seat); e=a['evidence'][0]
  for k,v in vals.items():
   if k in ('decision','claimed_role','confidence','review_questions'):
    a[k]=v
   else: e[k]=v
  if 'review_questions' in vals: a['review_questions']=vals['review_questions']
# update source path for the new direct public claim in game 90
for bvid,seat in [('BV1Nsgy6cEiG',2)]:
 g=byid[bvid]; dossier=json.loads((Path(g['game_dir'])/'dossier.json').read_text(encoding='utf-8')); sub=next(x['path'] for x in dossier['files'] if x['role']=='subtitle'); e=next(a for a in g['assessments'] if a['seat']==seat)['evidence'][0]; e['source_path']=sub; e['kind']='speech'
# update game 97 evidence attribution is a commentary/source report
for bvid,seat in [('BV1iMgq6ZEWn',2)]:
 g=byid[bvid]; a=next(a for a in g['assessments'] if a['seat']==seat); a['evidence'][0]['kind']='commentary'
fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='part_b.',suffix='.tmp')
with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f: json.dump(d,f,ensure_ascii=False,indent=2); f.write(chr(10))
os.replace(tmp,p)
print('patched',sum(len(x) for x in updates.values()),'assessments; atomic replace complete')
