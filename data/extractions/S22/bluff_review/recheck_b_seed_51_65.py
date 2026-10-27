import json,pathlib,sys
sys.stdout.reconfigure(encoding='utf-8')
p=pathlib.Path('data/extractions/S22/bluff_review/part_b.json');part=json.loads(p.read_text(encoding='utf-8'))
updates={}
def ev(kind,path,start,end,text,interp): return {'kind':kind,'source_path':path,'start_ms':start,'end_ms':end,'text':text,'interpretation':interp}
# use dossier subtitle/transcript paths per bvid
def source(b):
 d=json.loads(next(pathlib.Path('data/games/S22').glob(f'*{b}/dossier.json')).read_text(encoding='utf-8'))
 f=next(x for x in d['files'] if x['role'] in ('subtitle','transcript'))
 return f['path'],d
for b,rows in {
'BV1YmTc6yEFd':[
 (3,'yes','预言家','high',None,'狼人3号在首日首轮直接自称预言家并报验。',[('speech',1498350,1500230,'我是预言家','3号当前发言中的第一人称自称；在首日公开起跳。')]),
 (6,'no',None,'high',None,'核对6号首日发言：只以假设句讨论8号可能是预言家，未自称信息神。',[('speech',2239870,2242380,'假设八是一个预言家的话','该句以8号为假设对象，不是6号自称；已检查6号本轮余下发言。')]),
 (7,'no',None,'medium',None,'核对7号首日发言：明确表述混血身份并讨论8号预言家，没有本人报验或自称预言家/通灵师。',[('speech',2600360,2601560,'是我底牌是混子牌','7号该轮自述混子身份；周围上下文讨论其他玩家的预言家身份，不是本人信息神起跳。')])],
'BV1GmTc61EMA':[(8,'yes','预言家','high',None,'8号在首日警上发言报9号查杀并明确自称正常预言家。',[('speech',502380,506180,'所以我觉得我应该就是一个正常状态的预言家','8号首日竞选发言的第一人称自称，前文正在报9号查杀。')])],
'BV1Y2Tc6LEt4':[
 (2,'uncertain',None,'low','首日确认2号机械狼底牌，但目前未找到可定位到2号自己的完整信息神起跳句；不能仅凭被验狼判无。','2号首日发言片段只谈其他玩家身份，现有复盘仅佐证其底牌。',[('speech',510220,512660,'为什么我觉得他不是平民呢','2号当前发言是讨论他人身份；不足以证明其公开起跳或完全排除其他首日轮次。')]),
 (7,'yes','通灵师','high',None,'7号首日警上发言以第一人称报10号金水并留警徽流，构成通灵师起跳。',[('speech',1016520,1018580,'我验的十是金水','7号当轮第一人称报验，并在同一段公开留警徽流。')])],
'BV1gvTi66E7y':[(12,'no',None,'medium',None,'原证据中的“我仅仅是预言家”发生在该局开始前的赛间画面；之后首日未发现12号本人公开起跳，不能把解说/赛间台词算作悍跳。',[('speech',508510,510600,'我仅仅是预言家','此字幕处于游戏实际开局之前，非12号首日玩家发言；视频帧复核显示为赛间解说/过场。')])],
'BV18vTi66EnN':[(11,'yes','通灵师','high',None,'11号首日直接自称通灵师，后续复盘对底牌和跳神相互印证。',[('speech',731769,732469,'我是通灵师','11号首日公开自称通灵师。')])],
'BV119TJ6pEtC':[
 (7,'uncertain','通灵师','low','盗宝大师7号在首日被同期发言指称“跳通灵师”，但底牌夜间取得了通灵师能力；尚不能区分是在冒充通常通灵师还是公开其真实盗宝能力。','首日同期评论指向7号跳通灵师；盗宝大师机制可取通灵师能力，按要求保留这项特定区分疑问。',[('commentary',1513790,1517950,'但是呢KS跳舞的通灵师','首日讨论直接将KS与跳通灵师相连；当前转写未能定位到7号本人完整自称句，且盗宝大师可能取得该能力。')]),
 (10,'uncertain',None,'low','首日发言者认为10号像通灵师，但现有材料没有证明10号自己公开自称或报验。','他人对身份的判断不能代替10号本人起跳；暂保留需回听首日10号发言。',[('commentary',1597820,1599825,'觉得十是一个通灵师多一些','同期发言是对10号身份的推测，不是10号本人公开自称。')])],
'BV149TJ6WETs':[(7,'yes','通灵师','high',None,'7号首日发言自称通灵师并报4号金水，属于狼人底牌起跳。',[('speech',924270,925570,'等会儿哥们儿是个通灵师','7号在其首日发言轮中明确自称通灵师，随后报告4号验人。')])],
'BV1BjMh63EEK':[(7,'yes','预言家','high',None,'7号在首日轮次第一人称报告验2号为金水；原先误用的2744秒猎人话术不再作为证据。',[('speech',1303800,1305720,'我验的那个二是金水啊','7号在首日发言中报告本人查验结果，符合预言家起跳。')])],
'BV1BjMh63ED9':[
 (3,'uncertain',None,'low','3号狼王底牌已确认，但没有找到足以定位3号在首日公开起跳预言家/通灵师的个人窗口；复盘其被放逐不等于悍跳。','保留为未知，等待回听其首日完整发言。',[('recap','data/games/S22/2026-07-07_g02_BV1BjMh63ED9/复盘原文.txt',5855370,5857370,'3号狼王被公投出局','复盘只能确认3号狼王被投出，不能单独证明其首日跳了信息神。')]),
 (7,'yes','通灵师','high',None,'7号首日发言报告4号金水并留警徽流，属于通灵师公开起跳。',[('speech',640360,673430,'4号金金水啊……然后警徽3号十号十号','7号首日发言报告验人和警徽流；底牌为狼人，与真信息神区分。')])],
'BV1BjMh63EDf':[(12,'uncertain','通灵师','low','复盘将12号明确记为悍跳狼，但当前可用字幕中未找到12号自己的首日通灵师主张窗口；按新口径不能仅以复盘定为首日。','需要核对12号首日发言时段。',[('recap','data/games/S22/2026-07-07_g03_BV1BjMh63EDf/复盘原文.txt',4384640,4386420,'12号悍跳狼后的警徽','该句说明复盘认为12号悍跳并拿警徽，但本次首日个人发言摘录不足。')])],
'BV11uMG6PEkr':[(8,'no',None,'high',None,'8号首日被真预言家查验为狼人后自爆；首日自爆前发言未见本人冒充预言家或通灵师。',[('recap','data/games/S22/2026-07-08_g01_BV11uMG6PEkr/复盘原文.txt',6307075,6313895,'八号狼人自爆','复盘只记8号自爆；结合已检查的首日8号发言，没有确认其本人信息神自称。')])],
'BV1KuMG6NEez':[(9,'yes','预言家','high',None,'9号首日在警上发言自称预言家，并报6号金水。',[('speech',1181250,1184320,'然后我是一个预言家，我验了6号玩家是金水','9号本人首日发言，清楚自称并报验。')])],
'BV1suMG6PEYP':[(10,'yes','通灵师','high',None,'10号狼人首日警上自称通灵师，报验5号查杀并留警徽流；后续字幕中真正通灵师另有其人。',[('speech',551330,553865,'通灵师是在下验了那个五号是查杀','10号首日警上第一人称自称通灵师并报验，非真实信息神。')])]
}.items():
 path,d=source(b)
 for row in rows:
  seat,decision,role,conf,q,note,evs=row
  name=next(s['name'] for s in d['seats'] if s['seat']==seat); physical=next(s['role'] for s in d['seats'] if s['seat']==seat)
  evidence=[]
  for raw in evs:
   if len(raw)==5: k,st,en,text,interp=raw; ep=path
   else: k,ep,st,en,text,interp=raw
   evidence.append(ev(k,ep,st,en,text,interp))
  updates.setdefault(b,[]).append({'seat':seat,'name':name,'physical_role':physical,'decision':decision,'claimed_role':role,'first_day_claim': True if decision=='yes' else (False if decision=='no' else None),'claim_day':1 if decision=='yes' else None,'confidence':conf,'evidence':evidence,'review_questions':[q] if q else [],'decision_note':note})
# map dossiers in canonical range order
out=[]
for g in part['games'][:15]:
 b=g['bvid'];dp=next(pathlib.Path('data/games/S22').glob(f'*{b}/dossier.json'))
 if b in updates:out.append({'game_id':g['game_id'],'bvid':b,'first_day_end_ms':None,'assessments':updates[b]})
 payload={'schema_version':1,'scope':'first_day','games':out}
target=pathlib.Path('data/extractions/S22/bluff_review/recheck_b.json');tmp=target.with_suffix('.json.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(target)
print('wrote',target,'games',len(out),'assessments',sum(len(g['assessments']) for g in out))

