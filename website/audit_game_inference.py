"""Verify every published game uses current rules and export per-game evidence.

Run from the repository root: python -m website.audit_game_inference
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from website.api.game_presentation import PRESENTATION_VERSION, build_game_presentation


ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "hunter_state": "猎人开枪状态", "witch_poison": "毒药使用与压毒",
    "badge": "警徽流失", "seer_check": "查验反馈与实际目标",
    "wolf_attack": "交换后的实际刀口", "exile_result": "放逐结果",
    "hunter_shot": "猎人出局后开枪情况待核",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--season", default="S22", choices=["S22"])
    parser.add_argument("--browser", action="store_true", help="Open every dossier in Chrome and verify its rendered events")
    parser.add_argument("--web", default="http://127.0.0.1:3000")
    args = parser.parse_args()

    def api(path: str):
        with urlopen(args.api.rstrip("/") + path, timeout=30) as response:
            return json.load(response)

    first = api("/api/v1/games?" + urlencode({"season": args.season, "page": 1, "page_size": 100}))
    summaries = list(first["items"])
    for number in range(2, (first["total"] + 99) // 100 + 1):
        summaries.extend(api("/api/v1/games?" + urlencode({"season": args.season, "page": number, "page_size": 100}))["items"])
    assert len(summaries) == len({g["id"] for g in summaries}) == first["total"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        games = list(pool.map(lambda item: api("/api/v1/games/" + item["id"]), summaries))

    rules, unknown, poison_actions = Counter(), Counter(), Counter()
    rows = []
    for game in games:
        assert game["release_id"] == first["release_id"], "Active release changed during audit"
        original = json.dumps(game["rounds"], sort_keys=True, ensure_ascii=False)
        expected = build_game_presentation(game)
        assert game["presentation"] == expected, f"Stale or different rules: {game['id']}"
        assert expected["version"] == PRESENTATION_VERSION
        assert original == json.dumps(game["rounds"], sort_keys=True, ensure_ascii=False)
        inferred, pending = [], []
        for round_ in expected["rounds"]:
            for phase in ("night", "day"):
                for event in round_[phase]:
                    item = {"round": round_["number"], "phase": phase,
                            **{key: event.get(key) for key in ("slot", "slot_label", "actor", "action", "targets", "resolved_targets", "result", "inference_note")}}
                    if event.get("inferred"):
                        inferred.append(item)
                        rules[event["slot"]] += 1
                        if event["slot"] == "witch_poison":
                            poison_actions[event["action"]] += 1
                    if event.get("action") in (None, "unknown"):
                        pending.append(item)
                        unknown[event["slot"]] += 1
        rows.append({"id": game["id"], "date": game["date"], "game_number": game["game_number"],
                     "board": game["board"]["name"], "rules_version": expected["version"],
                     "source_rounds_sha256": hashlib.sha256(original.encode()).hexdigest(),
                     "raw_events": sum(len(r[p]) for r in game["rounds"] for p in ("night", "day")),
                     "display_events": sum(len(r[p]) for r in expected["rounds"] for p in ("night", "day")),
                     "omitted_events": expected["omitted_events"], "inferred": inferred, "pending": pending})
    rows.sort(key=lambda row: (row["date"], row["game_number"] or 0, row["id"]))
    browser_checked, browser_errors = 0, []
    if args.browser:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: browser_errors.append(str(error)))
            for index, game in enumerate(games, 1):
                response = page.goto(args.web.rstrip("/") + "/games/" + game["id"], wait_until="domcontentloaded")
                assert response and response.status == 200, game["id"]
                assert page.locator(".game-finish").count() == 1, game["id"]
                expected_count = sum(len(r[p]) for r in game["presentation"]["rounds"] for p in ("night", "day"))
                assert page.locator(".game-event").count() == expected_count, game["id"]
                for attack in page.locator('.game-event[data-action="attack"]').all():
                    assert "击杀" in attack.inner_text() and "袭击" not in attack.inner_text(), game["id"]
                for round_ in game["presentation"]["rounds"]:
                    for phase in ("night", "day"):
                        for event in round_[phase]:
                            if not event.get("inferred"):
                                continue
                            text = page.locator(f'.timeline-phase[data-phase="{phase}"][data-day="{round_["number"]}"] [data-slot="{event["slot"]}"]').first.inner_text()
                            if event["slot"] == "witch_poison" and event["action"] == "pass":
                                assert "压毒" in text and "仍待核实" not in text, game["id"]
                            if event["slot"] == "badge" and event["action"] == "badge_lost":
                                assert "警徽流失" in text and "没有结果" not in text, game["id"]
                            if event["slot"] == "seer_check" and event.get("result"):
                                assert "查验反馈待核" not in text, game["id"]
                            if event.get("resolved_targets"):
                                assert "实际" in text, game["id"]
                browser_checked += 1
                if index % 25 == 0 or index == len(games):
                    print(f"Browser verified {index}/{len(games)}", flush=True)
            browser.close()
        assert not browser_errors, browser_errors
    report = {"season": args.season, "checked_at": datetime.now(timezone.utc).isoformat(),
              "release_id": first["release_id"], "rules_version": PRESENTATION_VERSION,
              "games_checked": len(rows), "games_with_inference": sum(bool(row["inferred"]) for row in rows),
              "all_api_results_match_current_rules": True, "source_rounds_preserved": True,
              "browser_pages_checked": browser_checked, "browser_errors": browser_errors,
              "rule_counts": dict(rules), "inferred_poison_actions": dict(poison_actions),
              "remaining_unknown_counts": dict(unknown), "games": rows}
    output = ROOT / "data" / "exports"
    output.mkdir(exist_ok=True)
    base = output / f"{args.season}_全部档案推断汇总"
    base.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"{args.season} 全部档案推断汇总", f"已逐局核对：{len(rows)} 局；统一推断版本：{PRESENTATION_VERSION}",
             "全部线上 API 结果与当前推断规则一致；原始日夜记录保持不变。", "",
             "当前推断记录（含此前已应用的规则，并非本次新增数量）："]
    if browser_checked:
        lines.insert(3, f"已实际打开并检查 {browser_checked} 个档案网页，浏览器脚本错误为 0。")
    lines.extend(f"{LABELS.get(slot, slot)}：{count}" for slot, count in rules.items())
    lines += [f"其中压毒 {poison_actions['pass']} 条；毒药目标/结算 {poison_actions['poison']} 条。",
              f"仍有 {unknown['witch_poison']} 条毒药记录不能唯一确定，继续标注待核。", "", "逐局明细："]
    for row in rows:
        lines += ["", f"{row['date']} 第{row['game_number']}局 · {row['board']}",
                  f"http://127.0.0.1:3000/games/{row['id']}",
                  f"推断 {len(row['inferred'])} 项；待核 {len(row['pending'])} 项；省略无效空槽 {row['omitted_events']} 项。"]
        for item in row["inferred"]:
            phase = "夜" if item["phase"] == "night" else "天"
            lines.append(f"  第{item['round']}{phase} · {LABELS.get(item['slot'], item['slot'])}：{item['inference_note'] or item['result'] or item['action']}")
    base.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "games"}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
