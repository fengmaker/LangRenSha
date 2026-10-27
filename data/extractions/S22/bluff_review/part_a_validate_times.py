import json,pathlib,re
root=pathlib.Path('.'); d=json.loads((root/'data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig')); bad=[]
for g in d['games']:
 for a in g['assessments']:
  for e in a.get('evidence',[]):
   p=root/e['source_path']; q=e['text']; st=e['start_ms']; en=e['end_ms']
   if p.suffix.lower()=='.json':
    j=json.loads(p.read_text(encoding='utf-8-sig')); arr=j.get('body',j.get('segments',[])); hits=[]
    for x in arr:
     if 'from' in x: xa=round(float(x.get('from',0))*1000); xb=round(float(x.get('to',x.get('from',0)))*1000); t=x.get('content','')
     else: xa=int(x.get('start_ms',0)); xb=int(x.get('end_ms',xa)); t=x.get('text','')
     if q in t and xa<=en+1000 and xb>=st-1000: hits.append((xa,xb,t))
    if not hits: bad.append((g['bvid'],a['seat'],st,en,q,p.as_posix()))
   elif p.suffix.lower()=='.txt':
    raw=p.read_text(encoding='utf-8-sig',errors='replace'); found=False
    for m in re.finditer(r'\[(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)\]',raw):
     xa=float(m.group(1))*1000; xb=float(m.group(2))*1000; snippet=raw[m.end():raw.find('\n',m.end()) if '\n' in raw[m.end():] else len(raw)]
     if q in snippet and xa<=en+1000 and xb>=st-1000: found=True;break
    if not found: bad.append((g['bvid'],a['seat'],st,en,q,p.as_posix()))
print('localized mismatches',len(bad))
for x in bad[:100]: print(x)
