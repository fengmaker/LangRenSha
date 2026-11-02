"""Apply the two accepted S22 corrections using existing import transactions."""
from datetime import datetime, timezone
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from psycopg.types.json import Jsonb
from database import connect
from game_records import import_game
from voting_records import import_voting
from game_derivations import apply_precomputed
from role_constraints import puppet_target


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def counts(conn):
    return conn.execute('SELECT s.code AS season,count(*) AS games FROM games g '
                        'JOIN seasons s ON s.id=g.season_id GROUP BY s.code ORDER BY s.code').fetchall()


def identity(conn, slug):
    return conn.execute('SELECT id,season_id,primary_source_id FROM games WHERE slug=%s', (slug,)).fetchone()


def annotations(conn, game_id):
    return {r['annotation_key']: r for r in conn.execute(
        'SELECT annotation_key,annotation_type,source_path,source_sha256,payload '
        'FROM game_formal_annotations WHERE game_id=%s', (game_id,)).fetchall()}


items = []
for bvid in ['BV1KuMG6NEez', 'BV1yKJ56PEak']:
    folder = next((ROOT / 'data/games/S22').glob('*' + bvid))
    dossier, voting, report = [read(folder / (name + '.json'))
                               for name in ['dossier', 'voting', 'rule_derivations']]
    assert not report['issues']
    projected = apply_precomputed(dossier, voting, report)
    assert projected['dossier'] == dossier and projected['voting'] == voting
    db_dossier = deepcopy(dossier)
    normalization = []
    puppet = puppet_target(dossier)
    for round_ in db_dossier['rounds']:
        for event in round_['night']:
            if (event['slot'] == 'puppet_skill_effect'
                    and event['action'] in {'skill_disabled', 'reverse_check'} and not event['targets']):
                assert puppet is not None
                event['targets'] = [puppet]
                normalization.append({'round': round_['number'], 'phase': 'night',
                                      'slot': event['slot'], 'before_targets': [], 'db_targets': [puppet],
                                      'basis': '本局已核puppet_select；仅补数据库所需的傀儡效果作用座位，原人工档案保留'})
    sidecars = [('supplemental', 'supplemental_observations', folder / 'supplemental.json')]
    if (folder / 'formal_context.json').exists():
        sidecars.append(('terminal_observations', 'terminal_observations', folder / 'formal_context.json'))
    for key, _, path in sidecars:
        payload = read(path)
        assert payload.get('game_slug', dossier['slug']) == dossier['slug']
        if key == 'supplemental':
            for observation in payload.get('events', []):
                source = observation.get('source')
                if source:
                    assert hashlib.sha256((ROOT / source['path']).read_bytes()).hexdigest() == source['sha256']
    items.append((bvid, dossier, db_dossier, voting, report, sidecars, normalization))

receipts = []
with connect() as conn:
    before_counts = counts(conn)
    for bvid, dossier, db_dossier, voting, report, sidecars, normalization in items:
        before = identity(conn, dossier['slug'])
        assert before is not None
        previous_annotations = annotations(conn, before['id'])
        previous_files = conn.execute('SELECT file_role,artifact_id FROM game_files WHERE game_id=%s ORDER BY file_role', (before['id'],)).fetchall()
        receipt = import_game(db_dossier, allow_incomplete=True, conn=conn, derivations=report)
        receipt['voting'] = import_voting(voting, conn=conn)
        game_id = before['id']
        for key, kind, path in sidecars:
            conn.execute('''INSERT INTO game_formal_annotations
                (game_id,annotation_key,annotation_type,source_path,source_sha256,payload)
                VALUES(%s,%s,%s,%s,%s,%s)
                ON CONFLICT(game_id,annotation_key) DO UPDATE SET
                annotation_type=EXCLUDED.annotation_type,source_path=EXCLUDED.source_path,
                source_sha256=EXCLUDED.source_sha256,payload=EXCLUDED.payload,recorded_at=now()''',
                (game_id, key, kind, path.relative_to(ROOT).as_posix(),
                 hashlib.sha256(path.read_bytes()).hexdigest(), Jsonb(read(path))))
        if normalization:
            dossier_path = sidecars[0][2].with_name('dossier.json')
            conn.execute('''INSERT INTO game_formal_annotations
                (game_id,annotation_key,annotation_type,source_path,source_sha256,payload)
                VALUES(%s,'board-display-normalization-20261102','review_context',%s,%s,%s)
                ON CONFLICT(game_id,annotation_key) DO UPDATE SET
                source_path=EXCLUDED.source_path,source_sha256=EXCLUDED.source_sha256,
                payload=EXCLUDED.payload,recorded_at=now()''',
                (game_id, dossier_path.relative_to(ROOT).as_posix(),
                 hashlib.sha256(dossier_path.read_bytes()).hexdigest(), Jsonb({'normalization': normalization})))
        assert identity(conn, dossier['slug']) == before
        assert conn.execute('SELECT file_role,artifact_id FROM game_files WHERE game_id=%s ORDER BY file_role', (game_id,)).fetchall() == previous_files
        after_annotations = annotations(conn, game_id)
        changed_keys = {'shared-rule-derivations', 'board-display-normalization-20261102'} | {key for key, _, _ in sidecars}
        assert all(after_annotations[key] == value for key, value in previous_annotations.items() if key not in changed_keys)
        assert after_annotations['shared-rule-derivations']['payload'] == report
        for key, _, path in sidecars:
            assert after_annotations[key]['payload'] == read(path)
            assert after_annotations[key]['source_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
        actual_events = conn.execute('SELECT id,round_number,phase,slot_code,action,actor_seat,result_code FROM game_event_records WHERE game_id=%s', (game_id,)).fetchall()
        expected_events = {(r['number'], phase, e['slot']): e for r in db_dossier['rounds'] for phase in ['night', 'day'] for e in r[phase]}
        assert len(actual_events) == len(expected_events)
        for row in actual_events:
            expected = expected_events[(row['round_number'], row['phase'], row['slot_code'])]
            targets = [r['seat_number'] for r in conn.execute('SELECT seat_number FROM game_event_targets WHERE event_id=%s ORDER BY position', (row['id'],)).fetchall()]
            assert (row['action'], row['actor_seat'], row['result_code'], targets) == (expected['action'], expected['actor'], expected['result'], expected['targets'])
        actual_votes = conn.execute('''SELECT b.ballot_key,c.voter_seat,c.target_seat,c.state FROM game_ballots b
            JOIN game_ballot_choices c ON c.ballot_id=b.id WHERE b.game_id=%s ORDER BY b.ballot_key,c.voter_seat''', (game_id,)).fetchall()
        expected_votes = sorted((b['id'], v['voter'], v['target'], v['state']) for b in voting['ballots'] for v in b['votes'])
        assert [(r['ballot_key'], r['voter_seat'], r['target_seat'], r['state']) for r in actual_votes] == expected_votes
        receipts.append({**receipt, 'bvid': bvid, 'events_readback_verified': True,
                         'votes_readback_verified': True, 'annotations_readback_verified': True,
                         'source_binding_preserved': True, 'previous_annotations_preserved': True,
                         'db_normalization': normalization,
                         'terminal': report.get('terminal')})
    after_counts = counts(conn)
    assert after_counts == before_counts

result = {'database_write': True, 'completed_at_utc': datetime.now(timezone.utc).isoformat(),
          'transaction': 'one transaction for both selected games, votes, derivations and source annotations',
          'backup_receipt': 'data/backups/workflow-20261102T100311/receipt.json',
          'formal_counts_before': before_counts, 'formal_counts_after': after_counts,
          'readback_verified': True, 'receipts': receipts}
target = ROOT / 'data/reports/shared/版型发布修订入库_20261102.json'
target.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
