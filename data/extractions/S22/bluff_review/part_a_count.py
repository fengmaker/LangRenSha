import json
p='data/extractions/S22/bluff_review/part_a.json'; d=json.load(open(p,encoding='utf-8'))
from collections import Counter
c=Counter(a['decision'] for g in d['games'] for a in g['assessments'])
print(c, 'games',len(d['games']),'assessments',sum(c.values()))
