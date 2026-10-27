import json,re,sys
sys.stdout=open("data/extractions/S22/bluff_review/part_b_extract_86_100.txt","w",encoding="utf-8")
from pathlib import Path
all_dirs=sorted(Path('data/games/S22').glob('*/dossier.json'))
for idx in range(85,100):
 p=all_dirs[idx]; d=json.loads(p.read_text(encoding='utf-8')); bvid=re.search(r'BV[0-9A-Za-z]{10}',p.parent.name)[0]
 print(f'### {idx+1} {d["slug"]} {d["date"]}')
 print('DIR',p.parent.as_posix())
 print('WOLVES:', '; '.join(f'{x["seat"]} {x["name"]} [{x["role"]}]' for x in d['seats'] if x['faction']=='werewolf'))
 for f in p.parent.iterdir():
  if f.name in ('复盘原文.txt','复核记录.json'):
   try:
    if f.name.endswith('.txt'):
     text=f.read_text(encoding='utf-8-sig').strip()
     print('RECAP-TXT:',text[:9000])
    else:
     r=json.loads(f.read_text(encoding='utf-8-sig'))
     seg=r.get('recap_segments',[])
     print('RECAP-SEG:',json.dumps(seg,ensure_ascii=False)[:6000])
   except Exception as e: print('READERR',e)
 sub=next((x for x in d['files'] if x['role'] in ('subtitle','transcript')),None)
 if sub:
  q=Path(sub['path']); t=json.loads(q.read_text(encoding='utf-8-sig'))
  rows=t.get('body',t.get('segments',[]))
  print('SOURCE',sub['role'],sub['path'])
  n=0
  for row in rows:
   st=row.get('from',row.get('start_ms',0)/1000); en=row.get('to',row.get('end_ms',0)/1000); tx=row.get('content',row.get('text',''))
   if st>2500: break
   if re.search(r'预言家|通灵师|验|警徽|悍跳|自爆|上警|查杀|金水|玩家请发言|退水',tx):
    print(f'S {round(st*1000)}-{round(en*1000)} {tx}')
    n+=1
    if n>=130: break
 print()


