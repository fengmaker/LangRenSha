import json,pathlib,re,sys
root=pathlib.Path('.')
games=sorted((root/'data/games/S22').glob('*/dossier.json'),key=lambda p:str(p))
for ix in [7,9,10,12,13]:
 d=json.loads(games[ix-1].read_text(encoding='utf-8-sig')); b=d['slug'].split('-')[1]
 sub=next((f for f in d.get('files',[]) if f.get('role')=='subtitle'),None)
 if sub:
  src=sub['path']; j=json.loads((root/src).read_text(encoding='utf-8-sig')); seg=[(round(x.get('from',0)*1000),round(x.get('to',0)*1000),x.get('content','')) for x in j.get('body',[])]
 else: continue
 cue=re.compile(r'(?:\d{1,2}号玩家请发言|\d{1,2}号请发言|过了?\s*\d{1,2}号(?:玩家)?请发言|\d{1,2}号玩家请做发言准备)')
 cand=re.compile(r'(?:我.{0,12}(?:预言家|通灵师)|(?:我是|我就是|我这把|我底牌).{0,15}(?:预言家|通灵师)|(?:我验|我查|我验证).{0,15}(?:金水|好人|狼人)|\d{1,2}号.{0,8}悍跳|悍跳.{0,10}\d{1,2}号|跳.{0,8}(?:预言家|通灵师))')
 print(f'\n=== {ix} {b} {src}')
 prev=None
 for a,z,t in seg:
  if cue.search(t): prev=(a,t)
  if cand.search(t) and a<4200000:
   print(f'CAND {a}-{z} {t} | lastcue={prev}')
