"""Validate and stage source-bound S21/S23 manual slot-review exports."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
PAGE = Path("data/manual_review/日夜待核槽位人工复核_20261030.html")
INPUT = Path("data/manual_review/feedback/日夜槽位复核结果_20261030.json")
REVIEW_DIR = Path("data/extractions/S21/game_reviews")
ARCHIVE_DIR = Path("data/extractions/shared/manual_slot_reviews")
FORMAT = "masters-pending-slot-review-v1"
SIDECAR_SCHEMA = "masters-manual-slot-review-sidecar-v1"

# These conclusions are specific to the currently authorized export.  Their
# interpretation must not silently carry over to a later export.
AUTHORIZED_RAW_SHA256 = "bd5682e7b865695a12aab10fff80d9a418b63baab69cf0fbe45e4a89ffb521c7"
FOLLOWUP_RAW_SHA256 = "664c727a5613a7b451e3c9f5b9f385fa217835d111d75e1cbb21b3cb9951037f"
TERMINAL_BEFORE_ACTION = {
    "DN-086": ("BV1UMPqzjEvH", 4, "mechanical_action"),
    "DN-087": ("BV1UMPqzjEvH", 4, "seer_check"),
    "DN-091": ("BV1Vsc9zfEJt", 4, "mechanical_action"),
    "DN-094": ("BV1FacCz5E9e", 3, "seer_check"),
}
WITHDRAWN = {"DN-084": ("BV1UMPqzjEvH", 2, "mechanical_action")}
FOLLOWUP_TERMINAL = {"DN-099": ("BV1w3AVzPE3R", 3, "mechanical_action")}


def _review_dir(season: str) -> Path:
    return Path(f"data/extractions/{season}/game_reviews")


class ReviewError(ValueError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _read_page(root: Path) -> dict:
    match = re.search(r'<script id="review-data" type="application/json">(.*?)</script>',
                      (root / PAGE).read_text(encoding="utf-8"), flags=re.S)
    if not match:
        raise ReviewError("原人工复核页缺少review-data")
    try:
        page = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ReviewError(f"原人工复核页数据不是合法JSON：{exc}") from exc
    payload = {key: value for key, value in page.items() if key != "source_fingerprint"}
    fingerprint = _sha(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    if page.get("format") != FORMAT or page.get("source_fingerprint") != fingerprint:
        raise ReviewError("原人工复核页格式或source_fingerprint校验失败")
    return page


def _read_sidecar(path: Path, bvid: str, root: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"{bvid}: slot.reviewed.json不可读：{exc}") from exc
    source_hash = value.get("source_sha256")
    archive_rel = (ARCHIVE_DIR / f"{source_hash}.json").as_posix()
    archive = root / archive_rel
    if (value.get("schema") != SIDECAR_SCHEMA or value.get("bvid") != bvid
            or not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash)
            or value.get("archive_path") != archive_rel or not archive.is_file()
            or _sha(archive.read_bytes()) != source_hash):
        raise ReviewError(f"{bvid}: sidecar原始JSON来源或SHA校验失败")
    return value


def _already_applied(source: dict, raw: bytes, root: Path) -> tuple[list[dict], dict] | None:
    games = source.get("games")
    if not isinstance(games, list) or not games:
        return None
    source_hash = _sha(raw)
    rows = []
    for game in games:
        if not isinstance(game, dict) or not isinstance(game.get("bvid"), str):
            return None
        path = root / _review_dir(game.get("season", "S21")) / game["bvid"] / "slot.reviewed.json"
        if not path.is_file():
            return None
        sidecar = _read_sidecar(path, game["bvid"], root)
        if sidecar.get("source_sha256") != source_hash or sidecar.get("source_game") != game:
            return None
        rows.append({"bvid": game["bvid"], "status": "already_applied",
                     "sidecar_path": path.relative_to(root).as_posix(), "sidecar": sidecar})
    if len({row["bvid"] for row in rows}) != len(rows):
        raise ReviewError("输入包含重复BVID")
    archive_path = (ARCHIVE_DIR / f"{source_hash}.json").as_posix()
    return rows, {"archive_path": archive_path, "source_sha256": source_hash,
                  "source_fingerprint": source.get("source_fingerprint"), "idempotent_replay": True}


def _current_dossier(root: Path, slug: str, season: str = "S21") -> tuple[Path, dict]:
    matches = []
    for path in (root / "data/games" / season).glob("*/dossier.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("slug") == slug:
            matches.append((path, value))
    if len(matches) != 1:
        raise ReviewError(f"{slug}: 当前{season} typed dossier匹配数应为1，实际{len(matches)}")
    return matches[0]


def _seats(rows: list[dict]) -> list[dict]:
    return [{key: seat.get(key) for key in ("seat", "name", "role")}
            for seat in sorted(rows, key=lambda row: row.get("seat", 0))]


def _event(dossier: dict, number: int, phase: str, slot: str) -> dict:
    round_ = next((row for row in dossier.get("rounds", []) if row.get("number") == number), None)
    event = next((row for row in round_.get(phase, []) if row.get("slot") == slot), None) if round_ else None
    if event is None:
        raise ReviewError(f"{dossier.get('slug')}: 缺少{number}/{phase}/{slot} typed slot")
    return event


def _view(event: dict) -> dict:
    return {key: event.get(key) for key in ("action", "actor", "targets", "result")}


def _actor(seats: list[dict], slot: str, before: dict, review_id: str) -> int | None:
    if before.get("actor") is not None:
        return before["actor"]
    if slot == "wolf_attack":
        return None  # A team action does not identify a unique ordinary wolf.
    roles = {"mechanical_action": ["机械狼"], "mechanical_day_skill": ["机械狼"],
             "seer_check": ["预言家", "通灵师"], "guard": ["守卫"]}.get(slot, [])
    matches = [seat["seat"] for seat in seats if seat.get("role") in roles]
    if len(matches) != 1:
        raise ReviewError(f"{review_id}: {slot}行动者不能从已核身份唯一确定")
    return matches[0]


def _result(dossier: dict, slot: str, result, *, action: str | None = None):
    if slot == "mechanical_action" and action == "learn":
        from board_config import load_template
        forms = load_template("mechanical_wolf_seer")["mechanical_forms"]
        matches = [name for name, spec in forms.items() if spec.get("learned_from") == result]
        if len(matches) == 1:
            return matches[0]
    if slot == "seer_check" and dossier.get("board") != "s21_mechanical_wolf_seer":
        return {"狼人": "werewolf", "平民": "good"}.get(result, result)
    return result


def _review_slot(game: dict, question: dict, review: dict, raw_hash: str,
                 seats: list[dict], dossier: dict) -> dict:
    review_id = review["id"]
    number, phase = review.get("round"), review.get("phase")
    if (number, phase) != (question.get("round"), question.get("phase")):
        raise ReviewError(f"{review_id}: 输入轮次/阶段与原复核页不匹配")
    raw_slots = review.get("slots")
    if not isinstance(raw_slots, list):
        raise ReviewError(f"{review_id}: slots必须为数组")
    normalized = []
    followup = raw_hash == FOLLOWUP_RAW_SHA256
    special_terminal = (FOLLOWUP_TERMINAL if followup else TERMINAL_BEFORE_ACTION).get(review_id)
    withdrawn = WITHDRAWN.get(review_id) if not followup else None
    if (special_terminal or withdrawn) and raw_hash not in {AUTHORIZED_RAW_SHA256, FOLLOWUP_RAW_SHA256}:
        raise ReviewError(f"{review_id}: 本次特例仅适用于已授权的原始JSON SHA")
    expected_coordinate = special_terminal or withdrawn
    if expected_coordinate and (game["bvid"], number, question.get("phase")) != (
            expected_coordinate[0], expected_coordinate[1], "night"):
        raise ReviewError(f"{review_id}: 本次人工复核坐标不匹配")
    if (special_terminal and not raw_slots and review_id != "DN-087") or (withdrawn and not raw_slots):
        raise ReviewError(f"{review_id}: 本次授权复核缺少对应slot")
    for raw_slot in raw_slots:
        code = raw_slot.get("slot") if isinstance(raw_slot, dict) else None
        if expected_coordinate and code != expected_coordinate[2]:
            raise ReviewError(f"{review_id}: 本次人工复核slot不匹配")
        page_slot = next((row for row in question.get("slots", []) if row.get("code") == code), None)
        if page_slot is None or raw_slot.get("before") != page_slot.get("before"):
            raise ReviewError(f"{review_id}: slot/before与原人工复核页不匹配")
        current = _event(dossier, number, phase, code)
        before = page_slot["before"]
        changes = raw_slot.get("changes")
        if not isinstance(changes, dict):
            raise ReviewError(f"{review_id}: changes必须为对象")
        if withdrawn and (game["bvid"], number, code) == withdrawn:
            if _view(current) != before:
                raise ReviewError(f"{review_id}: before与当前typed值不匹配")
            normalized.append({"id": review_id, "round": number, "phase": phase, "slot": code,
                               "classification": "withdrawn_by_user_correction", "note": review.get("note", ""),
                               "before": before, "typed": None, "raw_review": review,
                               "disposition": "retain approved first-night learning; leave this slot unchanged"})
            continue
        if special_terminal and (game["bvid"], number, code) == special_terminal:
            typed = {"action": "unavailable", "actor": _actor(seats, code, before, review_id),
                     "targets": [], "result": None}
            classification = "game_ended_before_action"
        elif followup and review_id == "DN-102":
            if (game["bvid"], number, phase, code) != ("BV1roX7BQEau", 4, "day", "mechanical_day_skill"):
                raise ReviewError(f"{review_id}: 机械通灵白天技能复核坐标不匹配")
            typed = {"action": "unavailable", "actor": _actor(seats, code, before, review_id),
                     "targets": [], "result": None}
            classification = "mechanical_form_has_no_day_skill"
        elif changes:
            action = changes.get("action")
            if not isinstance(action, str) or action == "unknown":
                classification, typed = "unconfirmed", None
            else:
                targets, result = changes.get("targets", []), changes.get("result")
                if (not isinstance(targets, list) or any(type(target) is not int or not 1 <= target <= 12 for target in targets)
                        or result is not None and not isinstance(result, str)):
                    raise ReviewError(f"{review_id}: targets/result格式不合法")
                actor = changes.get("actor")
                typed = {"action": action, "actor": actor if actor is not None else _actor(seats, code, before, review_id),
                         "targets": targets, "result": _result(dossier, code, result, action=action)}
                classification = "confirmed"
        else:
            classification, typed = "unconfirmed", None
        already_confirmed = followup and game["season"] == "S23" and _view(current) == typed
        if followup and review_id == "DN-224":
            if (game["bvid"], number, phase, code) != ("BV1saaT6jEyK", 3, "night", "wolf_attack"):
                raise ReviewError(f"{review_id}: 九尾狐接刀复核坐标不匹配")
            fox = _event(dossier, number, phase, "nine_tail_kill")
            if (_view(current) != {"action": "unavailable", "actor": None, "targets": [], "result": None}
                    or fox.get("action") != "kill" or fox.get("actor") != 9
                    or fox.get("targets") != typed["targets"]):
                raise ReviewError(f"{review_id}: 当前九尾狐接刀与用户确认目标不匹配")
            code, typed = "nine_tail_kill", _view(fox)
            classification, already_confirmed = "confirmed_existing_nine_tail_takeover", True
        if _view(current) != before and not already_confirmed:
            raise ReviewError(f"{review_id}: before与当前typed值不匹配")
        normalized.append({"id": review_id, "round": number, "phase": phase, "slot": code,
                           "classification": classification, "note": review.get("note", ""),
                           "before": before, "typed": typed, "raw_review": review})

    # DN-087 has no exported slot change; its preserved, explicitly supplied
    # end-of-game note is the authorized basis for this unavailable outcome.
    if special_terminal and not raw_slots:
        bvid, round_number, code = special_terminal
        if (game["bvid"], number, phase) != (bvid, round_number, "night"):
            raise ReviewError(f"{review_id}: 终局复核坐标不匹配")
        page_slot = next((row for row in question.get("slots", []) if row.get("code") == code), None)
        if page_slot is None or _view(_event(dossier, number, phase, code)) != page_slot.get("before"):
            raise ReviewError(f"{review_id}: 终局slot与原页/当前typed值不匹配")
        normalized.append({"id": review_id, "round": number, "phase": phase, "slot": code,
                           "classification": "game_ended_before_action", "note": review.get("note", ""),
                           "before": page_slot["before"],
                           "typed": {"action": "unavailable", "actor": _actor(seats, code, page_slot["before"], review_id),
                                     "targets": [], "result": None}, "raw_review": review})
    return normalized


def build_plan(input_path: Path | None = None, *, root: Path = ROOT) -> tuple[list[dict], dict, bytes]:
    input_path = input_path or INPUT
    raw = (input_path if input_path.is_absolute() else root / input_path).read_bytes()
    try:
        source = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewError(f"输入JSON不可读：{exc}") from exc
    if not isinstance(source, dict) or source.get("format") != FORMAT:
        raise ReviewError("输入format不匹配")
    replay = _already_applied(source, raw, root)
    if replay:
        plan, summary = replay
        summary["input_path"] = input_path.as_posix()
        return plan, summary, raw

    page = _read_page(root)
    if source.get("source_fingerprint") != page.get("source_fingerprint"):
        raise ReviewError("输入source_fingerprint与原人工复核页不匹配")
    games = source.get("games")
    if not isinstance(games, list) or not games:
        raise ReviewError("输入games必须是非空数组")
    page_games = {row.get("bvid"): row for row in page.get("games", [])}
    seen_games, seen_reviews, grouped = set(), set(), []
    for game in games:
        if not isinstance(game, dict) or not isinstance(game.get("bvid"), str):
            raise ReviewError("输入game缺少字符串BVID")
        bvid = game["bvid"]
        if bvid in seen_games or bvid not in page_games:
            raise ReviewError(f"重复BVID或原复核页没有此BV：{bvid}")
        seen_games.add(bvid)
        page_game = page_games[bvid]
        for key in ("id", "season", "date", "game_number", "dossier_sha256"):
            if game.get(key) != page_game.get(key):
                raise ReviewError(f"{bvid}: {key}与原复核页不匹配")
        if game.get("season") not in {"S21", "S23"} or not isinstance(game.get("dossier_sha256"), str):
            raise ReviewError(f"{bvid}: 仅支持绑定完整dossier_sha256的S21/S23复核")
        seats = game.get("seats")
        if (not isinstance(seats, list) or len(seats) != 12 or any(not isinstance(row, dict) for row in seats)
                or sorted(row.get("seat") for row in seats) != list(range(1, 13))):
            raise ReviewError(f"{bvid}: 需要完整的12席身份")
        if _seats(seats) != _seats(page_game.get("seats", [])):
            raise ReviewError(f"{bvid}: 姓名/身份与原复核页不匹配")
        path, dossier = _current_dossier(root, game["id"], game["season"])
        # This exact S23 export predates separately confirmed knife corrections.
        # Identity and every reviewed slot are still checked below; only the
        # explicitly matching current action / fox takeover is accepted above.
        scoped_followup = _sha(raw) == FOLLOWUP_RAW_SHA256 and game["season"] == "S23"
        if _sha(path.read_bytes()) != game["dossier_sha256"] and not scoped_followup:
            raise ReviewError(f"{bvid}: dossier_sha256与当前typed档案不匹配")
        if _seats(dossier.get("seats", [])) != _seats(seats):
            raise ReviewError(f"{bvid}: 当前typed档案12席身份不匹配")
        questions = {row.get("id"): row for row in page_game.get("questions", [])}
        normalized = []
        for review in game.get("reviews", []):
            if not isinstance(review, dict) or not isinstance(review.get("id"), str):
                raise ReviewError(f"{bvid}: review缺少编号")
            review_id = review["id"]
            question = questions.get(review_id)
            if review_id in seen_reviews or question is None:
                raise ReviewError(f"{bvid}: 重复编号或原复核页没有此项目：{review_id}")
            seen_reviews.add(review_id)
            normalized.extend(_review_slot(game, question, review, _sha(raw), seats, dossier))
        special = [row for row in normalized if row["classification"] == "game_ended_before_action"]
        if special:
            derivations = json.loads((path.parent / "rule_derivations.json").read_text(encoding="utf-8"))
            terminal = derivations.get("terminal")
            if any(not terminal or (terminal.get("round"), terminal.get("phase")) != (row["round"], "night")
                   for row in special):
                raise ReviewError(f"{bvid}: game_ended_before_action与rule_derivations.terminal不同轮")
        grouped.append({"bvid": bvid, "game": game, "normalized": normalized})

    archive_path = (ARCHIVE_DIR / f"{_sha(raw)}.json").as_posix()
    plan = []
    for row in grouped:
        bvid, game = row["bvid"], row["game"]
        relative = (_review_dir(game["season"]) / bvid / "slot.reviewed.json").as_posix()
        existing = root / relative
        prior = None
        if existing.is_file():
            prior = _read_sidecar(existing, bvid, root)
        sidecar = {"schema": SIDECAR_SCHEMA, "season": game["season"], "bvid": bvid,
                   "game_slug": game["id"], "source_path": input_path.as_posix(),
                   "source_sha256": _sha(raw), "source_fingerprint": source["source_fingerprint"],
                   "archive_path": archive_path, "source_game": game, "reviews": row["normalized"]}
        if prior and prior.get("source_sha256") != _sha(raw):
            coordinates = {(r["round"], r["phase"], r["slot"]) for r in row["normalized"]}
            sidecar["previous_review"] = prior
            sidecar["reviews"] = [r for r in prior["reviews"]
                                  if (r["round"], r["phase"], r["slot"]) not in coordinates] + row["normalized"]
        plan.append({"bvid": bvid, "status": "ready", "sidecar_path": relative, "sidecar": sidecar})
    return plan, {"archive_path": archive_path, "source_sha256": _sha(raw),
                  "source_fingerprint": source["source_fingerprint"], "input_path": input_path.as_posix()}, raw


def apply_plan(plan: list[dict], summary: dict, raw: bytes, *, root: Path = ROOT) -> None:
    archive = root / summary["archive_path"]
    if archive.exists() and archive.read_bytes() != raw:
        raise ReviewError(f"归档目标已存在且内容不匹配：{summary['archive_path']}")
    writes = [(archive, raw)] + [(root / row["sidecar_path"], _json_bytes(row["sidecar"])) for row in plan]
    for path, content in writes:
        if path.is_file() and path.read_bytes() == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)


def load_manual_slot_review(bvid: str, *, root: Path = ROOT, season: str = "S21") -> dict | None:
    path = root / _review_dir(season) / bvid / "slot.reviewed.json"
    return _read_sidecar(path, bvid, root) if path.is_file() else None


def apply_manual_slot_review(bvid: str, rounds: list[dict], *, root: Path = ROOT, season: str = "S21") -> dict | None:
    sidecar = load_manual_slot_review(bvid, root=root, season=season)
    if sidecar is None:
        return None
    seen = set()
    for review in sidecar.get("reviews", []):
        if review.get("classification") == "withdrawn_by_user_correction" or review.get("typed") is None:
            continue
        key = (review.get("round"), review.get("phase"), review.get("slot"))
        if key in seen:
            raise ReviewError(f"{bvid}: manual slot坐标重复：{key}")
        seen.add(key)
        number, phase, slot = key
        event = _event({"slug": bvid, "rounds": rounds}, number, phase, slot)
        typed = review["typed"]
        if set(typed) != {"action", "actor", "targets", "result"}:
            raise ReviewError(f"{bvid}/{review.get('id')}: typed slot字段错误")
        event.update(typed)
    return sidecar


def validate_terminal_reviews(sidecar: dict | None, derivations: dict, bvid: str) -> None:
    if not sidecar:
        return
    terminal = derivations.get("terminal")
    for review in sidecar.get("reviews", []):
        if (review.get("classification") == "game_ended_before_action"
                and (not terminal or (terminal.get("round"), terminal.get("phase")) != (review.get("round"), "night"))):
            raise ReviewError(f"{bvid}/{review.get('id')}: rule_derivations.terminal必须是同轮night")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--apply", action="store_true", help="全部校验通过后写sidecar并归档原JSON")
    args = parser.parse_args(argv)
    plan, summary, raw = build_plan(args.input)
    if args.apply:
        apply_plan(plan, summary, raw)
    reviews = [review for row in plan for review in row["sidecar"]["reviews"]]
    input_ids = {review["id"] for row in plan for review in row["sidecar"]["source_game"]["reviews"]}
    summary.update({"file_write": args.apply, "games_checked": len(plan),
                    "reviews_checked": len(input_ids),
                    "reviews_retained": len({review["id"] for review in reviews} - input_ids),
                    "reviews_applied": len({review["id"] for review in reviews if review["typed"] is not None}),
                    "reviews_withdrawn": sum(review["classification"] == "withdrawn_by_user_correction" for review in reviews),
                    "slots_applied": sum(review["typed"] is not None for review in reviews),
                    "terminal_unavailable": sum(review["classification"] == "game_ended_before_action" for review in reviews),
                    "sidecars": [row["sidecar_path"] for row in plan]})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
