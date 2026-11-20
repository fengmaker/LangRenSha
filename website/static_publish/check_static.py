"""Check the generated static tree and a small set of representative routes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import re
import sys
from threading import Thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen


if __package__:
    from .snapshot_files import SNAPSHOT_SCHEMA_VERSION, document_path, object_path
else:
    from snapshot_files import SNAPSHOT_SCHEMA_VERSION, document_path, object_path


class StaticAcceptanceError(RuntimeError):
    """A static build is missing required data or representative pages."""


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StaticAcceptanceError(f"Cannot read JSON {path}: {error}") from error


def _base_path(value: str) -> str:
    if value == "/":
        return ""
    if value and (not value.startswith("/") or value.endswith("/") or "\\" in value or "//" in value
                  or any(part in {".", ".."} for part in value.split("/")[1:])):
        raise StaticAcceptanceError("base_path must be empty or a slash-prefixed path without dot segments")
    return value


def _route_file(root: Path, route: str) -> Path:
    parts = [part for part in route.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise StaticAcceptanceError(f"Unsafe static route: {route}")
    return root.joinpath(*parts, "index.html")


class _PrefixHandler(SimpleHTTPRequestHandler):
    directory: str
    base_path: str

    def translate_path(self, path: str) -> str:
        route = unquote(urlsplit(path).path)
        prefix = self.base_path
        if route == prefix:
            route = "/"
        elif prefix and route.startswith(prefix + "/"):
            route = route[len(prefix):]
        elif prefix:
            route = "/__outside_base_path__"
        return super().translate_path(route)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _serve(out: Path, base_path: str):
    class BoundHandler(_PrefixHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(out), **kwargs)

    BoundHandler.base_path = _base_path(base_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), BoundHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _read_response(url: str) -> bytes:
    try:
        with urlopen(url, timeout=5) as response:
            if response.status != 200:
                raise StaticAcceptanceError(f"Static route returned HTTP {response.status}: {url}")
            return response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise StaticAcceptanceError(f"Static route is unavailable: {url}: {error}") from error


def check(out: Path | str, base_path: str = "", *, output: Path | str | None = None) -> dict[str, Any]:
    """Validate required snapshot files and fetch the main and representative detail routes."""
    root = Path(out).resolve()
    base = _base_path(base_path)
    if not root.is_dir():
        raise StaticAcceptanceError(f"Static output directory does not exist: {root}")

    data_root = root / "data"
    manifest = _json(data_root / "manifest.json")
    if (manifest.get("schema_version") not in (2, SNAPSHOT_SCHEMA_VERSION) or not manifest.get("complete")
            or not re.fullmatch(r"snapshot-[a-f0-9]{64}", str(manifest.get("snapshot_id", "")))
            or manifest.get("base_path") != base):
        raise StaticAcceptanceError("Static manifest schema, snapshot, completeness, or base path is invalid")

    release = data_root / "releases" / manifest["snapshot_id"]
    overview = _json(release / "overview.json")
    games = _json(release / "games" / "index.json")
    players = _json(release / "players" / "index.json")
    season_rows = manifest.get("seasons")
    ranges = manifest.get("ranges")
    counts = manifest.get("counts")
    if not isinstance(season_rows, list) or not season_rows or not isinstance(ranges, list) or not ranges:
        raise StaticAcceptanceError("Static manifest has no seasons or ranges")
    if not isinstance(counts, dict) or games.get("total") != counts.get("games"):
        raise StaticAcceptanceError("Static game count differs from the manifest")
    if overview.get("totals", {}).get("games") != counts["games"]:
        raise StaticAcceptanceError("Overview game total differs from the manifest")
    game_items = games.get("items")
    player_items = players.get("items")
    if (not isinstance(game_items, list) or len(game_items) != counts["games"]
            or not isinstance(player_items, list) or len(player_items) != counts.get("players")):
        raise StaticAcceptanceError("Static indexes do not match the manifest counts")

    sample_game = next((item for item in game_items if isinstance(item.get("id"), str)), None)
    sample_player = next((item for item in player_items if isinstance(item.get("id"), str)), None)
    sample_season = season_rows[-1]["id"] if isinstance(season_rows[-1], dict) else None
    if not sample_game or not sample_player or not sample_season:
        raise StaticAcceptanceError("Static indexes contain no representative game, player, or season")
    if manifest["schema_version"] == SNAPSHOT_SCHEMA_VERSION:
        documents = manifest.get("document_hashes")
        expected = {f"games/{row['id']}.json" for row in game_items}
        expected.update(f"players/by-season/{row['id']}.json" for row in season_rows)
        if not isinstance(documents, dict) or documents.keys() != expected:
            raise StaticAcceptanceError("Content-addressed documents do not match the game and season indexes")
        for digest in documents.values():
            try:
                path = object_path(data_root, digest)
                content = path.read_bytes()
            except (ValueError, OSError) as error:
                raise StaticAcceptanceError(f"Cannot read content-addressed document {digest}: {error}") from error
            if hashlib.sha256(content).hexdigest() != digest:
                raise StaticAcceptanceError(f"Content-addressed document hash differs from its filename: {path}")
        _json(document_path(data_root, manifest, f"players/by-season/{sample_season}.json"))
    game_detail = document_path(data_root, manifest, f"games/{sample_game['id']}.json")
    _json(game_detail)
    profile = release / "players" / sample_player["id"] / f"{sample_season}--{sample_season}.json"
    if not profile.is_file():
        # For a player who did not appear that season, any indexed range is valid.
        profile = release / "players" / sample_player["id"] / f"{ranges[-1]['start']}--{ranges[-1]['end']}.json"
    _json(profile)
    _json(release / "stats" / f"{ranges[-1]['start']}--{ranges[-1]['end']}.json")
    _json(release / "leaderboards" / sample_season / "all.json")
    _json(release / "releases.json")

    media_root = root / "media"
    media_files = [path for path in media_root.rglob("*") if path.is_file()] if media_root.is_dir() else []
    if len(media_files) != counts.get("media_files"):
        raise StaticAcceptanceError("Static media count differs from the manifest")

    routes = ["", "games", "players", "stats", "leaderboard",
              f"games/{sample_game['id']}", f"players/{sample_player['id']}",
              f"seasons/{sample_season}"]
    for route in routes:
        page = _route_file(root, route)
        if not page.is_file():
            raise StaticAcceptanceError(f"Static route page is missing: {page}")

    server, thread = _serve(root, base)
    try:
        origin = f"http://127.0.0.1:{server.server_address[1]}{base}"
        checked = []
        for route in routes:
            url = origin + (f"/{route}/" if route else "/")
            body = _read_response(url)
            if b"<!DOCTYPE html>" not in body[:256] and b"<html" not in body[:256]:
                raise StaticAcceptanceError(f"Static route did not return an HTML document: {url}")
            checked.append(route or "/")
        _read_response(origin + "/data/manifest.json")
        if manifest["schema_version"] == SNAPSHOT_SCHEMA_VERSION:
            _read_response(origin + "/" + game_detail.relative_to(root).as_posix())
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    report = {
        "state": "passed", "snapshot_id": manifest["snapshot_id"],
        "games": counts["games"], "players": counts["players"],
        "media_files": counts.get("media_files", 0), "routes_checked": checked,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if output is not None:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def check_basic(out: Path | str, base_path: str = "", *, output: Path | str | None = None) -> dict[str, Any]:
    """Compatibility name for the local structural and representative-page check."""
    return check(out, base_path, output=output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="Next static export directory")
    parser.add_argument("--base-path", default="", help="Pages path prefix, such as /langrensha-site")
    parser.add_argument("--output", type=Path, help="Optional validation summary path")
    args = parser.parse_args(argv)
    try:
        report = check(args.out, args.base_path, output=args.output)
    except Exception as error:
        print(f"静态网站检查失败：{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
