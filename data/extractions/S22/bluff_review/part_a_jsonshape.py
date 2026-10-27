import json,pathlib
for b in ['BV1hb7R6XEtD','BV1vH7R6tEQp']:
 p=next(pathlib.Path('data/transcripts/S22').glob(f'{b}_p01_funasr_full/transcript.json'))
 d=json.loads(p.read_text(encoding='utf-8-sig'))
 print(b,d.keys())
 for k,v in d.items():
  if isinstance(v,list): print(k,len(v),str(v[:2])[:1200])
