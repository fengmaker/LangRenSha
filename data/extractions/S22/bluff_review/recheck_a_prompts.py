import json,pathlib,re,sys
D=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig'))
for n in map(int,sys.argv[1:]):
 g=D['games'][n-1]; d=json.loads((pathlib.Path(g['game_dir'])/'dossier.json').read_text(encoding='utf-8-sig')); f=next((f for f in d['files'] if f.get('role')=='subtitle'),None) or next((f for f in d['files'] if f.get('role')=='transcript'),None)
 print('\n===',n,g['bvid'],f['role'] if f else None)
 if not f: continue
 j=json.loads(pathlib.Path(f['path']).read_text(encoding='utf-8-sig')); raw=j.get('body',j.get('segments',[]))
 for x in raw:
  a=round(float(x.get('from',0))*1000) if 'from' in x else int(x.get('start_ms',0)); t=x.get('content',x.get('text',''))
  if a>3500000: break
  if re.search(r'号.*(?:请发言|发言准备)|随机点数|由.{0,12}号.*发言|过了?.{0,10}号.*发言|警徽流失|第一天白天|第一天.*投票|第一天.*出局',t): print(a,t)
