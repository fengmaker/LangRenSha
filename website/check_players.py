"""Verify season player metrics against dossiers, then exercise the real website."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000/api/v1"


def api(path: str):
    with urlopen(API + path, timeout=30) as response:
        return json.load(response)


def main():
    expected = {phase: defaultdict(Counter) for phase in ("all", "finals_week")}
    ratios = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    resolved = []
    for path in sorted((ROOT / "data/games/S22").glob("*/dossier.json")):
        game = json.loads(path.read_text(encoding="utf-8"))
        seats = {seat["seat"]: dict(seat) for seat in game["seats"]}
        for number, seat in seats.items():
            if seat["role"] == "混血儿" and seat["faction"] is None:
                targets = {event["targets"][0] for round_ in game["rounds"]
                           for event in round_["night"] + round_["day"]
                           if event["slot"] == "mixed_blood_model" and event["action"] == "choose"
                           and event["actor"] == number and len(event["targets"]) == 1}
                assert len(targets) == 1
                seat["faction"] = seats[next(iter(targets))]["faction"]
                resolved.append((game["slug"], number, seat["faction"]))
            assert seat["faction"] in ("good", "werewolf")
            win = seat["faction"] == game["winner"]
            half = (3 if seat["faction"] == "werewolf" else 2) if win else -2
            for phase in ("all", "finals_week"):
                if phase == "finals_week" and game["phase"] != phase:
                    continue
                counts = expected[phase][seat["name"]]
                counts.update({"appearances": 1, "wins": int(win), "losses": int(not win), "half": half})
            counts = ratios[seat["name"]][seat["faction"] + "_win_rate"]
            counts[0] += int(win)
            counts[1] += 1

        voting = json.loads((path.parent / "voting.json").read_text(encoding="utf-8"))
        first = min(voting["registrations"], key=lambda row: (row["day"], row["id"]))
        for number, seat in seats.items():
            assert number in first["on_police"] or number in first["off_police"]
            counts = ratios[seat["name"]]["sheriff_registration_rate"]
            counts[0] += int(number in first["on_police"])
            counts[1] += 1
        seers = [number for number, seat in seats.items() if seat["role"] in ("预言家", "通灵师")]
        assert len(seers) <= 1
        if not seers:
            continue
        seer = seers[0]
        for ballot in voting["ballots"]:
            votes = {vote["voter"]: vote for vote in ballot["votes"]}
            eligible = ballot["eligible_voters"]
            if eligible is None:
                continue
            for number in eligible:
                seat = seats[number]
                if seat["faction"] != "good" or number == seer or number not in votes:
                    continue
                vote = votes[number]
                if ballot["kind"] == "exile":
                    reference = votes.get(seer)
                    if seer not in eligible or not reference or reference["state"] != "cast" or reference["target"] is None:
                        continue
                    metric = "seer_follow_rate"
                    correct = vote["state"] == "cast" and vote["target"] == reference["target"]
                elif ballot["kind"] == "sheriff":
                    candidates = ballot["candidates"]
                    candidate = seer in candidates if candidates is not None else any(
                        row["state"] == "cast" and row["target"] == seer for row in votes.values())
                    if not candidate:
                        continue
                    metric = "sheriff_seer_vote_rate"
                    correct = vote["state"] == "cast" and vote["target"] == seer
                else:
                    continue
                counts = ratios[seat["name"]][metric]
                counts[0] += int(correct)
                counts[1] += 1

    boards = {phase: api(f"/leaderboard?phase={phase}") for phase in expected}
    assert boards["all"]["game_count"] == 148 and boards["finals_week"]["game_count"] == 12
    assert len(resolved) == 8
    players = api("/players?page_size=100")["items"]
    assert len(players) == 62
    profiles = {}
    for player in players:
        detail = api("/players/" + player["id"])
        profiles[player["name"]] = detail
        stats = detail["stats"]
        counts = expected["all"][player["name"]]
        assert detail["photo"]["season"] == "S22"
        assert stats["points"] == counts["half"] / 2
        assert stats["points_complete"] and stats["pending_games"] == 0
        assert (stats["wins"], stats["losses"], stats["appearances"]) == (counts["wins"], counts["losses"], counts["appearances"])
        assert stats["attendance"]["numerator"] == counts["appearances"]
        assert stats["attendance"]["denominator"] == 148
        assert stats["total_win_rate"]["rate"] == counts["wins"] / counts["appearances"]
        assert sum(row["points"] for row in stats["ledger"]) == stats["points"]
        assert stats["ledger"][-1]["cumulative_points"] == stats["points"]
        for metric, (numerator, denominator) in ratios[player["name"]].items():
            actual = stats[metric]
            assert (actual["numerator"], actual["denominator"]) == (numerator, denominator), (player["name"], metric, actual, (numerator, denominator))
        assert player["stats"]["total_win_rate"] == stats["total_win_rate"]
    for phase, board in boards.items():
        assert {row["name"] for row in board["items"]} == set(expected[phase])
        assert board["pending_games"] == 0
        for row in board["items"]:
            assert row["points"] == expected[phase][row["name"]]["half"] / 2
            assert row["rank"] == 1 + sum(other["points"] > row["points"] for other in board["items"])
            for metric in ("attendance", "total_win_rate", "werewolf_win_rate", "good_win_rate", "sheriff_registration_rate"):
                assert row[metric] == profiles[row["name"]]["stats"][metric]
    jy = profiles["JY"]
    assert api(f"/players/{jy['id']}?phase=finals_week")["stats"] == jy["stats"]
    for game_id, number, faction in resolved:
        game = api("/games/" + game_id)
        assert next(row for row in game["seats"] if row["seat"] == number)["faction"] == faction
        assert next(row for row in game["players"] if row["seat"] == number)["faction"] == faction
    with urlopen(WEB + jy["photo"]["url"]) as response:
        assert response.headers["Content-Type"] == "image/jpeg"
        assert hashlib.sha256(response.read()).hexdigest() == Path(jy["photo"]["url"]).stem

    artifacts = ROOT / "website/artifacts"
    artifacts.mkdir(exist_ok=True)
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("pageerror", lambda error: errors.append(str(error)))
        profile_url = WEB + "/players/" + jy["id"]
        page.goto(profile_url, wait_until="networkidle")
        assert page.get_by_role("heading", name="JY", exact=True).count() == 1
        assert page.locator('select[name="phase"]').count() == 0
        assert page.locator(".profile-photo-frame img").evaluate("img => img.complete && img.naturalWidth > 0")
        assert page.locator(".profile-stat-card").count() == 9
        page.screenshot(path=str(artifacts / "player-desktop.png"))
        page.locator(".metric-samples summary").nth(1).click()
        page.locator(".metric-samples").nth(1).locator("a").first.click()
        page.wait_for_url("**/games/**")
        page.wait_for_load_state("networkidle")
        assert "/games/" in page.url
        page.goto(WEB + "/leaderboard", wait_until="networkidle")
        assert "JY" in page.locator("tbody tr").first.inner_text()
        page.get_by_role("link", name="决赛周冠军榜", exact=True).click()
        page.wait_for_url("**phase=finals_week")
        page.wait_for_load_state("networkidle")
        assert "phase=finals_week" in page.url
        assert "小苍" in page.locator("tbody tr").first.inner_text()
        page.screenshot(path=str(artifacts / "leaderboard-desktop.png"))
        for width in (360, 390, 768):
            page.set_viewport_size({"width": width, "height": 844})
            for path in ("/players/" + jy["id"], "/leaderboard", "/leaderboard?phase=finals_week"):
                page.goto(WEB + path, wait_until="networkidle")
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (width, path)
                if width == 390:
                    filename = "player-mobile.png" if "/players/" in path else "leaderboard-mobile.png"
                    page.screenshot(path=str(artifacts / filename))
        browser.close()
    assert not errors, errors
    report = {"players_checked": len(players), "mixed_blood_resolved": len(resolved),
              "all_metrics_match_dossiers": True, "browser_errors": errors,
              "leaderboards": {phase: [{"name": row["name"], "points": row["points"]} for row in board["items"][:5]] for phase, board in boards.items()}}
    (artifacts / "players-acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
