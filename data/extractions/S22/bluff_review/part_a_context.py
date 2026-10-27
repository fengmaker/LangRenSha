import json,pathlib,re,sys
for bvid,terms in [('BV1CGVC6cE8T',['我是通灵师','我开牌的时候跳通灵师了','我站在通灵师']),('BV1pGVC6cEbW',['我这个通灵师','我先把预言家一手']),('BV1vH7R6tEQp',['我是预言家','五号狼人自爆'])]:
 p=next(pathlib.Path('data/seasons/S22').glob(f'**/*{bvid}*.原始.json'),None)
 if not p: print('no',bvid); continue
 body=json.loads(p.read_text(encoding='utf-8-sig')).get('body',[])
 print('\n===',bvid,p)
 for term in terms:
  for i,x in enumerate(body):
   if term in x.get('content',''):
    print('\nTERM',term)
    for y in body[max(0,i-8):min(len(body),i+9)]: print(f"{y.get('from',0):.3f}-{y.get('to',0):.3f} {y.get('content','')}")
