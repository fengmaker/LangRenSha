import json, pathlib, re, sys
root=pathlib.Path('.')
games=sorted((root/'data/games/S22').glob('*/dossier.json'),key=lambda p:str(p))
lo=int(sys.argv[1]); hi=int(sys.argv[2])
recc=re.compile(r'悍跳|获得警徽|拿到警徽|警徽|预言家|通灵师|第.{1,2}天.{0,12}(?:出局|被抗推|被公投)|第一天.{0,16}(?:出局|被抗推|被公投)')
speech=re.compile(r'(?:我.{0,10}(?:是|底牌|身份|验|查验|验证|警徽流).{0,12}(?:预言家|通灵师|金水|好人)|(?:我是|我就是|我这把|我底牌|我本人|我验).{0,18}(?:预言家|通灵师|金水)|\d{1,2}号.{0,8}悍跳|悍跳.{0,10}\d{1,2}号|跳.{0,8}(?:预言家|通灵师))')
for ix,p in enumerate(games[lo-1:hi],lo):
 d=json.loads(p.read_text(encoding='utf-8-sig')); bvid=d['slug'].split('-')[1]
 print(f'\n===== {ix} {p.parent.as_posix()} bvid={bvid} g{d.get("game_number")}')
 print('W',json.dumps([{k:s.get(k) for k in ('seat','name','role','learned_role')} for s in d['seats'] if s.get('faction')=='werewolf'],ensure_ascii=False))
 rp=p.parent/'复核记录.json'
 if rp.exists():
  r=json.loads(rp.read_text(encoding='utf-8-sig'))
  for x in r.get('recap_segments',[]):
   if recc.search(x.get('text','')): print(f"R {x['start_ms']}-{x['end_ms']} {x['text']}")
 sub=next((f for f in d.get('files',[]) if f.get('role')=='subtitle'),None)
 if sub:
  src=sub['path']; j=json.loads((root/src).read_text(encoding='utf-8-sig')); seg=[(round(x.get('from',0)*1000),round(x.get('to',0)*1000),x.get('content','')) for x in j.get('body',[])]
 else:
  tp=root/'data'/'transcripts'/'S22'/f'{bvid}_p01_funasr_full'/'transcript.json'
  if not tp.exists(): print('NO TRANSCRIPT'); continue
  src=tp.as_posix(); j=json.loads(tp.read_text(encoding='utf-8-sig')); seg=[(x.get('start_ms',0),x.get('end_ms',0),x.get('text','')) for x in j.get('segments',[])]
 print('SRC',src)
 count=0
 for a,z,t in seg:
  if speech.search(t) and a < 4200000:
   print(f'S {a}-{z} {t}'); count+=1
   if count>=45: print('...match cap...');break
