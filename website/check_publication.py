"""Read-only acceptance checks for the active multi-season website release."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote, urlencode
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from season_config import season_codes
from website.api import publisher
from website.api.app import _resolved_snapshot

API = os.environ.get("MASTERS_API_URL", "http://127.0.0.1:8000").rstrip("/")
WEB = os.environ.get("MASTERS_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
PHOTO_MANIFEST = ROOT / "website/api/player_photos.json"
PHOTO_ROOT = ROOT / "website/assets/player-photos"


def get_json(path: str) -> dict:
    with urlopen(API + path, timeout=30) as response:
        return json.load(response)


def counts(games: list[dict]) -> dict[str, int]:
    ballots = [ballot for game in games for ballot in game["voting"]["ballots"]]
    return {"games": len(games), "seats": sum(len(game["seats"]) for game in games),
            "rounds": sum(len(game["rounds"]) for game in games), "ballots": len(ballots),
            "votes": sum(len(ballot.get("votes", [])) for ballot in ballots)}


def load_source(seasons: list[str]) -> tuple[dict[str, dict], dict[str, dict[str, int]], str, str]:
    entries, source_hash, rules_hash = publisher.load_release(publisher.DEFAULT_SOURCE_ROOT, seasons)
    names = {seat["name"] for item in entries for seat in item["dossier"]["seats"]}
    person_ids = {name: str(uuid.uuid5(publisher.PERSON_NAMESPACE, name.strip().casefold())) for name in names}
    games = {}
    by_season = {season: [] for season in seasons}
    for item in entries:
        game = _resolved_snapshot(publisher._public_game(
            item["dossier"], item["voting"], item["endgame"], item["audit"], item["board"], person_ids))
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


def game_details(items: list[dict]) -> dict[str, dict]:
    def fetch(item: dict) -> dict:
        return get_json("/api/v1/games/" + quote(item["id"], safe=""))
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(fetch, items))
    return {row["id"]: row for row in rows}


def projection(game: dict, source: bool = False) -> dict:
    value = {key: field for key, field in game.items() if key not in {"presentation", "analytics_version"}}
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
    overview: dict, items: list[dict], details: dict[str, dict], release_id: str,
    registered: list[str], seasons: list[str], source_games: dict[str, dict],
    source_counts: dict[str, dict[str, int]], source_hash: str, rules_hash: str,
) -> dict:
    totals = overview["totals"]
    if (overview["release"]["id"] != release_id or overview["release"]["game_count"] != len(items)
            or totals["games"] != len(items)
            or totals["ballots"] != sum(item["ballot_count"] for item in items)):
        raise RuntimeError("Overview totals differ from paginated games")
    season_rows = {row["id"]: row for row in overview["seasons"]}
    item_counts = {season: sum(item["season"] == season for item in items) for season in season_rows}
    if item_counts != {season: row["games"] for season, row in season_rows.items()}:
        raise RuntimeError("Overview season counts differ from paginated games")
    api_seasons = sorted(season_rows)
    if set(seasons) == set(registered) and set(api_seasons) != set(registered):
        raise RuntimeError(f"Published seasons {api_seasons} differ from the registry {registered}")
    api_by_season = {season: [details[item["id"]] for item in items if item["season"] == season]
                     for season in api_seasons}
    total_votes = 0
    for game_id, game in details.items():
        if game["release_id"] != release_id:
            raise RuntimeError(f"Game {game_id} uses a different release")
        check_public_fields(game)
        ballots = game["voting"]["ballots"]
        if game["round_count"] != len(game["rounds"]) or game["ballot_count"] != len(ballots):
            raise RuntimeError(f"Game {game_id} has inconsistent round or ballot counts")
        total_votes += sum(len(ballot.get("votes", [])) for ballot in ballots)
    if totals["votes"] != total_votes:
        raise RuntimeError("Overview vote total differs from game details")
    for season in seasons:
        actual = api_by_season.get(season, [])
        expected_ids = {key for key, game in source_games.items() if game["season"] == season}
        actual_ids = {game["id"] for game in actual}
        if (counts(actual) != source_counts[season] or expected_ids != actual_ids
                or season_rows.get(season, {}).get("games", 0) != source_counts[season]["games"]):
            raise RuntimeError(f"{season} source/API games or counts differ")
        for game_id in expected_ids:
            expected = dict(source_games[game_id])
            expected["release_id"] = release_id
            require_match(projection(expected, source=True), projection(details[game_id], source=True), game_id)
    if set(seasons) == set(api_seasons) and (
        overview["release"]["source_hash"] != source_hash
        or publisher._release_id("_".join(seasons), source_hash, rules_hash) != release_id
    ):
        raise RuntimeError("Active release fingerprint differs from the formal source")
    return {
        "release_id": release_id,
        "paginated_games": len(items),
        "details_checked": len(details),
        "source_games_matched": sum(source_counts[season]["games"] for season in seasons),
        "overview_seasons": overview["seasons"],
        "selected_season_counts": {season: counts(api_by_season.get(season, [])) for season in seasons},
        "release_counts": counts(list(details.values())),
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
                or summary["wolf_appearances"] != len(data["items"])):
            raise RuntimeError(f"Bluff review game binding differs for {season}")
        checked[season] = {
            "games": summary["games"], "wolf_appearances": summary["wolf_appearances"],
            "identified_bluffs": summary["identified_bluffs"],
            "inference_version": data.get("inference_version"),
        }
    return checked


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_photos(seasons: list[str], leaderboards: dict[str, dict]) -> dict:
    if not PHOTO_MANIFEST.exists():
        return {"manifest": "absent", "assets_checked": 0, "players_without_photo": {}}
    players = json.loads(PHOTO_MANIFEST.read_text(encoding="utf-8")).get("players", {})
    checked, served, coverage, missing = 0, set(), {}, {}
    for season in seasons:
        records = players.get(season, {})
        rows = leaderboards[season]["items"]
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


def check_baseline(receipt_path: Path, seasons: list[str], details: dict[str, dict]) -> dict:
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
    }


def browser_check(seasons: list[str], details: dict[str, dict], leaderboards: dict[str, dict],
                  channel: str = "chrome", screenshots: Path | None = None) -> dict:
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
    pages, errors = [], []
    photo_pages = {season: 0 for season in seasons}
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
                        if path.startswith("/players?") and f"season={season}" in path:
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
    registered = season_codes(ROOT)
    seasons = publisher.publication_seasons(args.seasons or registered)
    if not set(seasons).issubset(registered):
        raise RuntimeError("Selected seasons must come from scripts.season_config")
    source_games, expected, source_hash, rules_hash = load_source(seasons)
    overview = get_json("/api/v1/overview")
    items, release_id = all_api_games()
    details = game_details(items)
    api = check_release(
        overview, items, details, release_id, registered, seasons,
        source_games, expected, source_hash, rules_hash,
    )
    leaderboards = {}
    for season in seasons:
        board = get_json("/api/v1/leaderboard?" + urlencode({"season": season}))
        if board["release_id"] != release_id or board["season"] != season or board["game_count"] != expected[season]["games"]:
            raise RuntimeError(f"Leaderboard season binding differs for {season}")
        leaderboards[season] = board

    api["stats"] = check_stats(seasons, api["overview_seasons"], release_id)
    api["bluff_bindings"] = check_bluffs(seasons, expected, release_id)
    api["photos"] = check_photos(seasons, leaderboards)
    api["leaderboards"] = {season: {"games": board["game_count"], "players": len(board["items"])}
                           for season, board in leaderboards.items()}
    baseline = None
    if args.baseline:
        path = args.baseline if args.baseline.is_absolute() else ROOT / args.baseline
        baseline = check_baseline(path, seasons, details)
    browser = {"skipped": True} if args.api_only else browser_check(
        api["overview_seasons"] and [row["id"] for row in api["overview_seasons"]] or [],
        details, leaderboards, channel=args.browser_channel, screenshots=args.screenshots,
    )
    return {
        "state": "passed", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "registered_seasons": registered, "selected_seasons": seasons,
        "source": {"source_hash": source_hash, "rules_hash": rules_hash,
                   "totals": counts(list(source_games.values())), "per_season": expected},
        "api": api, "baseline": baseline, "browser": browser,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="+", help="registered seasons; defaults to the full registry")
    parser.add_argument("--baseline", type=Path, help="backup receipt for earlier release snapshots")
    parser.add_argument("--output", type=Path, default=ROOT / "website/artifacts/publication-acceptance.json")
    parser.add_argument("--api-only", action="store_true", help="skip browser checks")
    parser.add_argument("--browser-channel", choices=("chrome", "chromium"), default="chrome")
    parser.add_argument("--screenshots", type=Path, help="public rendered pages only; no traces or source dumps")
    args = parser.parse_args(argv)
    try:
        report = run(args)
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as error:
        print(json.dumps({"state": "failed", "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"state": report["state"], "release_id": report["api"]["release_id"],
                      "output": str(output), "games": report["api"]["paginated_games"],
                      "source_games_matched": report["api"]["source_games_matched"],
                      "browser_pages": report["browser"].get("page_count", 0)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
