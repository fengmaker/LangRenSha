import json,pathlib,re
b='BV11uMG6PEkr';f=next(pathlib.Path('data/seasons/S22').rglob('*'+b+'*funasr.json'));d=json.loads(f.read_text(encoding='utf-8-sig'));out=[]
for r in d['segments']:
 s=r['start_ms'];t=r['text']
 if 2200000<=s<=3400000 and re.search(r'发言|请.{0,5}号|过.{0,5}号|八号|8号|预言家|通灵师|悍跳|金水|查杀|自爆|第一天',t):out.append('{}-{} {}'.format(s,r['end_ms'],t))
pathlib.Path('data/extractions/S22/bluff_review/recheck_b_63_after.txt').write_text('\n'.join(out),encoding='utf-8')
