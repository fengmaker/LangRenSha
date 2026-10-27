import json,pathlib
for b,start,end in [('BV1kGVC6cEyg',3100000,3400000),('BV1CGVC6cE8T',1270000,1750000),('BV1pGVC6cEbW',380000,740000)]:
 p=next(pathlib.Path('data/seasons/S22').glob(f'**/*{b}*.原始.json')); body=json.loads(p.read_text(encoding='utf-8-sig'))['body']
 print('\n===',b)
 for x in body:
  a=round(x.get('from',0)*1000)
  if start<=a<=end: print(f"{a} {x.get('content','')}")
