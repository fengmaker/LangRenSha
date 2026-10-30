"""Shared paths, state, and local-media checks for incremental season work."""

from __future__ import annotations

import json
from pathlib import Path

import media_ingest


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> object | None:
    """Read JSON when present; return ``None`` for a missing optional file."""
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    """Atomically replace a JSON file, keeping it readable during interruption."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def state_path(root: Path, season: str) -> Path:
    return Path(root) / "data" / "reports" / season / "incremental" / "state.json"


def load_state(root: Path, season: str) -> dict:
    state = read_json(state_path(root, season))
    if state is None:
        return {"schema_version": 1, "season": season, "items": {}, "weibo": {}}
    if not isinstance(state, dict) or state.get("season") != season:
        raise ValueError(f"增量状态不是 {season} 的状态文件")
    if not isinstance(state.get("items", {}), dict):
        raise ValueError("增量状态 items 必须是对象")
    if not isinstance(state.get("weibo", {}), dict):
        raise ValueError("增量状态 weibo 必须是对象")
    state.setdefault("schema_version", 1)
    state.setdefault("items", {})
    state.setdefault("weibo", {})
    return state


def save_state(root: Path, season: str, state: dict) -> None:
    if state.get("season") != season:
        raise ValueError(f"增量状态不是 {season} 的状态文件")
    state.setdefault("schema_version", 1)
    state.setdefault("items", {})
    state.setdefault("weibo", {})
    write_json(state_path(root, season), state)


def entry_key(entry: dict) -> str:
    return f"{entry['bvid']}:{entry['cid']}:p{int(entry.get('page') or 1):02d}"


def work_dir(root: Path, season: str, entry: dict) -> Path:
    page = int(entry.get("page") or 1)
    return (Path(root) / "data" / "extractions" / season / "incremental" /
            f"{entry['bvid']}_p{page:02d}_cid{entry['cid']}")


def _manifest_is_ready(path: Path, entry: dict) -> bool:
    if not path.is_file():
        return False
    try:
        checked = media_ingest.validate_media(
            path, expected_bvid=entry.get("bvid"),
            expected_page=int(entry.get("page") or 1))
        manifest = checked["manifest"]
        if int(manifest.get("cid")) != int(entry.get("cid")):
            return False
        return bool(checked["subtitles"] or checked["audio_path"])
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        return False


def ready_media(entry: dict, root: Path) -> bool:
    """True only when a matching manifest and valid Chinese subtitles or audio exist."""
    page = int(entry.get("page") or 1)
    paths = [
        Path(root) / "data" / "raw" / "bilibili" / entry["bvid"] /
        f"p{page:02d}" / "manifest.json",
    ]
    return any(_manifest_is_ready(path, entry) for path in paths)
