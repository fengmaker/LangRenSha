import json,pathlib
x=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig'))
for i in [2,3,16,19,29,30,46,47]:
 g=x['games'][i-1]; print('\n',i,g['bvid'])
 for a in g['assessments']: print(type(a['seat']),a['seat'],a['physical_role'],a['decision'],a.get('decision_note'))
