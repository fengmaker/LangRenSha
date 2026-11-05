"""Validate an exported static site against its source API and a real browser."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import sys
import tempfile
from threading import Thread
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit, unquote
from urllib.request import urlopen

if __package__:
    from .player_rankings import SNAPSHOT_SCHEMA_VERSION, restore_player_rankings
else:
    from player_rankings import SNAPSHOT_SCHEMA_VERSION, restore_player_rankings


MANIFEST_FIELDS = {
    "schema_version", "snapshot_id", "build_id", "release_id", "source_hash",
    "analytics_version", "bluff_publications", "media_manifest_hashes", "generated_at",
    "base_path", "seasons", "ranges", "counts", "complete", "partial",
}
COUNT_FIELDS = {
    "games", "players", "game_details", "player_ranges", "stats_ranges",
    "leaderboards", "bluff_reviews", "media_files",
}
MAX_SITE_BYTES = 1_000_000_000


class StaticAcceptanceError(RuntimeError):
    """A static snapshot failed an acceptance layer."""


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StaticAcceptanceError(f"Cannot read JSON {path}: {error}") from error


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _without_rankings(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_rankings(item) for key, item in value.items()
                if key not in {"ranking", "ranking_board", "rankings", "ranking_boards"}}
    if isinstance(value, list):
        return [_without_rankings(item) for item in value]
    return value


def _require_equal(expected: Any, actual: Any, label: str) -> None:
    if _canonical(expected) != _canonical(actual):
        raise StaticAcceptanceError(f"{label} differs from the source API")


_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_REUSABLE_API_FILE_TYPES = {"game_detail", "player_range", "stats_range", "leaderboard", "bluff_review"}


def _shared_input_hash_for_path(path: str, metadata: dict[str, Any], *,
                                player_name: str | None = None,
                                available_seasons: list[str] | None = None) -> str | None:
    """Use the exporter-owned dependency key rule for incremental acceptance."""
    try:
        from website.static_publish.export_static import input_hash_for_path
    except ModuleNotFoundError:
        # Support invoking this file directly with static_publish/ as sys.path[0].
        from export_static import input_hash_for_path
    return input_hash_for_path(path, metadata, player_name=player_name,
                               available_seasons=available_seasons)


def _reusable_file_kind(relative: str) -> tuple[str, str | None]:
    path = PurePosixPath(relative)
    parts = path.parts
    if path.suffix != ".json":
        return "", None
    if len(parts) == 2 and parts[0] == "games" and parts[1] != "index.json":
        return "game_detail", parts[1][:-5]
    if len(parts) == 3 and parts[0] == "players" and parts[1] != "by-season" \
            and re.fullmatch(r".+--.+\.json", parts[2]):
        return "player_range", parts[1]
    if len(parts) == 2 and parts[0] == "stats" and re.fullmatch(r".+--.+\.json", parts[1]):
        return "stats_range", None
    if len(parts) == 3 and parts[0] == "leaderboards":
        return "leaderboard", None
    if len(parts) == 2 and parts[0] == "bluff-review":
        return "bluff_review", None
    return "", None


def _validate_export_index(snapshot: dict[str, Any], docs: dict[str, Any],
                           export_index: dict[str, Any], api_metadata: dict[str, Any]) -> dict[str, Any]:
    """Validate the candidate index before trusting any reused API response."""
    required_index_fields = {"schema_version", "metadata", "files", "metrics"}
    if (not isinstance(export_index, dict) or not required_index_fields.issubset(export_index)
            or set(export_index) - (required_index_fields | {"changed"})):
        raise StaticAcceptanceError("Incremental export index has an invalid schema")
    if type(export_index.get("schema_version")) is not int or export_index["schema_version"] != 1:
        raise StaticAcceptanceError("Unsupported incremental export index schema_version")
    metadata = export_index.get("metadata")
    if not isinstance(metadata, dict) or _canonical(metadata) != _canonical(api_metadata):
        raise StaticAcceptanceError("Incremental export index metadata differs from the current API export-manifest")
    files = export_index.get("files")
    if (not isinstance(files, dict) or not isinstance(export_index.get("metrics"), dict)
            or ("changed" in export_index and not isinstance(export_index["changed"], dict))):
        raise StaticAcceptanceError("Incremental export index files or metrics are invalid")

    data_root = snapshot["data"].resolve()
    expected_paths = {path.relative_to(data_root).as_posix()
                      for path in data_root.rglob("*.json") if path.is_file()}
    if set(files) != expected_paths:
        raise StaticAcceptanceError("Incremental export index does not cover the release JSON files exactly")
    player_names = {item.get("id"): item.get("name")
                    for item in docs["players_index"].get("items", [])}
    player_available_seasons: dict[str, list[str]] = {}
    for season in snapshot["seasons"]:
        season_players = _json(data_root / "players" / "by-season" / f"{season}.json").get("items", [])
        for player in season_players:
            player_available_seasons.setdefault(player["id"], []).append(season)
    ranges = {f"{row['start']}--{row['end']}": row for row in snapshot["manifest"]["ranges"]}
    publications = {row["season"]: row for row in snapshot["manifest"]["bluff_publications"]}
    reused_paths: set[str] = set()
    reused_by_kind = {kind: 0 for kind in _REUSABLE_API_FILE_TYPES}
    for relative, entry in files.items():
        if (not isinstance(relative, str) or not relative or "\\" in relative
                or PurePosixPath(relative).is_absolute()
                or any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts)
                or PurePosixPath(relative).as_posix() != relative):
            raise StaticAcceptanceError(f"Invalid incremental export index path: {relative!r}")
        if not isinstance(entry, dict) or set(entry) != {"sha256", "input_hash", "reused"}:
            raise StaticAcceptanceError(f"Invalid incremental export index entry: {relative}")
        if (not isinstance(entry.get("sha256"), str) or not _SHA256_RE.fullmatch(entry["sha256"])
                or not isinstance(entry.get("input_hash"), str) or not _SHA256_RE.fullmatch(entry["input_hash"])
                or not isinstance(entry.get("reused"), bool)):
            raise StaticAcceptanceError(f"Invalid incremental export index hashes or reused flag: {relative}")
        if (relative.startswith("rankings/") and snapshot.get("player_rankings")
                and hashlib.sha256((data_root / relative).read_bytes()).hexdigest() != entry["sha256"]):
            raise StaticAcceptanceError(f"Shared player rankings SHA-256 differs from the site: {relative}")

        target = (data_root / Path(*PurePosixPath(relative).parts)).resolve()
        if not target.is_relative_to(data_root) or not target.is_file():
            raise StaticAcceptanceError(f"Incremental export index file is missing or unsafe: {relative}")
        if not entry["reused"]:
            continue

        kind, player_id = _reusable_file_kind(relative)
        if kind not in _REUSABLE_API_FILE_TYPES:
            raise StaticAcceptanceError(f"Incremental export index marks a non-reusable file as reused: {relative}")
        with target.open("rb") as stream:
            actual_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual_sha != entry["sha256"]:
            raise StaticAcceptanceError(f"Reused file SHA-256 differs from the site: {relative}")
        expected_input_hash = _shared_input_hash_for_path(
            relative, metadata, player_name=player_names.get(player_id),
            available_seasons=player_available_seasons.get(player_id, []))
        if expected_input_hash is None or expected_input_hash != entry["input_hash"]:
            raise StaticAcceptanceError(f"Reused file input_hash differs from its current dependencies: {relative}")
        document = _json(target)
        if (not isinstance(document, dict)
                or document.get("release_id") != snapshot["manifest"]["release_id"]
                or document.get("analytics_version") != snapshot["manifest"]["analytics_version"]):
            raise StaticAcceptanceError(f"Reused file manifest binding differs: {relative}")
        parts = PurePosixPath(relative).parts
        if kind == "game_detail" and document.get("id") != player_id:
            raise StaticAcceptanceError(f"Reused game detail ID differs from its path: {relative}")
        if kind == "player_range":
            interval_name = parts[2][:-5]
            interval = ranges.get(interval_name)
            scope = document.get("scope")
            if (document.get("id") != player_id or interval is None
                    or not isinstance(scope, dict)
                    or scope.get("season_start") != interval["start"]
                    or scope.get("season_end") != interval["end"]
                    or scope.get("seasons") != interval["seasons"]
                    or scope.get("minimum_appearances") != 0):
                raise StaticAcceptanceError(f"Reused player range scope differs from its manifest: {relative}")
            expected_publications = [publications[season] for season in interval["seasons"]]
            if _canonical(document.get("bluff_publications")) != _canonical(expected_publications):
                raise StaticAcceptanceError(f"Reused player range publication binding differs: {relative}")
        elif kind == "stats_range":
            interval_name = parts[1][:-5]
            interval = ranges.get(interval_name)
            scope = document.get("scope")
            if (interval is None or not isinstance(scope, dict)
                    or scope.get("seasons") != interval["seasons"]):
                raise StaticAcceptanceError(f"Reused stats range scope differs from its manifest: {relative}")
        elif kind == "leaderboard":
            season, phase = parts[1], parts[2][:-5]
            binding = publications.get(season)
            if (season not in snapshot["seasons"] or document.get("season") != season
                    or document.get("phase") != phase or binding is None
                    or document.get("bluff_publication_id") != binding.get("publication_id")
                    or document.get("bluff_payload_hash") != binding.get("payload_hash")):
                raise StaticAcceptanceError(f"Reused leaderboard binding differs from its manifest: {relative}")
        elif kind == "bluff_review":
            season = parts[1][:-5]
            binding = publications.get(season)
            if (season not in snapshot["seasons"] or document.get("season") != season
                    or document.get("status") != "all" or binding is None
                    or document.get("bluff_publication_id") != binding.get("publication_id")
                    or document.get("bluff_payload_hash") != binding.get("payload_hash")):
                raise StaticAcceptanceError(f"Reused bluff review binding differs from its manifest: {relative}")
        reused_paths.add(relative)
        reused_by_kind[kind] += 1

    return {"paths": reused_paths, "by_kind": reused_by_kind}


def _get_json(api_url: str, path: str) -> Any:
    with urlopen(api_url.rstrip("/") + path, timeout=45) as response:
        if response.status != 200:
            raise StaticAcceptanceError(f"API returned HTTP {response.status}: {path}")
        return json.load(response)


def _base_path(value: str) -> str:
    value = "/" + value.strip("/") if value.strip("/") else ""
    if not value:
        raise StaticAcceptanceError("--base-path must be a non-root Pages path")
    if ("?" in value or "#" in value or "\\" in value or "//" in value
            or any(part in {".", ".."} for part in unquote(value).split("/"))):
        raise StaticAcceptanceError(f"Invalid --base-path: {value}")
    return value


def _expected_ranges(seasons: list[str]) -> list[dict[str, Any]]:
    return [{"start": seasons[start], "end": seasons[end], "seasons": seasons[start:end + 1]}
            for start in range(len(seasons)) for end in range(start, len(seasons))]


def _route_file(root: Path, route: str) -> Path | None:
    clean = route.strip("/")
    candidates = [root / clean / "index.html", root / f"{clean}.html"] if clean else [root / "index.html"]
    return next((path for path in candidates if path.is_file()), None)


def _check_site_size(total_bytes: int) -> None:
    if total_bytes >= MAX_SITE_BYTES:
        raise StaticAcceptanceError(
            f"Static site is {total_bytes} bytes; GitHub Pages acceptance limit is < {MAX_SITE_BYTES} bytes")


def _load_snapshot(out: Path, base_path: str) -> dict[str, Any]:
    out = out.resolve()
    if not out.is_dir():
        raise StaticAcceptanceError(f"Static output directory does not exist: {out}")
    manifest_path = out / "data" / "manifest.json"
    manifest = _json(manifest_path)
    missing = sorted(MANIFEST_FIELDS - set(manifest))
    if missing:
        raise StaticAcceptanceError("Manifest is missing fields: " + ", ".join(missing))
    if manifest["base_path"] != base_path:
        raise StaticAcceptanceError(
            f"Manifest base_path {manifest['base_path']!r} differs from {base_path!r}")
    if manifest["schema_version"] not in {1, SNAPSHOT_SCHEMA_VERSION}:
        raise StaticAcceptanceError(f"Unsupported static manifest schema_version {manifest['schema_version']!r}")
    if not isinstance(manifest["complete"], bool):
        raise StaticAcceptanceError("Manifest complete must be a boolean")
    partial = manifest["partial"]
    if not isinstance(partial, dict) or not isinstance(partial.get("enabled"), bool):
        raise StaticAcceptanceError("Manifest partial.enabled must be a boolean")
    if manifest["complete"] == partial["enabled"]:
        raise StaticAcceptanceError("Manifest complete and partial.enabled contradict each other")
    if not isinstance(manifest["counts"], dict) or COUNT_FIELDS - set(manifest["counts"]):
        raise StaticAcceptanceError("Manifest counts are incomplete")
    season_rows = manifest["seasons"]
    if (not isinstance(season_rows, list) or not season_rows
            or any(not isinstance(item, dict) or not item.get("id") for item in season_rows)):
        raise StaticAcceptanceError("Manifest seasons must contain season records")
    seasons = [item["id"] for item in season_rows]
    if len(seasons) != len(set(seasons)):
        raise StaticAcceptanceError("Manifest seasons contain duplicate IDs")
    if partial["enabled"] and (len(seasons) != 1
                               or not partial.get("season") or not partial.get("game_id")
                               or not partial.get("player_id")):
        raise StaticAcceptanceError("Partial manifest must identify one season, game, and player")
    actual_ranges = [{"start": row.get("start"), "end": row.get("end"), "seasons": row.get("seasons")}
                     for row in manifest["ranges"]]
    if actual_ranges != _expected_ranges(seasons):
        raise StaticAcceptanceError("Manifest ranges do not contain every contiguous season range")
    data = out / "data" / "releases" / manifest["snapshot_id"]
    rankings = {}
    if manifest["schema_version"] == SNAPSHOT_SCHEMA_VERSION:
        expected_rankings = {f"{row['start']}--{row['end']}.json" for row in actual_ranges}
        if {path.name for path in (data / "rankings").glob("*.json")} != expected_rankings:
            raise StaticAcceptanceError("Shared player ranking files do not cover the snapshot ranges")
        for row in actual_ranges:
            name = f"{row['start']}--{row['end']}.json"
            shared = _json(data / "rankings" / name)
            scope = {"season_start": row["start"], "season_end": row["end"],
                     "seasons": row["seasons"], "minimum_appearances": 0}
            shared_scope = shared.get("scope")
            if (shared.get("release_id") != manifest["release_id"]
                    or shared.get("analytics_version") != manifest["analytics_version"]
                    or not isinstance(shared_scope, dict)
                    or any(shared_scope.get(key) != value for key, value in scope.items())):
                raise StaticAcceptanceError(f"Shared player rankings version or scope binding differs: {name}")
            rankings[name] = shared
    return {"out": out, "manifest": manifest, "seasons": seasons, "data": data,
            "player_rankings": rankings}


def _player_json(snapshot: dict[str, Any], path: Path, document: dict | None = None) -> dict[str, Any]:
    profile = _json(path) if document is None else document
    if snapshot["manifest"]["schema_version"] == SNAPSHOT_SCHEMA_VERSION:
        try:
            return restore_player_rankings(profile, snapshot["player_rankings"][path.name])
        except ValueError as exc:
            raise StaticAcceptanceError(f"{path}: {exc}") from exc
    return profile


def _read_documents(snapshot: dict[str, Any]) -> dict[str, Any]:
    data = snapshot["data"]
    if not data.is_dir():
        raise StaticAcceptanceError(f"Snapshot data directory is missing: {data}")
    overview = _json(data / "overview.json")
    releases = _json(data / "releases.json")
    games_index = _json(data / "games" / "index.json")
    players_index = _json(data / "players" / "index.json")
    return {"overview": overview, "releases": releases,
            "games_index": games_index, "players_index": players_index}


def _record_routes(snapshot: dict[str, Any], docs: dict[str, Any]) -> list[str]:
    manifest, data = snapshot["manifest"], snapshot["data"]
    seasons = snapshot["seasons"]
    game_ids = [row["id"] for row in docs["games_index"].get("items", [])]
    player_ids = [row["id"] for row in docs["players_index"].get("items", [])]
    expected = ["", "games", "players", "leaderboard", "leaderboard/bluff-review", "stats"]
    expected.extend(f"seasons/{quote(season, safe='')}" for season in seasons)
    if "S23" in seasons:
        expected.append("seasons/S23/bluff-review")
    expected.extend(f"games/{quote(game_id, safe='')}" for game_id in game_ids)
    expected.extend(f"players/{quote(player_id, safe='')}" for player_id in player_ids)
    for season in seasons:
        phase_names = ["all"]
        season_row = next(row for row in manifest["seasons"] if row["id"] == season)
        phases = season_row.get("phases", [])
        if "finals_week" in phases:
            phase_names.append("finals_week")
        for phase in phase_names:
            if not (data / "leaderboards" / season / f"{phase}.json").is_file():
                raise StaticAcceptanceError(f"Missing {phase} leaderboard data for {season}")
    missing = [route or "/" for route in expected if _route_file(snapshot["out"], route) is None]
    if missing:
        raise StaticAcceptanceError("Static HTML routes are missing: " + ", ".join(missing[:12]))
    # Route HTML is a reusable shell. Its data is checked below and rendered in
    # the browser, so names and other release values need not be baked into it.
    return ["/" + route if route else "/" for route in expected]


def _media_references(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _media_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _media_references(item)
    elif isinstance(value, str) and "/media/" in value:
        parsed = urlsplit(value)
        path = unquote(parsed.path)
        marker = "/media/"
        position = path.find(marker)
        if position >= 0:
            yield path[position + 1:]


def _snapshot_media_references(snapshot: dict[str, Any]) -> set[str]:
    references: set[str] = set()
    for path in (snapshot["data"]).rglob("*.json"):
        references.update(_media_references(_json(path)))
    for html_file in snapshot["out"].rglob("*.html"):
        source = html_file.read_text(encoding="utf-8")
        for match in re.finditer(r"(?:src|href)=[\"']([^\"']*/media/[^\"']+)", source):
            references.update(_media_references(match.group(1).split("?", 1)[0]))
    return references


def _media_references_for_check(snapshot: dict[str, Any],
                                media_cache: dict[str, Any] | None) -> set[str]:
    if media_cache is None:
        return _snapshot_media_references(snapshot)
    if "references" not in media_cache:
        media_cache["references"] = _snapshot_media_references(snapshot)
    return media_cache["references"]


def _media_sha256(path: Path, reference: str, hashes: dict[str, str]) -> str:
    if reference not in hashes:
        with path.open("rb") as stream:
            hashes[reference] = hashlib.file_digest(stream, "sha256").hexdigest()
    return hashes[reference]


_STATIC_ASSET_EXTENSIONS = {".css", ".js", ".mjs", ".json", ".png", ".jpg", ".jpeg", ".webp",
                           ".svg", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".map", ".webmanifest",
                           ".avif"}


def _check_local_assets(snapshot: dict[str, Any]) -> int:
    out, base = snapshot["out"], snapshot["manifest"]["base_path"]
    resolved_out = out.resolve()
    checked: set[str] = set()
    checked_references: set[tuple[str, str, str]] = set()

    def check_reference(reference: str, origin: Path):
        parsed = urlsplit(reference.strip())
        if parsed.scheme or parsed.netloc or not parsed.path:
            return
        path = unquote(parsed.path)
        if Path(path).suffix.casefold() not in _STATIC_ASSET_EXTENSIONS:
            return
        if path.startswith(base + "/"):
            relative = path[len(base) + 1:]
            reference_key = ("root", "", PurePosixPath(relative).as_posix())
        elif path.startswith("/"):
            raise StaticAcceptanceError(f"Static asset omits the configured base path: {reference}")
        else:
            relative = str(origin.parent.relative_to(out) / Path(path))
            reference_key = ("relative", origin.parent.relative_to(out).as_posix(),
                             PurePosixPath(path).as_posix())
        if reference_key in checked_references:
            return
        target = (out / relative).resolve()
        if not target.is_relative_to(resolved_out) or not target.is_file():
            raise StaticAcceptanceError(f"Static asset reference is missing: {reference}")
        checked_references.add(reference_key)
        checked.add(target.relative_to(resolved_out).as_posix())

    for html_file in out.rglob("*.html"):
        source = html_file.read_text(encoding="utf-8")
        for match in re.finditer(r"(?:src|href)=[\"']([^\"']+)", source):
            check_reference(match.group(1), html_file)
    for css_file in out.rglob("*.css"):
        source = css_file.read_text(encoding="utf-8")
        for match in re.finditer(r"url\(\s*[\"']?([^\"')]+)", source, flags=re.IGNORECASE):
            check_reference(match.group(1), css_file)
    return len(checked)


def _structure_check(snapshot: dict[str, Any], docs: dict[str, Any], *,
                     media_cache: dict[str, Any] | None = None,
                     basic: bool = False) -> dict[str, Any]:
    manifest, data, out = snapshot["manifest"], snapshot["data"], snapshot["out"]
    counts = manifest["counts"]
    games = docs["games_index"].get("items", [])
    players = docs["players_index"].get("items", [])
    if len({item.get("id") for item in games}) != len(games):
        raise StaticAcceptanceError("games/index.json contains duplicate game IDs")
    if len({item.get("id") for item in players}) != len(players):
        raise StaticAcceptanceError("players/index.json contains duplicate player IDs")
    if docs["games_index"].get("total") != len(games):
        raise StaticAcceptanceError("games index total does not match its items")
    if docs["games_index"].get("release_id") != manifest["release_id"]:
        raise StaticAcceptanceError("games index release binding differs from manifest")
    if docs["overview"].get("release", {}).get("id") != manifest["release_id"]:
        raise StaticAcceptanceError("overview release binding differs from manifest")
    active_releases = [item for item in docs["releases"].get("items", []) if item.get("active")]
    if len(active_releases) != 1 or active_releases[0].get("id") != manifest["release_id"]:
        raise StaticAcceptanceError("releases.json must contain exactly the manifest's active release")
    if counts["games"] != len(games) or counts["game_details"] != len(games):
        raise StaticAcceptanceError("Manifest game counts differ from the exported game index")
    if manifest["complete"]:
        if counts["games"] != docs["overview"].get("totals", {}).get("games"):
            raise StaticAcceptanceError("Complete game count differs from overview totals")
        by_season = {row["id"]: row for row in manifest["seasons"]}
        for season in snapshot["seasons"]:
            exported = sum(item.get("season") == season for item in games)
            if exported != by_season[season].get("game_count"):
                raise StaticAcceptanceError(f"Game count differs for {season}")
    elif counts["games"] < 1 or counts["players"] < 1:
        raise StaticAcceptanceError("A partial snapshot must include at least one game and player")
    if counts["players"] != len(players) or docs["players_index"].get("release_id") != manifest["release_id"]:
        raise StaticAcceptanceError("Manifest player count or release binding differs from players index")
    if manifest["partial"]["enabled"]:
        partial = manifest["partial"]
        if (counts["games"] != 1 or counts["players"] != 1
                or games[0].get("id") != partial["game_id"]
                or games[0].get("season") != partial["season"]
                or players[0].get("id") != partial["player_id"]
                or snapshot["seasons"] != [partial["season"]]):
            raise StaticAcceptanceError("Partial data does not match its declared one-game, one-player scope")

    media_root = out / "media"
    media_files = [path for path in media_root.rglob("*") if path.is_file()] if media_root.exists() else []
    if len(media_files) != counts["media_files"]:
        raise StaticAcceptanceError("Manifest media_files count differs from the static media directory")
    json_files = [path for path in data.rglob("*.json") if path.is_file()]
    required_files = [data / "overview.json", data / "releases.json",
                      data / "games" / "index.json", data / "players" / "index.json"]
    if any(not path.is_file() for path in required_files):
        raise StaticAcceptanceError("Required snapshot JSON file is missing")
    actual_player_ranges = list((data / "players").glob("*/*--*.json"))
    # The season summaries live one directory below players/by-season and are not player ranges.
    actual_player_ranges = [path for path in actual_player_ranges if path.parent.name != "by-season"]
    actual_stats_ranges = list((data / "stats").glob("*--*.json")) if (data / "stats").is_dir() else []
    actual_reviews = list((data / "bluff-review").glob("*.json")) if (data / "bluff-review").is_dir() else []
    actual_leaderboards = list((data / "leaderboards").glob("*/*.json")) if (data / "leaderboards").is_dir() else []
    actual_game_details = list((data / "games").glob("*.json")) if (data / "games").is_dir() else []
    actual_game_details = [path for path in actual_game_details if path.name != "index.json"]
    if counts["player_ranges"] != len(actual_player_ranges):
        raise StaticAcceptanceError("Manifest player_ranges count differs from exported player range files")
    if counts["stats_ranges"] != len(actual_stats_ranges):
        raise StaticAcceptanceError("Manifest stats_ranges count differs from exported stats files")
    if counts["leaderboards"] != len(actual_leaderboards):
        raise StaticAcceptanceError("Manifest leaderboards count differs from exported leaderboard files")
    if counts["bluff_reviews"] != len(actual_reviews):
        raise StaticAcceptanceError("Manifest bluff_reviews count differs from exported review files")
    expected_game_detail_names = {f"{item['id']}.json" for item in games}
    if {path.name for path in actual_game_details} != expected_game_detail_names:
        raise StaticAcceptanceError("Game detail files do not exactly cover the exported game index")
    if any(not (data / "players" / "by-season" / f"{season}.json").is_file()
           for season in snapshot["seasons"]):
        raise StaticAcceptanceError("A snapshot season is missing its by-season player index")
    known_ranges = {f"{row['start']}--{row['end']}.json" for row in manifest["ranges"]}
    known_players = set(item["id"] for item in players)
    for profile_path in actual_player_ranges:
        if (profile_path.parent.name not in known_players or profile_path.name not in known_ranges):
            raise StaticAcceptanceError(f"Player range file is outside the manifest scope: {profile_path.relative_to(data)}")
    if manifest["complete"]:
        expected_profiles = {f"{player_id}/{range_name}" for player_id in known_players for range_name in known_ranges}
        actual_profiles = {f"{path.parent.name}/{path.name}" for path in actual_player_ranges}
        if actual_profiles != expected_profiles:
            raise StaticAcceptanceError("Complete player range files do not cover every player and range")
    expected_stats_ranges = [data / "stats" / f"{item['start']}--{item['end']}.json"
                             for item in manifest["ranges"]]
    if any(not path.is_file() for path in expected_stats_ranges):
        raise StaticAcceptanceError("One or more range stats files are missing")
    expected_review_seasons = set(snapshot["seasons"])
    if {path.stem for path in actual_reviews} != expected_review_seasons:
        raise StaticAcceptanceError("Bluff review files do not cover the snapshot seasons")
    expected_leaderboards = {
        f"{season}/{phase}.json"
        for season_row in manifest["seasons"]
        for phase in (["all", "finals_week"] if "finals_week" in season_row.get("phases", []) else ["all"])
        for season in [season_row["id"]]
    }
    if {f"{path.parent.name}/{path.name}" for path in actual_leaderboards} != expected_leaderboards:
        raise StaticAcceptanceError("Leaderboard files do not match supported season phases")
    if manifest["complete"] and counts["player_ranges"] != len(players) * len(manifest["ranges"]):
        raise StaticAcceptanceError("Complete player range coverage is incomplete")

    media_references: set[str] = set()
    player_paths = set(actual_player_ranges)
    for path in json_files:
        document = _json(path)
        release_id = document.get("release_id") if isinstance(document, dict) else None
        if release_id is not None and release_id != manifest["release_id"]:
            raise StaticAcceptanceError(f"Stale release binding in {path.relative_to(out)}")
        if path in player_paths:
            _player_json(snapshot, path, document)
    if not basic:
        media_references = _media_references_for_check(snapshot, media_cache)
        media_hashes = media_cache.setdefault("hashes", {}) if media_cache is not None else {}
        for reference in sorted(media_references):
            relative = Path(reference)
            if relative.is_absolute() or ".." in relative.parts:
                raise StaticAcceptanceError(f"Invalid media reference {reference}")
            path = out / relative
            if not path.is_file():
                raise StaticAcceptanceError(f"Referenced media file is missing: {reference}")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", path.stem):
                raise StaticAcceptanceError(f"Media filename is not content-addressed: {reference}")
            digest = _media_sha256(path, reference, media_hashes)
            if digest.casefold() != path.stem.casefold():
                raise StaticAcceptanceError(f"Media content hash differs from filename: {reference}")
    all_files = [path for path in out.rglob("*") if path.is_file()]
    sizes = {"total_bytes": sum(path.stat().st_size for path in all_files),
             "json_bytes": sum(path.stat().st_size for path in json_files),
             "media_bytes": sum(path.stat().st_size for path in media_files),
             "files": len(all_files), "json_files": len(json_files),
             "media_files": len(media_files), "media_references": None if basic else len(media_references)}
    _check_site_size(sizes["total_bytes"])
    routes = _record_routes(snapshot, docs)
    return {"state": "passed", "files": sizes, "routes_checked": len(routes),
            "media_references_checked": len(media_references),
            "static_assets_checked": _check_local_assets(snapshot),
            "hash_algorithm": None if basic else "sha256",
            "hashes_checked": 0 if basic else len(media_files)}


def _all_api_games(api_url: str, release_id: str, expected_total: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while len(rows) < expected_total:
        result = _get_json(api_url, "/api/v1/games?" + urlencode({"page": page, "page_size": 100}))
        if result.get("release_id") != release_id or result.get("total") != expected_total:
            raise StaticAcceptanceError(f"Games API binding or total changed at page {page}")
        items = result.get("items", [])
        if not items:
            raise StaticAcceptanceError("Games API ended before all rows were read")
        rows.extend(items)
        page += 1
    if len(rows) != expected_total or len({row["id"] for row in rows}) != expected_total:
        raise StaticAcceptanceError("Games API pagination has duplicate or missing IDs")
    return rows


def _query_matches(item: dict[str, Any], filters: dict[str, str]) -> bool:
    if filters.get("season") and item.get("season") != filters["season"]:
        return False
    if filters.get("phase") and item.get("phase") != filters["phase"]:
        return False
    if filters.get("board") and item.get("board", {}).get("code") != filters["board"]:
        return False
    if filters.get("date_from") and item.get("date", "") < filters["date_from"]:
        return False
    if filters.get("date_to") and item.get("date", "") > filters["date_to"]:
        return False
    if filters.get("player") and not any(
            player.get("id") == filters["player"]
            or filters["player"].casefold() in player.get("name", "").casefold()
            for player in item.get("players", [])):
        return False
    if filters.get("q") and filters["q"].casefold() not in item.get("search_text", "").casefold():
        return False
    return True


def _representative_game_queries(games: list[dict[str, Any]]) -> list[dict[str, str]]:
    queries: list[dict[str, str]] = [{}]
    season = next((item.get("season") for item in games if item.get("season")), None)
    if season:
        queries.append({"season": season})
    phase_game = next((item for item in games if item.get("phase") == "finals_week"), None)
    if phase_game:
        queries.append({"season": phase_game["season"], "phase": "finals_week"})
    board_game = next((item for item in games if item.get("board", {}).get("code")), None)
    if board_game:
        queries.append({"board": board_game["board"]["code"]})
    player_game = next((item for item in games if item.get("players")), None)
    if player_game:
        player = player_game["players"][0]
        if player.get("id"):
            queries.append({"player": player["id"]})
        elif player.get("name"):
            queries.append({"player": player["name"]})
    qterm = next((token for item in games for token in str(item.get("search_text", "")).split()
                  if len(token) > 2), None)
    if qterm:
        queries.append({"q": qterm})
    dates = sorted(item["date"] for item in games if item.get("date"))
    if dates:
        queries.append({"date_from": dates[len(dates) // 3], "date_to": dates[-1]})
    # Keep a small but varied set; the page two case below separately verifies pagination.
    unique = []
    for query in queries:
        if query not in unique:
            unique.append(query)
    return unique


def _check_game_queries(api_url: str, release_id: str, games: list[dict[str, Any]]) -> dict[str, Any]:
    checked = []
    for filters in _representative_game_queries(games):
        query = {**filters, "page": "1", "page_size": "24"}
        response = _get_json(api_url, "/api/v1/games?" + urlencode(query))
        if response.get("release_id") != release_id:
            raise StaticAcceptanceError(f"Filtered games release binding differs for {filters}")
        matching = [item for item in games if _query_matches(item, filters)]
        expected_ids = [item["id"] for item in matching[:24]]
        actual_ids = [item["id"] for item in response.get("items", [])]
        if response.get("total") != len(matching) or actual_ids != expected_ids:
            raise StaticAcceptanceError(f"Filtered game IDs, ordering, or total differ for {filters}")
        checked.append({"filters": filters, "total": len(matching), "page": 1})
        if len(matching) > 24:
            query["page"] = "2"
            response = _get_json(api_url, "/api/v1/games?" + urlencode(query))
            expected_ids = [item["id"] for item in matching[24:48]]
            if [item["id"] for item in response.get("items", [])] != expected_ids:
                raise StaticAcceptanceError(f"Games page 2 ordering differs for {filters}")
            checked.append({"filters": filters, "total": len(matching), "page": 2})
    return {"queries": checked, "games_in_index": len(games)}


def _check_partial_game_queries(api_url: str, release_id: str,
                                games: list[dict[str, Any]]) -> dict[str, Any]:
    """Probe supported filters against the API while claiming only exported sample rows."""
    checked = []
    for game in games:
        filters: list[dict[str, str]] = []
        search_term = next((token for token in str(game.get("search_text", "")).split()
                            if token.upper().startswith("BV")), None)
        if search_term:
            filters.append({"q": search_term})
        filters.append({"season": game["season"]})
        if game.get("phase"):
            filters.append({"phase": game["phase"]})
        if game.get("board", {}).get("code"):
            filters.append({"board": game["board"]["code"]})
        if game.get("date"):
            filters.append({"date_from": game["date"], "date_to": game["date"]})
        player = next(iter(game.get("players", [])), None)
        if player and player.get("id"):
            filters.append({"player": player["id"]})
        for filter_set in filters:
            result = _get_json(api_url, "/api/v1/games?" + urlencode(
                {**filter_set, "page": 1, "page_size": 100}))
            if result.get("release_id") != release_id:
                raise StaticAcceptanceError(f"Partial games query binding differs for {filter_set}")
            rows = result.get("items", [])
            if result.get("total", -1) < len(rows):
                raise StaticAcceptanceError(f"Partial games query total is smaller than its page: {filter_set}")
            if filter_set.get("q") == search_term and [row["id"] for row in rows] != [game["id"]]:
                raise StaticAcceptanceError("Unique BVID search does not return the selected partial game")
            checked.append({"filters": filter_set, "source_total": result.get("total"),
                            "sample_game_id": game["id"]})
    return {"scope": "partial_exported_games", "queries": checked, "games_in_index": len(games)}


def _check_player_rankings(stats: dict[str, Any], minimum: int,
                           scope_appearances: dict[str, int] | None = None) -> int:
    boards: list[tuple[str, list[dict[str, Any]], bool]] = []
    boards.extend((key, board, key != "losses")
                  for key, board in stats.get("ranking_boards", {}).items() if isinstance(board, list))
    for rows in stats.get("roles", []):
        boards.append((f"role:{rows.get('role')}", rows.get("ranking_board", []), True))
    for rows in stats.get("boards", []):
        boards.append((f"board:{rows.get('code') or rows.get('name')}", rows.get("ranking_board", []), True))
    checked = 0
    for name, board, descending in boards:
        previous_rank = 0
        previous_value: float | None = None
        for index, row in enumerate(board, 1):
            total_appearances = (scope_appearances or {}).get(row.get("id"), row.get("appearances", 0))
            if total_appearances < minimum:
                raise StaticAcceptanceError("Ranking includes a player below the appearance threshold")
            rank = row.get("rank")
            if not isinstance(rank, int) or rank < 1 or rank > index:
                raise StaticAcceptanceError("Ranking contains an invalid boundary rank")
            if rank < previous_rank:
                raise StaticAcceptanceError("Ranking ranks are not nondecreasing")
            if rank != previous_rank and rank != index:
                raise StaticAcceptanceError("Competition ranks do not advance at the correct boundary")
            value = row.get("value")
            if (previous_value is not None and isinstance(value, (int, float))
                    and ((descending and value > previous_value) or (not descending and value < previous_value))):
                direction = "descending" if descending else "ascending"
                raise StaticAcceptanceError(f"Ranking values are not sorted {direction}: {name}")
            previous_rank, previous_value = rank, value if isinstance(value, (int, float)) else None
            checked += 1
    return checked


def _filtered_rank_rows(rows: list[dict[str, Any]], minimum_appearances: int,
                        minimum_effective_games: int = 0,
                        scope_appearances: dict[str, int] | None = None) -> list[dict[str, Any]]:
    cohort = [row for row in rows
              if (scope_appearances or {}).get(row.get("id"), row.get("appearances", 0)) >= minimum_appearances
              and row.get("effective_game_count", row.get("sample_count", 0)) >= minimum_effective_games]
    group_sizes: dict[int, int] = {}
    for row in cohort:
        group_sizes[row["rank"]] = group_sizes.get(row["rank"], 0) + 1
    result = []
    source_rank = None
    visible_rank = 0
    for index, row in enumerate(cohort, 1):
        if row["rank"] != source_rank:
            source_rank = row["rank"]
            visible_rank = index
        result.append({**row, "rank": visible_rank, "tied": group_sizes[source_rank] > 1})
    return result


def _ranking_summary(rows: list[dict[str, Any]], player_id: str) -> dict[str, Any] | None:
    row = next((item for item in rows if item.get("id") == player_id), None)
    if row is None:
        return None
    return {"rank": row["rank"], "total": len(rows), "tied": row["tied"]}


def _check_threshold_projection(base: dict[str, Any], actual: dict[str, Any],
                                player_id: str, minimum: int,
                                scope_appearances: dict[str, int]) -> None:
    for key, rows in base.get("ranking_boards", {}).items():
        expected_rows = _filtered_rank_rows(rows, minimum, scope_appearances=scope_appearances)
        _require_equal(expected_rows, actual.get("ranking_boards", {}).get(key, []),
                       f"minimum appearance ranking board {key}")
        expected_summary = _ranking_summary(expected_rows, player_id)
        if actual.get("rankings", {}).get(key) != expected_summary:
            raise StaticAcceptanceError(f"Minimum appearance summary rank differs for {key}")
    for field in ("roles", "boards"):
        key_for = (lambda row: row.get("role")) if field == "roles" else (
            lambda row: row.get("code") or row.get("name"))
        base_rows = {key_for(row): row for row in base.get(field, [])}
        actual_rows = {key_for(row): row for row in actual.get(field, [])}
        if base_rows.keys() != actual_rows.keys():
            raise StaticAcceptanceError(f"Minimum appearance threshold changed {field} keys")
        for name, base_row in base_rows.items():
            expected_rows = _filtered_rank_rows(base_row.get("ranking_board", []), minimum,
                                                scope_appearances=scope_appearances)
            actual_row = actual_rows[name]
            _require_equal(expected_rows, actual_row.get("ranking_board", []),
                           f"minimum appearance {field} ranking {name}")
            expected_summary = _ranking_summary(expected_rows, player_id)
            if actual_row.get("ranking") != expected_summary:
                raise StaticAcceptanceError(f"Minimum appearance summary rank differs for {field} {name}")


def _api_check(snapshot: dict[str, Any], docs: dict[str, Any], api_url: str,
               export_index: dict[str, Any] | None = None, *,
               media_cache: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest, data = snapshot["manifest"], snapshot["data"]
    release_id = manifest["release_id"]
    binding = _get_json(api_url, "/api/v1/export-manifest")
    reusable = {"paths": set(), "by_kind": {kind: 0 for kind in _REUSABLE_API_FILE_TYPES}}
    if export_index is not None:
        reusable = _validate_export_index(snapshot, docs, export_index, binding)
    if binding.get("release_id") != release_id or binding.get("release", {}).get("id") != release_id:
        raise StaticAcceptanceError("export-manifest release ID differs from the static manifest")
    if (binding.get("release", {}).get("source_hash") != manifest["source_hash"]
            or binding.get("analytics_version") != manifest["analytics_version"]):
        raise StaticAcceptanceError("export-manifest source or analytics version differs from the snapshot")
    api_seasons = [{"id": row.get("season"), "game_count": row.get("game_count"),
                    "phases": row.get("phases", [])} for row in binding.get("seasons", [])]
    static_seasons = [{"id": row.get("id"), "game_count": row.get("game_count"),
                       "phases": row.get("phases", [])} for row in manifest["seasons"]]
    if manifest["complete"]:
        _require_equal(static_seasons, api_seasons, "manifest seasons")
        _require_equal(manifest["bluff_publications"], binding.get("bluff_publications"),
                       "manifest bluff publication bindings")
    else:
        selected = set(snapshot["seasons"])
        _require_equal(static_seasons, [row for row in api_seasons if row["id"] in selected],
                       "partial manifest seasons")
        _require_equal(manifest["bluff_publications"],
                       [row for row in binding.get("bluff_publications", []) if row["season"] in selected],
                       "partial manifest bluff publication bindings")
    _require_equal(manifest["media_manifest_hashes"], binding.get("media_manifest_hashes"),
                   "manifest media hashes")
    for name, digest in manifest["media_manifest_hashes"].items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise StaticAcceptanceError(f"Invalid media manifest hash: {name}")
    allowed_assets = {item.get("url", "").lstrip("/"): item.get("sha256")
                      for item in binding.get("media_assets", [])}
    media_references = _media_references_for_check(snapshot, media_cache)
    media_hashes = media_cache.setdefault("hashes", {}) if media_cache is not None else {}
    for reference in media_references:
        if reference not in allowed_assets:
            raise StaticAcceptanceError(f"Referenced media is not allowed by export-manifest: /{reference}")
        media_path = snapshot["out"] / Path(reference)
        actual_hash = _media_sha256(media_path, reference, media_hashes)
        if actual_hash.casefold() != str(allowed_assets[reference]).casefold():
            raise StaticAcceptanceError(f"Referenced media hash differs from export-manifest: /{reference}")
    api_releases = _get_json(api_url, "/api/v1/releases")
    _require_equal(docs["releases"], api_releases, "releases.json")
    active_releases = [item for item in api_releases.get("items", []) if item.get("active")]
    if len(active_releases) != 1 or active_releases[0].get("id") != release_id:
        raise StaticAcceptanceError("Source API releases has no unique matching active release")
    overview = _get_json(api_url, "/api/v1/overview")
    if manifest["complete"]:
        _require_equal(docs["overview"], overview, "overview.json")
    else:
        static_overview = docs["overview"]
        for field in ("release", "totals", "boards"):
            _require_equal(static_overview.get(field), overview.get(field), f"partial overview.{field}")
        expected_season_rows = [row for row in overview.get("seasons", [])
                                if row.get("id") in set(snapshot["seasons"])]
        _require_equal(static_overview.get("seasons", []), expected_season_rows, "partial overview.seasons")
    api_games = _all_api_games(api_url, release_id, overview.get("totals", {}).get("games", -1))
    static_games = docs["games_index"].get("items", [])
    if manifest["complete"]:
        _require_equal(static_games, api_games, "games/index.json")
    else:
        exported_ids = {item["id"] for item in static_games}
        # The partial index may contain one representative game; compare that response directly.
        by_id = {item["id"]: item for item in api_games}
        if not exported_ids.issubset(by_id):
            raise StaticAcceptanceError("Partial game index contains an invalid game ID")
        _require_equal(static_games, [by_id[item["id"]] for item in static_games], "partial games/index.json")
        by_id = {item["id"]: item for item in api_games}
        _require_equal(docs["overview"].get("recent_games", []),
                       [by_id[item["id"]] for item in static_games], "partial overview.recent_games")
    if manifest["complete"]:
        query_checks = _check_game_queries(api_url, release_id, static_games)
    else:
        query_checks = _check_partial_game_queries(api_url, release_id, static_games)

    detail_ids = [item["id"] for item in static_games]
    def fetch_detail(game_id: str):
        return game_id, _get_json(api_url, "/api/v1/games/" + quote(game_id, safe=""))
    compared_detail_ids = [game_id for game_id in detail_ids
                           if f"games/{quote(game_id, safe='')}.json" not in reusable["paths"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        api_details = dict(pool.map(fetch_detail, compared_detail_ids))
    for game_id, actual in api_details.items():
        static = _json(data / "games" / f"{quote(game_id, safe='')}.json")
        _require_equal(static, actual, f"game detail {game_id}")
        if static.get("release_id") != release_id:
            raise StaticAcceptanceError(f"Game detail {game_id} is bound to a different release")
    for game_id in detail_ids:
        if f"games/{quote(game_id, safe='')}.json" in reusable["paths"]:
            static = _json(data / "games" / f"{quote(game_id, safe='')}.json")
            if static.get("release_id") != release_id:
                raise StaticAcceptanceError(f"Game detail {game_id} is bound to a different release")

    player_seasons: dict[str, list[dict[str, Any]]] = {}
    player_items_by_id: dict[str, dict[str, Any]] = {}
    for season in snapshot["seasons"]:
        page = 1
        api_items = []
        while True:
            response = _get_json(api_url, "/api/v1/players?" + urlencode(
                {"season": season, "phase": "all", "page": page, "page_size": 100}))
            if response.get("release_id") != release_id:
                raise StaticAcceptanceError(f"Players release binding differs for {season}")
            api_items.extend(response.get("items", []))
            if len(api_items) >= response.get("total", 0):
                break
            page += 1
        player_seasons[season] = api_items
        for player in api_items:
            player_items_by_id.setdefault(player["id"], {"id": player["id"], "name": player["name"]})
        by_season = _json(data / "players" / "by-season" / f"{season}.json")
        if manifest["complete"]:
            _require_equal(by_season.get("items", []), api_items, f"players/by-season/{season}.json")
            expected_total = len(api_items)
        else:
            api_by_id = {item["id"]: item for item in api_items}
            exported_players = by_season.get("items", [])
            if not {item["id"] for item in exported_players}.issubset(api_by_id):
                raise StaticAcceptanceError(f"Partial season player index contains an unknown ID: {season}")
            _require_equal(exported_players, [api_by_id[item["id"]] for item in exported_players],
                           f"partial players/by-season/{season}.json")
            expected_total = len(exported_players)
        if by_season.get("release_id") != release_id or by_season.get("total") != expected_total:
            raise StaticAcceptanceError(f"Season player index binding or total differs for {season}")
    static_players = docs["players_index"].get("items", [])
    if manifest["complete"]:
        if {row["id"]: row["name"] for row in static_players} != {
                row["id"]: row["name"] for row in player_items_by_id.values()}:
            raise StaticAcceptanceError("players/index.json IDs or names differ from seasonal indexes")
    else:
        api_names = {player_id: row["name"] for player_id, row in player_items_by_id.items()}
        if any(item.get("id") not in api_names or api_names[item["id"]] != item.get("name")
               for item in static_players):
            raise StaticAcceptanceError("Partial players/index.json contains an unknown player or name")
        season_ids = set(snapshot["seasons"])
        expected_partial_ids = {item["id"] for season in season_ids
                                 for item in _json(data / "players" / "by-season" / f"{season}.json").get("items", [])}
        if {item["id"] for item in static_players} != expected_partial_ids:
            raise StaticAcceptanceError("Partial players/index does not match by-season selected players")

    range_rows = manifest["ranges"]
    appearances_by_range: dict[str, dict[str, int]] = {}
    for range_row in range_rows:
        start, end = range_row["start"], range_row["end"]
        stats_path = data / "stats" / f"{start}--{end}.json"
        stats_static = _json(stats_path)
        if (stats_static.get("release_id") != release_id
                or stats_static.get("scope", {}).get("season_start") != start
                or stats_static.get("scope", {}).get("season_end") != end
                or stats_static.get("scope", {}).get("seasons") != range_row["seasons"]):
            raise StaticAcceptanceError(f"Stats scope differs for {start}--{end}")
        stats_relative = f"stats/{start}--{end}.json"
        if stats_relative not in reusable["paths"]:
            stats_response = _get_json(api_url, "/api/v1/stats?" + urlencode(
                {"season_start": start, "season_end": end}))
            _require_equal(stats_static, stats_response, stats_relative)
        appearances_by_range[f"{start}--{end}"] = {
            player["id"]: player["appearances"] for player in stats_static.get("players", [])
        }

    player_range_files = [path for path in (data / "players").glob("*/*--*.json")
                          if path.parent.name != "by-season"]
    nonzero_profiles: list[tuple[Path, int]] = []
    for path in player_range_files:
        player = _player_json(snapshot, path)
        if player.get("release_id") != release_id:
            raise StaticAcceptanceError(f"Player range release binding differs: {path.relative_to(data)}")
        if player.get("scope", {}).get("minimum_appearances") != 0:
            raise StaticAcceptanceError(f"Player range is not exported at minimum_appearances=0: {path.name}")
        appearances = player.get("stats", {}).get("appearances", 0)
        if appearances > 0:
            nonzero_profiles.append((path, appearances))

    def compare_profile(path: Path) -> tuple[str, str, int] | None:
        static_player = _player_json(snapshot, path)
        start, end = path.name.removesuffix(".json").split("--", 1)
        relative = path.relative_to(data).as_posix()
        if relative in reusable["paths"]:
            return None
        endpoint = "/api/v1/players/" + quote(static_player["id"], safe="") + "?" + urlencode(
            {"season_start": start, "season_end": end, "minimum_appearances": 0})
        actual = _get_json(api_url, endpoint)
        _require_equal(static_player, actual,
                       f"player {static_player['id']} range {start}--{end}")
        return static_player["id"], f"{start}--{end}", static_player.get("stats", {}).get("appearances", 0)

    with ThreadPoolExecutor(max_workers=4) as pool:
        profile_results = [result for result in pool.map(compare_profile, player_range_files)
                           if result is not None]
    if not nonzero_profiles:
        raise StaticAcceptanceError("No exported player range has a non-zero appearance sample")
    # Exercise non-zero and above-boundary thresholds on one non-zero sample per range.
    samples_by_range: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path, _ in nonzero_profiles:
        start, end = path.name.removesuffix(".json").split("--", 1)
        range_key = f"{start}--{end}"
        if range_key not in samples_by_range:
            samples_by_range[range_key] = (path, _player_json(snapshot, path))
    checked_players = []
    for range_key, (path, static_player) in samples_by_range.items():
        player_id = static_player["id"]
        start, end = range_key.split("--", 1)
        scope_appearances = appearances_by_range[range_key]
        if manifest["schema_version"] == SNAPSHOT_SCHEMA_VERSION:
            base_player = _get_json(api_url, "/api/v1/players/" + quote(player_id, safe="") + "?" + urlencode(
                {"season_start": start, "season_end": end, "minimum_appearances": 0}))
            _require_equal(static_player.get("stats", {}).get("ranking_boards"),
                           base_player.get("stats", {}).get("ranking_boards"),
                           f"shared player rankings {range_key}")
        rank_rows = _check_player_rankings(static_player.get("stats", {}), 0, scope_appearances)
        checked_players.append({"id": player_id, "range": range_key,
                                "appearances": static_player["appearances"], "ranking_rows": rank_rows})
        for threshold in (1, static_player["appearances"] + 1):
            threshold_endpoint = "/api/v1/players/" + quote(player_id, safe="") + "?" + urlencode(
                {"season_start": start, "season_end": end, "minimum_appearances": threshold})
            threshold_player = _get_json(api_url, threshold_endpoint)
            if (threshold_player.get("scope", {}).get("minimum_appearances") != threshold
                    or threshold_player.get("appearances") != static_player["appearances"]
                    or threshold_player.get("stats", {}).get("appearances") != static_player["stats"].get("appearances")):
                raise StaticAcceptanceError(f"Player threshold changed base stats for {player_id} at {threshold}")
            if _canonical(_without_rankings(static_player.get("stats", {}))) != _canonical(
                    _without_rankings(threshold_player.get("stats", {}))):
                raise StaticAcceptanceError(f"Player threshold changed non-ranking statistics for {player_id}")
            _check_player_rankings(threshold_player.get("stats", {}), threshold, scope_appearances)
            _check_threshold_projection(static_player.get("stats", {}),
                                        threshold_player.get("stats", {}), player_id, threshold,
                                        scope_appearances)
            if static_player["appearances"] < threshold:
                if any(value is not None for value in threshold_player.get("stats", {}).get("rankings", {}).values()):
                    raise StaticAcceptanceError(f"Player above-boundary threshold retained a rank for {player_id}")
    expected_range_keys = {f"{row['start']}--{row['end']}" for row in range_rows}
    if manifest["complete"] and set(samples_by_range) != expected_range_keys:
        raise StaticAcceptanceError("No non-zero player sample was API-checked for every season range")

    leaderboards = []
    leaderboards_api_compared = []
    for season_row in manifest["seasons"]:
        season = season_row["id"]
        phases = ["all"] + (["finals_week"] if "finals_week" in season_row.get("phases", []) else [])
        for phase in phases:
            board_path = data / "leaderboards" / season / f"{phase}.json"
            board = _json(board_path)
            board_relative = f"leaderboards/{season}/{phase}.json"
            if board_relative not in reusable["paths"]:
                api_board = _get_json(api_url, "/api/v1/leaderboard?" + urlencode({"season": season, "phase": phase}))
                _require_equal(board, api_board, board_relative)
            if board.get("release_id") != release_id or board.get("season") != season:
                raise StaticAcceptanceError(f"Leaderboard binding differs for {season}/{phase}")
            if phase == "all" and manifest["complete"] and board.get("game_count") != season_row.get("game_count"):
                raise StaticAcceptanceError(f"Full-season leaderboard count differs for {season}")
            leaderboards.append({"season": season, "phase": phase, "games": board.get("game_count"),
                                 "players": len(board.get("items", []))})
            leaderboards_api_compared.append(board_relative not in reusable["paths"])

    reviews = []
    reviews_api_compared = []
    publication_ids = {item["season"]: item for item in manifest["bluff_publications"]}
    for season in snapshot["seasons"]:
        review = _json(data / "bluff-review" / f"{season}.json")
        review_relative = f"bluff-review/{season}.json"
        if review_relative not in reusable["paths"]:
            api_review = _get_json(api_url, "/api/v1/bluff-review?" + urlencode({"season": season, "status": "all"}))
            _require_equal(review, api_review, review_relative)
        if review.get("release_id") != release_id or review.get("season") != season:
            raise StaticAcceptanceError(f"Bluff review binding differs for {season}")
        binding = publication_ids.get(season)
        if binding and (review.get("bluff_publication_id") != binding.get("publication_id")
                        or review.get("bluff_payload_hash") != binding.get("payload_hash")):
            raise StaticAcceptanceError(f"Bluff review publication binding differs for {season}")
        reviews.append({"season": season, "items": len(review.get("items", [])),
                        "games": review.get("summary", {}).get("games")})
        reviews_api_compared.append(review_relative not in reusable["paths"])

    api_file_comparisons = {
        "game_details": len(compared_detail_ids),
        "player_ranges": len(profile_results),
        "stats_ranges": len(range_rows) - reusable["by_kind"]["stats_range"],
        "leaderboards": sum(leaderboards_api_compared),
        "bluff_reviews": sum(reviews_api_compared),
    }
    api_file_comparisons["total"] = sum(api_file_comparisons.values())
    return {"state": "passed", "release_id": release_id,
            "game_filters": query_checks, "game_details_checked": api_file_comparisons["game_details"],
            "game_details_present": len(detail_ids),
            "season_player_indexes_checked": len(player_seasons),
            "game_details_api_compared": api_file_comparisons["game_details"],
            "player_ranges_checked": len(profile_results),
            "player_ranges_api_compared": api_file_comparisons["player_ranges"],
            "player_ranking_samples": checked_players,
            "stats_ranges_checked": api_file_comparisons["stats_ranges"],
            "stats_ranges_present": len(range_rows),
            "stats_ranges_api_compared": api_file_comparisons["stats_ranges"],
            "leaderboards_checked": [row for row, compared in zip(leaderboards, leaderboards_api_compared)
                                      if compared],
            "leaderboards_reused": reusable["by_kind"]["leaderboard"],
            "bluff_reviews_checked": [row for row, compared in zip(reviews, reviews_api_compared)
                                       if compared],
            "bluff_reviews_reused": reusable["by_kind"]["bluff_review"],
            "leaderboards_api_compared": api_file_comparisons["leaderboards"],
            "bluff_reviews_api_compared": api_file_comparisons["bluff_reviews"],
            "api_file_comparisons": api_file_comparisons,
            "input_fingerprint_reused": len(reusable["paths"]),
            "input_fingerprint_reused_by_kind": reusable["by_kind"],
            "export_manifest": {"season_count": len(api_seasons),
                                "media_assets_available": len(allowed_assets),
                                "media_manifests_checked": len(manifest["media_manifest_hashes"]),
                                "bindings_checked": True},
            "release_history_count": len(docs["releases"].get("items", []))}


class _PrefixHandler(SimpleHTTPRequestHandler):
    directory: str
    base_path: str

    def translate_path(self, path: str) -> str:
        route = unquote(urlsplit(path).path)
        prefix = self.base_path
        if route == prefix:
            route = "/"
        elif route.startswith(prefix + "/"):
            route = route[len(prefix):]
        else:
            route = "/__outside_base_path__"
        return super().translate_path(route)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _serve(out: Path, base_path: str):
    class BoundHandler(_PrefixHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(out), **kwargs)
    BoundHandler.base_path = base_path
    handler = BoundHandler
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _record_request_failure(request: Any, failed_requests: list[str],
                            cancelled_document_navigations: list[str]) -> None:
    failure = request.failure or "unknown failure"
    if request.resource_type == "document" and failure == "net::ERR_ABORTED":
        cancelled_document_navigations.append(request.url)
        return
    failed_requests.append(f"{request.url} ({request.resource_type}; {failure})")


def _expected_game_page_ids(games: list[dict[str, Any]], page: int, page_size: int = 24) -> list[str]:
    ordered = sorted(games, key=lambda item: str(item.get("id", "")))
    ordered.sort(key=lambda item: item.get("game_number")
                 if isinstance(item.get("game_number"), (int, float)) else float("-inf"), reverse=True)
    ordered.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
    start = (page - 1) * page_size
    return [str(item["id"]) for item in ordered[start:start + page_size]]


def _browser_page_number(url: Any) -> str | None:
    values = parse_qs(urlsplit(str(url)).query).get("page")
    return values[0] if values else None


def _wait_for_game_ids(page: Any, expected: list[str]) -> None:
    page.wait_for_function(
        "expected => { const ids = Array.from(document.querySelectorAll('tr[data-game-row]')).map(row => {"
        "const link = row.querySelector(\"a[href*='/games/']\"); if (!link) return null;"
        "const path = new URL(link.href).pathname.replace(/\\/+$/, '');"
        "return decodeURIComponent(path.slice(path.lastIndexOf('/') + 1)); });"
        "return JSON.stringify(ids) === JSON.stringify(expected); }",
        arg=expected, timeout=15000)


def _select_player_range_target(snapshot: dict[str, Any], profile_path: Path,
                                profile: dict[str, Any]) -> Path | None:
    if not snapshot["manifest"]["complete"]:
        return None
    player_id = profile["id"]
    current_start, current_end = profile_path.stem.split("--", 1)
    available = set(profile.get("available_seasons") or snapshot["seasons"])
    current_appearances = profile.get("stats", {}).get("appearances", profile.get("appearances", 0))
    candidates: list[tuple[bool, int, Path]] = []
    for index, row in enumerate(snapshot["manifest"]["ranges"]):
        start, end = row["start"], row["end"]
        if (start, end) == (current_start, current_end) or start not in available or end not in available:
            continue
        path = snapshot["data"] / "players" / player_id / f"{start}--{end}.json"
        if not path.is_file():
            continue
        target = _json(path)
        appearances = target.get("stats", {}).get("appearances", target.get("appearances", 0))
        candidates.append((appearances == current_appearances, index, path))
    return min(candidates)[2] if candidates else None


def _affected_browser_scope(export_index: dict[str, Any] | None,
                            previous_export_index: dict[str, Any] | None) -> dict[str, set[str]]:
    """Compare stable content keys; release rebinding alone changes no route scope."""
    affected: dict[str, set[str]] = {"games": set(), "seasons": set(), "players": set()}
    if export_index is None or previous_export_index is None:
        return affected
    current_metadata = export_index.get("metadata", {})
    previous_metadata = previous_export_index.get("metadata", {})
    current_fp = current_metadata.get("content_fingerprints", {})
    previous_fp = previous_metadata.get("content_fingerprints", {})
    current_fp = current_fp if isinstance(current_fp, dict) else {}
    previous_fp = previous_fp if isinstance(previous_fp, dict) else {}
    for key in ("games", "seasons"):
        current = current_fp.get(key)
        previous = previous_fp.get(key)
        if isinstance(current, dict) and isinstance(previous, dict):
            affected[key].update(item for item in set(current) | set(previous)
                                 if current.get(item) != previous.get(item))

    current_publications = {row["season"]: row for row in current_metadata.get("bluff_publications", [])}
    previous_publications = {row["season"]: row for row in previous_metadata.get("bluff_publications", [])}
    affected["seasons"].update(season for season in set(current_publications) | set(previous_publications)
                               if current_publications.get(season) != previous_publications.get(season))
    current_assets = {row["url"]: row.get("sha256") for row in current_metadata.get("media_assets", [])}
    previous_assets = {row["url"]: row.get("sha256") for row in previous_metadata.get("media_assets", [])}
    for url in set(current_assets) | set(previous_assets):
        if current_assets.get(url) == previous_assets.get(url):
            continue
        parts = urlsplit(url).path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "media" and parts[1] in {"player-photos", "bluff-frames"}:
            affected["seasons"].add(parts[2])

    previous_files = previous_export_index.get("files", {})
    for relative, entry in export_index.get("files", {}).items():
        old_entry = previous_files.get(relative, {})
        # SHA-256 changes on every release_id rebind. input_hash describes the
        # actual dependencies and therefore keeps the browser scope local.
        if entry.get("input_hash") == old_entry.get("input_hash"):
            continue
        kind, item_id = _reusable_file_kind(relative)
        parts = PurePosixPath(relative).parts
        if kind == "game_detail" and not (
                isinstance(current_fp.get("games"), dict) and isinstance(previous_fp.get("games"), dict)):
            affected["games"].add(item_id)
        elif kind == "player_range":
            affected["players"].add(item_id)
        elif kind == "stats_range" and not (
                isinstance(current_fp.get("seasons"), dict) and isinstance(previous_fp.get("seasons"), dict)):
            start, end = parts[1][:-5].split("--", 1)
            if start == end:
                affected["seasons"].add(start)
        elif kind in {"leaderboard", "bluff_review"} and not (
                isinstance(current_fp.get("seasons"), dict) and isinstance(previous_fp.get("seasons"), dict)):
            affected["seasons"].add(parts[1] if kind == "leaderboard" else parts[1][:-5])
    return affected


def _browser_routes(snapshot: dict[str, Any], docs: dict[str, Any],
                    export_index: dict[str, Any] | None = None,
                    previous_export_index: dict[str, Any] | None = None) -> tuple[list[str], list[str]]:
    """Visit key entries and changed games, with bounded season/player samples."""
    seasons = snapshot["seasons"]
    games = docs["games_index"].get("items", [])
    players = docs["players_index"].get("items", [])
    representative = ["/", "/games", "/players", "/stats", "/leaderboard", "/leaderboard/bluff-review"]
    if "S23" in seasons:
        representative.append("/seasons/S23/bluff-review")
    affected = _affected_browser_scope(export_index, previous_export_index)
    affected["seasons"].update(game["season"] for game in games if game["id"] in affected["games"])

    if seasons:
        representative.extend([f"/seasons/{quote(seasons[-1], safe='')}",
                               f"/stats?{urlencode({'season_start': seasons[0], 'season_end': seasons[-1]})}"])
    if games:
        representative.append("/games/" + quote(games[0]["id"], safe=""))
    if players and seasons:
        player = next((row for row in players if row["id"] in affected["players"]), players[0])
        representative.append("/players/" + quote(player["id"], safe="") + "?" + urlencode(
            {"season_start": seasons[0], "season_end": seasons[-1]}))

    # Keep one visible evidence sample even when no affected review season is
    # selected. The unfiltered entry may otherwise hide completed evidence.
    photo_sample_selected = False
    frame_sample_selected = False
    for season in reversed(seasons):
        season_players = _json(snapshot["data"] / "players" / "by-season" / f"{season}.json")
        if not photo_sample_selected and any(path.startswith("media/player-photos/")
                                             for path in _media_references(season_players)):
            representative.append("/players?" + urlencode({"season": season}))
            photo_sample_selected = True
        review = _json(snapshot["data"] / "bluff-review" / f"{season}.json")
        if not frame_sample_selected and any(path.startswith("media/bluff-frames/")
                                             for path in _media_references(review)):
            representative.append("/leaderboard/bluff-review?" + urlencode({"season": season, "status": "all"}))
            frame_sample_selected = True
        if photo_sample_selected and frame_sample_selected:
            break

    for season in seasons:
        if season not in affected["seasons"]:
            continue
        encoded = quote(season, safe="")
        representative.extend([
            f"/seasons/{encoded}", "/players?" + urlencode({"season": season}),
            "/stats?" + urlencode({"season_start": season, "season_end": season}),
            "/leaderboard?" + urlencode({"season": season}),
            "/leaderboard/bluff-review?" + urlencode({"season": season, "status": "all"}),
        ])
        if season == "S23":
            representative.append("/seasons/S23/bluff-review")
        season_players = _json(snapshot["data"] / "players" / "by-season" / f"{season}.json").get("items", [])
        player = next((row for row in season_players if row["id"] in affected["players"]),
                      next(iter(season_players), None))
        if player:
            representative.append("/players/" + quote(player["id"], safe="") + "?" + urlencode(
                {"season_start": season, "season_end": season}))
    representative = list(dict.fromkeys(representative))
    changed_games = ["/games/" + quote(game["id"], safe="")
                     for game in games if game["id"] in affected["games"]]
    return list(dict.fromkeys(representative + changed_games)), representative


def _browser_check(snapshot: dict[str, Any], docs: dict[str, Any], api_url: str,
                   channel: str, output: Path | None,
                   export_index: dict[str, Any] | None = None,
                   previous_export_index: dict[str, Any] | None = None, *,
                   media_cache: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise StaticAcceptanceError("Playwright is required for browser acceptance; use --skip-browser-check to skip it explicitly") from error
    routes, representative = _browser_routes(snapshot, docs, export_index, previous_export_index)
    base_path, out = snapshot["manifest"]["base_path"], snapshot["out"]
    server, thread = _serve(out, base_path)
    web_url = f"http://127.0.0.1:{server.server_port}{base_path}"
    errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    cancelled_document_navigations: list[str] = []
    bad_responses: list[str] = []
    blocked_api: list[str] = []
    screenshot_dir = (output.parent / (output.stem + "-screenshots") if output else
                      Path(tempfile.mkdtemp(prefix="static-acceptance-screenshots-")))
    if output and screenshot_dir.resolve().is_relative_to(out.resolve()):
        screenshot_dir = Path(tempfile.mkdtemp(prefix="static-acceptance-screenshots-"))
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_paths: list[str] = []
    loaded_image_paths: set[str] = set()
    expected_references = _media_references_for_check(snapshot, media_cache)
    player_photos_expected = any(reference.startswith("media/player-photos/")
                                 for reference in expected_references)
    bluff_frames_expected = any(reference.startswith("media/bluff-frames/")
                               for reference in expected_references)
    api_parts = urlsplit(api_url)
    try:
        with sync_playwright() as playwright:
            launch = {} if channel == "chromium" else {"channel": channel}
            browser = playwright.chromium.launch(headless=True, **launch)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            try:
                def block_apis(route):
                    url = route.request.url
                    parts = urlsplit(url)
                    if ((parts.scheme, parts.netloc) == (api_parts.scheme, api_parts.netloc)
                            or parts.path.startswith("/api/v1/")):
                        blocked_api.append(url)
                        route.abort()
                    else:
                        route.continue_()

                context.route("**/*", block_apis)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
                page.on("requestfailed", lambda request: _record_request_failure(
                    request, failed_requests, cancelled_document_navigations))

                def collect_response(response):
                    if response.status >= 400 and urlsplit(response.url).path.rstrip("/") != "/favicon.ico":
                        bad_responses.append(f"{response.status} {response.url}")
                page.on("response", collect_response)

                base_test = web_url + "/"
                response = page.goto(base_test, wait_until="networkidle", timeout=45000)
                if response is None or response.status != 200 or page.locator("main").count() == 0:
                    raise StaticAcceptanceError("Static home route did not load through the configured base path")

                def inspect_page(route: str, width: int, capture: bool = False, reload: bool = False):
                    page.set_viewport_size({"width": width, "height": 844 if width < 500 else 1000})
                    response = page.goto(web_url + route, wait_until="networkidle", timeout=45000)
                    if response is None or response.status != 200:
                        raise StaticAcceptanceError(f"Static page returned an error at {route}: {getattr(response, 'status', None)}")
                    if page.locator("main").count() == 0:
                        raise StaticAcceptanceError(f"Static route has no main content: {route}")
                    page.wait_for_selector("main h1", state="visible", timeout=20000)
                    page.wait_for_function(
                        "() => !document.querySelector('main [aria-busy=\"true\"]') && "
                        "!Array.from(document.querySelectorAll('main [role=status]')).some("
                        "element => /^正在/.test(element.textContent?.trim() || ''))",
                        timeout=20000)
                    load_errors = page.locator("main").get_by_role("alert")
                    if load_errors.count():
                        raise StaticAcceptanceError(f"Static route displays a load error: {route}: "
                                                    + "; ".join(load_errors.all_inner_texts()))
                    route_path = unquote(urlsplit(route).path).rstrip("/")
                    if route_path.startswith("/players/"):
                        player_id = route_path.removeprefix("/players/")
                        player = next(row for row in docs["players_index"]["items"] if row["id"] == player_id)
                        page.get_by_role("heading", level=1, name=player["name"], exact=True).wait_for(timeout=20000)
                    elif route_path.startswith("/games/"):
                        game_id = route_path.removeprefix("/games/")
                        game = next(row for row in docs["games_index"]["items"] if row["id"] == game_id)
                        board_name = (game.get("board") or {}).get("name") or "版型未知"
                        page.get_by_role("heading", level=1, name=board_name, exact=True).wait_for(timeout=20000)
                    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                        raise StaticAcceptanceError(f"Horizontal overflow at {width}px: {route}")
                    images = page.locator("main img")
                    selected_images: list[int] = []
                    seen_categories = {
                        "player": any("/media/player-photos/" in path for path in loaded_image_paths),
                        "frame": any("/media/bluff-frames/" in path for path in loaded_image_paths),
                    }
                    for image_index in range(images.count()):
                        path = urlsplit(images.nth(image_index).get_attribute("src") or "").path
                        category = ("player" if "/media/player-photos/" in path else
                                    "frame" if "/media/bluff-frames/" in path else None)
                        if category and not seen_categories[category]:
                            selected_images.append(image_index)
                            seen_categories[category] = True
                    if not selected_images and images.count() and not loaded_image_paths:
                        selected_images.append(0)
                    for image_index in selected_images:
                        image = images.nth(image_index)
                        image.scroll_into_view_if_needed(timeout=10000)
                        image.evaluate("element => { element.loading = 'eager'; }")
                        page.wait_for_function("element => element.complete && element.naturalWidth > 0",
                                               arg=image.element_handle(), timeout=20000)
                        source = image.evaluate("element => element.currentSrc || element.src")
                        loaded_image_paths.add(urlsplit(source).path)
                    _assert_no_maintenance_controls(page, route)
                    if capture:
                        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", route.strip("/") or "home")[:60]
                        target = screenshot_dir / f"{width}-{safe_name}.png"
                        page.screenshot(path=str(target), full_page=False)
                        screenshot_paths.append(str(target))
                    if reload:
                        page.reload(wait_until="networkidle", timeout=45000)
                        if page.locator("main").count() == 0:
                            raise StaticAcceptanceError(f"Static route failed after refresh: {route}")
                        page.wait_for_selector("main h1", state="visible", timeout=20000)

                # File completeness covers every route; browser work stays on
                # key entries and routes affected by this update.
                for index, route in enumerate(routes, 1):
                    inspect_page(route, 1440, capture=route in representative, reload=route in representative)
                    if index % 50 == 0 or index == len(routes):
                        print(f"Static browser desktop: {index}/{len(routes)} routes", flush=True)
                for route in representative:
                    capture = route in {"/", "/games", "/leaderboard/bluff-review"} or route.startswith(
                        "/leaderboard/bluff-review?season=")
                    inspect_page(route, 390, capture=capture)
                print(f"Static browser mobile: {len(representative)} routes", flush=True)

                interaction = _exercise_browser_flows(page, web_url, snapshot, docs)
                page.goto(web_url + "/games", wait_until="networkidle", timeout=45000)
                _filter_games(page, web_url, snapshot, docs)
                page.reload(wait_until="networkidle", timeout=45000)
                if page.locator("main").count() == 0 or page.get_by_role("button", name="检索对局").count() == 0:
                    raise StaticAcceptanceError("Games page did not reload and remain interactive with API blocked")
            finally:
                try:
                    context.unroute_all(behavior="ignoreErrors")
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    failures = []
    if blocked_api:
        failures.append("dynamic API requests: " + ", ".join(blocked_api[:5]))
    if errors:
        failures.append("page errors: " + "; ".join(errors[:8]))
    if bad_responses:
        failures.append("HTTP errors: " + "; ".join(bad_responses[:12]))
    if failed_requests:
        failures.append("failed requests: " + "; ".join(failed_requests[:8]))
    if console_errors:
        failures.append("console errors: " + "; ".join(console_errors[:8]))
    if failures:
        raise StaticAcceptanceError("Browser acceptance failed; " + " | ".join(failures))
    if player_photos_expected and not any("/media/player-photos/" in path for path in loaded_image_paths):
        raise StaticAcceptanceError("Snapshot player photos were not decoded in a browser page")
    if bluff_frames_expected and not any("/media/bluff-frames/" in path for path in loaded_image_paths):
        raise StaticAcceptanceError("Snapshot evidence screenshots were not decoded in a browser page")
    return {"state": "passed", "browser_channel": channel, "base_path": base_path,
            "scope": "key_entries_and_affected_routes", "routes": routes,
            "baseline_compared": previous_export_index is not None,
            "routes_checked": len(routes), "representative_routes_checked": len(representative),
            "viewports": [1440, 390], "api_blocked_during_browser_check": True,
            "api_requests_attempted": len(blocked_api), "screenshots": screenshot_paths,
            "images_decoded": len(loaded_image_paths),
            "player_photos_decoded": player_photos_expected,
            "evidence_screenshots_decoded": bluff_frames_expected,
            "interaction": interaction, "console_errors": 0, "request_errors": 0,
            "cancelled_document_navigations": len(cancelled_document_navigations)}


def _assert_no_maintenance_controls(page, route: str) -> None:
    forbidden = re.compile(r"(保存草稿|导入|导出|维护者|反馈填写|反馈导入|反馈导出)")
    for control in page.locator("main button, main input, main textarea, main select").all():
        text = " ".join(filter(None, [control.get_attribute("aria-label"), control.get_attribute("name"),
                                      control.get_attribute("placeholder"), control.inner_text()]))
        if forbidden.search(text):
            raise StaticAcceptanceError(f"Public static route exposes a maintenance control: {route}: {text}")


def _filter_games(page, web_url: str, snapshot: dict[str, Any], docs: dict[str, Any]) -> list[str]:
    games = docs["games_index"].get("items", [])
    if not games:
        raise StaticAcceptanceError("Games interaction cannot run without a sample game")
    page.goto(web_url + "/games", wait_until="networkidle", timeout=45000)
    season = games[0]["season"]
    page.get_by_label("赛季").select_option(season)
    page.get_by_role("button", name="检索对局").click()
    page.wait_for_url(lambda url: f"season={quote(season)}" in str(url), timeout=10000)
    page.wait_for_load_state("networkidle")
    if f"season={quote(season)}" not in page.url:
        raise StaticAcceptanceError(f"Games season filter did not update the URL: {page.url}")
    ids = []
    for row in page.locator("tr[data-game-row]").all():
        href = row.locator("a[href*='/games/']").first.get_attribute("href") or ""
        ids.append(unquote(urlsplit(href).path.rstrip("/").rsplit("/", 1)[-1]))
    expected = [item["id"] for item in games if item.get("season") == season][:24]
    if ids != expected:
        raise StaticAcceptanceError("Games season filter rendered IDs in a different order")
    page.go_back(wait_until="networkidle")
    page.wait_for_url(lambda url: "season=" not in str(url), timeout=10000)
    page.go_forward(wait_until="networkidle")
    page.wait_for_url(lambda url: f"season={quote(season)}" in str(url), timeout=10000)
    if f"season={quote(season)}" not in page.url:
        raise StaticAcceptanceError("Games filter state was not restored by browser history")
    return ids


def _exercise_games_pagination(page, web_url: str, snapshot: dict[str, Any],
                               docs: dict[str, Any]) -> dict[str, Any]:
    games = docs["games_index"].get("items", [])
    if snapshot["manifest"]["partial"]["enabled"]:
        return {"state": "skipped", "reason": "partial snapshot has one exported game",
                "matching_count": len(games)}

    page.goto(web_url + "/games", wait_until="networkidle", timeout=45000)
    first_page_ids = _expected_game_page_ids(games, 1)
    _wait_for_game_ids(page, first_page_ids)
    if len(games) <= 24:
        if page.get_by_role("navigation", name="结果分页").get_by_role(
                "link", name=re.compile("下一页")).count():
            raise StaticAcceptanceError("Games pagination exposes a next page for at most 24 matches")
        return {"state": "not_applicable", "reason": "full snapshot has at most 24 matching games",
                "matching_count": len(games), "page_one_ids": first_page_ids}

    pagination = page.get_by_role("navigation", name="结果分页")
    next_page = pagination.get_by_role("link", name=re.compile("下一页"))
    if next_page.count() != 1:
        raise StaticAcceptanceError("Games page with more than 24 matches has no next-page link")
    next_page.click()
    page.wait_for_url(lambda url: _browser_page_number(url) == "2", timeout=10000)
    page.wait_for_load_state("networkidle")
    second_page_ids = _expected_game_page_ids(games, 2)
    _wait_for_game_ids(page, second_page_ids)

    page.go_back(wait_until="networkidle")
    page.wait_for_url(lambda url: _browser_page_number(url) in (None, "1"), timeout=10000)
    _wait_for_game_ids(page, first_page_ids)
    return {"state": "passed", "matching_count": len(games), "page_size": 24,
            "page_one_ids": first_page_ids, "page_two_ids": second_page_ids,
            "browser_back_restored_page_one": True}


def _exercise_player_range_switch(page, range_form, profile_path: Path,
                                  profile: dict[str, Any], snapshot: dict[str, Any],
                                  range_start: str, range_end: str,
                                  initial_end: str) -> dict[str, Any]:
    partial = snapshot["manifest"]["partial"]["enabled"]
    single_season = len(snapshot["seasons"]) == 1
    if partial or single_season:
        if len(snapshot["seasons"]) != 1:
            raise StaticAcceptanceError("Single-season player range interaction has an inconsistent scope")
        if initial_end != "latest":
            raise StaticAcceptanceError("Single-season player range should begin with its latest-range selection")
        target_path = profile_path
        target_start, target_end = range_start, range_end
    else:
        target_path = _select_player_range_target(snapshot, profile_path, profile)
        if target_path is None:
            raise StaticAcceptanceError("Complete snapshot has no alternate exported player range to exercise")
        target_start, target_end = target_path.stem.split("--", 1)

    target_profile = _json(target_path)
    expected_appearances = target_profile.get("stats", {}).get(
        "appearances", target_profile.get("appearances", 0))
    expected_label = (target_start if target_start == target_end
                      else f"{target_start} — {target_end}")

    minimum_input = range_form.get_by_label("区间最低出场次数")
    if not minimum_input.is_visible():
        range_form.get_by_role("button", name=re.compile("筛选出场次数")).click()
    minimum_input.fill("0")
    range_form.get_by_label("起始赛季").select_option(target_start)
    range_form.get_by_label("结束赛季").select_option(target_end)

    page_base_path = snapshot["manifest"]["base_path"]
    expected_data_path = (f"{page_base_path}/data/releases/"
                          f"{quote(snapshot['manifest']['snapshot_id'], safe='')}/players/"
                          f"{quote(profile['id'], safe='')}/"
                          f"{quote(target_start, safe='')}--{quote(target_end, safe='')}.json")
    view_button = range_form.get_by_role("button", name=re.compile("查看表现"))
    if single_season:
        view_button.click()
    else:
        with page.expect_response(
                lambda response: urlsplit(response.url).path == expected_data_path,
                timeout=20000) as target_response:
            view_button.click()
        if target_response.value.status != 200:
            raise StaticAcceptanceError(
                f"Player range interaction loaded the wrong status: {target_response.value.status} "
                f"{target_response.value.url}")

    def url_matches_range(url: Any) -> bool:
        query = parse_qs(urlsplit(str(url)).query)
        return (query.get("season_start") == [target_start]
                and query.get("season_end") == [target_end]
                and "minimum_appearances" not in query)

    page.wait_for_url(url_matches_range, timeout=10000)
    page.wait_for_load_state("networkidle")
    page.wait_for_function(
        "expected => { const label = document.querySelector('.profile-range-label')?.textContent?.trim();"
        "const card = Array.from(document.querySelectorAll('.profile-stat-card')).find(item =>"
        "item.querySelector('.metric-copy > span')?.textContent?.trim() === '出场次数');"
        "const count = card?.querySelector('strong')?.textContent?.trim();"
        "const expectedCount = new Intl.NumberFormat('zh-CN').format(expected.appearances);"
        "const loading = Array.from(document.querySelectorAll('[role=status]')).some(item =>"
        "item.textContent?.includes('正在载入选手统计范围'));"
        "return label === expected.label && count === expectedCount && !loading; }",
        arg={"label": expected_label, "appearances": expected_appearances}, timeout=20000)
    if not url_matches_range(page.url):
        raise StaticAcceptanceError("Player range form did not clear the minimum threshold or update the URL")
    if (range_form.get_by_label("起始赛季").input_value() != target_start
            or range_form.get_by_label("结束赛季").input_value() != target_end
            or minimum_input.input_value() != "0"):
        raise StaticAcceptanceError("Player range controls do not show the applied range and cleared threshold")
    visible_appearances = page.locator(".profile-stat-card").filter(
        has=page.get_by_text("出场次数", exact=True)).first.locator("strong").inner_text()
    visible_label = page.locator(".profile-range-label").inner_text()
    if visible_label != expected_label:
        raise StaticAcceptanceError("Player range label differs after applying the selected range")
    if not single_season:
        return {"state": "passed", "from_range": f"{range_start}--{range_end}",
                "to_range": f"{target_start}--{target_end}", "range_changed": True,
                "minimum_appearances_cleared": True,
                "expected_appearances": expected_appearances,
                "visible_appearances": visible_appearances,
                "static_range_response_status": 200}
    return {"state": "single_season_explicit_selection_checked",
            "reason": "snapshot has no alternate exported season range",
            "latest_to_explicit_same_season": True,
            "cross_season_range_change": "not_applicable_single_season",
            "snapshot_complete": snapshot["manifest"]["complete"],
            "selected_range": f"{target_start}--{target_end}",
            "minimum_appearances_cleared": True,
            "expected_appearances": expected_appearances,
            "visible_appearances": visible_appearances,
            "static_range_response_status": None}


def _exercise_browser_flows(page, web_url: str, snapshot: dict[str, Any], docs: dict[str, Any]) -> dict[str, Any]:
    game_ids = _filter_games(page, web_url, snapshot, docs)
    games_pagination = _exercise_games_pagination(page, web_url, snapshot, docs)
    players = docs["players_index"].get("items", [])
    if not players:
        raise StaticAcceptanceError("Player interaction cannot run without a sample player")
    seasons = snapshot["seasons"]
    candidate_profiles = [path for path in (snapshot["data"] / "players").glob("*/*--*.json")
                          if path.parent.name != "by-season"]
    profile_path = None
    profile_ranking: list[dict[str, Any]] = []
    for candidate in candidate_profiles:
        candidate_data = _player_json(snapshot, candidate)
        ranking = candidate_data.get("stats", {}).get("ranking_boards", {}).get("total_win_rate", [])
        max_appearances = max((row.get("appearances", 0) for row in ranking), default=0)
        if (candidate_data.get("appearances", 0) > 0 and ranking
                and max_appearances > candidate_data.get("appearances", 0)):
            profile_path = candidate
            profile_ranking = ranking
            break
    if profile_path is None:
        profile_path = candidate_profiles[0] if candidate_profiles else None
    if profile_path is None:
        raise StaticAcceptanceError("Player range data is missing for browser interactions")
    profile = _player_json(snapshot, profile_path)
    player_id = profile["id"]
    range_start, range_end = profile_path.name.removesuffix(".json").split("--", 1)
    initial_end = "latest" if len(snapshot["seasons"]) == 1 else range_end
    player_route = "/players/" + quote(player_id, safe="") + "?" + urlencode(
        {"season_start": range_start, "season_end": initial_end})
    page.goto(web_url + player_route, wait_until="networkidle", timeout=45000)
    range_form = page.get_by_role("form", name="筛选赛季范围与排名出场次数")
    if range_form.get_by_label("起始赛季").input_value() != range_start:
        raise StaticAcceptanceError("Player page did not retain its start season")
    if range_form.get_by_label("结束赛季").input_value() != initial_end:
        raise StaticAcceptanceError("Player page did not retain its end season")
    minimum = profile.get("appearances", 0) + 1
    range_form.get_by_role("button", name="筛选出场次数").click()
    range_form.get_by_label("区间最低出场次数").fill(str(minimum))
    range_form.get_by_role("button", name="应用筛选").click()
    page.wait_for_url(lambda url: f"minimum_appearances={minimum}" in str(url), timeout=10000)
    page.wait_for_load_state("networkidle")
    if f"minimum_appearances={minimum}" not in page.url:
        raise StaticAcceptanceError("Player appearance threshold did not update the URL")
    status = page.get_by_role("status").all_inner_texts()
    if not any("未达到" in text for text in status):
        raise StaticAcceptanceError("Player above-boundary threshold did not show the excluded state")
    rank_buttons = page.get_by_role("button", name=re.compile("总胜率：查看排行榜"))
    if rank_buttons.count() == 0:
        raise StaticAcceptanceError("Player page has no ranking dialog trigger")
    rank_buttons.first.click()
    dialog = page.get_by_role("dialog")
    if dialog.count() != 1 or not dialog.is_visible():
        raise StaticAcceptanceError("Ranking dialog did not open")
    filters = dialog.get_by_role("button", name="筛选场次")
    if filters.count() != 1:
        raise StaticAcceptanceError("Total-win-rate dialog has no effective-game filter")
    filters.click()
    if dialog.get_by_role("group", name="最低有效场次").count() != 1:
        raise StaticAcceptanceError("Ranking dialog did not expose the effective-game threshold")
    ranking_rows = profile_ranking or profile.get("stats", {}).get("ranking_boards", {}).get("total_win_rate", [])
    expected_appearance_rows = _filtered_rank_rows(ranking_rows, minimum)
    actual_appearance_rows = dialog.get_by_role("table").locator("tbody tr").all()
    if len(actual_appearance_rows) != len(expected_appearance_rows):
        raise StaticAcceptanceError("Ranking dialog did not apply the appearance threshold")
    actual_ranks = [int(row.locator("td").nth(0).inner_text()) for row in actual_appearance_rows]
    if actual_ranks != [row["rank"] for row in expected_appearance_rows]:
        raise StaticAcceptanceError("Appearance threshold did not recalculate visible boundary ranks")
    actual_ids = [unquote(urlsplit(row.locator("a[href*='/players/']").get_attribute("href") or "")
                           .path.rstrip("/").rsplit("/", 1)[-1]) for row in actual_appearance_rows]
    if actual_ids != [row["id"] for row in expected_appearance_rows]:
        raise StaticAcceptanceError("Appearance threshold changed ranking order")
    max_effective = max((row.get("effective_game_count", row.get("sample_count", 0))
                         for row in ranking_rows), default=0)
    nonzero_threshold = 1
    custom_threshold = max_effective + 1
    dialog.get_by_label("自定义最低有效场次").fill(str(nonzero_threshold))
    dialog.get_by_role("button", name="应用").click()
    expected_effective_rows = _filtered_rank_rows(ranking_rows, minimum, nonzero_threshold)
    actual_effective_rows = dialog.get_by_role("table").locator("tbody tr").all()
    if len(actual_effective_rows) != len(expected_effective_rows) or not actual_effective_rows:
        raise StaticAcceptanceError("Non-zero effective-game threshold removed every eligible ranking row")
    effective_ranks = [int(row.locator("td").nth(0).inner_text()) for row in actual_effective_rows]
    if effective_ranks != [row["rank"] for row in expected_effective_rows]:
        raise StaticAcceptanceError("Effective-game threshold did not recalculate visible boundary ranks")
    dialog.get_by_label("自定义最低有效场次").fill(str(custom_threshold))
    dialog.get_by_role("button", name="应用").click()
    if not any("没有符合要求" in text for text in dialog.get_by_role("status").all_inner_texts()):
        raise StaticAcceptanceError("Ranking effective-game boundary did not produce an empty result")
    dialog.get_by_role("button", name="关闭排行榜").click()
    if dialog.is_visible():
        raise StaticAcceptanceError("Ranking dialog did not close")
    player_range_switch = _exercise_player_range_switch(
        page, range_form, profile_path, profile, snapshot, range_start, range_end, initial_end)
    return {"games_filter_ids": game_ids, "games_pagination": games_pagination, "player_id": player_id,
            "player_range": f"{range_start}--{range_end}", "minimum_appearances": minimum,
            "player_range_switch": player_range_switch,
            "ranking_dialog": {"nonzero_effective_games": nonzero_threshold,
                               "empty_boundary": custom_threshold}}


def check(out: Path | str, base_path: str, api_url: str, *, browser_channel: str = "chrome",
          export_index: dict[str, Any] | None = None,
          previous_export_index: dict[str, Any] | None = None,
          skip_browser_check: bool = False,
          output: Path | str | None = None) -> dict[str, Any]:
    """Check structure/API and selected browser routes unless explicitly skipped."""
    started = perf_counter()
    load_started = perf_counter()
    base = _base_path(base_path)
    out_path = Path(out)
    snapshot = _load_snapshot(out_path, base)
    docs = _read_documents(snapshot)
    stage_durations = {"load": round(perf_counter() - load_started, 3)}
    media_cache: dict[str, Any] = {}
    structure_started = perf_counter()
    structure = _structure_check(snapshot, docs, media_cache=media_cache)
    stage_durations["structure"] = round(perf_counter() - structure_started, 3)
    api_started = perf_counter()
    api = _api_check(snapshot, docs, api_url, export_index, media_cache=media_cache)
    stage_durations["api"] = round(perf_counter() - api_started, 3)
    report_path = Path(output) if output is not None else None
    if skip_browser_check:
        browser = {"state": "skipped", "reason": "explicit --skip-browser-check",
                   "scope": "key_entries_and_affected_routes", "routes_checked": 0,
                   "representative_routes_checked": 0, "routes": [], "viewports": []}
        stage_durations["browser"] = 0.0
    else:
        browser_started = perf_counter()
        browser = _browser_check(snapshot, docs, api_url, browser_channel, report_path,
                                 export_index, previous_export_index, media_cache=media_cache)
        stage_durations["browser"] = round(perf_counter() - browser_started, 3)
    manifest = snapshot["manifest"]
    report = {
        "state": "partial" if manifest["partial"]["enabled"] else "passed",
        "check_scope": "full",
        "mode": "partial" if manifest["partial"]["enabled"] else "full",
        "complete": manifest["complete"], "snapshot_id": manifest["snapshot_id"],
        "build_id": manifest["build_id"], "release_id": manifest["release_id"],
        "seasons": snapshot["seasons"], "ranges": manifest["ranges"],
        "partial_scope": manifest["partial"] if manifest["partial"]["enabled"] else None,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(perf_counter() - started, 3),
        "stage_durations_seconds": stage_durations,
        "layers": {"structure": structure, "api": api, "browser": browser},
    }
    print("Acceptance stage seconds: " + json.dumps(stage_durations, ensure_ascii=False), flush=True)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def check_basic(out: Path | str, base_path: str, *,
                output: Path | str | None = None) -> dict[str, Any]:
    """Check local static snapshot structure without source API or browser checks."""
    started = perf_counter()
    load_started = perf_counter()
    base = _base_path(base_path)
    out_path = Path(out)
    snapshot = _load_snapshot(out_path, base)
    docs = _read_documents(snapshot)
    stage_durations = {"load": round(perf_counter() - load_started, 3)}

    structure_started = perf_counter()
    structure = _structure_check(snapshot, docs, media_cache={}, basic=True)
    stage_durations["structure"] = round(perf_counter() - structure_started, 3)
    stage_durations["api"] = 0.0
    stage_durations["browser"] = 0.0

    manifest = snapshot["manifest"]
    report_path = Path(output) if output is not None else None
    report = {
        "state": "basic",
        "check_scope": "basic",
        "mode": "partial" if manifest["partial"]["enabled"] else "full",
        "complete": manifest["complete"], "snapshot_id": manifest["snapshot_id"],
        "build_id": manifest["build_id"], "release_id": manifest["release_id"],
        "seasons": snapshot["seasons"], "ranges": manifest["ranges"],
        "partial_scope": manifest["partial"] if manifest["partial"]["enabled"] else None,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(perf_counter() - started, 3),
        "stage_durations_seconds": stage_durations,
        "layers": {
            "structure": structure,
            "api": {"state": "skipped", "reason": "basic scope does not call the source API"},
            "browser": {"state": "skipped", "reason": "basic scope does not launch a browser",
                        "scope": "none", "routes_checked": 0,
                        "representative_routes_checked": 0, "routes": [], "viewports": []},
        },
    }
    print("Acceptance stage seconds: " + json.dumps(stage_durations, ensure_ascii=False), flush=True)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="Next static export directory")
    parser.add_argument("--base-path", required=True, help="Pages path prefix, such as /langrensha-site")
    parser.add_argument("--api-url", required=True, help="Published source API used for consistency checks")
    parser.add_argument("--output", type=Path, help="Acceptance report path")
    parser.add_argument("--browser-channel", choices=("chrome", "chromium"), default="chrome",
                        help="Installed local browser; CI callers should pass chromium")
    parser.add_argument("--skip-browser-check", action="store_true",
                        help="Skip browser checks only; structure, data, API and version checks still run")
    args = parser.parse_args(argv)
    try:
        report = check(args.out, args.base_path, args.api_url,
                       browser_channel=args.browser_channel, skip_browser_check=args.skip_browser_check,
                       output=args.output)
    except Exception as error:
        failed = {"state": "failed", "mode": "unknown", "complete": False,
                  "error": f"{type(error).__name__}: {error}",
                  "checked_at_utc": datetime.now(timezone.utc).isoformat()}
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(failed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failed, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"state": report["state"], "mode": report["mode"],
                      "complete": report["complete"], "snapshot_id": report["snapshot_id"],
                      "output": str(args.output) if args.output else None,
                      "browser_routes": report["layers"]["browser"]["routes_checked"],
                      "duration_seconds": report["duration_seconds"],
                      "stage_durations_seconds": report.get("stage_durations_seconds", {})},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
