import json, pathlib, sys

root=pathlib.Path('.')
review=json.loads((root/'data/extractions/S22/bluff_review/recheck_a.json').read_text(encoding='utf-8'))
base=json.loads((root/'data/extractions/S22/bluff_review/part_a.json').read_text(encoding='utf-8-sig'))
issues=[]; counts={'yes':0,'no':0,'uncertain':0}; outmap={}
for g in review['games']:
    for a in g['assessments']:
        counts[a['decision']]+=1; outmap[(g['bvid'],a['seat'])]=a
        if a['decision']=='yes' and (not a.get('evidence') or a.get('claim_day') not in (1,2) or a.get('first_day_claim') is not True):
            issues.append((g['bvid'],a['seat'],'yes_missing_claim_evidence_or_day'))
        if a['decision']=='no' and not a.get('decision_note'):
            issues.append((g['bvid'],a['seat'],'no_missing_reason'))
        for e in a.get('evidence',[]):
            p=root/e['source_path']
            if not p.exists():
                issues.append((g['bvid'],a['seat'],'source_missing',e['source_path'])); continue
            j=json.loads(p.read_text(encoding='utf-8-sig')); raw=j.get('body',j.get('segments',[])); found=False
            for x in raw:
                if 'from' in x: start=round(float(x.get('from',0))*1000); end=round(float(x.get('to',x.get('from',0)))*1000); text=x.get('content','')
                else: start=int(x.get('start_ms',0)); end=int(x.get('end_ms',start)); text=x.get('text','')
                if start==e['start_ms'] and end==e['end_ms'] and text==e['text']:
                    found=True; break
            if not found: issues.append((g['bvid'],a['seat'],'segment_mismatch',e['source_path'],e['start_ms'],e['end_ms'],e['text']))
        if a['decision']=='uncertain' and a.get('review_questions')==[]:
            issues.append((g['bvid'],a['seat'],'uncertain_missing_question'))
old={(g['bvid'],a['seat']) for g in base['games'] for a in g['assessments'] if a['decision']!='no'}
missing=sorted(old-set(outmap))
print('counts',counts,'games',len(review['games']),'assessments',sum(counts.values()),'old_yes_or_uncertain_missing',missing,'issues',len(issues))
for x in issues: print(x)
if issues or missing: sys.exit(1)
