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
RULE_DOCS = ('docs/12_S22正式版型规则与录入流程.md', 'docs/10_版型规则与夜间顺序.md')


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


def embedded_rule_documents(root=batch.ROOT):
    """Return the fixed rule documents and their individual source hashes."""
    root = Path(root)
    parts, hashes = [], {}
    for relative_path in RULE_DOCS:
        path = root / relative_path
        content = path.read_text(encoding='utf-8')
        hashes[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
        label = '历史证据资料，规则更新以第12号规则册为准。\n\n' if path.name.startswith('10_') else '当前正式录入口径。\n\n'
        parts.append(f'# {path.stem}\n\n{label}{content.rstrip()}')
    return '\n\n---\n\n'.join(parts) + '\n', hashes


def attach_original_questions(decisions, questions):
    enriched = [{**decision, 'original_question': questions.get(decision['id'])}
                for decision in decisions]
    original = sum(decision['original_question'] is not None for decision in enriched)
    return enriched, original, len(enriched) - original


def build():
    state = batch.load_state()
    voting_review_path = batch.ROOT / 'data/reports/S22_投票逐局核对.json'
    voting_review = batch.read_json(voting_review_path) if voting_review_path.is_file() else {'items': [], 'dates': []}
    voting_reviews = {item['bvid']: item for item in voting_review['items']}
    inference = batch.read_json(batch.ROOT / 'data/reports/S22_疑点推理复核.json')
    assert inference['state'] == 'complete'
    rules, rule_hashes = embedded_rule_documents()
    findings = {g['bvid']: g for g in inference['items']}
    alignment_path = batch.ROOT / 'data/reports/S22_正式规则对齐记录.json'
    alignment = batch.read_json(alignment_path) if alignment_path.is_file() else {'items': []}
    aligned = {g['bvid']: g for g in alignment['items'] if g.get('state') == 'applied'}
    index, blobs, templates, frames, hashes = [], {}, {}, set(), {}
    hashes.update(rule_hashes)
    if voting_review_path.is_file():
        hashes[batch.relative(voting_review_path)] = batch.digest(voting_review_path)
    if alignment_path.is_file():
        hashes[batch.relative(alignment_path)] = batch.digest(alignment_path)
    transcript_count = recap_count = decision_count = seats = 0
    voting_games = voting_ballots = voting_choices = voting_pk = voting_registrations = voting_default_abstentions = 0
    wolf_rush_phases = 0
    original_question_count = additional_finding_count = 0
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
        decisions = list(findings.get(bvid, {}).get('decisions', []))
        if bvid in aligned:
            update = aligned[bvid]
            assert update['after_sha256'] == dossier_hash
            decisions = [{**d, 'review_kind': 'historical_inference'} for d in decisions]
            decisions.insert(0, dict(id='formal-rules-20261024-' + bvid, resolved=True, review_kind='formal_rules',
                confidence='high', conclusion='正式规则对齐后的更正', reason=update['reason'],
                evidence=update['evidence']))
        question_rows = review.get('text_review', {}).get('questions', [])
        questions = {q['id']: q for q in question_rows}
        assert len(questions) == len(question_rows)
        decisions, original_count, additional_count = attach_original_questions(decisions, questions)
        assert original_count == len(questions)
        decision_count += len(decisions)
        original_question_count += len(questions)
        additional_finding_count += additional_count
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
        endgame_path = folder / 'endgame.json'
        if endgame_path.is_file():
            endgame = batch.read_json(endgame_path)
            assert endgame['schema_version'] == 1 and endgame['game_slug'] == value['slug']
            assert endgame['source_sha256'] == source_hash, '拍刀依据已变化，请先重新复核并生成 endgame.json'
            hashes[batch.relative(endgame_path)] = batch.digest(endgame_path)
            game['endgame'] = endgame
            wolf_rush_phases += len(endgame['phases'])
        voting_file = folder / 'voting.json'
        if voting_file.is_file():
            from voting_records import validate as validate_voting
            voting = batch.read_json(voting_file)
            validate_voting(voting)
            assert voting['game_slug'] == value['slug']
            voting_audit_file = batch.ROOT / 'data/extractions/S22/voting' / (bvid + '.json')
            voting_audit = batch.read_json(voting_audit_file)
            assert voting_audit['source_sha256'] == source_hash
            assert voting_audit['dossier_sha256'] == dossier_hash
            assert voting_audit['facts'] == voting
            voting_rule = voting_audit.get('voting_rule_source')
            if voting_rule:
                rule_file = batch.ROOT / voting_rule['path']
                assert batch.digest(rule_file) == voting_rule['sha256'], '投票规则已变化，请先重新生成票型'
                hashes[voting_rule['path']] = voting_rule['sha256']
            item['voting_sha256'] = batch.digest(voting_file)
            hashes[batch.relative(voting_file)] = item['voting_sha256']
            hashes[batch.relative(voting_audit_file)] = batch.digest(voting_audit_file)
            game.update(voting=voting, voting_evidence=voting_audit['evidence'], voting_issues=voting_audit['issues'],
                        voting_rule_applications=voting_audit.get('rule_applications', []),
                        voting_human_confirmations=voting_audit.get('human_confirmations', []),
                        voting_election_flow=voting_audit.get('election_flow', []),
                        game_flow=voting_audit.get('game_flow'),
                        eligibility_derivations=voting_audit.get('eligibility_derivations', []),
                        night_death_supplements=voting_audit.get('night_death_supplements', []))
            if bvid in voting_reviews:
                reviewed = voting_reviews[bvid]
                assert reviewed['voting_sha256'] == item['voting_sha256'], '票型已变化，请先运行 review_s22_voting.py'
                assert reviewed['source_sha256'] == source_hash
                review_path = folder / 'voting_review.json'
                assert batch.read_json(review_path) == reviewed
                hashes[batch.relative(review_path)] = batch.digest(review_path)
                game['voting_review'] = reviewed
                item.update(voting_question_count=reviewed['question_count'], voting_pending_count=reviewed['pending_count'],
                            causal_reviewed_count=len(reviewed.get('causal_decisions', [])),
                            causal_resolved_count=sum(d['resolved'] for d in reviewed.get('causal_decisions', [])),
                            voting_days=reviewed['days'],
                            voting_video_checked=bool(reviewed['video_checks']) or any(
                                d.get('media_evidence') for d in reviewed.get('causal_decisions', [])),
                            voting_video_pending=any(not x.get('resolved') and not x.get('resolved_by_rule') and
                                                     not x.get('resolved_by_causal') for x in reviewed['video_checks']) or any(
                                not d['resolved'] and d.get('media_evidence') for d in reviewed.get('causal_decisions', [])))
                frames.update(collect_frames(reviewed))
            voting_games += 1
            voting_ballots += len(voting['ballots'])
            voting_choices += sum(len(b['votes']) for b in voting['ballots'])
            voting_pk += sum(b['stage'] == 'pk' for b in voting['ballots'])
            voting_registrations += len(voting['registrations'])
            voting_default_abstentions += sum(len(a['voters']) for a in voting_audit.get('rule_applications', []))
        if bvid in aligned:
            game['summary'] = '2026-10-24当前更正：' + aligned[bvid]['reason'] + '\n以下为较早的历史推理，涉及已更正字段时以当前档案和顶部规则对齐结论为准。\n' + game['summary']
        blobs[bvid] = base64.b64encode(gzip.compress(compact(game).encode('utf-8'), mtime=0)).decode('ascii')
    causal_reviewed_count = sum(item.get('causal_reviewed_count', 0) for item in index)
    causal_resolved_count = sum(item.get('causal_resolved_count', 0) for item in index)
    causal_manual_count = causal_reviewed_count - causal_resolved_count
    image_data = {}
    for path in sorted(frames):
        file = (batch.ROOT / path).resolve()
        assert file.is_relative_to(batch.ROOT / 'data') and file.is_file()
        content = file.read_bytes()
        hashes[path] = hashlib.sha256(content).hexdigest()
        assert file.suffix.lower() == '.png'
        image_data[path] = 'data:image/png;base64,' + base64.b64encode(content).decode('ascii')
    snapshot_id = hashlib.sha256(compact(sorted(hashes.items())).encode('utf-8')).hexdigest()
    payload = dict(format=FORMAT, snapshot_id=snapshot_id, generated_at=batch.now(),
                   counts=dict(games=len(index), seats=seats, original_questions=original_question_count,
                               additional_findings=additional_finding_count, decisions=decision_count,
                               images=len(image_data), full_transcripts=len(index),
                               voting_games=voting_games, voting_ballots=voting_ballots, voting_choices=voting_choices,
                               voting_pk=voting_pk, voting_registrations=voting_registrations,
                               voting_questions=voting_review.get('question_count', 0),
                               voting_pending=voting_review.get('pending_count', 0),
                               causal_reviewed=causal_reviewed_count, causal_resolved=causal_resolved_count,
                               causal_manual=causal_manual_count,
                               voting_default_abstentions=voting_default_abstentions,
                               wolf_rush_phases=wolf_rush_phases,
                               transcript_segments=transcript_count, recap_segments=recap_count),
                   index=index, templates=templates, game_blobs=blobs, images=image_data,
                   voting_review_dates=voting_review['dates'],
                   rules=rules)
    page = (Path(__file__).parent / 'templates/s22_offline_review.html').read_text(encoding='utf-8')
    assert page.count('__S22_EMBEDDED_DATA__') == 1
    page = page.replace('__S22_EMBEDDED_DATA__', safe_json(payload))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(page, encoding='utf-8')
    # Decode every game again, so a missing or truncated payload fails before delivery.
    assert len(index) == len(state['items'])
    assert decision_count == original_question_count + additional_finding_count
    assert sum(item['decision_count'] for item in index) == decision_count
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
    readme.write_text(f'''S22 离线共享复核

双击 S22_最终复核_离线分享版.html，用较新版本的 Edge 或 Chrome 打开。
只需发送这一个 HTML 文件；无需安装服务、数据库或另带资料文件夹。
内嵌{len(index)}局身份与逐轮事件、{decision_count}项AI推理、全部{len(index)}份全文转写和{len(image_data)}张姓名牌及投票证据截图。
新增{voting_registrations}组上警/警下名单、{voting_ballots}轮投票、{voting_choices}条逐人票型，其中{voting_pk}轮为PK后复投。
其中{voting_default_abstentions}条为按用户确认口径补记的默认弃票；页面及逐人CSV都与原文明确弃票分开标注。
在“警下名单与逐日票型”中按天查看警徽票、放逐票及PK前后各轮；每轮可展开原文并定位全文。
普通放逐票按游戏日展示，平票PK及技能重投另列；两轮均平票时明确记平安日、无人被放逐。
已结合复盘与出局记录交叉核对日期；没有白天自爆却缺少票型的，保留待补录，不视为没有投票。
另有{wolf_rush_phases}个独立“狼人拍刀”环节，列出明确目标、结算结果和原文；未明确的刀路、技能影响与击杀不补造。
已对剩余{causal_reviewed_count}项逐项结合整局转写、存活与投票因果复核，必要时查看原视频、重转写关键原音频；解决{causal_resolved_count}项，仅{causal_manual_count}项仍须人工。每局可展开“逐项因果复核”查看结论、理由和原句。
有票权玩家未明确报出投向时按确认口径默认弃票，与原文明确弃票分别标注。完全缺失的整轮票型不会整体补为弃票。AI复核与人工意见分别保存。
延期警长竞选仅由首日自爆中断未完竞选触发，次日再自爆则警徽流失；否则仍由原警下玩家投给警上候选，同日PK另列。
新增按比赛日期、游戏日及“有疑问 / 待复核”筛选；左侧可查看哪些日期、哪一局、哪一天仍有问题。
当前逐局核对清单有{voting_review.get('question_count', 0)}项疑问、{voting_review.get('pending_count', 0)}项待补录/复核；包括证据不足及本日是否投票尚未确定的项目，不代表全部都是错票。
每局“投票核对清单”列出原因、原文、按秒打开原视频和已保存的截图，可逐项填写人工意见。
已做全范围结构与转写证据检查；逐项更正与原视频查看分别说明，AI检查不代表人工确认。
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
                  games=len(index), seats=seats, original_questions=original_question_count,
                  additional_findings=additional_finding_count, decisions=decision_count,
                  voting_games=voting_games, voting_ballots=voting_ballots, voting_choices=voting_choices,
                  voting_pk=voting_pk, voting_registrations=voting_registrations,
                  voting_questions=voting_review.get('question_count', 0), voting_pending=voting_review.get('pending_count', 0),
                  causal_reviewed=causal_reviewed_count, causal_resolved=causal_resolved_count,
                  causal_manual=causal_manual_count,
                  voting_default_abstentions=voting_default_abstentions,
                  wolf_rush_phases=wolf_rush_phases,
                  original_frames=len(frames), full_transcripts=len(index),
                  transcript_segments=transcript_count, recap_segments=recap_count,
                  database_connection=False, runtime_network_requests=False,
                  source_files_unchanged=True, source_hashes=hashes)
    batch.atomic_json(MANIFEST, report)
    print(compact({k: v for k, v in report.items() if k != 'source_hashes'}))
    return report


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    build()
