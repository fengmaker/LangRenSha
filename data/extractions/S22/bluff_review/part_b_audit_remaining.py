import json,runpy,re
from pathlib import Path
ns=runpy.run_path('scripts/build_bluff_inference.py'); _,_,summary=ns['build'](allow_partial=True)
part=json.loads(Path('data/extractions/S22/bluff_review/part_b.json').read_text(encoding='utf-8')); ids={g['game_id'] for g in part['games']}; records={g['game_id']:g for g in part['games']}
out=Path('data/extractions/S22/bluff_review/part_b_remaining_issues.txt')
with out.open('w',encoding='utf-8') as w:
 for issue in summary['validation_issues']:
  if issue['game_id'] not in ids: continue
  g=records[issue['game_id']]; a=next(a for a in g['assessments'] if a['seat']==issue['seat']); e=next((e for e in a['evidence'] if e['source_path']==issue['source_path'] and e['start_ms']==issue['start_ms']),None)
  w.write(f"\n### {g['bvid']} seat={a['seat']} role={a['physical_role']} decision={a['decision']}\nSOURCE {issue['source_path']} {issue['start_ms']}-{e['end_ms'] if e else ''}\nQUOTE {e['text'] if e else ''}\n")
  if e:
   for row in ns['source_segments'](e['source_path']):
    if row['end_ms']>=e['start_ms']-1500 and row['start_ms']<=e['end_ms']+1500:
     w.write(f"{row['start_ms']}-{row['end_ms']} {row['text']}\n")
print(out)
