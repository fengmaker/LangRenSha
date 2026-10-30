"""Verify daily-audit coverage, exact quote locations and recap-only exports."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from audit_s23_review import evidence_objects
from prepare_s23_review import segments

ROOT = Path(__file__).resolve().parents[1]


def check():
    progress = json.loads((ROOT / 'data/reports/S23/S23_逐局复核进度.json').read_text(encoding='utf-8'))
    html = (ROOT / 'data/exports/S23_逐局推导与复核.html').read_text(encoding='utf-8')
    payload = json.loads(html.split('window.__S23_REVIEW__=', 1)[1].split(';</script>', 1)[0])
    old_path = ROOT / 'data/archive/S23_daily_review_20261026/before/data/reports/S23_日夜待核定位.json'
    old = json.loads(old_path.read_text(encoding='utf-8'))
    old_pending = {g['bvid']: {f['id'] for f in g['findings'] if f['status'] == 'unresolved'} for g in old['games']}
    issues, games, proof_count = [], [], 0
    if payload['snapshot_id'] != progress['snapshot_id']:
        issues.append({'code': 'page_progress_snapshot_mismatch'})
    for game in payload['games']:
        entry, review = game['entry'], game['review']
        bvid = entry['bvid']
        audit = review.get('daily_audit')
        if not audit:
            issues.append({'bvid': bvid, 'code': 'missing_daily_audit'})
            continue
        source = ROOT / entry['source_path']
        rows = segments(source)
        if hashlib.sha256(source.read_bytes()).hexdigest() != audit['source_sha256']:
            issues.append({'bvid': bvid, 'code': 'changed_source'})
        window = audit['recap_window']
        expected = [r for r in rows if r['end_ms'] > window['start_ms'] and r['start_ms'] < window['end_ms']]
        if game['transcript'] != expected or not expected:
            issues.append({'bvid': bvid, 'code': 'recap_display_mismatch'})
        if len(expected) == len(rows) or not audit.get('checks'):
            issues.append({'bvid': bvid, 'code': 'missing_substantive_audit'})
        ids = [r['id'] for r in audit.get('finding_resolutions', [])]
        if len(ids) != len(set(ids)):
            issues.append({'bvid': bvid, 'code': 'duplicate_resolution'})
        for missing in old_pending[bvid] - set(ids):
            issues.append({'bvid': bvid, 'code': 'unreviewed_old_question', 'id': missing})
        for proof in evidence_objects(audit):
            proof_count += 1
            p = ROOT / proof.get('source_path', proof.get('source', ''))
            if not p.is_file():
                issues.append({'bvid': bvid, 'code': 'missing_proof', 'source': str(p)})
                continue
            if proof.get('source_sha256') and hashlib.sha256(p.read_bytes()).hexdigest() != proof['source_sha256']:
                issues.append({'bvid': bvid, 'code': 'proof_hash_mismatch'})
            if proof.get('quote') and p.suffix == '.json' and proof.get('kind') != 'video_frame':
                raw = json.loads(p.read_text(encoding='utf-8'))
                if not isinstance(raw, dict) or not ({'segments', 'body'} & raw.keys()):
                    if re.sub(r'\s+', '', proof['quote']) not in re.sub(r'\s+', '', json.dumps(raw, ensure_ascii=False)):
                        issues.append({'bvid': bvid, 'code': 'rule_quote_mismatch'})
                    continue
                source_rows = rows if p == source else segments(p)
                start, end = proof.get('start_ms'), proof.get('end_ms')
                if start is None or end is None:
                    issues.append({'bvid': bvid, 'code': 'proof_missing_time'})
                    continue
                text = ''.join(r['text'] for r in source_rows if r['end_ms'] >= start and r['start_ms'] <= end)
                norm = lambda t: re.sub(r'\s+', '', t)
                if norm(proof['quote']) not in norm(text):
                    issues.append({'bvid': bvid, 'code': 'proof_quote_mismatch', 'start_ms': start, 'quote': proof['quote']})
        for rr in game['dossier']['rounds']:
            roles = {s['seat']: s['role'] for s in game['dossier']['seats']}
            expected_roles = {'guard': {'守卫'}, 'witch_save': {'女巫'},
                              'witch_poison': {'毒师'} if game['dossier']['board'] == 'treasure_master' else {'女巫'},
                              'seer_check': {'预言家', '通灵师'}, 'mechanical_action': {'机械狼'},
                              'mechanical_knife_status': {'机械狼'}, 'mechanical_day_skill': {'机械狼'}}
            for phase in ['night', 'day']:
                for ev in rr[phase]:
                    if any(type(t) is not int or not 1 <= t <= 12 for t in ev.get('targets', [])):
                        issues.append({'bvid': bvid, 'code': 'invalid_event_target'})
                    if ev.get('actor') is not None and ev['slot'] in expected_roles and roles[ev['actor']] not in expected_roles[ev['slot']]:
                        issues.append({'bvid': bvid, 'code': 'actor_role_mismatch', 'round': rr['number'], 'event': ev})
            if rr['number'] == 1 and game['dossier']['board'] == 'treasure_master':
                attack = next((e for e in rr['night'] if e['slot'] == 'wolf_attack'), {})
                if attack.get('action') != 'forbidden' or attack.get('targets'):
                    issues.append({'bvid': bvid, 'code': 'treasure_first_night_knife'})
            if rr['number'] == 1 and game['dossier']['board'] == 'masquerade':
                for slot in ['masquerade_verify', 'masquerade_mask', 'dancer_dance']:
                    ev = next((e for e in rr['night'] if e['slot'] == slot), {})
                    if ev.get('action') != 'unavailable' or ev.get('targets'):
                        issues.append({'bvid': bvid, 'code': 'masquerade_first_night_skill', 'slot': slot})
        unresolved = [f for f in review['phase_findings'] if f['status'] == 'unresolved']
        questions = {q['id'] for q in review['human_questions']}
        for finding in unresolved:
            if not questions.intersection({finding['id'], finding.get('question_id')}):
                issues.append({'bvid': bvid, 'code': 'question_missing_from_user_list', 'id': finding['id']})
        games.append({'bvid': bvid, 'date': entry['date'], 'game_number': entry['game_number'],
                      'full_segments': len(rows), 'recap_segments': len(expected), 'pending': len(unresolved),
                      'patches': len(audit.get('event_patches', []))})
    if len(games) != 75:
        issues.append({'code': 'incomplete_games', 'count': len(games)})
    result = {'snapshot_id': progress['snapshot_id'], 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'games': games, 'audited_games': len(games), 'proofs_checked': proof_count,
              'old_pending': sum(len(v) for v in old_pending.values()),
              'pending': sum(g['pending'] for g in games), 'issues': issues, 'passed': not issues,
              'formal_database_writes': False}
    (ROOT / 'data/reports/S23/S23_逐日复核验收_20261026.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result = check()
    print(json.dumps({k: v for k, v in result.items() if k != 'games'}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
