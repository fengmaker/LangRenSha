import json,pathlib
p=next(pathlib.Path('data/games/S22').glob('*BV1gvTi66E7y/dossier.json'));d=json.loads(p.read_text(encoding='utf-8'))
for s in d['seats']: print(s['seat'],s['name'],s['role'])
