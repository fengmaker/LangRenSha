"""Cross-check definite departures against recorded S23 voter eligibility."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]


def check():
    progress=json.loads((ROOT/'data/reports/S23/S23_逐局复核进度.json').read_text(encoding='utf-8'))
    issues=[]
    for candidate in progress['candidate_dossiers']:
        folder=(ROOT/candidate).parent
        d=json.loads((folder/'dossier.candidate.json').read_text(encoding='utf-8'))
        v=json.loads((folder/'voting.candidate.json').read_text(encoding='utf-8'))
        bvid=folder.name.rsplit('_',1)[-1]
        dead=set()
        shots=Counter()
        for rr in d['rounds']:
            n=rr['number'];prior=set(dead)
            night_dead={t for e in rr['day'] if e['slot']=='night_deaths' and e['action']=='die' for t in e['targets']}
            for b in (b for b in v['ballots'] if b['day']==n):
                # A not-yet-announced night death can vote for sheriff, but
                # cannot take part in the subsequent exile ballot.
                excluded=prior | (night_dead if b['kind']=='exile' else set())
                voters={x['voter'] for x in b['votes']}
                eligible=set(b['eligible_voters']) if b.get('eligible_voters') is not None else None
                for code,invalid in [('dead_voter',voters&excluded),
                                     ('dead_eligible_voter',(eligible or set())&excluded),
                                     ('voter_outside_eligible',voters-eligible if eligible is not None else set())]:
                    if invalid:issues.append({'bvid':bvid,'round':n,'ballot':b['id'],'code':code,'seats':sorted(invalid)})
            dead.update(night_dead)
            for e in rr['day']:
                if e['action']=='self_destruct' and e.get('actor'):dead.add(e['actor'])
                if e['slot'] in {'exile_result','second_exile_result'} and e['action']=='exile':dead.update(e['targets'])
                if e['action']=='shoot':
                    dead.update(e['targets'])
                    if e['slot'] in {'hunter_shot','wolf_king_shot','mechanical_day_skill'}:
                        shots[e.get('actor')]+=1
        for actor,count in shots.items():
            if count>1:issues.append({'bvid':bvid,'code':'repeated_gun_action','actor':actor,'count':count})
    result={'snapshot_id':progress['snapshot_id'],'checked_at_utc':datetime.now(timezone.utc).isoformat(),
            'games':len(progress['candidate_dossiers']),'issues':issues,'passed':not issues,
            'boundary':'Only confirmed prior departures and final night-death records exclude voters; unknown deaths are not assumed absent. Sheriff voting may precede the night-death announcement.',
            'formal_database_writes':False}
    (ROOT/'data/reports/S23/S23_日夜存活票权交叉验收.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result=check();print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
