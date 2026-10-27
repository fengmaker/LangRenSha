import json,re
from pathlib import Path
p=next(Path('data/games/S22').glob('*BV1RGgx6xEun/dossier.json')); d=json.loads(p.read_text(encoding='utf-8')); f=next(Path(x['path']) for x in d['files'] if x['role']=='subtitle'); z=json.loads(f.read_text(encoding='utf-8-sig')); rows=z.get('body',z.get('segments',[])); out=Path('data/extractions/S22/bluff_review/part_b_window_92.txt')
with out.open('w',encoding='utf-8') as w:
 for r in rows:
  s=r.get('from',r.get('start_ms',0)/1000); e=r.get('to',r.get('end_ms',0)/1000); t=r.get('content',r.get('text',''))
  if s<1800 and re.search(r'预言家|通灵师|我验|查杀|金水|号玩家请发言|警徽|退水|自爆',t): w.write(f'{round(s*1000)}-{round(e*1000)} {t}\n')
