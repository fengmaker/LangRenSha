import json, pathlib
D=pathlib.Path('data/games/S22')
p=next(D.glob('*BV1YmTc6yEFd/dossier.json'))
d=json.loads(p.read_text(encoding='utf-8'))
sf=next(pathlib.Path(f['path']) for f in d['files'] if f['role']=='subtitle')
rows=json.loads(sf.read_text(encoding='utf-8-sig'))['body']
out=pathlib.Path('data/extractions/S22/bluff_review/recheck_b_probe.txt')
out.write_text('\n'.join('{}-{} {}'.format(round(r['from']*1000),round(r['to']*1000),r['content']) for r in rows if 1000000<=r['from']*1000<=1250000),encoding='utf-8')
