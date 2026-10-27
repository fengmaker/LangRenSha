import json,sys,re
from pathlib import Path
KEYS=('预言家','通灵师','悍跳','上警','警上','退水','警徽','验','金水','查验','起跳','跳了','诈身份','反水')
allp=sorted(Path('data/games/S22').glob('*/dossier.json'))
lo,hi=map(int,sys.argv[1:3])
out=[]
for idx in range(lo,hi+1):
 p=allp[idx-1]; d=json.loads(p.read_text(encoding='utf-8')); g=p.parent
 recap=(g/'复盘原文.txt').read_text(encoding='utf-8') if (g/'复盘原文.txt').exists() else ''
 rec=json.loads((g/'复核记录.json').read_text(encoding='utf-8')) if (g/'复核记录.json').exists() else {}
 out += [f'\n===== IDX {idx} {d["slug"]} {d["date"]} G{d["game_number"]} {g.as_posix()} =====', 'WOLVES '+json.dumps([s for s in d['seats'] if s.get('faction')=='werewolf' and s.get('role') not in ('混血儿',)],ensure_ascii=False), 'RECAP\n'+recap]
 srcs=[f['path'] for f in d.get('files',[]) if f.get('role')=='subtitle']
 if not srcs:
  srcs=list(Path('data/seasons/S22').rglob('*'+re.search(r'BV[0-9A-Za-z]{10}',d['slug'])[0]+'*本地全文转写_funasr.json'))
 if not srcs: out.append('NO TRANSCRIPT'); continue
 src=Path(srcs[0]); out.append('TRANSCRIPT '+src.as_posix())
 try:
  x=json.loads(src.read_text(encoding='utf-8-sig')); rows=x.get('body',x.get('segments',[]))
 except Exception as e: out.append('TRANSCRIPT ERROR '+repr(e)); continue
 # Pull early game candidate window, capped to likely first-day election; print hits and immediate neighbors.
 lim=min((rec.get('recap_start_ms') or 1800000)/1000, 1600)
 hit=set()
 for i,row in enumerate(rows):
  t=row.get('content',row.get('text','')); st=row.get('from',row.get('start_ms',0)/1000); en=row.get('to',row.get('end_ms',0)/1000)
  if st>lim: break
  if any(k in t for k in KEYS):
   for j in range(max(0,i-1),min(len(rows),i+2)):
    r=rows[j]; ss=r.get('from',r.get('start_ms',0)/1000)
    if ss<=lim: hit.add(j)
 hit=sorted(hit)
 if len(hit)>100:
  # retain exact role/claim / police hits first; then use chronological order and record cap
  pri=[]
  for i in hit:
   t=rows[i].get('content',rows[i].get('text',''))
   if any(k in t for k in ('我是预言家','我是通灵师','悍跳','金水','验了','警徽流','退水')): pri.append(i)
  keep=set(pri)
  keep.update(hit[:max(0,100-len(keep))]); hit=sorted(keep)
 out.append('KEY HITS lim='+str(lim)+' count='+str(len(hit)))
 for i in hit:
  r=rows[i]; st=r.get('from',r.get('start_ms',0)/1000); en=r.get('to',r.get('end_ms',0)/1000); t=r.get('content',r.get('text',''))
  out.append(f'[{round(st*1000)}-{round(en*1000)}] {t}')
Path('data/extractions/S22/bluff_review/part_e_scan_'+str(lo)+'_'+str(hi)+'.txt').write_text('\n'.join(out),encoding='utf-8')
print('wrote',len(out),'lines')
