"""Select the best existing Chinese capture without network requests or text edits."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from audit_season import coverage
from collect_bilibili_audio import save_json
from collect_season import COLLECTION_ID, PLAN, SEASON, STATE, source_key
import database
from media_ingest import validate_media
from season_naming import digest, export_source, naming, preserve_copy, validate_cues

ROOT = Path(__file__).resolve().parents[1]


def record_success(entry: dict, manifest_path: Path, anchor: str) -> dict:
    """Explicitly archive and register a reconciled historical subtitle capture."""
    checked = validate_media(manifest_path, entry['bvid'], entry['page'])
    manifest = checked['manifest']
    if manifest['cid'] != entry['cid']:
        raise ValueError('当前 CID 与冻结的合集清单不符')
    labels = naming(manifest['title'], entry['bvid'], entry['cid'], entry['page'], anchor, SEASON)
    exports = export_source(manifest_path, labels)
    manifest['collection_context'] = {
        'season': SEASON, 'collection_id': COLLECTION_ID,
        'labels': labels, 'exports': exports,
    }
    save_json(manifest_path, manifest)
    registered = database.import_media(manifest_path, entry['bvid'], entry['page'])
    tracks = exports['subtitles']
    return {
        'status': 'complete' if tracks else 'audio_only',
        'bvid': entry['bvid'], 'cid': entry['cid'],
        'source_id': registered['source_id'],
        'audio_bytes': manifest['audio']['bytes'],
        'audio_sha256': manifest['audio']['sha256'],
        'subtitle_status': (manifest.get('subtitles') or {}).get('status'),
        'subtitle_tracks': len(tracks),
        'subtitle_segments': sum(track['segment_count'] for track in tracks),
        'labels': labels, 'exports': exports, 'cached': False,
        'finished_at_utc': datetime.now(timezone.utc).isoformat(),
    }


def write_inventory(plan: dict, state: dict) -> None:
    """Refresh the legacy archive inventory after explicit reconciliation."""
    target = ROOT / f'data/seasons/{SEASON}'
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    for entry in plan['entries']:
        result = state['items'].get(source_key(entry), {})
        labels = result.get('labels') or entry['labels']
        exports = result.get('exports') or {}
        tracks = exports.get('subtitles') or []
        rows.append({
            '目录序号': entry['index'], '状态': result.get('status', 'pending'),
            '标题日期候选': labels['event_date_candidate'], '归档周次': labels['week_number'],
            '阶段候选': labels['phase_label'], '正赛期次候选': labels['issue_candidate'],
            '局次候选': labels['game_number_candidate'], '配置候选': labels['board_candidate'],
            '原始标题': entry['title'], 'BVID': entry['bvid'], 'CID': entry['cid'],
            '分P': entry['page'], '音频文件': exports.get('audio'),
            '音频字节数': result.get('audio_bytes'), '字幕段数': result.get('subtitle_segments'),
            '字幕状态': result.get('subtitle_status'),
            '字幕原件': ' | '.join(track['raw'] for track in tracks),
            'SRT': ' | '.join(track['srt'] for track in tracks),
            '阅读版': ' | '.join(track['readable'] for track in tracks),
            '待核事项': ' | '.join(labels['warnings']), '错误': result.get('reason', ''),
        })
    temporary = target / f'{SEASON}_音频与字幕总目录.csv.tmp'
    with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(target / f'{SEASON}_音频与字幕总目录.csv')
    counts = Counter(row['状态'] for row in rows)
    state['summary'] = {
        'planned': len(rows), 'status_counts': dict(counts),
        'audio_ready': sum(row['状态'] in {'complete', 'audio_only'} for row in rows),
        'with_subtitles': counts.get('complete', 0),
        'audio_bytes': sum(row['音频字节数'] or 0 for row in rows),
        'subtitle_segments': sum(row['字幕段数'] or 0 for row in rows),
    }
    state['updated_at_utc'] = datetime.now(timezone.utc).isoformat()
    save_json(STATE, state)
    save_json(target / f'{SEASON}_音频与字幕总目录.json', {
        'plan_metadata': {key: value for key, value in plan.items() if key != 'entries'},
        'summary': state['summary'], 'entries': rows,
    })


def choose_best(candidates: list[dict], duration: float) -> dict | None:
    chinese = []
    for candidate in candidates:
        language = str(candidate['metadata'].get('language') or '')
        if language != 'ai-zh' and not language.startswith('zh'):
            continue
        path = ROOT / candidate['relative_path']
        if not path.resolve().is_relative_to((ROOT / 'data/archive').resolve()):
            raise ValueError('字幕候选必须来自已入库的证据快照')
        if digest(path) != candidate['sha256']:
            raise ValueError('已入库字幕快照的哈希不一致')
        score = coverage(validate_cues(json.loads(path.read_text(encoding='utf-8'))), duration)
        chinese.append({**candidate, 'coverage': score})
    return max(chinese, key=lambda item: (
        item['coverage']['covered_seconds'],
        min(item['coverage']['last_seconds'], duration),
        item['coverage']['characters']), default=None)


def reconcile() -> dict:
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    state = json.loads(STATE.read_text(encoding='utf-8'))
    if state.get('current_run', {}).get('state') == 'running':
        raise ValueError('采集仍在运行，请完成后再整理既有字幕版本')
    with database.connect() as conn:
        artifacts = conn.execute("""SELECT s.external_key,a.relative_path,a.sha256,a.metadata
            FROM artifacts a JOIN sources s ON s.id=a.source_id
            WHERE s.platform='bilibili' AND a.kind='subtitle'""").fetchall()
    by_source = {}
    for item in artifacts:
        by_source.setdefault(item['external_key'], []).append(item)
    changes = []
    for entry in plan['entries']:
        key = source_key(entry)
        best = choose_best(by_source.get(key, []), entry['duration_seconds'])
        if best is None:
            continue
        manifest_path = ROOT/'data/raw/bilibili'/entry['bvid']/f"p{entry['page']:02d}"/'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        subtitles = manifest.get('subtitles') or {}
        tracks = subtitles.get('tracks') or []
        if any(digest(manifest_path.parent/track['file']) == best['sha256'] for track in tracks):
            continue
        name = f"subtitle.retained.{best['metadata']['language']}.{best['sha256'][:12]}.raw.json"
        preserve_copy(ROOT/best['relative_path'], manifest_path.parent/name)
        track = {**best['metadata'], 'file': name,
                 'retained_from_snapshot': best['relative_path'],
                 'retained_original_ingested_from': best['metadata'].get('ingested_from'),
                 'selection_note': '同一 BV/CID 已保存中文版本中按时间覆盖择优，未拼接或修改文字',
                 'accuracy_verified': False}
        subtitles['latest_request_status'] = subtitles.get('latest_request_status', subtitles.get('status'))
        subtitles['status'] = 'retained_previous_chinese_capture'
        subtitles['tracks'] = [track] + [t for t in tracks if not (t.get('language') == 'ai-zh' or str(t.get('language', '')).startswith('zh'))]
        manifest['subtitles'] = subtitles
        save_json(manifest_path, manifest)
        state['items'][key] = record_success(entry, manifest_path, plan['anchor'])
        changes.append({'bvid': entry['bvid'], 'cid': entry['cid'], 'sha256': best['sha256'],
                        'coverage': best['coverage'], 'latest_request_status': subtitles['latest_request_status']})
    report = {'reconciled_at_utc': datetime.now(timezone.utc).isoformat(), 'restored_sources': len(changes),
              'changes': changes, 'network_requests': 0, 'text_modified': False,
              'selection_note': '只比较同一来源已入库快照的时间覆盖；保留所有原件，不代表转写准确率已核验。'}
    state['subtitle_reconciliation'] = report
    write_inventory(plan, state)
    save_json(ROOT/'data/reports/S22/S22_字幕版本整理.json', report)
    return report


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    report = reconcile()
    print(json.dumps({key: value for key, value in report.items() if key != 'changes'}, ensure_ascii=False, indent=2))
