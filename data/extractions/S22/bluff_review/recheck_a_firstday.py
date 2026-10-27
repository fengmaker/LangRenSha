import json,pathlib,re,sys
root=pathlib.Path('.'); data=json.loads((root/'data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig')); lo=int(sys.argv[1]);hi=int(sys.argv[2])
pat=re.compile(r'预言家|通灵师|悍跳|起跳|退水|警徽|验了|验的|查杀|金水|请发言|发言准备|入夜|天亮|第[一二三四五六七八九十0-9]+天|放逐|公投|投票')
for i,g in enumerate(data['games'][lo-1:hi],lo):
 p=root/g['game_dir']; d=json.loads((p/'dossier.json').read_text(encoding='utf-8-sig')); recp=p/'复核记录.json'; rec=json.loads(recp.read_text(encoding='utf-8-sig')) if recp.exists() else {}; rs=rec.get('recap_segments',[])
 print(f'\n=={i} {g["bvid"]} current='+str([(a['seat'],a['physical_role'],a['decision'],a.get('claimed_role')) for a in g['assessments'] if a['decision']!='no']))
 f=next((x for x in d.get('files',[]) if x.get('role')=='subtitle'),None) or next((x for x in d.get('files',[]) if x.get('role')=='transcript'),None)
 if not f: print('NO TRANSCRIPT'); continue
 j=json.loads((root/f['path']).read_text(encoding='utf-8-sig')); raw=j.get('body',j.get('segments',[])); arr=[]
 for x in raw:
  if 'from' in x: a=round(float(x.get('from',0))*1000);b=round(float(x.get('to',x.get('from',0)))*1000); t=x.get('content','')
  else: a=int(x.get('start_ms',0));b=int(x.get('end_ms',a));t=x.get('text','')
  if pat.search(t): arr.append((a,b,t))
 # Print timeline up to 3M (live part), sparse relevant text. 
 for a,b,t in arr:
  if a<3100000: print(f'{a}–{b} {t}')
