import json,pathlib,re
ROOT=pathlib.Path('.');part=json.loads((ROOT/'data/extractions/S22/bluff_review/part_b.json').read_text(encoding='utf-8')); out=[]
pat=re.compile(r'(?:(?:过了|过|就请|当前到|轮到|准备|请)?\s*(\d{1,2})\s*号(?:玩家|的)?(?:请发言|发言|开始发言)|(?:由|从)(\d{1,2})号玩家开始发言)')
key=re.compile('预言家|通灵师|悍跳|金水|查杀|警徽流|退水|验了|我是')
for n,g in enumerate(part['games'][15:30],66):
 d=json.loads(next(pathlib.Path('data/games/S22').glob(f'*{g["bvid"]}/dossier.json')).read_text(encoding='utf-8'))
 f=next((f for f in d['files'] if f['role'] in ('subtitle','transcript')),None)
 if not f:
  continue
 src=pathlib.Path(f['path']); dat=json.loads(src.read_text(encoding='utf-8-sig')); rr=dat.get('body',dat.get('segments',[]))
 rows=[(round(x.get('start_ms',x.get('from',0)*1000)),round(x.get('end_ms',x.get('to',0)*1000)),x.get('text',x.get('content',''))) for x in rr]
 anchors=[]
 for i,(_,_,t) in enumerate(rows):
  m=pat.search(t)
  if m: anchors.append((i,int(m.group(1) or m.group(2))))
 out.append(f'\n=== {n} {g["bvid"]} source={src} ===')
 for j,(ix,seat) in enumerate(anchors):
  en=anchors[j+1][0] if j+1<len(anchors) else min(len(rows),ix+150)
  turn=rows[ix:en]
  if turn and turn[0][0]<3500000 and any(key.search(t) for _,_,t in turn):
   if 1 <= seat <= len(d['seats']) and d['seats'][seat-1]['faction']=='werewolf':
    out.append(f'--WOLF SEAT {seat} {turn[0][0]}-{turn[-1][1]}--')
    for k,(a,b,t) in enumerate(turn):
     if key.search(t):
      out.extend(f' {rows[z][0]}-{rows[z][1]} {rows[z][2]}' for z in range(max(ix,k+ix-2),min(en,k+ix+3)))
 out.append('BOUNDARY '+repr([(a,t) for a,b,t in rows if any(x in t for x in ['天黑请闭眼','第二天','警上发言'])][:8]))
pathlib.Path('data/extractions/S22/bluff_review/recheck_b_scan_66_80.txt').write_text('\n'.join(out),encoding='utf-8')

