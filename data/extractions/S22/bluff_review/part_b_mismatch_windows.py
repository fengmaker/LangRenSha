import json,re
from pathlib import Path
p=Path('data/extractions/S22/bluff_review/part_b.json'); d=json.loads(p.read_text(encoding='utf-8'))
want={'BV1RGgx6xEun':{5},'BV1RGgx6xEP9':{5,6},'BV1iMgq6ZE5t':{4}}
for g in d['games']:
 if g['bvid'] not in want: continue
 for a in g['assessments']:
  if a['seat'] not in want[g['bvid']]: continue
  for e in a['evidence']:
   print('\n###',g['bvid'],a['seat'],e['source_path'],e['start_ms'],e['end_ms'],'WANTED',e['text'])
   src=Path(e['source_path']); rows=[]
   if src.suffix=='.json':
    z=json.loads(src.read_text(encoding='utf-8-sig')); raw=z.get('body',z.get('segments',[]))
    for r in raw: rows.append((r.get('start_ms',round(r.get('from',0)*1000)),r.get('end_ms',round(r.get('to',0)*1000)),r.get('text',r.get('content',''))))
   else:
    for line in src.read_text(encoding='utf-8-sig').splitlines():
     m=re.match(r'\[([\d.]+)[–—-]([\d.]+)\]\s*(.*)',line)
     if m: rows.append((round(float(m[1])*1000),round(float(m[2])*1000),m[3]))
   for s,en,t in rows:
    if en>=e['start_ms']-1000 and s<=e['end_ms']+1000: print(s,en,t)
