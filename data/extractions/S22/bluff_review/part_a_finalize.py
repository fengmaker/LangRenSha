import json,pathlib
p=pathlib.Path('data/extractions/S22/bluff_review/part_a.json'); d=json.loads(p.read_text(encoding='utf-8-sig'))
a=next(a for a in d['games'][40]['assessments'] if a['seat']==12)
a['evidence']=[e for e in a.get('evidence',[]) if e.get('start_ms')!=741660]
for e in a['evidence']:
 if e.get('start_ms')==1371520: e['interpretation']='12号先自称预言家，紧接着报出第一天验人和警徽流；连续内容确认这是一段完整的预言家发言。'
p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
