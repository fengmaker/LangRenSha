import json,pathlib
b='BV11uMG6PEkr';d=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_b.json').read_text(encoding='utf-8'));g=next(x for x in d['games'] if x['bvid']==b);o=[]
for a in g['assessments']:
 if a['decision'] in ('yes','uncertain'):o.append(str(a))
pathlib.Path('data/extractions/S22/bluff_review/recheck_b_old63.txt').write_text('\n'.join(o),encoding='utf-8')
