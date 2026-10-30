"""Check one effective S23 game and show formal-value differences; no DB writes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

from audit_s23_review import audit, evidence_objects
from collect_bilibili_audio import save_json
from game_derivations import derive_game, fingerprint
from s23_effective_game import load_effective_games, candidate_values

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ('structure', 'rules', 'evidence')


def field_matches(field, selected):
    field = str(field or '').removeprefix('dossier.')
    for item in selected:
        item = item.removeprefix('dossier.')
        if field in {'seats.names', 'seats.roles'} and item.startswith('seats['):
            if item.endswith('.name' if field == 'seats.names' else '.role'):
                return True
        if field == item or any(a.startswith(b + separator)
                                for a, b in ((field, item), (item, field))
                                for separator in ('.', '[')):
            return True
    return False


def review_context(review, fields):
    if not fields:
        return [review]
    found = []
    def visit(value):
        if isinstance(value, dict):
            if field_matches(value.get('field'), fields):
                found.append(value)
                return
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(review)
    return found


def field_differences(before, after, path=''):
    """Use recorded seat/round/slot/ballot identifiers rather than list order."""
    if before == after:
        return []
    result = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            name = f'{path}.{key}' if path else key
            if key not in before or key not in after:
                result.append({'field': name, 'before': before.get(key), 'after': after.get(key),
                               'change': 'added' if key not in before else 'removed'})
            else:
                result.extend(field_differences(before[key], after[key], name))
    elif isinstance(before, list) and isinstance(after, list):
        identity = next((key for key in ('seat', 'number', 'slot', 'id', 'voter')
                         if before + after and all(isinstance(row, dict) and key in row for row in before + after)
                         and len({row[key] for row in before}) == len(before)
                         and len({row[key] for row in after}) == len(after)), None)
        if identity:
            left, right = ({row[identity]: row for row in rows} for rows in (before, after))
            if path == 'voting.ballots' and list(left) != list(right) and left.keys() == right.keys():
                result.append({'field': path+'.order', 'before': list(left), 'after': list(right),
                               'change': 'reordered'})
            for key in sorted(left.keys() | right.keys(), key=str):
                name = f'{path}.{key}' if identity == 'slot' else f'{path}[{key}]'
                result.extend(field_differences(left.get(key), right.get(key), name))
        else:
            result.append({'field': path, 'before': before, 'after': after, 'change': 'changed'})
    else:
        result.append({'field': path, 'before': before, 'after': after, 'change': 'changed'})
    return result


def direct_impacts(field):
    if '.name' in field or field.startswith('dossier.roster'):
        return ['本局座位与人物关联', '该选手统计关联；不重新核查夜间行动']
    if field.startswith('voting.'):
        return ['所属票轮的票权、票重、计票和最终结果', '结果改变时再追离场及后续票权；结果未变即停止']
    if any(word in field for word in ('sheriff_result', 'badge')):
        return ['对应警徽归属与实际票重', '该人的悍跳成功条件']
    if any(word in field for word in ('night_deaths', 'exile_result', 'self_destruct', 'hunter_shot')):
        return ['对应公布时点及离场', '该座位后续行动、发言和票权；后续状态一致即停止']
    if any(word in field for word in ('.role', '.faction', 'mixed_blood_model', 'learning')):
        return ['本局底牌、个人胜利阵营及相关技能资格', '受影响的胜负、票力和悍跳成功条件']
    return ['仅核对引用本字段的判断；出现具体冲突才沿直接依赖扩大']


def check_game(bvid, *, checks=CHECKS, fields=(), loaded=None):
    started = perf_counter()
    loaded = loaded if loaded is not None else load_effective_games([bvid])
    if not loaded['games']:
        raise ValueError('尚缺本局复核材料：' + bvid)
    game = loaded['games'][0]
    loaded_done = perf_counter()
    evidence_context = review_context(game['review'], fields)
    audit_result = audit([bvid], checks=checks, write_report=False,
                         loaded=loaded, evidence_context=evidence_context)
    audit_done = perf_counter()
    derivations = None
    if 'rules' in checks:
        daily = game['review'].get('daily_audit', {})
        observation = daily.get('terminal_observation')
        derivations = derive_game(game['dossier'], game['voting'],
                                  supplemental={'events': game['supplemental_events']},
                                  endgame=game['endgame'], terminal_observation=observation)['derivations']
    rule_done = perf_counter()
    folder = ROOT / game['entry']['output_dir']
    changes = []
    formal_hashes = {}
    for name, value in candidate_values(game).items():
        if name == 'ai_review.json':
            continue
        formal_name = name.replace('.candidate', '')
        path = folder / formal_name
        before = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
        if path.is_file():
            formal_hashes[formal_name] = hashlib.sha256(path.read_bytes()).hexdigest()
        key = formal_name.removesuffix('.json')
        changes.extend(field_differences(before, value, key))
    if fields:
        changes = [row for row in changes if field_matches(row['field'], fields)]
    evidence = list(evidence_objects(evidence_context))
    for row in changes:
        context = review_context(game['review'], [row['field']])
        row['evidence'] = list(evidence_objects(context))
        row['direct_impacts'] = direct_impacts(row['field'])
    receipt_path = folder / 'formal_import_receipt.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.is_file() else None
    issues = derivations.get('issues', []) if derivations else []
    return {'season': 'S23', 'bvid': bvid, 'mode': 'partial',
            'generated_at_utc': datetime.now(timezone.utc).isoformat(),
            'selected_checks': list(checks), 'selected_fields': list(fields),
            'valid': not audit_result['errors'] and not any(i.get('severity', 'error') == 'error' for i in issues),
            'effective': {key: game[key] for key in ('entry', 'dossier', 'voting', 'endgame')},
            'errors': audit_result['errors'], 'warnings': audit_result['warnings'],
            'rule_derivations': derivations, 'changes': changes, 'evidence': evidence,
            'evidence_gap': '所选字段未关联可直接定位旁证；需按字段证据规范补证。' if fields and not evidence else None,
            'versions': {'effective_sha256': fingerprint(candidate_values(game)),
                         'formal_files': formal_hashes, 'prepared_import_receipt': receipt,
                         'database_receipt_checked': False, 'website_release_checked': False},
            'dependency_bvids': loaded['dependency_bvids'], 'checked_games': 1,
            'rewritten_games': 0, 'formal_database_writes': False,
            'timings_seconds': {**loaded['timings_seconds'], 'validation': audit_done - loaded_done,
                                'rules': rule_done - audit_done, 'total': perf_counter() - started},
            'note': '结构与规则检查不代表事实已核实。差异比较正式文件与当前候选，包含入库适配前的差异。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bvid', required=True)
    parser.add_argument('--checks', nargs='+', choices=CHECKS, default=list(CHECKS))
    parser.add_argument('--field', action='append', default=[], help='字段路径，可重复；限制差异与原文旁证范围')
    parser.add_argument('--output', type=Path, help='显式保存本次局部报告；不覆盖全季报告')
    args = parser.parse_args()
    try:
        result = check_game(args.bvid, checks=args.checks, fields=args.field)
        if args.output:
            save_json(args.output, result)
            print(json.dumps({key: result[key] for key in ('bvid', 'mode', 'valid', 'checked_games', 'timings_seconds')}, ensure_ascii=False, indent=2))
            print('Report:', args.output)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['valid'] else 1
    except (ValueError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
