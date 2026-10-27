#!/usr/bin/env python3
"""Read-only current-data audit: source -> publication -> API pure functions.
Not live service, PostgreSQL, image/video or independent source-media verification.
Uses names as deterministic local person IDs (real DB identity binding is not checked).
"""
from pathlib import Path
import argparse,collections,copy,json,sys
from probe_mapping import load


def inferred_faction(dossier, seat):
    if seat['faction'] is not None: return seat['faction']
    if seat['role']!='混血儿': return None
    events=[v for r in dossier['rounds'] for p in ('night','day') for v in r[p] if v.get('actor')==seat['seat']]
    choices=[v['targets'][0] for v in events if v['slot']=='mixed_blood_model' and v['action']=='choose' and len(v['targets'])==1]
    aligns={ {'good':'good','wolf':'werewolf'}[v['action']] for v in events if v['slot']=='mixed_blood_alignment' and v['action'] in ('good','wolf') }
    if not choices or len(set(choices))!=1 or len(aligns)>1: return None
    target=next((s for s in dossier['seats'] if s['seat']==choices[0]),{})
    f=target.get('faction')
    return f if f in ('good','werewolf') and (not aligns or f in aligns) else None


def blank():
    return {'appearances':0,'wins':0,'losses':0,'pending_games':0,'points_half':0,'werewolf_appearances':0,'exile_abstentions':0,
     'metrics':{k:[0,0] for k in ('total_win_rate','good_win_rate','werewolf_win_rate','werewolf_draw_rate','werewolf_self_explosion_rate','sheriff_registration_rate','werewolf_sheriff_registration_rate','wolf_vote_rate','seer_follow_rate','sheriff_seer_vote_rate')}}


def add(acc,key,success):
    acc['metrics'][key][0]+=int(success);acc['metrics'][key][1]+=1


def run(root):
    p,a,b,E,G,meta=load(root)
    from website.api.app import _resolved_snapshot,_summary
    from website.api.bluff_store import _validate_review
    snapshot_before=copy.deepcopy(G)
    byseason={s:collections.defaultdict(blank) for s in ('S22','S23')}
    checks=[];derived=[];differences=[];unused_results=[];default_basis_loss=[];result_conflicts=[];null_results=[]
    for e,g in zip(E,G):
        d,v,z=e['dossier'],e['voting'],e['endgame'];resolved=_resolved_snapshot(g)
        report={'season':g['season'],'date':g['date'],'game_number':g['game_number'],'game_id':g['id'],'bvid':g['source']['bvid'],'folder':str(e['folder'].relative_to(root)), 'source_hashes':e['source_hashes'], 'seats':len(d['seats']),'source_rounds':len(d['rounds']),'published_rounds':len(g['rounds']),'ballots':len(v['ballots']),'votes':sum(len(x['votes']) for x in v['ballots']),'checks':[]}
        def check(label,condition):
            report['checks'].append({'check':label,'ok':bool(condition)})
            if not condition: differences.append({'game':g['id'],'check':label})
        check('identity_role_learning_fields_exact', all(all(ps[k]==s.get(k) for k in ('seat','name','role','learning_target','learned_role')) for s,ps in zip(d['seats'],g['seats'])))
        check('source_faction_retained_in_snapshot',all(x['faction']==s['faction'] for s,x in zip(d['seats'],g['seats'])))
        check('date_phase_game_winner_exact',all(d.get(k)==g.get(k) for k in ('date','season','phase','game_number','winner')))
        check('ballots_and_votes_exact_except_public_basis',all(all(x.get(k)==y.get(k) for k in p.BALLOT_FIELDS if k!='votes') and [{k:q[k] for k in ('voter','target','state') if k in q} for q in x['votes']]==[{k:q[k] for k in ('voter','target','state') if k in q} for q in y['votes']] for x,y in zip(v['ballots'],g['voting']['ballots'])))
        check('registrations_exact',v['registrations']==g['voting']['registrations'])
        check('endgame_public_fields_exact', [{k:ph[k] for k in p.ENDGAME_FIELDS if k in ph} for ph in z['phases']]==g['endgame']['phases'])
        check('all_recorded_votes_have_recorded_eligibility',all(q['voter'] in x['eligible_voters'] for x in v['ballots'] for q in x['votes']))
        check('no_duplicate_voter_in_round',all(len({q['voter'] for q in x['votes']})==len(x['votes']) for x in v['ballots']))
        check('one_person_one_seat',len({s['name'] for s in d['seats']})==len(d['seats']))
        check('resolved_faction_matches_independent_source_resolver',all(inferred_faction(d,s)==r['faction'] for s,r in zip(d['seats'],resolved['seats'])))
        f={s['seat']:inferred_faction(d,s) for s in d['seats']};info=[s['seat'] for s in d['seats'] if s['role'] in ('预言家','通灵师')]
        reg=min(v['registrations'],key=lambda x:(x['day'],x['id'])) if v['registrations'] else None
        exploded={x['actor'] for r in d['rounds'] for phase in ('night','day') for x in r[phase] if x['action']=='self_destruct'}
        for s in d['seats']:
            acc=byseason[g['season']][s['name']];n=s['seat'];faction=f[n];acc['appearances']+=1
            if s['faction'] is None:
                ev=[{'round':r['number'],'phase':phase,'event':x} for r in d['rounds'] for phase in ('night','day') for x in r[phase] if x['actor']==n and x['slot'] in ('mixed_blood_model','mixed_blood_alignment')]
                derived.append({'game_id':g['id'],'date':g['date'],'seat':n,'name':s['name'],'role':s['role'],'source_faction':None,'effective_faction':faction,'formal_evidence_events':ev,'source_file':str(e['folder'].relative_to(root)/'dossier.json')})
            if faction in ('good','werewolf'):
                add(acc,'werewolf_draw_rate',faction=='werewolf')
                if faction=='werewolf':
                    acc['werewolf_appearances']+=1;add(acc,'werewolf_self_explosion_rate',n in exploded)
                if d['winner'] in ('good','werewolf'):
                    win=faction==d['winner'];acc['wins' if win else 'losses']+=1
                    add(acc,'total_win_rate',win);add(acc,faction+'_win_rate',win)
                    acc['points_half']+= (3 if faction=='werewolf' else 2) if win else -2
                else: acc['pending_games']+=1
            else: acc['pending_games']+=1
            if reg and n in reg['on_police']+reg['off_police']:
                add(acc,'sheriff_registration_rate',n in reg['on_police'])
                if faction=='werewolf':add(acc,'werewolf_sheriff_registration_rate',n in reg['on_police'])
            for ballot in v['ballots']:
                elig=ballot['eligible_voters'];votes={q['voter']:q for q in ballot['votes']};q=votes.get(n)
                if ballot['kind']=='exile':
                    if faction=='good' and q and q['state']=='abstained' and (elig is None or n in elig):acc['exile_abstentions']+=1
                    if elig is None or n not in elig or faction!='good':continue
                    if q and q['state']=='abstained':add(acc,'wolf_vote_rate',False)
                    elif q and q['state']=='cast' and f.get(q['target']) in ('good','werewolf'):add(acc,'wolf_vote_rate',f[q['target']]=='werewolf')
                    if len(info)==1 and info[0] in elig and s['role'] not in ('预言家','通灵师'):
                        iq=votes.get(info[0])
                        if iq and iq['state']=='cast' and iq['target'] is not None and q:
                            add(acc,'seer_follow_rate',q['state']=='cast' and q['target']==iq['target'])
                elif ballot['kind']=='sheriff' and faction=='good' and s['role']!='预言家' and elig is not None and n in elig and len(info)==1:
                    candidate=(info[0] in ballot['candidates']) if ballot['candidates'] is not None else any(x['state']=='cast' and x['target']==info[0] for x in ballot['votes'])
                    if candidate and q:add(acc,'sheriff_seer_vote_rate',q['state']=='cast' and q['target']==info[0])
        for ballot in v['ballots']:
            public_ballot=next(x for x in g['voting']['ballots'] if x['id']==ballot['id'])
            for q in ballot['votes']:
                if '默认弃票' in str(q.get('basis','')):
                    public_vote=next(x for x in public_ballot['votes'] if x['voter']==q['voter'])
                    if public_vote.get('basis')!='rule_default':
                        default_basis_loss.append({'game_id':g['id'],'date':g['date'],'game_number':g['game_number'],'source':str(e['folder'].relative_to(root)/'voting.json'),'ballot':ballot['id'],'day':ballot['day'],'kind':ballot['kind'],'source_vote':q,'published_vote':public_vote})
            if 'result' in ballot:unused_results.append({'game':g['id'],'ballot_id':ballot['id'],'source_result':ballot['result'],'published_has_result':'result' in next(x for x in g['voting']['ballots'] if x['id']==ballot['id'])})
        for r in g['rounds']:
            for kind,slot,action in [('exile','exile_result','exile'),('sheriff','sheriff_result','elected')]:
                events=[x for x in r['day'] if x['slot']==slot and x['action']==action]
                ballots=[x for x in g['voting']['ballots'] if x['day']==r['number'] and x['kind']==kind]
                if len(events)!=1 or not ballots:continue
                final=sorted(ballots,key=lambda x:x['number'])[-1]
                detail={'game_id':g['id'],'date':g['date'],'day':r['number'],'kind':kind,'ballot':final['id'],'ballot_winner':final['winner'],'dossier_targets':events[0]['targets']}
                if final['winner'] is None:null_results.append(detail)
                elif [final['winner']]!=events[0]['targets']:result_conflicts.append(detail)
        checks.append(report)
    aggregates={}
    for season,expected in byseason.items():
        gs=[g for g in G if g['season']==season];actual={r['name']:r for r in a.build_leaderboard(G,season=season)}
        for name,x in expected.items():
            y=actual[name]
            for k in ('appearances','wins','losses','pending_games','werewolf_appearances','exile_abstentions'):
                if x[k]!=y[k]:differences.append({'season':season,'name':name,'field':k,'expected':x[k],'actual':y[k]})
            if x['points_half']/2!=y['points']:differences.append({'season':season,'name':name,'field':'points'})
            for k,(num,den) in x['metrics'].items():
                if (num,den)!=(y[k]['numerator'],y[k]['denominator']):differences.append({'season':season,'name':name,'metric':k,'expected':[num,den],'actual':y[k]})
                expected_rate=num/den if den else None
                if expected_rate!=y[k]['rate']:differences.append({'season':season,'name':name,'metric':k,'field':'rate'})
        items,summary=_validate_review(gs,b.load_review(season),season,len(gs))
        aggregates[season]={'players':len(expected),'formula_differences':sum(x.get('season')==season for x in differences),'totals':{k:sum(x[k] for x in expected.values()) for k in ('appearances','wins','losses','pending_games','points_half','werewolf_appearances','exile_abstentions')},'metric_totals':{k:[sum(x['metrics'][k][i] for x in expected.values()) for i in (0,1)] for k in blank()['metrics']},'bluff_validation':summary,'later_claims':[x for x in items if x['decision']=='yes' and x['claim_day']!=1]}
    return {'meta':meta,'scope':'S22/S23 formal files and local pure API functions, not production API/media verification','source_snapshot_not_mutated':G==snapshot_before,'per_game_checks':checks,'derived_mixed_blood_factions':derived,'aggregate_checks':aggregates,'differences':differences,'ballot_results_not_published':unused_results,'default_vote_basis_loss':default_basis_loss,'final_vote_result_conflicts':result_conflicts,'null_vote_result_not_contradiction':null_results}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--output',required=True);parser.add_argument('--render-input');args=parser.parse_args()
    result=run(Path(args.root).resolve());Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if args.render_input:
        *_,games,_=load(Path(args.root).resolve())
        Path(args.render_input).write_text(json.dumps([g for g in games if g['source']['bvid'] in {'BV1gBhn6dE5c','BV1UNaQ6kEWR','BV1iDGK61E1c'}],ensure_ascii=False)+'\n')
    print(json.dumps({'games':len(result['per_game_checks']),'semantic_formula_differences':len(result['differences']),'source_immutable':result['source_snapshot_not_mutated'],'derived_mixed_blood':len(result['derived_mixed_blood_factions']),'default_vote_basis_loss_count':len(result['default_vote_basis_loss']),'final_vote_result_conflict_count':len(result['final_vote_result_conflicts']),'aggregate_checks':result['aggregate_checks']},ensure_ascii=False,indent=2))
