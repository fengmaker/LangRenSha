import json, pathlib, re
ROOT=pathlib.Path('.')
part=json.loads((ROOT/'data/extractions/S22/bluff_review/part_b.json').read_text(encoding='utf-8'))
games=part['games'][0:15]
pat=re.compile(r'(?:(?:过了|过|就请|当前到|轮到)?\s*(\d{1,2})\s*号(?:玩家|的)?请发言|请\s*(\d{1,2})\s*号(?:玩家)?发言|(?:由|从)\s*(\d{1,2})\s*号玩家开始发言)')
kw=re.compile(r'预言家|通灵师|悍跳|金水|查杀|警徽流|验了|我验|我是|我底牌|退水')
out=[]
for off,g in enumerate(games,51):
    bvid=g['bvid']; dp=next(pathlib.Path('data/games/S22').glob(f'*{bvid}/dossier.json'))
    d=json.loads(dp.read_text(encoding='utf-8')); f=next((x for x in d['files'] if x['role']=='subtitle'),None)
    if f: src=f['path']
    else:
        ss=list(pathlib.Path('data/seasons/S22').rglob(f'*{bvid}*原始.json'))
        if not ss: ss=list(pathlib.Path('data/seasons/S22').rglob(f'*{bvid}*funasr.json'))
        if not ss: out.append(f'\n===== {off} {bvid} NO_TRANSCRIPT ====='); continue
        src=ss[0].as_posix()
    data=json.loads(pathlib.Path(src).read_text(encoding='utf-8-sig')); rr=data.get('body',data.get('segments',[]))
    rows=[(round(x.get('start_ms',x.get('from',0)*1000)),round(x.get('end_ms',x.get('to',0)*1000)),x.get('text',x.get('content',''))) for x in rr]
    anchors=[]
    for i,(_,_,t) in enumerate(rows):
        m=pat.search(t)
        if m: anchors.append((i,int(next(v for v in m.groups() if v))))
    out.append(f'\n===== {off} {bvid} =====')
    cands=[a for a in g['assessments'] if a['decision'] in ('yes','uncertain')]
    out.append('CANDS '+','.join(f'{a["seat"]}:{a["decision"]}' for a in cands))
    out.append('PROMPTS '+ ' ; '.join(f'{rows[i][0]}:{seat}:{rows[i][2]}' for i,seat in anchors if rows[i][0]<3500000))
    for a in cands:
        seat=a['seat']; out.append(f'--SEAT {seat}--')
        turn_found=False
        for z,(ix,n) in enumerate(anchors):
            if n!=seat: continue
            iend=anchors[z+1][0] if z+1<len(anchors) else min(len(rows),ix+180)
            turn=rows[ix:iend]
            if not turn or turn[0][0]>=3500000: continue
            hits=[i for i,row in enumerate(turn) if kw.search(row[2])]
            if not hits: continue
            turn_found=True
            keep=set([0])
            for i in hits: keep.update(range(max(0,i-1),min(len(turn),i+2)))
            out.append(f'TURN {turn[0][0]}-{turn[-1][1]}')
            out.extend(f'{turn[i][0]}-{turn[i][1]} {turn[i][2]}' for i in sorted(keep))
        if not turn_found:
            out.append('NO DIRECT CLAIM KEYWORDS IN EXACT PROMPT TURN')
            hits=[i for i,row in enumerate(rows) if row[0]<3500000 and kw.search(row[2]) and (f'{seat}号' in row[2] or '我是' in row[2] or '我验' in row[2])]
            out.extend('MENTION '+f'{rows[i][0]}-{rows[i][1]} {rows[i][2]}' for i in hits[:20])
pathlib.Path('data/extractions/S22/bluff_review/recheck_b_batch_51_65.txt').write_text('\n'.join(out),encoding='utf-8')
