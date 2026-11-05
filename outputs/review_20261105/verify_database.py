"""Read back this batch and compare preserved public snapshots."""
import json
from pathlib import Path
import sys

ROOT = Path('D:/langrensha')
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]
from database import connect
from incremental_common import load_state, write_json
from website.api.publisher import _connect

BV = ['BV1zzxR6sEB6', 'BV1zzxR6sEos', 'BV16zxR6sEKG']
state = load_state(ROOT, 'S23')
results = []
with connect() as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    for bvid in BV:
        item = next(v for v in state['items'].values() if v.get('entry', {}).get('bvid') == bvid)
        folder = ROOT / item['formal_dir']
        dossier, voting, endgame = [json.loads((folder / (name + '.json')).read_text(encoding='utf-8'))
                                    for name in ['dossier', 'voting', 'endgame']]
        game = conn.execute('SELECT g.id,d.* FROM games g JOIN game_details d ON d.game_id=g.id WHERE g.slug=%s',
                            (dossier['slug'],)).fetchone()
        gid = game['game_id']
        assert game['winning_faction'] == dossier['winner']
        assert game['board_code'] == dossier['board'] and str(game['event_date']) == dossier['date']
        seats = conn.execute('''SELECT s.seat_number AS seat,p.name,s.role,s.faction,
            s.learning_target_seat AS learning_target,s.learned_role FROM game_seats s
            LEFT JOIN people p ON p.id=s.person_id WHERE s.game_id=%s ORDER BY s.seat_number''', (gid,)).fetchall()
        assert seats == dossier['seats'], bvid + ': seats'
        events = conn.execute('''SELECT id,round_number,phase,slot_code,action,actor_seat AS actor,
            result_code AS result,start_seat,direction,random_point,speech_scope,availability
            FROM game_event_records WHERE game_id=%s''', (gid,)).fetchall()
        expected = {(r['number'], phase, e['slot']): e for r in dossier['rounds']
                    for phase in ['night', 'day'] for e in r[phase]}
        assert len(events) == len(expected)
        for row in events:
            event_id = row.pop('id')
            key = (row.pop('round_number'), row.pop('phase'), row.pop('slot_code'))
            row['slot'] = key[2]
            row['targets'] = [v['seat_number'] for v in conn.execute(
                'SELECT seat_number FROM game_event_targets WHERE event_id=%s ORDER BY position', (event_id,))]
            row['effects'] = conn.execute('''SELECT kind,intended_target,dead_seat,shield_actor
                FROM game_event_effects WHERE event_id=%s ORDER BY position''', (event_id,)).fetchall()
            row['votes'] = conn.execute('''SELECT ballot_round AS round,voter_seat AS voter,target_seat AS target,abstained
                FROM game_event_votes WHERE event_id=%s ORDER BY ballot_round,voter_seat''', (event_id,)).fetchall()
            wanted = dict(expected[key])
            wanted['votes'] = sorted(wanted['votes'], key=lambda v: (v['round'], v['voter']))
            assert row == wanted, (bvid, key, row, wanted)
        ballots = conn.execute('''SELECT id AS database_id,ballot_key AS id,day_number AS day,kind,
            ballot_number AS number,stage,status,candidates,eligible_voters,tied_candidates,winner_seat AS winner
            FROM game_ballots WHERE game_id=%s ORDER BY ballot_key''', (gid,)).fetchall()
        votes = 0
        for row in ballots:
            ballot_id = row.pop('database_id')
            row['votes'] = conn.execute('''SELECT voter_seat AS voter,target_seat AS target,state
                FROM game_ballot_choices WHERE ballot_id=%s ORDER BY voter_seat''', (ballot_id,)).fetchall()
            wanted = next(b for b in voting['ballots'] if b['id'] == row['id'])
            wanted = {k: wanted[k] for k in row}
            wanted['votes'] = [{k: v[k] for k in ['voter', 'target', 'state']}
                               for v in sorted(wanted['votes'], key=lambda v: v['voter'])]
            assert row == wanted, (bvid, row['id'])
            votes += len(row['votes'])
        assert len(ballots) == len(voting['ballots'])
        ending = conn.execute('''SELECT kind,day_number AS day,actor_seat AS actor,declared_targets,result
            FROM game_endgame_phases WHERE game_id=%s ORDER BY phase_number''', (gid,)).fetchall()
        assert ending == [{k: e[k] for k in ['kind', 'day', 'actor', 'declared_targets', 'result']}
                          for e in endgame['phases']]
        results.append({'bvid': bvid, 'seats': len(seats), 'events': len(events), 'ballots': len(ballots),
                        'votes': votes, 'endgame_phases': len(ending), 'winner': dossier['winner']})
    formal_counts = conn.execute('''SELECT s.code AS season,count(*) AS games FROM games g
        JOIN seasons s ON s.id=g.season_id GROUP BY s.code ORDER BY s.code''').fetchall()

baseline = json.loads((ROOT / 'data/backups/workflow-20261105T055500/receipt.json').read_text(encoding='utf-8'))
with _connect() as conn:
    current = conn.execute('SELECT release_id FROM active_release WHERE singleton=true').fetchone()['release_id']
    old_rows = conn.execute('SELECT id,season,snapshot FROM games WHERE release_id=%s',
                            (baseline['active_release']['release_id'],)).fetchall()
    current_rows = {row['id']: row for row in conn.execute(
        'SELECT id,season,snapshot FROM games WHERE release_id=%s', (current,))}
    preserved = {}
    for old in old_rows:
        before, after = dict(old['snapshot']), dict(current_rows[old['id']]['snapshot'])
        before.pop('release_id', None)
        after.pop('release_id', None)
        assert before == after, old['id']
        preserved[old['season']] = preserved.get(old['season'], 0) + 1
    bluffs = conn.execute('''SELECT i.game_id,i.seat,i.decision,i.success FROM bluff_review_items i
        JOIN active_bluff_reviews a ON a.release_id=i.release_id AND a.publication_id=i.publication_id
        WHERE i.release_id=%s AND i.game_id=ANY(%s) AND i.decision='yes' ORDER BY i.game_id,i.seat''',
        (current, [f'bili-{bvid}-p01-g0{number}' for number, bvid in enumerate(BV, 1)])).fetchall()
    assert len(bluffs) == 3 and all(r['success'] is False for r in bluffs)
report = {'state': 'passed', 'release_id': current, 'games': results, 'formal_counts': formal_counts,
          'preserved_snapshot_games': preserved, 'public_games': len(current_rows), 'bluffs': bluffs}
write_json(ROOT / 'data/reports/S23/incremental/20261105_database_readback.json', report)
print(json.dumps(report, ensure_ascii=False, indent=2))
