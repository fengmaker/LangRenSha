import subprocess,json,hashlib
from pathlib import Path
r=Path('/workspace/scratch/a7edd912716e/langrensha-cloud'); out=Path('/workspace/scratch/a7edd912716e/audit-published/S22');p=json.loads((out/'recaps_b_input.json').read_text())
result=[]
for ix,a,b in [(80,2878100,2888070),(90,4928700,4954330),(101,4991470,5007800),(116,3380920,3396370),(126,4904075,4923700)]:
 i=p[ix-74];base=i['path'].rsplit('/',1)[0]
 rr=json.loads(subprocess.check_output(['git','show','origin/ci/full-acceptance:'+base+'/复核记录.json'],cwd=r,text=True));sp=rr['source_path']; raw=subprocess.check_output(['git','show','origin/ci/full-acceptance:'+sp],cwd=r); data=json.loads(raw)
 print('\n##',ix,i['game_id'],sp,hashlib.sha256(raw).hexdigest()); print('keys',list(data) if isinstance(data,dict) else 'list')
 rows=data.get('body',data.get('segments',[])) if isinstance(data,dict) else data
 ss=[]
 for row in rows:
  st=row.get('start_ms',row.get('start',row.get('from',0)));ed=row.get('end_ms',row.get('end',row.get('to',0)))
  if 'from' in row or 'start' in row:st=int(st*1000);ed=int(ed*1000)
  if ed>=a and st<=b:
   q={'start_ms':st,'end_ms':ed,'text':row.get('text',row.get('content',''))};ss.append(q);print(q)
 result.append({'index':ix,'game_id':i['game_id'],'path':sp,'sha256':hashlib.sha256(raw).hexdigest(),'range_ms':[a,b],'segments':ss})
(out/'top_b_primary_text_windows.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
