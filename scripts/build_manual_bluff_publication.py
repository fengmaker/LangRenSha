"""Prepare a source-bound S23 bluff payload from the user's manual review."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT, ROOT / "scripts"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))
DEFAULT_MANUAL = ROOT / "S23_manual_bluff_review_a9b3b788d571.json"
ASSET_PATH = ROOT / "website/assets/bluffs/S23.json"
USER_ARCHIVE_DIR = ROOT / "data/extractions/S23/bluff_review"
REPORT_JSON = ROOT / "data/reports/S23_悍跳人工复核应用_20261029.json"
REPORT_MD = ROOT / "data/reports/S23_悍跳人工复核应用_20261029.md"


class ManualReviewError(ValueError):
    """The manual review does not match its bound source or is contradictory."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ManualReviewError(f"{label}必须是64位小写SHA-256")
    return value


def _index_games(rows: object, label: str, key: str) -> dict[str, dict]:
    if not isinstance(rows, list):
        raise ManualReviewError(f"{label} games必须是数组")
    indexed: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ManualReviewError(f"{label}包含无效对局")
        value = row.get(key)
        if not isinstance(value, str) or not value:
            raise ManualReviewError(f"{label}包含缺失的{key}")
        if value in indexed:
            raise ManualReviewError(f"{label}包含重复的{key}: {value}")
        indexed[value] = row
    return indexed


def _seat_index(game: dict, label: str) -> dict[int, dict]:
    seats = game.get("seats")
    if not isinstance(seats, list) or len(seats) != 12:
        raise ManualReviewError(f"{label}必须有12个座位")
    indexed: dict[int, dict] = {}
    for seat in seats:
        if not isinstance(seat, dict) or type(seat.get("seat")) is not int:
            raise ManualReviewError(f"{label}包含无效座位")
        number = seat["seat"]
        if not 1 <= number <= 12 or number in indexed:
            raise ManualReviewError(f"{label}座位号重复或越界")
        indexed[number] = seat
    if set(indexed) != set(range(1, 13)):
        raise ManualReviewError(f"{label}座位不完整")
    return indexed


def _manual_games(manual: dict, source: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    if manual.get("format") != source.get("format") or manual.get("season") != "S23":
        raise ManualReviewError("人工文件格式或赛季与生成来源不一致")
    if (manual.get("source_fingerprint") != source.get("source_fingerprint")
            or not isinstance(source.get("source_fingerprint"), str)):
        raise ManualReviewError("人工文件来源指纹与当前生成来源不一致")
    for key in ("dates",):
        if manual.get(key) != source.get(key):
            raise ManualReviewError(f"人工文件{key}与当前生成来源不一致")

    manual_by_id = _index_games(manual.get("games"), "人工文件", "review_id")
    source_by_id = _index_games(source.get("games"), "生成来源", "review_id")
    if set(manual_by_id) != set(source_by_id):
        raise ManualReviewError("人工文件对局范围与当前生成来源不一致")
    for review_id, row in manual_by_id.items():
        source_row = source_by_id[review_id]
        without_reviews = {key: value for key, value in row.items() if key != "reviews"}
        if _canonical(without_reviews) != _canonical(source_row):
            raise ManualReviewError(f"{review_id}剔除reviews后的元数据与来源不一致")

    manual_by_bvid: dict[str, dict] = {}
    source_by_bvid: dict[str, dict] = {}
    for mapping, target, label in ((manual_by_id, manual_by_bvid, "人工文件"),
                                   (source_by_id, source_by_bvid, "生成来源")):
        for row in mapping.values():
            bvid = row.get("bvid")
            if not isinstance(bvid, str) or not bvid or bvid in target:
                raise ManualReviewError(f"{label}包含缺失或重复的BVID")
            target[bvid] = row
    return manual_by_bvid, source_by_bvid


def _success_value(value: object, label: str) -> bool | None:
    if value in (None, "", "unknown"):
        return None
    if value == "yes":
        return True
    if value == "no":
        return False
    raise ManualReviewError(f"{label}成功结果只能是yes、no、unknown或空值")


def _review_selection(row: dict, source_row: dict) -> tuple[dict[int, dict], bool, str, list[str]]:
    reviews = row.get("reviews", [])
    if not isinstance(reviews, list):
        raise ManualReviewError(f"{row['review_id']} reviews必须是数组")
    source_id = source_row["review_id"]
    selected: dict[int, dict] = {}
    no_bluff = False
    review_note = ""
    seen_review_ids: set[str] = set()
    for review in reviews:
        if not isinstance(review, dict):
            raise ManualReviewError(f"{row['review_id']}包含无效复核记录")
        review_id = review.get("id")
        if review_id != source_id or review_id in seen_review_ids:
            raise ManualReviewError(f"{row['review_id']}复核ID缺失、不匹配或重复")
        seen_review_ids.add(review_id)
        if "reviewed" in review and type(review["reviewed"]) is not bool:
            raise ManualReviewError(f"{row['review_id']} reviewed必须是布尔值")
        explicit_no = review.get("no_bluff", False)
        if type(explicit_no) is not bool:
            raise ManualReviewError(f"{row['review_id']} no_bluff必须是布尔值")
        rows = review.get("rows", [])
        if not isinstance(rows, list):
            raise ManualReviewError(f"{row['review_id']} rows必须是数组")
        if explicit_no and rows:
            raise ManualReviewError(f"{row['review_id']}同时声明无人悍跳和选中座位")
        if explicit_no:
            no_bluff = True
        game_note = review.get("note", "")
        if not isinstance(game_note, str):
            raise ManualReviewError(f"{row['review_id']}备注必须是字符串")
        if game_note:
            review_note = game_note
        source_seats = _seat_index(source_row, row["review_id"])
        for selected_row in rows:
            if not isinstance(selected_row, dict) or type(selected_row.get("seat")) is not int:
                raise ManualReviewError(f"{row['review_id']}包含无效选择座位")
            seat = selected_row["seat"]
            if seat not in source_seats:
                raise ManualReviewError(f"{row['review_id']}选择了不存在的座位{seat}")
            if seat in selected:
                raise ManualReviewError(f"{row['review_id']}重复选择{seat}号")
            note = selected_row.get("note", "")
            if not isinstance(note, str):
                raise ManualReviewError(f"{row['review_id']}座位备注必须是字符串")
            selected[seat] = {
                "manual_success": _success_value(selected_row.get("success"), row["review_id"]),
                "note": note,
            }
    if no_bluff and selected:
        raise ManualReviewError(f"{row['review_id']}的无人悍跳声明与选择座位矛盾")
    notes = [value["note"] for value in selected.values() if value["note"]]
    return selected, no_bluff, review_note, notes


def _snapshot_by_bvid(games: list[dict], source_by_bvid: dict[str, dict]) -> dict[str, dict]:
    if not isinstance(games, list):
        raise ManualReviewError("发布快照必须是数组")
    indexed: dict[str, dict] = {}
    game_ids: set[str] = set()
    for game in games:
        if not isinstance(game, dict):
            raise ManualReviewError("发布快照包含无效对局")
        game_id = game.get("id", game.get("slug"))
        bvid = (game.get("source") or {}).get("bvid")
        if not isinstance(game_id, str) or not game_id or game_id in game_ids:
            raise ManualReviewError("发布快照对局ID缺失或重复")
        if not isinstance(bvid, str) or not bvid or bvid in indexed:
            raise ManualReviewError("发布快照BVID缺失或重复")
        if bvid not in source_by_bvid:
            raise ManualReviewError(f"发布快照含有人工来源之外的对局：{bvid}")
        if game.get("season") != "S23":
            raise ManualReviewError(f"发布快照对局{bvid}不属于S23")
        if (str(game.get('date')), game.get('game_number')) != (
                source_by_bvid[bvid]['date'], source_by_bvid[bvid]['game_number']):
            raise ManualReviewError(f'{bvid}日期或局次与活动发布快照不一致')
        snapshot_seats = _seat_index(game, bvid)
        source_seats = _seat_index(source_by_bvid[bvid], bvid)
        for seat_no in range(1, 13):
            snapshot = snapshot_seats[seat_no]
            source = source_seats[seat_no]
            if (snapshot.get("name"), snapshot.get("role")) != (source.get("name"), source.get("role")):
                raise ManualReviewError(f"{bvid} {seat_no}号姓名或底牌与活动发布快照不一致")
        indexed[bvid] = game
        game_ids.add(game_id)
    if set(indexed) != set(source_by_bvid):
        raise ManualReviewError("活动发布快照与人工复核来源对局范围不一致")
    return indexed


def _baseline_by_game(baseline: dict) -> dict[str, dict]:
    if not isinstance(baseline, dict):
        raise ManualReviewError("旧悍跳payload必须是对象")
    rows = baseline.get("games", [])
    if not isinstance(rows, list):
        raise ManualReviewError("旧payload games必须是数组")
    indexed: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("game_id"), str):
            raise ManualReviewError("旧payload包含无效对局")
        if row["game_id"] in indexed:
            raise ManualReviewError("旧payload包含重复对局ID")
        indexed[row["game_id"]] = row
    return indexed


def _make_assessments(snapshot: dict, baseline_record: dict, selected: dict[int, dict],
                      review_id: str, source_sha256: str, game_note: str,
                      source_row: dict) -> list[dict]:
    from website.api import bluffs

    old_by_seat = {}
    for row in baseline_record.get("assessments", []):
        if isinstance(row, dict) and type(row.get("seat")) is int:
            old_by_seat[row["seat"]] = row
    output = []
    for seat in sorted(snapshot.get("seats", []), key=lambda row: row["seat"]):
        number = seat["seat"]
        selected_row = selected.get(number)
        physical = bluffs.physical_wolf(snapshot, seat)
        if not physical and selected_row is None:
            continue
        decision = "yes" if selected_row is not None else "no"
        note = selected_row["note"] if selected_row else ""
        tentative = bool(selected_row is not None and "暂定" in note
                         and source_row.get("date") == "2026-10-06"
                         and source_row.get("game_number") == 2 and number == 12)
        is_unknown = bool(selected_row is not None and selected_row["manual_success"] is None)
        questions = [note] if tentative and note else []
        if is_unknown:
            questions.append("用户将成功结果保留为待定")
        old = old_by_seat.get(number, {})
        assessment = {
            "seat": number,
            "name": seat["name"],
            "physical_role": seat.get("role"),
            "decision": decision,
            "claimed_role": None,
            "claim_day": None,
            "actual_claim_day": None,
            "first_day_claim": None,
            "confidence": "high",
            "verification_status": "user_confirmed",
            "decision_note": (note or '用户人工复核确认悍跳。') if selected_row is not None else (
                '用户本局明确填写无人悍跳。' if not selected else '用户确认的本局悍跳名单未包含该座位。'),
            "evidence": deepcopy(old.get("evidence", [])),
            "review_questions": questions,
            "requires_user_review": tentative or is_unknown,
            "review_stage": "user_pending" if tentative or is_unknown else "reviewed",
            "manual_included": bool(selected_row is not None and not physical),
            "manual_source_sha256": source_sha256,
            "manual_review_id": review_id,
            "manual_game_note": game_note,
            "manual_note": note,
        }
        if selected_row is not None:
            assessment["manual_success"] = selected_row["manual_success"]
        output.append(assessment)
    return output


def _count_summary(payload: dict, games: list[dict], manual_reviewed_games: int) -> dict:
    from website.api import bluffs

    items = bluffs.review_items(games, payload)
    physical_count = sum(bluffs.physical_wolf(game, seat)
                         for game in games for seat in game.get("seats", []))
    yes = sum(item["decision"] == "yes" for item in items)
    no = sum(item["decision"] == "no" for item in items)
    uncertain = sum(item["decision"] == "uncertain" for item in items)
    successful = sum(item["decision"] == "yes" and item["success"] is True for item in items)
    pending = sum(bool(item["needs_review"]) for item in items)
    stats = deepcopy(payload.get("summary", {}))
    stats.update({
        "games_total": len(games),
        "games_assessed": len(payload.get("games", [])),
        "manual_reviewed_games": manual_reviewed_games,
        # Keep the legacy physical-wolf denominator stable; extra user-selected
        # seats are reported separately and still included in bluff totals.
        "wolf_appearances": physical_count,
        "manual_included_appearances": sum(bool(item.get("manual_included")) for item in items),
        "decisions": {"yes": yes, "no": no, "uncertain": uncertain},
        "successful_bluffs": successful,
        "pending": pending,
        "statistics_pending": sum(item["decision"] == "yes" and item["success"] is None for item in items),
        "assistant_pending": sum(bool(item["assistant_pending"]) for item in items),
        "games_pending": len({item["game_id"] for item in items if item["needs_review"]}),
        "audited_identified_bluffs": yes,
        "user_confirmed_records": sum(item["verification_status"] == "user_confirmed" for item in items),
    })
    return stats


def _change_record(item: dict, change: str, **extra: Any) -> dict:
    return {
        "change": change,
        "game_id": item["game_id"],
        "bvid": item.get("bvid"),
        "date": item.get("date"),
        "game_number": item.get("game_number"),
        "seat": item["seat"],
        "name": item["name"],
        "decision": item["decision"],
        "success": item["success"],
        "note": item.get("decision_note", ""),
        **extra,
    }


def build_payload(manual: dict, source: dict, games: list[dict], baseline: dict,
                  source_sha256: str) -> tuple[dict, dict]:
    """Convert explicit manual selections into the current S23 review payload.

    A row means an explicit bluff attempt; ``no_bluff`` means an explicit empty
    game. A review with neither is blank and keeps its baseline game record.
    The legacy ``reviewed`` flag is informational and does not revoke selections.
    """
    source_sha256 = _require_hash(source_sha256, "人工文件SHA-256")
    manual_by_bvid, source_by_bvid = _manual_games(manual, source)
    snapshots = _snapshot_by_bvid(games, source_by_bvid)
    baseline_by_id = _baseline_by_game(baseline)

    from website.api import bluffs

    result = deepcopy(baseline)
    result["schema_version"] = 1
    result["season"] = "S23"
    result["inference_version"] = f"S23-manual-20261029-{source_sha256[:12]}"
    result["manual_review"] = {
        "source_sha256": source_sha256,
        "reviewed_games": 0,
        "covered_games": 0,
        "total_games": len(source_by_bvid),
    }
    result_games = []
    changed_game_ids: set[str] = set()
    reviewed_games = 0
    no_bluff_games = 0
    selections_total = 0

    for bvid, source_row in source_by_bvid.items():
        manual_row = manual_by_bvid[bvid]
        game = snapshots[bvid]
        selected, explicit_no, game_note, _ = _review_selection(manual_row, source_row)
        filled = bool(selected) or explicit_no
        game_id = game.get("id", game.get("slug"))
        existing = baseline_by_id.get(game_id)
        if not filled:
            if existing is None:
                raise ManualReviewError(f"{bvid}人工复核为空且旧payload无记录，无法保持原值")
            result_games.append(deepcopy(existing))
            continue

        reviewed_games += 1
        selections_total += len(selected)
        no_bluff_games += int(explicit_no)
        if existing is None:
            existing = {
                "game_id": game_id,
                "bvid": bvid,
                "source_fingerprint": bluffs.source_fingerprint(game),
                "coverage": "first_day_video_and_transcript",
            }
        else:
            existing = deepcopy(existing)
        existing["game_id"] = game_id
        existing["bvid"] = bvid
        existing["source_fingerprint"] = bluffs.source_fingerprint(game)
        existing["assessments"] = _make_assessments(
            game, existing, selected, source_row["review_id"], source_sha256, game_note, source_row,
        )
        result_games.append(existing)
        changed_game_ids.add(game_id)

    result["games"] = result_games
    result["manual_review"]["reviewed_games"] = reviewed_games
    result["manual_review"]["covered_games"] = reviewed_games
    result["summary"] = _count_summary(result, games, reviewed_games)
    new_items = bluffs.review_items(games, result)
    old_items = bluffs.review_items(games, baseline)
    new_yes = {(item["game_id"], item["seat"]): item for item in new_items if item["decision"] == "yes"}
    old_yes = {(item["game_id"], item["seat"]): item for item in old_items if item["decision"] == "yes"}
    added_keys = sorted(set(new_yes) - set(old_yes))
    removed_keys = sorted(set(old_yes) - set(new_yes))
    shared_keys = sorted(set(new_yes) & set(old_yes))
    added = [_change_record(new_yes[key], "added") for key in added_keys]
    removed = [_change_record(old_yes[key], "removed") for key in removed_keys]
    success_changes = []
    for key in shared_keys:
        old_item, new_item = old_yes[key], new_yes[key]
        if old_item["success"] != new_item["success"]:
            success_changes.append(_change_record(
                new_item, "success_changed", old_success=old_item["success"],
                new_success=new_item["success"],
            ))
    affected = {row["game_id"] for row in added + removed + success_changes}
    physical_count = sum(bluffs.physical_wolf(game, seat)
                         for game in games for seat in game.get("seats", []))
    manual_included_count = sum(bool(item.get("manual_included")) for item in new_items)
    report = {
        "season": "S23",
        "source_sha256": source_sha256,
        "database_written": False,
        "publication_written": False,
        "total_games": len(source_by_bvid),
        "manual_reviewed_games": reviewed_games,
        "no_bluff_games": no_bluff_games,
        "blank_games_preserved": len(source_by_bvid) - reviewed_games,
        "physical_wolf_appearances": physical_count,
        "manual_included_appearances": manual_included_count,
        "manual_selections": selections_total,
        "identified_bluffs": len(new_yes),
        "successes": sum(item["success"] is True for item in new_yes.values()),
        "failures": sum(item["success"] is False for item in new_yes.values()),
        "unknown_successes": sum(item["success"] is None for item in new_yes.values()),
        "pending_records": sum(bool(item["needs_review"]) for item in new_items),
        "added_count": len(added),
        "removed_count": len(removed),
        "success_change_count": len(success_changes),
        "affected_game_count": len(affected),
        "added": added,
        "removed": removed,
        "success_changes": success_changes,
        "affected_game_ids": sorted(affected),
        "expected_reviewed_game_ids": sorted(changed_game_ids),
    }
    return result, report


def _markdown(report: dict) -> str:
    state = '数据库已写入并读回验证。' if report.get('database_written') else '本报告描述本地准备结果；数据库未写入。'
    lines = [
        "# S23 悍跳人工复核应用差异",
        "",
        f"人工来源 SHA-256：`{report['source_sha256']}`。{state}",
        "",
        "## 汇总",
        "",
        f"- 明确复核 {report['manual_reviewed_games']}/{report['total_games']} 局；其中明确无人悍跳 {report['no_bluff_games']} 局。",
        f"- 本次结果：{report['identified_bluffs']} 次悍跳，成功 {report['successes']}、失败 {report['failures']}、成功待定 {report['unknown_successes']}。",
        f"- 物理狼人座位 {report['physical_wolf_appearances']}；用户额外明确纳入 {report['manual_included_appearances']} 个非物理狼座位。",
        f"- 相对旧payload：新增 {report['added_count']}、取消 {report['removed_count']}、成功结果变化 {report['success_change_count']}，影响 {report['affected_game_count']} 局。",
        *([f"- 总数变化：悍跳 {report['before']['identified_bluffs']} → {report['identified_bluffs']}；成功 {report['before']['successes']} → {report['successes']}。"] if report.get('before') else []),
        '- 成功数包含2026-10-06第二局12号Bobby的1次“暂定成功”；按用户本次选择计入，同时保留原备注与待复核标记。仅因狼王被放逐后能开枪并不满足原自动成功条件，本条作为人工结果保存，不推广为其他局的规则。',
        "- success=unknown或空值按人工待定保留；只有明确写有‘暂定’备注的当前记录额外保留该原备注并标为待用户复核。此规则仅对应本次人工文件，不扩展为全赛季规则。",
        "",
        "## 全部差异",
        "",
        '“取消”表示本次已改为不计悍跳；这些行的备注保留旧判断理由，仅用于对照，现行结果以用户复核为准。',
        '',
        "| 变化 | 对局 | 日期/局号 | 座位 | 选手 | 旧结果 | 新结果 | 备注 |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    rows = []
    for item in report["added"]:
        rows.append((item, "新增", "—", _success_text(item["success"])))
    for item in report["removed"]:
        rows.append((item, "取消", _success_text(item["success"]), "—"))
    for item in report["success_changes"]:
        rows.append((item, "成功变化", _success_text(item["old_success"]), _success_text(item["new_success"])))
    rows.sort(key=lambda row: (row[0].get("date") or "", row[0].get("game_number") or 0,
                               row[0]["seat"], row[1]))
    for item, label, old, new in rows:
        game_label = _md_cell(item.get("bvid") or item["game_id"])
        date_game = f"{item.get('date') or ''} 第{item.get('game_number') or '?'}局"
        lines.append(f"| {label} | {game_label} | {_md_cell(date_game)} | {item['seat']} | "
                     f"{_md_cell(item['name'])} | {old} | {new} | {_md_cell(item.get('note', ''))} |")
    if not rows:
        lines.append("| 无 | — | — | — | — | — | — | — |")
    lines.extend(["", "`success_changes` 表列出仍计为悍跳、但成功值发生变化的记录。"])
    if report.get('database_receipt'):
        lines.extend(['', '## 入库与验证', '',
            f"- 写入位置：`masters_web.bluff_review_publications/bluff_review_items/active_bluff_reviews`；发布ID `{report['database_receipt']['publication_id']}`。",
            '- 75局用户选择与成功结果逐项读回一致，共302条明细；重复应用未增加版本或明细。',
            '- 活动对局版本、全部对局快照和S22悍跳版本保持原值，旧S23悍跳版本保留。',
            f"- 整库备份回执：`{report['backup_receipt']}`。",
            '- 网页显示67次悍跳、10次成功及1条暂定项；两条混血儿记录和全部原备注已核对。'])
    return "\n".join(lines) + "\n"


def _success_text(value: object) -> str:
    return "成功" if value is True else "失败" if value is False else "待定"


def _md_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _read_json_bytes(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    try:
        parsed = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManualReviewError(f"JSON无法读取：{path}") from exc
    if not isinstance(parsed, dict):
        raise ManualReviewError(f"JSON顶层必须是对象：{path}")
    return parsed, data


def _read_active_s23() -> tuple[list[dict], dict]:
    from website.api import bluff_store, publisher

    conn = publisher._connect("masters_web")
    try:
        release = bluff_store._active_release(conn, "S23", lock=False)
        games = bluff_store._published_games(conn, release, "S23")
        baseline = bluff_store.read_review(conn, release["id"], "S23")
        return games, baseline
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual", type=Path, default=DEFAULT_MANUAL, help="用户人工复核JSON")
    parser.add_argument("--prepare", action="store_true", help="写本地资产、归档与差异报告；不写数据库")
    args = parser.parse_args(argv)

    from scripts import build_manual_bluff_review

    manual, raw_manual = _read_json_bytes(args.manual)
    source, _ = build_manual_bluff_review.build(season="S23")
    games, baseline = _read_active_s23()
    payload, report = build_payload(manual, source, games, baseline, _sha256(raw_manual))
    if args.prepare:
        old_asset = ASSET_PATH.read_bytes() if ASSET_PATH.is_file() else _canonical(baseline) + b"\n"
        old_sha = _sha256(old_asset)
        old_archive = ROOT / f"data/archive/S23_bluffs_before_manual_20261029_{old_sha[:12]}.json"
        user_archive = USER_ARCHIVE_DIR / f"manual_{report['source_sha256'][:12]}.json"
        for path, content in ((old_archive, old_asset), (user_archive, raw_manual)):
            if path.exists() and path.read_bytes() != content:
                raise ManualReviewError(f"归档目标已存在但内容不同：{path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        asset_bytes = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        report["archived_old_payload"] = old_archive.relative_to(ROOT).as_posix()
        report["archived_manual_source"] = user_archive.relative_to(ROOT).as_posix()
        report["asset_path"] = ASSET_PATH.relative_to(ROOT).as_posix()
        report["database_written"] = False
        report["publication_written"] = False
        ASSET_PATH.parent.mkdir(parents=True, exist_ok=True)
        ASSET_PATH.write_bytes(asset_bytes)
        REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
        REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        REPORT_MD.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {"added", "removed", "success_changes", "affected_game_ids",
                                     "expected_reviewed_game_ids"}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
