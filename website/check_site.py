"""Exercise real published data and browser navigation against a running website."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", default="http://127.0.0.1:3000")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    artifacts = ROOT / "website" / "artifacts"
    artifacts.mkdir(exist_ok=True)

    def api(path):
        with urlopen(args.api + path, timeout=15) as response:
            return json.load(response)

    overview = api("/api/v1/overview")
    assert overview["totals"]["games"] == 148, "This S22 acceptance check expects the full release"
    assert overview["totals"]["days"] == 47
    items = []
    for number in (1, 2):
        items.extend(api(f"/api/v1/games?page={number}&page_size=100")["items"])
    assert len(items) == len({g["id"] for g in items}) == 148
    details = [api("/api/v1/games/" + item["id"]) for item in items]
    assert {d["release_id"] for d in details} == {overview["release"]["id"]}
    assert sum(len(d["seats"]) for d in details) == 1776
    assert sum(len(d["voting"]["ballots"]) for d in details) == 347
    assert sum(len(b["votes"]) for d in details for b in d["voting"]["ballots"]) == 2513
    assert sum(s["faction"] is None for d in details for s in d["seats"]) == 0
    assert all(".secrets" not in json.dumps(d) and '"path"' not in json.dumps(d) for d in details)
    assert api("/api/v1/games?phase=finals_week")["total"] == 12
    assert api("/api/v1/games?phase=regular")["total"] == 136
    for path, expected in (("/api/v1/games?page=0", 422), ("/api/v1/games/missing-game", 404)):
        try:
            api(path)
            raise AssertionError(f"Expected HTTP {expected}")
        except HTTPError as error:
            assert error.code == expected

    sample = next(d for d in details if d["source"]["bvid"] == "BV1yt7v6QE3Q")
    reflected = next(d for d in details if any(e.get("effects") for r in d["rounds"] for e in r["night"] + r["day"]))
    default_vote = next(d for d in details if any(v.get("basis") == "rule_default" for b in d["voting"]["ballots"] for v in b["votes"]))
    endgame = next(d for d in details if d["endgame"]["phases"])
    double_ties = [d for d in details if any(e.get("result") == "double_tie"
                   for r in d["presentation"]["rounds"] for e in r["day"])]
    assert len(double_ties) == 4
    jy = next(p for p in api("/api/v1/players?q=JY")["items"] if p["name"] == "JY")
    report = {"totals": overview["totals"], "release": overview["release"]["id"],
              "api_details_checked": len(details), "browser_errors": [], "pages_checked": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.on("pageerror", lambda error: report["browser_errors"].append(str(error)))
        for path in ("/", "/seasons/S22", "/games", "/players", "/players/" + jy["id"], "/stats"):
            response = page.goto(args.web + path, wait_until="networkidle")
            assert response and response.status == 200, path
            assert "暂时无法" not in page.locator("main").inner_text(), path
            report["pages_checked"].append(path)
            if path == "/":
                page.screenshot(path=str(artifacts / "home-desktop.png"), full_page=True)
        page.goto(args.web + "/games", wait_until="networkidle")
        page.get_by_label("比赛阶段", exact=True).select_option("finals_week")
        page.get_by_role("button", name=re.compile("检索对局")).click()
        page.wait_for_load_state("networkidle")
        assert "phase=finals_week" in page.url
        assert page.locator('section[aria-labelledby="games-heading"] [data-game-row]').count() == 12
        page.goto(args.web + "/games?page=100&phase=finals_week", wait_until="networkidle")
        assert "page=100" not in page.url and "phase=finals_week" in page.url
        page.goto(args.web + "/players?" + urlencode({"q": "JY"}), wait_until="networkidle")
        page.locator(f'a[href^="/players/{jy["id"]}"]').first.click()
        page.wait_for_load_state("networkidle")
        assert page.get_by_role("heading", name="JY", exact=True).count() == 1
        for game in (sample, reflected, default_vote, endgame, *double_ties):
            page.goto(args.web + "/games/" + game["id"], wait_until="networkidle")
            text = page.locator("main").inner_text()
            assert page.locator('.timeline-phase[data-phase="night"]').count() > 0
            finish = page.locator(".game-finish")
            assert finish.count() == 1 and "游戏结束" in finish.inner_text()
            expected_winner = {"good": "好人阵营获胜", "werewolf": "狼人阵营获胜"}.get(game["winner"])
            if expected_winner:
                assert expected_winner in finish.inner_text()
            assert page.evaluate("""() => {
                const finish = document.querySelector('.game-finish');
                return [...document.querySelectorAll('.timeline-phase, .endgame-section')]
                    .every(section => Boolean(section.compareDocumentPosition(finish) & Node.DOCUMENT_POSITION_FOLLOWING));
            }""")
            assert "该座位是本局唯一且仍在场的猎人" not in text
            for round_ in game["presentation"]["rounds"]:
                if any(e.get("result") == "double_tie" for e in round_["day"]):
                    day = page.locator(f'.timeline-day[data-day="{round_["number"]}"]')
                    assert "首轮与 PK 轮均平票，本日无人被放逐。" in day.inner_text()
            if game is sample:
                assert "延期" in text and ("流徽" in text or "警徽流失" in text)
                police = page.locator('.registration-card p').filter(has_text="警下").first.inner_text()
                assert "2号、3号、10号" in police.replace(" ", "")
                assert page.locator('[data-slot="seer_check"] .game-event-content').filter(has_text="结果为狼人").count() > 0
                page.screenshot(path=str(artifacts / "game-desktop.png"), full_page=True)
            if game is reflected:
                assert "反弹" in text and "实际出局" in text
            if game is default_vote:
                assert "默认弃票" in text
            if game is endgame:
                assert "明确提及目标" in text
            if game["source"]["bvid"] == "BV1jM8B6jEkF":
                night2 = page.locator('.timeline-night[data-day="2"]')
                seer = night2.locator('[data-slot="seer_check"] .game-event-content').inner_text()
                assert "原选择查验4号" in seer and "实际查验6号" in seer
                assert "结果为好人" in seer and "反馈待核" not in seer
                knife = night2.locator('[data-slot="wolf_attack"]').inner_text()
                assert "选择击杀6号" in knife and "实际刀口为4号" in knife
                for number in (2, 3):
                    poison = page.locator(f'.timeline-night[data-day="{number}"] [data-slot="witch_poison"]').inner_text()
                    assert "压毒，本夜未使用毒药" in poison and "仍待核实" not in poison
                badge = page.locator('.timeline-day[data-day="2"] [data-slot="badge"]').inner_text()
                assert "警徽流失" in badge and "没有结果" not in badge
            for attack in page.locator('.game-event[data-action="attack"]').all():
                assert "击杀" in attack.inner_text() and "袭击" not in attack.inner_text()
            report["pages_checked"].append("/games/" + game["id"])
        response = page.goto(args.web + "/games/not-a-real-game", wait_until="networkidle")
        assert "档案" in page.locator("main").inner_text()
        assert response and response.status == 404
        for width in (360, 390, 768):
            page.set_viewport_size({"width": width, "height": 844})
            for path in ("/", "/seasons/S22", "/games", "/games/" + sample["id"], "/players", "/stats"):
                page.goto(args.web + path, wait_until="networkidle")
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (width, path)
                if width == 390 and path == "/":
                    page.screenshot(path=str(artifacts / "home-mobile.png"), full_page=True)
                if width == 390 and path.endswith(sample["id"]):
                    page.screenshot(path=str(artifacts / "game-mobile.png"), full_page=True)
        browser.close()
    assert not report["browser_errors"], report["browser_errors"]
    (artifacts / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
