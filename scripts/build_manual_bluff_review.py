"""Build blank S21/S23 date-grouped manual bluff review pages from checked evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path('data/manual_review/S21_悍跳人工复核.html')
REPORT = Path('data/reports/S21/S21_悍跳人工复核页验收.json')
TEMPLATE = Path('scripts/templates/manual_bluff_review.html')
FORMAT = 'masters-manual-bluff-review-v1'


def read(root: Path, path: str | Path):
    return json.loads((root / path).read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def local_file(root: Path, path: str) -> Path:
    resolved = (root / path).resolve()
    if not resolved.is_relative_to((root / 'data').resolve()) or not resolved.is_file():
        raise ValueError(f'本机来源不存在或不在data目录：{path}')
    return resolved


def href(root: Path, path: str) -> str:
    return quote(os.path.relpath(local_file(root, path), root / OUTPUT.parent).replace('\\', '/'), safe='/._-')


def clock(ms: int) -> str:
    seconds = ms // 1000
    return f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'


def build_s21(root: Path) -> tuple[dict, dict]:
    index_path = 'data/reports/S21/S21_文字与截图时点索引.json'
    from rule_config import load_scope
    scope_path = 'config/seasons.json'
    entries = read(root, index_path)['entries']
    excluded = set(load_scope('S21', root)['excluded_bvids'])
    catalog = {row['BVID']: row for row in read(root, 'data/seasons/S21/S21_中文优先复核目录.json')['entries']}
    games, verified_images = [], {}
    for entry in entries:
        bvid = entry['bvid']
        if bvid in excluded or entry['phase_candidate'] not in {'regular', 'finals_week'}:
            raise ValueError(f'{bvid}不在当前保留范围')
        identity_path = f'data/extractions/S21/game_reviews/{bvid}/identity.reviewed.json'
        identity = read(root, identity_path)
        if (identity['bvid'], identity['cid'], identity['page']) != (bvid, entry['cid'], entry['page']):
            raise ValueError(f'{bvid}的身份来源绑定不一致')
        seats = sorted(identity['seats'], key=lambda row: row['seat'])
        if [row['seat'] for row in seats] != list(range(1, 13)):
            raise ValueError(f'{bvid}缺少完整12席名单')
        transcript_path = entry['transcript_selected_path']
        transcript = read(root, transcript_path)
        images, literal_quotes = {}, []
        image_evidence = []
        fantasy_roles = False
        for seat in seats:
            basis = seat.get('role_basis')
            fantasy_roles |= basis == 'terminal_referee_recap_overrides_fantasy_view'
            if isinstance(basis, dict) and basis.get('quote') and basis['quote'] not in literal_quotes:
                literal_quotes.append(basis['quote'])
        for seat in seats:
            for evidence in seat['evidence']:
                path = evidence.get('path', '')
                if evidence.get('kind') == 'literal_transcript':
                    if evidence['quote'] not in literal_quotes:
                        literal_quotes.append(evidence['quote'])
                    continue
                if Path(path).suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}:
                    image_evidence.append(evidence)
        unknown_roles = any('unknown' in row.get('kind', '') for row in image_evidence)
        visual_path = f'data/extractions/S21/game_reviews/{bvid}/visual_review.json'
        if not any('role' in row.get('kind', '') and 'unknown' not in row.get('kind', '') for row in image_evidence):
            visual = read(root, visual_path)
            image_evidence.extend(row for row in visual.get('actually_inspected_frames', [])
                                  if 'role' in row.get('kind', '') and 'unknown' not in row.get('kind', ''))
        for evidence in image_evidence:
            path = evidence['path']
            if path not in verified_images:
                verified_images[path] = sha(local_file(root, path))
            if verified_images[path] != evidence['sha256']:
                raise ValueError(f'{bvid}身份截图SHA不一致：{path}')
            ms = evidence.get('actual_frame_time_ms') or evidence.get('requested_time_ms') or 0
            images[path] = {
                'path': path, 'href': href(root, path), 'sha256': verified_images[path],
                'time_ms': ms, 'label': f"{'座位姓名画面（底牌见复盘原文）' if fantasy_roles or unknown_roles else '身份佐证画面'} · {clock(ms)}",
            }
        if not images:
            raise ValueError(f'{bvid}没有可显示的身份截图')
        source_row = catalog[bvid]
        reading = next((source_row.get(key) for key in ('本地轻校对阅读版', '中文阅读版', '本地全文阅读版')
                        if source_row.get(key)), None)
        if not reading:
            raise ValueError(f'{bvid}没有已有阅读版全文')
        references = []
        for candidate in entry['recap_candidates']:
            start, end = candidate.get('start_ms'), candidate.get('end_ms')
            if start is None or end is None:
                continue
            rows = [row for row in transcript['segments'] if row['end_ms'] >= start and row['start_ms'] <= end]
            references.append('\n'.join(f"[{clock(row['start_ms'])}] {row['text']}" for row in rows))
        if literal_quotes:
            references.insert(0, '身份核实所用原文：\n' + '\n'.join(literal_quotes))
        games.append({
            'review_id': f"S21:{bvid}:p{entry['page']}", 'bvid': bvid,
            'cid': entry['cid'], 'page': entry['page'], 'date': entry['date_candidate'], 'title': entry['title'],
            'identity_sha256': sha(local_file(root, identity_path)),
            'transcript_sha256': sha(local_file(root, transcript_path)),
            'source_paths': {'identity': identity_path, 'transcript': transcript_path, 'reading': reading, 'visual': visual_path},
            'seats': [{'seat': row['seat'], 'name': row['name'], 'role': row['role']} for row in seats],
            'images': list(images.values()),
            'links': {'video': f"https://www.bilibili.com/video/{bvid}/?p={entry['page']}",
                      'transcript': href(root, reading), 'identity': href(root, identity_path)},
            'reference_text': '\n\n'.join(references),
            'evidence_note': ('本局画面含奇幻视角伪装底牌；上方名单采用已核终局复盘更正，请同时查看复盘原文。' if fantasy_roles
                              else '本局截图的底牌栏显示未知；截图用于座位和姓名，名单中的底牌来自已核终局复盘，请同时查看原文。' if unknown_roles else ''),
        })
    games.sort(key=lambda game: (game['date'], next(i for i, e in enumerate(entries) if e['bvid'] == game['bvid'])))
    fingerprint = hashlib.sha256(json.dumps(games, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    payload = {'format': FORMAT, 'season': 'S21', 'source_fingerprint': fingerprint,
               'dates': sorted({game['date'] for game in games}), 'games': games}
    report = {
        'season': 'S21', 'format': FORMAT, 'review_page': OUTPUT.as_posix(),
        'dates': len(payload['dates']), 'media_items': len(games), 'seats': sum(len(game['seats']) for game in games),
        'identity_images': len(verified_images), 'source_fingerprint': fingerprint,
        'all_twelve_seats_selectable': True, 'automatic_bluff_decisions': False,
        'user_review_prefilled': False, 'database_written': False,
        'scope_source_sha256': sha(root / scope_path),
        'index_source_sha256': sha(local_file(root, index_path)),
    }
    return payload, report


def build_s23(root: Path) -> tuple[dict, dict]:
    from prepare_s23_review import segments
    from s23_daily_audit import load_audit, recap_rows

    index_path = 'data/reports/S23/S23_逐局复核计划.json'
    entries = {row['bvid']: row for row in read(root, index_path)['entries']}
    catalog_path = 'data/seasons/S23/S23_中文优先复核目录.json'
    catalog = {row['BVID']: row for row in read(root, catalog_path)['entries']}
    games, verified_images = [], {}
    for identity_file in sorted((root / 'data/games/S23').glob('*/dossier.json')):
        identity_path = identity_file.relative_to(root).as_posix()
        identity = read(root, identity_path)
        if identity['season'] != 'S23' or identity['phase'] != 'regular':
            raise ValueError(f'{identity_path}不在当前S23正赛范围')
        manifest_path = next(row['path'] for row in identity['files'] if row['role'] == 'manifest')
        manifest = read(root, manifest_path)
        bvid, cid, page = manifest['bvid'], manifest['cid'], manifest['page']
        entry = entries[bvid]
        if (entry['cid'], entry['page']) != (cid, page):
            raise ValueError(f'{bvid}的媒体来源绑定不一致')
        seats = sorted(identity['seats'], key=lambda row: row['seat'])
        if [row['seat'] for row in seats] != list(range(1, 13)):
            raise ValueError(f'{bvid}缺少完整12席名单')
        transcript_path = entry['source_path']
        transcript_sha = sha(local_file(root, transcript_path))
        if transcript_sha != entry['source_sha256']:
            raise ValueError(f'{bvid}转写来源SHA不一致')
        frame = entry['frame']
        if (frame['bvid'], frame['cid'], frame['page']) != (bvid, cid, page):
            raise ValueError(f'{bvid}的截图来源绑定不一致')
        image_path = frame['frame_path']
        image_sha = sha(local_file(root, image_path))
        if image_sha != frame['frame_sha256']:
            raise ValueError(f'{bvid}身份截图SHA不一致：{image_path}')
        verified_images[image_path] = image_sha
        review_dir = root / f'data/extractions/S23/game_reviews/{bvid}'
        audit_path = (review_dir / 'daily_audit.json').relative_to(root).as_posix()
        audit = load_audit(review_dir, entry)
        if audit is None:
            raise ValueError(f'{bvid}缺少已核复盘窗口')
        recap = recap_rows(segments(root / transcript_path), audit)
        source_row = catalog[bvid]
        reading = next((source_row.get(key) for key in ('本地轻校对阅读版', '中文阅读版', '本地全文阅读版')
                        if source_row.get(key)), None)
        if not reading:
            raise ValueError(f'{bvid}没有已有阅读版全文')
        ms = frame['frame_time_ms']
        games.append({
            'review_id': f'S23:{bvid}:p{page}', 'bvid': bvid, 'cid': cid, 'page': page,
            'date': identity['date'], 'game_number': identity['game_number'],
            'title': f"{identity['date']} 第{identity['game_number']:02d}局 · {entry['board_name']}",
            'identity_sha256': sha(identity_file), 'transcript_sha256': transcript_sha,
            'source_paths': {'identity': identity_path, 'transcript': transcript_path, 'reading': reading,
                             'manifest': manifest_path, 'recap_audit': audit_path},
            'recap_audit_sha256': sha(local_file(root, audit_path)), 'recap_window': audit['recap_window'],
            'seats': [{'seat': row['seat'], 'name': row['name'], 'role': row['role']} for row in seats],
            'images': [{'path': image_path, 'href': href(root, image_path), 'sha256': image_sha,
                        'time_ms': ms, 'label': f'身份佐证画面 · {clock(ms)}'}],
            'links': {'video': f'https://www.bilibili.com/video/{bvid}/?p={page}',
                      'transcript': href(root, reading), 'identity': href(root, identity_path)},
            'reference_text': '\n'.join(f"[{clock(row['start_ms'])}] {row['text']}" for row in recap),
            'evidence_note': '',
        })
    if len(games) != 75 or {game['bvid'] for game in games} != set(entries):
        raise ValueError('S23人工复核页应覆盖现有全部75局正式档案，与复核计划范围一致')
    games.sort(key=lambda game: (game['date'], game['game_number']))
    fingerprint = hashlib.sha256(json.dumps(games, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    payload = {'format': FORMAT, 'season': 'S23', 'source_fingerprint': fingerprint,
               'dates': sorted({game['date'] for game in games}), 'games': games}
    report = {
        'season': 'S23', 'format': FORMAT, 'review_page': 'data/manual_review/S23_悍跳人工复核.html',
        'dates': len(payload['dates']), 'media_items': len(games), 'seats': sum(len(game['seats']) for game in games),
        'identity_images': len(verified_images), 'source_fingerprint': fingerprint,
        'all_twelve_seats_selectable': True, 'automatic_bluff_decisions': False,
        'user_review_prefilled': False, 'database_written': False,
        'index_source_sha256': sha(local_file(root, index_path)),
        'catalog_source_sha256': sha(local_file(root, catalog_path)),
    }
    return payload, report


def build(root: Path = ROOT, season: str = 'S21') -> tuple[dict, dict]:
    if season == 'S23':
        return build_s23(root)
    if season == 'S21':
        return build_s21(root)
    raise ValueError(f'不支持的人工复核赛季：{season}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', choices=['S21', 'S23'], default='S21', help='人工复核赛季（默认S21）')
    parser.add_argument('--check', action='store_true', help='只校验来源，不生成复核页')
    args = parser.parse_args()
    payload, report = build(season=args.season)
    if not args.check:
        template = (ROOT / TEMPLATE).read_text(encoding='utf-8')
        if template.count('__REVIEW_DATA__') != 1:
            raise ValueError('人工复核模板数据占位符不唯一')
        safe_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
        output = ROOT / report['review_page']
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(template.replace('__REVIEW_SEASON__', args.season).replace('__REVIEW_DATA__', safe_json), encoding='utf-8')
        report_path = ROOT / f'data/reports/{args.season}/{args.season}_悍跳人工复核页验收.json'
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({**report, 'written': not args.check}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
