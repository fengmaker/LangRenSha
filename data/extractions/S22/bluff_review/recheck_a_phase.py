import json,pathlib,re,sys
D=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig'))
pat=re.compile(r'天亮|天黑|入夜|夜晚降临|夜幕|游戏结束|投票结束|自爆|警徽流失|开始投票|准备投票|自由投票|公投|结束退水')
for i in map(int,sys.argv[1:]):
 g=D['games'][i-1]; d=json.loads(pathlib.Path(g['game_dir']+'/dossier.json').read_text(encoding='utf-8-sig')); f=next((x for x in d['files'] if x.get('role')=='subtitle'),None) or next((x for x in d['files'] if x.get('role')=='transcript'),None)
 j=json.loads(pathlib.Path(f['path']).read_text(encoding='utf-8-sig')); raw=j.get('body',j.get('segments',[])); arr=[]
 for x in raw:
  a=round(float(x.get('from',0))*1000) if 'from' in x else int(x.get('start_ms',0)); t=x.get('content',x.get('text',''))
  if a>3500000: break
  if pat.search(t): arr.append((a,t))
 print('\n',i,g['bvid']);print(' | '.join(f'{a}:{t}' for a,t in arr[:35]))
