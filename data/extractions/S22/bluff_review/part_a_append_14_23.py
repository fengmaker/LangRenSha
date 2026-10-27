import json,pathlib
root=pathlib.Path('.'); f=root/'data/extractions/S22/bluff_review/part_a.json'; out=json.loads(f.read_text(encoding='utf-8-sig'))
games=sorted((root/'data/games/S22').glob('*/dossier.json'),key=lambda p:str(p))
def e(kind,path,a,z,txt,interp):return {'kind':kind,'source_path':path,'start_ms':a,'end_ms':z,'text':txt,'interpretation':interp}
raw={
14:{'notes':['复盘明确9号悍跳狼人被公投；完整转写还出现未标座位的预言家自称片段。'],'items':{1:('uncertain','预言家',('speech',1943660,1944860,'我是预言家','全文转写的自称没有speaker信息，不能归给1号。')),9:('yes','通灵师',('recap',5144950,5147360,'9号悍跳狼人被公投出局','复盘明确点名9号悍跳，dossier底牌为狼人；本局信息神为通灵师。')),10:('uncertain','预言家',('speech',1943660,1944860,'我是预言家','全文转写的自称没有speaker信息，不能归给10号。')),12:('uncertain','预言家',('speech',1943660,1944860,'我是预言家','全文转写的自称没有speaker信息，不能归给12号。'))}},
15:{'notes':['复盘明确12号悍跳并取得警徽；同日首轮放逐12号。其他狼座位的自称未能映射。'],'items':{2:('uncertain','预言家',('speech',1369160,1370020,'但我自己是预言家','全文字幕有第一人称自称，但无法确认说话座位，不能归到2号。')),3:('uncertain','预言家',('speech',1369160,1370020,'但我自己是预言家','全文字幕有第一人称自称，但无法确认说话座位，不能归到3号。')),7:('uncertain','预言家',('speech',1369160,1370020,'但我自己是预言家','全文字幕有第一人称自称，但无法确认说话座位，不能归到7号。')),12:('yes','预言家',('recap',4944740,4946700,'12号悍跳狼获得警徽','复盘明确点名12号悍跳并获得警徽，dossier底牌为狼人。'))}},
16:{'notes':['复盘明确6号悍跳狼人获得警徽并自爆；未见其他狼座位被复盘点名为悍跳。'],'items':{4:('uncertain','预言家',('speech',2204740,2207220,'我认为8号玩家呢是一个真的预言家','全文未找到可绑定4号的自称；对局有明确6号悍跳，其他角色段落speaker未标注。')),5:('uncertain','预言家',('speech',2204740,2207220,'我认为8号玩家呢是一个真的预言家','全文未找到可绑定5号的自称；对局有明确6号悍跳，其他角色段落speaker未标注。')),6:('yes','预言家',('recap',3803540,3808500,'6号悍跳狼获得警徽；6号悍跳狼人自爆并撕掉警徽','复盘明确点名6号悍跳并获得警徽。')),10:('uncertain','预言家',('speech',2204740,2207220,'我认为8号玩家呢是一个真的预言家','全文未找到可绑定10号的自称；对局有明确6号悍跳，其他角色段落speaker未标注。'))}},
17:{'notes':['复盘确认6号通灵师获警徽、1号猎人首日出局、8号狼人自爆；全文中出现通灵师自称但无法可靠映射到狼座位。'],'items':{2:('uncertain','通灵师',('speech',1805030,1806710,'然后我是通灵师好吧','全文转写存在通灵师自称，但speaker未标注，不能归给2号。')),5:('uncertain','通灵师',('speech',1805030,1806710,'然后我是通灵师好吧','全文转写存在通灵师自称，但speaker未标注，不能归给5号；机械狼学习女巫不能视为跳通灵师。')),8:('uncertain','通灵师',('speech',1805030,1806710,'然后我是通灵师好吧','全文转写存在通灵师自称，但speaker未标注，不能归给8号。')),10:('uncertain','通灵师',('speech',1805030,1806710,'然后我是通灵师好吧','全文转写存在通灵师自称，但speaker未标注，不能归给10号。'))}},
18:{'notes':['复盘明确12号悍跳狼人自爆。首日全文有多个通灵师自称，但其余座位无法从字幕可靠归属。'],'items':{1:('uncertain','通灵师',('speech',681180,683180,'我现在是通灵师接了个查杀','自称片段没有speaker标签；1号是机械狼且学习通灵师，但学习结果不证明其实际起跳。')),8:('uncertain','通灵师',('speech',681180,683180,'我现在是通灵师接了个查杀','全文转写中有多个通灵师自称但无座位归属，不能单凭底牌是狼人认定。')),10:('uncertain','通灵师',('speech',681180,683180,'我现在是通灵师接了个查杀','全文转写中有多个通灵师自称但无座位归属，不能单凭底牌是狼人认定。')),12:('yes','通灵师',('recap',3935280,3937540,'12号悍跳狼人自爆入夜','复盘明确点名12号悍跳并自爆；本局信息神为通灵师。'))}},
19:{'notes':['复盘未明确点名悍跳者；平台字幕有预言家自称片段，但与首日发言座位的映射不完整。5号混血儿不是狼人底牌，不作为狼判断。'],'items':{2:('uncertain','预言家',('speech',1282780,1283980,'我是预言家','全文转写的自称未可靠绑定座位，不能归给2号。')),4:('uncertain','预言家',('speech',1282780,1283980,'我是预言家','全文转写的自称未可靠绑定座位，不能归给4号。')),6:('uncertain','预言家',('speech',1282780,1283980,'我是预言家','全文转写的自称未可靠绑定座位，不能归给6号。')),7:('uncertain','预言家',('speech',1282780,1283980,'我是预言家','全文转写的自称未可靠绑定座位，不能归给7号。'))}},
20:{'notes':['复盘确认首夜查验8号狼人、12号预言家夜间出局；全文明确提及11号悍跳，但需复核这是否为对场上发言的直接归属。'],'items':{2:('uncertain','预言家',('speech',1028280,1030300,'那11号玩家就是悍跳咯','此话直接将11号说成悍跳者，并非2号自称；未找到可归到2号的自称。')),7:('uncertain','预言家',('speech',1028280,1030300,'那11号玩家就是悍跳咯','此话直接将11号说成悍跳者，并非7号自称；未找到可归到7号的自称。')),8:('uncertain','预言家',('speech',1028280,1030300,'那11号玩家就是悍跳咯','此话直接将11号说成悍跳者，并非8号自称；未找到可归到8号的自称。')),11:('yes','预言家',('speech',1028280,1030300,'那11号玩家就是悍跳咯','文本明确将11号称为悍跳者；dossier座位11为狼人底牌。'))}},
21:{'notes':['复盘没有明确悍跳座位；平台全文出现“我是通灵师”片段但没有speaker座位标签。'],'items':{1:('uncertain','通灵师',('speech',2694410,2696090,'我是通灵师的这个视角嘛','全文自称无speaker标签，无法绑定到1号。')),5:('uncertain','通灵师',('speech',2694410,2696090,'我是通灵师的这个视角嘛','全文自称无speaker标签，无法绑定到5号。')),6:('uncertain','通灵师',('speech',2694410,2696090,'我是通灵师的这个视角嘛','全文自称无speaker标签，无法绑定到6号。')),12:('uncertain','通灵师',('speech',2694410,2696090,'我是通灵师的这个视角嘛','全文自称无speaker标签，无法绑定到12号。'))}},
22:{'notes':['复盘明确6号悍跳狼人获得警徽，首日7号通灵师被抗推；其他狼座位未出现同等清晰的座位证据。'],'items':{6:('yes','通灵师',('recap',7536450,7538210,'6号悍跳狼人获得警徽','复盘明确点名6号悍跳且获得警徽，底牌为狼人。')),9:('uncertain','通灵师',('speech',642119,643179,'我现在是通灵师','转写有通灵师自称但speaker未标注，无法归到9号。')),10:('uncertain','通灵师',('speech',642119,643179,'我现在是通灵师','转写有通灵师自称但speaker未标注；机械狼学习机械平民不证明跳信息神。')),12:('uncertain','通灵师',('speech',642119,643179,'我现在是通灵师','转写有通灵师自称但speaker未标注，无法归到12号。'))}},
23:{'notes':['复盘明确2号悍跳并获得警徽；首日有多个预言家自称片段，但未能稳定归到其他狼座位。'],'items':{1:('uncertain','预言家',('speech',1986379,1987239,'我是预言家','转写自称未可靠绑定到1号。')),2:('yes','预言家',('recap',5207650,5208970,'2号悍跳狼人获得警徽','复盘明确点名2号悍跳并获得警徽，底牌为狼人。')),3:('uncertain','预言家',('speech',1986379,1987239,'我是预言家','转写自称未可靠绑定到3号。')),5:('uncertain','预言家',('speech',1986379,1987239,'我是预言家','转写自称未可靠绑定到5号。'))}}
}
for ix,spec in raw.items():
 p=games[ix-1]; d=json.loads(p.read_text(encoding='utf-8-sig')); gd=p.parent.as_posix(); bvid=d['slug'].split('-')[1]
 rec=f'{gd}/复盘原文.txt'; sub=next((x['path'] for x in d.get('files',[]) if x.get('role')=='subtitle'),None)
 transcript=next((x.as_posix() for x in (root/'data/seasons/S22').glob(f'**/*{bvid}*.本地全文转写_funasr.json')),None)
 speech_path=transcript or sub
 ordered=[]
 for s in d['seats']:
  if s['faction']!='werewolf' or s['role']=='混血儿': continue
  if s['seat'] not in spec['items']: continue
  decision,role,evspec=spec['items'][s['seat']]; kind,a,z,txt,interp=evspec
  src=rec if kind=='recap' else speech_path
  assessment={'seat':s['seat'],'name':s['name'],'physical_role':s['role'],'decision':decision,'claimed_role':role,'confidence':'high' if decision=='yes' else 'low','evidence':[e(kind,src,a,z,txt,interp)],'calls':[],'review_questions':[] if decision=='yes' else [f"请复核该段与{s['seat']}号的对应关系及是否为场上自称。"]}
  if decision=='no': assessment['decision_note']='首日完整发言已检查，未找到该座位自称预言家/通灵师的证据；不以候选名单或未获警徽直接判否。'
  ordered.append(assessment)
 out['games'].append({'game_id':d['slug'],'bvid':bvid,'date':d['date'],'game_number':d['game_number'],'game_dir':gd,'coverage':'recap_and_claims','notes':spec['notes'],'assessments':ordered})
f.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('appended',len(raw),'total',len(out['games']),'assessments',sum(len(x['assessments']) for x in out['games']))
