from pathlib import Path
import hashlib, json
ROOT=Path(__file__).resolve().parent
BVID='BV1RPaW6zEg8'
entry=json.loads((ROOT/'data/extractions/S23/game_reviews'/BVID/'entry.json').read_text(encoding='utf-8'))
source=ROOT/entry['source_path']
raw=json.loads(source.read_text(encoding='utf-8'))
rows=raw.get('body',raw.get('segments',[]))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def quote(lo,hi,meaning):
    selected=[r for r in rows if round(lo*1000)<=r.get('start_ms',round(r.get('from',0)*1000))<round(hi*1000)]
    assert selected,(lo,hi)
    start=selected[0].get('start_ms',round(selected[0].get('from',0)*1000))
    end=selected[-1].get('end_ms',round(selected[-1].get('to',0)*1000))
    return {'kind':'transcript','source_path':entry['source_path'],'source_sha256':sha(source),'start_ms':start,'end_ms':end,
            'text':'\n'.join(r.get('content',r.get('text','')) for r in selected),'interpretation':meaning}
def frame(sec,desc):
    p=ROOT/'data/extractions/S23/bluff_review/frames'/BVID/f'{BVID}_{sec:09.3f}.png'
    return {'kind':'video_frame','source_path':p.relative_to(ROOT).as_posix(),'source_sha256':sha(p),'start_ms':round(sec*1000),'end_ms':round(sec*1000),'frame_time_ms':round(sec*1000),'text':desc,'interpretation':'已直接目视原帧；以座位号和姓名牌定位本人，并将可见侧栏与首日原话交叉核实。'}
dossier=json.loads(next((ROOT/'data/games/S23').glob('*'+BVID)).joinpath('dossier.json').read_text(encoding='utf-8'))
seats={s['seat']:s for s in dossier['seats']}
main_desc='1190.000s处于首日警上发言结束前；侧栏可读。11号徐言雨侧栏显示“验10平民、警徽流5-12”，1/8/12号侧栏没有显示自己的预言家或通灵师验人结果/警徽流。'
main=frame(1190,main_desc)
assessments=[
 {'seat':1,'decision':'no','note':'我读完1号首日警上竞选话轮和警下话轮。警上他反复讨论7号是否真通灵、11号是否通灵，并以好人身份交边；警下继续围绕他人视角分析，没有把他人的验人或假设说成自己的查验，也没有本人预言家/通灵师自称。',
  'windows':[(1036.20,1195.90,'1号完整警上竞选话轮：讨论7/11号的身份并以好人身份交边；未报自己的查验。'),(1368.10,1624.52,'1号完整警下话轮：讨论其他玩家的站边与狼坑，并明确说自己的底牌是好人。')], 'extra':[]},
 {'seat':8,'decision':'no','note':'我读完8号首日警上与警下完整话轮。警上他是在听11号的金水和等后置位信息；警下他讨论7号、11号和10号的他人验人关系并以好人身份发言，没有把引用他人的验人、站边或假设改成自己的信息神自称。',
  'windows':[(509.91,582.89,'8号完整警上话轮：评价11号给10号金水，明确自称好人并继续等后置位发言。'),(2495.78,2666.68,'8号完整警下话轮：讨论7/11号如何报10号身份及自己的狼坑，未声称自己验人。')], 'extra':[]},
 {'seat':11,'decision':'yes','role':'通灵师','note':'11号在本人首日警上话轮先报10号为金水、安排警徽流，并明确说“无论如何我都会自己跳的”。1190.000s末位发言前截图中11号侧栏显示“验10平民、警徽流5-12”；400.000s另帧显示徐言雨本人正在发言。本人报告和视觉摘要相互印证，计为首日通灵师悍跳。',
  'windows':[(385.96,399.64,'本人报10号金水并在同一话轮说会自己跳。'),(410.99,422.73,'本人重复10号金水和自己的警徽流。')], 'extra':[(400,'400.000s徐言雨正在首日警上发言，画面姓名牌与11号座位侧栏相符。')]},
 {'seat':12,'decision':'no','note':'我读完12号首日警下完整话轮。他解释给11号投票的原因，称自己是好人，继续讨论11号是否有通灵师面及其他玩家的狼坑；没有以本人身份报验人或警徽流。截图中12号侧栏也未显示自己的信息神查验摘要。',
  'windows':[(1234.40,1368.10,'12号警下完整话轮：解释投11号的原因、站边并分析其他座位；没有本人验人或警徽流。')], 'extra':[]}
]
for a in assessments:
    seat=seats[a['seat']]
    evidence=[quote(lo,hi,meaning) for lo,hi,meaning in a['windows']]+[main]
    evidence += [frame(sec,desc) for sec,desc in a['extra']]
    a_out={'seat':seat['seat'],'name':seat['name'],'physical_role':seat['role'],'decision':a['decision'],
           'claimed_role':a.get('role'),'claim_day':1 if a['decision']=='yes' else None,
           'first_day_claim':a['decision']=='yes','verification_status':'assistant_inferred','decision_note':a['note'],'evidence':evidence,'review_questions':[]}
    a.clear(); a.update(a_out)
record={'game_id':dossier['slug'],'bvid':BVID,'date':dossier['date'],'game_number':dossier['game_number'],
 'source_path':entry['source_path'],'source_sha256':sha(source),
 'first_day_window':{'start_ms':364480,'end_ms':1198240,'basis':'364.48s字幕确认警上竞选开始；1195.90s字幕确认警上发言结束。首日竞选末位结束前5.90秒取1190.000s原视频帧。'},
 'frame_selection':{'timestamp_ms':1190000,'basis':'1195.90s字幕确认警上发言结束；1190.000s位于最后一人结束前5.90秒，侧栏仍可读。','phase_verified':True,'visual_reviewed':True,'overlay_readable':True,'frame_path':main['source_path'],'frame_sha256':main['source_sha256']},
 'assessments':assessments,'separate_identity_claims':[],'notes':['全部判断为助手独立推断；未新增用户确认。']}
out=ROOT/'data/extractions/S23/bluff_review/parts/audit_f.json'
out.write_text(json.dumps({'part':'f','reviewer':'independent_assistant','games':[record]},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'out':out.as_posix(),'games':1,'assessments':len(assessments)},ensure_ascii=False))

