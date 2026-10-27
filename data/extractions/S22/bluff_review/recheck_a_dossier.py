import json,pathlib
p=sorted(pathlib.Path('data/games/S22').glob('*/dossier.json'),key=lambda p:str(p))[3];d=json.loads(p.read_text(encoding='utf-8-sig'));print(d['slug']);print(d['files'])
