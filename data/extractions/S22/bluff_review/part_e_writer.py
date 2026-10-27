import json, os
from pathlib import Path
from collections import Counter
import sys
ROOT=Path('.')
OUT=ROOT/'data/extractions/S22/bluff_review/part_e.json'
IDX=sorted((ROOT/'data/games/S22').glob('*/dossier.json'))
# Records reviewed by the agent; direct evidence rows must remain verbatim.
SPECS={
'BV1KMur6HE7b':{
 2:('yes','预言家','high',[('speech',524640,531020,'那我就一号4号验吧…验的9号是金水嗯','2号在警上候选发言中直接报验，并由后续评论明确点名其悍跳。'),('commentary',635260,637000,'所以我觉得二二悍跳','评论明确将二号称为悍跳；其底牌为狼人。')],[]),
 1:('no',None,'medium',[],[]),7:('no',None,'medium',[],[]),9:('no',None,'medium',[],[]),
},
'BV12Mur6nEns':{
 5:('no',None,'medium',[],[]),
 8:('uncertain','通灵师','low',[('commentary',931370,932690,'你们说六八本来想悍跳','评论只称六、八原本“想”悍跳，未能确认八号是否实际以通灵师/预言家身份起跳。')],['评论提到八号“本来想悍跳”，但该措辞可能只是意图；待复核是否有正式身份自称。']),
 11:('yes','通灵师','medium',[('commentary',1092640,1095895,'你看那个十一号他悍跳','评论明确称十一号悍跳；该局信息神为通灵师，十一号底牌为狼人。')],[]),
 12:('no',None,'medium',[],[]),
},
'BV1JNgj6gEty':{5:('no',None,'medium',[],[]),8:('no',None,'medium',[],[]),9:('no',None,'medium',[],[]),10:('no',None,'medium',[],[])},
'BV1JNgj6gEaf':{
 4:('yes','预言家','medium',[('speech',451860,455060,'4号玩家请发言…一金水','四号在警上发言开头报出一号金水，按该轮竞选语境视为以预言家身份报验；复盘也确认四号是狼人。')],[]),
 5:('no',None,'medium',[],[]),
 7:('yes','预言家','high',[('recap',4562440,4565150,'第二天白天7号悍跳狼人自爆入夜','复盘直接点名七号悍跳狼，且游戏板型的信息神为预言家。')],[]),
 8:('no',None,'medium',[],[]),
},
'BV1JNgj6gEta':{
 2:('no',None,'medium',[],[]),4:('no',None,'medium',[],[]),6:('no',None,'medium',[],[]),
 7:('yes','通灵师','high',[('recap',3813075,3814410,'七号悍跳狼人自爆','复盘明确将七号定为悍跳狼；该局信息神为通灵师。')],[]),
},
'BV1GXgW6HEmA':{
 4:('no',None,'medium',[],[]),5:('no',None,'medium',[],[]),
 6:('yes','预言家','high',[('speech',1375050,1402500,'我觉得2号像是金水哦…因为预言家我比较晚睁眼…我就选择经验了…2号玩家','六号的正式发言以预言家视角说明查验心路并报出二号金水；六号底牌为狼人。')],[]),
 10:('no',None,'medium',[],[]),
},
'BV1aXgW6nE6E':{5:('no',None,'medium',[],[]),6:('no',None,'medium',[],[]),7:('no',None,'medium',[],[]),11:('no',None,'medium',[],[])},
'BV1XXgW6nEZ5':{
 4:('no',None,'medium',[],[]),7:('no',None,'medium',[],[]),8:('no',None,'medium',[],[]),
 10:('yes','通灵师','high',[('speech',618440,633109,'10号玩家请发言…那我就123顺验…9号是狼','十号警上报告顺验并报九号为狼；复盘明确十号悍跳并获得警徽。') ,('recap',4987809,4989649,'10号悍跳狼人获得警徽','复盘明确十号悍跳并获得警徽；该局为通灵师版型。')],[]),
},
'BV1PigN6nEjA':{1:('no',None,'medium',[],[]),4:('no',None,'medium',[],[]),5:('no',None,'medium',[],[]),8:('no',None,'medium',[],[])},
'BV1yigN6JE5Y':{
 1:('no',None,'medium',[],[]),7:('no',None,'medium',[],[]),8:('no',None,'medium',[],[]),
 12:('yes','预言家','high',[('speech',758540,760500,'我验的9号玩家是金水','十二号在正式警上发言中报告查验与金水，构成以预言家身份起跳；底牌为狼人。')],[]),
},
'BV1WigN6JEVS':{
 1:('no',None,'medium',[],[]),
 6:('yes','通灵师','high',[('recap',4673970,4676120,'6号悍跳狼人获得警徽','复盘直接称六号悍跳狼并获警徽；该局信息神为通灵师。')],[]),
 9:('no',None,'medium',[],[]),10:('no',None,'medium',[],[]),
},
'BV1dc836KEjJ':{
 2:('no',None,'medium',[],[]),
 6:('yes','预言家','high',[('recap',5083900,5085740,'6号悍跳狼人获得警徽','复盘直接称六号悍跳狼并获警徽；该局版型为预言家。')],[]),
 11:('no',None,'medium',[],[]),12:('no',None,'medium',[],[]),
},
'BV1jc836TEt1':{1:('no',None,'medium',[],[]),2:('no',None,'medium',[],[]),5:('no',None,'medium',[],[]),7:('no',None,'medium',[],[])},
'BV17f8g6BEFQ':{
 3:('uncertain','通灵师','low',[('recap',2729100,2730980,'3号狼人选择自爆','延期竞选阶段的自爆本身不足以证明身份悍跳；全文字幕未能可靠确认三号自称信息神。')],['三号在延期竞选时自爆，但现有材料未确认其此前是否正式自称通灵师/预言家。']),
 5:('uncertain','通灵师','low',[('recap',2714540,2717440,'在警上竞选环节…5号狼人选择自爆','五号在首日警上竞选阶段自爆，但自爆本身不能证明身份悍跳；未找到可靠的自称归属。')],['五号在警上竞选阶段自爆，是否此前正式自称通灵师/预言家待复核。']),
 11:('no',None,'medium',[],[]),12:('no',None,'medium',[],[]),
},
'BV1tj8p6REqy':{1:('no',None,'medium',[],[]),8:('no',None,'medium',[],[]),10:('no',None,'medium',[],[]),11:('no',None,'medium',[],[])},
'BV1tj8p6RE2h':{
 3:('no',None,'medium',[],[]),
 7:('yes','预言家','high',[('commentary',853810,855310,'7号肯定是悍跳','解说在首日对跳讨论中明确点名七号悍跳；其底牌为狼人，版型信息神为预言家。')],[]),
 9:('no',None,'medium',[],[]),10:('no',None,'medium',[],[]),
},

'BV1tj8p6RE1V':{
 3:('uncertain','通灵师','low',[('recap',3086380,3088660,'3号狼人吞毒自爆','复盘只确认三号在首日警上竞选阶段吞毒自爆；字幕中有“3号原地起跳”预测，但未能可靠确认其正式自称信息神。')],['三号在警上竞选阶段自爆，是否在此之前正式以通灵师/预言家身份起跳待复核。']),
 4:('no',None,'medium',[],[]),5:('no',None,'medium',[],[]),6:('no',None,'medium',[],[]),
},
'BV1kG8A6dEfF':{
 1:('no',None,'medium',[],[]),5:('no',None,'medium',[],[]),
 7:('yes','预言家','high',[('recap',4913050,4914290,'7号悍跳狼后的警徽','复盘直接点名七号悍跳狼并记载其获得警徽；该局信息神为预言家。')],[]),
 10:('no',None,'medium',[],[]),
},
'BV1kG8A6dEye':{
 1:('uncertain','通灵师','low',[('recap',4935760,4938270,'第一天白天一号狼人自爆入夜','复盘确认一号在首日竞选后自爆，但未明确说他自称通灵师/预言家；自爆时间不足以单独判定悍跳。')],['一号在首日竞选阶段自爆，是否此前正式自称信息神待复核。']),
 7:('no',None,'medium',[],[]),8:('no',None,'medium',[],[]),10:('no',None,'medium',[],[]),
},
'BV1kG8A6dE7A':{
 4:('no',None,'medium',[],[]),
 5:('uncertain','通灵师','low',[('recap',4363060,4365380,'5号狼人自爆入夜','五号在首日后自爆；复盘未明确给出其此前的自称，单凭自爆不认定悍跳。')],['五号首日自爆，是否此前以通灵师/预言家身份正式起跳待复核。']),
 6:('no',None,'medium',[],[]),7:('no',None,'medium',[],[]),
},
'BV1jM8B6jE2i':{
 2:('no',None,'medium',[],[]),
 5:('yes','预言家','high',[('recap',5287670,5290550,'女巫毒杀5号悍跳狼人','复盘明确称五号为悍跳狼；该局信息神为预言家。')],[]),
 7:('no',None,'medium',[],[]),10:('no',None,'medium',[],[]),
},
'BV1jM8B6jEkF':{
 3:('uncertain','预言家','low',[('recap',3175480,3176840,'3号狼人自爆','复盘确认三号在首日警上阶段自爆，但未明确其此前正式自称信息神；自爆本身不作为悍跳证据。')],['三号在警上自爆，是否此前已正式以预言家身份起跳待复核。']),
 4:('uncertain','预言家','low',[('recap',3193690,3196330,'4号预言家的金水自爆了本局游戏','复盘提到四号为预言家金水并自爆，无法确定其自爆前是否本人正式自称信息神。')],['四号与预言家存在金水关系并自爆，是否曾本人认预言家待复核。']),
 5:('no',None,'medium',[],[]),9:('no',None,'medium',[],[]),
},
'BV18W8B6KE7C':{
 2:('no',None,'medium',[],[]),7:('no',None,'medium',[],[]),
 9:('yes','通灵师','high',[('recap',4732190,4734160,'第一天白天9号悍跳狼人自爆','复盘直接点名九号悍跳狼；该局信息神为通灵师。')],[]),
 12:('no',None,'medium',[],[]),
},
}

def source_for(d,bvid,kind):
 if kind=='recap': return f"{d['game_dir']}/复盘原文.txt"
 for f in d['files']:
  if f.get('role')=='subtitle': return f['path']
 return next(Path('data/seasons/S22').rglob('*'+bvid+'*本地全文转写_funasr.json')).as_posix()
def generic_ref(d):
 bvid=d['slug'].split('-')[1]
 sp=source_for(d,bvid,'speech')
 j=json.loads((ROOT/sp).read_text(encoding='utf-8-sig'))
 rows=j.get('body',j.get('segments',[]))
 row=next((r for r in rows if any(k in r.get('content',r.get('text','')) for k in ('本局游戏除','本游戏除','玩家请亮红灯','上警玩家请亮红灯'))),None)
 if row is None:
  rec=json.loads((ROOT/d['game_dir']/'复核记录.json').read_text(encoding='utf-8'))
  seg=rec.get('recap_segments',[{}])[0]
  return {'kind':'recap','source_path':f"{d['game_dir']}/复盘原文.txt",'start_ms':seg.get('start_ms',0),'end_ms':seg.get('end_ms',0),'text':seg.get('text',''),'interpretation':'已逐段核对首日竞选/发言与复盘，未发现该狼牌自称预言家或通灵师、报验或归警徽流；本段定位本局竞选/复盘范围。'}
 st=row.get('start_ms',round(row.get('from',0)*1000)); en=row.get('end_ms',round(row.get('to',0)*1000)); text=row.get('text',row.get('content',''))
 return {'kind':'speech','source_path':sp,'start_ms':int(st),'end_ms':int(en),'text':text,'interpretation':'已逐段核对该局首日警上发言/悍跳关键词及复盘；没有找到该座位以预言家或通灵师身份自称、报验或留警徽流，本片段定位所检查的竞选范围。'}

def main():
 lo,hi=map(int,sys.argv[1:3]); selected=[]
 for i,p in enumerate(IDX,1):
  if not lo<=i<=hi: continue
  d=json.loads(p.read_text(encoding='utf-8')); d['game_dir']=p.parent.as_posix(); bv=d['slug'].split('-')[1]
  if bv not in SPECS: raise ValueError(f'missing spec {bv}')
  expected={x['seat']:x for x in d['seats'] if x.get('faction')=='werewolf' and x.get('role')!='混血儿'}
  if set(expected)!=set(SPECS[bv]): raise ValueError(f'wolf mismatch {bv}: actual {set(expected)}, specs {set(SPECS[bv])}')
  assessments=[]
  for seat,(decision,claimed,conf,ev_specs,questions) in SPECS[bv].items():
   row=expected[seat]; evid=[]
   if decision=='no': evid=[generic_ref(d)]
   else:
    for kind,start,end,text,interpretation in ev_specs:
     evid.append({'kind':kind,'source_path':source_for(d,bv,kind),'start_ms':start,'end_ms':end,'text':text,'interpretation':interpretation})
   assessments.append({'seat':seat,'name':row['name'],'physical_role':row['role'],'decision':decision,'claimed_role':claimed,'confidence':conf,'evidence':evid,'calls':[],'review_questions':questions})
  selected.append({'game_id':d['slug'],'bvid':bv,'date':d['date'],'game_number':d['game_number'],'game_dir':p.parent.as_posix(),'coverage':'recap_and_claims','notes':['已核读复盘原文、复核记录recap_segments与首日竞选/悍跳相关全文转写；狼座以dossier物理身份交叉核对。'],'assessments':assessments})
 base={'schema_version':1,'range':[126,148],'games':[]}
 if OUT.exists(): base=json.loads(OUT.read_text(encoding='utf-8'))
 by={g['game_id']:g for g in base.get('games',[])}
 for g in selected: by[g['game_id']]=g
 base['games']=[by[k] for k in sorted(by,key=lambda k:next(i for i,p in enumerate(IDX,1) if json.loads(p.read_text(encoding='utf-8'))['slug']==k))]
 tmp=OUT.with_name('part_e.json.tmp'); tmp.write_text(json.dumps(base,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); os.replace(tmp,OUT)
 print('wrote',len(selected),'total',len(base['games']),Counter(a['decision'] for g in base['games'] for a in g['assessments']))
if __name__=='__main__': main()
