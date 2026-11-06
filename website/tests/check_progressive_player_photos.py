"""Browser acceptance for progressive player photos in a static export."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

from PIL import Image
from playwright.async_api import async_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from website.static_publish.check_static import _serve


DEFAULT_SITE_ROOT = REPO_ROOT / "tmp" / "pages-preview" / "langrensha-site"
DEFAULT_REPORT = REPO_ROOT / "tmp" / "diagnostics" / "check_progressive_player_photos.json"
SEASON = "S23"
PLAYER_NAME = "JY"
PROFILE_SELECTOR = ".profile-photo-frame img"
LIST_SELECTOR = ".player-card-photo img"
VIEWPORT = {"width": 390, "height": 844}


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _public_path(path: str, base_path: str) -> str:
    if not path.startswith("/"):
        raise ValueError(f"Expected an absolute asset path, got {path!r}")
    if not base_path or path == base_path or path.startswith(base_path + "/"):
        return path
    return base_path + path


def _asset_file(site_root: Path, asset_url: str, base_path: str) -> Path:
    route_path = urlsplit(asset_url).path
    if base_path and (route_path == base_path or route_path.startswith(base_path + "/")):
        route_path = route_path[len(base_path):] or "/"
    asset = (site_root / route_path.lstrip("/")).resolve()
    if not asset.is_relative_to(site_root.resolve()):
        raise ValueError(f"Asset path escapes the static export: {asset_url}")
    return asset


def _player_artifacts(site_root: Path) -> dict:
    manifest = _read_json(site_root / "data" / "manifest.json")
    snapshot_id = manifest["snapshot_id"]
    base_path = manifest.get("base_path", "")
    release_dir = site_root / "data" / "releases" / snapshot_id
    season_players = _read_json(release_dir / "players" / "by-season" / f"{SEASON}.json")
    player = next((row for row in season_players["items"] if row.get("name", "").casefold() == PLAYER_NAME.casefold()), None)
    if not player or not player.get("photo"):
        raise ValueError(f"Could not find {PLAYER_NAME} with a photo in {SEASON} player data")

    profile_path = release_dir / "players" / player["id"] / f"{SEASON}--{SEASON}.json"
    profile = _read_json(profile_path)
    list_photo = player["photo"]
    profile_photo = profile.get("photo") or {}
    original_url = list_photo.get("url")
    thumbnail_url = manifest.get("player_photo_thumbnails", {}).get(original_url)
    if not original_url or not thumbnail_url:
        raise ValueError("The static player photo must have a thumbnail in the manifest")
    if profile_photo.get("url") != original_url:
        raise ValueError("The selected player's list and profile photo URLs do not match")

    original_file = _asset_file(site_root, original_url, base_path)
    thumbnail_file = _asset_file(site_root, thumbnail_url, base_path)
    for photo_file in (original_file, thumbnail_file):
        if not photo_file.is_file():
            raise ValueError(f"Static player photo asset is missing: {photo_file}")
    with Image.open(original_file) as original_image:
        original_size = list(original_image.size)

    return {
        "manifest": manifest,
        "release_dir": release_dir,
        "player": player,
        "original_url": original_url,
        "thumbnail_url": thumbnail_url,
        "original_size": original_size,
        "profile_route": f"/players/{quote(player['id'], safe='')}/?{urlencode({'season': SEASON})}",
        "list_route": f"/players/?{urlencode({'season': SEASON, 'q': PLAYER_NAME})}",
    }


async def _open_page_with_original_route(browser, page_url: str, original_path: str, *, abort_original: bool = False,
                                         capture_priority: bool = False) -> dict:
    context = await browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
    page = await context.new_page()
    route_started = asyncio.Event()
    route_aborted = asyncio.Event()
    release_route = asyncio.Event()
    original_requests: list[str] = []
    priorities: list[dict] = []

    async def handle_route(route):
        if urlsplit(route.request.url).path == original_path:
            original_requests.append(route.request.url)
            route_started.set()
            if abort_original:
                await route.abort()
                route_aborted.set()
            else:
                await release_route.wait()
                await route.continue_()
            return
        await route.continue_()

    await context.route("**/*", handle_route)
    cdp = None
    if capture_priority:
        cdp = await context.new_cdp_session(page)
        await cdp.send("Network.enable")
        await cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})

        def record_request(event):
            request = event.get("request", {})
            if urlsplit(request.get("url", "")).path == original_path:
                priorities.append({
                    "event": "requestWillBeSent",
                    "initialPriority": request.get("initialPriority"),
                    "isLinkPreload": request.get("isLinkPreload"),
                })

        def record_priority_change(event):
            priorities.append({"event": "resourceChangedPriority", "priority": event.get("newPriority")})

        cdp.on("Network.requestWillBeSent", record_request)
        cdp.on("Network.resourceChangedPriority", record_priority_change)

    await page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
    await asyncio.wait_for(route_started.wait(), timeout=25)
    return {
        "context": context,
        "page": page,
        "release_route": release_route,
        "route_aborted": route_aborted,
        "original_requests": original_requests,
        "priorities": priorities,
        "cdp": cdp,
    }


async def _wait_for_photo(page, selector: str, expected_url: str, expected_size: list[int] | None = None) -> dict:
    await page.wait_for_selector(selector, state="visible", timeout=25000)
    args = {"selector": selector, "url": expected_url, "size": expected_size}
    await page.wait_for_function(
        """({selector, url, size}) => {
          const img = document.querySelector(selector);
          if (!img || img.currentSrc !== url || !img.complete || img.naturalWidth === 0) return false;
          if (size && (img.naturalWidth !== size[0] || img.naturalHeight !== size[1])) return false;
          const rect = img.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0 && getComputedStyle(img).visibility !== 'hidden';
        }""",
        arg=args,
        timeout=25000,
    )
    return await page.locator(selector).evaluate(
        "img => ({currentSrc: img.currentSrc, complete: img.complete, naturalWidth: img.naturalWidth, "
        "naturalHeight: img.naturalHeight, visible: img.getBoundingClientRect().width > 0})")


async def _assert_profile_preloads(page, original_absolute: str, thumbnail_absolute: str) -> dict:
    links = await page.evaluate(
        """() => Array.from(document.querySelectorAll('link[rel="preload"][as="image"]')).map(link => ({
          href: link.href,
          fetchPriority: (link.fetchPriority || link.getAttribute('fetchpriority') || 'auto').toLowerCase()
        }))"""
    )
    original = next((link for link in links if link["href"] == original_absolute), None)
    thumbnail = next((link for link in links if link["href"] == thumbnail_absolute), None)
    if not original or original["fetchPriority"] != "high":
        raise AssertionError(f"Profile original photo does not have a high-priority preload: {links}")
    if not thumbnail:
        raise AssertionError(f"Profile thumbnail preload is missing: {links}")
    return {"links": links, "original_priority": original["fetchPriority"]}


async def _assert_low_priority(priority_events: list[dict]) -> dict:
    initial = next((event.get("initialPriority") for event in priority_events
                    if event.get("event") == "requestWillBeSent" and event.get("initialPriority")), None)
    if not initial or str(initial).lower() != "low":
        raise AssertionError(f"CDP did not report Low initial priority for the list original: {priority_events}")
    return {"initial_priority": initial, "events": priority_events}


async def _run_checks(site_root: Path, report_path: Path) -> dict:
    artifacts = _player_artifacts(site_root)
    manifest = artifacts["manifest"]
    base_path = manifest.get("base_path", "")
    base_path = base_path.rstrip("/")
    original_path = urlsplit(artifacts["original_url"]).path
    thumbnail_path = urlsplit(artifacts["thumbnail_url"]).path
    original_public_path = _public_path(original_path, base_path)
    thumbnail_public_path = _public_path(thumbnail_path, base_path)
    screenshot_dir = report_path.parent / "check_progressive_player_photos"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "state": "running",
        "site_root": str(site_root),
        "player": {"id": artifacts["player"]["id"], "name": artifacts["player"]["name"], "season": SEASON},
        "assets": {
            "original_url": artifacts["original_url"],
            "thumbnail_url": artifacts["thumbnail_url"],
            "original_size": artifacts["original_size"],
        },
        "checks": {},
        "screenshots": [],
    }

    server, thread = _serve(site_root, base_path)
    web_root = f"http://127.0.0.1:{server.server_port}{base_path}"
    origin = f"http://127.0.0.1:{server.server_port}"
    original_absolute = origin + original_public_path
    thumbnail_absolute = origin + thumbnail_public_path
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel="chrome", headless=True)
            try:
                # Profile: original network is held while the preview and high-priority preload are checked.
                profile = await _open_page_with_original_route(
                    browser, web_root + artifacts["profile_route"], original_public_path)
                try:
                    page = profile["page"]
                    profile_preview = await _wait_for_photo(page, PROFILE_SELECTOR, thumbnail_absolute)
                    preload_result = await _assert_profile_preloads(page, original_absolute, thumbnail_absolute)
                    profile_shot = screenshot_dir / "profile-thumbnail-visible.png"
                    await page.screenshot(path=str(profile_shot), full_page=False)
                    report["screenshots"].append(str(profile_shot))
                    profile["release_route"].set()
                    profile_original = await _wait_for_photo(page, PROFILE_SELECTOR, original_absolute,
                                                             artifacts["original_size"])
                    report["checks"]["profile_preview_then_original"] = {
                        "passed": True,
                        "preview": profile_preview,
                        "preload": preload_result,
                        "original": profile_original,
                    }
                finally:
                    profile["release_route"].set()
                    await profile["context"].close()

                # Directory: capture the browser's initial request priority while the original is held.
                listing = await _open_page_with_original_route(
                    browser, web_root + artifacts["list_route"], original_public_path, capture_priority=True)
                try:
                    page = listing["page"]
                    list_preview = await _wait_for_photo(page, LIST_SELECTOR, thumbnail_absolute)
                    priority = await _assert_low_priority(listing["priorities"])
                    list_shot = screenshot_dir / "list-thumbnail-visible.png"
                    await page.screenshot(path=str(list_shot), full_page=False)
                    report["screenshots"].append(str(list_shot))
                    listing["release_route"].set()
                    list_original = await _wait_for_photo(page, LIST_SELECTOR, original_absolute,
                                                          artifacts["original_size"])
                    report["checks"]["list_preview_then_original"] = {
                        "passed": True,
                        "preview": list_preview,
                        "priority": priority,
                        "original": list_original,
                    }
                finally:
                    listing["release_route"].set()
                    await listing["context"].close()

                # Directory: abort the original and confirm the decoded thumbnail remains visible.
                aborted = await _open_page_with_original_route(
                    browser, web_root + artifacts["list_route"], original_public_path, abort_original=True)
                try:
                    page = aborted["page"]
                    await _wait_for_photo(page, LIST_SELECTOR, thumbnail_absolute)
                    await asyncio.wait_for(aborted["route_aborted"].wait(), timeout=10)
                    await page.wait_for_timeout(500)
                    aborted_preview = await _wait_for_photo(page, LIST_SELECTOR, thumbnail_absolute)
                    report["checks"]["original_abort_keeps_preview"] = {
                        "passed": True,
                        "aborted_requests": len(aborted["original_requests"]),
                        "preview": aborted_preview,
                    }
                finally:
                    aborted["release_route"].set()
                    await aborted["context"].close()
            finally:
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    report["state"] = "passed"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path, default=DEFAULT_SITE_ROOT,
                        help="Static export directory (default: tmp/pages-preview/langrensha-site)")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT,
                        help="JSON report output (default: tmp/diagnostics/check_progressive_player_photos.json)")
    args = parser.parse_args()
    site_root = args.site_root.resolve()
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = asyncio.run(_run_checks(site_root, report_path))
        result["report"] = str(report_path)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Progressive player photo checks passed; report: {report_path}")
        return 0
    except Exception as error:
        failure = {
            "state": "failed",
            "site_root": str(site_root),
            "error": f"{type(error).__name__}: {error}",
            "report": str(report_path),
        }
        report_path.write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Progressive player photo checks failed: {failure['error']}", file=sys.stderr)
        print(f"Report: {report_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
