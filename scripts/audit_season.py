"""Offline completeness and subtitle-coverage audit for the downloaded S22 archive."""

from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from collect_bilibili_audio import save_json
import database
from media_ingest import validate_media
from season_naming import validate_cues

ROOT=Path(__file__).resolve().parents[1]


def coverage(cues: list[dict],duration: float) -> dict:
    intervals=sorted((max(0,row['from']),min(duration,row['to'])) for row in cues if row['from']<duration)
    total=0.0; end=0.0
    for left,right in intervals:
        if right>max(left,end):
            total+=right-max(left,end)
        end=max(end,right)
    last=max(row['to'] for row in cues)
    chars=sum(len(row['content'].strip()) for row in cues)
    warnings=[]
    if last<duration*0.8:
        warnings.append('最后字幕早于音轨时长的80%，疑似只覆盖前段')
    if duration>=1800 and len(cues)<100:
        warnings.append('长音轨仅有少量字幕段，疑似片头/宣传字幕')
    if duration>=1800 and chars<500:
        warnings.append('长音轨字幕文字不足500字符，需核对是否缺少主体内容')
    if total/duration<0.25:
        warnings.append('字幕时间区间覆盖不足25%，需要核对')
    return {'segments':len(cues),'characters':chars,'first_seconds':min(row['from'] for row in cues),
            'last_seconds':last,'covered_seconds':round(total,3),'covered_ratio':round(total/duration,4),
            'screening_status':'needs_review' if warnings else 'no_short_caption_signal',
            'warnings':warnings,'accuracy_verified':False}


def audit() -> dict:
    plan=json.loads((ROOT/'data/indexes/S22_采集计划.json').read_text(encoding='utf-8'))
    progress=json.loads((ROOT/'data/reports/S22_采集进度.json').read_text(encoding='utf-8'))
    rows=[];problems=[];total_bytes=0;raw_tracks=0
    for entry in plan['entries']:
        key=f"{entry['bvid']}:{entry['cid']}"
        item=progress['items'].get(key,{})
        row={'目录序号':entry['index'],'BVID':entry['bvid'],'CID':entry['cid'],'原始标题':entry['title'],
             '音频状态':item.get('status','pending'),'日期候选':entry['labels']['event_date_candidate'],
             '归档周次':entry['labels']['week_number'],'阶段候选':entry['labels']['phase_label'],
             '局次候选':entry['labels']['game_number_candidate'],'音频文件':None,'平台字幕状态':item.get('subtitle_status'),
             '平台报告轨道数':None,'中文字幕状态':'unavailable',
             '字幕段数':0,'字幕字符数':0,'字幕覆盖比例':None,'字幕最后秒数':None,
             '中文字幕原件':None,'中文字幕SRT':None,'中文阅读版':None,'质量筛查':'no_zh_subtitle',
             '字幕待核事项':'','命名待核事项':' | '.join(entry['labels']['warnings'])}
        try:
            if item.get('status') not in {'complete','audio_only'}:
                raise ValueError('本条采集未完成')
            path=ROOT/'data/raw/bilibili'/entry['bvid']/f"p{entry['page']:02d}"/'manifest.json'
            checked=validate_media(path,entry['bvid'],entry['page'])
            if checked['manifest']['cid']!=entry['cid']:
                raise ValueError('CID 不一致')
            human_audio=ROOT/item['exports']['audio']
            if not os.path.samefile(human_audio,checked['audio_path']):
                raise ValueError('整理目录音频不是原始音轨的硬链接')
            row['音频文件']=item['exports']['audio']
            row['平台报告轨道数']=(checked['manifest'].get('subtitles') or {}).get('count')
            total_bytes+=checked['manifest']['audio']['bytes']
            assessments=[]
            for track in item['exports']['subtitles']:
                raw_tracks+=1
                raw_path=ROOT/track['raw']
                with raw_path.open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=track['sha256']:
                        raise ValueError('整理后的字幕原件哈希发生变化')
                document=json.loads(raw_path.read_text(encoding='utf-8'))
                score=coverage(validate_cues(document),checked['summary']['probe']['duration_seconds'])
                record={**track,'coverage':score}
                assessments.append(record)
            chinese=[value for value in assessments if value.get('language')=='ai-zh' or str(value.get('language','')).startswith('zh')]
            preferred=next((value for value in chinese if value.get('language')=='ai-zh'),chinese[0] if chinese else None)
            if preferred:
                value=preferred['coverage']
                row.update({'中文字幕状态':'downloaded','字幕段数':value['segments'],'字幕字符数':value['characters'],
                            '字幕覆盖比例':value['covered_ratio'],'字幕最后秒数':value['last_seconds'],
                            '中文字幕原件':preferred['raw'],'中文字幕SRT':preferred['srt'],'中文阅读版':preferred['readable'],
                            '质量筛查':value['screening_status'],'字幕待核事项':' | '.join(value['warnings'])})
            item['subtitle_coverage']=assessments
            item['preferred_chinese']=preferred
            description_path=ROOT/item['exports']['description']
            description=json.loads(description_path.read_text(encoding='utf-8'))
            description['subtitle_coverage']=assessments
            description['preferred_chinese']=preferred
            save_json(description_path,description)
        except (ValueError,OSError,KeyError) as error:
            row['音频状态']='audit_failed'
            problems.append({'bvid':entry['bvid'],'reason':str(error)})
        rows.append(row)
    target=ROOT/'data/seasons/S22'
    output=target/'S22_中文优先复核目录.csv'
    with output.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    chinese_rows=[row for row in rows if row['中文字幕状态']=='downloaded']
    counts=Counter(row['质量筛查'] for row in rows)
    with database.connect() as conn:
        stored=conn.execute("SELECT external_key FROM sources WHERE platform='bilibili'").fetchall()
        stored_keys={row['external_key'] for row in stored}
        missing_db=[source for source in (f"{e['bvid']}:{e['cid']}" for e in plan['entries']) if source not in stored_keys]
        registered=conn.execute("""SELECT s.external_key,a.kind,a.sha256 FROM artifacts a
            JOIN sources s ON s.id=a.source_id WHERE s.platform='bilibili' AND a.kind IN ('audio','subtitle')""").fetchall()
        registered_keys={(item['external_key'],item['kind'],item['sha256']) for item in registered}
        missing_artifacts=[]
        for entry in plan['entries']:
            key=f"{entry['bvid']}:{entry['cid']}"
            item=progress['items'].get(key,{})
            expected=[('audio',item.get('audio_sha256'))]
            expected.extend(('subtitle',track['sha256']) for track in item.get('exports',{}).get('subtitles',[]))
            missing_artifacts.extend({'source':key,'kind':kind,'sha256':sha} for kind,sha in expected if (key,kind,sha) not in registered_keys)
    report={'audited_at_utc':datetime.now(timezone.utc).isoformat(),'collection_id':plan['collection_id'],
            'official_collection_entries':len(rows),'audio_verified':sum(row['音频状态'] in {'complete','audio_only'} for row in rows),
            'audio_bytes':total_bytes,'audio_GiB':round(total_bytes/1024**3,3),'raw_subtitle_tracks_all_languages':raw_tracks,
            'with_chinese_subtitles':len(chinese_rows),'without_chinese_subtitles':len(rows)-len(chinese_rows),
            'chinese_subtitle_segments':sum(row['字幕段数'] for row in chinese_rows),
            'chinese_subtitle_screening':dict(counts),'audio_or_file_errors':problems,'database_missing_sources':missing_db,
            'database_missing_selected_artifacts':missing_artifacts,
            'subtitle_followup_sources':counts.get('needs_review',0)+counts.get('no_zh_subtitle',0),
            'preferred_review_index':output.relative_to(ROOT).as_posix(),
            'scope_note':plan['coverage_note'],'quality_note':'时间覆盖和段数只是缺失筛查；无截短信号不等于内容正确或完整。未运行本地ASR或事实提取。',
            'game_facts_created':False,'full_videos_downloaded':False,'audio_export_mode':'hardlinks_no_second_media_copy'}
    progress['final_audit']=report
    save_json(ROOT/'data/reports/S22_采集进度.json',progress)
    save_json(ROOT/'data/reports/S22_采集验收.json',report)
    save_json(target/'S22_中文优先复核目录.json',{'summary':report,'entries':rows})
    return report


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(audit(),ensure_ascii=False,indent=2))
