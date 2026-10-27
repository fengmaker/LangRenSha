"""Build a linked media/text/frame review index and verify selected outputs."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

from collect_bilibili_audio import save_json
from season_naming import digest
from season_config import season_codes
import transcribe_review_queue as queue

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEASON = season_codes(ROOT)[-1]


def build(season: str) -> dict:
    queue.configure_season(season)
    base = ROOT/f'data/seasons/{season}'
    plan = json.loads((ROOT/f'data/indexes/{season}_采集计划.json').read_text(encoding='utf-8'))
    frames = json.loads((ROOT/f'data/reports/{season}_发言截图进度.json').read_text(encoding='utf-8'))
    registered = json.loads((ROOT/f'data/reports/{season}_转写入库验收.json').read_text(encoding='utf-8'))
    runs = {r['bvid']: r for r in registered['items']}
    with (base/f'{season}_中文优先复核目录.csv').open(encoding='utf-8-sig', newline='') as stream:
        captions = {r['BVID']: r for r in csv.DictReader(stream)}
    local_plan = queue.load_json(queue.PLAN_PATH)
    local_entries = {entry['bvid']: entry for entry in local_plan['entries']}
    local_verified, issues, rows, cards = [], [], [], []

    def link(path: str, label: str) -> str:
        if not path:
            return ''
        relative = os.path.relpath(ROOT/path, base).replace('\\', '/')
        return f'<a href="{quote(relative, safe="/.:_")}">{escape(label)}</a>'

    for entry in plan['entries']:
        bvid = entry['bvid']
        caption, frame, run = captions[bvid], frames['items'].get(bvid, {}), runs[bvid]
        local = bvid in local_entries
        if local:
            selected = local_entries[bvid]
            try:
                checked = queue.validate_output(selected, ROOT)
                local_verified.append({'bvid': bvid, 'duration_ms': checked['duration_ms'],
                                       'sentence_count': checked['sentence_count'],
                                       'audio_sha256': checked['audio_sha256'], 'full_audio_processed': True})
            except (ValueError, OSError, KeyError, queue.QueueError) as error:
                issues.append({'bvid': bvid, 'kind': 'asr', 'reason': str(error)})
            text, srt = selected['exports']['reading'], selected['exports']['srt']
        else:
            text, srt = caption['中文阅读版'], caption['中文字幕SRT']
        image_path = frame.get('frame_path', '')
        for kind, path in [('audio', caption['音频文件']), ('text', text), ('srt', srt), ('frame', image_path)]:
            if not path or not (ROOT/path).is_file():
                issues.append({'bvid': bvid, 'kind': kind, 'reason': '文件缺失'})
        if image_path and (ROOT/image_path).is_file() and digest(ROOT/image_path) != frame.get('frame_sha256'):
            issues.append({'bvid': bvid, 'kind': 'frame', 'reason': 'SHA256不一致'})
        if run.get('status') != 'registered':
            issues.append({'bvid': bvid, 'kind': 'database', 'reason': run.get('reason')})
        row = {'目录序号': entry['index'], '日期候选': entry['labels']['event_date_candidate'],
               '阶段候选': entry['labels']['phase_label'], '原始标题': entry['title'], 'BVID': bvid, 'CID': entry['cid'],
               '音频文件': caption['音频文件'], '全文来源': '本地Paraformer全文转写' if local else 'B站中文字幕',
               '阅读版': text, 'SRT': srt, '数据库状态': run.get('status'), '数据库片段数': run.get('segments', 0),
               '发言截图': image_path, '截图秒数': frame.get('frame_time_ms', 0)/1000,
               '图层已目视检查': frame.get('selection', {}).get('visual_verified', False),
               '最后游戏日已确认': frame.get('selection', {}).get('last_game_day_verified', False),
               '字幕人工校对状态': '未校对'}
        rows.append(row)
        picture_url = quote(os.path.relpath(ROOT/image_path, base).replace('\\', '/'), safe='/.:_') if image_path else ''
        cards.append(f'<article><h2>{entry["index"]}. {escape(entry["title"])}</h2>'
                     f'<p>{escape(bvid)} · {escape(row["全文来源"])} · 截图 {row["截图秒数"]:.3f} 秒</p>'
                     f'<p>{link(caption["音频文件"], "音频")}　{link(text, "带时间戳全文")}　{link(srt, "SRT")}　{link(image_path, "原尺寸截图")}</p>'
                     f'<a href="{picture_url}"><img loading="lazy" src="{picture_url}" alt="发言画面、座位与票型"></a></article>')
    csv_path = base/f'{season}_音频字幕截图复核目录.csv'
    with csv_path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    html_path = base/f'{season}_音频字幕截图复核.html'
    html_path.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+season+' 媒体复核</title>'
        '<style>body{font:16px/1.6 system-ui;background:#f2f4f7;color:#19202d;max-width:1600px;margin:32px auto;padding:0 20px}'
        'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:20px}article{background:white;padding:18px;border-radius:12px}'
        'h2{font-size:18px;margin:0}p{margin:8px 0}img{width:100%;height:auto}a{color:#125bb3}</style>'
        f'<h1>{season} 音频、字幕与发言截图复核</h1><p>官方合集 {len(rows)} 条；{len(rows)-len(local_entries)} 条中文字幕，'
        f'{len(local_entries)} 条本地全文转写。资料均未人工校对。</p>'
        '<p>红底数字为警徽票，绿底数字为放逐票。截图优先靠后的明确玩家发言；最后游戏日仍需结合字幕和画面核对。原题日期、期次与局次均保留候选口径。</p>'
        '<main>'+''.join(cards)+'</main></html>', encoding='utf-8')
    asr_report = {'season': season, 'audited_at_utc': datetime.now(timezone.utc).isoformat(),
                  'planned': len(local_entries), 'verified': len(local_verified),
                  'full_audio_duration_ms': sum(i['duration_ms'] for i in local_verified),
                  'sentences': sum(i['sentence_count'] for i in local_verified), 'items': local_verified}
    save_json(ROOT/f'data/reports/{season}_全文补转写验收.json', asr_report)
    report = {'season': season, 'audited_at_utc': datetime.now(timezone.utc).isoformat(), 'entries': len(rows),
              'registered_transcripts': registered['registered'], 'database_segments': registered['segments'],
              'local_full_transcripts_verified': len(local_verified),
              'frames_captured': sum(bool(r['发言截图']) for r in rows),
              'frames_visually_verified': sum(bool(r['图层已目视检查']) for r in rows),
              'issues': issues, 'index_csv': csv_path.relative_to(ROOT).as_posix(),
              'review_html': html_path.relative_to(ROOT).as_posix(), 'game_facts_changed': False}
    save_json(ROOT/f'data/reports/{season}_媒体转写汇总验收.json', report)
    return report


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', choices=season_codes(ROOT), default=DEFAULT_SEASON)
    args = parser.parse_args()
    result = build(args.season)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result['issues'] else 0)
