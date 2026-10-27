import json,pathlib,re
for bvid in ['BV1kGVC6cEyg','BV1CGVC6cE8T','BV1pGVC6cEbW']:
 p=next(pathlib.Path('data/seasons/S22').glob(f'**/*{bvid}*.原始.json'))
 b=json.loads(p.read_text(encoding='utf-8-sig'))['body']
 print('\n===',bvid)
 for i,x in enumerate(b):
  s=x['content']
  if any(t in s for t in ['玩家请发言','号玩家请','号玩家发言','号做发言准备','号玩家请做','通灵师','预言家','悍跳']):
   if x['from']<2400: print(f"{x['from']:.3f}-{x['to']:.3f} {s}")
