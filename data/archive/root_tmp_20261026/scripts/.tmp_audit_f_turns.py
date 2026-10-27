import json, pathlib, re, sys
root=pathlib.Path('.')
b=sys.argv[1]; stop=float(sys.argv[2])
e=json.loads((root/'data/extractions/S23/game_reviews'/b/'entry.json').read_text(encoding='utf-8'))
d=json.loads((root/e['source_path']).read_text(encoding='utf-8'))
rows=d.get('body',d.get('segments',[])); source_rows=[]
for i,x in enumerate(rows):
    start=x.get('from',x.get('start_ms',0)/1000); end=x.get('to',x.get('end_ms',0)/1000)
    source_rows.append((start,end,x.get('content',x.get('text','')),i))
def seatno(v):
    if v.isdigit(): return int(v)
    vals={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if v=='十': return 10
    if v.startswith('十'): return 10+(vals.get(v[1:],0) if len(v)>1 else 0)
    if v.endswith('十'): return vals.get(v[0],0)*10
    return vals.get(v,0)
calls=[]
for st,en,t,i in source_rows:
    m=re.search(r'(?:过了|请|有请|到|发言到|叫)?\s*([0-9一二两三四五六七八九十]+)号(?:玩家|家)?请发言',t)
    if m:
        n=seatno(m.group(1))
        if n: calls.append((st,en,n,i,t))
folder=next((root/'data/games/S23').glob('*'+b)); dossier=json.loads((folder/'dossier.json').read_text(encoding='utf-8'))
import sys as _sys; _sys.path.insert(0,'.'); from website.api.bluffs import physical_wolf
wolves=[s['seat'] for s in dossier['seats'] if physical_wolf(dossier,s)]
print('WOLVES',wolves)
for j,(st,en,seat,i,calltxt) in enumerate(calls):
    nextst=calls[j+1][0] if j+1<len(calls) else stop
    if st>stop: break
    if seat not in wolves: continue
    print(f'\n--- seat {seat} {st:.2f}-{min(nextst,stop):.2f} prompt={calltxt} ---')
    for ss,ee,t,ii in source_rows:
        if ii==i: continue
        if ss>=en and ss<min(nextst,stop) and t.strip(): print(f'{ss:.2f} {t}')
