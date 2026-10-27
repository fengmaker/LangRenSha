import json, pathlib, sys
root=pathlib.Path('.'); b=sys.argv[1]; lo=float(sys.argv[2]); hi=float(sys.argv[3])
e=json.loads((root/'data/extractions/S23/game_reviews'/b/'entry.json').read_text(encoding='utf-8'))
d=json.loads((root/e['source_path']).read_text(encoding='utf-8'))
rows=d.get('body',d.get('segments',[]))
for x in rows:
    st=x.get('from',x.get('start_ms',0)/1000); en=x.get('to',x.get('end_ms',0)/1000); t=x.get('content',x.get('text',''))
    if st>=lo and st<hi and t.strip(): print(f'{st:.2f}-{en:.2f} {t}')
