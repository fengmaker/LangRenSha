import json,pathlib
root=pathlib.Path('.'); d=json.loads((root/'data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig'))
for g in d['games']:
 dossier=json.loads((root/g['game_dir']/'dossier.json').read_text(encoding='utf-8-sig'))
 seats={s['seat']:s for s in dossier.get('seats',[])}
 for a in g['assessments']:
  s=seats.get(a['seat'],{})
  if s.get('faction')!='werewolf': print(g['bvid'],a['seat'],s.get('role'),s.get('faction'),a['decision'])
