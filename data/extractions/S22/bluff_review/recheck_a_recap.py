import json,pathlib
D=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig')); g=D['games'][3]; p=pathlib.Path(g['game_dir'])/'复核记录.json'; r=json.loads(p.read_text(encoding='utf-8-sig')); print(g['game_dir'],r.get('recap_start_ms'),r.get('recap_end_ms'))
for x in r.get('recap_segments',[]):
 if 2600000<=x.get('start_ms',0)<=2900000: print(x)
print('issues',r.get('issues'))
