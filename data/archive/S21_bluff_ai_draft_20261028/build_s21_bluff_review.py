"""Build local S21 bluff review progress and detail exports from source-bound assessments."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from website.api import bluffs  # noqa: E402
from website.api.analytics import effective_faction  # noqa: E402


INDEX = Path("data/reports/S21_文字与截图时点索引.json")
ASSESSMENTS = Path("data/extractions/S21/bluff_review/assessments")
PROGRESS_JSON = Path("data/reports/S21_悍跳核实进度.json")
DETAIL_JSON = Path("data/exports/S21_悍跳核实明细.json")
DETAIL_MD = Path("data/exports/S21_悍跳核实明细.md")
INFO_ROLES = {"预言家", "通灵师"}
STANDARD_FACTIONS = {
    "狼人": "werewolf",
    "平民": "good",
    "预言家": "good",
    "女巫": "good",
    "猎人": "good",
    "守卫": "good",
    "通灵师": "good",
}
EXPECTED_SCHEMA = 1


class BuildError(ValueError):
    """S21 source binding or a manual assessment is invalid."""


def _read_json(root: Path, relative: str | Path) -> Any:
    try:
        return json.loads((root / relative).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"无法读取JSON：{relative}: {exc}") from exc


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise BuildError(f"无法读取来源文件：{path}") from exc


def _safe_data_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    data_root = (root / "data").resolve()
    if not path.is_relative_to(data_root) or not path.is_file():
        raise BuildError(f"来源文件缺失或不在data目录：{relative}")
    return path


def _scope_entries(root: Path, bvid: str | None) -> tuple[list[dict], int]:
    from scripts import import_s21_formal

    index = _read_json(root, INDEX)
    indexed = index.get("entries")
    if not isinstance(indexed, list):
        raise BuildError("S21媒体索引缺少entries")
    try:
        entries = import_s21_formal.selected_entries(root=root, bvids=[bvid] if bvid else None)
    except Exception as exc:
        raise BuildError(f"无法确定S21当前媒体范围：{exc}") from exc
    expected_count = len(import_s21_formal.selected_entries(root=root))
    by_bvid = {row.get("bvid"): row for row in indexed}
    if len(by_bvid) != len(indexed):
        raise BuildError("S21媒体索引存在重复BVID")
    if any(by_bvid.get(row.get("bvid")) != row for row in entries):
        raise BuildError("已选媒体条目与S21索引不一致")
    return entries, expected_count


def _source_bundle(root: Path, entry: dict, approvals: dict) -> dict:
    from scripts import import_s21_formal

    bvid = entry["bvid"]
    try:
        identity, phase, binding = import_s21_formal.approved_identity_and_phase(
            entry, root=root, approvals=approvals,
        )
        transcript_relative = phase["source"]["selected_path"]
        transcript_path = _safe_data_path(root, transcript_relative)
        transcript = _read_json(root, transcript_relative)
        transcript_sha = _sha256(transcript_path)
        if transcript_sha != phase["source"].get("selected_sha256"):
            raise BuildError(f"{bvid}: selected transcript与phase reviewed哈希不一致")
        if (transcript.get("bvid") != bvid
                or Path(transcript_relative).as_posix() != entry.get("transcript_selected_path")):
            raise BuildError(f"{bvid}: selected transcript的BV或索引路径不匹配")
        if not isinstance(transcript.get("segments"), list):
            raise BuildError(f"{bvid}: selected transcript缺少segments")
        if identity.get("bvid") != bvid or phase.get("bvid") != bvid:
            raise BuildError(f"{bvid}: identity/phase来源绑定不匹配")
        identity_relative = binding["identity"]
        phase_relative = binding["phase"]
        identity_sha = _sha256(_safe_data_path(root, identity_relative))
        phase_sha = _sha256(_safe_data_path(root, phase_relative))
        if phase.get("identity_source", {}).get("sha256") != identity_sha:
            raise BuildError(f"{bvid}: phase绑定的identity reviewed哈希不匹配")
        record = import_s21_formal.build_records(entry, identity, phase, binding, root=root)
        game = record["dossier"]
        game["id"] = record["slug"]
        game["voting"] = record["voting"]
        game["source"] = {"bvid": bvid, "path": transcript_relative, "sha256": transcript_sha}
        return {
            "entry": entry,
            "identity": identity,
            "phase": phase,
            "transcript": transcript,
            "game": game,
            "identity_path": Path(identity_relative).as_posix(),
            "identity_sha256": identity_sha,
            "phase_path": Path(phase_relative).as_posix(),
            "phase_sha256": phase_sha,
            "transcript_path": Path(transcript_relative).as_posix(),
            "transcript_sha256": transcript_sha,
            "original_source_path": phase["source"]["original_path"],
            "original_source_sha256": phase["source"]["original_sha256"],
        }
    except BuildError:
        raise
    except Exception as exc:
        raise BuildError(f"{bvid}: 已核S21来源无效：{exc}") from exc


def _candidate_seats(identity: dict) -> list[dict]:
    """Use the current bluff contract's role vocabulary, retaining unknown factions."""
    return sorted(
        [row for row in identity.get("seats", []) if row.get("role") in bluffs.WOLF_ROLES],
        key=lambda row: row["seat"],
    )


def _completion_flags(counts: dict[str, int], faction_unresolved: int,
                     success_excluded: int) -> tuple[bool, bool]:
    assessment_coverage_complete = counts["missing"] == 0
    complete = (assessment_coverage_complete and counts["uncertain"] == 0
                and faction_unresolved == 0 and success_excluded == 0)
    return complete, assessment_coverage_complete


def _literal_evidence(transcript: dict, raw: Any, context: str) -> dict:
    if not isinstance(raw, dict):
        raise BuildError(f"{context}: evidence必须为对象")
    indices = raw.get("segment_indices")
    segments = {row.get("index"): row for row in transcript["segments"] if type(row.get("index")) is int}
    if (not isinstance(indices, list) or not indices
            or any(type(index) is not int for index in indices)
            or indices != sorted(set(indices))
            or any(index not in segments for index in indices)):
        raise BuildError(f"{context}: selected transcript片段索引无效或未排序")
    rows = [segments[index] for index in indices]
    start_ms, end_ms = rows[0].get("start_ms"), rows[-1].get("end_ms")
    quote = "\n".join(row.get("text", "") for row in rows)
    if (type(start_ms) is not int or type(end_ms) is not int or end_ms < start_ms
            or raw.get("start_ms") != start_ms or raw.get("end_ms") != end_ms
            or raw.get("quote") != quote or not quote):
        raise BuildError(f"{context}: quote或时间与selected transcript的literal segments不一致")
    return {
        "segment_indices": indices,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "quote": quote,
    }


def _validate_ranges(value: Any, bvid: str, seat_number: int) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise BuildError(f"{bvid}:{seat_number} 缺少reviewed_ranges")
    result = []
    for row in value:
        if (not isinstance(row, dict) or type(row.get("start_ms")) is not int
                or type(row.get("end_ms")) is not int or row["start_ms"] < 0
                or row["end_ms"] < row["start_ms"] or not isinstance(row.get("phase"), str)
                or not row["phase"].strip() or type(row.get("complete")) is not bool):
            raise BuildError(f"{bvid}:{seat_number} reviewed_range格式无效")
        result.append({key: row[key] for key in ("start_ms", "end_ms", "phase", "complete")})
    return result


def _load_assessments(root: Path, bundle: dict) -> tuple[dict[int, dict], bool]:
    entry, identity, transcript = bundle["entry"], bundle["identity"], bundle["transcript"]
    bvid = entry["bvid"]
    candidates = _candidate_seats(identity)
    path = root / ASSESSMENTS / f"{bvid}.json"
    if not path.is_file():
        return {}, False
    payload = _read_json(root, ASSESSMENTS / f"{bvid}.json")
    expected_bindings = {
        "schema_version": EXPECTED_SCHEMA,
        "season": "S21",
        "bvid": bvid,
        "cid": entry["cid"],
        "page": entry["page"],
        "identity_reviewed_sha256": bundle["identity_sha256"],
        "phase_reviewed_sha256": bundle["phase_sha256"],
        "transcript_selected_sha256": bundle["transcript_sha256"],
    }
    for key, expected in expected_bindings.items():
        if payload.get(key) != expected:
            raise BuildError(f"{bvid}: assessments.{key}与当前来源不匹配")
    # The selected transcript digest binds its embedded original source path/hash.
    # These optional echoes are accepted for reviewer readability, and checked if present.
    for key, expected in (("original_source_path", bundle["original_source_path"]),
                          ("original_source_sha256", bundle["original_source_sha256"])):
        if key in payload and payload[key] != expected:
            raise BuildError(f"{bvid}: assessments.{key}与phase reviewed来源不匹配")
    rows = payload.get("assessments")
    if not isinstance(rows, list):
        raise BuildError(f"{bvid}: assessments必须为数组")
    by_seat = {seat["seat"]: seat for seat in candidates}
    output: dict[int, dict] = {}
    for raw in rows:
        if not isinstance(raw, dict) or type(raw.get("seat")) is not int:
            raise BuildError(f"{bvid}: assessment缺少有效seat")
        number = raw["seat"]
        if number not in by_seat:
            raise BuildError(f"{bvid}:{number} 不是当前bluffs.WOLF_ROLES物理角色范围")
        if number in output:
            raise BuildError(f"{bvid}:{number} assessment重复")
        source_seat = by_seat[number]
        if raw.get("name") != source_seat.get("name") or raw.get("physical_role") != source_seat.get("role"):
            raise BuildError(f"{bvid}:{number} assessment姓名或物理底牌与identity.reviewed不匹配")
        decision = raw.get("decision")
        if decision not in {"yes", "no", "uncertain"}:
            raise BuildError(f"{bvid}:{number} decision必须是yes/no/uncertain")
        note = raw.get("decision_note")
        if not isinstance(note, str) or not note.strip():
            raise BuildError(f"{bvid}:{number} 缺少decision_note")
        claim_day = raw.get("claim_day")
        if claim_day is not None and (type(claim_day) is not int or claim_day < 1):
            raise BuildError(f"{bvid}:{number} claim_day必须为正整数或null")
        claimed_role = raw.get("claimed_role")
        if decision == "yes" and (claimed_role not in INFO_ROLES or claim_day is None):
            raise BuildError(f"{bvid}:{number} yes必须明确claimed_role与claim_day")
        if decision != "yes" and claimed_role is not None and claimed_role not in INFO_ROLES:
            raise BuildError(f"{bvid}:{number} claimed_role无效")
        evidence_rows = raw.get("evidence")
        if not isinstance(evidence_rows, list):
            raise BuildError(f"{bvid}:{number} evidence必须为数组")
        evidence = [_literal_evidence(transcript, item, f"{bvid}:{number} evidence")
                    for item in evidence_rows]
        if decision == "yes" and not evidence:
            raise BuildError(f"{bvid}:{number} yes必须有literal source evidence")
        faction = raw.get("faction")
        if faction not in (None, "werewolf"):
            raise BuildError(f"{bvid}:{number} faction仅支持werewolf或null")
        faction_evidence_raw = raw.get("faction_evidence", [])
        if not isinstance(faction_evidence_raw, list):
            raise BuildError(f"{bvid}:{number} faction_evidence必须为数组")
        faction_evidence = [_literal_evidence(transcript, item, f"{bvid}:{number} faction_evidence")
                            for item in faction_evidence_raw]
        if faction == "werewolf" and not faction_evidence:
            raise BuildError(f"{bvid}:{number} 手工确认wolf faction须引用literal source evidence")
        gaps = raw.get("explicit_gaps")
        if not isinstance(gaps, list) or any(not isinstance(item, str) or not item.strip() for item in gaps):
            raise BuildError(f"{bvid}:{number} explicit_gaps必须为字符串数组")
        ranges = _validate_ranges(raw.get("reviewed_ranges"), bvid, number)
        output[number] = {
            "seat": number,
            "name": source_seat["name"],
            "physical_role": source_seat["role"],
            "decision": decision,
            "claimed_role": claimed_role,
            "claim_day": claim_day,
            "decision_note": note.strip(),
            "evidence": evidence,
            "reviewed_ranges": ranges,
            "explicit_gaps": gaps,
            "faction_override": faction,
            "faction_evidence": faction_evidence,
        }
    return output, True


def _reviewed_game(bundle: dict, assessments: dict[int, dict]) -> dict:
    game = copy.deepcopy(bundle["game"])
    board = game.get("board")
    for seat in game.get("seats", []):
        role = seat.get("role")
        # S21 identity proves the basic wolf and village role factions. The only
        # special-card faction map used automatically is the S21-verified Guile card.
        if role in STANDARD_FACTIONS:
            seat["faction"] = STANDARD_FACTIONS[role]
        if board == "s21_guile_realm":
            try:
                from scripts import import_s21_formal
                rules = _read_json(bundle["root"], "config/S21_formal_rules.json")
                faction = import_s21_formal.role_faction(board, role, rules)
                if faction:
                    seat["faction"] = faction
            except Exception as exc:
                raise BuildError(f"{bundle['entry']['bvid']}: 无法应用S21诡术之境官方阵营卡：{exc}") from exc
        assessment = assessments.get(seat["seat"])
        if assessment and assessment.get("faction_override") == "werewolf":
            seat["faction"] = "werewolf"
    return game


def _assessment_rows(bundle: dict, assessment_map: dict[int, dict], reviewed_game: dict,
                     contract_items: list[dict]) -> list[dict]:
    candidates = _candidate_seats(bundle["identity"])
    item_by_seat = {item["seat"]: item for item in contract_items}
    game_id = reviewed_game["id"]
    output = []
    for candidate in candidates:
        number = candidate["seat"]
        assessment = assessment_map.get(number)
        actual_seat = next(row for row in reviewed_game["seats"] if row["seat"] == number)
        faction = effective_faction(reviewed_game, actual_seat)
        if assessment is None:
            output.append({
                "seat": number, "name": candidate.get("name"), "physical_role": candidate.get("role"),
                "faction": faction, "decision": None, "claimed_role": None, "claim_day": None,
                "success": None, "success_reasons": [], "success_questions": [],
                "decision_note": "缺少语义核实记录；未自动判为no。",
                "evidence": [], "faction_evidence": [], "reviewed_ranges": [],
                "explicit_gaps": ["缺少assessment记录"], "assessment_status": "missing",
            })
            continue
        if assessment["decision"] == "yes" and faction != "werewolf":
            raise BuildError(f"{bundle['entry']['bvid']}:{number} 标记yes但S21狼人阵营未由来源证实")
        contract_item = item_by_seat.get(number)
        success = contract_item.get("success") if contract_item else None
        success_reasons = contract_item.get("success_reasons", []) if contract_item else []
        success_questions = contract_item.get("review_questions", []) if contract_item else []
        output.append({
            "seat": number, "name": candidate.get("name"), "physical_role": candidate.get("role"),
            "faction": faction, "decision": assessment["decision"],
            "claimed_role": assessment["claimed_role"], "claim_day": assessment["claim_day"],
            "success": success, "success_reasons": success_reasons,
            "success_questions": success_questions, "decision_note": assessment["decision_note"],
            "evidence": assessment["evidence"], "faction_evidence": assessment["faction_evidence"],
            "reviewed_ranges": assessment["reviewed_ranges"],
            "explicit_gaps": assessment["explicit_gaps"],
            "assessment_status": "reviewed",
        })
    return output


def _md_escape(value: Any) -> str:
    return str(value if value is not None else "—").replace("|", "\\|").replace("\n", "<br>")


def build(root: Path = ROOT, bvid: str | None = None) -> tuple[dict, dict, str]:
    entries, full_scope_count = _scope_entries(root, bvid)
    from scripts import import_s21_formal

    try:
        approvals = _read_json(root, import_s21_formal.PHASE_AUDIT)["items"]
    except (KeyError, TypeError) as exc:
        raise BuildError("S21 phase approval索引无效") from exc
    if not isinstance(approvals, dict):
        raise BuildError("S21 phase approval索引必须为对象")

    bundles = []
    for entry in entries:
        bundle = _source_bundle(root, entry, approvals)
        bundle["root"] = root
        assessment_map, file_present = _load_assessments(root, bundle)
        bundle["assessments"] = assessment_map
        bundle["assessment_file_present"] = file_present
        reviewed_game = _reviewed_game(bundle, assessment_map)
        bundle["reviewed_game"] = reviewed_game
        bundles.append(bundle)

    # Pass confirmed wolf seats through the established website contract. Unknown
    # special-role factions remain visible in detail, but do not enter its denominator.
    contract_games = [bundle["reviewed_game"] for bundle in bundles]
    payload_games = []
    for bundle in bundles:
        game = bundle["reviewed_game"]
        assessments = []
        for seat in game["seats"]:
            if not bluffs.physical_wolf(game, seat):
                continue
            source_assessment = bundle["assessments"].get(seat["seat"])
            if source_assessment is None:
                continue
            assessments.append({
                "seat": seat["seat"], "name": seat.get("name"), "physical_role": seat.get("role"),
                "decision": source_assessment["decision"],
                "claimed_role": source_assessment["claimed_role"],
                "claim_day": source_assessment["claim_day"],
                "decision_note": source_assessment["decision_note"],
                "evidence": [{"kind": "source", "text": row["quote"],
                              "start_ms": row["start_ms"], "end_ms": row["end_ms"]}
                             for row in source_assessment["evidence"]],
            })
        payload_games.append({
            "game_id": game["id"], "bvid": bundle["entry"]["bvid"],
            "source_fingerprint": bluffs.source_fingerprint(game), "assessments": assessments,
        })
    payload = {"games": payload_games}
    contract_items = bluffs.review_items(contract_games, payload)
    contract_stats = bluffs.aggregate_bluffs(contract_games, payload)
    contract_by_game: dict[str, list[dict]] = {}
    for item in contract_items:
        contract_by_game.setdefault(item["game_id"], []).append(item)

    media_rows = []
    counts = {"yes": 0, "no": 0, "uncertain": 0, "missing": 0}
    faction_unresolved = 0
    wolf_appearances = 0
    identified = 0
    success_num = success_den = success_excluded = 0
    for bundle in bundles:
        game = bundle["reviewed_game"]
        rows = _assessment_rows(bundle, bundle["assessments"], game,
                                contract_by_game.get(game["id"], []))
        for row in rows:
            if row["assessment_status"] == "missing":
                counts["missing"] += 1
            else:
                counts[row["decision"]] += 1
            if row["faction"] != "werewolf":
                faction_unresolved += 1
            else:
                wolf_appearances += 1
            if row["decision"] == "yes" and row["faction"] == "werewolf":
                identified += 1
                if row["success"] is None:
                    success_excluded += 1
                else:
                    success_den += 1
                    success_num += int(row["success"] is True)
        media_rows.append({
            "bvid": bundle["entry"]["bvid"], "cid": bundle["entry"]["cid"],
            "page": bundle["entry"]["page"], "title": bundle["entry"].get("title"),
            "source_paths": {
                "identity_reviewed": bundle["identity_path"],
                "phase_reviewed": bundle["phase_path"],
                "transcript_selected": bundle["transcript_path"],
                "original_transcript": bundle["original_source_path"],
            },
            "source_sha256": {
                "identity_reviewed": bundle["identity_sha256"],
                "phase_reviewed": bundle["phase_sha256"],
                "transcript_selected": bundle["transcript_sha256"],
                "original_transcript": bundle["original_source_sha256"],
            },
            "assessment_file_present": bundle["assessment_file_present"],
            "candidates": rows,
        })

    by_name = {}
    # `aggregate_bluffs` keys on person_id. S21 has no local formal person IDs in
    # these source files, so use confirmed display names as provisional local keys.
    for bundle in bundles:
        for seat in bundle["reviewed_game"]["seats"]:
            if seat.get("name"):
                seat["person_id"] = f"s21-name:{seat['name']}"
    # Recompute the name-keyed contract aggregate on the exact same normalized games.
    contract_stats = bluffs.aggregate_bluffs(contract_games, payload)
    name_for_key = {
        f"s21-name:{seat['name']}": seat["name"]
        for bundle in bundles for seat in bundle["reviewed_game"]["seats"] if seat.get("name")
    }
    for key, value in contract_stats.items():
        by_name[name_for_key.get(key, key)] = value

    is_full_scope = bvid is None
    complete, assessment_coverage_complete = _completion_flags(
        counts, faction_unresolved, success_excluded,
    )
    summary = {
        "media_items": len(entries),
        "media_scope_items": full_scope_count,
        "is_full_season_scope": is_full_scope,
        "formal_game_count": None,
        "media_count_note": "当前统计边界为S21已选媒体范围；122条媒体记录不等同于正式局数。",
        "assessed_media_items": sum(row["assessment_file_present"] for row in media_rows),
        "media_items_missing_assessment_file": sum(not row["assessment_file_present"] for row in media_rows),
        "wolf_role_candidates": sum(len(row["candidates"]) for row in media_rows),
        "wolf_role_candidate_decisions": {key: counts[key] for key in ("yes", "no", "uncertain", "missing")},
        "confirmed_wolf_appearances": wolf_appearances,
        "candidate_factions_unresolved": faction_unresolved,
        "identified_bluffs": identified,
        "successful_bluffs": success_num,
        "success_rate": {
            "numerator": success_num, "denominator": success_den,
            "rate": success_num / success_den if success_den else None,
            "excluded_unknown_success": success_excluded,
        },
        "name_keyed_player_stats": by_name,
        "player_key_note": "本机显示名汇总，不是数据库person_id；不自动合并跨名别名。",
        "complete": complete,
        "assessment_coverage_complete": assessment_coverage_complete,
        "success_contract": "website.api.bluffs.evaluate_success / aggregate_bluffs",
        "faction_method": [
            "基础狼人按identity.reviewed物理身份确认狼方。",
            "诡术之境仅采用S21已核官方规则卡阵营。",
            "机械狼等特殊身份只有assessment明确给出faction=werewolf并带selected transcript literal evidence时计入已确认狼方。",
            "混血儿有效阵营由已核choose_model事件和已知目标阵营按网站effective_faction契约派生；不改identity/phase源数据。",
            "未知阵营不会作好人或狼人判定，也不进入悍跳成功率分母。",
        ],
    }
    progress = {
        "schema_version": 1,
        "season": "S21",
        "title": "S21悍跳本机核实进度",
        "scope": {"bvid": bvid, "media_items": len(entries), "full_scope_media_items": full_scope_count,
                  "is_full_season_scope": is_full_scope},
        "summary": summary,
    }
    detail = {
        "schema_version": 1,
        "season": "S21",
        "scope": progress["scope"],
        "summary": summary,
        "items": media_rows,
    }
    markdown = _render_markdown(detail)
    return progress, detail, markdown


def _render_markdown(detail: dict) -> str:
    summary = detail["summary"]
    lines = [
        "# S21 悍跳核实明细（本机）",
        "",
        f"统计范围：{summary['media_items']} 条媒体记录；完整范围边界为 {summary['media_scope_items']} 条媒体记录。该数量不是正式局数。",
        "",
        f"已建立assessment文件：{summary['assessed_media_items']}；缺文件：{summary['media_items_missing_assessment_file']}。",
        f"候选狼位：{summary['wolf_role_candidates']}；确认狼方：{summary['confirmed_wolf_appearances']}；阵营未决：{summary['candidate_factions_unresolved']}。",
        f"悍跳yes/no/uncertain/未核：{summary['wolf_role_candidate_decisions']['yes']}/{summary['wolf_role_candidate_decisions']['no']}/{summary['wolf_role_candidate_decisions']['uncertain']}/{summary['wolf_role_candidate_decisions']['missing']}。",
        f"Assessment覆盖完整：{summary['assessment_coverage_complete']}；全部核实完整：{summary['complete']}。",
        f"成功悍跳：{summary['successful_bluffs']}；成功率：{summary['success_rate']['numerator']}/{summary['success_rate']['denominator']}（未知成功排除 {summary['success_rate']['excluded_unknown_success']} 项）。",
        "",
        "特殊身份阵营未决时保留候选位与核实状态，不自动作no或好人判断。成功条件按现有网站契约计算；该本地导出不写数据库或网站资源。",
        "",
        "## 逐媒体明细",
        "",
    ]
    for item in detail["items"]:
        lines.extend([f"### {item['bvid']} — {_md_escape(item.get('title'))}", "",
                      f"来源绑定：identity `{item['source_sha256']['identity_reviewed']}`；phase `{item['source_sha256']['phase_reviewed']}`；selected transcript `{item['source_sha256']['transcript_selected']}`。", ""])
        lines.extend([
            "| 座位 | 姓名 | 物理底牌 | 阵营 | 悍跳判断 | 自称身份 | 发生日 | 成功 | 成功依据 | 成功待核问题 | 状态 | 明确缺口 |",
            "|---:|---|---|---|---|---|---:|---|---|---|---|---|",
        ])
        for row in item["candidates"]:
            success_reasons = "；".join(
                reason.get("text", str(reason)) if isinstance(reason, dict) else str(reason)
                for reason in row.get("success_reasons", []))
            success_questions = "；".join(row.get("success_questions", []))
            values = [row.get(key) for key in (
                "seat", "name", "physical_role", "faction", "decision", "claimed_role", "claim_day", "success")]
            values.extend((success_reasons, success_questions, row.get("assessment_status"), row.get("explicit_gaps")))
            lines.append("| " + " | ".join(_md_escape(value) for value in values) + " |")
        lines.append("")
        for row in item["candidates"]:
            if not row["evidence"] and not row["faction_evidence"]:
                continue
            lines.append(f"#### {row['seat']}号 {row['name']} 证据")
            lines.append("")
            for evidence in row["evidence"]:
                lines.append(f"- 悍跳：segments {evidence['segment_indices']}，{evidence['start_ms']}–{evidence['end_ms']}ms：{evidence['quote']}")
            for evidence in row["faction_evidence"]:
                lines.append(f"- 狼方：segments {evidence['segment_indices']}，{evidence['start_ms']}–{evidence['end_ms']}ms：{evidence['quote']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_json(root: Path, path: Path, value: Any) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if target.is_file() and target.read_text(encoding="utf-8") == text:
        return
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="S21 project root")
    parser.add_argument("--bvid", help="limit the local report to one in-scope media item")
    parser.add_argument("--check", action="store_true", help="validate and summarize without writing")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        progress, detail, markdown = build(root, args.bvid)
        if not args.check:
            _write_json(root, PROGRESS_JSON, progress)
            _write_json(root, DETAIL_JSON, detail)
            target = root / DETAIL_MD
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(markdown, encoding="utf-8")
        summary = progress["summary"]
        print(json.dumps({
            "season": "S21", "media_items": summary["media_items"],
            "full_scope_media_items": summary["media_scope_items"],
            "formal_game_count": None, "complete": summary["complete"],
            "assessment_coverage_complete": summary["assessment_coverage_complete"],
            "candidate_decisions": summary["wolf_role_candidate_decisions"],
            "confirmed_wolf_appearances": summary["confirmed_wolf_appearances"],
            "candidate_factions_unresolved": summary["candidate_factions_unresolved"],
            "successful_bluffs": summary["successful_bluffs"],
            "success_rate": summary["success_rate"],
            "checked": True, "written": not args.check,
        }, ensure_ascii=False, indent=2))
        return 0
    except BuildError as exc:
        print(json.dumps({"error": "s21_bluff_review_failed", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
