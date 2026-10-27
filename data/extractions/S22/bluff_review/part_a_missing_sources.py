import json,pathlib
ps=sorted(pathlib.Path('data/games/S22').glob('*/dossier.json'),key=lambda p:str(p)); data=json.loads(pathlib.Path('data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig'))
for i in [5,37,43,46,47]:
 d=json.loads(ps[i-1].read_text(encoding='utf-8-sig')); print('\n===',i,d['slug']);
 for f in d.get('files',[]): print(f.get('role'),f.get('path'))
 print('season candidates:'); b=d.get('bvid','');
 for q in pathlib.Path('data/seasons/S22').rglob('*'+d['slug'].split('-')[1]+'*'):
  if q.is_file() and ('funasr' in q.name or '全文' in q.name): print(q.as_posix())

