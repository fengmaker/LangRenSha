"""Build one portable HTML review file from disk; never connect to the database."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import batch_s22 as batch
from game_records import template

OUTPUT = batch.ROOT / 'data/exports/S22_最终复核_离线分享版.html'
MANIFEST = batch.ROOT / 'data/reports/S22_离线分享版验收.json'
FORMAT = 's22-offline-review-v1'


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def safe_json(value):
    return compact(value).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def collect_frames(value):
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'frame_path' and isinstance(item, str):
                found.add(item)
            else:
                found.update(collect_frames(item))
    elif isinstance(value, list):
        for item in value:
            found.update(collect_frames(item))
    return found


def build():
    state = batch.load_state()
    inference = batch.read_json(batch.ROOT / 'data/reports/S22_疑点推理复核.json')
    assert inference['state'] == 'complete'
    findings = {g['bvid']: g for g in inference['items']}
    index, blobs, templates, frames, hashes = [], {}, {}, set(), {}
    transcript_count = recap_count = decision_count = seats = 0
    for bvid, entry in state['items'].items():
        folder = batch.ROOT / entry['output_dir']
        value = batch.read_json(folder / 'dossier.json')
        review_file = folder / '复核记录.json'
        review = batch.read_json(review_file) if review_file.is_file() else {}
        board = value['board']
        templates[board] = template(board)
        source = batch.ROOT / entry['source_path']
        source_hash, dossier_hash = batch.digest(source), batch.digest(folder / 'dossier.json')
        hashes[entry['source_path']] = source_hash
        hashes[batch.relative(folder / 'dossier.json')] = dossier_hash
        source_segments = batch.load_segments(source)
        transcript_count += len(source_segments)
        recap = review.get('recap_segments', [])
        recap_count += len(recap)
        decisions = findings.get(bvid, {}).get('decisions', [])
        questions = {q['id']: q for q in review.get('text_review', {}).get('questions', [])}
        decisions = [{**d, 'original_question': questions.get(d['id'])} for d in decisions]
        decision_count += len(decisions)
        frame_info = review.get('frame_seats', {})
        frames.update(collect_frames(frame_info))
        seats += len(value['seats'])
        item = {k: entry.get(k) for k in ('bvid', 'date', 'game_number', 'title', 'board_name')}
        item.update(board=board, dossier_sha256=dossier_hash, decision_count=len(decisions),
                    names=' '.join(s['name'] or '' for s in value['seats']),
                    protected=entry['state'] == 'preserved')
        index.append(item)
        game = dict(entry=item, dossier=value, frame_seats=frame_info, decisions=decisions,
                    summary=findings.get(bvid, {}).get('summary', '此前确认的保护样例。'),
                    source_path=entry['source_path'], source_sha256=source_hash,
                    recap_segments=recap, full_transcript=source_segments)
        blobs[bvid] = base64.b64encode(gzip.compress(compact(game).encode('utf-8'), mtime=0)).decode('ascii')
    image_data = {}
    for path in sorted(frames):
        file = (batch.ROOT / path).resolve()
        assert file.is_relative_to(batch.ROOT / 'data') and file.is_file()
        content = file.read_bytes()
        hashes[path] = hashlib.sha256(content).hexdigest()
        assert file.suffix.lower() == '.png'
        image_data[path] = 'data:image/png;base64,' + base64.b64encode(content).decode('ascii')
    rule_path = batch.ROOT / 'docs/10_版型规则与夜间顺序.md'
    hashes[batch.relative(rule_path)] = batch.digest(rule_path)
    snapshot_id = hashlib.sha256(compact(sorted(hashes.items())).encode('utf-8')).hexdigest()
    payload = dict(format=FORMAT, snapshot_id=snapshot_id, generated_at=batch.now(),
                   counts=dict(games=len(index), seats=seats, original_questions=inference['original_questions'],
                               decisions=decision_count, images=len(image_data)),
                   index=index, templates=templates, game_blobs=blobs, images=image_data,
                   rules=rule_path.read_text(encoding='utf-8'))
    page = (Path(__file__).parent / 'templates/s22_offline_review.html').read_text(encoding='utf-8')
    assert page.count('__S22_EMBEDDED_DATA__') == 1
    page = page.replace('__S22_EMBEDDED_DATA__', safe_json(payload))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(page, encoding='utf-8')
    # Decode every game again, so a missing or truncated payload fails before delivery.
    assert len(index) == 149 and seats == 1788 and decision_count == 363
    for item in index:
        decoded = json.loads(gzip.decompress(base64.b64decode(blobs[item['bvid']])))
        assert decoded['entry']['dossier_sha256'] == item['dossier_sha256']
        assert decoded['full_transcript']
        for decision in decoded['decisions']:
            for ev in decision.get('evidence', []):
                assert ev.get('quote')
    assert '<script src=' not in page and 'fetch(' not in page and '127.0.0.1' not in page
    assert all(batch.digest(batch.ROOT / p) == digest for p, digest in hashes.items())
    readme = OUTPUT.parent / 'S22_离线复核使用说明.txt'
    readme.write_text('''S22 离线共享复核

双击 S22_最终复核_离线分享版.html，用较新版本的 Edge 或 Chrome 打开。
只需发送这一个 HTML 文件；无需安装服务、数据库或另带资料文件夹。
内嵌149局身份与逐轮事件、363项AI推理、全部149份全文转写和78张姓名牌原图。
没有内嵌音视频，页面上的“打开原视频”按需访问哔哩哔哩。

1. 填写复核人姓名或代号；可按日期、局次、版型或BV号筛选分工。
2. 逐局核对，对AI结论、座位或事件填写赞同/异议及理由。
3. 意见会保存在当前浏览器；离开前点击“导出我的意见”，把JSON文件交回汇总。
4. “导入意见”可查看其他人的反馈，或恢复自己此前导出的进度。

本文件是生成时的数据快照。多人各自核对，不会自动同步，也不会写入项目数据库。
HTML本身不会因填写意见而改写；分享或备份意见需要导出的JSON文件。
''', encoding='utf-8')
    archive_path = OUTPUT.with_suffix('.zip')
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(OUTPUT, OUTPUT.name)
        archive.write(readme, readme.name)
    report = dict(valid=True, built_at=batch.now(), snapshot_id=snapshot_id, output=batch.relative(OUTPUT),
                  html_bytes=OUTPUT.stat().st_size, zip_bytes=archive_path.stat().st_size,
                  games=len(index), seats=seats, original_questions=inference['original_questions'],
                  decisions=decision_count, original_frames=len(frames), full_transcripts=len(index),
                  transcript_segments=transcript_count, recap_segments=recap_count,
                  database_connection=False, runtime_network_requests=False,
                  source_files_unchanged=True, source_hashes=hashes)
    batch.atomic_json(MANIFEST, report)
    print(compact({k: v for k, v in report.items() if k != 'source_hashes'}))
    return report


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    build()
