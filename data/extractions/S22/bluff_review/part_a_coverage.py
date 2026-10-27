import json,pathlib
D=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig'))
for n in [5,6,7,8,9,10,11,43,46,47]:
 g=D['games'][n-1]; print(n,g['bvid'],(pathlib.Path(g['game_dir'])/'复盘原文.txt').exists(),g['coverage'])
