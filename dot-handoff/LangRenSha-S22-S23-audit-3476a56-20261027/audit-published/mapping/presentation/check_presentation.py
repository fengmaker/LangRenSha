#!/usr/bin/env python3
"""Offline audit: official JSON -> publication -> presentation; never opens a DB.
Requires the repository's web Python dependencies (not stubbed).
Run: python check_presentation.py --repo PATH --out result.json
Optional --render-input outputs public/presentation copies for check_render.cjs.
"""
from __future__ import annotations
import argparse, json, re, sys, hashlib
from collections import Counter
from copy import deepcopy
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--render-input', type=Path)
    args=parser.parse_args(); root=args.repo.resolve();sys.path.insert(0,str(root))
    from website.api.publisher import load_release, _public_game
    from website.api.analytics import effective_faction
    from website.api.game_presentation import build_game_presentation, _actual_deaths
    entries,source_hash,rules_hash=load_release(root,['S22','S23'])
    names={s['name']:s['name'] for en in entries for s in en['dossier']['seats']}
    output={'schema_version':1,'scope':'Offline committed S22/S23 sources; not live API or original-media verification',
            'source_hash':source_hash,'rules_hash':rules_hash,'counts':{},'findings':{},'coverage':[]}
    findings={k:[] for k in ('badge_lost_wrong_cause','skill_revote_unmapped','post_dq_hunter_inference','post_terminal_day','last_god_hunter_pending','s22_terminal_hunter_pending','s22_puppet_hunter_pending')}
    counts=Counter();render_inputs=[]
    for en in entries:
        d,v=en['dossier'],en['voting']; folder=en['folder']; ident={'game_id':d['slug'],'season':d['season'],'date':d['date'],'game_number':d['game_number'],'bvid':en['bvid'],'source_folder':str(folder.relative_to(root))}
        public=_public_game(d,v,en['endgame'],en['audit'],en['board'],names)
        public['seats']=[{**s,'faction':effective_faction(public,s)} for s in public['seats']]
        before=deepcopy(public);presentation=build_game_presentation(public)
        assert before==public, 'projection mutated input'
        rounds=presentation['rounds'];inferred=[{'round':r['number'],'phase':ph,**e} for r in rounds for ph in ('night','day') for e in r[ph] if e.get('inferred')]
        counts[d['season']+'_games']+=1;counts['inferred_events']+=len(inferred);counts['omitted_events']+=presentation['omitted_events']
        output['coverage'].append({**ident,'rounds':len(rounds),'inferred_events':len(inferred),'omitted_events':presentation['omitted_events'],'input_unchanged':True})
        for e in inferred:
            if e['slot']=='badge' and e['action']=='badge_lost':
                counts['badge_lost_inferences']+=1
                if e['round']==1:
                    findings['badge_lost_wrong_cause'].append({**ident,'presentation_event':e,'registrations':[x for x in v['registrations'] if x['day']==1],
                        'sheriff_ballots':[{k:x.get(k) for k in ('id','day','kind','stage','status','winner','tied_candidates')} for x in v['ballots'] if x['day']==1 and x['kind']=='sheriff'],
                        'source_sheriff_and_badge':[x for r in d['rounds'] if r['number']==1 for x in r['day'] if x['slot'] in ('sheriff_result','badge')]})
        for b in v['ballots']:
            if b['stage']=='revote':findings['skill_revote_unmapped'].append({**ident,'ballot_id':b['id'],'day':b['day'],'stage':b['stage'],'number':b['number'],'kind':b['kind']})
        sp=folder/'supplemental.json';side=json.loads(sp.read_text()) if sp.exists() else {}
        for x in side.get('events',[]):
            e=x.get('event',{});dq_seats=set(e.get('targets') or [])
            if e.get('actor') is not None:dq_seats.add(e['actor'])
            hunters={s['seat'] for s in public['seats'] if s['role']=='猎人'}
            if e.get('action')=='disqualify' and dq_seats&hunters:
                bad=[i for i in inferred if i['slot']=='hunter_state' and i['action']=='can_shoot' and i['round']>x['round'] and i.get('actor') in dq_seats]
                if bad:findings['post_dq_hunter_inference'].append({**ident,'supplemental_event':x,'later_inferences':bad})
        for r in d['rounds']:
            markers=[x for ph in ('night','day') for x in r[ph] if isinstance(x.get('result'),str) and re.search(rf'D{r["number"]}未开始(?!放逐|投票)|未进入D{r["number"]}',x['result'])]
            pr=next((x for x in rounds if x['number']==r['number']),None)
            if markers and pr and pr['day']:
                findings['post_terminal_day'].append({**ident,'round':r['number'],'source_terminal_markers':markers,'presentation_day':pr['day']})
        if d['season']=='S22':
            audit=en.get('audit') or {};terminal=(audit.get('game_flow') or {}).get('terminal') or {}
            pending=[x for x in inferred if x['slot']=='hunter_shot' and x['action']=='unknown']
            for x in pending:
                if terminal.get('phase')=='night' and terminal.get('round')==x['round']:
                    assert audit.get('dossier_sha256')==en['source_hashes']['dossier'], 'S22 terminal audit is not bound to current dossier'
                    rr=next(r for r in rounds if r['number']==x['round'])
                    row={**ident,'round':x['round'],'terminal':terminal,'presentation_event':x,
                         'presentation_day':rr['day'],'source_path':audit.get('source_path'),
                         'source_sha256':audit.get('source_sha256'),'audit_dossier_sha256':audit.get('dossier_sha256'),
                         'rule_source':'data/extractions/S22/用户确认_20261025_存活与终局.txt'}
                    findings['s22_terminal_hunter_pending'].append(row)
                    findings['post_terminal_day'].append({**row,'scope_note':'Existing S22 terminal annotation matched to a pending-hunter day; not a new S23 rule application'})
                if d['board']=='neighbor_puppet':
                    disabled=[{'round':rr['number'],'event':ev} for rr in d['rounds'] if rr['number']<=x['round'] for ph in ('night','day') for ev in rr[ph]
                              if ev.get('slot')=='puppet_skill_effect' and ev.get('action')=='skill_disabled']
                    hunters={ss['seat'] for ss in d['seats'] if ss.get('role')=='猎人'}
                    applicable=[z for z in disabled if hunters & (set(z['event'].get('targets') or []) | {int(n) for n in re.findall(r'(\d+)号',z['event'].get('result') or '')})]
                    if applicable:findings['s22_puppet_hunter_pending'].append({**ident,'round':x['round'],'prior_disabled_events':applicable,'presentation_event':x,
                        'source_path':audit.get('source_path'),'source_sha256':audit.get('source_sha256')})
        if d['season']=='S23' and d['board']=='mixed_blood':
            gods={s['seat'] for s in public['seats'] if s['role'] in {'预言家','女巫','猎人','白神','白痴'}};dead=set()
            for r in rounds:
                dead|=_actual_deaths(r['night']+r['day'])
                pending=[x for x in r['day'] if x.get('slot')=='hunter_shot' and x.get('action')=='unknown' and x.get('inferred') and x.get('actor') in dead]
                if pending and gods and gods<=dead:
                    findings['last_god_hunter_pending'].append({**ident,'round':r['number'],'god_seats':sorted(gods),'known_departed_seats':sorted(dead),'presentation_event':pending[0],
                        'source_departures':[{'round':rr['number'],'phase':ph,'event':x} for rr in d['rounds'] if rr['number']<=r['number'] for ph in ('night','day') for x in rr[ph] if x.get('action') in ('die','exile','shoot','self_destruct')]})
        if any(any(x['game_id']==d['slug'] for x in rows) for rows in findings.values()):
            render_inputs.append({**public,'presentation':presentation})
    output['counts']=dict(counts);output['findings']=findings
    output['code_sha256']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/'website/api/game_presentation.py',root/'website/api/publisher.py',root/'website/web/src/components/event-board.tsx',root/'website/web/src/components/ballot-panel.tsx']}
    rule_path=root/'data/extractions/S22/用户确认_20261025_存活与终局.txt'
    output['established_rule_sha256']={str(rule_path.relative_to(root)):hashlib.sha256(rule_path.read_bytes()).hexdigest()}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    if args.render_input:args.render_input.write_text(json.dumps(render_inputs,ensure_ascii=False)+'\n')
    print(json.dumps({'counts':output['counts'],'finding_rows':{k:len(v) for k,v in findings.items()}},ensure_ascii=False))
if __name__=='__main__':main()
