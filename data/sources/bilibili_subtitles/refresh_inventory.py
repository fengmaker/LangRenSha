"""Refresh the six season inventories from saved research evidence; no network."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from season_naming import naming

LABELS = {'verified': '已核时间覆盖', 'pending_text': '有中文轨，全文待核',
          'needs_source': '保留官方源，后续转写或复核'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def normalize_files(value, evidence):
    if isinstance(value, list):
        return [normalize_files(item, evidence) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: normalize_files(item, evidence) for key, item in value.items()}
    if isinstance(result.get('file'), str):
        relative = result['file']
        path = ROOT / relative if relative.startswith('data/') else evidence / relative
        if not path.is_file():
            raise ValueError(f'Missing saved subtitle: {path}')
        result['file'] = path.relative_to(ROOT).as_posix()
    return result


def local_link(path, folder):
    return os.path.relpath(path, folder).replace('\\', '/')


def has_body(source):
    return bool(source) and any(track.get('file') for track in source.get('tracks', []))


def subtitle_link(source, folder):
    tracks = (source or {}).get('tracks', [])
    saved = next((track for track in tracks if track.get('file')), None)
    return f"[原始JSON]({local_link(ROOT / saved['file'], folder)})" if saved else '—'


def planned_source(row):
    """Keep verified subtitles, then indexed Chinese tracks, then official audio."""
    official = row['official_observation']
    if row['selected_source']:
        return row['selected_source'], 'saved_verified', 'use_saved_subtitle'
    if official and official.get('tracks') and not has_body(official):
        return official, 'indexed_body_pending', 'fetch_chinese_subtitle'
    candidate = next((source for source in row['candidate_sources'] if source.get('tracks')), None)
    if candidate:
        return candidate, 'indexed_body_pending', 'fetch_chinese_subtitle'
    if has_body(official):
        return official, 'saved_needs_review', 'review_or_transcribe_official_audio'
    if official:
        return official, 'missing', 'transcribe_official_audio'
    raise ValueError(f"No acquisition source for {row['id']}")


def build_plan(inventory, created_at):
    season = inventory['season']
    evidence = ROOT / inventory['evidence_directory']
    snapshot_path = evidence / f'{season}-official-view.json'
    snapshot = read(snapshot_path)['data']['ugc_season']
    parts = {(item['bvid'], item['cid']): item['page']['part']
             for section in snapshot['sections'] for item in section['episodes']}
    prepared = []
    for row in inventory['entries']:
        source, subtitle_status, action = planned_source(row)
        label_title = row['title']
        if row['scope'] == 'early_supplement':
            label_title = f"{source['video_title']} {source['title']}"
        elif not re.search(r'20\d{6}', label_title):
            ref = row['reference']
            label_title = parts[(ref['bvid'], ref['cid'])]
        prepared.append((row, source, subtitle_status, action, label_title))
    opening = min(re.search(r'20\d{6}', title)[0] for *_, title in prepared
                  if '表演赛' in title and re.search(r'20\d{6}', title))
    anchor = datetime.strptime(opening, '%Y%m%d').date().isoformat()
    end_year = max(int(match[0][:4]) for *_, title in prepared
                   if (match := re.search(r'20\d{6}', title)))
    entries = []
    for row, source, subtitle_status, action, label_title in prepared:
        kind = 'official' if row['official_observation'] and source['bvid'] == row['reference']['bvid'] else 'alternative'
        owner = inventory['collection']['owner'] if kind == 'official' else source['owner']
        entry = {'bvid': source['bvid'], 'cid': source['cid'], 'page': source['page'],
                 'title': row['title'], 'duration_seconds': source['duration_seconds'],
                 'labels': naming(label_title, source['bvid'], source['cid'], source['page'],
                                  anchor, season, end_year=end_year),
                 'source_entry_id': row['id'], 'scope': row['scope'], 'source_kind': kind,
                 'owner_mid': str(owner['mid']), 'url': source['url'],
                 'subtitle_status': subtitle_status, 'collection_action': action,
                 'subtitle_tracks': source.get('tracks', []),
                 'subtitle_checked_at_utc': source.get('checked_at_utc')}
        if label_title != row['title']:
            entry['label_title'] = label_title
        if source['title'] != row['title']:
            entry['source_title'] = source['title']
        if kind == 'alternative':
            entry['official_reference'] = row['reference'] if row['scope'] == 'official_collection' else None
            entry['labels']['warnings'].append('第三方字幕时间戳对应所选视频，不与官方录像共用时间轴')
        if not entry['labels']['event_date_candidate']:
            entry['labels']['warnings'].append('原题未提供完整八位日期，未按相邻视频补齐')
        entries.append(entry)
    # Keep undated entries in their original collection slots. Dated entries are
    # sorted within those slots, including S15's separately counted supplement.
    dated = iter(sorted((entry for entry in entries if entry['labels']['event_date_candidate']),
                        key=lambda entry: (entry['labels']['event_date_candidate'],
                                           entry['labels']['game_number_candidate'] or 999)))
    entries = [next(dated) if entry['labels']['event_date_candidate'] else entry for entry in entries]
    for index, entry in enumerate(entries, 1):
        entry['index'] = index
    sources = dict(Counter(entry['source_kind'] for entry in entries))
    actions = dict(Counter(entry['collection_action'] for entry in entries))
    return {'schema_version': 1, 'season': season,
            'collection_id': snapshot['id'], 'collection_title': snapshot['title'],
            'owner_mid': str(snapshot['mid']), 'created_at_utc': created_at.isoformat(),
            'collection_source': snapshot_path.relative_to(ROOT).as_posix(),
            'resource_inventory': f'data/sources/bilibili_subtitles/{season}/resources.json',
            'anchor': anchor, 'declared_count': snapshot['ep_count'], 'entry_count': len(entries),
            'early_supplement_count': sum(entry['scope'] == 'early_supplement' for entry in entries),
            'source_policy': '保留已核中文字幕；官方全文待取得时继续使用已索引中文轨；已有替代中文字幕来源则沿用；未找到中文字幕则使用官方源，后续转写。',
            'source_counts': sources, 'action_counts': actions, 'entries': entries,
            'coverage_note': ('条数按媒体条目计，含合集附带内容，不等于正式计分局数。'
                              + ('S15另含40条合集前段补充，尚未找到匹配官方源。' if season == 'S15' else '')
                              + '标题标签均为候选，未据相邻视频补齐日期或局次。'),
            'total_duration_seconds': sum(entry['duration_seconds'] for entry in entries)}


seasons = {}
for batch in ['s19-s20', 's15-s18']:
    evidence = BASE / '_evidence' / batch
    source_index = read(evidence / 'resource-index.json')
    catalog = read(evidence / 'official-catalog.json')
    for season, collection in catalog.items():
        seasons[season] = {'season': season, 'collection': collection,
                           'evidence_directory': evidence.relative_to(ROOT).as_posix(), 'entries': []}
    for item in source_index['entries'] + source_index.get('s15_early_supplement', []):
        season = item['season']
        early = item.get('reference_kind') == 'earlier_than_official_collection'
        reference = item.get('reference') or item['official']
        observed = item.get('official_audit') if 'official_audit' in item else item.get('official')
        candidates = item.get('alternatives', item.get('alternative_checks', []))
        selected = item.get('selected')
        state = 'verified' if selected else 'pending_text' if item['status'] == 'pending_text_check' else 'needs_source'
        entry = {'id': reference['id'] if early else f"{reference['bvid']}:p{reference['page']:02d}:{reference['cid']}",
                 'scope': 'early_supplement' if early else 'official_collection', 'season': season,
                 'title': reference['title'], 'reference': reference,
                 'official_observation': observed if not early else None,
                 'selected_source': selected, 'candidate_sources': candidates, 'status': state}
        seasons[season]['entries'].append(normalize_files(entry, evidence))

captured_utc = datetime.now(timezone.utc)
captured_local = captured_utc.astimezone(timezone(timedelta(hours=8)))
progress_rows = []
for season in sorted(seasons, key=lambda value: int(value[1:])):
    inventory = seasons[season]
    folder = BASE / season
    folder.mkdir(exist_ok=True)
    plan = build_plan(inventory, captured_utc)
    plan_path = ROOT / 'data' / 'indexes' / f'{season}_采集计划.json'
    write(plan_path, plan)
    regular = [r for r in inventory['entries'] if r['scope'] == 'official_collection']
    extra = [r for r in inventory['entries'] if r['scope'] == 'early_supplement']
    counts = Counter(r['status'] for r in regular)
    extra_counts = Counter(r['status'] for r in extra)
    available = sum(bool((r['official_observation'] or {}).get('tracks')) for r in regular)
    bodies = sum(has_body(r['official_observation']) for r in regular)
    official_passed = sum(bool(r['selected_source']) and r['selected_source']['source_kind'] == 'official' for r in regular)
    alternative_passed = sum(bool(r['selected_source']) and r['selected_source']['source_kind'] == 'alternative' for r in regular)
    progress = {
        'season': season, 'captured_at_local': captured_local.isoformat(timespec='seconds'),
        'collection_state': 'stopped_for_current_delivery',
        'official': {'entries': len(regular), 'index_checked': len(regular), 'with_chinese_track': available,
                     'without_chinese_track': len(regular) - available, 'subtitle_bodies_saved': bodies,
                     'subtitle_bodies_pending': available - bodies, 'timeline_passed': official_passed,
                     'saved_body_needs_review': bodies - official_passed},
        'resources': {'verified': counts['verified'], 'verified_from_alternative': alternative_passed,
                      'pending_text': counts['pending_text'], 'needs_source': counts['needs_source']},
        'early_supplement': {'entries': len(extra), 'verified': extra_counts['verified'],
                            'pending_text': extra_counts['pending_text'], 'needs_source': extra_counts['needs_source']},
        'collection_plan': {'path': plan_path.relative_to(ROOT).as_posix(), 'entries': plan['entry_count'],
                            'source_counts': plan['source_counts'], 'action_counts': plan['action_counts']},
        'next_step': ('按采集计划取得已索引中文字幕全文；缺完整字幕的条目保留官方源，后续转写或复核。'
                      if counts['pending_text'] or extra_counts['pending_text'] else
                      '缺完整字幕的条目已保留官方源，后续转写或复核。' if counts['needs_source'] or extra_counts['needs_source'] else
                      '本轮清单内资源均已核对；后续仅按新证据更新。'),
    }
    collection = inventory.pop('collection')
    inventory['collection'] = {key: value for key, value in collection.items() if key != 'entries'}
    inventory['captured_at_local'] = progress['captured_at_local']
    inventory['timeline_criterion'] = '字幕末尾达到视频时长95%以上，尾部空档不超过120秒，内部空档不超过120秒；未逐字校对，不证明原录像无剪辑。'
    write(folder / 'resources.json', inventory)
    write(folder / 'progress.json', progress)
    progress_rows.append(progress)
    sid = collection['collection_id']
    collection_url = f'https://space.bilibili.com/19106800/channel/collectiondetail?sid={sid}'
    lines = [f'# {season} 中文字幕资源清单', '', f"官方合集：[{collection['title']}]({collection_url})。",
             f"整理时间：{progress['captured_at_local']}。查看[采集计划]({local_link(plan_path, folder)})、[进度](进度.md)和[逐条来源](resources.json)。", '',
             '“已核时间覆盖”表示实际取得字幕全文并通过时间轴检查；“有中文轨，全文待核”尚不算完整字幕已落实。', '',
             '| 官方标题 | 原视频 | 当前状态 | 已落实或待核的其他源 | 已保存字幕 |', '|---|---|---|---|---|']
    for row in regular:
        ref, chosen = row['reference'], row['selected_source']
        candidates = [r for r in row['candidate_sources'] if r.get('tracks')]
        links = ([chosen] if chosen and chosen['source_kind'] == 'alternative' else candidates[:2])
        alternates = '；'.join(f"[{r['owner']['name']} P{r['page']}]({r['url']})" for r in links) or '—'
        saved = subtitle_link(chosen or row['official_observation'], folder)
        lines.append(f"| {row['title']} | [{ref['bvid']}]({ref['url']}) | {LABELS[row['status']]} | {alternates} | {saved} |")
    if extra:
        lines += ['', '## 官方合集前段的补充清单', '', 'S15 官方当前合集从2024-08-07开始；以下40条对应2024-07-16至08-06，单独计数。相关日期的官方搜索未检出匹配源，检索范围和限制保留在证据目录。', '',
                  '| 分P标题 | 当前状态 | 已落实或待核来源 | 已保存字幕 |', '|---|---|---|---|']
        for row in extra:
            candidates = [r for r in row['candidate_sources'] if r.get('tracks')]
            chosen = row['selected_source']
            links = [chosen] if chosen else candidates[:2]
            alternatives = '；'.join(f"[{r['owner']['name']} P{r['page']}]({r['url']})" for r in links) or '—'
            lines.append(f"| {row['title']} | {LABELS[row['status']]} | {alternatives} | {subtitle_link(chosen, folder)} |")
    lines += ['', '未落实完整字幕的条目保留官方视频源，后续可转写；不再把寻找替代字幕作为采集前提。', '',
              f"原始字幕、官方合集快照与必要来源索引保存在[固定证据目录]({local_link(ROOT / inventory['evidence_directory'], folder)}/)。"]
    (folder / '清单.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    status = '待继续核验全文' if counts['pending_text'] or extra_counts['pending_text'] else '官方源待转写或复核' if counts['needs_source'] else '本轮清单已核对'
    lines = [f'# {season} 完成进度', '', f"整理时间：{progress['captured_at_local']}。状态：**{status}**。", '',
             '| 项目 | 进度 |', '|---|---:|', f'| 官方目录字幕索引 | {len(regular)}/{len(regular)} |',
             f'| 官方有中文轨 / 未见中文轨 | {available} / {len(regular)-available} |',
             f'| 官方字幕全文已保存 | {bodies}/{available} |', f'| 官方字幕时间轴通过 / 已保存但需复核 | {official_passed} / {bodies-official_passed} |',
             f"| 官方条目已落实完整字幕资源（含替代源） | {counts['verified']}/{len(regular)} |",
             f"| 有轨但全文待核 | {counts['pending_text']} |", f"| 缺完整字幕，保留官方源 | {counts['needs_source']} |",
             f"| 采集计划媒体条目 | {plan['entry_count']} |"]
    if extra:
        lines += [f"| 前段补充：已核 / 待全文 / 待补来源 | {extra_counts['verified']} / {extra_counts['pending_text']} / {extra_counts['needs_source']}（共{len(extra)}） |"]
    lines += ['', f"下一步：{progress['next_step']}", '', '[查看逐条清单](清单.md) · [机器可读进度](progress.json) · [返回总览](../README.md)', '',
              '计数按媒体条目和资源核验状态统计，不等于赛事正式计分局数；全文待核和来源缺口均未标作完成。']
    (folder / '进度.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

overview = {'captured_at_local': captured_local.isoformat(timespec='seconds'),
            'collection_state': 'stopped_for_current_delivery', 'seasons': progress_rows}
write(BASE / 'progress.json', overview)
lines = ['# B站中文字幕资源清单与完成进度', '', '固定入口。按赛季保存清单、已取得的字幕与查询证据，以及未完成项目；不再使用tmp目录作为成果位置。', '',
         f"整理时间：{overview['captured_at_local']}。本轮仅整理已有资料；字幕实际观测时间保留在逐条来源中。", '',
         '| 赛季 | 官方条目 | 已落实完整字幕资源 | 有轨全文待核 | 官方源待转写或复核 | 前段补充 | 采集计划与清单 |',
         '|---|---:|---:|---:|---:|---|---|']
for p in progress_rows:
    season, counts, early = p['season'], p['resources'], p['early_supplement']
    extra = f"{early['verified']}已核 / {early['pending_text']}待核（共{early['entries']}）" if early['entries'] else '—'
    lines.append(f"| {season} | {p['official']['entries']} | {counts['verified']} | {counts['pending_text']} | {counts['needs_source']} | {extra} | [计划](../../indexes/{season}_采集计划.json) · [清单]({season}/清单.md) · [进度]({season}/进度.md) |")
lines += ['', '每季采集计划参考 S21 的结构，保留 BV/CID/P、标题、时长和候选标签。entries 中的 BV/CID/P 和 owner_mid 对应实际选定的采集源；第三方源保留 official_reference（S15 前段未找到官方源则为 null），字幕时间戳随所选源使用。declared_count 仅为官方合集声明数量，entry_count 另包含 S15 前段40条补充。', '',
          '采集顺序：复用已保存且通过时间覆盖检查的中文字幕；有中文轨但全文待核的继续取字幕；未找到中文字幕的使用官方源，后续转写。已保存但时间覆盖不通过且无替代字幕的官方条目单独标为复核或转写。S15 前段已有第三方中文轨，继续沿用并保留官方源未找到的说明。', '',
          '每季的`resources.json`保存逐条观测、候选来源和字幕路径；`progress.json`保存分类计数。[_evidence/](_evidence/)仅保留原始字幕、官方合集快照、刷新所需来源索引与必要说明，清理重复响应、搜索缓存和临时脚本日志。', '',
          '保留的刷新输入为两批 official-catalog.json 与 resource-index.json；官方原始合集见各季 Sxx-official-view.json，S15 前段官方源检索的范围与限制见 s15-s18/s15-early-official-search.md。S16 已离线补入此前保存但未登记的61份字幕，其哈希及时间覆盖检查均通过。', '',
          '六季计划是本次清单整理成果；现有 collect_season.py 只接受 config/seasons.json 已登记的赛季，S15–S20 尚未接入批量采集命令。', '',
          '核验口径：实际取得字幕全文，末尾达到视频时长95%以上、尾部及内部空档均不超过120秒。该检查识别明显截短或断段，不等于逐字校对，也不证明原录像未剪辑。', '',
          '离线刷新清单与进度：', '', '```powershell', '.\\.venv\\Scripts\\python.exe data/sources/bilibili_subtitles/refresh_inventory.py', '```', '',
          '该命令只读取固定证据并生成采集计划、清单与进度，不启动采集、转写、网站构建或发布。继续核对时先更新对应研究批次的证据索引，再刷新本入口。']
(BASE / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps({p['season']: p['resources'] for p in progress_rows}, ensure_ascii=False))
