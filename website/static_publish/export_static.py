"""Build the website's static JSON snapshot directly from canonical game files."""
from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any
from urllib.parse import urlsplit
import uuid

if __package__:
    from .generated_dirs import rename_generated_directory
    from .photo_thumbnails import VERSION as PHOTO_THUMBNAIL_VERSION, create_thumbnails
    from .player_rankings import split_player_rankings
    from .snapshot_files import SNAPSHOT_SCHEMA_VERSION, object_path
else:
    from generated_dirs import rename_generated_directory
    from photo_thumbnails import VERSION as PHOTO_THUMBNAIL_VERSION, create_thumbnails
    from player_rankings import split_player_rankings
    from snapshot_files import SNAPSHOT_SCHEMA_VERSION, object_path


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


def _response_media(documents: Iterable[object]) -> list[dict[str, str]]:
    references: dict[str, str] = {}
    for value in documents:
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
                rename_generated_directory(target, backup)
                backups.append((backup, target))
            rename_generated_directory(source, target)
            promoted.append((target, source))
    except BaseException:
        for target, source in reversed(promoted):
            if target.exists():
                rename_generated_directory(target, source)
        for backup, target in reversed(backups):
            if backup.exists():
                rename_generated_directory(backup, target)
        raise


def _leaderboard_summary(board: dict) -> dict:
    items = [
        {
            key: {field: detail for field, detail in value.items()
                  if field not in {"game_ids", "samples"}} if isinstance(value, dict) else value
            for key, value in item.items() if key != "photo"
        }
        for item in board["items"]
    ]
    latest_date = (max((game["date"] for game in board["sample_games"]), default=None)
                   if board["phase"] == "all" else None)
    return {
        **{key: value for key, value in board.items() if key not in {"items", "sample_games", "notes"}},
        "items": items,
        "latest_date": latest_date,
    }


def _player_directory(page: dict, thumbnails: dict[str, str]) -> dict:
    items = []
    for player in page["items"]:
        stats = player.get("stats")
        photo = player.get("photo")
        appearances = stats.get("appearances") if stats is not None else None
        row = {
            "id": player["id"],
            "name": player["name"],
            "appearances": player["appearances"] if appearances is None else appearances,
        }
        if stats is not None:
            row["stats"] = {"wins": stats["wins"], "losses": stats["losses"],
                            "win_rate": stats["total_win_rate"]["rate"]}
        if photo:
            row["photo"] = {"url": thumbnails[photo["url"]], "season": photo["season"]}
        items.append(row)
    return {"items": items, "total": page["total"], "page": page["page"], "page_size": page["page_size"]}


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
    profile_paths = {name for name in documents
                     if name.startswith("players/") and "--" in PurePosixPath(name).name}
    for relative in sorted(profile_paths):
        compact, shared = split_player_rankings(documents[relative])
        range_name = PurePosixPath(relative).name
        if range_name in shared_rankings and shared_rankings[range_name] != shared:
            raise ExportError(f"Player ranking boards differ within season range {range_name}")
        shared_rankings[range_name] = shared
        documents[relative] = compact
    documents.update({f"rankings/{name}": value for name, value in shared_rankings.items()})
    documents.update({
        f"{relative.removesuffix('.json')}.summary.json": _leaderboard_summary(board)
        for relative, board in documents.items() if relative.startswith("leaderboards/")
    })

    data_root.parent.mkdir(parents=True, exist_ok=True)
    # These are public generated assets. Inherit the workspace ACL instead of
    # tempfile's private Windows ACL, which survives promotion and prevents a
    # different local account from replacing or cleaning the exported tree.
    stage = data_root.parent / f".{data_root.name}.direct-export-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        staged_data, staged_media = stage / "data", stage / "media"
        staged_media.mkdir()
        pending = staged_data / "releases" / "__pending__"
        pending.mkdir(parents=True)

        media_files = _response_media(documents.values())
        copied_media: list[dict[str, str]] = []
        for asset in media_files:
            _, relative, _ = _media_endpoint(asset["url"])
            source = _direct_media_source(root, relative)
            body = source.read_bytes()
            actual_hash = _sha256(body)
            if actual_hash != asset["sha256"]:
                raise ExportError(f"Allowlisted media hash differs from its public URL: {asset['url']}")
            target = _media_target(staged_media, relative, asset["url"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            copied_media.append({**asset, "path": relative})

        try:
            photo_thumbnails = create_thumbnails(
                staged_media, copied_media, cache_root=root / ".cache/static-publish/photo-thumbnails",
            )
        except (OSError, ValueError) as exc:
            raise ExportError(f"Cannot create player photo thumbnails: {exc}") from exc

        document_hashes = {}
        immutable_hashes = {}
        for relative, value in documents.items():
            if relative.startswith("players/by-season/"):
                value = _player_directory(value, photo_thumbnails)
            elif relative in profile_paths and (photo := value.get("photo")):
                original = photo["url"]
                value = {**value, "photo": {**photo, "url": photo_thumbnails[original], "original_url": original}}

            if relative.startswith("players/by-season/") or (relative.startswith("games/") and relative != "games/index.json"):
                # The manifest owns the release ID. The immutable body describes only this document.
                body = _canonical_json({key: item for key, item in value.items() if key != "release_id"}) + b"\n"
                digest = _sha256(body)
                target = object_path(staged_data, digest)
                target.parent.mkdir(exist_ok=True)
                if not target.exists():
                    target.write_bytes(body)
                immutable_hashes[relative] = document_hashes[relative] = digest
            else:
                document_hashes[relative] = _write_json(pending / relative, value)

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
        rename_generated_directory(pending, pending.with_name(snapshot_id))
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        manifest = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "build_id": build_id or data["release_id"],
            "release_id": data["release_id"],
            "source_hash": data["source_hash"],
            "analytics_version": ANALYTICS_VERSION,
            "photo_thumbnail_version": PHOTO_THUMBNAIL_VERSION,
            "document_hashes": immutable_hashes,
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
        # A failed rollback can leave the previous snapshot in the stage.
        if not any(stage.glob("previous-*")):
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
