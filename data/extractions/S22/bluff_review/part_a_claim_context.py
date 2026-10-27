import json,pathlib,re
for bvid in ['BV1hb7R6XEtD','BV1vH7R6tEQp']:
 p=next(pathlib.Path('data/transcripts/S22').glob(f'{bvid}_p01_funasr_full/transcript.json'))
 b=json.loads(p.read_text(encoding='utf-8-sig'))['segments']
 print('\n===',bvid)
 pat=re.compile(r'我.{0,15}(?:预言家|通灵师)|(?:我是|我不是)(?:个|一个)?(?:预言家|通灵师)|(?:悍跳|跳.{0,8}(?:预言家|通灵师)|(?:预言家|通灵师).{0,8}跳)')
 for i,x in enumerate(b):
  s=x['text']; a=x['start_ms']
  if a>2200000: continue
  if pat.search(s):
   print(f"\nHIT {a}-{x['end_ms']} {s}")
   for y in b[max(0,i-3):min(len(b),i+4)]: print(f" {y['start_ms']}-{y['end_ms']} {y['text']}")
