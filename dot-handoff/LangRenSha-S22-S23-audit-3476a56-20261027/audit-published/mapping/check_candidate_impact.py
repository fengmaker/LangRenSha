#!/usr/bin/env python3
"""Read-only counterfactual. Never edits formal files. Not media validation.
Current scoped hypothesis supplied by S23 fact auditor: BV1KaaT67Eca seat4
mixed-blood model 12 -> 8; personal faction good -> werewolf. Winner unchanged.
"""
from pathlib import Path
from copy import deepcopy
import argparse,json
from probe_mapping import load

def compact(value):
    if isinstance(value,dict) and 'numerator' in value:
        return {k:value[k] for k in ('numerator','denominator','rate','excluded') if k in value}
    return value

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--output',required=True);args=ap.parse_args()
    root=Path(args.root).resolve();p,a,b,entries,games,meta=load(root)
    entry=next(e for e in entries if e['bvid']=='BV1KaaT67Eca');current=next(g for g in games if g['source']['bvid']==entry['bvid'])
    assert next(s for s in entry['dossier']['seats'] if s['seat']==4)['role']=='混血儿'
    before_entry=deepcopy(entry);before_games=deepcopy(games)
    candidate_entry=deepcopy(entry);d=candidate_entry['dossier'];seat=next(s for s in d['seats'] if s['seat']==4);seat['faction']='werewolf'
    targets=[v for r in d['rounds'] for phase in ('night','day') for v in r[phase] if v['slot']=='mixed_blood_model' and v['action']=='choose' and v['actor']==4]
    assert len(targets)==1 and targets[0]['targets']==[12];targets[0]['targets']=[8]
    ids={s['name']:s['name'] for e in entries for s in e['dossier']['seats']}
    candidate=p._public_game(d,candidate_entry['voting'],candidate_entry['endgame'],candidate_entry['audit'],candidate_entry['board'],ids)
    proposed=[candidate if g['id']==current['id'] else g for g in games]
    before={r['id']:r for r in a.build_leaderboard(games,season='S23')};after={r['id']:r for r in a.build_leaderboard(proposed,season='S23')}
    changes=[]
    for pid,x in before.items():
        diff={k:{'before':compact(x[k]),'after':compact(after[pid][k])} for k in x if compact(x[k])!=compact(after[pid][k])}
        if diff:changes.append({'player':pid,'diff':diff})
    out={'scope':'COUNTERFACTUAL ONLY. Candidate fact correction from S23 auditor; not independently media-verified here; no formal file modified.',
      'baseline':meta,'game_id':current['id'],'date':current['date'],'game_number':current['game_number'],'source_hashes':entry['source_hashes'],
      'proposed_changes':[{'field':'seats[seat=4].faction','before':'good','after':'werewolf'},{'field':'rounds[number=1].night[slot=mixed_blood_model,actor=4].targets','before':[12],'after':[8]}],
      'current_seat4':next(s for s in current['seats'] if s['seat']==4),'unchanged_winner':current['winner'],
      'target8':next(s for s in current['seats'] if s['seat']==8),'target12':next(s for s in current['seats'] if s['seat']==12),
      'leaderboard_changes':changes,
      'bluff_before_after_equal':b.review_items([current],b.load_review('S23'))==b.review_items([candidate],b.load_review('S23')),
      'source_fingerprint_before':b.source_fingerprint(current),'source_fingerprint_after':b.source_fingerprint(candidate),
      'original_unchanged':entry==before_entry and games==before_games}
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
