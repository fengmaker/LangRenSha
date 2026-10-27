from pathlib import Path
import hashlib, json
ROOT=Path(__file__).resolve().parent
spec={
 'bvid':'BV1V8af6zE56','start':971.16,'end':1608.14,'frame_sec':1600,
 'phase_basis':'971.16s字幕确认其他玩家上警，警上竞选开始；1608.14s字幕确认警上发言结束。1600.000s位于最后一位警上发言结束前8.14秒。',
 'frame_basis':'1608.14s字幕确认警上发言结束；1600.000s截帧仍在最后一位候选人的话轮中，侧栏可读。',
 'frame_text':'1600.000s处于首日警上竞选末位发言中。逐席核看侧栏：3号章亿阳显示“验2金水、警徽流1-5”；2/5/10号狼位的侧栏没有显示他们本人的预言家或通灵师查验/警徽流摘要。',
 'assessments':[
  {'seat':2,'decision':'no','note':'我读完2号首日警上竞选和警下完整话轮。竞选时他是在数还有几人起跳、说人少了并结束；警下他明确称自己为独立好人，讨论3/10/12号的狼坑与验人，没有把他人查验或站边当成本人的信息神身份。',
   'windows':[(1577.67,1608.14,'2号完整警上话轮：数还剩的起跳位，没报自己的验人或警徽流。'),(3304.99,3503.58,'2号完整警下话轮：自称独立好人，评论3/10/12号的身份及狼坑；没有本人信息神自称。')], 'extra':[]},
  {'seat':3,'decision':'yes','role':'预言家','note':'3号本人首日警上报验2号金水，称“单边预言家”，并留1/5顺验。警徽侧栏在3号章亿阳行显示“验2金水、警徽流1-5”；这和他本人1536.57–1577.31话轮直接互证。后续首日话轮继续用自己的预言家视角报验9，不是引用他人身份。计为首日预言家悍跳。',
   'windows':[(1541.26,1577.31,'3号本人报验2号金水，称单边预言家并安排1/5顺验。'),(3503.58,3633.53,'3号在首日后续话轮继续以自己的预言家视角报9号并请求投票。')], 'extra':[(1550,'1550.000s落在3号本人警上话轮内；3号章亿阳侧栏显示“验2金水、警徽流1-5”，与其原话对应。')]},
  {'seat':5,'decision':'no','note':'我读完5号首日警下完整话轮。他明确把3号认作预言家、解释自己为什么投3号；其中“如果我是预言家”是谈论假设，不是本人起跳或报自己的查验。其本人没有声称预言家/通灵师，也没有自己的验人和警徽流。',
   'windows':[(1804.30,1971.10,'5号完整警下话轮：评估3/9/12号的对跳，明确说目前站边3号；“如果我是预言家”属于假设。')], 'extra':[]},
  {'seat':10,'decision':'no','note':'我读完10号首日警下完整话轮。他讨论7号跳女巫、3/12号谁像预言家，之后明确以“我是平民”解释自己退水。全段没有报自己的查验或警徽流；他对其他玩家预言家身份的判断不是本人起跳。',
   'windows':[(2654.02,2985.66,'10号完整警下话轮：以平民身份解释退水，讨论7/3/12号的身份及站边；未报本人验人。')], 'extra':[]}
 ]
}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def times(r):
 s=r.get('start_ms',round(r.get('from',0)*1000)); e=r.get('end_ms',round(r.get('to',0)*1000)); return s,e
def quote(entry,raw,source_sha,lo,hi,meaning):
 rows=[r for r in raw.get('body',raw.get('segments',[])) if round(lo*1000)<=times(r)[0]<round(hi*1000)]
 assert rows,(spec['bvid'],lo,hi)
 return {'kind':'transcript','source_path':entry['source_path'],'source_sha256':source_sha,'start_ms':times(rows[0])[0],'end_ms':times(rows[-1])[1],
         'text':'\n'.join(r.get('content',r.get('text','')) for r in rows),'interpretation':meaning}
def frame(bvid,sec,desc,interp):
 p=ROOT/'data/extractions/S23/bluff_review/frames'/bvid/f'{bvid}_{sec:09.3f}.png'
 return {'kind':'video_frame','source_path':p.relative_to(ROOT).as_posix(),'source_sha256':sha(p),'start_ms':round(sec*1000),'end_ms':round(sec*1000),'frame_time_ms':round(sec*1000),'text':desc,'interpretation':interp}
b=spec['bvid']; entry=json.loads((ROOT/'data/extractions/S23/game_reviews'/b/'entry.json').read_text(encoding='utf-8')); source=ROOT/entry['source_path']; source_sha=sha(source); raw=json.loads(source.read_text(encoding='utf-8-sig'))
dossier=json.loads(next((ROOT/'data/games/S23').glob('*'+b)).joinpath('dossier.json').read_text(encoding='utf-8')); seats={s['seat']:s for s in dossier['seats']}
main=frame(b,spec['frame_sec'],spec['frame_text'],'已直接目视并核对侧栏行号/姓名牌；阶段与原始字幕中的结束时点交叉确认。')
ass=[]
for a in spec['assessments']:
 seat=seats[a['seat']]
 ev=[quote(entry,raw,source_sha,lo,hi,meaning) for lo,hi,meaning in a['windows']]+[main]
 for sec,desc in a['extra']:
  ev.append(frame(b,sec,desc,'已直接目视原帧；座位侧栏与该时段本人的原话相互核实。'))
 row={'seat':seat['seat'],'name':seat['name'],'physical_role':seat['role'],'decision':a['decision'],'claimed_role':a.get('role'),
      'claim_day':1 if a['decision']=='yes' else None,'first_day_claim':a['decision']=='yes','verification_status':'assistant_inferred',
      'decision_note':a['note'],'evidence':ev,'review_questions':[]}
 ass.append(row)
record={'game_id':dossier['slug'],'bvid':b,'date':dossier['date'],'game_number':dossier['game_number'],'source_path':entry['source_path'],'source_sha256':source_sha,
 'first_day_window':{'start_ms':round(spec['start']*1000),'end_ms':round(spec['end']*1000),'basis':spec['phase_basis']},
 'frame_selection':{'timestamp_ms':round(spec['frame_sec']*1000),'basis':spec['frame_basis'],'phase_verified':True,'visual_reviewed':True,'overlay_readable':True,
  'frame_path':main['source_path'],'frame_sha256':main['source_sha256']},'assessments':ass,'separate_identity_claims':[],'notes':['全部判断为助手独立推断；未新增用户确认。']}
out=ROOT/'data/extractions/S23/bluff_review/parts/audit_f.json'
payload=json.loads(out.read_text(encoding='utf-8')) if out.exists() else {'part':'f','reviewer':'independent_assistant','games':[]}
if any(g['bvid']==b for g in payload['games']): raise SystemExit('already present: '+b)
payload['games'].append(record)
tmp=out.with_name(out.name+'.tmp')
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
check=json.loads(tmp.read_text(encoding='utf-8'))
assert len(check['games'])==len(payload['games'])
tmp.replace(out)
json.loads(out.read_text(encoding='utf-8'))
print(json.dumps({'added':b,'games':len(payload['games']),'wolves':len(ass)},ensure_ascii=False))
