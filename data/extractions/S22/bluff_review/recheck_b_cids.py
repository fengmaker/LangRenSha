import json,pathlib
ids=['BV1gvTi66E7y','BV1BjMh63EEK','BV1BjMh63EDf','BV1KuMG6NEez']
for b in ids:
 d=json.loads(next(pathlib.Path('data/games/S22').glob('*'+b+'/dossier.json')).read_text(encoding='utf-8'))
 print(b,[(f.get('role'),f.get('external_key')) for f in d['files']])
