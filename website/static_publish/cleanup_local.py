"""Remove completed incremental materials and disposable static-build copies."""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import shutil
import stat
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from incremental_common import work_dir, write_json
from update_incremental import (WEIBO_UID, _archive_interval, _archive_paths,
                                _coverage_until, _merge_intervals, archive_complete)
from website.public_data import _load_catalog, _load_games, _source_fingerprint


def _validate_target(root: Path, path: Path, base: Path) -> None:
    """Check the final absolute deletion target and reject Windows reparse points."""
    path = Path(os.path.abspath(path))
    base = Path(os.path.abspath(base))
    if base == root or not base.is_relative_to(root) or not path.is_relative_to(base):
        raise ValueError(f"Cleanup target leaves its temporary directory: {path}")

    def check_link(item: Path) -> None:
        try:
            info = item.lstat()
        except FileNotFoundError:
            return
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError(f"Cleanup target cannot contain links or junctions: {item}")

    cursor = path
    while cursor != root:
        check_link(cursor)
        cursor = cursor.parent
    if path.is_dir():
        for folder, directories, files in os.walk(path):
            for name in directories + files:
                check_link(Path(folder) / name)


def cleanup(root: Path, output: Path, build_id: str, source_hash: str, *,
            dry_run: bool = False) -> dict:
    """Call only after deployment and online verification have both succeeded."""
    root = Path(root).resolve()
    games, hashes = _load_games(root)
    _, catalog_hash = _load_catalog(root)
    if _source_fingerprint(root, hashes, catalog_hash) != source_hash:
        raise ValueError("本地正式数据在构建后发生变化，已保留临时资料；下次成功部署后再清理")
    formal_sources = set()
    for game in games:
        for media in game["source"]["media"]:
            identity = (media["bvid"], int(media["cid"]), int(media["page"]))
            formal_sources.add(identity)

    targets: dict[Path, Path] = {}

    def add(path: Path, base: Path) -> None:
        if path.exists() or path.is_symlink():
            targets[path] = base

    states = []
    pending_media = set()
    for path in sorted((root / "data/reports").glob("*/incremental/state.json")):
        state = json.loads(path.read_text(encoding="utf-8"))
        done = {}
        for key, item in state["items"].items():
            entry = item["entry"]
            identity = (entry["bvid"], int(entry["cid"]), int(entry.get("page") or 1))
            formal_path = item.get("formal_dir", "") + "/game.json"
            if (item.get("applied") and item.get("game_sha256")
                    and hashes.get(formal_path) == item["game_sha256"]
                    and identity in formal_sources):
                done[key] = item
            else:
                pending_media.add((identity[0], identity[2]))
        states.append((path, state, done))

    for path, state, done in states:
        season = state["season"]
        for item in done.values():
            entry = item["entry"]
            add(work_dir(root, season, entry), root / "data/extractions" / season / "incremental")
            stem = f"{entry['bvid']}_p{int(entry.get('page') or 1):02d}"
            transcripts = root / "data/transcripts" / season
            add(transcripts / f"{stem}_cid{entry['cid']}_funasr", transcripts)
            legacy = transcripts / f"{stem}_funasr"
            if (legacy / "transcript.json").is_file():
                source = json.loads((legacy / "transcript.json").read_text(encoding="utf-8"))["source"]
                if (source["bvid"], int(source["cid"]), int(source["page"])) == (
                        entry["bvid"], int(entry["cid"]), int(entry.get("page") or 1)):
                    add(legacy, transcripts)
            if (entry["bvid"], int(entry.get("page") or 1)) not in pending_media:
                raw = root / "data/raw/bilibili" / entry["bvid"] / f"p{int(entry.get('page') or 1):02d}"
                if (raw / "manifest.json").is_file():
                    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
                    if int(manifest["cid"]) == int(entry["cid"]):
                        add(raw, root / "data/raw/bilibili")
        if done and len(done) == len(state["items"]):
            review = root / "data/manual_review"
            add(review / f"{season}_新增对局人工复核.html", review)
            for page in review.glob(f"{season}_指定对局人工复核_*.html"):
                add(page, review)
            add(review / "feedback" / f"{season}_逐局复核意见.json", review)

    # Weibo materials can be shared by different matches and seasons. Keep all
    # of them while any tracked match still needs review.
    checkpoint_path = root / "data/sources/weibo_checkpoint.json"
    checkpoint = None
    if states and not pending_media:
        checkpoint = (json.loads(checkpoint_path.read_text(encoding="utf-8"))
                      if checkpoint_path.is_file() else
                      {"uid": WEIBO_UID, "complete_intervals": [], "posts": {}})
        if checkpoint["uid"] != WEIBO_UID:
            raise ValueError("微博 checkpoint UID 不匹配，已保留临时资料")
        intervals = [(date.fromisoformat(a), date.fromisoformat(b))
                     for a, b in checkpoint["complete_intervals"]]
        for manifest_path in _archive_paths(root, WEIBO_UID):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            interval = _archive_interval(manifest)
            if not archive_complete(manifest) or interval is None:
                continue
            start, until = interval
            closed = _coverage_until(manifest, start, until)
            if closed >= start:
                intervals.append((start, closed))
            for post in manifest.get("posts", []):
                published = date.fromisoformat(post["published_date"]).isoformat()
                checkpoint["posts"][str(post["post_id"])] = published
            add(manifest_path.parent, root / "data/raw/weibo")
        checkpoint["complete_intervals"] = [[a.isoformat(), b.isoformat()]
                                             for a, b in _merge_intervals(intervals)]

    # Keep the latest small timing receipts, dependency/model caches and Next's
    # compiler cache. Only remove duplicate generated data, media and exports.
    builds = root / "tmp/pages-build"
    current = builds / build_id
    for previous in builds.iterdir() if builds.is_dir() else []:
        if previous != current and (previous / "result.json").is_file():
            add(previous, builds)
    for child in current.iterdir() if current.is_dir() else []:
        if child.name not in {"result.json", "sync-result.json"}:
            add(child, builds)
    add(Path(output), root / "tmp")
    workspace = root / "website/web/.static-build"
    for name in ("out", "public", ".static-snapshot"):
        add(workspace / name, workspace)

    # Validate every final path before writing the checkpoint or deleting any
    # files. Never follow a junction into formal data or another directory.
    for path, base in targets.items():
        _validate_target(root, path, base)
    for path, state, done in states:
        if done:
            _validate_target(root, path.parent, root / "data/reports")
    if checkpoint is not None:
        _validate_target(root, checkpoint_path, root / "data/sources")
    result = {"state": "planned" if dry_run else "passed",
              "completed_games": sum(len(done) for _, _, done in states),
              "pending_games": sum(len(state["items"]) - len(done) for _, state, done in states),
              "paths": [str(path.relative_to(root)) for path in targets], "errors": []}
    if dry_run:
        return result
    if checkpoint is not None:
        write_json(checkpoint_path, checkpoint)
    for path in targets:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError as error:
            result["errors"].append(f"{path}: {error}")
    # Keep resumable state if Windows left any occupied temporary files behind.
    if result["errors"]:
        result["state"] = "partial"
        return result
    for path, state, done in states:
        if not done:
            continue
        state["items"] = {key: item for key, item in state["items"].items() if key not in done}
        if state["items"]:
            write_json(path, state)
        else:
            shutil.rmtree(path.parent)
    return result
