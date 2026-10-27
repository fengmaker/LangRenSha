import json,pathlib,re
for bvid in ['BV1vH7R6tEQp','BV1hb7R6XEtD']:
 p=next(pathlib.Path('data/seasons/S22').glob(f'**/*{bvid}*.原始.json'))
 body=json.loads(p.read_text(encoding='utf-8-sig')).get('body',[])
 print('\n===',bvid,p)
 for x in body:
  a=round(x.get('from',0)*1000); s=x.get('content','')
  if a>2500000: continue
  if re.search(r'悍跳|跳.{0,8}(?:预言家|通灵师)|我.{0,10}(?:预言家|通灵师)|\d{1,2}号玩家请.*?(?:发言|准备)|过了?\d{1,2}号.{0,6}发言',s): print(f'{a} {s}')
