"""Register selected platform/local transcripts in the existing raw-text schema."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from collect_bilibili_audio import save_json
import database
from season_naming import digest, validate_cues
import transcribe_review_queue as queue
from season_config import season_codes

ROOT = Path(__file__).resolve().parents[1]


def platform_transcript(row: dict, manifest: dict, season: str) -> Path:
    raw_path = ROOT/row['中文字幕原件']
    document = json.loads(raw_path.read_text(encoding='utf-8'))
    cues = validate_cues(document)
    empty_cues = [{'index': index, 'from': cue['from'], 'to': cue['to']}
                  for index, cue in enumerate(cues) if not cue['content'].strip()]
    output = ROOT/f"data/transcripts/{season}/{row['BVID']}_p{manifest['page']:02d}_platform_zh/transcript.json"
    value = {'schema_version': 1, 'engine': 'Bilibili',
             'model': document.get('type') or 'platform_subtitle', 'language': document.get('lang') or 'zh',
             'status': 'machine_generated_unverified', 'speaker_identity_verified': False,
             'source': {'bvid': manifest['bvid'], 'cid': manifest['cid'], 'page': manifest['page'],
                        'audio_sha256': manifest['audio']['sha256'],
                        'subtitle_file': row['中文字幕原件'], 'subtitle_sha256': digest(raw_path)},
             'segments': [{'start': cue['from'], 'end': cue['to'], 'text': cue['content']}
                          for cue in cues if cue['content'].strip()]}
    if empty_cues:
        value['normalization'] = {'empty_cues_omitted': empty_cues,
                                  'note': '仅不向文字片段表写入平台空白字幕；完整原件按原始哈希保留。'}
    save_json(output, value)
    return output


def run(season: str) -> dict:
    queue.configure_season(season)
    review_path = ROOT/f'data/seasons/{season}/{season}_中文优先复核目录.csv'
    with review_path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    asr_plan_path = ROOT/f'data/reports/{season}/{season}_全文补转写计划.json'
    asr_plan = json.loads(asr_plan_path.read_text(encoding='utf-8')) if asr_plan_path.exists() else {'entries': []}
    local_entries = {entry['bvid']: entry for entry in asr_plan['entries']}
    results = []
    for row in rows:
        bvid, cid = row['BVID'], row['CID']
        try:
            manifest = json.loads((ROOT/f'data/raw/bilibili/{bvid}/p01/manifest.json').read_text(encoding='utf-8'))
            if row['质量筛查'] in queue.SELECTED_QUALITIES:
                if bvid not in local_entries:
                    raise ValueError('等待本地全文转写计划')
                verified = queue.validate_output(local_entries[bvid], ROOT)
                path = verified['output_dir']/'transcript.json'
                kind = 'local_full_audio'
            else:
                path = platform_transcript(row, manifest, season)
                kind = 'platform_chinese_subtitle'
            value = json.loads(path.read_text(encoding='utf-8'))
            source = value['source']
            if (source['bvid'] != bvid or str(source['cid']) != str(cid)
                    or source['audio_sha256'] != manifest['audio']['sha256']):
                raise ValueError('转写来源与原始音轨不一致')
            with database.connect() as conn:
                stored = conn.execute("SELECT id FROM sources WHERE platform='bilibili' AND external_key=%s", (f'{bvid}:{cid}',)).fetchone()
                if stored is None:
                    raise ValueError('原始媒体尚未登记')
                run_id = database.import_transcript(conn, stored['id'], path)
                count = conn.execute('SELECT count(*) AS n FROM transcript_segments WHERE run_id=%s', (run_id,)).fetchone()['n']
                if count != len(value['segments']):
                    raise ValueError('数据库转写片段数量不一致')
            results.append({'bvid': bvid, 'cid': cid, 'status': 'registered', 'kind': kind,
                            'run_id': str(run_id), 'segments': count,
                            'transcript': path.relative_to(ROOT).as_posix(), 'sha256': digest(path)})
        except (ValueError, OSError, KeyError, queue.QueueError) as error:
            results.append({'bvid': bvid, 'cid': cid, 'status': 'pending', 'reason': str(error)})
        print(f"{bvid}: {results[-1]['status']}", flush=True)
    report = {'season': season, 'updated_at_utc': datetime.now(timezone.utc).isoformat(),
              'planned': len(rows), 'registered': sum(r['status'] == 'registered' for r in results),
              'segments': sum(r.get('segments', 0) for r in results),
              'game_facts_changed': False, 'verification_status': 'unverified', 'items': results}
    save_json(ROOT/f'data/reports/{season}/{season}_转写入库验收.json', report)
    return {k: v for k, v in report.items() if k != 'items'}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', choices=season_codes(ROOT), default=season_codes(ROOT)[-1])
    args = parser.parse_args()
    result = run(args.season)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['registered'] == result['planned'] else 1)
