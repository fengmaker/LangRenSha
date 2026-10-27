import json,pathlib
D=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig'))
for i,g in enumerate(D['games'][:50],1):
 for a in g['assessments']:
  if a['decision']!='no':
   print(i,g['bvid'],a['seat'],a['decision'],[(e['kind'],e['start_ms'],e['text']) for e in a.get('evidence',[])])
