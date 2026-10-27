import json,pathlib,re
for bvid in ['BV1kGVC6cEyg','BV1CGVC6cE8T','BV1pGVC6cEbW']:
 p=next(pathlib.Path('data/seasons/S22').glob(f'**/*{bvid}*.原始.json')); body=json.loads(p.read_text(encoding='utf-8-sig'))['body']
 print('\n===',bvid)
 for x in body:
  a=round(x.get('from',0)*1000); s=x.get('content','')
  if a<4300000 and re.search(r'(?<![\d])\d{1,2}号.{0,10}(?:请.*?发言|发言准备)',s): print(f'{a} {s}')
