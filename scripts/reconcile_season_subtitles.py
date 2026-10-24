"""Select the best existing Chinese capture without network requests or text edits."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from audit_season import coverage
from collect_bilibili_audio import save_json
from collect_season import PLAN, STATE, record_success, source_key, write_inventory
import database
from season_naming import digest, preserve_copy, validate_cues

ROOT = Path(__file__).resolve().parents[1]


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
        state['items'][key] = record_success(entry, manifest_path, plan['anchor'], cached=False)
        changes.append({'bvid': entry['bvid'], 'cid': entry['cid'], 'sha256': best['sha256'],
                        'coverage': best['coverage'], 'latest_request_status': subtitles['latest_request_status']})
    report = {'reconciled_at_utc': datetime.now(timezone.utc).isoformat(), 'restored_sources': len(changes),
              'changes': changes, 'network_requests': 0, 'text_modified': False,
              'selection_note': '只比较同一来源已入库快照的时间覆盖；保留所有原件，不代表转写准确率已核验。'}
    state['subtitle_reconciliation'] = report
    write_inventory(plan, state)
    save_json(ROOT/'data/reports/S22_字幕版本整理.json', report)
    return report


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    report = reconcile()
    print(json.dumps({key: value for key, value in report.items() if key != 'changes'}, ensure_ascii=False, indent=2))
