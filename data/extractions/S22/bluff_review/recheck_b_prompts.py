import json,pathlib,re
for b in ['BV11uMG6PEkr','BV1KuMG6NEez','BV1suMG6PEYP']:
 fs=list(pathlib.Path('data/seasons/S22').rglob('*'+b+'*funasr.json'))
 if not fs: fs=list(pathlib.Path('data/seasons/S22').rglob('*'+b+'*原始.json'))
 print('GAME',b,'sources',fs)
 if not fs: continue
 d=json.loads(fs[0].read_text(encoding='utf-8-sig')); rows=d.get('segments',d.get('body',[])); out=[]
 for r in rows:
  s=r.get('start_ms',round(r.get('from',0)*1000));e=r.get('end_ms',round(r.get('to',0)*1000));t=r.get('text',r.get('content',''))
  if s<2500000 and re.search(r'发言|请.{0,4}号|过了.{0,5}号|我是预言家|我是通灵师|验.{0,5}[0-9一二三四五六七八九十]+号|警徽流|金水|查杀',t): out.append('{}-{} {}'.format(s,e,t))
 pathlib.Path('data/extractions/S22/bluff_review/recheck_b_'+b+'_prompts.txt').write_text('\n'.join(out),encoding='utf-8')
