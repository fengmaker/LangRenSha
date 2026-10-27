import json,pathlib,re
b='BV119TJ6pEtC'; f=next(pathlib.Path('data/seasons/S22').rglob('*'+b+'*funasr.json')); d=json.loads(f.read_text(encoding='utf-8-sig')); out=[]
for r in d['segments']:
 s=r['start_ms'];t=r['text']
 if s<2400000 and re.search(r'号|预言家|通灵师|悍跳|金水|查杀|警徽|发言|退水|我是',t): out.append('{}-{} {}'.format(s,r['end_ms'],t))
p=pathlib.Path('data/extractions/S22/bluff_review/recheck_b_58_window.txt');p.write_text('\n'.join(out),encoding='utf-8')
