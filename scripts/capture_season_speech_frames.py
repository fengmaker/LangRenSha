"""Capture a late player-speech frame per source, preserving selection evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from capture_bilibili_frame import capture
from collect_bilibili_audio import save_json
import database
from season_naming import digest, validate_cues
from season_config import load_season, season_codes

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEASON = season_codes(ROOT)[-1]
COMMAND = re.compile(r"(?:[1-9]|1[0-2]|[一二三四五六七八九十]{1,2})号(?:玩家|选手|的|来|你|您|先|可以|开始|继续|再|再次|最后|进行|\s|[，,。])*请(?:你|您)?发言")


def choose_speech(cues: list[dict], duration: float) -> dict | None:
    """Prefer the latest explicit numbered speech handoff, never a fixed fraction."""
    candidates = [c for c in cues if COMMAND.search(c['content'])
                  and len(c['content']) <= 65 and c['to'] + 4 < duration
                  and not any(word in c['content'] for word in ('复盘', '采访', '遗言'))]
    if not candidates:
        return None
    cue = max(candidates, key=lambda c: c['from'])
    # Leave enough time for the camera to switch from the judge to the player.
    second = round(min(cue['to'] + 8, duration - 2), 3)
    dawns = [c for c in cues if c['from'] < cue['from'] and '天亮了' in c['content']]
    return {'seconds': second, 'cue': cue,
            'preceding_dawn_cue': dawns[-1] if dawns else None,
            'method': 'latest_explicit_numbered_player_speech_handoff_plus_8_seconds',
            'last_game_day_verified': False, 'visual_verified': False,
            'note': '优先最晚的明确座位发言指令；游戏日和画面内容仍需目视核对。'}


def source_cues(bvid: str, page: int, item: dict, season: str) -> tuple[list[dict], str]:
    local = ROOT / f'data/transcripts/{season}/{bvid}_p{page:02d}_funasr_full/transcript.json'
    if local.is_file():
        value = json.loads(local.read_text(encoding='utf-8'))
        if value.get('full_audio_processed'):
            return [{'from': s['start_ms']/1000, 'to': s['end_ms']/1000, 'content': s['text']}
                    for s in value['segments']], local.relative_to(ROOT).as_posix()
    tracks = item.get('exports', {}).get('subtitles', [])
    if not tracks:
        raise ValueError('等待中文字幕或本地全文转写')
    choices = []
    for track in tracks:
        path = ROOT / track['raw']
        cues = validate_cues(json.loads(path.read_text(encoding='utf-8')))
        choices.append((max(c['to'] for c in cues), cues, track['raw']))
    _, cues, path = max(choices, key=lambda choice: choice[0])
    return cues, path


def run(season: str, limit: int | None = None, bvid_filter: str | None = None,
        auth: str = 'none', cookies_file: Path | None = None) -> dict:
    load_season(season, ROOT)
    plan = json.loads((ROOT/f'data/indexes/{season}_采集计划.json').read_text(encoding='utf-8'))
    collection = json.loads((ROOT/f'data/reports/{season}_采集进度.json').read_text(encoding='utf-8'))
    progress_path = ROOT/f'data/reports/{season}_发言截图进度.json'
    progress = json.loads(progress_path.read_text(encoding='utf-8')) if progress_path.exists() else {'season': season, 'items': {}}
    attempted = 0
    for entry in plan['entries']:
        bvid, cid, page = entry['bvid'], entry['cid'], entry['page']
        if bvid_filter and bvid != bvid_filter:
            continue
        old = progress['items'].get(bvid, {})
        item = collection['items'].get(f'{bvid}:{cid}', {})
        if item.get('status') not in {'complete', 'audio_only'}:
            continue
        try:
            cues, text_path = source_cues(bvid, page, item, season)
            text_sha256 = digest(ROOT/text_path)
        except (ValueError, OSError, KeyError):
            cues, text_path, text_sha256 = None, None, None
        if old.get('status') == 'captured':
            path = ROOT/old['frame_path']
            if (path.is_file() and digest(path) == old['frame_sha256']
                    and text_path == old.get('text_source')
                    and text_sha256 is not None and text_sha256 == old.get('text_source_sha256')):
                continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        try:
            if cues is None:
                raise ValueError('等待可读取的中文字幕或本地全文转写')
            selected = choose_speech(cues, entry['duration_seconds'])
            if selected is None:
                raise ValueError('未找到明确的座位发言指令，需人工选时点')
            folder = ROOT/f'data/extractions/{season}/speech_frames/{bvid}'
            second = selected['seconds']
            frame = folder/f'{bvid}_{second:09.3f}.png'
            if not frame.is_file():
                capture(bvid, cid, [second], folder, auth, cookies_file)
            receipt = {'bvid': bvid, 'cid': cid, 'page': page, 'status': 'captured',
                       'date_candidate': entry['labels']['event_date_candidate'],
                       'game_number_candidate': entry['labels']['game_number_candidate'],
                       'frame_time_ms': round(second*1000), 'frame_path': frame.relative_to(ROOT).as_posix(),
                       'frame_sha256': digest(frame), 'text_source': text_path, 'text_source_sha256': text_sha256,
                       'selection': selected, 'source_url': f'https://www.bilibili.com/video/{bvid}/?p={page}&t={second}',
                       'captured_at_utc': datetime.now(timezone.utc).isoformat()}
            with database.connect() as conn:
                source = conn.execute("SELECT id FROM sources WHERE platform='bilibili' AND external_key=%s", (f'{bvid}:{cid}',)).fetchone()
                if source is None:
                    raise ValueError('原始媒体尚未登记数据库')
                artifact_id = database.artifact(conn, source['id'], frame, 'frame', receipt)
                receipt['artifact_id'] = str(artifact_id)
            save_json(folder/'capture.json', receipt)
            progress['items'][bvid] = receipt
        except Exception as error:
            # Decoder errors can contain temporary signed URLs; retain the type only.
            progress['items'][bvid] = {'status': 'pending_review' if isinstance(error, ValueError) else 'failed',
                                       'bvid': bvid, 'error_type': type(error).__name__,
                                       'reason': str(error) if isinstance(error, ValueError) else '原视频截帧失败'}
        progress['updated_at_utc'] = datetime.now(timezone.utc).isoformat()
        progress['captured'] = sum(v.get('status') == 'captured' for v in progress['items'].values())
        progress['planned'] = len(plan['entries'])
        save_json(progress_path, progress)
        print(f"{bvid}: {progress['items'][bvid]['status']} ({progress['captured']}/{len(plan['entries'])})", flush=True)
    return {k: v for k, v in progress.items() if k != 'items'}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', choices=season_codes(ROOT), default=DEFAULT_SEASON)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--bvid')
    parser.add_argument('--auth', choices=['none', 'cookies'], default='none')
    parser.add_argument('--cookies-file', type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.season, args.limit, args.bvid, args.auth, args.cookies_file), ensure_ascii=False, indent=2))
