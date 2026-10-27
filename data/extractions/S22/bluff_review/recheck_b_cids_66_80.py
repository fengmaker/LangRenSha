import json,pathlib
for b in ['BV1hZMp63Esx','BV13ZMp63EEB','BV1GxNH6YESw','BV1GxNH6YEht','BV1VxNH6YETC','BV1YxNH6YEqY','BV1sEN86gEM2','BV1PEN863EXG','BV1WEN86gE1i','BV1WEN86gERp','BV1BPNB6QE1s','BV1BPNB6QE1V']:
 d=json.loads(next(pathlib.Path('data/games/S22').glob('*'+b+'/dossier.json')).read_text(encoding='utf-8'))
 print(b, next((f.get('external_key') for f in d['files'] if f.get('external_key')),None))
