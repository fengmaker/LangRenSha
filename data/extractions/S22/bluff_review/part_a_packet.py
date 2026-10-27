import json, pathlib, re, sys
root=pathlib.Path('.')
games=sorted((root/'data/games/S22').glob('*/dossier.json'), key=lambda p:str(p))
lo=int(sys.argv[1]) if len(sys.argv)>1 else 1; hi=int(sys.argv[2]) if len(sys.argv)>2 else 5
claim=re.compile(r'悍跳|跳(?:了)?(?:个|一)?(?:预言家|通灵师)|(?:我|我是|本人|本人就是|我就是).{0,12}(?:预言家|通灵师)|(?:预言家|通灵师).{0,8}(?:是我|我跳|我来|我验)|警徽流|归票|带票|今天.{0,8}(?:出|推|投)|出掉|投给')
for ix,p in enumerate(games[lo-1:hi],lo):
 d=json.loads(p.read_text(encoding='utf-8-sig')); bvid=d['slug'].split('-')[1]
 print(f'\n===== {ix} {p.parent.as_posix()} {d.get("slug")} {d.get("date")} g{d.get("game_number")} bvid={bvid}')
 wolves=[s for s in d['seats'] if s.get('faction')=='werewolf']; print('WOLVES',json.dumps([{k:s.get(k) for k in ('seat','name','role','learned_role')} for s in wolves],ensure_ascii=False))
 rev=p.parent/'复核记录.json'
 if rev.exists():
  r=json.loads(rev.read_text(encoding='utf-8-sig')); print('RECAP:')
  for s in r.get('recap_segments',[]):
   tx=s.get('text','')
   if re.search(r'悍跳|上警|警徽|预言家|通灵师|归票|投票|公投|出局|放逐|带走|狼.{0,3}跳',tx): print(f" {s.get('start_ms')}–{s.get('end_ms')} {tx}")
 sub=next((f for f in d.get('files',[]) if f.get('role')=='subtitle'),None)
 segs=[]; src=''
 if sub:
  src=sub['path']; t=json.loads((root/src).read_text(encoding='utf-8-sig'))
  segs=[(round(x.get('from',0)*1000),round(x.get('to',0)*1000),x.get('content','')) for x in t.get('body',[])]
 else:
  tp=root/'data'/'transcripts'/'S22'/f'{bvid}_p01_funasr_full'/'transcript.json'
  if tp.exists():
   src=tp.as_posix(); t=json.loads(tp.read_text(encoding='utf-8-sig'))
   segs=[(x.get('start_ms',0),x.get('end_ms',0),x.get('text','')) for x in t.get('segments',[])]
  else: print('NO_TRANSCRIPT'); continue
 print('SOURCE',src); print('TRANSCRIPT MATCHES:')
 for a,z,tx in segs:
  if claim.search(tx): print(f' {a}–{z} {tx}')
