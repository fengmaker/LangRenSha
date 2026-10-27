import json,pathlib,sys,re
root=pathlib.Path('.'); b=sys.argv[1]; hi=float(sys.argv[2])
e=json.loads((root/'data/extractions/S23/game_reviews'/b/'entry.json').read_text(encoding='utf-8'))
d=json.loads((root/e['source_path']).read_text(encoding='utf-8'))
rows=d.get('body',d.get('segments',[]))
for x in rows:
 t=x.get('content',x.get('text','')); st=x.get('from',x.get('start_ms',0)/1000)
 if st<=hi and re.search(r'天黑|入夜|请闭眼|睁眼|公布昨夜|昨夜信息|天亮|第一天白天|第二天白天|警徽流失|结果出来|宣布投票',t): print(f'{st:.2f} {t}')
