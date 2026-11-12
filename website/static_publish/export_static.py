"""Build the website's static JSON snapshot directly from canonical game files."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any
from urllib.parse import urlsplit

if __package__:
    from .photo_thumbnails import VERSION as PHOTO_THUMBNAIL_VERSION, create_thumbnails
    from .player_rankings import SNAPSHOT_SCHEMA_VERSION, split_player_rankings
else:
    from photo_thumbnails import VERSION as PHOTO_THUMBNAIL_VERSION, create_thumbnails
    from player_rankings import SNAPSHOT_SCHEMA_VERSION, split_player_rankings


class ExportError(RuntimeError):
    """Canonical public data cannot be written as a complete static snapshot."""


_PLAYER_MEDIA_RE = re.compile(
    r"/media/player-photos/(S[0-9]{1,4})/([a-f0-9]{64}\.(?:jpg|jpeg|png|webp))"
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_base_path(value: str) -> str:
    if value == "/":
        return ""
    if value and (not value.startswith("/") or value.endswith("/") or "\\" in value or "//" in value):
        raise ExportError("base_path must be empty or a slash-prefixed path without a trailing slash")
    if any(part in {".", ".."} for part in value.split("/")[1:]):
        raise ExportError("base_path cannot contain dot path segments")
    return value


def _media_endpoint(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment or parsed.scheme or parsed.netloc:
        raise ExportError(f"Media reference must be a relative public URL: {url}")
    match = _PLAYER_MEDIA_RE.fullmatch(parsed.path)
    if not match:
        raise ExportError(f"Media reference is outside the public photo allowlist: {url}")
    season, filename = match.groups()
    relative = f"player-photos/{season}/{filename}"
    return f"/media/{relative}", relative, filename.split(".", 1)[0]


def _walk_media_values(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"url", "image_url"} and isinstance(child, str) and "/media/" in child:
                yield child, value.get("sha256") if isinstance(value.get("sha256"), str) else None
            else:
                yield from _walk_media_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_media_values(child)
    elif isinstance(value, str) and "/media/" in value:
        yield value, None


def _response_media(data_root: Path) -> list[dict[str, str]]:
    references: dict[str, str] = {}
    for path in data_root.rglob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExportError(f"Cannot read generated JSON while collecting media: {path}") from exc
        for url, declared_hash in _walk_media_values(value):
            _, _, filename_hash = _media_endpoint(url)
            expected = declared_hash or filename_hash
            if expected != filename_hash:
                raise ExportError(f"Media reference hash disagrees with its filename: {url}")
            if url in references and references[url] != expected:
                raise ExportError(f"Conflicting media hashes for {url}")
            references[url] = expected
    return [{"url": url, "sha256": references[url]} for url in sorted(references)]


def _media_target(root: Path, relative: str, url: str) -> Path:
    parts = PurePosixPath(relative).parts
    if len(parts) != 3 or any(part in {"", ".", ".."} for part in parts):
        raise ExportError(f"Unsafe media path: {url}")
    return root.joinpath(*parts)


def _direct_media_source(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if len(parts) != 3 or parts[0] != "player-photos":
        raise ExportError(f"Media path is outside the local public allowlist: {relative}")
    assets = (root / "website" / "assets").resolve()
    source = assets.joinpath(*parts)
    if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(assets):
        raise ExportError(f"Allowlisted media file is missing or unsafe: {source}")
    return source


def _write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(body)
    return _sha256(body)


def _direct_export_is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _promote_direct_export(stage: Path, data_root: Path, media_root: Path) -> None:
    targets = ((stage / "data", data_root), (stage / "media", media_root))
    backups: list[tuple[Path, Path]] = []
    promoted: list[tuple[Path, Path]] = []
    for _, target in targets:
        if _direct_export_is_link(target):
            raise ExportError(f"Direct export target cannot be a link: {target}")
        if target.exists() and not target.is_dir():
            raise ExportError(f"Direct export target must be a directory: {target}")
    try:
        for index, (source, target) in enumerate(targets):
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup = stage / f"previous-{index}"
                target.rename(backup)
                backups.append((backup, target))
            source.rename(target)
            promoted.append((target, source))
    except BaseException:
        for target, source in reversed(promoted):
            if target.exists():
                target.rename(source)
        for backup, target in reversed(backups):
            if backup.exists():
                backup.rename(target)
        raise


def export_direct_snapshot(root: Path | str, output: Path | str, *, base_path: str = "",
                           build_id: str | None = None) -> dict[str, Any]:
    """Write static response JSON and media directly from final game records."""
    from website.public_data import ANALYTICS_VERSION, build_public_data

    root = Path(root).resolve()
    data_root = Path(output).absolute()
    _safe_base_path(base_path)
    if _direct_export_is_link(data_root):
        raise ExportError(f"Direct export target cannot be a link: {data_root}")
    media_root = data_root.parent / "media"
    data = build_public_data(root)

    documents = dict(data["documents"])
    shared_rankings: dict[str, dict[str, Any]] = {}
    for relative in sorted(name for name in documents
                           if name.startswith("players/") and "--" in PurePosixPath(name).name):
        compact, shared = split_player_rankings(documents[relative])
        range_name = PurePosixPath(relative).name
        if range_name in shared_rankings and shared_rankings[range_name] != shared:
            raise ExportError(f"Player ranking boards differ within season range {range_name}")
        shared_rankings[range_name] = shared
        documents[relative] = compact
    documents.update({f"rankings/{name}": value for name, value in shared_rankings.items()})

    data_root.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{data_root.name}.direct-export-", dir=data_root.parent))
    try:
        staged_data, staged_media = stage / "data", stage / "media"
        staged_media.mkdir()
        pending = staged_data / "releases" / "__pending__"
        document_hashes = {}
        for relative, value in documents.items():
            document_hashes[relative] = _write_json(pending.joinpath(*PurePosixPath(relative).parts), value)

        media_files = _response_media(pending)
        copied_media: list[dict[str, str]] = []
        for asset in media_files:
            _, relative, _ = _media_endpoint(asset["url"])
            source = _direct_media_source(root, relative)
            actual_hash = _sha256(source.read_bytes())
            if actual_hash != asset["sha256"]:
                raise ExportError(f"Allowlisted media hash differs from its public URL: {asset['url']}")
            target = _media_target(staged_media, relative, asset["url"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied_media.append({**asset, "path": relative})

        try:
            photo_thumbnails = create_thumbnails(staged_media, copied_media)
        except (OSError, ValueError) as exc:
            raise ExportError(f"Cannot create player photo thumbnails: {exc}") from exc

        fingerprint = _sha256(_canonical_json({
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "release_id": data["release_id"],
            "source_hash": data["source_hash"],
            "documents": document_hashes,
            "media_files": sorted((asset["path"], asset["sha256"]) for asset in copied_media),
            "analytics_version": ANALYTICS_VERSION,
            "photo_thumbnail_version": PHOTO_THUMBNAIL_VERSION,
            "base_path": base_path,
        }))
        snapshot_id = f"snapshot-{fingerprint}"
        (staged_data / "releases" / "__pending__").rename(staged_data / "releases" / snapshot_id)
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        manifest = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "build_id": build_id or data["release_id"],
            "release_id": data["release_id"],
            "source_hash": data["source_hash"],
            "analytics_version": ANALYTICS_VERSION,
            "photo_thumbnail_version": PHOTO_THUMBNAIL_VERSION,
            "player_photo_thumbnails": photo_thumbnails,
            "generated_at": generated_at,
            "base_path": base_path,
            "seasons": [{"id": row["season"], "game_count": row["game_count"], "phases": row["phases"]}
                        for row in data["season_rows"]],
            "ranges": data["ranges"],
            "counts": {**data["counts"], "media_files": len(copied_media)},
            "complete": True,
        }
        _write_json(staged_data / "manifest.json", manifest)
        _promote_direct_export(stage, data_root, media_root)
        shutil.rmtree(stage, ignore_errors=True)
        return manifest
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build public static data from final game JSON")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2],
                        help="project root containing data/games and config/seasons.json")
    parser.add_argument("--output", type=Path,
                        help="data output directory (default: website/web/public/data)")
    parser.add_argument("--base-path", default="")
    parser.add_argument("--build-id")
    parser.add_argument("--check", action="store_true",
                        help="read-only validation of response shape and statistical coverage")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        if str(root) not in __import__("sys").path:
            __import__("sys").path.insert(0, str(root))
        if args.check:
            from website.public_data import check_public_data
            result = check_public_data(root)
        else:
            output = args.output or root / "website" / "web" / "public" / "data"
            result = export_direct_snapshot(root, output, base_path=args.base_path, build_id=args.build_id)
    except (ExportError, OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"静态快照导出失败：{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
