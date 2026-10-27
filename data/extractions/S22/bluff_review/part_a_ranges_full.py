import json,pathlib
for b,start,end in [('BV1vH7R6tEQp',600000,710000),('BV1vH7R6tEQp',1560000,1660000),('BV1hb7R6XEtD',1080000,1190000),('BV1hb7R6XEtD',2700000,2800000)]:
 p=next(pathlib.Path('data/transcripts/S22').glob(f'{b}_p01_funasr_full/transcript.json')); body=json.loads(p.read_text(encoding='utf-8-sig'))['segments']
 print('\n===',b,start,end)
 for x in body:
  a=x['start_ms']
  if start<=a<=end: print(f"{a} {x['text']}")
