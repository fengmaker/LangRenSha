import json,pathlib
D=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig')); g=D['games'][7]; d=json.loads((pathlib.Path(g['game_dir'])/'dossier.json').read_text(encoding='utf-8-sig'))
print(g['game_dir'])
for k,v in d.items():
 if any(x in k.lower() for x in ['player','seat','role']): print(k,str(v)[:4000])
