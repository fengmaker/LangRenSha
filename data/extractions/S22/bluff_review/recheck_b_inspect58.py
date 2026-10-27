import json,pathlib
b='BV119TJ6pEtC'; fs=list(pathlib.Path('data/seasons/S22').rglob('*'+b+'*funasr.json')); print(fs)
if fs:
 d=json.loads(fs[0].read_text(encoding='utf-8-sig')); print(d.keys()); print(type(d.get('segments')),len(d.get('segments',[]))); print(d.get('segments',[None])[0])
