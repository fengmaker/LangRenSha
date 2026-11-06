"""Capture the current, unmodified website for the introduction video."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1]
SHOTS = OUT / "support" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:3000"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
    records = {}

    def capture(name, path, y=0):
        page.goto(BASE + path, wait_until="networkidle", timeout=60000)
        page.evaluate("document.fonts.ready")
        page.locator("img").evaluate_all("imgs => Promise.all(imgs.filter(i => i.getBoundingClientRect().top < innerHeight && i.getBoundingClientRect().bottom > 0).map(i => i.decode().catch(() => {})))")
        page.evaluate("y => window.scrollTo({top:y,behavior:'instant'})", y)
        page.screenshot(path=str(SHOTS / f"{name}.png"), animations="disabled")
        records[name] = {"url": page.url, "scroll_y": page.evaluate("scrollY"),
                         "title": page.title(), "text": page.locator("body").inner_text()[:18000],
                         "links": page.locator("a[href]").evaluate_all("a => a.map(x => ({text:x.innerText, href:x.getAttribute('href')}))"),
                         "controls": page.locator("input,select,button").evaluate_all("a => a.map(x => ({tag:x.tagName, text:x.innerText, placeholder:x.getAttribute('placeholder'), label:x.getAttribute('aria-label'), options:x.tagName==='SELECT' ? [...x.options].map(o=>({text:o.text,value:o.value})) : null}))")}
        print(name, page.title(), flush=True)
        (OUT / "support" / "capture_manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    capture("home", "/")
    capture("games", "/games")
    page.get_by_label("赛季", exact=True).select_option("S23")
    page.get_by_label("版型", exact=True).select_option("mechanical_wolf_seer")
    page.get_by_role("button", name="检索对局", exact=True).click()
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(SHOTS / "games_filtered.png"), animations="disabled")
    games = [x["href"] for x in records["games"]["links"] if x["href"].startswith("/games/")]
    game = games[0]
    capture("game_seats", game)
    records["game_sections"] = page.locator("section").evaluate_all("s => s.map(x => ({heading:x.querySelector('h1,h2,h3')?.innerText, y:x.getBoundingClientRect().top+scrollY}))")
    capture("game_flow", game, 750)
    capture("game_roles", game, 490)
    capture("game_night", game, 1230)
    capture("game_vote", game, 2130)
    capture("leaderboard", "/leaderboard")
    capture("players", "/players")
    players = [x["href"] for x in records["players"]["links"] if x["href"].startswith("/players/")]
    capture("player", players[0])
    capture("player_stats", players[0], 860)
    h = page.get_by_role("heading", name="逐局记录", exact=True)
    if not h.count():
        h = page.get_by_role("heading", name="出场记录", exact=True)
    if h.count():
        h.scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "player_games.png"), animations="disabled")
    else:
        headings = page.locator("h2").evaluate_all("a => a.map(x=>({text:x.innerText,y:x.getBoundingClientRect().top+scrollY}))")
        print("player headings", headings, flush=True)
    capture("stats", "/stats")
    (OUT / "support" / "capture_manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    browser.close()
