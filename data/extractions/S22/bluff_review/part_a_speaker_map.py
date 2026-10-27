import json,pathlib,re
for bvid in ['BV1hb7R6XEtD','BV1vH7R6tEQp']:
 p=next(pathlib.Path('data/transcripts/S22').glob(f'{bvid}_p01_funasr_full/transcript.json')); segs=json.loads(p.read_text(encoding='utf-8-sig'))['segments']
 print('\n===',bvid)
 cue=re.compile(r'(\d{1,2})号.{0,8}(?:请发言|发言准备)|过了?(?:\d{1,2}号)?玩家请发言')
 for i,x in enumerate(segs):
  a=x['start_ms']; s=x['text']
  if a>2500000: continue
  if cue.search(s): print(f"CUE {a} {s}")
  elif re.search(r'我.{0,15}(?:预言家|通灵师)|(?:我是|我就是).{0,12}(?:预言家|通灵师)|悍跳',s):
   prev=[]
   for y in reversed(segs[max(0,i-80):i]):
    if cue.search(y['text']): prev.append(y); break
   print(f"HIT {a} prev={prev[0]['text'] if prev else '??'} {s}")
