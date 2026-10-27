import json,pathlib
root=pathlib.Path('.')
outpath=root/'data/extractions/S22/bluff_review/part_a.json'; out=json.loads(outpath.read_text(encoding='utf-8-sig'))
games=sorted((root/'data/games/S22').glob('*/dossier.json'),key=lambda p:str(p))
def ev(k,src,a,z,txt,interp): return {'kind':k,'source_path':src,'start_ms':a,'end_ms':z,'text':txt,'interpretation':interp}
manual={
6:{'notes':['复盘确认11号首日出局，但全文存在多处“我是通灵师”自称；FunASR没有说话者标签，不能安全映射到座位。'],'assessments':{1:('uncertain',None,'low',('speech',473730,474910,'我通灵师熬夜了','全文转写有信息神自称线索，但speaker未标注，无法绑定1号。'),['请复核是否1号说出该片段。']),9:('uncertain',None,'low',('speech',473730,474910,'我通灵师熬夜了','全文转写有信息神自称线索，但speaker未标注，无法绑定9号。'),['请复核是否9号说出该片段。']),10:('uncertain','通灵师','low',('speech',549550,550430,'我底牌是一个通灵师','10号底牌是机械狼并学习通灵师，但该自称片段的speaker未标注；学习结果本身不证明悍跳。'),['请复核此自称是否由10号发出。']),11:('uncertain',None,'low',('speech',473730,474910,'我通灵师熬夜了','全文转写有信息神自称线索，但speaker未标注，无法绑定11号。'),['请复核是否11号说出该片段。'])}},
7:{'notes':['复盘明确7号悍跳并获得警徽；其他狼座位未能从无说话者标签的全文转写中确认自称。9号为混血儿，非狼人底牌，未列入assessment。'],'assessments':{5:('uncertain','预言家','low',('speech',1243515,1245135,'我呢是预言家啊','全文转写出现信息神自称，但speaker未标注，不能归给5号或其他具体座位。'),['请复核该自称片段的座位归属。']),7:('yes','预言家','high',('recap',4820730,4821890,'七号悍跳狼人获的警徽','复盘明确座位7悍跳，真实底牌为狼人，并获得警徽。'),[]),8:('uncertain','预言家','low',('speech',1243515,1245135,'我呢是预言家啊','全文转写出现信息神自称，但speaker未标注，不能归给8号或其他具体座位。'),['请复核该自称片段的座位归属。']),11:('uncertain','预言家','low',('speech',1243515,1245135,'我呢是预言家啊','全文转写出现信息神自称，但speaker未标注，不能归给11号或其他具体座位。'),['请复核该自称片段的座位归属。'])}},
8:{'notes':['复盘确认10号通灵师获得警徽、第一天放逐1号狼人；全文转写有多处通灵师自称，但speaker未标注。'],'assessments':{1:('uncertain','通灵师','low',('speech',844735,848745,'有一个第二啊我是通灵师','全文转写出现通灵师自称，但speaker未标注；不能仅凭1号是狼人底牌映射。'),['请复核该自称是否来自1号。']),2:('uncertain','通灵师','low',('speech',844735,848745,'有一个第二啊我是通灵师','全文转写出现通灵师自称，但speaker未标注；不能仅凭盗宝大师身份推定。'),['请复核该自称是否来自2号。']),6:('uncertain','通灵师','low',('speech',844735,848745,'有一个第二啊我是通灵师','全文转写出现通灵师自称，但speaker未标注；不能仅凭6号狼人底牌映射。'),['请复核该自称是否来自6号。']),9:('uncertain','通灵师','low',('speech',844735,848745,'有一个第二啊我是通灵师','全文转写出现通灵师自称，但speaker未标注；不能仅凭9号狼人底牌映射。'),['请复核该自称是否来自9号。'])}},
9:{'notes':['复盘确认10号预言家获得警徽；全文转写有多个第一人称预言家自称和“本局一定要跳预言家”，说话者未标注，不能按候选名单/警徽结果归到具体狼座位。7号混血儿为非狼人底牌，单独核查。'],'assessments':{2:('uncertain','预言家','low',('speech',1413370,1415570,'就决定我本局一定要跳预言家','全文转写为无speaker标签，无法判断是哪一座位的策略陈述或自称。'),['请复核这段是否属于2号且是否为场上自称。']),5:('uncertain','预言家','low',('speech',1413370,1415570,'就决定我本局一定要跳预言家','全文转写为无speaker标签，无法判断是哪一座位的策略陈述或自称。'),['请复核这段是否属于5号且是否为场上自称。']),6:('uncertain','预言家','low',('speech',1413370,1415570,'就决定我本局一定要跳预言家','全文转写为无speaker标签，无法判断是哪一座位的策略陈述或自称。'),['请复核这段是否属于6号且是否为场上自称。']),12:('uncertain','预言家','low',('speech',1413370,1415570,'就决定我本局一定要跳预言家','全文转写为无speaker标签，无法判断是哪一座位的策略陈述或自称。'),['请复核这段是否属于12号且是否为场上自称。'])}},
10:{'notes':['复盘确认2号预言家获得警徽并验证12号平民；FunASR中有多个预言家自称，但没有可靠speaker-座位映射。'],'assessments':{3:('uncertain','预言家','low',('speech',328920,329585,'我是预言家','全文转写出现自称，speaker未标注，不能可靠归给3号。'),['请复核该自称归属。']),4:('uncertain','预言家','low',('speech',328920,329585,'我是预言家','全文转写出现自称，speaker未标注，不能可靠归给4号。'),['请复核该自称归属。']),5:('uncertain','预言家','low',('speech',328920,329585,'我是预言家','全文转写出现自称，speaker未标注，不能可靠归给5号。'),['请复核该自称归属。']),8:('uncertain','预言家','low',('speech',328920,329585,'我是预言家','全文转写出现自称，speaker未标注，不能可靠归给8号。'),['请复核该自称归属。'])}},
11:{'notes':['复盘明确12号悍跳；对其他狼人底牌检查首日全文，未出现同样清晰的座位归属证据。'],'assessments':{3:('uncertain',None,'low',('recap',3606349,3607549,'12号悍跳','目前唯一清楚点名的悍跳是12号；全文的说话者没有座位标签，仍需复核3号是否有单独起跳。'),['请复核3号首日发言是否也跳信息神。']),9:('uncertain',None,'low',('recap',3606349,3607549,'12号悍跳','目前唯一清楚点名的悍跳是12号；全文的说话者没有座位标签，仍需复核9号是否有单独起跳。'),['请复核9号首日发言是否也跳信息神。']),10:('uncertain',None,'low',('recap',3606349,3607549,'12号悍跳','目前唯一清楚点名的悍跳是12号；全文的说话者没有座位标签，仍需复核10号是否有单独起跳。'),['请复核10号首日发言是否也跳信息神。']),12:('yes',None,'high',('recap',3606349,3607549,'12号悍跳','复盘明确点名12号悍跳；dossier底牌为狼人。'),[]) }},
12:{'notes':['复盘没有明确点名悍跳座位；转写中多处自称预言家，speaker未标注，不能单凭座位名单判定。5号混血儿为非狼人底牌，单独核查。'],'assessments':{1:('uncertain','预言家','low',('speech',1330070,1331590,'我是预言家','全文转写出现多个信息神自称，speaker未标注，无法映射到1号。'),['请复核这些自称是否属于1号场上发言。']),2:('uncertain','预言家','low',('speech',1330070,1331590,'我是预言家','全文转写出现多个信息神自称，speaker未标注，无法映射到2号。'),['请复核这些自称是否属于2号场上发言。']),6:('uncertain','预言家','low',('speech',1330070,1331590,'我是预言家','全文转写出现多个信息神自称，speaker未标注，无法映射到6号。'),['请复核这些自称是否属于6号场上发言。']),12:('uncertain','预言家','low',('speech',1330070,1331590,'我是预言家','全文转写出现多个信息神自称，speaker未标注，无法映射到12号。'),['请复核这些自称是否属于12号场上发言。'])}},
13:{'notes':['复盘明确7号悍跳并取得警徽；首日第一天10号平民被抗推出。转写其余候选自称均无可靠座位对应。'],'assessments':{2:('uncertain','通灵师','low',('speech',1440090,1441230,'我是不是通灵师','全文转写存在通灵师相关第一人称语句，但speaker未标注；不能映射到2号。'),['请复核该段是否属于2号场上自称。']),3:('uncertain','通灵师','low',('speech',1440090,1441230,'我是不是通灵师','全文转写存在通灵师相关第一人称语句，但speaker未标注；不能映射到3号。'),['请复核该段是否属于3号场上自称。']),7:('yes','通灵师','high',('recap',4565720,4567500,'7号悍跳狼王获得警徽','复盘明确点名7号悍跳，且dossier座位7底牌为狼王；警徽竞选板型的唯一信息神为通灵师。'),[]),8:('uncertain','通灵师','low',('speech',1440090,1441230,'我是不是通灵师','全文转写存在通灵师相关第一人称语句，但speaker未标注；不能映射到8号。'),['请复核该段是否属于8号场上自称。'])}}
}
for ix, spec in manual.items():
 p=games[ix-1]; d=json.loads(p.read_text(encoding='utf-8-sig')); gd=p.parent.as_posix(); bvid=d['slug'].split('-')[1]
 rp=f'{gd}/复盘原文.txt'
 tp=next((x.as_posix() for x in (root/'data/seasons/S22').glob(f'**/*{bvid}*.本地全文转写_funasr.json')),None)
 sub=next((f['path'] for f in d.get('files',[]) if f.get('role')=='subtitle'),None)
 for seat,(decision,role,conf,evspec,questions) in spec['assessments'].items():
  kind,a,z,txt,interp=evspec
  src=rp if kind=='recap' else (tp or sub)
  evs=[ev(kind,src,a,z,txt,interp)]
  # use recap confirmation as a second source for yes assessments where applicable
  if decision=='yes' and kind=='recap': evs.append(ev('recap',src,a,z,txt,interp))
  s=next(x for x in d['seats'] if x['seat']==seat)
  assessment={'seat':seat,'name':s['name'],'physical_role':s['role'],'decision':decision,'claimed_role':role,'confidence':conf,'evidence':evs,'calls':[],'review_questions':questions}
  if decision=='no': assessment['decision_note']='首日完整发言已检查，未找到该座位自称预言家/通灵师的证据；不以候选名单或未获警徽直接判否。'
  spec['assessments'][seat]=assessment
 # preserve seat order and normalize assessment list
 ordered=[]
 for s in d['seats']:
  if s['faction']=='werewolf' and s['role']!='混血儿' and s['seat'] in spec['assessments']:
   ordered.append(spec['assessments'][s['seat']])
 entry={'game_id':d['slug'],'bvid':bvid,'date':d['date'],'game_number':d['game_number'],'game_dir':gd,'coverage':'recap_and_claims','notes':spec['notes'],'assessments':ordered}
 out['games'].append(entry)
outpath.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('appended',len(manual),'total games',len(out['games']),'total assessments',sum(len(g['assessments']) for g in out['games']))
