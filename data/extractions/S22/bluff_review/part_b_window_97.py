import json
from pathlib import Path
p=next(Path('data/games/S22').glob('*BV1iMgq6ZEWn/dossier.json')); d=json.loads(p.read_text(encoding='utf-8')); f=next(Path(x['path']) for x in d['files'] if x['role']=='transcript'); z=json.loads(f.read_text(encoding='utf-8-sig')); rows=z.get('body',z.get('segments',[])); out=Path('data/extractions/S22/bluff_review/part_b_window_97.txt')
with out.open('w',encoding='utf-8') as w:
 for r in rows:
  s=r.get('from',r.get('start_ms',0)/1000); e=r.get('to',r.get('end_ms',0)/1000); t=r.get('content',r.get('text',''))
  if 800<=s<=1150: w.write(f'{round(s*1000)}-{round(e*1000)} {t}\n')
