import json,re
from pathlib import Path
p=next(Path('data/games/S22').glob('*BV1iMgq6ZE5t/dossier.json')); d=json.loads(p.read_text(encoding='utf-8')); f=next(Path(x['path']) for x in d['files'] if x['role']=='transcript'); z=json.loads(f.read_text(encoding='utf-8-sig')); rows=z.get('body',z.get('segments',[]))
for r in rows:
 s=r.get('from',r.get('start_ms',0)/1000); e=r.get('to',r.get('end_ms',0)/1000); t=r.get('content',r.get('text',''))
 if s<2500 and re.search(r'(号玩家请发言|我是预言家|我是通灵师|自爆|退水|验.*查杀|验.*金水)',t): print(round(s*1000),round(e*1000),t)
