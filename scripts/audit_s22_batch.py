"""Read-only comparison of S22 dossiers, batch receipts and PostgreSQL facts."""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
import json
import sys
from urllib.parse import unquote, urlsplit

import batch_s22 as batch
from database import connect
from game_scope import exclusion_reason
from game_records import validate


REPORT = batch.ROOT / "data/reports/S22/S22_对局批处理验收.json"


class LocalLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        self.links.extend(value for key, value in attrs if key in {"href", "src"} and value)


def check_review_links(state):
    pages = [batch.SEASON_DIR / "批量复核.html"]
    pages.extend(batch.ROOT / e["output_dir"] / "复核.html"
                 for e in state["items"].values() if e.get("state") != "preserved")
    broken, count = [], 0
    for page in pages:
        if not page.is_file():
            broken.append({"page": batch.relative(page), "target": "复核页缺失"})
            continue
        parser = LocalLinks()
        parser.feed(page.read_text(encoding="utf-8"))
        for target in parser.links:
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            count += 1
            if not (page.parent / unquote(parts.path)).is_file():
                broken.append({"page": batch.relative(page), "target": target})
    return {"pages": len(pages), "local_links": count, "broken": broken}


def check_scope_exclusions(state, conn):
    """Confirm excluded catalog items are absent and active entries are in scope."""
    catalog_entries = batch.entries_from_catalog(include_excluded=True)
    excluded_entries = [entry for entry in catalog_entries
                        if exclusion_reason(entry, root=batch.ROOT)]
    excluded_bvids = {entry["bvid"] for entry in excluded_entries}
    active_excluded = sorted(
        bvid for bvid, entry in state["items"].items()
        if exclusion_reason(entry, root=batch.ROOT)
    )
    slugs = [row["slug"] for row in conn.execute("""SELECT g.slug FROM games g
        JOIN seasons s ON s.id=g.season_id WHERE s.code='S22'""").fetchall()]
    excluded_database_games = sorted(
        slug for slug in slugs
        if any(slug.startswith(f"bili-{bvid}-") for bvid in excluded_bvids)
    )
    return {
        "pass": not active_excluded and not excluded_database_games,
        "excluded_catalog_games": len(excluded_entries),
        "active_entries_excluded_by_scope": active_excluded,
        "excluded_database_games": excluded_database_games,
    }


def audit():
    state = batch.load_state()
    entries = state["items"]
    expected_games = len(entries)
    errors, coverage = [], []
    scope_check = {}
    with connect() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        scope_check = check_scope_exclusions(state, conn)
        if not scope_check["pass"]:
            errors.append({"bvid": "", "error": "数据库或有效批次包含范围排除的对局。"})
        for entry in entries.values():
            bvid = entry["bvid"]
            out = batch.ROOT / entry["output_dir"]
            try:
                value = batch.read_json(out / "dossier.json")
                validate(value, allow_incomplete=entry.get("state") != "preserved")
                detail = conn.execute("""SELECT g.id, d.* FROM games g
                    JOIN game_details d ON d.game_id=g.id WHERE g.slug=%s""", (value["slug"],)).fetchone()
                if not detail:
                    raise ValueError("数据库没有对应对局")
                game_id = detail["id"]
                if str(game_id) != entry.get("db_receipt", {}).get("game_id"):
                    raise ValueError("数据库对局标识与进度收据不一致")
                for column, key in [("board_code", "board"), ("phase", "phase"), ("episode", "episode"),
                                    ("day_in_episode", "day_in_episode"), ("game_number", "game_number"),
                                    ("winning_faction", "winner")]:
                    if detail[column] != value[key]:
                        raise ValueError("数据库对局字段不一致：" + key)
                if detail["event_date"].isoformat() != value["date"]:
                    raise ValueError("数据库比赛日期不一致")
                seats = conn.execute("""SELECT s.seat_number AS seat, p.name, s.role, s.faction,
                    s.learning_target_seat AS learning_target, s.learned_role
                    FROM game_seats s LEFT JOIN people p ON p.id=s.person_id
                    WHERE s.game_id=%s ORDER BY s.seat_number""", (game_id,)).fetchall()
                if seats != sorted(value["seats"], key=lambda s: s["seat"]):
                    raise ValueError("数据库座位身份或学习形态与档案不一致")
                rounds = [r["round_number"] for r in conn.execute(
                    "SELECT round_number FROM game_rounds WHERE game_id=%s ORDER BY round_number", (game_id,)).fetchall()]
                if rounds != [r["number"] for r in value["rounds"]]:
                    raise ValueError("数据库轮次与档案不一致")
                db_events = conn.execute("SELECT * FROM game_event_records WHERE game_id=%s", (game_id,)).fetchall()
                events = {}
                event_ids = {}
                for row in db_events:
                    key = (row["round_number"], row["phase"], row["slot_code"])
                    event = {"slot": row["slot_code"], "action": row["action"], "actor": row["actor_seat"],
                             "result": row["result_code"], "start_seat": row["start_seat"], "direction": row["direction"],
                             "random_point": row["random_point"], "speech_scope": row["speech_scope"],
                             "availability": row["availability"], "targets": [], "votes": [], "effects": []}
                    events[key] = event
                    event_ids[row["id"]] = event
                for row in conn.execute("SELECT * FROM game_event_targets WHERE game_id=%s ORDER BY event_id,position", (game_id,)):
                    event_ids[row["event_id"]]["targets"].append(row["seat_number"])
                for row in conn.execute("SELECT * FROM game_event_votes WHERE game_id=%s ORDER BY event_id,ballot_round,voter_seat", (game_id,)):
                    event_ids[row["event_id"]]["votes"].append({"round": row["ballot_round"], "voter": row["voter_seat"],
                                                             "target": row["target_seat"], "abstained": row["abstained"]})
                for row in conn.execute("SELECT * FROM game_event_effects WHERE game_id=%s ORDER BY event_id,position", (game_id,)):
                    event_ids[row["event_id"]]["effects"].append({k: row[k] for k in ("kind", "intended_target", "dead_seat", "shield_actor")})
                expected = {}
                for r in value["rounds"]:
                    for phase in ("night", "day"):
                        for event in r[phase]:
                            expected[(r["number"], phase, event["slot"])] = {
                                **event, "votes": sorted(event["votes"], key=lambda v: (v["round"], v["voter"]))}
                if events != expected:
                    different = [str(k) for k in set(events) | set(expected) if events.get(k) != expected.get(k)]
                    raise ValueError("数据库事件、目标、票型或结算与档案不一致：" + "; ".join(different[:4]))
                receipt = entry["db_receipt"]
                if len(events) != receipt["event_records"]:
                    raise ValueError("事件数量与入库收据不一致")
                if entry.get("state") != "preserved":
                    if batch.digest(out / "dossier.json") != entry.get("imported_dossier_sha256"):
                        raise ValueError("档案内容与入库文件哈希不一致")
                    for name in ("复核.html", "复核.md", "复核记录.json", "复盘原文.txt", "复盘定位.json", "座位身份.csv", "游戏事件.csv", "database_receipt.json"):
                        if not (out / name).is_file():
                            raise ValueError("缺少复核材料：" + name)
                coverage.append({"bvid": bvid, "state": entry["state"], "recap_status": entry.get("recap_status"), **batch.coverage(value)})
            except ValueError as exc:
                errors.append({"bvid": bvid, "error": f"{type(exc).__name__}: {exc}"})
            except Exception as exc:
                errors.append({"bvid": bvid, "error": type(exc).__name__})
    actual = batch.database_snapshot()
    links = check_review_links(state)
    errors.extend({"bvid": "", "error": "复核页本地链接失效：" + str(item)} for item in links["broken"])
    preservation_file = batch.ROOT / "data/reports/S22/S22_批处理保留示例文件.json"
    preserved_checks = {}
    if preservation_file.is_file():
        for relative_path, expected_hash in batch.read_json(preservation_file)["files"].items():
            path = batch.ROOT / relative_path
            preserved_checks[relative_path] = path.is_file() and batch.digest(path) == expected_hash
            if not preserved_checks[relative_path]:
                errors.append({"bvid": "BV1yt7v6QE3Q", "error": "保留示例文件发生变化：" + relative_path})
    sample_bvid = "BV1yt7v6QE3Q"
    sample_entry = entries.get(sample_bvid)
    if not sample_entry or sample_entry.get("state") != "preserved":
        errors.append({"bvid": sample_bvid, "error": "保留示例对局未处于当前有效批次的保留状态。"})
    report = {"checked_at": batch.now(), "valid": not errors and len(coverage) == expected_games
              and actual["games"] == expected_games and scope_check.get("pass", False),
              "database_actual": actual, "checked_games": len(coverage), "failed_checks": len(errors),
              "expected_games": expected_games, "scope_exclusions": scope_check,
              "complete_role_lists": sum(r["known_roles"] == 12 for r in coverage),
              "partial_role_lists": sum(0 < r["known_roles"] < 12 for r in coverage),
              "unknown_role_lists": sum(r["known_roles"] == 0 for r in coverage),
              "no_explicit_rounds": sum(r["rounds"] == 0 for r in coverage),
              "named_seats": sum(r["named_seats"] for r in coverage),
              "known_events": sum(r["known_events"] for r in coverage),
              "recap_status": dict(Counter(r["recap_status"] for r in coverage)),
              "human_reviewed": sum(r["state"] == "reviewed" for r in coverage),
              "preserved_sample_files": preserved_checks,
              "review_links": links,
              "sample_dossier_sha256": (batch.digest(batch.ROOT / sample_entry["output_dir"] / "dossier.json")
                                         if sample_entry else None),
              "note": "验收只确认结构、文件和数据库内容一致；机器提取尚未经过逐局人工核实。",
              "errors": errors, "items": coverage}
    batch.atomic_json(REPORT, report)
    print(json.dumps({k: v for k, v in report.items() if k != "items"}, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        return audit()
    except Exception as exc:
        print(json.dumps({"valid": False, "audit_error": type(exc).__name__}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
