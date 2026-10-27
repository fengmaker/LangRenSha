import json,pathlib
p=sorted(pathlib.Path('data/games/S22').glob('*/dossier.json'),key=lambda p:str(p))[0]; d=json.loads(p.read_text(encoding='utf-8-sig')); print('dossier',d.keys()); print('slug',d.get('slug')); print('seats',d.get('seats')); print('files',[(x.get('role'),x.get('path')) for x in d.get('files',[])]); print('voting',d.get('voting'))
for q in pathlib.Path('data/games/S22').glob('*/复核记录.json'):
 j=json.loads(q.read_text(encoding='utf-8-sig')); print('review',q,j.keys()); print('sample',str(j)[:1000]); break
