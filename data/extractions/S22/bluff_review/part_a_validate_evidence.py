import json,pathlib
root=pathlib.Path('.'); d=json.loads((root/'data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig'))
issues=[]; missing=[]; counts={'yes':0,'no':0,'uncertain':0};
for g in d['games']:
  dossier=json.loads((root/g['game_dir']/'dossier.json').read_text(encoding='utf-8-sig'))
  assessed={a['seat']:a for a in g['assessments']}
  for s in dossier.get('seats',[]):
    if s.get('faction')=='werewolf' and s.get('role')!='混血儿' and s['seat'] not in assessed: missing.append((g['bvid'],s['seat'],s.get('role')))
  for a in g['assessments']:
    counts[a['decision']]+=1
    if a['decision']=='yes' and not a.get('evidence'): issues.append((g['bvid'],a['seat'],'yes_no_evidence'))
    if a['decision']=='no' and not a.get('decision_note'): issues.append((g['bvid'],a['seat'],'no_no_note'))
    for e in a.get('evidence',[]):
      p=root/e['source_path']
      if not p.exists(): issues.append((g['bvid'],a['seat'],'source_missing',e['source_path'])); continue
      text=p.read_text(encoding='utf-8-sig',errors='replace')
      if e['text'] not in text: issues.append((g['bvid'],a['seat'],'quote_not_in_source',e['source_path'],e['start_ms'],e['text']))
print('counts',counts,'games',len(d['games']),'missing_wolf_assessments',missing,'issues',len(issues))
for x in issues[:80]: print(x)
