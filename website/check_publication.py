"""Read-only acceptance checks for the active multi-season website release."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from threading import Lock
import time
from urllib.parse import quote, urlencode
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from season_config import season_codes
from website.api.analytics import compute_player_stats
from website.api import publisher
from website.api.app import _resolved_snapshot
from scripts.game_timeline import build_game_timeline

API = os.environ.get("MASTERS_API_URL", "http://127.0.0.1:8000").rstrip("/")
WEB = os.environ.get("MASTERS_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
PHOTO_MANIFEST = ROOT / "website/api/player_photos.json"
PHOTO_ROOT = ROOT / "website/assets/player-photos"
_REQUEST_COUNT = 0
_REQUEST_LOCK = Lock()


def _note_request() -> None:
    global _REQUEST_COUNT
    with _REQUEST_LOCK:
        _REQUEST_COUNT += 1


def get_json(path: str) -> dict:
    _note_request()
    with urlopen(API + path, timeout=30) as response:
        return json.load(response)


def counts(games: list[dict]) -> dict[str, int]:
    ballots = [ballot for game in games for ballot in game["voting"]["ballots"]]
    return {"games": len(games), "seats": sum(len(game["seats"]) for game in games),
            "rounds": sum(len(game["rounds"]) for game in games), "ballots": len(ballots),
            "votes": sum(len(ballot.get("votes", [])) for ballot in ballots)}


def load_source(seasons: list[str], bvids_by_season: dict[str, list[str]] | None = None
                ) -> tuple[dict[str, dict], dict[str, dict[str, int]], str, str]:
    if bvids_by_season is None:
        entries, source_hash, rules_hash = publisher.load_release(publisher.DEFAULT_SOURCE_ROOT, seasons)
    else:
        entries, source_hashes, rule_hashes = [], [], {}
        for season in seasons:
            for bvid in bvids_by_season.get(season, []):
                sample, sample_hash, rules_hash = publisher.load_release(
                    publisher.DEFAULT_SOURCE_ROOT, [season], sample=bvid,
                )
                entries.extend(sample)
                source_hashes.append(sample_hash)
                rule_hashes[season] = rules_hash
        source_hash = hashlib.sha256("\n".join(sorted(source_hashes)).encode("utf-8")).hexdigest()
        rules_hash = hashlib.sha256(json.dumps(rule_hashes, sort_keys=True).encode("utf-8")).hexdigest()
    names = {seat["name"] for item in entries for seat in item["dossier"]["seats"]}
    person_ids = {name: str(uuid.uuid5(publisher.PERSON_NAMESPACE, name.strip().casefold())) for name in names}
    games = {}
    by_season = {season: [] for season in seasons}
    for item in entries:
        game = _resolved_snapshot(publisher._public_game(
            item["dossier"], item["voting"], item["endgame"], item["audit"], item["board"], person_ids,
            source_voting=item.get("source_voting"), derivations=item.get("derivations")))
        if game["id"] in games:
            raise RuntimeError(f"Formal source contains duplicate game ID {game['id']}")
        games[game["id"]] = game
        by_season[game["season"]].append(game)
    return games, {season: counts(rows) for season, rows in by_season.items()}, source_hash, rules_hash


def all_api_games() -> tuple[list[dict], str]:
    items, release_id, total, page = [], None, None, 1
    while total is None or len(items) < total:
        result = get_json("/api/v1/games?" + urlencode({"page": page, "page_size": 100}))
        if release_id is None:
            release_id, total = result["release_id"], result["total"]
        elif result["release_id"] != release_id or result["total"] != total:
            raise RuntimeError(f"Pagination changed on games page {page}")
        items.extend(result["items"])
        if not result["items"] and len(items) < total:
            raise RuntimeError("Games API ended before all pages were read")
        page += 1
    if len(items) != total or len({item["id"] for item in items}) != total:
        raise RuntimeError("Games API total or IDs are inconsistent")
    return items, release_id


def item_bvid(item: dict) -> str | None:
    match = re.search(r"BV[0-9A-Za-z]+", str(item.get("id", "")), re.IGNORECASE)
    return match.group(0) if match else None


def select_bvid_items(items: list[dict], bvids: list[str], seasons: list[str] | None = None
                      ) -> list[dict]:
    selected = []
    for bvid in bvids:
        matches = [item for item in items if (item_bvid(item) or "").casefold() == bvid.casefold()]
        if not matches:
            raise RuntimeError(f"Requested BVID {bvid} is absent from the active release")
        if len(matches) != 1:
            raise RuntimeError(f"Requested BVID {bvid} does not identify exactly one active game")
        item = matches[0]
        if seasons is not None and item["season"] not in seasons:
            raise RuntimeError(f"Requested BVID {bvid} is outside the selected seasons")
        selected.append(item)
    if len({item["id"] for item in selected}) != len(selected):
        raise RuntimeError("Requested BVIDs resolve to duplicate active games")
    return selected


def affected_player_source_bvids(items: list[dict], target_items: list[dict]) -> dict[str, list[str]]:
    affected_by_season = {}
    for item in target_items:
        affected_by_season.setdefault(item["season"], set()).update(
            player["id"] for player in item["players"]
        )
    related = {item["id"]: item for item in items if item["season"] in affected_by_season
               and any(player["id"] in affected_by_season[item["season"]] for player in item["players"])}
    related.update({item["id"]: item for item in target_items})
    bvids = {}
    for item in related.values():
        bvid = item_bvid(item)
        if bvid is None:
            raise RuntimeError(f"Cannot derive a BVID for affected player source game {item['id']}")
        bvids.setdefault(item["season"], set()).add(bvid)
    return {season: sorted(values) for season, values in bvids.items()}


def game_details(items: list[dict]) -> dict[str, dict]:
    def fetch(item: dict) -> dict:
        return get_json("/api/v1/games/" + quote(item["id"], safe=""))
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(fetch, items))
    return {row["id"]: row for row in rows}


def projection(game: dict, source: bool = False) -> dict:
    # Publication bindings stay in the stored snapshot; GameDetail intentionally
    # omits them from the public API. Their integrity is checked by bluff publish.
    value = {key: field for key, field in game.items() if key not in {
        "presentation", "timeline", "analytics_version", "bluff_evidence_sources", "bluff_source_binding",
    }}
    if source:
        value["players"] = [{k: v for k, v in player.items() if k != "id"} for player in value["players"]]
        value["seats"] = [{k: v for k, v in seat.items() if k != "person_id"} for seat in value["seats"]]
    return value


def require_match(expected: dict, actual: dict, label: str) -> None:
    changed = [key for key in sorted(set(expected) | set(actual)) if expected.get(key) != actual.get(key)]
    if changed:
        raise RuntimeError(f"{label} differs in fields: {', '.join(changed[:12])}")


def check_public_fields(game: dict) -> None:
    encoded = json.dumps(game, ensure_ascii=False).casefold()
    if any(marker in encoded for marker in (
        "source_path", "data/extractions/", "data\\extractions\\", ".secrets/", ".secrets\\",
        ROOT.as_posix().casefold(), str(ROOT).casefold(),
    )):
        raise RuntimeError(f"Game {game['id']} exposes a private source path")


def check_release(
    overview: dict, all_items: list[dict], detail_items: list[dict], details: dict[str, dict], release_id: str,
    registered: list[str], seasons: list[str], source_games: dict[str, dict],
    source_counts: dict[str, dict[str, int]], source_hash: str, rules_hash: str,
    *, full_mode: bool, requested_ids: set[str] | None = None,
) -> dict:
    totals = overview["totals"]
    if (overview["release"]["id"] != release_id or overview["release"]["game_count"] != len(all_items)
            or totals["games"] != len(all_items)
            or totals["ballots"] != sum(item["ballot_count"] for item in all_items)):
        raise RuntimeError("Overview totals differ from paginated games")
    season_rows = {row["id"]: row for row in overview["seasons"]}
    if len(season_rows) != len(overview["seasons"]):
        raise RuntimeError("Overview contains duplicate seasons")
    item_counts = {season: sum(item["season"] == season for item in all_items) for season in season_rows}
    if item_counts != {season: row["games"] for season, row in season_rows.items()}:
        raise RuntimeError("Overview season counts differ from paginated games")
    api_seasons = sorted(season_rows)
    if set(api_seasons) != set(registered):
        raise RuntimeError(f"Published seasons {api_seasons} differ from the registry {registered}")
    api_by_season = {season: [details[item["id"]] for item in detail_items if item["season"] == season]
                     for season in seasons}
    for item in all_items:
        player_ids = [player["id"] for player in item["players"]]
        seats = [player["seat"] for player in item["players"]]
        if len(player_ids) != len(set(player_ids)) or len(seats) != len(set(seats)):
            raise RuntimeError(f"Game summary {item['id']} has duplicate players or seats")
        if item["season"] not in registered:
            raise RuntimeError(f"Game summary {item['id']} uses an unregistered season")
    total_votes = 0
    for game_id, game in details.items():
        if game["release_id"] != release_id:
            raise RuntimeError(f"Game {game_id} uses a different release")
        check_public_fields(game)
        ballots = game["voting"]["ballots"]
        if game["round_count"] != len(game["rounds"]) or game["ballot_count"] != len(ballots):
            raise RuntimeError(f"Game {game_id} has inconsistent round or ballot counts")
        total_votes += sum(len(ballot.get("votes", [])) for ballot in ballots)
    summary_keys = ("id", "season", "date", "phase", "game_number", "board", "winner", "players",
                    "ballot_count", "round_count")
    for item in detail_items:
        actual_summary = {key: details[item["id"]].get(key) for key in summary_keys}
        require_match({key: item.get(key) for key in summary_keys}, actual_summary,
                      f"game summary {item['id']}")
    if full_mode and totals["votes"] != total_votes:
        raise RuntimeError("Overview vote total differs from game details")
    detail_ids = set(details)
    source_detail_games = (source_games if requested_ids is None else
                           {game_id: source_games[game_id] for game_id in requested_ids if game_id in source_games})
    expected_detail_ids = requested_ids if requested_ids is not None else set(source_games)
    if detail_ids != expected_detail_ids:
        raise RuntimeError("Fetched detail IDs differ from the selected acceptance scope")
    if set(source_detail_games) != expected_detail_ids:
        raise RuntimeError("Formal source is missing a game in the selected acceptance scope")
    for season in seasons:
        actual = api_by_season.get(season, [])
        expected_ids = {key for key, game in source_detail_games.items() if game["season"] == season}
        actual_ids = {game["id"] for game in actual}
        if expected_ids != actual_ids:
            raise RuntimeError(f"{season} source/API game IDs differ in the selected acceptance scope")
        if requested_ids is None and (
            counts(actual) != source_counts[season]
            or season_rows.get(season, {}).get("games", 0) != source_counts[season]["games"]
        ):
            raise RuntimeError(f"{season} source/API games or counts differ")
        for game_id in expected_ids:
            expected = dict(source_games[game_id])
            expected["release_id"] = release_id
            require_match(projection(expected, source=True), projection(details[game_id], source=True), game_id)
            require_match(build_game_timeline(expected), details[game_id]["timeline"], f"{game_id} timeline")
    if full_mode and (
        overview["release"]["source_hash"] != source_hash
        or publisher._release_id("_".join(seasons), source_hash, rules_hash) != release_id
    ):
        raise RuntimeError("Active release fingerprint differs from the formal source")
    return {
        "release_id": release_id,
        "paginated_games": len(all_items),
        "details_checked": len(details),
        "source_games_matched": len(source_detail_games),
        "overview_seasons": overview["seasons"],
        "selected_season_counts": {season: season_rows[season]["games"] for season in seasons},
        "accepted_scope_counts": counts(list(details.values())),
        "overview_totals": overview["totals"],
    }


def check_stats(seasons: list[str], season_rows: list[dict], release_id: str) -> dict:
    available = [row["id"] for row in season_rows]
    counts_by_season = {row["id"]: row["games"] for row in season_rows}
    singles = {}
    for season in seasons:
        stats = get_json("/api/v1/stats?" + urlencode({"season": season}))
        if (stats["release_id"] != release_id or stats["game_count"] != counts_by_season.get(season, 0)
                or stats["scope"]["seasons"] != ([season] if counts_by_season.get(season, 0) else [])
                or stats["available_seasons"] != available):
            raise RuntimeError(f"Stats filter differs for {season}")
        singles[season] = stats["game_count"]
    span = None
    if available:
        start, end = available[0], available[-1]
        stats = get_json("/api/v1/stats?" + urlencode({"season_start": start, "season_end": end}))
        if (stats["release_id"] != release_id or stats["scope"]["seasons"] != available
                or stats["game_count"] != sum(counts_by_season.values())):
            raise RuntimeError("Cross-season stats total differs")
        span = {"start": start, "end": end, "games": stats["game_count"]}
    return {"single_season_games": singles, "range": span}


def check_bluffs(seasons: list[str], source_counts: dict[str, dict[str, int]], release_id: str) -> dict:
    checked = {}
    for season in seasons:
        data = get_json("/api/v1/bluff-review?" + urlencode({"season": season, "status": "all"}))
        summary = data["summary"]
        if (data["release_id"] != release_id or data["season"] != season
                or summary["games"] != source_counts[season]["games"]
                or summary["wolf_appearances"] + summary.get("manual_included_appearances", 0)
                != len(data["items"])):
            raise RuntimeError(f"Bluff review game binding differs for {season}")
        checked[season] = {
            "games": summary["games"], "wolf_appearances": summary["wolf_appearances"],
            "identified_bluffs": summary["identified_bluffs"],
            "inference_version": data.get("inference_version"),
        }
    return checked


def check_affected_players(items: list[dict], details: dict[str, dict],
                           source_games: dict[str, dict], available_seasons: list[str],
                           release_id: str) -> tuple[dict, list[tuple[str, str]]]:
    affected = sorted({(player["id"], game["season"])
                       for game in details.values() for player in game["players"]})
    checked = {}
    stat_keys = (
        "appearances", "wins", "losses", "pending_games", "points", "points_complete",
        "total_win_rate", "werewolf_win_rate", "good_win_rate", "sheriff_registration_rate",
        "seer_follow_rate", "sheriff_seer_vote_rate", "wolf_vote_rate", "exile_abstentions",
        "werewolf_appearances", "werewolf_draw_rate", "werewolf_self_explosion_rate",
        "werewolf_sheriff_registration_rate", "roles", "boards", "ledger",
    )
    for player_id, season in affected:
        expected_games = [game for game in items if game["season"] == season
                          and any(player["id"] == player_id for player in game["players"])]
        endpoint = "/api/v1/players/" + quote(player_id, safe="") + "?" + urlencode({
            "season_start": season, "season_end": season,
        })
        actual = get_json(endpoint)
        expected_ids = {game["id"] for game in expected_games}
        actual_ids = {game["id"] for game in actual["games"]}
        if (actual["release_id"] != release_id or actual["scope"]["seasons"] != [season]
                or actual["available_seasons"] != available_seasons
                or actual["appearances"] != len(expected_games)
                or actual["stats"]["appearances"] != len(expected_games)
                or actual_ids != expected_ids or len(actual["games"]) != len(actual_ids)):
            raise RuntimeError(f"Player stats binding differs for {player_id} in {season}")
        source_player_games = []
        for summary in expected_games:
            source = source_games.get(summary["id"])
            if source is None:
                raise RuntimeError(f"Formal source is missing affected player game {summary['id']}")
            summary_player = next(player for player in summary["players"] if player["id"] == player_id)
            source_players = [player for player in source["players"] if player["seat"] == summary_player["seat"]]
            source_seats = [seat for seat in source["seats"] if seat["seat"] == summary_player["seat"]]
            if len(source_players) != 1 or len(source_seats) != 1:
                raise RuntimeError(f"Formal source has an ambiguous player seat in {summary['id']}")
            if (source_players[0].get('name') != summary_player['name']
                    or source_seats[0].get('name') != summary_player['name']
                    or actual['name'] != summary_player['name']):
                raise RuntimeError(f"Formal source player identity differs in {summary['id']}")
            source_player_games.append({
                **source,
                "players": [{**player, "id": player_id} if player["seat"] == summary_player["seat"] else player
                            for player in source["players"]],
                "seats": [{**seat, "person_id": player_id}
                          if seat["seat"] == summary_player["seat"] else seat for seat in source["seats"]],
            })
        expected_stats = compute_player_stats(
            player_id, source_player_games, season=season, seasons=[season], name=actual["name"],
        )
        expected_core = {key: expected_stats[key] for key in stat_keys}
        actual_core = {key: actual["stats"].get(key) for key in stat_keys}
        for role in expected_core["roles"] + actual_core["roles"]:
            role.pop("ranking", None)
            role.pop("ranking_board", None)
        for board in expected_core["boards"] + actual_core["boards"]:
            board.pop("ranking", None)
            board.pop("ranking_board", None)
        season_game_count = sum(game["season"] == season for game in items)
        attendance = actual["stats"]["attendance"]
        if (actual_core != expected_core or actual["scope"]["games"] != season_game_count
                or actual["stats"]["scope_games"] != season_game_count
                or attendance["numerator"] != len(expected_games)
                or attendance["denominator"] != season_game_count
                or attendance["rate"] != (len(expected_games) / season_game_count if season_game_count else None)):
            raise RuntimeError(f"Player stats differ from formal source for {player_id} in {season}")
        checked[f"{season}:{player_id}"] = {
            "name": actual["name"], "appearances": actual["appearances"],
            "games_checked": len(actual["games"]),
        }
    return checked, affected


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_photos(seasons: list[str], leaderboards: dict[str, dict],
                 player_names: set[str] | None = None) -> dict:
    if not PHOTO_MANIFEST.exists():
        return {"manifest": "absent", "assets_checked": 0, "players_without_photo": {}}
    players = json.loads(PHOTO_MANIFEST.read_text(encoding="utf-8")).get("players", {})
    checked, served, coverage, missing = 0, set(), {}, {}
    for season in seasons:
        records = players.get(season, {})
        rows = leaderboards[season]["items"]
        if player_names is not None:
            records = {name: record for name, record in records.items() if name in player_names}
            rows = [player for player in rows if player["name"] in player_names]
        for record in records.values():
            season_part, filename = record["asset"].split("/")
            path = (PHOTO_ROOT / season_part / filename).resolve()
            if season_part != season or not path.is_relative_to(PHOTO_ROOT.resolve()) or not path.is_file():
                raise RuntimeError(f"Missing or invalid photo asset in {season} manifest")
            digest = sha256_file(path)
            if Path(filename).stem != digest:
                raise RuntimeError(f"Photo hash mismatch in {season} manifest")
            checked += 1
            asset = f"{season}/{filename}"
            if asset not in served:
                _note_request()
                with urlopen(API + f"/api/v1/photos/{quote(season)}/{quote(filename)}", timeout=30) as response:
                    body = response.read()
                    if (not response.headers.get("Content-Type", "").startswith("image/")
                            or hashlib.sha256(body).hexdigest() != digest):
                        raise RuntimeError(f"Photo API differs for {season}/{filename}")
                served.add(asset)
        present = 0
        for player in rows:
            record, photo = records.get(player["name"]), player.get("photo")
            if record and photo and photo.get("season") == season and photo.get("url") == f"/media/player-photos/{record['asset']}":
                present += 1
            elif record or photo:
                raise RuntimeError(f"Leaderboard photo differs from {season} manifest")
        coverage[season], missing[season] = present, len(rows) - present
    return {
        "manifest": "checked", "entries_checked": checked, "api_assets_checked": len(served),
        "leaderboard_photos": coverage, "players_without_photo": missing,
    }


def check_baseline(receipt_path: Path, seasons: list[str], details: dict[str, dict],
                   game_ids: set[str] | None = None) -> dict:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    release_id = receipt["active_release"]["release_id"]
    backup = Path(receipt["backup"])
    if not backup.is_absolute():
        backup = ROOT / backup
    if backup.stat().st_size != receipt["bytes"] or sha256_file(backup) != receipt["sha256"]:
        raise RuntimeError("Baseline backup differs from its receipt")
    conn = publisher._connect()
    try:
        conn.rollback()
        conn.execute("BEGIN READ ONLY")
        if not conn.execute("SELECT id FROM releases WHERE id=%s", (release_id,)).fetchone():
            raise RuntimeError("Baseline release is unavailable in the read-only database")
        rows = conn.execute("SELECT id,season,snapshot FROM games WHERE release_id=%s ORDER BY season,id",
                            (release_id,)).fetchall()
    finally:
        conn.rollback()
        conn.close()
    compared = {}
    for row in rows:
        if row["season"] not in seasons:
            continue
        if game_ids is not None and row["id"] not in game_ids:
            continue
        current = details.get(row["id"])
        if current is None:
            raise RuntimeError(f"Current release is missing baseline game {row['id']}")
        before = projection(_resolved_snapshot(row["snapshot"]))
        after = projection(current)
        before.pop("release_id", None)
        after.pop("release_id", None)
        require_match(before, after, f"baseline {row['id']}")
        compared[row["season"]] = compared.get(row["season"], 0) + 1
    return {
        "receipt": receipt_path.name, "release_id": release_id,
        "backup_hash_verified": True, "compared_games": sum(compared.values()),
        "compared_seasons": compared,
        "target_games_not_in_baseline": sorted(game_ids - {row["id"] for row in rows}) if game_ids else [],
    }


def browser_check(seasons: list[str], details: dict[str, dict], leaderboards: dict[str, dict],
                  channel: str = "chrome", screenshots: Path | None = None,
                  player_pages: list[tuple[str, str]] | None = None) -> dict:
    from playwright.sync_api import sync_playwright
    routes = {"/": None}
    for season in seasons:
        query = urlencode({"season": season})
        routes[f"/seasons/{quote(season)}"] = None
        routes[f"/games?{query}"] = None
        routes[f"/players?{query}"] = None
        routes[f"/leaderboard?{query}"] = None
        routes[f"/leaderboard/bluff-review?{urlencode({'season': season, 'status': 'all'})}"] = None
        routes[f"/stats?{query}"] = (season, season)
        game = next((item for item in details.values() if item["season"] == season), None)
        if game:
            routes["/games/" + quote(game["id"], safe="")] = None
        players = leaderboards.get(season, {}).get("items", [])
        if players:
            player = players[0]
            span = urlencode({"season_start": season, "season_end": season})
            routes[f"/players/{quote(player['id'], safe='')}?{span}"] = None
    if seasons:
        span = urlencode({"season_start": seasons[0], "season_end": seasons[-1]})
        routes[f"/stats?{span}"] = (seasons[0], seasons[-1])
    for player_id, season in player_pages or []:
        span = urlencode({"season_start": season, "season_end": season})
        routes[f"/players/{quote(player_id, safe='')}?{span}"] = None
    pages, errors = [], []
    photo_pages = {season: 0 for season in seasons if any(
        player.get("photo") for player in leaderboards.get(season, {}).get("items", []))}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**({} if channel == "chromium" else {"channel": channel}), headless=True)
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
        try:
            page = browser.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            for width, height in ((1440, 1000), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                for path, span in routes.items():
                    response = page.goto(WEB + path, wait_until="networkidle", timeout=45000)
                    if response.status != 200 or page.locator("main").count() == 0:
                        raise RuntimeError(f"Browser page failed at width {width}: {path}")
                    if "暂时无法" in page.locator("main").inner_text():
                        raise RuntimeError(f"Page shows an unavailable state: {path}")
                    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                        raise RuntimeError(f"Horizontal overflow at width {width}: {path}")
                    for season in seasons:
                        if path == f"/leaderboard?season={season}" and season in leaderboards:
                            board = leaderboards[season]
                            text = page.locator("main").inner_text()
                            if (season not in page.locator("h1").inner_text()
                                    or not board["items"] or board["items"][0]["name"] not in text
                                    or f'{board["game_count"]} 局' not in text):
                                raise RuntimeError(f"Leaderboard does not render real {season} data")
                    # Force lazy images to load, then check decoded pixels, not just HTTP status.
                    images = page.locator("main img")
                    for index in range(images.count()):
                        img = images.nth(index)
                        img.scroll_into_view_if_needed(timeout=10000)
                        img.evaluate("img => img.loading = 'eager'")
                        page.wait_for_function("img => img.complete && img.naturalWidth > 0",
                                               arg=img.element_handle(), timeout=15000)
                    for season in seasons:
                        if season in photo_pages and path.startswith("/players?") and f"season={season}" in path:
                            if images.count() == 0:
                                raise RuntimeError(f"No player photos rendered for {season}")
                            photo_pages[season] += 1
                    page.evaluate("window.scrollTo(0, 0)")
                    if screenshots:
                        page.screenshot(path=str(screenshots / f"{width}-{len(pages):03d}.png"), full_page=False)
                    if span is not None:
                        start = page.locator('select[name="season_start"]').input_value()
                        end = page.locator('select[name="season_end"]').input_value()
                        if (start, end) != span:
                            raise RuntimeError(f"Stats range was not retained: {path}")
                    pages.append({"width": width, "path": path})
        except Exception:
            if screenshots:
                try:
                    page.screenshot(path=str(screenshots / "failure.png"), full_page=False)
                except Exception:
                    pass  # Preserve the original failure even if the browser crashed.
            raise
        finally:
            browser.close()
    if errors:
        raise RuntimeError("Browser page error: " + "; ".join(errors[:8]))
    if any(count != 2 for count in photo_pages.values()):
        raise RuntimeError("Both viewport sizes must render photos for every season")
    return {"widths": [1440, 390], "page_count": len(pages), "pages": pages,
            "photo_pages": photo_pages}


def run(args: argparse.Namespace) -> dict:
    global _REQUEST_COUNT
    with _REQUEST_LOCK:
        _REQUEST_COUNT = 0
    started = time.perf_counter()
    timings = {}
    registered = season_codes(ROOT)
    explicit_seasons = publisher.publication_seasons(args.seasons) if args.seasons else None
    if explicit_seasons is not None and not set(explicit_seasons).issubset(registered):
        raise RuntimeError("Selected seasons must come from scripts.season_config")

    step_started = time.perf_counter()
    overview = get_json("/api/v1/overview")
    all_items, release_id = all_api_games()
    timings["api_index_seconds"] = round(time.perf_counter() - step_started, 3)
    if args.bvid:
        requested_items = select_bvid_items(all_items, args.bvid)
        bvid_seasons = publisher.publication_seasons(sorted({item["season"] for item in requested_items}))
        if explicit_seasons is not None:
            select_bvid_items(all_items, args.bvid, explicit_seasons)
        seasons = bvid_seasons
        selected_items = requested_items
        selected_bvids = [item_bvid(item) for item in selected_items]
        bvids_by_season = affected_player_source_bvids(all_items, selected_items)
        requested_ids = {item["id"] for item in selected_items}
    else:
        seasons = explicit_seasons or publisher.publication_seasons(registered)
        selected_items = [item for item in all_items if item["season"] in seasons]
        selected_bvids = []
        bvids_by_season = None
        requested_ids = None
    full_mode = not args.bvid and set(seasons) == set(registered)

    step_started = time.perf_counter()
    source_games, expected, source_hash, rules_hash = load_source(seasons, bvids_by_season)
    timings["source_load_seconds"] = round(time.perf_counter() - step_started, 3)

    step_started = time.perf_counter()
    details = game_details(selected_items)
    timings["detail_fetch_seconds"] = round(time.perf_counter() - step_started, 3)

    step_started = time.perf_counter()
    api = check_release(
        overview, all_items, selected_items, details, release_id, registered, seasons,
        source_games, expected, source_hash, rules_hash,
        full_mode=full_mode, requested_ids=requested_ids,
    )
    available_seasons = [row["id"] for row in api["overview_seasons"]]
    if full_mode:
        affected_players, player_pages = {}, []
    else:
        affected_players, player_pages = check_affected_players(
            all_items, details, source_games, available_seasons, release_id,
        )
    leaderboards = {}
    for season in seasons:
        board = get_json("/api/v1/leaderboard?" + urlencode({"season": season}))
        api_season_count = next(row["games"] for row in api["overview_seasons"] if row["id"] == season)
        if (board["release_id"] != release_id or board["season"] != season
                or board["game_count"] != api_season_count):
            raise RuntimeError(f"Leaderboard season binding differs for {season}")
        leaderboards[season] = board

    api["stats"] = check_stats(seasons, api["overview_seasons"], release_id)
    api["bluff_bindings"] = check_bluffs(
        seasons,
        {season: {"games": next(row["games"] for row in api["overview_seasons"] if row["id"] == season)}
         for season in seasons},
        release_id,
    )
    affected_names = {item["name"] for game in details.values() for item in game["players"]}
    api["affected_players"] = affected_players
    api["photos"] = check_photos(seasons, leaderboards, affected_names if args.bvid else None)
    api["leaderboards"] = {season: {"games": board["game_count"], "players": len(board["items"])}
                           for season, board in leaderboards.items()}
    api["accepted_games"] = len(details)
    api["requested_detail_ids"] = sorted(details)
    timings["api_acceptance_seconds"] = round(time.perf_counter() - step_started, 3)
    baseline = None
    if args.baseline:
        step_started = time.perf_counter()
        path = args.baseline if args.baseline.is_absolute() else ROOT / args.baseline
        baseline = check_baseline(path, seasons, details, requested_ids)
        timings["baseline_seconds"] = round(time.perf_counter() - step_started, 3)
    else:
        timings["baseline_seconds"] = 0.0
    step_started = time.perf_counter()
    browser = {"skipped": True} if args.api_only else browser_check(
        seasons, details, leaderboards, channel=args.browser_channel, screenshots=args.screenshots,
        player_pages=player_pages,
    )
    timings["browser_seconds"] = round(time.perf_counter() - step_started, 3)
    timings["total_seconds"] = round(time.perf_counter() - started, 3)
    with _REQUEST_LOCK:
        request_count = _REQUEST_COUNT
    return {
        "state": "passed", "mode": "full" if full_mode else "partial",
        "complete_release_accepted": full_mode,
        "acceptance_scope": {
            "mode": "full" if full_mode else "partial",
            "complete_release": full_mode,
            "accepted_games": len(details),
            "release_vote_total_checked": full_mode,
            "full_source_fingerprint_checked": full_mode,
        },
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "registered_seasons": registered, "selected_seasons": seasons,
        "source": {"source_hash": source_hash, "rules_hash": rules_hash,
                   "scope": "target_and_affected_player_games" if args.bvid else "selected_seasons",
                   "games_loaded": len(source_games), "selected_bvids": selected_bvids,
                   "related_player_games": max(0, len(source_games) - len(details)),
                   "source_bvids_loaded": (sorted(bvid for values in bvids_by_season.values()
                                                   for bvid in values) if bvids_by_season else []),
                   "totals": counts(list(source_games.values())), "per_season": expected},
        "timing_seconds": timings,
        "requests": {"checker_api_http": request_count,
                     "paginated_game_summaries": len(all_items),
                     "detail_requests": len(details), "accepted_games": len(details),
                     "affected_player_stats": len(affected_players)},
        "api": api, "baseline": baseline, "browser": browser,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="+", help="registered seasons; defaults to the full registry")
    parser.add_argument("--bvid", nargs="+", help="BVIDs whose changed games should receive detail checks")
    parser.add_argument("--baseline", type=Path, help="backup receipt for earlier release snapshots")
    parser.add_argument("--output", type=Path, help="Defaults to separate full/partial acceptance reports")
    parser.add_argument("--api-only", action="store_true", help="skip browser checks")
    parser.add_argument("--browser-channel", choices=("chrome", "chromium"), default="chrome")
    parser.add_argument("--screenshots", type=Path, help="public rendered pages only; no traces or source dumps")
    args = parser.parse_args(argv)
    try:
        report = run(args)
        if args.output is None:
            filename = 'publication-acceptance.json' if report['mode'] == 'full' else 'publication-acceptance-partial.json'
            args.output = ROOT / 'website/artifacts' / filename
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as error:
        print(json.dumps({"state": "failed", "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"state": report["state"], "release_id": report["api"]["release_id"],
                      "mode": report["mode"],
                      "output": str(output), "games": report["api"]["paginated_games"],
                      "accepted_games": report["requests"]["accepted_games"],
                      "detail_requests": report["requests"]["detail_requests"],
                      "elapsed_seconds": report["timing_seconds"]["total_seconds"],
                      "source_games_matched": report["api"]["source_games_matched"],
                      "browser_pages": report["browser"].get("page_count", 0)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
