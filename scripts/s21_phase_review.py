"""Source-bound S21 day/night observations; no bluff or cross-season rules."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = Path('data/reports/S21_文字与截图时点索引.json')
SPEC_DIR = Path('data/extractions/S21/phase_specs')
PACK_DIR = Path('data/extractions/S21/phase_inputs')
SCOPE = ['night_actions', 'day_events', 'ballots', 'badge', 'endgame']
ACTIONS = {
    'guard', 'wolf_attack', 'extra_attack', 'save', 'poison', 'investigate',
    'choose_model', 'learn', 'learned_form', 'dream', 'wear_mask', 'dance',
    'exchange', 'steal_card', 'puppet', 'night_deaths', 'death_announcement',
    'sheriff_signup', 'sheriff_withdraw', 'sheriff_candidates', 'sheriff_elected',
    'sheriff_deferred', 'badge_transfer', 'badge_destroyed', 'badge_lost',
    'exile', 'no_exile', 'self_destruct', 'shoot', 'disqualify', 'concede',
    'prince_revote', 'reveal', 'endgame_attack', 'game_end', 'speech_start',
    'turn_day', 'turn_night', 'skill_forbidden', 'skill_resolution', 'trade',
}
LIVE_CUE = re.compile(
    r'投票开始|投票结束|投票结果|请.{0,12}(?:投票|退水|准备竞选)|号(?:玩家)?投给|号(?:玩家)?弃票|'
    r'号.{0,5}(?:当选警长|票当选)|当选警长|成为警长|警徽.{0,12}(?:流失|移交|撕)|'
    r'移交.{0,8}警徽|撕.{0,5}警徽|天黑.{0,8}闭眼|天亮.{0,8}睁眼|'
    r'(?:昨夜|昨晚).{0,18}(?:死|平安)|退出竞选|投票前.{0,10}候选|'
    r'游戏结束|阵营.{0,4}获胜|请.{0,8}(?:离场|灭灯)|等待.{0,8}发动技能|'
    r'上警(?:的)?玩家|警下(?:的)?玩家|所有玩家上警|自爆玩家|玩家自爆|号.{0,3}自爆'
)


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def sha(path):
    with (ROOT / path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def game(bvid):
    entry = next(e for e in read(INDEX)['entries'] if e['bvid'] == bvid)
    tp = Path(f'data/extractions/S21/media_evidence/{bvid}/transcript.selected.json')
    ip = Path(f'data/extractions/S21/game_reviews/{bvid}/identity.reviewed.json')
    transcript, identity = read(tp), read(ip)
    if sha(transcript['source_path']) != transcript['source_sha256']:
        raise ValueError(f'{bvid}: original transcript hash changed')
    if any(identity[k] != entry[k] for k in ('bvid', 'cid', 'page')):
        raise ValueError(f'{bvid}: identity source mismatch')
    return entry, transcript, identity, tp, ip


def evidence(transcript, indices, tp):
    if not indices or any(type(i) is not int or i < 0 or i >= len(transcript['segments']) for i in indices):
        raise ValueError('Evidence must contain valid literal source segment indices')
    indices = sorted(set(indices))
    segments = transcript['segments']
    return {
        'kind': 'literal_transcript', 'source_path': tp.as_posix(), 'source_sha256': sha(tp),
        'original_source_path': transcript['source_path'], 'original_source_sha256': transcript['source_sha256'],
        'source_segment_indices': indices, 'start_ms': segments[indices[0]]['start_ms'],
        'end_ms': segments[indices[-1]]['end_ms'],
        'quote': '\n'.join(segments[i]['text'] for i in indices),
        'time_kind': 'evidence_location_not_actual_event_time',
    }


def seat(value, nullable=False):
    if nullable and value is None:
        return
    if type(value) is not int or not 1 <= value <= 12:
        raise ValueError(f'Invalid seat: {value}')


def build(spec):
    bvid = spec['bvid']
    entry, transcript, identity, tp, ip = game(bvid)
    roles = {s['seat']: s['role'] for s in identity['seats']}
    if set(spec).intersection({'bluffs', 'claims', 'bluff_attempts'}):
        raise ValueError('Bluff/claim review is outside this stage')
    events = []
    for number, row in enumerate(spec.get('events', []), 1):
        if len(row) not in (6, 7):
            raise ValueError(f'{bvid}: event row must have 6 or 7 entries')
        phase, round_number, action, actor, targets, indices = row[:6]
        options = row[6] if len(row) == 7 else {}
        if phase not in {'night', 'day', 'endgame'} or action not in ACTIONS:
            raise ValueError(f'{bvid}: invalid phase/action {phase}/{action}')
        if round_number is not None and (type(round_number) is not int or not 1 <= round_number <= 20):
            raise ValueError('Invalid round')
        seat(actor, True)
        for target in targets:
            seat(target)
        if len(targets) != len(set(targets)):
            raise ValueError('Duplicate event targets')
        for target in options.get('actual_targets') or []:
            seat(target)
        status = options.get('status', 'text_explicit')
        state = options.get('state', 'performed')
        if status not in {'text_explicit', 'visual_explicit', 'unique_deduction', 'unknown'}:
            raise ValueError('Unknown evidence status')
        if state not in {'performed', 'pass', 'unknown', 'forbidden', 'not_applicable'}:
            raise ValueError('Unknown action state')
        if status == 'unique_deduction' and not options.get('note'):
            raise ValueError('Unique deductions require their reasoning')
        if state in {'pass', 'unknown', 'forbidden', 'not_applicable'} and targets:
            raise ValueError('Unperformed action must not invent a successful target')
        event = {
            'event_id': f'{bvid}-event-{number:03d}', 'phase': phase, 'round': round_number,
            'action': action, 'actor': actor, 'actor_physical_role': roles.get(actor),
            'targets': targets, 'actual_targets': options.get('actual_targets'),
            'state': state, 'status': status, 'result': options.get('result'),
            'details': options.get('details', {}), 'note': options.get('note'),
            'evidence': [evidence(transcript, indices, tp)],
        }
        events.append(event)
    ballots = []
    for number, original in enumerate(spec.get('ballots', []), 1):
        kind = original['type']
        if kind not in {'sheriff', 'exile'}:
            raise ValueError('A reviewed ballot requires its actual vote type')
        votes = []
        for row in original.get('votes', []):
            voter, target, indices = row[:3]
            seat(voter); seat(target, True)
            state = row[3] if len(row) > 3 else ('cast' if target else 'abstained')
            if state not in {'cast', 'abstained', 'default_abstention'} or (state == 'cast') != (target is not None):
                raise ValueError('Invalid ballot choice state')
            votes.append({'voter': voter, 'target': target, 'state': state,
                          'evidence': [evidence(transcript, indices, tp)]})
        voters = [v['voter'] for v in votes]
        if len(voters) != len(set(voters)):
            raise ValueError(f'{bvid}: one voter has conflicting or duplicate choices in a round')
        eligible = original.get('eligible_voters')
        if eligible is not None:
            for s in eligible: seat(s)
            if not set(voters) <= set(eligible):
                raise ValueError('Ballot includes an ineligible voter')
        if original.get('complete') and (eligible is None or set(voters) != set(eligible)):
            raise ValueError('Complete ballots must account for a proven voter set')
        if any(v['state'] == 'default_abstention' for v in votes) and (eligible is None or not original.get('eligibility_source')):
            raise ValueError('Default abstention requires source-bound known eligibility')
        ballots.append({
            'ballot_id': f'{bvid}-ballot-{number:02d}', 'day': original.get('day'),
            'type': kind, 'stage': original.get('stage', 'unknown'),
            'eligible_voters': eligible, 'candidate_seats': original.get('candidate_seats'),
            'votes': votes, 'outcome': original.get('outcome', {}),
            'completeness': 'complete_for_proven_eligible_set' if original.get('complete') else 'reviewed_explicit_choices_only',
            'evidence': [evidence(transcript, original['source'], tp)],
            'eligibility_evidence': [evidence(transcript, original['eligibility_source'], tp)] if original.get('eligibility_source') else [],
            'note': original.get('note'),
        })
    spans = spec.get('recap_spans', []) + spec.get('live_spans', [])
    if not spec.get('recap_spans') or not spec.get('live_spans') or not events:
        raise ValueError(f'{bvid}: continuous recap and actual daytime evidence must both be reviewed')
    for lo, hi in spans:
        if lo > hi: raise ValueError('Reversed inspected span')
        evidence(transcript, list(range(lo, hi + 1)), tp)
    gaps = [{**gap, 'evidence': [evidence(transcript, gap['sources'], tp)]}
            for gap in spec.get('gaps', [])]
    return {
        'schema_version': 1, 'season': 'S21', 'bvid': bvid, 'cid': entry['cid'], 'page': entry['page'],
        'field_scope': SCOPE, 'excluded_scope': ['bluffs', 'public_role_claims'],
        'review_status': 'assistant_reviewed_with_explicit_limits',
        'reviewer': spec.get('reviewer', 'codex_primary'),
        'source': {'selected_path': tp.as_posix(), 'selected_sha256': sha(tp),
                   'original_path': transcript['source_path'], 'original_sha256': transcript['source_sha256']},
        'identity_source': {'path': ip.as_posix(), 'sha256': sha(ip)},
        'round_convention': 'night 1 = opening night; night 2 = after day 1; day numbers follow actual game phases, not title Day',
        'event_time_note': 'Evidence times locate original-media words; no live event timestamp or wake order is inferred from recap order.',
        'events': events, 'ballots': ballots,
        'coverage': {'recap_spans_actually_read': spec['recap_spans'], 'live_spans_actually_read': spec['live_spans'],
                     'gaps': gaps, 'notes': spec.get('notes', []),
                     'status': 'reviewed_with_explicit_gaps' if spec.get('gaps') else 'reviewed_explicit_events'},
    }


def merge_spans(spans):
    result = []
    for lo, hi in sorted(spans):
        if result and lo <= result[-1][1] + 1:
            result[-1][1] = max(hi, result[-1][1])
        else:
            result.append([lo, hi])
    return result


def pack(entry):
    bvid = entry['bvid']
    _, transcript, identity, _, _ = game(bvid)
    segments = transcript['segments']
    candidates = read(f'data/extractions/S21/media_evidence/{bvid}/recap_candidates.json')['recap_location']['candidates']
    starts = [c['start_ms'] for c in candidates]
    # Last identity batch already has an independently checked terminal paragraph.
    primary = ROOT / 'data/extractions/S21/primary_identity_checks/remaining_primary/primary_review.json'
    if primary.exists():
        found = next((x for x in read(primary)['items'] if x['bvid'] == bvid), None)
        if found:
            indices = found['terminal_identity_text_actually_read']['source_segment_indices']
            starts.insert(0, segments[indices[0]]['start_ms'])
    if not starts:
        starts = [max(0, segments[-1]['end_ms'] - 600_000)]
    recap = []
    for start in starts:
        ids = [i for i, s in enumerate(segments) if start - 10_000 <= s['start_ms'] <= start + 300_000]
        if ids: recap.append([ids[0], ids[-1]])
    recap = merge_spans(recap)
    live = merge_spans([[max(0, i-5), min(len(segments)-1, i+7)] for i,s in enumerate(segments) if LIVE_CUE.search(s['text'])])
    lines = [f"{entry['index']} {bvid} CID={entry['cid']} P={entry['page']} {entry['title']}",
             'ROSTER: ' + ' | '.join(f"{s['seat']} {s['name']} {s['role']}" for s in identity['seats']),
             'READING RULE: candidates are locators, not verified facts; recap words are not live event times.',
             'FULL TRANSCRIPT: ' + f'data/extractions/S21/media_evidence/{bvid}/transcript.selected.json']
    for heading, spans in [('RECAP WINDOWS (check true boundaries)', recap), ('LIVE PROCEDURE WINDOWS (exclude commentary/player speculation)', live)]:
        lines.append('\n' + heading)
        for lo, hi in spans:
            lines.append(f'--- segments {lo}..{hi}')
            lines.extend(f"{i} [{segments[i]['start_ms']}..{segments[i]['end_ms']}] {segments[i]['text']}" for i in range(lo,hi+1))
    path = ROOT / PACK_DIR / f'{bvid}.txt'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'bvid': bvid, 'index': entry['index'], 'path': path.relative_to(ROOT).as_posix(),
            'recap_spans': recap, 'live_spans': live, 'lines': len(lines)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['pack', 'build'])
    parser.add_argument('--bvid', action='append')
    args = parser.parse_args()
    entries = [e for e in read(INDEX)['entries'] if not args.bvid or e['bvid'] in args.bvid]
    if args.command == 'pack':
        rows = [pack(e) for e in entries]
        save(PACK_DIR / 'index.json', rows)
        print(f'prepared {len(rows)} source-bound day/night reading packs')
    else:
        count = 0
        for e in entries:
            p = SPEC_DIR / f"{e['bvid']}.json"
            if not (ROOT / p).exists(): continue
            value = build(read(p))
            save(Path(f"data/extractions/S21/game_reviews/{e['bvid']}/phase.reviewed.json"), value)
            count += 1
        print(f'validated and built {count} reviewed phase records')


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    main()
