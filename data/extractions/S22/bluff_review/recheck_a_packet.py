import json,pathlib,re,sys
root=pathlib.Path('.'); data=json.loads((root/'data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig')); lo=int(sys.argv[1]); hi=int(sys.argv[2])
for ix,g in enumerate(data['games'][lo-1:hi],lo):
 p=pathlib.Path(g['game_dir']); d=json.loads((p/'dossier.json').read_text(encoding='utf-8-sig')); rp=p/'复核记录.json'; rec=json.loads(rp.read_text(encoding='utf-8-sig')) if rp.exists() else {}; rs=rec.get('recap_segments',[])
 print(f'\n=== {ix} {g["bvid"]} {g["game_id"]}')
 print('wolves',[(s['seat'],s['name'],s['role']) for s in d['seats'] if s.get('faction')=='werewolf'])
 print('current',[(a['seat'],a['physical_role'],a['decision'],a.get('claimed_role')) for a in g['assessments'] if a['decision']!='no'])
 # Print recap flow from first-day heading to second night/day.
 start=next((i for i,x in enumerate(rs) if '第一天白天' in x.get('text','')),None)
 if start is not None:
  recaps=[]
  for x in rs[start:]:
   recaps.append(f'{x.get("start_ms")}–{x.get("end_ms")} {x.get("text")}')
   if len(recaps)>1 and any(k in x.get('text','') for k in ['入夜','第二天','第二日']): break
  print('recap day1:',' | '.join(recaps))
 # candidate transcript source
 f=next((f for f in d.get('files',[]) if f.get('role')=='subtitle'),None) or next((f for f in d.get('files',[]) if f.get('role')=='transcript'),None)
 if f:
  j=json.loads((root/f['path']).read_text(encoding='utf-8-sig')); raw=j.get('body',j.get('segments',[])); arr=[]
  for x in raw:
   if 'from' in x: a=round(float(x.get('from',0))*1000); b=round(float(x.get('to',x.get('from',0)))*1000); t=x.get('content','')
   else: a=int(x.get('start_ms',0)); b=int(x.get('end_ms',a)); t=x.get('text','')
   # Restrict to before day2. Keep direct claims, role keywords, referee prompts, and direct number claims.
   if re.search(r'预言家|通灵师|悍跳|起跳|退水|警徽|验了|验的|查杀|金水|请发言|发言准备|过了?\s*[0-9一二三四五六七八九十]+号',t): arr.append((a,b,t))
  print('speech candidates:')
  for a,b,t in arr[:90]: print(f' {a}–{b} {t}')
