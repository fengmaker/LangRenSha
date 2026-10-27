import json,pathlib
b='BV1gvTi66E7y'
d=json.loads(next(pathlib.Path('data/games/S22').glob('*'+b+'/dossier.json')).read_text(encoding='utf-8'))
sf=next(pathlib.Path(f['path']) for f in d['files'] if f['role']=='subtitle')
rows=json.loads(sf.read_text(encoding='utf-8-sig'))['body']
o=pathlib.Path('data/extractions/S22/bluff_review/recheck_b_game55_300_700.txt')
o.write_text('\n'.join('{}-{} {}'.format(round(x['from']*1000),round(x['to']*1000),x['content']) for x in rows if 300<=x['from']<=700),encoding='utf-8')
