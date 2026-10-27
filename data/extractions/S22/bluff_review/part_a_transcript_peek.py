import json,pathlib
ps=sorted(pathlib.Path('data/games/S22').glob('*/dossier.json'),key=lambda p:str(p))
for i in [5,37,43]:
 d=json.loads(ps[i-1].read_text(encoding='utf-8-sig')); f=next(x for x in d['files'] if x.get('role')=='transcript'); j=json.loads(pathlib.Path(f['path']).read_text(encoding='utf-8-sig')); print('\n',i,'duration',j.get('audio_duration_ms'),'full',j.get('full_audio_processed'),'judge',j.get('judge_speakers'))
 segments=j.get('segments',[])
 for s in segments:
  t=s['text'];
  if any(q in t for q in ['号玩家请发言','玩家开始正式发言','随机点数']): print(s)
