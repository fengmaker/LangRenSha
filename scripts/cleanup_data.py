"""Offline cleanup preview: preserve active season media and registered evidence."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from psycopg.types.json import Jsonb

from collect_bilibili_audio import is_chinese_subtitle, save_json
import database
from season_config import season_codes

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT/'data/reports/maintenance'/f"data_cleanup_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
REFERENCE_DIRS = ('candidates', 'reviews', 'extractions', 'games', 'transcripts')
SHA256_PATTERN = re.compile(r'^[0-9a-fA-F]{64}$')
PATH_KEY_PARTS = ('path', 'file', 'source', 'transcript', 'audio', 'subtitle', 'frame',
                  'image', 'snapshot', 'candidate', 'evidence', 'artifact', 'input', 'output')
HASH_KEY_PARTS = ('sha', 'hash', 'fingerprint', 'checksum')


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


def _data_path(value: str | Path, root: Path, base: Path | None = None) -> Path:
    path = Path(value)
    candidates = [path] if path.is_absolute() else [root/path]
    if not path.is_absolute() and base is not None:
        candidates.append(base/path)
    data_root = (root/'data').resolve()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_relative_to(data_root):
            return resolved
    raise ValueError(f'当前证据引用超出项目 data 目录: {value}')


def current_media_references(root: Path = ROOT) -> dict:
    """Collect active exports and source subtitle paths from every registered season."""
    active_exports: set[Path] = set()
    active_raw: set[Path] = set()
    manifests: set[Path] = set()
    running_seasons: list[str] = []
    season_counts: dict[str, dict[str, int]] = {}
    for season in season_codes(root):
        progress_path = root/'data/reports'/season/f'{season}_采集进度.json'
        if not progress_path.is_file():
            continue
        progress = json.loads(progress_path.read_text(encoding='utf-8'))
        if progress.get('current_run', {}).get('state') == 'running':
            running_seasons.append(season)
        items = progress.get('items', {})
        if not isinstance(items, dict):
            raise ValueError(f'{season}采集进度的items不是对象')
        season_exports: set[Path] = set()
        season_raw: set[Path] = set()
        for key, item in items.items():
            if not isinstance(item, dict):
                raise ValueError(f'{season}采集进度项目格式无效: {key}')
            exports = item.get('exports') or {}
            if not isinstance(exports, dict):
                raise ValueError(f'{season}采集进度导出信息格式无效: {key}')
            for field in ('audio', 'description'):
                if exports.get(field):
                    season_exports.add(_data_path(exports[field], root))
            for track in exports.get('subtitles') or []:
                if not is_chinese_subtitle(track.get('language')):
                    raise ValueError('当前目录仍引用外语字幕，请先修正目录')
                for field in ('raw', 'srt', 'readable'):
                    if track.get(field):
                        season_exports.add(_data_path(track[field], root))

            manifest_value = exports.get('source_manifest')
            if not manifest_value:
                bvid = item.get('bvid') or str(key).split(':', 1)[0]
                if bvid.startswith('BV'):
                    page = int(item.get('page', 1))
                    fallback = root/'data/raw/bilibili'/bvid/f'p{page:02d}'/'manifest.json'
                    if fallback.is_file():
                        manifest_value = fallback.relative_to(root).as_posix()
            if not manifest_value:
                continue
            manifest_path = _data_path(manifest_value, root)
            if not manifest_path.is_file():
                raise ValueError(f'当前进度引用的源manifest不存在: {manifest_value}')
            manifests.add(manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            tracks = (manifest.get('subtitles') or {}).get('tracks') or []
            for track in tracks:
                if track.get('file'):
                    season_raw.add(_data_path(track['file'], root, manifest_path.parent))
        active_exports.update(season_exports)
        active_raw.update(season_raw)
        season_counts[season] = {'current_export_files': len(season_exports),
                                 'manifest_raw_subtitle_files': len(season_raw)}
    return {'active_exports': active_exports, 'active_raw': active_raw,
            'manifests': manifests, 'running_seasons': running_seasons,
            'season_counts': season_counts}


def scan_evidence_references(root: Path = ROOT, documents: set[Path] | None = None) -> tuple[set[Path], set[str]]:
    """Find referenced data paths and SHA256s in current evidence JSON.

    Operational progress is read separately above. Reports, logs, cleanup history,
    and maintenance baselines are deliberately excluded so their own inventories
    cannot keep prior cleanup candidates alive.
    """
    protected_paths: set[Path] = set()
    protected_hashes: set[str] = set()
    data_root = (root/'data').resolve()
    root_prefix = root.resolve().as_posix().rstrip('/') + '/'
    evidence_documents = set(documents or ())
    for directory in REFERENCE_DIRS:
        base = root/'data'/directory
        if base.exists():
            evidence_documents.update(path.resolve() for path in base.rglob('*.json') if path.is_file())

    def visit(value, document: Path, key: str = '') -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, document, str(child_key).lower())
        elif isinstance(value, list):
            if key in {'segments', 'sentences', 'cues', 'words', 'tokens', 'body'}:
                return
            for child in value:
                visit(child, document, key)
        elif isinstance(value, str):
            hash_field = any(part in key for part in HASH_KEY_PARTS)
            if hash_field and SHA256_PATTERN.fullmatch(value):
                protected_hashes.add(value.lower())
            normalized = value.replace('\\', '/')
            looks_like_path_field = any(part in key for part in PATH_KEY_PARTS)
            looks_like_data_path = normalized.lower().startswith('data/')
            looks_like_absolute_path = normalized.lower().startswith(root_prefix.lower())
            if looks_like_data_path or looks_like_path_field or looks_like_absolute_path:
                for candidate in ([Path(value)] if Path(value).is_absolute() else
                                  [root/Path(value), document.parent/Path(value)]):
                    resolved = candidate.resolve()
                    if resolved.is_relative_to(data_root):
                        protected_paths.add(resolved)

    for document in evidence_documents:
        if not document.is_file():
            continue
        try:
            value = json.loads(document.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f'无法核对业务证据引用: {document.relative_to(root)}') from error
        visit(value, document)
    return protected_paths, protected_hashes


def require_idle_seasons(running_seasons: list[str]) -> None:
    if running_seasons:
        raise ValueError(f'采集仍在运行，不能同时清理: {", ".join(running_seasons)}')


def build_plan() -> dict:
    references = current_media_references(ROOT)
    with database.connect() as conn:
        artifacts = conn.execute('SELECT id,source_id,kind,relative_path,sha256,metadata FROM artifacts').fetchall()
    # Keep every database artifact registration and its recorded content hash.
    # This cleanup only considers unregistered file copies.
    foreign = []
    protected = {(ROOT/a['relative_path']).resolve() for a in artifacts if a.get('relative_path')}
    protected_hashes = {a['sha256'].lower() for a in artifacts if a.get('sha256')}
    protected.update(references['active_exports'])
    protected.update(references['active_raw'])
    protected.update(references['manifests'])
    evidence_paths, evidence_hashes = scan_evidence_references(ROOT, references['manifests'])
    protected.update(evidence_paths)
    protected_hashes.update(evidence_hashes)
    pending = {}

    def add(path: Path, reason: str):
        relative = path.resolve().relative_to(ROOT).as_posix()
        path = data_path(relative)
        if not path.is_file() or path in protected:
            return
        digest = checksum(path)
        if digest.lower() in protected_hashes:
            return
        pending[relative] = {'path':relative, 'reason':reason, 'bytes':path.stat().st_size, 'sha256':digest}

    # Retain the active audio/Chinese caption set, not superseded exported copies.
    for season in season_codes(ROOT):
        if not (ROOT/'data/reports'/season/f'{season}_采集进度.json').is_file():
            continue
        for path in (ROOT/'data/seasons'/season).rglob('*'):
            if path.is_file() and path.resolve() not in references['active_exports'] and '字幕_' in path.name:
                if path.name.endswith(('.原始.json','.srt','.阅读.txt')):
                    add(path,'obsolete_or_foreign_subtitle_export')
    for path in (ROOT/'data/raw/bilibili').rglob('subtitle*.raw.json'):
        if path.resolve() not in references['active_raw']:
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
            'protected_media_by_season':references['season_counts'],
            'summary':{'files':len(files),'file_bytes':sum(item['bytes'] for item in files),
                       'reasons':dict(Counter(item['reason'] for item in files)), 'foreign_database_records':len(foreign)},
            'files':files}


def apply(plan: dict) -> dict:
    require_idle_seasons(current_media_references(ROOT)['running_seasons'])
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
    print(json.dumps({'state':plan['state'],**plan['summary'],
                      'protected_media_by_season':plan['protected_media_by_season'],
                      'report':str(REPORT.relative_to(ROOT)) if args.apply else None},
                     ensure_ascii=False,indent=2))
