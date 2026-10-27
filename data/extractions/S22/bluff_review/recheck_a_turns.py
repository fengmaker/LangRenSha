import json, pathlib, re, sys

root = pathlib.Path('.')
pa = json.loads((root/'data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig'))
lo, hi = map(int, sys.argv[1:3])
prompt = re.compile(r'(?:过了?|轮到)?\s*([0-9一二三四五六七八九十]+)号玩家?(?:请发言|发言准备|发言|开始发言)')
claim = re.compile(r'我是.{0,8}(?:预言家|通灵师)|我(?:就是|本来是|底牌是).{0,8}(?:预言家|通灵师)|(?:预言家|通灵师).{0,12}(?:我|验|金水|查杀)|我.{0,12}(?:验了|验的|查杀|金水|警徽流|警徽票)|起跳.{0,6}(?:预言家|通灵师)|跳.{0,6}(?:预言家|通灵师)')
nums={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
def toint(s):
    try:return int(s)
    except:return nums.get(s)

for i,g in enumerate(pa['games'][lo-1:hi],lo):
    p=root/g['game_dir']; d=json.loads((p/'dossier.json').read_text(encoding='utf-8-sig'))
    f=next((x for x in d.get('files',[]) if x.get('role')=='subtitle'),None) or next((x for x in d.get('files',[]) if x.get('role')=='transcript'),None)
    if not f: continue
    j=json.loads((root/f['path']).read_text(encoding='utf-8-sig')); raw=j.get('body',j.get('segments',[])); arr=[]
    for x in raw:
        if 'from' in x:a=round(float(x.get('from',0))*1000);b=round(float(x.get('to',x.get('from',0)))*1000);t=x.get('content','')
        else:a=int(x.get('start_ms',0));b=int(x.get('end_ms',a));t=x.get('text','')
        arr.append((a,b,t))
    # First-day edge from recap, when available: the first 入夜/第二天 after 第一天白天.
    rp=p/'复核记录.json'; rs=json.loads(rp.read_text(encoding='utf-8-sig')).get('recap_segments',[]) if rp.exists() else []
    dayend=None; in_day=False
    for x in rs:
        t=x.get('text','')
        if '第一天白天' in t: in_day=True
        if in_day and any(k in t for k in ('入夜','第二天','第二日')):
            dayend=int(x.get('start_ms',0)); break
    # If recap edge unavailable, use the second 天亮 cue; retain null when ambiguous.
    if dayend is None:
        days=[a for a,b,t in arr if '天亮' in t]
        if len(days)>1: dayend=days[1]
    roster={s['seat']:(s['name'],s.get('role')) for s in d['seats'] if s.get('faction')=='werewolf'}
    old=[a for a in g['assessments'] if a['decision']!='no']
    print(f'\n=={i} {g["bvid"]} end={dayend} wolves={roster} old={[(a["seat"],a["decision"]) for a in old]}')
    active=None; start=0; turns=[]
    for a,b,t in arr:
        m=prompt.search(t)
        if m:
            if active is not None: turns.append((active,start,a,buf))
            active=toint(m.group(1)); start=a; buf=[]
        if active is not None and (dayend is None or a <= dayend):
            buf.append((a,b,t))
        if dayend is not None and a>dayend: break
    if active is not None: turns.append((active,start,arr[-1][1],buf))
    for seat,st,en,buf in turns:
        hits=[x for x in buf if claim.search(x[2])]
        if hits:
            excerpt=' | '.join(f'{a}:{t}' for a,b,t in hits)
            print(f' turn seat={seat} {st}-{en}: {excerpt}')
