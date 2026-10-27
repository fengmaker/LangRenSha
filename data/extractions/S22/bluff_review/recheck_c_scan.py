import json,re,sys
from pathlib import Path
allp=sorted(Path('data/games/S22').glob('*/dossier.json'))
lo,hi=map(int,sys.argv[1:3]); terms=('预言家','通灵师','悍跳','起跳','金水','查杀','退水','警徽流','我是','我验','验了','首跳')
out=[]
for ix in range(lo,hi+1):
 p=allp[ix-1]; d=json.loads(p.read_text(encoding='utf-8')); gd=p.parent.as_posix(); bv=re.search(r'BV[0-9A-Za-z]{10}',d['slug'])[0]
 rec=json.loads((p.parent/'复核记录.json').read_text(encoding='utf-8')) if (p.parent/'复核记录.json').exists() else {}
 recap=(p.parent/'复盘原文.txt').read_text(encoding='utf-8') if (p.parent/'复盘原文.txt').exists() else ''
 wolves=[s for s in d.get('seats',[]) if s.get('faction')=='werewolf' and s.get('role')!='混血儿']
 out += [f'\n=== {ix} {d["slug"]} {d["date"]} #{d["game_number"]} {gd} ===','W '+json.dumps(wolves,ensure_ascii=False)]
 rr=[x for x in recap.splitlines() if any(k in x for k in ('悍跳','跳预言家','跳通灵','警徽','自爆','退水'))]
 out.append('RECAP\n'+'\n'.join(rr))
 src=next((f['path'] for f in d.get('files',[]) if f.get('role')=='subtitle'),None)
 if not src:
  src=next((x.as_posix() for x in Path('data/seasons/S22').rglob('*'+bv+'*本地全文转写_funasr.json')),None)
 if not src: out.append('NO SOURCE'); continue
 try:
  j=json.loads(Path(src).read_text(encoding='utf-8-sig')); rows=j.get('body',j.get('segments',[]))
 except Exception as e: out.append(f'SOURCE_ERROR {src} {e}'); continue
 def times(r):
  return (r.get('start_ms',round(r.get('from',0)*1000)),r.get('end_ms',round(r.get('to',0)*1000)),r.get('text',r.get('content','')))
 startidx=None
 for i,r in enumerate(rows):
  _,_,t=times(r)
  if any(x in t for x in ('本局游戏除','本局除','本游戏除','本角戏除')):
   startidx=i; break
 if startidx is None:
  for i,r in enumerate(rows):
   ms,_,t=times(r)
   if ms>250000 and any(x in t for x in ('上警玩家请亮红灯','其他玩家均上警')):
    startidx=i; break
 if startidx is None: out.append('NO ELECTION MARKER '+src); continue
 s_ms=times(rows[startidx])[0]
 endidx=None
 for i in range(startidx+1,len(rows)):
  ms,_,t=times(rows[i])
  if ms-s_ms>1400000: break
  if any(x in t for x in ('退水自爆环节','退水自爆','退水环节')):
   endidx=i; break
 if endidx is None:
  for i in range(startidx+1,len(rows)):
   ms,_,t=times(rows[i])
   if ms-s_ms>1400000: break
   if any(x in t for x in ('第一天白天','第一天开始')):
    endidx=i; break
 if endidx is None: endidx=min(len(rows)-1,startidx+500)
 e_ms=times(rows[endidx])[1] if endidx<len(rows) else None
 dayend=None
 for r in rows[endidx+1:]:
  ms,en,t=times(r)
  if en-s_ms>2200000: break
  if any(x in t for x in ('入夜','天黑请闭眼','狼人请睁眼')):
   dayend=en; break
 out.append(f'SOURCE {src}\nWINDOW {s_ms}-{e_ms} DAYEND {dayend}')
 selected=[]
 for i in range(startidx,min(endidx+1,len(rows))):
  ms,en,t=times(rows[i])
  if any(k in t for k in terms) or re.search(r'\d+号(?:玩家)?(?:请)?发言',t):
   selected.append((ms,en,t))
 # Add a few surrounding context rows to role/callout lines.
 keep=set()
 for i in range(startidx,min(endidx+1,len(rows))):
  ms,en,t=times(rows[i])
  if any(k in t for k in ('悍跳','预言家','通灵师','我是','我验','验了','金水','查杀','退水','警徽流')):
   keep.update(j for j in range(max(startidx,i-1),min(endidx+1,i+2)))
 out.append('CLAIM CUES '+str(len(keep)))
 for i in sorted(keep):
  ms,en,t=times(rows[i]); out.append(f'[{ms}-{en}] {t}')
Path(f'data/extractions/S22/bluff_review/recheck_c_scan_{lo}_{hi}.txt').write_text('\n'.join(out),encoding='utf-8')
print('wrote',len(out),'lines')
