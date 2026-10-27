import json
from pathlib import Path
for bvid,start,end,label in [('BV1Nsgy6cEiG',1000,1300,'90'),('BV1iMgq6ZEWn',0,1000,'97')]:
 p=next(Path('data/games/S22').glob(f'*{bvid}/dossier.json')); d=json.loads(p.read_text(encoding='utf-8')); f=next(Path(x['path']) for x in d['files'] if x['role'] in ('subtitle','transcript')); z=json.loads(f.read_text(encoding='utf-8-sig')); rows=z.get('body',z.get('segments',[])); out=Path(f'data/extractions/S22/bluff_review/part_b_window_{label}_claims.txt')
 with out.open('w',encoding='utf-8') as w:
  for r in rows:
   s=r.get('from',r.get('start_ms',0)/1000); e=r.get('to',r.get('end_ms',0)/1000); t=r.get('content',r.get('text',''))
   if start<=s<=end: w.write(f'{round(s*1000)}-{round(e*1000)} {t}\n')
 print(out)
