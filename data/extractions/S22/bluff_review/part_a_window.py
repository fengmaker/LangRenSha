import json,pathlib,sys
idx=int(sys.argv[1]); ms=int(sys.argv[2]); w=int(sys.argv[3]); ps=sorted(pathlib.Path('data/games/S22').glob('*/dossier.json'),key=lambda p:str(p)); d=json.loads(ps[idx-1].read_text(encoding='utf-8-sig')); f=next(x for x in d['files'] if x.get('role') in ['subtitle','transcript']); j=json.loads(pathlib.Path(f['path']).read_text(encoding='utf-8-sig')); raw=j.get('body',[]) or j.get('segments',[])
for x in raw:
 a=round(x.get('from',0)*1000) if 'from' in x else x.get('start_ms',0); t=x.get('content',x.get('text',''))
 if ms-w<=a<=ms+w: print(a,repr(t))
