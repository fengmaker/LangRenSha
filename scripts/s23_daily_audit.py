"""Apply source-bound daily audits without replacing original review records."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json

from s23_phase_review import phase_label, WOLVES


def load_audit(folder, entry):
    path = folder / 'daily_audit.json'
    if not path.exists():
        return None
    audit = json.loads(path.read_text(encoding='utf-8'))
    if audit.get('bvid') != entry['bvid'] or audit.get('source_sha256') != entry['source_sha256']:
        raise ValueError('逐日复核来源绑定不匹配 ' + entry['bvid'])
    return audit


def apply_events(game, audit):
    """Patch the normalized dossier before presentation and survival replay."""
    changes = []
    for patch in audit.get('event_patches', []):
        number, phase, slot = patch['round'], patch['phase'], patch['slot']
        if phase not in {'night', 'day'}:
            raise ValueError('逐日复核阶段无效')
        rr = next(r for r in game['dossier']['rounds'] if r['number'] == number)
        matches = [e for e in rr[phase] if e['slot'] == slot]
        if len(matches) > 1:
            raise ValueError('逐日复核遇到重复事件槽 ' + slot)
        before = deepcopy(matches[0]) if matches else None
        event = matches[0] if matches else {'slot': slot, 'actor': None, 'targets': [], 'action': 'unknown'}
        event.update(deepcopy(patch['changes']))
        if event['slot'] != slot:
            raise ValueError('逐日复核不能改写事件槽名称')
        if not matches:
            rr[phase].append(event)
        changes.append({'round': number, 'phase': phase, 'slot': slot, 'before': before, 'after': deepcopy(event)})
    if audit.get('voting_replacement') is not None:
        game['voting'] = deepcopy(audit['voting_replacement'])
    bluff_changes = []
    for bluff in audit.get('bluff_overrides', []):
        if not any(s['seat'] == bluff['seat'] and s.get('role') in WOLVES for s in game['dossier']['seats']):
            raise ValueError('悍跳补正座位必须为本局狼人阵营')
        bluffs = game['review'].setdefault('bluffs', [])
        previous = next((b for b in bluffs if b['seat'] == bluff['seat']), None)
        bluff_changes.append({'before': deepcopy(previous), 'after': deepcopy(bluff)})
        if previous is None:
            bluffs.append(deepcopy(bluff))
        else:
            previous.update(deepcopy(bluff))
    suppressed = []
    for alias in audit.get('supplemental_suppressions', []):
        for item in list(game.get('supplemental_events', [])):
            if item['round'] == alias['round'] and item['event']['slot'] == alias['slot']:
                suppressed.append({**deepcopy(item), 'alias_reason': alias['reason']})
                game['supplemental_events'].remove(item)
    game['review']['daily_audit'] = deepcopy(audit)
    game['review']['daily_audit_changes'] = changes
    game['review']['daily_bluff_changes'] = bluff_changes
    game['review']['daily_supplemental_aliases'] = suppressed


def apply_findings(game, audit):
    """Retain resolved questions as history; expose only remaining questions."""
    review = game['review']
    observation = audit.get('terminal_observation')
    if observation:
        flow = game.setdefault('flow', {})
        flow['theoretical_terminal'] = flow.get('terminal')
        flow['terminal'] = {**deepcopy(observation), 'basis': 'explicit_source_announcement'}
        number, phase = observation['round'], observation['phase']
        flow['display_phases'] = [p for p in flow.get('display_phases', [])
                                 if p['round'] < number or p['round'] == number
                                 and (phase == 'day' or p['phase'] == 'night')]
    findings = review['phase_findings']
    resolutions = {r['id']: r for r in audit.get('finding_resolutions', [])}
    for finding in findings:
        resolution = resolutions.get(finding['id'])
        if resolution:
            status = resolution['status']
            if status not in {'confirmed', 'inferred', 'unresolved', 'not_observed'}:
                raise ValueError('逐日复核结论状态无效')
            # A copied old gap must not reopen a death/resource state which
            # the updated chronological replay has already ruled out.
            if status == 'unresolved' and finding['status'] != 'unresolved':
                continue
            finding['previous_question'] = finding.get('title')
            finding.update({k: deepcopy(v) for k, v in resolution.items() if k != 'id'})
            finding['daily_audited'] = True
    for extra in audit.get('extra_findings', []):
        if not any(f['id'] == extra['id'] for f in findings):
            findings.append(deepcopy(extra))
    # New unresolved audit questions get a stable anchor on the timeline.
    questions = {q['id']: deepcopy(q) for q in review.get('human_questions', [])}
    for q in audit.get('human_questions', []):
        questions[q['id']] = deepcopy(q)
    unresolved_ids = {f['id'] for f in findings if f['status'] == 'unresolved'}
    kept = []
    for q in questions.values():
        resolution = resolutions.get(q['id']) or resolutions.get('question-' + q['id'])
        if resolution and resolution['status'] != 'unresolved':
            continue
        q.setdefault('reason', q.get('reasoning', ''))
        q.setdefault('phase_label', phase_label(q['round'], q['phase']))
        kept.append(q)
        if q['id'] not in unresolved_ids and 'question-' + q['id'] not in unresolved_ids:
            findings.append({'id': 'question-' + q['id'], 'question_id': q['id'],
                             'round': q['round'], 'phase': q['phase'], 'phase_label': q['phase_label'],
                             'status': 'unresolved', 'field': q.get('field'),
                             'title': q['question'], 'conclusion': q['reason'], 'reasoning': q['reason'],
                             'evidence': deepcopy(q.get('evidence', [])), 'origin': 'human_question'})
    for f in findings:
        f.setdefault('phase_label', phase_label(f['round'], f['phase']))
        if f['status'] == 'unresolved' and not any(q['id'] in {f['id'], f.get('question_id')} for q in kept):
            kept.append({'id': f['id'], 'round': f['round'], 'phase': f['phase'],
                         'phase_label': f['phase_label'], 'field': f.get('field'),
                         'question': f['title'], 'reason': f.get('reasoning', ''),
                         'evidence': deepcopy(f.get('evidence', []))})
    # A human question also has a "question-" timeline id. Both references
    # must produce one response field, rather than duplicate user tasks.
    aliases = {f['id']: f.get('question_id') or f['id'] for f in findings}
    unique = {}
    for q in kept:
        canonical = aliases.get(q['id'], q['id'])
        if canonical not in unique:
            q['id'] = canonical
            unique[canonical] = q
    review['human_questions'] = list(unique.values())
    review['historical_ai_followups'] = review.pop('open_ai_followups', [])
    counts = Counter(f['status'] for f in findings)
    review['phase_review_counts'] = {s: counts[s] for s in ['unresolved', 'confirmed', 'inferred']}
    review['phase_review_counts']['not_observed'] = counts['not_observed']


def recap_rows(rows, audit):
    window = audit['recap_window']
    start, end = window['start_ms'], window['end_ms']
    if not (0 <= start < end):
        raise ValueError('最终复盘时间范围无效')
    chosen = [r for r in rows if r['end_ms'] > start and r['start_ms'] < end]
    if not chosen:
        raise ValueError('最终复盘窗口没有转写')
    return chosen
