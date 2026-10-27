import json,pathlib
root=pathlib.Path('.'); f=root/'data/extractions/S22/bluff_review/part_a.json'; out=json.loads(f.read_text(encoding='utf-8-sig')); games=sorted((root/'data/games/S22').glob('*/dossier.json'),key=lambda p:str(p))
def ev(k,p,a,z,t,i):return {'kind':k,'source_path':p,'start_ms':a,'end_ms':z,'text':t,'interpretation':i}
raw={
24:{'notes':['全文明确提到7号跳通灵师，dossier显示7号机械狼；复盘身份与底牌已交叉。'],'items':{1:('uncertain',None,('speech',2281670,2282570,'我是通灵师','全文有信息神自称但转写没有speaker标签，无法归到1号。')),4:('uncertain',None,('speech',2281670,2282570,'我是通灵师','全文有信息神自称但转写没有speaker标签，无法归到4号。')),7:('yes','通灵师',('speech',2013029,2015929,'7号跳了个通灵师给他头上杀了一刀','转写明确把跳通灵师归给7号，且dossier座位7底牌为机械狼。')),11:('uncertain',None,('speech',2281670,2282570,'我是通灵师','全文有信息神自称但转写没有speaker标签，无法归到11号。'))}},
25:{'notes':['复盘确认6号预言家得警徽、验8号为狼人；其他第一人称预言家自称无法可靠映射到狼底牌。局次标记待核，保留原目录身份。'],'items':{5:('uncertain','预言家',('speech',495070,496270,'我是预言家','全文有自称但speaker未标注，不能归到5号。')),8:('uncertain','预言家',('speech',495070,496270,'我是预言家','全文有自称但speaker未标注，不能归到8号。')),10:('uncertain','预言家',('speech',495070,496270,'我是预言家','全文有自称但speaker未标注，不能归到10号。'))}},
26:{'notes':['复盘记录首夜解救、警徽流失和身份信息，未点名悍跳；全文有预言家自称但没有speaker标签。8号混血儿不是狼人底牌。'],'items':{1:('uncertain','预言家',('speech',1896220,1897380,'我是预言家牌啊','全文转写出现自称但无speaker标签，无法绑定到1号。')),3:('uncertain','预言家',('speech',1896220,1897380,'我是预言家牌啊','全文转写出现自称但无speaker标签，无法绑定到3号。')),9:('uncertain','预言家',('speech',1896220,1897380,'我是预言家牌啊','全文转写出现自称但无speaker标签，无法绑定到9号。')),12:('uncertain','预言家',('speech',1896220,1897380,'我是预言家牌啊','全文转写出现自称但无speaker标签，无法绑定到12号。'))}},
27:{'notes':['复盘明确4号悍跳女巫并被放逐；女巫不属于本任务定义的悍跳身份。其他狼座位没有获得悍跳结论。'],'items':{1:('uncertain','预言家',('speech',1517630,1518310,'我是预言家','全文存在自称，但没有speaker-座位对应，无法判断是否1号。')),4:('no',None,('recap',6486779,6489860,'4号悍跳女巫的狼人被公投出局','复盘明确4号跳的是女巫；按定义不算预言家/通灵师悍跳，首日全文也未发现其自称这两种身份。')),5:('uncertain','预言家',('speech',1517630,1518310,'我是预言家','全文存在自称，但没有speaker-座位对应，无法判断是否5号。')),6:('uncertain','预言家',('speech',1517630,1518310,'我是预言家','全文存在自称，但没有speaker-座位对应，无法判断是否6号。'))}},
28:{'notes':['复盘确认2号通灵师及首日进程；转写有多个通灵师自称，speaker未标注。'],'items':{3:('uncertain','通灵师',('speech',410490,413510,'初八我是通灵师啊','全文转写出现通灵师自称，但未识别speaker，无法归到3号。')),8:('uncertain','通灵师',('speech',410490,413510,'初八我是通灵师啊','全文转写出现通灵师自称，但未识别speaker；机械狼身份本身不证明跳身份。')),9:('uncertain','通灵师',('speech',410490,413510,'初八我是通灵师啊','全文转写出现通灵师自称，但未识别speaker，无法归到9号。')),12:('uncertain','通灵师',('speech',410490,413510,'初八我是通灵师啊','全文转写出现通灵师自称，但未识别speaker，无法归到12号。'))}},
29:{'notes':['复盘只明确11号狼人获得警徽；依规则警徽本身不能证明跳了信息神。全文有第一人称预言家自称但座位归属未确认。'],'items':{5:('uncertain','预言家',('speech',1602470,1603990,'我是一张预言家牌','自称片段没有speaker标签，无法归到5号。')),8:('uncertain','预言家',('speech',1602470,1603990,'我是一张预言家牌','自称片段没有speaker标签，无法归到8号。')),10:('uncertain','预言家',('speech',1602470,1603990,'我是一张预言家牌','自称片段没有speaker标签，无法归到10号。')),11:('uncertain','预言家',('speech',1602470,1603990,'我是一张预言家牌','11号拿警徽不能单独证明悍跳；转写自称无法绑定座位，待复核。'))}},
30:{'notes':['复盘明确8号悍跳狼人自爆；其他狼底牌没有同等清楚的座位归属证据。'],'items':{6:('uncertain','预言家',('speech',1006690,1008130,'我是一张预言家','转写自称没有speaker标签，不能归给6号。')),8:('yes','预言家',('recap',3190460,3192640,'第一天白天8号悍跳狼人自爆','复盘明确8号悍跳狼人并自爆，dossier底牌为狼人。')),9:('uncertain','预言家',('speech',1006690,1008130,'我是一张预言家','转写自称没有speaker标签，不能归给9号。')),11:('uncertain','预言家',('speech',1006690,1008130,'我是一张预言家','转写自称没有speaker标签，不能归给11号。'))}},
31:{'notes':['复盘明确3号悍跳并获得警徽；其他狼座位有身份讨论但未确认起跳。'],'items':{2:('uncertain','通灵师',('speech',1401380,1402840,'我是预言家牌','全文自称转写无speaker标签，无法绑定到2号。')),3:('yes','通灵师',('recap',4309690,4312570,'3号悍3号狼人获得警徽','复盘明确点名3号悍跳并获警徽，dossier底牌为狼人；本局信息神为通灵师。')),9:('uncertain','通灵师',('speech',1401380,1402840,'我是预言家牌','全文自称转写无speaker标签，无法绑定到9号。')),11:('uncertain','通灵师',('speech',1401380,1402840,'我是预言家牌','全文自称转写无speaker标签，无法绑定到11号。'))}},
32:{'notes':['复盘未明示悍跳者；全文有第一人称预言家自称但speaker未标注。4号混血儿非狼人底牌，单独核查。'],'items':{1:('uncertain','预言家',('speech',1118220,1119040,'我是预言家','全文中有自称但无speaker标签，无法归到1号。')),2:('uncertain','预言家',('speech',1118220,1119040,'我是预言家','全文中有自称但无speaker标签，无法归到2号。')),3:('uncertain','预言家',('speech',1118220,1119040,'我是预言家','全文中有自称但无speaker标签，无法归到3号。')),7:('uncertain','预言家',('speech',1118220,1119040,'我是预言家','全文中有自称但无speaker标签，无法归到7号。'))}},
33:{'notes':['复盘确认8号预言家获得警徽；全文发言称6号为悍跳狼，dossier座位6为狼人。'],'items':{1:('uncertain',None,('speech',1668750,1669510,'6号悍跳狼','该文本明确指向6号；全文其余自称归属不明，未见1号明确自称。')),5:('uncertain',None,('speech',1668750,1669510,'6号悍跳狼','该文本明确指向6号；全文其余自称归属不明，未见5号明确自称。')),6:('yes','预言家',('speech',1668750,1669510,'6号悍跳狼','发言明确将6号称为悍跳狼，dossier底牌为狼人；本局信息神为预言家。')),9:('uncertain',None,('speech',1668750,1669510,'6号悍跳狼','该文本明确指向6号；全文其余自称归属不明，未见9号明确自称。'))}}
}
for ix,spec in raw.items():
 p=games[ix-1];d=json.loads(p.read_text(encoding='utf-8-sig'));gd=p.parent.as_posix();b=d['slug'].split('-')[1]
 rec=f'{gd}/复盘原文.txt'; sub=next((x['path'] for x in d.get('files',[]) if x.get('role')=='subtitle'),None)
 full=next((x.as_posix() for x in (root/'data/seasons/S22').glob(f'**/*{b}*.本地全文转写_funasr.json')),None); speech=full or sub
 arr=[]
 for s in d['seats']:
  if s['faction']!='werewolf' or s['role']=='混血儿' or s['seat'] not in spec['items']:continue
  dec,role,(kind,a,z,t,interp)=spec['items'][s['seat']];src=rec if kind=='recap' else speech
  q=[] if dec=='yes' else [f'请复核该证据是否属于{s["seat"]}号的场上发言。']
  aobj={'seat':s['seat'],'name':s['name'],'physical_role':s['role'],'decision':dec,'claimed_role':role,'confidence':'high' if dec=='yes' else ('medium' if dec=='no' else 'low'),'evidence':[ev(kind,src,a,z,t,interp)],'calls':[],'review_questions':q}
  if dec=='no':aobj['decision_note']='复盘明确跳女巫，非本任务的预言家/通灵师；全文未找到其自称这两种信息神。'
  arr.append(aobj)
 out['games'].append({'game_id':d['slug'],'bvid':b,'date':d['date'],'game_number':d['game_number'],'game_dir':gd,'coverage':'recap_and_claims','notes':spec['notes'],'assessments':arr})
f.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('appended',len(raw),'total games',len(out['games']),'assessments',sum(len(g['assessments']) for g in out['games']))
