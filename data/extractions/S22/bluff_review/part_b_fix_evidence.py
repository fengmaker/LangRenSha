import json,os,tempfile
from pathlib import Path
p=Path('data/extractions/S22/bluff_review/part_b.json'); d=json.loads(p.read_text(encoding='utf-8'))
for g in d['games']:
 if g['bvid']=='BV1RGgx6xEP9':
  a=next(a for a in g['assessments'] if a['seat']==10)
  a['evidence'][0]['text']='五号狼人通灵师茶叶十二号……玩家为平民身份'
fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='part_b.',suffix='.tmp')
with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f: json.dump(d,f,ensure_ascii=False,indent=2); f.write(chr(10))
os.replace(tmp,p)
