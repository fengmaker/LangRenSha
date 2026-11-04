"""Export a version-bound snapshot for static publishing from the read-only API."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
import argparse
import uuid


class ExportError(RuntimeError):
    """The API did not provide a complete, consistently bound public snapshot."""


_PAGE_SIZE = 100
_MAX_WORKERS = 4
_HTTP_TIMEOUT = 180
_HASH_RE = re.compile(r"[a-f0-9]{64}")
_PLAYER_MEDIA_RE = re.compile(
    r"/media/player-photos/(S[0-9]{1,4})/([a-f0-9]{64}\.(?:jpg|jpeg|png|webp))"
)
_FRAME_MEDIA_RE = re.compile(r"/media/bluff-frames/(S[0-9]{1,4})/([a-f0-9]{64}\.png)")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,120}")


def _url(api_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    query = urlencode(params or {})
    return api_url.rstrip("/") + path + (f"?{query}" if query else "")


def _request_bytes(api_url: str, path: str, params: dict[str, Any] | None = None) -> tuple[bytes, dict[str, str]]:
    request = Request(_url(api_url, path, params), headers={"Accept": "application/json, image/*"})
    try:
        with urlopen(request, timeout=_HTTP_TIMEOUT) as response:
            return response.read(), {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as exc:
        detail = exc.read(1024).decode("utf-8", errors="replace").strip()
        raise ExportError(f"API returned HTTP {exc.code} for {path}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ExportError(f"API request failed for {path}: {exc}") from exc


def _request_json(api_url: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body, _ = _request_bytes(api_url, path, params)
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportError(f"API returned invalid JSON for {path}") from exc
    if not isinstance(value, dict):
        raise ExportError(f"API returned a non-object response for {path}")
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _HASH_RE.fullmatch(value) is not None


def _input_hash(value: Any) -> str:
    return _sha256(_canonical_json(value))


def _season_window(metadata: dict[str, Any], start: str, end: str) -> list[str] | None:
    rows = metadata.get("seasons")
    if not isinstance(rows, list):
        return None
    seasons = [row.get("season") for row in rows if isinstance(row, dict)]
    if len(seasons) != len(rows) or any(not isinstance(season, str) for season in seasons):
        return None
    try:
        first, last = seasons.index(start), seasons.index(end)
    except ValueError:
        return None
    return seasons[first:last + 1] if first <= last else None


def input_hash_for_path(path: str, metadata: dict[str, Any], *, player_name: str | None = None,
                        available_seasons: list[str] | None = None) -> str | None:
    """Return the stable dependency key for a cacheable release JSON path.

    Paths are relative to ``data/releases/<snapshot_id>``. A missing or invalid
    content fingerprint makes the path non-cacheable and returns None.
    """
    fingerprints = metadata.get("content_fingerprints")
    if not isinstance(fingerprints, dict):
        return None
    implementation = fingerprints.get("implementation")
    if not _is_sha256(implementation):
        return None
    parts = PurePosixPath(path).parts
    if len(parts) == 2 and parts[0] == "games" and parts[1].endswith(".json"):
        game_id = parts[1][:-5]
        games = fingerprints.get("games")
        game_hash = games.get(game_id) if isinstance(games, dict) else None
        if not _is_sha256(game_hash):
            return None
        return _input_hash({"kind": "game-detail", "implementation": implementation,
                            "game": game_hash})
    if (len(parts) == 3 and parts[0] == "players" and parts[2].endswith(".json")
            and "--" in parts[2]):
        player_id = parts[1]
        start, end = parts[2][:-5].split("--", 1)
        seasons = _season_window(metadata, start, end)
        season_hashes = fingerprints.get("seasons")
        if (seasons is None or not isinstance(season_hashes, dict)
                or any(not _is_sha256(season_hashes.get(season)) for season in seasons)
                or not isinstance(player_name, str) or not isinstance(available_seasons, list)
                or any(not isinstance(season, str) for season in available_seasons)):
            return None
        return _input_hash({"kind": "player-range", "implementation": implementation,
                            "seasons": [(season, season_hashes[season]) for season in seasons],
                            "player_id": player_id, "player_name": player_name,
                            "available_seasons": available_seasons})
    if len(parts) == 2 and parts[0] == "stats" and parts[1].endswith(".json") and "--" in parts[1]:
        start, end = parts[1][:-5].split("--", 1)
        seasons = _season_window(metadata, start, end)
        season_hashes = fingerprints.get("seasons")
        if (seasons is None or not isinstance(season_hashes, dict)
                or any(not _is_sha256(season_hashes.get(season)) for season in seasons)):
            return None
        return _input_hash({"kind": "stats-range", "implementation": implementation,
                            "seasons": [(season, season_hashes[season]) for season in seasons]})
    if len(parts) == 3 and parts[0] == "leaderboards" and parts[2].endswith(".json"):
        season, phase = parts[1], parts[2][:-5]
        season_hashes = fingerprints.get("seasons")
        season_hash = season_hashes.get(season) if isinstance(season_hashes, dict) else None
        if not _is_sha256(season_hash):
            return None
        return _input_hash({"kind": "leaderboard", "implementation": implementation,
                            "season": season_hash, "phase": phase})
    if len(parts) == 2 and parts[0] == "bluff-review" and parts[1].endswith(".json"):
        season = parts[1][:-5]
        season_hashes = fingerprints.get("seasons")
        season_hash = season_hashes.get(season) if isinstance(season_hashes, dict) else None
        if not _is_sha256(season_hash):
            return None
        return _input_hash({"kind": "bluff-review", "implementation": implementation,
                            "season": season_hash, "phase": "all"})
    return None


def _walk_media_values(value: Any) -> Iterable[tuple[str, str | None]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"url", "image_url"} and isinstance(child, str) and "/media/" in child:
                expected = value.get("sha256") if isinstance(value.get("sha256"), str) else None
                yield child, expected
            else:
                yield from _walk_media_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_media_values(child)
    elif isinstance(value, str) and "/media/" in value:
        yield value, None


def _media_endpoint(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment or parsed.scheme or parsed.netloc:
        raise ExportError(f"Media reference must be a relative public URL: {url}")
    path = parsed.path
    photo = _PLAYER_MEDIA_RE.fullmatch(path)
    if photo:
        season, filename = photo.groups()
        return f"/api/v1/photos/{season}/{filename}", f"player-photos/{season}/{filename}", filename.split(".", 1)[0]
    frame = _FRAME_MEDIA_RE.fullmatch(path)
    if frame:
        season, filename = frame.groups()
        return f"/api/v1/bluff-frames/{season}/{filename}", f"bluff-frames/{season}/{filename}", filename[:-4]
    raise ExportError(f"Media reference is outside the public allowlist: {url}")


def _media_references(values: list | dict | None) -> dict[str, tuple[str, str]]:
    if values is None:
        raise ExportError("Export manifest is missing its media_assets list")

    references: dict[str, tuple[str, str]] = {}
    for url, declared_hash in _walk_media_values(values):
        endpoint, relative, path_hash = _media_endpoint(url)
        if not _HASH_RE.fullmatch(path_hash):
            raise ExportError(f"Media filename has no SHA-256 content hash: {url}")
        if declared_hash is not None and declared_hash != path_hash:
            raise ExportError(f"Media reference hash disagrees with its filename: {url}")
        previous = references.get(url)
        expected = declared_hash or path_hash
        if previous is not None and previous[1] != expected:
            raise ExportError(f"Conflicting media hashes for {url}")
        references[url] = (endpoint, expected)
    return references


def _media_target(root: Path, relative: str, url: str) -> Path:
    parts = PurePosixPath(relative).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ExportError(f"Unsafe media path: {url}")
    return root.joinpath(*parts)


def _write_media_body(target: Path, body: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(body)
    os.replace(temporary, target)


def sync_media(api_url: str, destination: Path, values: list | dict | None = None) -> list[dict[str, str]]:
    """Copy referenced allowlisted images, checking their content-addressed names."""
    if values is None:
        values = _request_json(api_url, "/api/v1/export-manifest").get("media_assets")
    references = _media_references(values)

    root = Path(destination)
    copied: list[dict[str, str]] = []
    for url in sorted(references):
        endpoint, expected_hash = references[url]
        body, _ = _request_bytes(api_url, endpoint)
        actual_hash = _sha256(body)
        if actual_hash != expected_hash:
            raise ExportError(f"Media content hash mismatch for {url}")
        _, relative, _ = _media_endpoint(url)
        target = _media_target(root, relative, url)
        if target.is_file():
            if _sha256(target.read_bytes()) != expected_hash:
                raise ExportError(f"Existing media file has the wrong hash: {target}")
        else:
            _write_media_body(target, body)
        copied.append({"url": url, "sha256": actual_hash, "path": relative})
    return copied


def _sync_media_with_reuse(api_url: str, destination: Path, values: list | dict | None,
                           reuse_from: Path | None) -> tuple[list[dict[str, str]], int, int]:
    references = _media_references(values)
    root = Path(destination)
    copied: list[dict[str, str]] = []
    reused = fetched = 0
    for url in sorted(references):
        endpoint, expected_hash = references[url]
        _, relative, _ = _media_endpoint(url)
        target = _media_target(root, relative, url)
        if target.exists():
            if target.is_symlink() or not target.is_file() or _sha256(target.read_bytes()) != expected_hash:
                raise ExportError(f"Existing media file has the wrong hash: {target}")
            actual_hash = expected_hash
            reused += 1
        else:
            source = _media_target(reuse_from / "media", relative, url) if reuse_from is not None else None
            if source is not None and source.exists():
                if source.is_symlink() or not source.is_file():
                    raise ExportError(f"Existing reused media file is not a regular file: {source}")
                body = source.read_bytes()
                actual_hash = _sha256(body)
                if actual_hash != expected_hash:
                    raise ExportError(f"Reused media content hash mismatch for {url}")
                _write_media_body(target, body)
                reused += 1
            else:
                body, _ = _request_bytes(api_url, endpoint)
                actual_hash = _sha256(body)
                if actual_hash != expected_hash:
                    raise ExportError(f"Media content hash mismatch for {url}")
                _write_media_body(target, body)
                fetched += 1
        copied.append({"url": url, "sha256": actual_hash, "path": relative})
    return copied, reused, fetched


def _safe_base_path(value: str) -> str:
    if value == "/":
        return ""
    if value and (not value.startswith("/") or value.endswith("/") or "\\" in value or "//" in value):
        raise ExportError("base_path must be empty or a slash-prefixed path without a trailing slash")
    if any(part in {".", ".."} for part in value.split("/")[1:]):
        raise ExportError("base_path cannot contain dot path segments")
    return value


def _validate_manifest(metadata: dict[str, Any]) -> tuple[str, list[str]]:
    release = metadata.get("release")
    if not isinstance(release, dict) or not isinstance(release.get("id"), str):
        raise ExportError("Export manifest is missing the active release")
    release_id = release["id"]
    if metadata.get("release_id") != release_id:
        raise ExportError("Export manifest release_id does not match release.id")
    if type(release.get("game_count")) is not int or release["game_count"] < 0:
        raise ExportError("Export manifest has an invalid release game_count")
    if not isinstance(release.get("source_hash"), str) or not release["source_hash"]:
        raise ExportError("Export manifest is missing the release source_hash")
    if type(metadata.get("analytics_version")) is not int:
        raise ExportError("Export manifest is missing analytics_version")

    raw_seasons = metadata.get("seasons")
    if not isinstance(raw_seasons, list):
        raise ExportError("Export manifest seasons must be a list")
    seasons: list[str] = []
    for row in raw_seasons:
        if (not isinstance(row, dict) or not isinstance(row.get("season"), str)
                or type(row.get("game_count")) is not int or row["game_count"] < 0
                or not isinstance(row.get("phases"), list)
                or any(not isinstance(phase, str) for phase in row["phases"])):
            raise ExportError("Export manifest contains an invalid season entry")
        season = row["season"]
        if not _SAFE_ID_RE.fullmatch(season) or season in seasons:
            raise ExportError("Export manifest has an unsafe or duplicate season ID")
        seasons.append(season)
    if release["game_count"] and not seasons:
        raise ExportError("A nonempty release has no published seasons")
    if sum(row["game_count"] for row in raw_seasons) != release["game_count"]:
        raise ExportError("Export manifest season totals do not match the release game_count")

    publication_rows = metadata.get("bluff_publications")
    if (not isinstance(publication_rows, list)
            or any(not isinstance(row, dict) or not isinstance(row.get("season"), str)
                   for row in publication_rows)
            or [row["season"] for row in publication_rows] != seasons):
        raise ExportError("Export manifest bluff publications do not cover every season")
    for row in publication_rows:
        publication_id, payload_hash = row.get("publication_id"), row.get("payload_hash")
        if (publication_id is None) != (payload_hash is None):
            raise ExportError(f"Incomplete bluff publication binding for {row.get('season')}")
        if payload_hash is not None and not _HASH_RE.fullmatch(payload_hash):
            raise ExportError(f"Invalid bluff payload hash for {row.get('season')}")

    media_hashes = metadata.get("media_manifest_hashes")
    if (not isinstance(media_hashes, dict)
            or set(media_hashes) != {"player_photos", "bluff_frames"}
            or any(not isinstance(value, str) or not _HASH_RE.fullmatch(value)
                   for value in media_hashes.values())):
        raise ExportError("Export manifest media hashes are missing or invalid")
    media_assets = metadata.get("media_assets")
    if not isinstance(media_assets, list):
        raise ExportError("Export manifest media_assets must be a list")
    for asset in media_assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("url"), str):
            raise ExportError("Export manifest contains an invalid media asset")
        _, _, filename_hash = _media_endpoint(asset["url"])
        if (not isinstance(asset.get("sha256"), str) or not _HASH_RE.fullmatch(asset["sha256"])
                or asset["sha256"] != filename_hash):
            raise ExportError(f"Export manifest media hash does not match its filename: {asset['url']}")
    return release_id, seasons


def _check_release(response: dict[str, Any], release_id: str, context: str,
                   analytics_version: int | None = None) -> None:
    if response.get("release_id") != release_id:
        raise ExportError(f"{context} belongs to a different release")
    if analytics_version is not None and response.get("analytics_version") != analytics_version:
        raise ExportError(f"{context} uses a different analytics_version")


def _paged_items(api_url: str, path: str, params: dict[str, Any], *, release_id: str,
                 analytics_version: int | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    first = _request_json(api_url, path, {**params, "page": 1, "page_size": _PAGE_SIZE})
    _check_release(first, release_id, path, analytics_version)
    if first.get("page") != 1:
        raise ExportError(f"{path} did not return page 1")
    items = first.get("items")
    total = first.get("total")
    if not isinstance(items, list) or type(total) is not int or total < 0:
        raise ExportError(f"{path} returned an invalid first page")
    expected_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    all_items = list(items)
    for page in range(2, expected_pages + 1):
        response = _request_json(api_url, path, {**params, "page": page, "page_size": _PAGE_SIZE})
        _check_release(response, release_id, f"{path} page {page}", analytics_version)
        if response.get("total") != total or response.get("page") != page:
            raise ExportError(f"{path} pagination changed while exporting")
        page_items = response.get("items")
        if not isinstance(page_items, list):
            raise ExportError(f"{path} page {page} has no items list")
        all_items.extend(page_items)
    if len(all_items) != total:
        raise ExportError(f"{path} exported {len(all_items)} of {total} records")
    first["items"] = all_items
    first["page"] = 1
    first["page_size"] = _PAGE_SIZE
    return first, all_items


def _assert_unique(items: list[dict[str, Any]], key: str, label: str) -> None:
    identifiers = [item.get(key) for item in items]
    if any(not isinstance(value, str) or not value for value in identifiers):
        raise ExportError(f"{label} has a missing {key}")
    if len(identifiers) != len(set(identifiers)):
        raise ExportError(f"{label} contains duplicate {key} values")


def _parallel_map(function: Callable[[Any], Any], values: list[Any]) -> list[Any]:
    if not values:
        return []
    results: list[Any] = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        for start in range(0, len(values), 16):
            results.extend(executor.map(function, values[start:start + 16]))
    return results


def _ranges(seasons: list[str]) -> list[dict[str, Any]]:
    return [
        {"start": seasons[start], "end": seasons[end], "seasons": seasons[start:end + 1]}
        for start in range(len(seasons)) for end in range(start, len(seasons))
    ]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def _response_media(data_root: Path) -> list[dict[str, str]]:
    references: dict[str, str] = {}
    for path in data_root.rglob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExportError(f"Cannot read generated JSON while collecting media: {path}") from exc
        for url, declared_hash in _walk_media_values(value):
            _, _, path_hash = _media_endpoint(url)
            expected_hash = declared_hash or path_hash
            previous = references.get(url)
            if previous is not None and previous != expected_hash:
                raise ExportError(f"Conflicting media hashes for {url}")
            references[url] = expected_hash
    return [{"url": url, "sha256": references[url]} for url in sorted(references)]


def _publication_map(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["season"]: {"season": row["season"], "publication_id": row["publication_id"],
                             "payload_hash": row["payload_hash"]}
            for row in metadata["bluff_publications"]}


def _check_bluff_binding(response: dict[str, Any], season: str,
                         publication_map: dict[str, dict[str, Any]], context: str) -> None:
    expected = publication_map[season]
    if ("bluff_publication_id" not in response or "bluff_payload_hash" not in response
            or response["bluff_publication_id"] != expected["publication_id"]
            or response["bluff_payload_hash"] != expected["payload_hash"]):
        raise ExportError(f"{context} used a different bluff publication for {season}")


def _fetch_one_game(api_url: str, game_id: str, release_id: str, analytics_version: int) -> dict[str, Any]:
    if not _SAFE_ID_RE.fullmatch(game_id):
        raise ExportError(f"Unsafe game ID: {game_id}")
    response = _request_json(api_url, f"/api/v1/games/{quote(game_id, safe='')}")
    _check_release(response, release_id, f"game {game_id}", analytics_version)
    if response.get("id") != game_id:
        raise ExportError(f"Game detail ID does not match requested ID {game_id}")
    if not isinstance(response.get("search_text"), str):
        raise ExportError(f"Game {game_id} is missing search_text")
    return response


def _fetch_one_player(api_url: str, player_id: str, interval: dict[str, Any], release_id: str,
                      analytics_version: int, publication_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not _SAFE_ID_RE.fullmatch(player_id):
        raise ExportError(f"Unsafe player ID: {player_id}")
    params = {"season_start": interval["start"], "season_end": interval["end"],
              "minimum_appearances": 0}
    response = _request_json(api_url, f"/api/v1/players/{quote(player_id, safe='')}", params)
    _check_release(response, release_id, f"player {player_id} {interval['start']}--{interval['end']}",
                   analytics_version)
    if response.get("id") != player_id:
        raise ExportError(f"Player detail ID does not match requested ID {player_id}")
    scope = response.get("scope")
    if (not isinstance(scope, dict) or scope.get("season_start") != interval["start"]
            or scope.get("season_end") != interval["end"] or scope.get("seasons") != interval["seasons"]
            or scope.get("minimum_appearances") != 0):
        raise ExportError(f"Player detail {player_id} has the wrong season or appearance scope")
    expected_publications = [publication_map[season] for season in interval["seasons"]]
    if response.get("bluff_publications") != expected_publications:
        raise ExportError(f"Player detail {player_id} has a different cross-season bluff binding")
    return response


def _load_reuse_context(reuse_from: Path | None, reuse_index: dict[str, Any] | None,
                        partial_season: str | None) -> dict[str, Any] | None:
    if reuse_from is None or partial_season is not None:
        return None
    root = Path(reuse_from)
    manifest_path = root / "data" / "manifest.json"
    try:
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExportError(f"Reuse site is missing data/manifest.json: {manifest_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"Cannot read reuse site manifest: {manifest_path}") from exc
    if not isinstance(old_manifest, dict) or old_manifest.get("complete") is not True:
        return None
    snapshot_id = old_manifest.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not _SAFE_ID_RE.fullmatch(snapshot_id):
        raise ExportError("Reuse site manifest has an invalid snapshot_id")
    release_root = root / "data" / "releases" / snapshot_id
    files: dict[str, Any] = {}
    metadata: dict[str, Any] | None = None
    if reuse_index is not None:
        if not isinstance(reuse_index, dict):
            raise ExportError("Reuse export index must be an object")
        if reuse_index.get("schema_version") != 1:
            raise ExportError("Reuse export index has an unsupported schema_version")
        candidate_files = reuse_index.get("files")
        if not isinstance(candidate_files, dict):
            raise ExportError("Reuse export index is missing its files object")
        files = candidate_files
        candidate_metadata = reuse_index.get("metadata")
        if isinstance(candidate_metadata, dict):
            metadata = candidate_metadata
    return {"root": root, "release_root": release_root, "files": files,
            "metadata": metadata}


def _load_cached_json(reuse_context: dict[str, Any] | None, relative: str,
                      input_hash: str | None, release_id: str,
                      publication_map: dict[str, dict[str, Any]], *,
                      season: str | None = None, seasons: list[str] | None = None) -> dict[str, Any] | None:
    if reuse_context is None or input_hash is None:
        return None
    previous_metadata = reuse_context.get("metadata")
    if (not isinstance(previous_metadata, dict)
            or input_hash_for_path(relative, previous_metadata, player_name="",
                                  available_seasons=[]) is None):
        return None
    entry = reuse_context["files"].get(relative)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ExportError(f"Reuse export index has an invalid entry for {relative}")
    if entry.get("input_hash") != input_hash:
        return None
    expected_hash = entry.get("sha256")
    if not _is_sha256(expected_hash):
        raise ExportError(f"Reuse export index has an invalid file hash for {relative}")
    source_root: Path = reuse_context["release_root"]
    source = source_root.joinpath(*PurePosixPath(relative).parts)
    try:
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(source_root.resolve()):
            raise ExportError(f"Reused snapshot file is missing or unsafe: {source}")
        body = source.read_bytes()
    except OSError as exc:
        raise ExportError(f"Cannot read reused snapshot file: {source}") from exc
    actual_hash = _sha256(body)
    if actual_hash != expected_hash:
        raise ExportError(f"Reused snapshot file hash mismatch: {source}")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportError(f"Reused snapshot file is invalid JSON: {source}") from exc
    if not isinstance(value, dict):
        raise ExportError(f"Reused snapshot file is not a JSON object: {source}")
    result = dict(value)
    result["release_id"] = release_id
    if "bluff_publication_id" in result or "bluff_payload_hash" in result:
        publication_season = season or result.get("season")
        if isinstance(publication_season, str) and publication_season in publication_map:
            binding = publication_map[publication_season]
            if "bluff_publication_id" in result:
                result["bluff_publication_id"] = binding["publication_id"]
            if "bluff_payload_hash" in result:
                result["bluff_payload_hash"] = binding["payload_hash"]
    if "bluff_publications" in result:
        selected_seasons = seasons
        if selected_seasons is None and isinstance(result.get("scope"), dict):
            possible = result["scope"].get("seasons")
            selected_seasons = possible if isinstance(possible, list) else None
        if selected_seasons is not None:
            result["bluff_publications"] = [publication_map[item] for item in selected_seasons]
    return result


def _changed_fingerprints(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    current_fp = current.get("content_fingerprints")
    previous_fp = previous.get("content_fingerprints") if isinstance(previous, dict) else None
    if not isinstance(current_fp, dict) or not isinstance(previous_fp, dict):
        games = current_fp.get("games") if isinstance(current_fp, dict) else {}
        season_hashes = current_fp.get("seasons") if isinstance(current_fp, dict) else {}
        return {"implementation": True,
                "games": sorted(games) if isinstance(games, dict) else [],
                "seasons": sorted(season_hashes) if isinstance(season_hashes, dict) else []}
    current_games = current_fp.get("games") if isinstance(current_fp.get("games"), dict) else {}
    previous_games = previous_fp.get("games") if isinstance(previous_fp.get("games"), dict) else {}
    current_seasons = current_fp.get("seasons") if isinstance(current_fp.get("seasons"), dict) else {}
    previous_seasons = previous_fp.get("seasons") if isinstance(previous_fp.get("seasons"), dict) else {}
    return {
        "implementation": current_fp.get("implementation") != previous_fp.get("implementation"),
        "games": sorted(key for key in set(current_games) | set(previous_games)
                         if current_games.get(key) != previous_games.get(key)),
        "seasons": sorted(key for key in set(current_seasons) | set(previous_seasons)
                          if current_seasons.get(key) != previous_seasons.get(key)),
    }


def export_snapshot(api_url: str, output: Path, *, base_path: str = "", build_id: str | None = None,
                    partial_season: str | None = None, partial_game: str | None = None,
                    partial_player: str | None = None, reuse_from: Path | None = None,
                    reuse_index: dict[str, Any] | None = None) -> dict[str, Any]:
    """Export a full snapshot, or a marked one-season/one-game/one-player sample."""
    base_path = _safe_base_path(base_path)
    if any(value is not None for value in (partial_game, partial_player)) and partial_season is None:
        raise ExportError("partial_game and partial_player require partial_season")

    health = _request_json(api_url, "/health")
    if health.get("status") != "ok":
        raise ExportError("Published API health check did not return status=ok")
    initial_metadata = _request_json(api_url, "/api/v1/export-manifest")
    release_id, all_seasons = _validate_manifest(initial_metadata)
    analytics_version = initial_metadata["analytics_version"]
    release = initial_metadata["release"]
    if partial_season is not None:
        if partial_season not in all_seasons:
            raise ExportError(f"Partial season {partial_season} is not in the active release")
        seasons = [partial_season]
    else:
        seasons = list(all_seasons)
    reuse_context = _load_reuse_context(reuse_from, reuse_index, partial_season)
    metrics = {
        "game_details": {"reused": 0, "fetched": 0},
        "player_ranges": {"reused": 0, "fetched": 0},
        "stats_ranges": {"reused": 0, "fetched": 0},
        "leaderboards": {"reused": 0, "fetched": 0},
        "reviews": {"reused": 0, "fetched": 0},
        "media": {"reused": 0, "fetched": 0},
    }
    reused_paths: set[str] = set()
    file_input_hashes: dict[str, str | None] = {}

    overview = _request_json(api_url, "/api/v1/overview")
    if (overview.get("release", {}).get("id") != release_id
            or overview.get("release", {}).get("source_hash") != release["source_hash"]):
        raise ExportError("Overview does not match the export-manifest release")
    releases = _request_json(api_url, "/api/v1/releases")
    active_releases = [row for row in releases.get("items", []) if row.get("active")]
    if len(active_releases) != 1 or active_releases[0].get("id") != release_id:
        raise ExportError("Release history does not match the export-manifest release")

    game_pages, listed_games = _paged_items(
        api_url, "/api/v1/games", {"season": partial_season} if partial_season else {},
        release_id=release_id, analytics_version=None,
    )
    _assert_unique(listed_games, "id", "Game index")
    if partial_season is None:
        if len(listed_games) != release["game_count"]:
            raise ExportError("Full game listing does not match the release game_count")
        if game_pages["total"] != release["game_count"]:
            raise ExportError("Full game pagination total does not match the release")
    else:
        season_metadata = next(row for row in initial_metadata["seasons"] if row["season"] == partial_season)
        if game_pages["total"] != season_metadata["game_count"]:
            raise ExportError(f"Game count for partial season {partial_season} changed")
    season_game_summaries = list(listed_games)
    if partial_season is None:
        for season_row in initial_metadata["seasons"]:
            season_count = sum(game.get("season") == season_row["season"] for game in listed_games)
            if season_count != season_row["game_count"]:
                raise ExportError(f"Game index does not cover season {season_row['season']} completely")

    players_by_season: dict[str, dict[str, Any]] = {}
    all_player_ids: dict[str, str] = {}
    player_available_seasons: dict[str, list[str]] = {}
    for season in seasons:
        page, items = _paged_items(api_url, "/api/v1/players", {"season": season},
                                   release_id=release_id, analytics_version=analytics_version)
        _assert_unique(items, "id", f"Player index for {season}")
        players_by_season[season] = page
        for item in items:
            all_player_ids[item["id"]] = item["name"]
            player_available_seasons.setdefault(item["id"], []).append(season)
    if partial_season is None and len(all_player_ids) != overview.get("totals", {}).get("players"):
        raise ExportError("Season player union does not match overview player count")

    if partial_season is not None:
        chosen_game = next((item for item in listed_games if item.get("id") == partial_game), None) if partial_game else None
        if partial_game and chosen_game is None:
            raise ExportError(f"Partial game {partial_game} is not in season {partial_season}")
        if chosen_game is None:
            if not listed_games:
                raise ExportError(f"Partial season {partial_season} contains no games")
            chosen_game = listed_games[0]
        listed_games = [chosen_game]
        default_player = next((player.get("id") for player in chosen_game.get("players", [])
                               if isinstance(player.get("id"), str)), None)
        selected_player = partial_player or default_player or next(iter(all_player_ids), None)
        if selected_player is None or selected_player not in all_player_ids:
            raise ExportError(f"Partial player {selected_player!r} is not in season {partial_season}")
        partial_info = {"enabled": True, "season": partial_season,
                        "game_id": chosen_game["id"], "player_id": selected_player}
        all_player_ids = {selected_player: all_player_ids[selected_player]}
        sample_page = players_by_season[partial_season]
        sample_items = [item for item in sample_page["items"] if item["id"] == selected_player]
        if not sample_items:
            raise ExportError(f"Partial player {selected_player} is missing from {partial_season} player index")
        players_by_season[partial_season] = {
            **sample_page, "items": sample_items, "total": len(sample_items),
            "page": 1, "page_size": len(sample_items),
        }
        overview["seasons"] = [row for row in overview.get("seasons", [])
                                if row.get("id") == partial_season]
        overview["recent_games"] = [chosen_game]
    else:
        partial_info = {"enabled": False, "season": None, "game_id": None, "player_id": None}
        selected_player = None

    game_ids = [item["id"] for item in listed_games]
    publication_map = _publication_map(initial_metadata)
    game_details_by_id: dict[str, dict[str, Any]] = {}
    game_misses: list[str] = []
    for game_id in game_ids:
        relative = f"games/{game_id}.json"
        key = input_hash_for_path(relative, initial_metadata)
        cached = _load_cached_json(reuse_context, relative, key, release_id, publication_map)
        if cached is None:
            game_misses.append(game_id)
        else:
            game_details_by_id[game_id] = cached
            metrics["game_details"]["reused"] += 1
            reused_paths.add(relative)
        file_input_hashes[relative] = key
    fetched_games = _parallel_map(
        lambda game_id: _fetch_one_game(api_url, game_id, release_id, analytics_version), game_misses,
    )
    metrics["game_details"]["fetched"] = len(fetched_games)
    game_details_by_id.update({detail["id"]: detail for detail in fetched_games})
    game_details = [game_details_by_id[game_id] for game_id in game_ids]
    detail_by_id = {detail["id"]: detail for detail in game_details}
    if set(detail_by_id) != set(game_ids) or len(detail_by_id) != len(game_ids):
        raise ExportError("Game details do not cover the game index exactly")
    summary_by_id = {item["id"]: item for item in listed_games}
    for game_id, detail in detail_by_id.items():
        _check_release(detail, release_id, f"game {game_id}", analytics_version)
        if detail.get("id") != game_id:
            raise ExportError(f"Game detail ID does not match requested ID {game_id}")
        if not isinstance(detail.get("search_text"), str):
            raise ExportError(f"Game {game_id} is missing search_text")
        summary = summary_by_id[game_id]
        if detail.get("season") != summary.get("season") or detail.get("search_text") != summary.get("search_text"):
            raise ExportError(f"Game {game_id} detail does not match its index entry")

    ranges = _ranges(seasons)
    player_ids = list(all_player_ids)
    player_jobs = [(player_id, interval) for interval in ranges for player_id in player_ids]
    player_result_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    player_misses: list[tuple[str, dict[str, Any]]] = []
    for player_id, interval in player_jobs:
        relative = f"players/{player_id}/{interval['start']}--{interval['end']}.json"
        key = input_hash_for_path(relative, initial_metadata,
                                  player_name=all_player_ids[player_id],
                                  available_seasons=player_available_seasons.get(player_id, []))
        cached = _load_cached_json(reuse_context, relative, key, release_id, publication_map,
                                   seasons=interval["seasons"])
        if cached is None:
            player_misses.append((player_id, interval))
        else:
            _check_release(cached, release_id, f"player {player_id} {interval['start']}--{interval['end']}",
                           analytics_version)
            if cached.get("id") != player_id:
                raise ExportError(f"Player detail ID does not match requested ID {player_id}")
            scope = cached.get("scope")
            if (not isinstance(scope, dict) or scope.get("season_start") != interval["start"]
                    or scope.get("season_end") != interval["end"] or scope.get("seasons") != interval["seasons"]
                    or scope.get("minimum_appearances") != 0):
                raise ExportError(f"Player detail {player_id} has the wrong season or appearance scope")
            if cached.get("bluff_publications") != [publication_map[season] for season in interval["seasons"]]:
                raise ExportError(f"Player detail {player_id} has a different cross-season bluff binding")
            player_result_by_key[(player_id, interval["start"], interval["end"])] = cached
            metrics["player_ranges"]["reused"] += 1
            reused_paths.add(relative)
        file_input_hashes[relative] = key
    fetched_players = _parallel_map(
        lambda job: _fetch_one_player(api_url, job[0], job[1], release_id,
                                      analytics_version, publication_map), player_misses,
    )
    metrics["player_ranges"]["fetched"] = len(fetched_players)
    player_result_by_key.update({(player_id, interval["start"], interval["end"]): detail
                                 for (player_id, interval), detail in zip(player_misses, fetched_players)})
    player_results = [player_result_by_key[(player_id, interval["start"], interval["end"])]
                      for player_id, interval in player_jobs]

    stats_results = []
    stats_reused = 0
    stats_fetched = 0
    for interval in ranges:
        relative = f"stats/{interval['start']}--{interval['end']}.json"
        key = input_hash_for_path(relative, initial_metadata)
        response = _load_cached_json(reuse_context, relative, key, release_id, publication_map)
        if response is None:
            response = _request_json(api_url, "/api/v1/stats", {
                "season_start": interval["start"], "season_end": interval["end"],
            })
            stats_fetched += 1
        else:
            stats_reused += 1
            reused_paths.add(relative)
        file_input_hashes[relative] = key
        _check_release(response, release_id, f"stats {interval['start']}--{interval['end']}", analytics_version)
        scope = response.get("scope")
        if (not isinstance(scope, dict) or scope.get("seasons") != interval["seasons"]
                or scope.get("season_start") != interval["start"] or scope.get("season_end") != interval["end"]):
            raise ExportError(f"Stats {interval['start']}--{interval['end']} returned the wrong scope")
        stats_results.append(response)
    metrics["stats_ranges"] = {"reused": stats_reused, "fetched": stats_fetched}

    leaderboards: list[tuple[str, str, dict[str, Any]]] = []
    bluff_reviews: list[tuple[str, dict[str, Any]]] = []
    leaderboard_reused = leaderboard_fetched = 0
    review_reused = review_fetched = 0
    for season in seasons:
        season_phases = next(row["phases"] for row in initial_metadata["seasons"] if row["season"] == season)
        leaderboard_phases = ["all"] + (["finals_week"] if "finals_week" in season_phases else [])
        for phase in leaderboard_phases:
            relative = f"leaderboards/{season}/{phase}.json"
            key = input_hash_for_path(relative, initial_metadata)
            response = _load_cached_json(reuse_context, relative, key, release_id, publication_map,
                                         season=season)
            if response is None:
                response = _request_json(api_url, "/api/v1/leaderboard", {"season": season, "phase": phase})
                leaderboard_fetched += 1
            else:
                leaderboard_reused += 1
                reused_paths.add(relative)
            file_input_hashes[relative] = key
            _check_release(response, release_id, f"leaderboard {season}/{phase}", analytics_version)
            _check_bluff_binding(response, season, publication_map, f"leaderboard {season}/{phase}")
            if response.get("season") != season or response.get("phase") != phase:
                raise ExportError(f"Leaderboard returned the wrong scope for {season}/{phase}")
            expected_games = sum(game.get("season") == season
                                 and (phase == "all" or game.get("phase") == "finals_week")
                                 for game in season_game_summaries)
            if response.get("game_count") != expected_games:
                raise ExportError(f"Leaderboard game count changed for {season}/{phase}")
            leaderboards.append((season, phase, response))

        relative = f"bluff-review/{season}.json"
        key = input_hash_for_path(relative, initial_metadata)
        review = _load_cached_json(reuse_context, relative, key, release_id, publication_map,
                                   season=season)
        if review is None:
            review = _request_json(api_url, "/api/v1/bluff-review", {"season": season, "status": "all"})
            review_fetched += 1
        else:
            review_reused += 1
            reused_paths.add(relative)
        file_input_hashes[relative] = key
        _check_release(review, release_id, f"bluff review {season}", analytics_version)
        _check_bluff_binding(review, season, publication_map, f"bluff review {season}")
        if review.get("season") != season or review.get("status") != "all":
            raise ExportError(f"Bluff review returned the wrong scope for {season}")
        season_game_count = next(row["game_count"] for row in initial_metadata["seasons"]
                                 if row["season"] == season)
        if review.get("summary", {}).get("games") != season_game_count:
            raise ExportError(f"Bluff review game count changed for {season}")
        bluff_reviews.append((season, review))

    metrics["leaderboards"] = {"reused": leaderboard_reused, "fetched": leaderboard_fetched}
    metrics["reviews"] = {"reused": review_reused, "fetched": review_fetched}

    scoped_metadata = {
        **initial_metadata,
        "seasons": [row for row in initial_metadata["seasons"] if row["season"] in seasons],
        "bluff_publications": [row for row in initial_metadata["bluff_publications"]
                               if row["season"] in seasons],
    }
    snapshot_fingerprint = _sha256(_canonical_json({
        "release_id": release_id, "source_hash": release["source_hash"],
        "seasons": scoped_metadata["seasons"], "bluff_publications": scoped_metadata["bluff_publications"],
        "media_manifest_hashes": initial_metadata["media_manifest_hashes"],
        "content_fingerprints": initial_metadata.get("content_fingerprints"),
        "analytics_version": analytics_version, "partial": partial_info,
    }))
    snapshot_id = f"snapshot-{snapshot_fingerprint}"
    final_output = Path(output)
    final_output.parent.mkdir(parents=True, exist_ok=True)
    if final_output.exists():
        raise ExportError(f"Snapshot output already exists: {final_output}")
    stage = Path(tempfile.mkdtemp(prefix=f".{final_output.name}.export-", dir=final_output.parent))
    try:
        data_root = stage / "data"
        release_root = data_root / "releases" / snapshot_id
        def write_release_json(relative: str, value: Any) -> None:
            _write_json(release_root / relative, value)
            file_input_hashes.setdefault(relative, _input_hash({"fresh_path": relative, "value": value}))

        write_release_json("overview.json", overview)
        write_release_json("releases.json", releases)
        write_release_json("games/index.json", {
            "release_id": release_id, "total": len(listed_games), "items": listed_games,
        })
        for game_id, detail in detail_by_id.items():
            write_release_json(f"games/{game_id}.json", detail)

        player_index = sorted(
            ({"id": player_id, "name": name} for player_id, name in all_player_ids.items()),
            key=lambda item: (item["name"].casefold(), item["name"], item["id"]),
        )
        write_release_json("players/index.json", {
            "release_id": release_id, "seasons": seasons, "items": player_index,
        })
        for season, page in players_by_season.items():
            write_release_json(f"players/by-season/{season}.json", page)
        for (player_id, interval), detail in zip(player_jobs, player_results):
            if not _SAFE_ID_RE.fullmatch(player_id):
                raise ExportError(f"Unsafe player ID: {player_id}")
            write_release_json(f"players/{player_id}/{interval['start']}--{interval['end']}.json", detail)
        for interval, response in zip(ranges, stats_results):
            write_release_json(f"stats/{interval['start']}--{interval['end']}.json", response)
        for season, phase, response in leaderboards:
            write_release_json(f"leaderboards/{season}/{phase}.json", response)
        for season, response in bluff_reviews:
            write_release_json(f"bluff-review/{season}.json", response)

        media_references = _response_media(data_root)
        current_media_assets = {asset["url"]: asset["sha256"]
                                for asset in initial_metadata["media_assets"]}
        for reference in media_references:
            if current_media_assets.get(reference["url"]) != reference["sha256"]:
                raise ExportError(
                    f"Snapshot media reference is absent from the current export-manifest allowlist: "
                    f"{reference['url']}"
                )
        if media_references:
            media_files, metrics["media"]["reused"], metrics["media"]["fetched"] = \
                _sync_media_with_reuse(api_url, stage / "media", media_references,
                                       reuse_context["root"] if reuse_context is not None else None)
        else:
            media_files = []

        final_metadata = _request_json(api_url, "/api/v1/export-manifest")
        if final_metadata != initial_metadata:
            raise ExportError("Export metadata changed during snapshot generation")

        expected_game_count = len(listed_games) if partial_season is not None else release["game_count"]
        if len(detail_by_id) != expected_game_count:
            raise ExportError("Exported game detail count is incomplete")
        expected_player_count = len(player_ids)
        if len(player_index) != expected_player_count:
            raise ExportError("Exported player index count is incomplete")
        if len(player_results) != expected_player_count * len(ranges):
            raise ExportError("Exported player range count is incomplete")
        if len(stats_results) != len(ranges):
            raise ExportError("Exported stats range count is incomplete")
        expected_leaderboards = sum(
            1 + ("finals_week" in row["phases"])
            for row in scoped_metadata["seasons"]
        )
        if len(leaderboards) != expected_leaderboards or len(bluff_reviews) != len(seasons):
            raise ExportError("Exported leaderboard or bluff-review coverage is incomplete")

        now = datetime.now(timezone.utc)
        generated_at = now.isoformat(timespec="seconds").replace("+00:00", "Z")
        if build_id is None:
            build_id = f"export-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        manifest = {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "build_id": build_id,
            "release_id": release_id,
            "source_hash": release["source_hash"],
            "analytics_version": analytics_version,
            "bluff_publications": scoped_metadata["bluff_publications"],
            "media_manifest_hashes": initial_metadata["media_manifest_hashes"],
            "generated_at": generated_at,
            "base_path": base_path,
            "seasons": [{"id": row["season"], "game_count": row["game_count"], "phases": row["phases"]}
                        for row in scoped_metadata["seasons"]],
            "ranges": ranges,
            "counts": {
                "games": len(listed_games), "players": len(player_index),
                "game_details": len(detail_by_id), "player_ranges": len(player_results),
                "stats_ranges": len(stats_results), "leaderboards": len(leaderboards),
                "bluff_reviews": len(bluff_reviews), "media_files": len(media_files),
            },
            "complete": partial_season is None,
            "partial": partial_info,
        }
        _write_json(data_root / "manifest.json", manifest)
        index_files = {}
        for path in sorted(release_root.rglob("*.json")):
            relative = path.relative_to(release_root).as_posix()
            index_files[relative] = {
                "sha256": _sha256(path.read_bytes()),
                "input_hash": file_input_hashes.get(relative)
                or _input_hash({"uncacheable_path": relative, "snapshot_id": snapshot_id}),
                "reused": relative in reused_paths,
            }
        export_index = {
            "schema_version": 1,
            "metadata": initial_metadata,
            "files": index_files,
            "metrics": metrics,
            "changed": _changed_fingerprints(
                initial_metadata, reuse_context.get("metadata") if reuse_context is not None else None),
        }
        _write_json(stage / "export-index.json", export_index)
        os.replace(stage, final_output)
        return manifest
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a version-bound static website snapshot")
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--output", required=True, type=Path, help="snapshot directory to create")
    parser.add_argument("--base-path", default="")
    parser.add_argument("--build-id")
    parser.add_argument("--partial-season")
    parser.add_argument("--partial-game")
    parser.add_argument("--partial-player")
    args = parser.parse_args(argv)
    try:
        manifest = export_snapshot(
            args.api_url, args.output, base_path=args.base_path, build_id=args.build_id,
            partial_season=args.partial_season, partial_game=args.partial_game,
            partial_player=args.partial_player,
        )
    except (ExportError, OSError) as exc:
        parser.exit(1, f"静态快照导出失败：{exc}\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
