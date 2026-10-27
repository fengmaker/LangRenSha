"""Validate, audit and store reviewed S21 day/night observations only."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from database import artifact, connect, migrate, ReviewError
from psycopg.types.json import Jsonb
import s21_phase_review as phase

METHOD = 's21_day_night_review_v1'
REPORT = Path('data/reports/S21_白天夜间核实进度.json')
GAPS_REPORT = Path('data/reports/S21_白天夜间待核项.json')
AUDIT = Path('data/extractions/S21/phase_primary_audit.json')


def baseline(conn):
    # A partial-stage importer must not alter any formal or publication tables.
    return {name: conn.execute(f'SELECT count(*) AS n FROM {name}').fetchone()['n'] for name in (
        'games','game_seats','game_event_records','game_event_targets','game_ballots','game_ballot_choices',
        'game_formal_annotations','transcript_segments','transcription_runs',
    )}


def prepare(entry, approvals):
    path = phase.SPEC_DIR / f"{entry['bvid']}.json"
    if not (phase.ROOT / path).exists():
        return None
    spec = phase.read(path)
    if spec['bvid'] != entry['bvid']:
        raise ReviewError('Phase spec belongs to another media')
    approval = approvals.get(entry['bvid'])
    if not approval:
        return None
    if approval['spec_sha256'] != phase.sha(path):
        raise ReviewError(f"{entry['bvid']}: stale primary phase audit")
    payload = phase.build(spec)
    payload['primary_audit'] = approval
    output = Path(f"data/extractions/S21/game_reviews/{entry['bvid']}/phase.reviewed.json")
    phase.save(output, payload)
    return {'entry': entry, 'path': output, 'sha256': phase.sha(output), 'payload': payload}


def import_batch(items):
    stats = Counter()
    with connect() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('s21-day-night-only-import',))
        before = baseline(conn)
        identity_before = conn.execute("SELECT count(*) AS n FROM reviewed_identity_seats WHERE season='S21'").fetchone()['n']
        for item in items:
            entry, payload = item['entry'], item['payload']
            source = conn.execute("SELECT id,metadata FROM sources WHERE platform='bilibili' AND external_key=%s",
                                  (f"{entry['bvid']}:{entry['cid']}",)).fetchone()
            if not source or any(source['metadata'].get(k) != entry[k] for k in ('bvid','cid','page')):
                raise ReviewError('Previously verified media source is absent or changed')
            source_id = source['id']
            # Preserve literal selected transcript, frozen identity and compact authoring spec.
            for proof_path, kind in ((payload['source']['selected_path'],'candidate'),
                                     (payload['identity_source']['path'],'candidate'),
                                     ((phase.SPEC_DIR / f"{entry['bvid']}.json").as_posix(),'candidate')):
                artifact(conn, source_id, phase.ROOT / proof_path, kind, {'phase_review_proof': True})
            aid = artifact(conn, source_id, phase.ROOT / item['path'], 'candidate', {'method': METHOD,'field_scope':phase.SCOPE})
            old = conn.execute('SELECT method,payload,verification_status FROM extraction_runs WHERE artifact_id=%s', (aid,)).fetchone()
            if old:
                if old['method'] != METHOD or old['payload'] != payload or old['verification_status'] != 'reviewed':
                    raise ReviewError('Existing phase extraction differs from the reviewed file')
                stats['unchanged'] += 1
                continue
            row = conn.execute("INSERT INTO extraction_runs(source_id,artifact_id,method,payload,verification_status) VALUES(%s,%s,%s,%s,'reviewed') RETURNING id",
                               (source_id,aid,METHOD,Jsonb(payload))).fetchone()
            conn.execute('INSERT INTO audit_events(action,actor,entity_id,details) VALUES(%s,%s,%s,%s)',
                         ('import_s21_day_night_review','codex_primary',row['id'],Jsonb({'bvid':entry['bvid'],'sha256':item['sha256'],'scope':phase.SCOPE})))
            stats['inserted'] += 1
        after = baseline(conn)
        identity_after = conn.execute("SELECT count(*) AS n FROM reviewed_identity_seats WHERE season='S21'").fetchone()['n']
        if before != after or identity_before != identity_after:
            raise ReviewError('Day/night import changed unrelated facts; transaction rolled back')
        rows = conn.execute("SELECT payload FROM reviewed_phase_records WHERE payload->>'season'='S21'").fetchall()
        actual = {r['payload']['bvid']: r['payload'] for r in rows}
        if any(actual.get(item['entry']['bvid']) != item['payload'] for item in items):
            raise ReviewError('Database readback differs from reviewed payload; transaction rolled back')
    return {'records':dict(stats),'current_media':len(actual),'readback_exact':True,
            'unrelated_fact_counts_before':before,'unrelated_fact_counts_after':after,
            'identity_seats_before':identity_before,'identity_seats_after':identity_after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-db',action='store_true')
    args = parser.parse_args()
    approvals = phase.read(AUDIT)['items']
    entries = phase.read(phase.INDEX)['entries']
    items = [item for e in entries if (item := prepare(e, approvals))]
    reviewed = {x['entry']['bvid'] for x in items}
    result = {'season':'S21','updated_at_utc':datetime.now(timezone.utc).isoformat(),'field_scope':phase.SCOPE,
              'excluded_scope':['bluffs','public_role_claims'],'media_target':len(entries),'media_reviewed':len(items),
              'events_reviewed':sum(len(x['payload']['events']) for x in items),
              'ballot_rounds_reviewed':sum(len(x['payload']['ballots']) for x in items),
              'ballot_choices_reviewed':sum(len(b['votes']) for x in items for b in x['payload']['ballots']),
              'explicit_gaps':sum(len(x['payload']['coverage']['gaps']) for x in items),
              'pending_media':[e['bvid'] for e in entries if e['bvid'] not in reviewed],
              'database_writes':args.import_db,
              'items':[{'bvid':i['entry']['bvid'],'path':i['path'].as_posix(),'sha256':i['sha256']} for i in items]}
    if args.import_db:
        migrate()
        result['database'] = import_batch(items)
    ballots = [b for item in items for b in item['payload']['ballots']]
    gaps = [{'bvid':item['entry']['bvid'], 'cid':item['entry']['cid'],
             'title':item['entry']['title'], **gap}
            for item in items for gap in item['payload']['coverage']['gaps']]
    complete = sum(b['completeness']=='complete_for_proven_eligible_set' for b in ballots)
    result['complete_ballot_rounds'] = complete
    result['incomplete_ballot_rounds'] = len(ballots)-complete
    result['explicit_gaps_report'] = GAPS_REPORT.as_posix()
    phase.save(GAPS_REPORT, {'schema_version':1, 'season':'S21', 'updated_at_utc':result['updated_at_utc'],
        'media_reviewed':len(items), 'media_with_explicit_gaps':len({g['bvid'] for g in gaps}),
        'ballot_rounds':len(ballots), 'complete_ballot_rounds':complete,
        'incomplete_ballot_rounds':len(ballots)-complete, 'gap_count':len(gaps),
        'field_scope':phase.SCOPE, 'excluded_scope':result['excluded_scope'],
        'note':'核查覆盖不代表每个字段均已确定；未知不补成空过、弃票或目标。证据时点定位原文，不是游戏内动作发生时点。',
        'database_writes':args.import_db, 'items':gaps})
    phase.save(REPORT,result)
    print(json.dumps({k:v for k,v in result.items() if k not in {'items','pending_media'}},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    main()
