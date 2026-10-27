import json,pathlib,sys
D=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig')); lo=int(sys.argv[1]);hi=int(sys.argv[2])
for n in range(lo,hi+1):
 g=D['games'][n-1]; print('\n',n,g['bvid'])
 for a in g['assessments']:
  if a['decision']!='no':
   print(' seat',a['seat'],a['physical_role'],a['decision'],a['claimed_role'],a['confidence'],'Q=',a.get('review_questions'))
   for e in a.get('evidence',[]): print('  ',e['kind'],e['start_ms'],e['end_ms'],e['text'])
