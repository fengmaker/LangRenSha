"""Expose phase summaries and chronology issues for primary semantic review."""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import s21_phase_review as p


def audit(value):
    warnings = []
    dead = set()
    events = value['events']
    allowed_actors = {
        'guard': {'守卫','机械狼','盗宝大师'}, 'save': {'女巫','机械狼','盗宝大师'},
        'poison': {'女巫','毒师','机械狼','盗宝大师'},
        'investigate': {'预言家','通灵师','机械狼','盗宝大师'},
        'choose_model': {'混血儿'}, 'learn': {'机械狼'}, 'learned_form': {'机械狼'},
        'dream': {'摄梦人','机械狼','盗宝大师'}, 'dance': {'舞者'},
        'wear_mask': {'假面'}, 'exchange': {'魔术师','诡术师','机械狼','盗宝大师'},
    }
    for e in events:
        effective_role = e.get('details', {}).get('effective_role')
        explicit_form_basis = e.get('details', {}).get('form_evidence_indices')
        known_temporary_ability = effective_role in allowed_actors.get(e['action'], set()) and bool(explicit_form_basis)
        if e['actor'] is not None and e['action'] in allowed_actors and e['actor_physical_role'] not in allowed_actors[e['action']] and not known_temporary_ability:
            warnings.append({'kind':'actor_physical_role_mismatch','event_id':e['event_id'],
                             'actor':e['actor'],'role':e['actor_physical_role'],'action':e['action'],
                             'quote':e['evidence'][0]['quote']})
    chinese = {'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'十一':11,'十二':12}
    for ballot in value['ballots']:
        for vote in ballot['votes']:
            literal = ''.join(ev['quote'] for ev in vote['evidence'])
            literal = re.sub(r'\s+', '', literal)
            literal = re.sub(r'十([12])号', lambda m: str(10+int(m[1]))+'号', literal)
            literal = re.sub(r'^321(?=\d+号)', '', literal)
            literal = re.sub(r'(十二|十一|十|[一二两三四五六七八九])号', lambda m: str(chinese[m[1]])+'号', literal)
            pairs = {(int(m[1]),int(m[2])) for m in re.finditer(
                r'(?<!\d)(?=(\d+)号(?:玩家)?投(?:票)?给(\d+)号)', literal)}
            if pairs and vote['state']=='cast' and (vote['voter'],vote['target']) not in pairs:
                # Grouped declarations such as 8号11号投给12号 are checked as a group.
                grouped = re.search(r'((?:\d+号[、和与及,，]*)+)投(?:票)?给(\d+)号', literal)
                group_ok = bool(grouped and vote['voter'] in [int(n) for n in re.findall(r'(\d+)号', grouped[1])]
                                and vote['target']==int(grouped[2]))
                if not group_ok:
                    warnings.append({'kind':'vote_literal_pair_mismatch','ballot_id':ballot['ballot_id'],
                                     'voter':vote['voter'],'target':vote['target'],'literal':literal})
    rounds = sorted({e['round'] for e in events if e['round'] is not None})
    by_phase = defaultdict(list)
    for e in events: by_phase[e['round'],e['phase']].append(e)
    for number in rounds:
        night = by_phase[number,'night']
        for e in night:
            if e['actor'] in dead and e['state'] == 'performed':
                warnings.append({'kind':'night_actor_previously_departed','event_id':e['event_id'],
                                 'actor':e['actor'],'night':number,'quote':e['evidence'][0]['quote']})
        new = {s for e in night if e['action']=='night_deaths' and e['state']=='performed' for s in e['targets']}
        repeated = new & dead
        if repeated:
            warnings.append({'kind':'night_death_repeats_departed_player','night':number,'seats':sorted(repeated)})
        dead.update(new)
        # Sheriff votes can precede the announcement of the latest night's deaths.
        for ballot in value['ballots']:
            if ballot['day'] == number and ballot['type']=='exile':
                departed_voters = {v['voter'] for v in ballot['votes']} & dead
                if departed_voters:
                    warnings.append({'kind':'exile_votes_by_previously_departed','ballot_id':ballot['ballot_id'],'seats':sorted(departed_voters)})
        poisoned_targets = {s for n in night if n['action']=='poison' and n['state']=='performed' for s in n['targets']}
        for e in by_phase[number,'day']:
            departure = set(e['targets']) if e['action'] in {'exile','shoot','disqualify'} else ({e['actor']} if e['action']=='self_destruct' and e['actor'] else set())
            # S21 recaps explicitly report a poisoned wolf exploding before the
            # delayed death announcement. Retain that observed procedure without
            # counting a second death or restoring vote/skill eligibility.
            literal = ''.join(ev['quote'] for ev in e.get('evidence', []))
            explicit_poisoned_explosion = (e['action']=='self_destruct' and e['actor'] in new
                and e['actor'] in poisoned_targets
                and bool(re.search(r'吞毒.{0,12}自[爆曝]', literal)))
            if departure & dead and not explicit_poisoned_explosion:
                warnings.append({'kind':'day_departure_repeats_dead_player','event_id':e['event_id'],'seats':sorted(departure & dead)})
            dead.update(departure)
    return warnings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bvid',action='append')
    parser.add_argument('--summary',action='store_true')
    args=parser.parse_args()
    rows=[]
    for entry in p.read(p.INDEX)['entries']:
        bvid=entry['bvid'];path=p.SPEC_DIR/f'{bvid}.json'
        if args.bvid and bvid not in args.bvid: continue
        if not (p.ROOT/path).exists(): continue
        try:
            value=p.build(p.read(path)); warnings=audit(value)
            row={'bvid':bvid,'spec_sha256':p.sha(path),'events':len(value['events']),
                 'ballots':len(value['ballots']),'gaps':value['coverage']['gaps'],'chronology_warnings':warnings}
            rows.append(row)
            if args.summary:
                summary='; '.join(f"{e['phase'][0]}{e['round']} {e['action']} {e['actor']}->{e['targets']} {e['result'] or ''}"
                                 for e in value['events'])
                print(f"{bvid} E{len(value['events'])} B{len(value['ballots'])} G{len(row['gaps'])} W{len(warnings)} | {summary}")
            elif warnings:
                print(json.dumps({'bvid':bvid,'warnings':warnings},ensure_ascii=False))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            rows.append({'bvid':bvid,'validation_error':str(exc)})
            print('ERROR',bvid,str(exc))
    p.save(Path('data/reports/S21_白天夜间结构与时序审计.json'),{'items':rows})
    summary = {'media':len(rows),'events':sum(x.get('events',0) for x in rows),
                      'ballots':sum(x.get('ballots',0) for x in rows),'gaps':sum(len(x.get('gaps',[])) for x in rows),
                      'warnings':sum(len(x.get('chronology_warnings',[])) for x in rows),
               'validation_errors':sum('validation_error' in x for x in rows)}
    print(json.dumps(summary,ensure_ascii=False))
    return 1 if summary['validation_errors'] else 0


if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
