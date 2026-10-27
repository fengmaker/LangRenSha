"""Validate and apply evidence-backed S22 AI doubt reviews through the review save seam."""
from __future__ import annotations
import argparse
import copy
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import zipfile

import batch_s22 as batch
from game_records import validate, validate_batch
from game_scope import exclusion_reason
from formal_rule_checks import has_unresolved_departures, registry
from s22_text_review import make_round
from s22_review_server import save_item

BASE = batch.ROOT / 'data/extractions/S22/疑点推理复核'
REPORT = batch.ROOT / 'data/reports/S22_疑点推理复核.json'
GROUPS = ('mechanical', 'mixed_neighbor', 'special', 'primary')


def normalized(text):
    return re.sub(r'[\W_]+', '', str(text))


def changed_value(original, changes, *, allow_legacy_treasure_faction=False):
    value = copy.deepcopy(original)
    for change in changes:
        kind = change['kind']
        if kind == 'event':
            round_ = next(r for r in value['rounds'] if r['number'] == change['number'])
            event = next(e for e in round_[change['phase']] if e['slot'] == change['slot'])
            if set(change['fields']) - (set(event) - {'slot'}):
                raise ValueError('非法事件字段')
            event.update(copy.deepcopy(change['fields']))
        elif kind == 'seat':
            seat = next(s for s in value['seats'] if s['seat'] == change['seat'])
            if set(change['fields']) - {'role', 'faction', 'learning_target', 'learned_role'}:
                raise ValueError('本轮不允许更改姓名等无关字段')
            seat.update(copy.deepcopy(change['fields']))
        elif kind == 'round_count':
            count = change['value']
            if type(count) is not int or not 0 <= count <= 12:
                raise ValueError('非法轮数')
            while len(value['rounds']) < count:
                value['rounds'].append(make_round(batch.template(value['board']), len(value['rounds']) + 1, value['seats']))
            value['rounds'] = value['rounds'][:count]
        elif kind == 'winner':
            value['winner'] = change['value']
        elif kind == 'game_number':
            number = change['value']
            if type(number) is not int or number < 1:
                raise ValueError('非法局次')
            value['game_number'] = number
        else:
            raise ValueError('非法修正类型：' + str(kind))
    # Historical plans are replayed against their original structural contract.
    # Current saves/imports separately enforce the latest confirmed rules.
    validate_batch(value, check_rules=False,
                   allow_legacy_treasure_faction=allow_legacy_treasure_faction)
    return value



def semantic_issues(value):
    """Cross-check known facts; current-night damage does not block same-night skills."""
    departed, issues, medicines = set(), [], {}
    seats = {p.get("seat"): p for p in value.get("seats", []) if isinstance(p, dict)}
    treasure = next((p for p in seats.values() if p.get("role") == "盗宝大师"), None)
    takeover_roles = set(registry()["boards"]["treasure_master"]["board_rules"]
                        ["ordinary_wolf_knife_takeover"]["after_all_identity_roles_departed"])
    uncertain_departure_history = False
    previous_choices, danced, self_destructed = {}, set(), set()
    active = {"guard", "check", "poison", "save", "learn", "exchange", "dream", "choose", "verify", "give_mask", "dance", "attack"}
    for round_ in value["rounds"]:
        number = round_["number"]
        used_this_night = []
        for event in round_["night"]:
            slot, action = event['slot'], event['action']
            if slot in {'masquerade_mask', 'masquerade_verify', 'treasure_choice'} and action in {'give_mask', 'verify', 'choose'}:
                choice = event['result'] if slot == 'treasure_choice' else event['targets']
                if previous_choices.get(slot) == (number - 1, choice):
                    issues.append(f"第{number}夜{slot}连续重复选择")
                previous_choices[slot] = (number, choice)
            if slot == 'dancer_dance' and action == 'dance':
                if danced.intersection(event['targets']):
                    issues.append(f"第{number}夜共舞包含此前已共舞者")
                danced.update(event['targets'])
            if value.get('board') == 'treasure_master' and number == 1 and slot == 'wolf_attack' and action != 'forbidden':
                issues.append('盗宝大师版型首夜必须记录规则禁刀')
            if (number > 1 and value.get('board') == 'treasure_master' and slot == 'wolf_attack'
                    and action in {'attack', 'pass'} and treasure
                    and event.get('actor') == treasure.get('seat')
                    and any(p.get('role') in takeover_roles and p.get('seat') not in departed for p in seats.values())
                    and not uncertain_departure_history
                    and all(p.get('role') is not None for p in seats.values())):
                issues.append(f'第{number}夜其他初始狼队成员（狼人、狼王）仍存活，盗宝大师不能接替普通狼刀')
            if event["action"] in active:
                if event["actor"] in departed:
                    issues.append(f"第{number}夜{event['slot']}行动者前轮已出局")
                if any(t in departed for t in event["targets"]):
                    issues.append(f"第{number}夜{event['slot']}目标前轮已出局")
            if event["slot"] in {"witch_save", "witch_poison"} and event["action"] in {"save", "poison"}:
                medicines.setdefault(event["slot"], []).append(number)
                used_this_night.append(event["slot"])
        if len(used_this_night) > 1:
            issues.append(f"第{number}夜普通女巫同夜使用两药")
        for event in round_["day"]:
            if event["action"] == "die" and any(t in departed for t in event["targets"]):
                issues.append(f"第{number}天夜死名单重复前轮死者")
            if event["action"] in {"die", "exile", "shoot", "suicide", "die_after_speech"}:
                departed.update(event["targets"])
            if event["action"] == "self_destruct" and event["actor"]:
                if event['actor'] in self_destructed:
                    issues.append(f"第{number}天同一狼人重复自爆")
                self_destructed.add(event['actor'])
                departed.add(event["actor"])
        if value.get('board') == 'treasure_master' and has_unresolved_departures(round_):
            uncertain_departure_history = True
    for slot, uses in medicines.items():
        if len(uses) > 1:
            issues.append(f"一次性{slot}重复用于轮次{uses}")
    return issues


def evidence_check(item, cache):
    source = (batch.ROOT / item['path']).resolve()
    if not any(source.is_relative_to((batch.ROOT / name).resolve()) for name in ('data', 'docs', 'config', 'outputs/asr_clip_reviews')) or not source.is_file():
        raise ValueError('证据文件缺失或越界：' + item['path'])
    if source not in cache:
        cache[source] = source.read_text(encoding='utf-8-sig')
    raw = cache[source]
    start, end = item.get('start_ms'), item.get('end_ms')
    if start is not None and (type(start) is not int or start < 0):
        raise ValueError('非法证据开始时间')
    if end is not None and (type(end) is not int or end < (start or 0)):
        raise ValueError('非法证据结束时间')
    if not item.get('quote'):
        raise ValueError('缺少证据原句')
    try:
        segments = batch.load_segments(source)
    except (ValueError, AttributeError, TypeError):
        segments = []
    if segments and start is not None:
        if start > max(s['end_ms'] for s in segments) + 1000:
            raise ValueError('证据时间越界')
        local = ''.join(s['text'] for s in segments if s['end_ms'] >= start - 500 and s['start_ms'] <= (end or start) + 500)
        literal = normalized(item['quote']) in normalized(local)
    else:
        literal = normalized(item['quote']) in normalized(raw)
    return {'source_sha256': batch.digest(source), 'literal_match': literal}


def active_scope_entries(entries, *, root=batch.ROOT):
    """Ignore historical plan rows excluded from the current structured scope."""
    return [entry for entry in entries
            if not exclusion_reason({**entry, "season": entry.get("season", "S22")}, root=root)]


def later_rule_alignment_valid(bvid, old_hash, current_hash, cache):
    """Validate a later sourced correction without rewriting the historic review."""
    path = batch.ROOT / 'data/reports/S22_正式规则对齐记录.json'
    if not path.is_file():
        return False
    report = batch.read_json(path)
    row = next((r for r in report.get('items', []) if r.get('bvid') == bvid), None)
    if not row or row.get('state') != 'applied' or row.get('before_sha256') != old_hash or row.get('after_sha256') != current_hash:
        return False
    before_path = (batch.ROOT / row['before_snapshot']).resolve()
    current_path = (batch.ROOT / row['file']).resolve()
    if (not before_path.is_relative_to((batch.ROOT / 'data/archive/S22_formal_rule_alignment').resolve())
            or not current_path.is_relative_to((batch.ROOT / 'data/games/S22').resolve())
            or batch.digest(before_path) != old_hash or batch.digest(current_path) != current_hash):
        return False
    if changed_value(batch.read_json(before_path), row['changes'], allow_legacy_treasure_faction=True) != batch.read_json(current_path):
        return False
    if not row.get('evidence'):
        return False
    return all((audit := evidence_check(ev, cache))['literal_match'] and audit['source_sha256'] == ev['source_sha256']
               for ev in row['evidence'])


def check():
    state = batch.load_state()
    seen, games, errors, warnings, cache, plan_hashes = set(), [], [], [], {}, {}
    previous = batch.read_json(REPORT) if REPORT.is_file() else {}
    completed = {g['bvid']: g for g in previous.get('items', [])}
    for group in GROUPS:
        path = BASE / (group + '_plan.json')
        if not path.is_file():
            errors.append({'group': group, 'error': '计划缺失'})
            continue
        plan_hashes[group] = batch.digest(path)
        plan = batch.read_json(path)
        queue = {x['bvid']: x for x in active_scope_entries(
            batch.read_json(BASE / (group + '_queue.json'))['items'])}
        plan_games = active_scope_entries(plan['games'])
        supplied = {x['bvid'] for x in plan_games}
        for missing in queue.keys() - supplied:
            errors.append({'bvid': missing, 'error': '尚未逐局核查'})
        for game in plan_games:
            bvid = game['bvid']
            try:
                if bvid in seen or bvid not in queue:
                    raise ValueError('重复或范围外对局')
                seen.add(bvid)
                entry = state['items'][bvid]
                if entry['state'] in {'preserved', 'reviewed'}:
                    raise ValueError('不得覆盖保护或人工已确认对局')
                folder = batch.ROOT / entry['output_dir']
                current_hash = batch.digest(folder / 'dossier.json')
                already_saved = completed.get(bvid)
                unchanged_saved_plan = already_saved and all(already_saved.get(key) == val for key, val in game.items())
                later_alignment = unchanged_saved_plan and later_rule_alignment_valid(bvid, already_saved.get('after_sha256'), current_hash, cache)
                if current_hash != game['dossier_sha256'] and not (unchanged_saved_plan and current_hash == already_saved.get('after_sha256')) and not later_alignment:
                    raise ValueError('基础档案哈希变化')
                review = batch.read_json(folder / '复核记录.json')
                questions = review.get('text_review', {}).get('questions', [])
                required = {q['id'] for q in questions}
                decisions = game['decisions']
                ids = [d['id'] for d in decisions]
                if len(ids) != len(set(ids)) or not required <= set(ids):
                    raise ValueError('疑点决策重复或遗漏')
                for d in decisions:
                    if type(d['resolved']) is not bool or not d['conclusion'] or not d['reason']:
                        raise ValueError('决策缺少结论、依据或明确状态')
                    if d['resolved'] and (not d.get('evidence') or d.get('confidence') == 'low'):
                        raise ValueError('已解决项缺少足够依据')
                    for ev in d.get('evidence', []):
                        audit = evidence_check(ev, cache)
                        if not audit['literal_match']:
                            warnings.append({'bvid': bvid, 'id': d['id'], 'kind': 'quote_requires_manual_comparison'})
                if current_hash != game['dossier_sha256']:
                    with zipfile.ZipFile(batch.ROOT / previous['backup']['files']) as snapshot:
                        before = json.loads(snapshot.read(entry['output_dir'] + '/dossier.json').decode('utf-8-sig'))
                else:
                    before = batch.read_json(folder / 'dossier.json')
                after = changed_value(before, game.get('changes', []), allow_legacy_treasure_faction=True)
                content_errors = semantic_issues(after)
                if content_errors:
                    raise ValueError('内容交叉检查：' + '；'.join(content_errors))
                games.append({**game, 'original_question_ids': sorted(required), 'after': after,
                              'changed': before != after, 'output_dir': entry['output_dir']})
            except Exception as exc:
                errors.append({'bvid': bvid, 'error': str(exc)})
    report = {'checked_at': batch.now(), 'valid': not errors, 'games': len(games),
              'original_questions': sum(len(g['original_question_ids']) for g in games),
              'resolved': sum(d['resolved'] for g in games for d in g['decisions'] if d['id'] in g['original_question_ids']),
              'pending': sum(not d['resolved'] for g in games for d in g['decisions'] if d['id'] in g['original_question_ids']),
              'additional_findings': sum(d['id'] not in g['original_question_ids'] for g in games for d in g['decisions']),
              'changed_games': sum(g['changed'] for g in games),
              'content_cross_checks': 'prior_departures, living_targets, one_medicine_per_night, one_time_medicines, repeated_night_deaths, repeated_self_destruct, unique_dance_participants, consecutive_mask_verify_and_card_choices, treasure_first_night_forbidden, treasure_knife_after_all_ordinary_wolves_depart',
              'plan_hashes': plan_hashes,
              'source_hashes': {batch.relative(p): batch.digest(p) for p in cache},
              'errors': errors, 'warnings': warnings}
    batch.atomic_json(BASE / 'check.json', report)
    return report, games


def stamp(ms):
    if ms is None:
        return '未定位'
    sec = ms // 1000
    return f'{sec//3600}:{sec//60%60:02d}:{sec%60:02d}'


def note(decision):
    lines = [decision['conclusion'], '依据与推断：' + decision['reason']]
    for ev in decision.get('evidence', []):
        lines.append(f"来源 {ev['path']} · {stamp(ev.get('start_ms'))}–{stamp(ev.get('end_ms'))}\n原句：{ev['quote']}")
    return '\n'.join(lines)


def render_report(report):
    records = report.get('items', [])
    lines = ['# S22 疑点推理核查', '',
             f"核查 {report['games']} 局；更正业务档案 {report['changed_games']} 局；关联发现 {report['additional_findings']} 项。", '',
             f"原疑点 {report['original_questions']} 项；已核实 {report['resolved']} 项；仍需 review {report['pending']} 项。", '',
             '每项保留原转写、定位和AI推断。AI核查不记录为用户人工复核。', '']
    for pending_only, heading in [(True, '仍需 review'), (False, '已核实与关联修正')]:
        lines.extend(['## ' + heading, ''])
        for game in records:
            decisions = [d for d in game['decisions'] if (not d['resolved']) == pending_only]
            if not decisions:
                continue
            lines.extend([f"### {game['bvid']}", '', f"[打开本局审校](http://127.0.0.1:8766/#{game['bvid']})", ''])
            for d in decisions:
                lines.extend(['- ' + note(d).replace('\n', '\n  '), ''])
    markdown = '\n'.join(lines)
    (batch.ROOT / 'data/reports/S22_疑点推理复核.md').write_text(markdown, encoding='utf-8')
    rows = []
    for game in records:
        for d in game['decisions']:
            rows.append((d['resolved'], game['bvid'], d))
    rows.sort(key=lambda x: x[0])
    body = [f'<h1>S22 疑点推理核查</h1><p>核查 {report["games"]} 局 · 业务更正 {report["changed_games"]} 局</p><p>原疑点 {report["original_questions"]} 项 · 已核实 {report["resolved"]} · 待 review {report["pending"]} · 关联修正发现 {report["additional_findings"]}</p>',
            '<p>AI核查与用户人工复核分别保存。原始转写未修改。待review项排在前面；已核实项可展开回查。</p>']
    for resolved, bvid, d in rows:
        body.append('<details' + ('' if resolved else ' open') + '><summary>' + html.escape(('AI已核实' if resolved else '待review') + ' · ' + bvid + ' · ' + d['conclusion']) + '</summary>')
        body.append(f'<p><a href="http://127.0.0.1:8766/#{bvid}">打开本局审校</a></p><pre>{html.escape(note(d))}</pre></details>')
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>S22疑点推理核查</title><style>body{max-width:1100px;margin:30px auto;padding:0 20px;font:16px/1.7 system-ui;color:#203140;background:#f4f7f9}details{background:white;padding:14px;margin:12px 0;border-radius:8px}summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;font:inherit}a{color:#176e9d}</style>' + ''.join(body) + '</html>'
    (batch.ROOT / 'data/reports/S22_疑点推理复核.html').write_text(page, encoding='utf-8')


def apply():
    report, games = check()
    if not report['valid']:
        raise ValueError('先修复计划校验失败项')
    approval = batch.read_json(BASE / 'primary_approved.json')
    if approval['plan_hashes'] != report['plan_hashes'] or approval.get('source_hashes') != report['source_hashes']:
        raise ValueError('计划在主代理审核后发生变化，需重新审核')
    checkpoint = batch.read_json(REPORT) if REPORT.is_file() else {'items': []}
    done = {x['bvid']: x for x in checkpoint.get('items', [])}
    if not checkpoint.get('backup'):
        with batch.batch_lock():
            state = batch.load_state()
            snapshot = batch.ROOT / 'data/backups' / ('S22疑点推理前_' + batch.now().replace(':', '').replace('+', '_') + '.zip')
            with zipfile.ZipFile(snapshot, 'w', zipfile.ZIP_DEFLATED) as archive:
                for file in [batch.STATE_FILE, batch.ROOT / 'data/reports/S22_转写逐句复核进度.json']:
                    archive.write(file, batch.relative(file))
                for entry in state['items'].values():
                    if entry['state'] == 'preserved':
                        continue
                    for file in (batch.ROOT / entry['output_dir']).glob('*'):
                        if file.is_file():
                            archive.write(file, batch.relative(file))
            state.pop('backup', None)
            batch.backup_database(state)
            checkpoint.update(backup={'files': batch.relative(snapshot), 'database': state['backup']})
        batch.atomic_json(REPORT, checkpoint)
    for game in games:
        bvid = game['bvid']
        if bvid in done and batch.digest(batch.ROOT / game['output_dir'] / 'dossier.json') == done[bvid].get('after_sha256'):
            print(f'{bvid}: 已保存，跳过', flush=True)
            continue
        old_review = batch.read_json(batch.ROOT / game['output_dir'] / '复核记录.json')
        answers = old_review.get('question_answers', {}).copy()
        for d in game['decisions']:
            answers[d['id']] = {**d, 'note': note(d), 'reviewer': 'ai', 'checked_at': batch.now()}
        additions = [d['conclusion'] for d in game['decisions'] if d['id'] not in game['original_question_ids']]
        summary = f"AI疑点推理核查：{sum(d['resolved'] for d in game['decisions'])}项已核实，{sum(not d['resolved'] for d in game['decisions'])}项仍待review。" + ('关联发现：' + '；'.join(additions) if additions else '') + '\n本局判断：' + game.get('summary', '')
        saved = save_item(bvid, {'expected_sha256': game['dossier_sha256'], 'dossier': game['after'],
            'question_answers': answers, 'note': (old_review.get('review_note', '') + '\n' + summary).strip(), 'mark_reviewed': False})
        record = {k: v for k, v in game.items() if k != 'after'}
        record.update(after_sha256=saved['sha256'], saved_at=batch.now())
        done[bvid] = record
        checkpoint.update({k: v for k, v in report.items() if k not in {'errors', 'warnings', 'valid'}})
        checkpoint.update(state='applying', items=list(done.values()), last_bvid=bvid)
        batch.atomic_json(REPORT, checkpoint)
        print(f"{bvid}: 已保存 {'业务更正' if game['changed'] else '核查结论'}", flush=True)
    checkpoint.update(state='complete', completed_at=batch.now())
    batch.atomic_json(REPORT, checkpoint)
    render_report(checkpoint)
    return {k: v for k, v in checkpoint.items() if k != 'items'}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'apply'])
    args = parser.parse_args()
    print(json.dumps(check()[0] if args.command == 'check' else apply(), ensure_ascii=False, indent=2))
