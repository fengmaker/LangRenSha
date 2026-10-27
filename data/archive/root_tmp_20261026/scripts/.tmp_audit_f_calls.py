import json, pathlib, re, sys
root=pathlib.Path('.')
b=sys.argv[1]; stop=float(sys.argv[2])
e=json.loads((root/'data/extractions/S23/game_reviews'/b/'entry.json').read_text(encoding='utf-8'))
d=json.loads((root/e['source_path']).read_text(encoding='utf-8'))
rows=d.get('body',d.get('segments',[]))
for i,x in enumerate(rows):
    t=x.get('content',x.get('text',''))
    sec=x.get('from',x.get('start_ms',0)/1000)
    if sec>stop: break
    if re.search(r'\d+号(?:玩家)?请发言|请\d+号(?:玩家)?发言|第一天白天|选择警长|警长竞选|进入警长|警上结束|竞选结束|上警玩家请|玩家发言结束|发言结束|投票|天黑请闭眼|入夜',t):
        print(f'{i} {sec:.2f} {t}')
