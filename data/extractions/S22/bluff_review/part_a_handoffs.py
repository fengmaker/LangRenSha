import json,pathlib,sys,re
idx=int(sys.argv[1]); ps=sorted(pathlib.Path('data/games/S22').glob('*/dossier.json'),key=lambda p:str(p)); d=json.loads(ps[idx-1].read_text(encoding='utf-8-sig')); f=next(x for x in d['files'] if x.get('role')=='transcript'); j=json.loads(pathlib.Path(f['path']).read_text(encoding='utf-8-sig')); print(d['slug'])
for x in j.get('segments',[]):
 t=x['text'];
 if re.search(r'[零一二三四五六七八九十0-9]+号玩家请发言|随机点数|开始.*发言',t): print(x['start_ms'],repr(t))
