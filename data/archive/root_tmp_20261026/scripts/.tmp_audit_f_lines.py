import json, pathlib, sys
root=pathlib.Path('.')
b=sys.argv[1];lo=float(sys.argv[2]);hi=float(sys.argv[3])
e=json.loads((root/'data/extractions/S23/game_reviews'/b/'entry.json').read_text(encoding='utf-8'))
d=json.loads((root/e['source_path']).read_text(encoding='utf-8'))
rows=d.get('body',d.get('segments',[]))
for x in rows:
 t=x.get('content',x.get('text','')); st=x.get('from',x.get('start_ms',0)/1000)
 if lo<=st<hi and ('发言' in t or '号玩家' in t and ('过了' in t or '请' in t)):
  print(f'{st:.2f} {t}')
