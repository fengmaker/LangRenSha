"""Offline S22 cleanup: Chinese subtitles only; preserve registered evidence."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from psycopg.types.json import Jsonb

from collect_bilibili_audio import is_chinese_subtitle, save_json
import database

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT/'data/reports'/f"data_cleanup_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"


def data_path(relative: str) -> Path:
    path = (ROOT/relative).resolve()
    if not path.is_relative_to((ROOT/'data').resolve()):
        raise ValueError('清理目标超出项目 data 目录')
    if path.suffix.lower() in {'.m4a', '.mp4', '.mp3', '.wav', '.flac'}:
        raise ValueError('本次清理禁止删除媒体文件')
    return path


def checksum(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def ensure_unreferenced(conn, ids: list) -> None:
    if not ids:
        return
    for table in ['transcription_runs', 'extraction_runs', 'evidence_links']:
        # Table names are fixed above; IDs are bound as parameters.
        row = conn.execute(f'SELECT count(*) AS n FROM {table} WHERE artifact_id=ANY(%s)', (ids,)).fetchone()
        if row['n']:
            raise ValueError('非中文字幕已被业务证据引用，停止清理')


def build_plan() -> dict:
    progress = json.loads((ROOT/'data/reports/S22_采集进度.json').read_text(encoding='utf-8'))
    if progress.get('current_run',{}).get('state') == 'running':
        raise ValueError('采集正在运行，不能同时清理')
    with database.connect() as conn:
        artifacts = conn.execute('SELECT id,source_id,kind,relative_path,sha256,metadata FROM artifacts').fetchall()
        foreign = [a for a in artifacts if a['kind']=='subtitle' and a['metadata'].get('language')
                   and not is_chinese_subtitle(a['metadata']['language'])]
        ensure_unreferenced(conn, [a['id'] for a in foreign])
    foreign_ids = {a['id'] for a in foreign}
    protected = {(ROOT/a['relative_path']).resolve() for a in artifacts if a['id'] not in foreign_ids}
    pending = {}

    def add(path: Path, reason: str):
        relative = path.resolve().relative_to(ROOT).as_posix()
        path = data_path(relative)
        if not path.is_file() or path in protected:
            return
        pending[relative] = {'path':relative, 'reason':reason, 'bytes':path.stat().st_size, 'sha256':checksum(path)}

    # Retain the active audio/Chinese caption set, not superseded exported copies.
    active_exports = set()
    active_raw = set()
    for item in progress['items'].values():
        exports = item.get('exports') or {}
        active_exports.update((ROOT/value).resolve() for key,value in exports.items() if key in {'audio','description'})
        for track in exports.get('subtitles',[]):
            if not is_chinese_subtitle(track.get('language')):
                raise ValueError('当前目录仍引用外语字幕，请先修正目录')
            active_exports.update((ROOT/track[key]).resolve() for key in ['raw','srt','readable'])
        manifest_path = ROOT/exports['source_manifest']
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for track in (manifest.get('subtitles') or {}).get('tracks') or []:
            if not is_chinese_subtitle(track.get('language')):
                raise ValueError('当前媒体清单仍引用外语字幕')
            active_raw.add((manifest_path.parent/track['file']).resolve())
    for path in (ROOT/'data/seasons/S22').rglob('*'):
        if path.is_file() and path.resolve() not in active_exports and '字幕_' in path.name:
            if path.name.endswith(('.原始.json','.srt','.阅读.txt')):
                add(path,'obsolete_or_foreign_subtitle_export')
    for path in (ROOT/'data/raw/bilibili').rglob('subtitle*.raw.json'):
        if path.resolve() not in active_raw:
            add(path,'unused_raw_subtitle_copy')
    # Snapshots with a surviving artifact registration are always protected.
    for path in (ROOT/'data/archive').rglob('*.json'):
        if len(path.stem)==64 and all(c in '0123456789abcdef' for c in path.stem):
            if path.resolve() not in protected:
                add(path,'foreign_or_unregistered_snapshot')
    for suffix in ['json','srt']:
        add(ROOT/f'data/transcripts/BV1tj8p6REqy.sample.asr.{suffix}','superseded_first_asr_sample')
    # Failed Weibo probes have no post body or downloaded images.
    for folder in (ROOT/'data/raw/weibo').glob('*'):
        if folder.is_dir() and sorted(p.name for p in folder.iterdir())==['manifest.json']:
            manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
            if manifest.get('status')=='blocked':
                add(folder/'manifest.json','empty_failed_weibo_probe')
    add(ROOT/'data/indexes/S22_决赛周_候选索引.csv','redundant_subset_of_official_index')
    files = sorted(pending.values(),key=lambda item:item['path'])
    return {'planned_at_utc':datetime.now(timezone.utc).isoformat(), 'state':'planned',
            'policy':'只保留中文；整理目录只留当前选用版本；保留仍登记的中文证据、来源快照和全部音频。',
            'database_subtitle_records_to_remove':[{key:str(a[key]) for key in ['id','source_id','sha256','relative_path']}
                | {'language':a['metadata']['language']} for a in foreign],
            'summary':{'files':len(files),'file_bytes':sum(item['bytes'] for item in files),
                       'reasons':dict(Counter(item['reason'] for item in files)), 'foreign_database_records':len(foreign)},
            'files':files}


def apply(plan: dict) -> dict:
    # Check the entire frozen file plan before committing any deletion.
    for item in plan['files']:
        path = data_path(item['path'])
        if not path.is_file() or checksum(path)!=item['sha256']:
            raise ValueError('清理计划形成后文件发生变化，停止删除')
    with database.connect() as conn:
        ids = [item['id'] for item in plan['database_subtitle_records_to_remove']]
        if ids:
            current = conn.execute('SELECT id,metadata FROM artifacts WHERE id=ANY(%s::uuid[]) FOR UPDATE',(ids,)).fetchall()
            if len(current)!=len(ids) or any(is_chinese_subtitle(item['metadata'].get('language')) for item in current):
                raise ValueError('字幕登记发生变化，停止删除')
            ensure_unreferenced(conn, [item['id'] for item in current])
            conn.execute('DELETE FROM artifacts WHERE id=ANY(%s::uuid[])',(ids,))
        conn.execute("INSERT INTO audit_events(action,actor,details) VALUES('cleanup_non_chinese_subtitles','user_requested',%s)",
                     (Jsonb({'report':REPORT.relative_to(ROOT).as_posix(),'removed_subtitle_records':len(ids),
                             'file_count':len(plan['files']),'audio_files_removed':0}),))
    save_json(REPORT,plan)
    removed=[]
    for item in plan['files']:
        data_path(item['path']).unlink()
        removed.append(item['path'])
    for base in [ROOT/'data/archive',ROOT/'data/raw/weibo']:
        if base.exists():
            for folder in sorted((p for p in base.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
                data_path(folder.relative_to(ROOT).as_posix())
                if not any(folder.iterdir()):
                    folder.rmdir()
            if base.name=='weibo' and not any(base.iterdir()):
                data_path(base.relative_to(ROOT).as_posix()).rmdir()
    plan.update(state='completed',completed_at_utc=datetime.now(timezone.utc).isoformat(),removed_files=len(removed),audio_files_removed=0)
    save_json(REPORT,plan)
    return plan


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='实际执行；不传此参数只预览')
    args=parser.parse_args()
    plan=build_plan()
    if args.apply:
        plan=apply(plan)
    print(json.dumps({'state':plan['state'],**plan['summary'],'report':str(REPORT.relative_to(ROOT)) if args.apply else None},ensure_ascii=False,indent=2))
