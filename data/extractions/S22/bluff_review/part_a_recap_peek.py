import json,pathlib,sys
D=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig')); ns=list(map(int,sys.argv[1:]))
for n in ns:
 g=D['games'][n-1]; p=pathlib.Path(g['game_dir'])/'复盘原文.txt'; print('\n===',n,g['bvid']); print(p.read_text(encoding='utf-8-sig')[:5000])
