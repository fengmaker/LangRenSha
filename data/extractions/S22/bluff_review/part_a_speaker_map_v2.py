import json,pathlib,re,sys
root=pathlib.Path('.'); games=sorted((root/'data/games/S22').glob('*/dossier.json'),key=lambda p:str(p)); lo=int(sys.argv[1]); hi=int(sys.argv[2])
zh='零一二三四五六七八九十'
def num(s):
 if s.isdigit(): return int(s)
 if s=='十': return 10
 if s.startswith('十'): return 10+(zh.index(s[1]) if len(s)>1 else 0)
 if '十' in s: return (zh.index(s[0]) if s[0] in zh else 1)*10+(zh.index(s[-1]) if s[-1] in zh else 0)
 return zh.index(s) if s in zh else None
cue=re.compile(r'([0-9]{1,2}|[零一二三四五六七八九十]{1,2})号玩家请(?:做发言准备|发言)')
claim=re.compile(r'(?:我.{0,14}(?:预言家|通灵师)|(?:我是|我就是|我这把|我底牌|我本人).{0,14}(?:预言家|通灵师)|我验.{0,18}(?:金水|好人|狼人|查杀)|\d{1,2}号.{0,12}(?:悍跳|起跳)|(?:悍跳|起跳).{0,12}\d{1,2}号)')
for ix,p in enumerate(games[lo-1:hi],lo):
 d=json.loads(p.read_text(encoding='utf-8-sig')); f=next((f for f in d.get('files',[]) if f.get('role')=='subtitle'),None)
 if f:
  j=json.loads((root/f['path']).read_text(encoding='utf-8-sig')); raw=j.get('body',[]); items=[(round(x.get('from',0)*1000),x.get('content','')) for x in raw]
 else:
  f=next((f for f in d.get('files',[]) if f.get('role')=='transcript'),None)
  if not f: continue
  j=json.loads((root/f['path']).read_text(encoding='utf-8-sig')); raw=j.get('segments',[]); items=[(x.get('start_ms',0),x.get('text','')) for x in raw]
 current=None
 print(f'\n=== {ix} {d["slug"]} ({f["role"]})')
 for a,t in items:
  m=cue.search(t)
  if m:
   current=num(m.group(1))
  if claim.search(t): print(f' {a} seat={current} {t}')
