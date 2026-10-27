import json, pathlib, re
ROOT=pathlib.Path('.')
part=json.loads((ROOT/'data/extractions/S22/bluff_review/part_b.json').read_text(encoding='utf-8'))
games=part['games'][15:30]
pat=re.compile(r'(?:(?:过了|过|就请|当前到|轮到|准备|请)?\s*(\d{1,2})\s*号(?:玩家|的)?(?:请发言|发言|开始发言)|(?:由|从)\s*(\d{1,2})\s*号玩家开始发言)')
claim=re.compile(r'预言家|通灵师|悍跳|金水|查杀|警徽流|验了|我验|我是|我底牌|退水')
self_claim=re.compile(r'(我|本人|底牌).{0,8}(预言家|通灵师)|(预言家|通灵师).{0,8}(是我|在下|底牌)|我验|我验的|验人|警徽流')
out=[]
for off,g in enumerate(games,66):
 bvid=g['bvid'];dp=next(pathlib.Path('data/games/S22').glob(f'*{bvid}/dossier.json'));d=json.loads(dp.read_text(encoding='utf-8')); f=next((x for x in d['files'] if x['role']=='subtitle'),None)
 if f: src=f['path']
 else:
  ss=list(pathlib.Path('data/seasons/S22').rglob(f'*{bvid}*funasr.json')) or list(pathlib.Path('data/seasons/S22').rglob(f'*{bvid}*原始.json'))
  if not ss: out.append(f'\n===== {off} {bvid} NO_TRANSCRIPT =====');continue
  src=ss[0].as_posix()
 data=json.loads(pathlib.Path(src).read_text(encoding='utf-8-sig'));rr=data.get('body',data.get('segments',[]))
 rows=[(round(x.get('start_ms',x.get('from',0)*1000)),round(x.get('end_ms',x.get('to',0)*1000)),x.get('text',x.get('content',''))) for x in rr]
 anchors=[]
 for i,(_,_,t) in enumerate(rows):
  m=pat.search(t)
  if m: anchors.append((i,int(next(v for v in m.groups() if v))))
 out.append(f'\n===== {off} {bvid} =====')
 out.append('WOLVES '+','.join(f'{a["seat"]}:{a["decision"]}' for a in g['assessments']))
 out.append('PROMPTS '+' ; '.join(f'{rows[i][0]}:{seat}:{rows[i][2]}' for i,seat in anchors if rows[i][0]<3500000))
 for a in g['assessments']:
  seat=a['seat']; hits_out=[]
  for z,(ix,n) in enumerate(anchors):
   if n!=seat:continue
   iend=anchors[z+1][0] if z+1<len(anchors) else min(len(rows),ix+180)
   turn=rows[ix:iend]
   if not turn or turn[0][0]>=3500000:continue
   ixes=[i for i,row in enumerate(turn) if claim.search(row[2])]
   if not ixes:continue
   if a['decision'] in ('yes','uncertain') or any(self_claim.search(turn[i][2]) for i in ixes):
    keep=set([0])
    for i in ixes:keep.update(range(max(0,i-1),min(len(turn),i+2)))
    hits_out.append((turn,sorted(keep)))
  if a['decision'] in ('yes','uncertain') or hits_out:
   out.append(f'--SEAT {seat} old={a["decision"]}/{a.get("claimed_role")}--')
   for turn,keep in hits_out:
    out.append(f'TURN {turn[0][0]}-{turn[-1][1]}')
    out.extend(f'{turn[i][0]}-{turn[i][1]} {turn[i][2]}' for i in keep)
   if not hits_out:out.append('NO PROMPT TURN CLAIM KEYWORDS FOUND')
pathlib.Path('data/extractions/S22/bluff_review/recheck_b_batch_66_80.txt').write_text('\n'.join(out),encoding='utf-8')
