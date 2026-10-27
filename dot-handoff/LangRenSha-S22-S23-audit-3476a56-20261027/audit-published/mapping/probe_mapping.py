#!/usr/bin/env python3
"""Read-only S22/S23 mapping audit; never connects to a database or changes repo inputs.
Uses the real publisher, analytics and bluffs code; this is NOT a DB/API integration test.
"""
from pathlib import Path
import argparse,collections,json,sys

def load(root):
    sys.path.insert(0,str(root))
    from website.api import publisher
    mode="normal imports"
    from website.api import analytics,bluffs
    entries,source_hash,rules_hash=publisher.load_release(root,['S22','S23'])
    names={s['name']:s['name'] for e in entries for s in e['dossier']['seats']}
    games=[publisher._public_game(e['dossier'],e['voting'],e['endgame'],e['audit'],e['board'],names) for e in entries]
    return publisher,analytics,bluffs,entries,games,{'mode':mode,'source_hash':source_hash,'rules_hash':rules_hash}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--output');args=parser.parse_args()
    p,a,b,E,G,meta=load(Path(args.root).resolve())
    out={'scope':meta,'seasons':{}}
    for season in ['S22','S23']:
        gs=[g for g in G if g['season']==season];items=b.review_items(gs,b.load_review(season))
        out['seasons'][season]={
          'games':len(gs),'seats':sum(len(g['seats']) for g in gs),'winner_counts':dict(collections.Counter(str(g['winner']) for g in gs)),
          'bluff_summary':dict(collections.Counter(str((x['decision'],x['success'],x['claim_day'])) for x in items)),
          'unknown_factions':[{'game':g['id'],'seat':s['seat'],'role':s['role'],'published':s['faction'],'effective':a.effective_faction(g,s)} for g in gs for s in g['seats'] if s['faction'] is None],
          'unknown_roles':[{'game':g['id'],'seat':s['seat']} for g in gs for s in g['seats'] if s['role'] is None],
          'voting_coverage':dict(collections.Counter(str((v['kind'],v.get('eligible_voters') is None,v.get('candidates') is None)) for g in gs for v in g['voting']['ballots'])),
          'bluff_pending':[{'game':x['game_id'],'seat':x['seat'],'questions':x['review_questions']} for x in items if x['needs_review']],
        }
    text=json.dumps(out,ensure_ascii=False,indent=2)
    if args.output: Path(args.output).write_text(text+'\n')
    else: print(text)
