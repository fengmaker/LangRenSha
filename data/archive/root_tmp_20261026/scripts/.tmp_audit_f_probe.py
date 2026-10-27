import json, pathlib, re
root=pathlib.Path('.')
ids=['BV1RPaW6zEg8','BV1V8af6zE56','BV1V8af6zEtX','BV1V8af6zE5T','BV1D2ak6XExH','BV1D2ak6XEji','BV1D2ak6XEMa','BV1N3aQ6zEXr']
for b in ids:
    e=json.loads((root/'data/extractions/S23/game_reviews'/b/'entry.json').read_text(encoding='utf-8'))
    d=json.loads((root/e['source_path']).read_text(encoding='utf-8'))
    rows=d.get('body',d.get('segments',[]))
    print('\n###',b)
    for x in rows:
        t=x.get('content',x.get('text',''))
        sec=x.get('from',x.get('start_ms',0)/1000)
        if re.search(r'\d+号玩家请发言|请\d+号.*发言|第一天白天|选择警长|警长竞选|进入警长|警上结束|竞选结束|上警|警徽',t) and sec<3000:
            print(f'{sec:.2f} {t}')
