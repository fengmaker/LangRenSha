"""Apply a reviewed incremental export to one season's formal records."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

from incremental_common import (ROOT, entry_key, load_state, save_state, work_dir,
                                write_json)


class ReviewApplyError(ValueError):
    """A review, source, ownership, or release contract is not satisfied."""


REVIEW_FORMAT = "masters-incremental-review-v1"
REVIEW_FORMAT_V2 = "masters-incremental-review-v2"
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
IMMUTABLE_DOSSIER_FIELDS = {"slug", "season", "board", "phase", "files"}


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _json_sha256(value: object) -> str:
    # write_json uses text mode, which writes CRLF on Windows.  Approval hashes
    # must match those file bytes on both the first application and a retry.
    raw = _json_bytes(value).replace(b"\n", os.linesep.encode("ascii"))
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewApplyError(f"JSON无效或文件不存在：{path}") from exc


def _state_entry(item: dict) -> dict:
    entry = item.get("entry", item)
    if not isinstance(entry, dict):
        raise ReviewApplyError("增量状态 entry 必须是对象")
    return entry


def _state_item(state: dict, game: dict, root: Path, season: str) -> tuple[str, dict, dict, Path, Path]:
    bvid, cid, page = game["bvid"], game["cid"], game["page"]
    probe = {"bvid": bvid, "cid": cid, "page": page}
    key = entry_key(probe)
    item = state.get("items", {}).get(key)
    if not isinstance(item, dict):
        raise ReviewApplyError(f"{game['review_id']} 已不在增量队列中")
    entry = _state_entry(item)
    if (entry.get("bvid") != bvid or str(entry.get("cid")) != str(cid)
            or int(entry.get("page") or 1) != page):
        raise ReviewApplyError(f"{game['review_id']} 与增量队列身份不一致")
    expected_review_id = item.get("review_id") or entry.get("review_id") or key
    if game["review_id"] != expected_review_id:
        raise ReviewApplyError(f"{game['review_id']} 的复核ID与队列不匹配")
    if item.get("analysis") != "ready":
        raise ReviewApplyError(f"{game['review_id']} 尚无可导入候选")
    folder = work_dir(root, season, entry)
    candidate_path = folder / "candidate.json"
    source_value = item.get("source_path") or entry.get("source_path")
    if not isinstance(source_value, str):
        raise ReviewApplyError(f"{game['review_id']} 缺少原文路径")
    source_path = (root / source_value).resolve()
    if not source_path.is_relative_to((root / "data").resolve()) or not source_path.is_file():
        raise ReviewApplyError(f"{game['review_id']} 原文不存在或超出data目录")
    return key, item, entry, candidate_path, source_path


def _verify_disk_identity(game: dict, item: dict, entry: dict, candidate: dict,
                          candidate_path: Path, source_path: Path, season: str) -> None:
    candidate_hash = sha256_file(candidate_path)
    source_hash = sha256_file(source_path)
    expected_candidate = item.get("candidate_sha256")
    expected_source = item.get("source_sha256")
    if candidate_hash != expected_candidate or candidate_hash != game["candidate_sha256"]:
        raise ReviewApplyError(f"{game['review_id']} 候选版本不匹配；旧导出不能用于变化后的候选")
    if source_hash != expected_source or source_hash != game["source_sha256"]:
        raise ReviewApplyError(f"{game['review_id']} 原文版本不匹配")
    if not HASH_RE.fullmatch(str(candidate_hash or "")) or not HASH_RE.fullmatch(str(source_hash or "")):
        raise ReviewApplyError(f"{game['review_id']} 的版本SHA格式无效")
    dossier = candidate.get("dossier")
    voting = candidate.get("voting")
    if not isinstance(dossier, dict) or not isinstance(voting, dict):
        raise ReviewApplyError(f"{game['review_id']} 候选缺少 dossier 或 voting")
    if dossier.get("season") != season or voting.get("game_slug") != dossier.get("slug"):
        raise ReviewApplyError(f"{game['review_id']} 候选赛季或对局关联不一致")
    external_key = f"{game['bvid']}:{game['cid']}"
    if not any(isinstance(row, dict) and row.get("external_key") == external_key
               for row in dossier.get("files", [])):
        raise ReviewApplyError(f"{game['review_id']} 候选源文件身份与BVID/CID不一致")
    # Transcripts produced by the incremental collector carry their own media
    # identity. Keep checking it when present; the file hash is always checked.
    try:
        source = _read_json(source_path)
    except ReviewApplyError:
        source = None
    if isinstance(source, dict):
        identity = source.get("source") if isinstance(source.get("source"), dict) else source
        for key in ("bvid", "cid", "page"):
            actual = identity.get(key)
            expected = game[key]
            if actual is not None and str(actual) != str(expected):
                raise ReviewApplyError(f"{game['review_id']} 原文内 {key} 身份不一致")


def _patch_pointer(document: dict, pointer: str, value: object) -> None:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ReviewApplyError("备注AI补丁必须使用非空JSON Pointer")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    if len(parts) < 2 or parts[0] not in {"dossier", "voting"}:
        raise ReviewApplyError("备注补丁只能定位 dossier 或 voting 的现有字段")
    if parts[0] == "dossier" and any(
            parts[1] == field or parts[1].startswith(field + "/")
            for field in IMMUTABLE_DOSSIER_FIELDS):
        raise ReviewApplyError("备注补丁不能修改来源、slug、赛季、版型或阶段")
    current = document
    for part in parts[:-1]:
        if isinstance(current, list):
            if not part.isdigit() or int(part) >= len(current):
                raise ReviewApplyError(f"备注补丁路径不存在：{pointer}")
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ReviewApplyError(f"备注补丁路径不存在：{pointer}")
    leaf = parts[-1]
    if isinstance(current, list):
        if not leaf.isdigit() or int(leaf) >= len(current):
            raise ReviewApplyError(f"备注补丁路径不存在：{pointer}")
        current[int(leaf)] = deepcopy(value)
    elif isinstance(current, dict) and leaf in current:
        current[leaf] = deepcopy(value)
    else:
        raise ReviewApplyError(f"备注补丁只能替换现有字段：{pointer}")


def _apply_note(candidate: dict, note: str, review_id: str, *, root: Path,
                codex: str = "codex") -> tuple[dict, list[dict], dict, list[str]]:
    if not note.strip():
        return deepcopy(candidate), [], {"reviewed": False, "no_bluff": False, "items": []}, []
    try:
        from incremental_ai import run_json
    except ImportError as exc:
        raise ReviewApplyError("缺少增量分析或AI模块，不能处理人工备注") from exc
    prompt = (
        f"只处理复核条目 {review_id} 的以下用户备注。已验证候选JSON为：\n"
        + json.dumps(candidate, ensure_ascii=False, indent=2)
        + "\n原文与直接来源事实只按候选证据引用，不读取其他对局。\n"
        + "备注原文（逐字保留）：\n" + note + "\n"
        + "将要求明确且唯一的事实修正为对现有候选字段的最小JSON Pointer补丁。"
        + "仅允许把字段定位到 /dossier/... 或 /voting/... 的现有叶字段；不增补缺少字段，"
        + "不更改 dossier 的 slug、season、board、phase、files，也不改证据或其他未被备注明确要求的数据。"
        + "每个补丁都要含有 note_quote（从备注逐字复制的相关短语）和 reason。"
        + "若对象、轮次、座位、方向或含义不能唯一确定，返回 unresolved 并解释，不要猜。"
        + "输出形如 {\"patches\":[{\"path\":\"/dossier/...\",\"value\":...,"
        + "\"note_quote\":\"...\",\"reason\":\"...\"}],\"unresolved\":[\"...\"]}。"
        + "并返回bluffs:{reviewed:boolean,no_bluff:boolean,items:[{seat,decision,success,note}]}。"
        + "只从本条备注抄录明确的悍跳判断：decision为yes（明确悍跳）、no（明确未悍跳）或uncertain（备注明确说待定）；"
        + "success只有decision=yes时可为true/false/null，其他decision必须为null；"
        + "no_bluff仅在备注明确确认整局无人悍跳时为true。未提到的座位不推断为未悍跳，保持未知。"
        + "每个item.note必须逐字摘录备注；非悍跳备注返回reviewed:false,no_bluff:false,items:[]。"
        + "模糊到不能唯一确定座位、尝试与成功结果时列入unresolved。"
        + "非空备注必须有实际字段补丁或明确悍跳条目/无人悍跳判断；否则列为unresolved。"
    )
    (root / "data").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="incremental-note-", dir=root / "data") as temp:
        response_path = Path(temp) / "note_response.json"
        result = run_json(prompt, response_path, root=root, codex=codex)
    if (not isinstance(result, dict) or not isinstance(result.get("patches"), list)
            or not isinstance(result.get("unresolved"), list)
            or not isinstance(result.get("bluffs"), dict)):
        raise ReviewApplyError(f"{review_id} 备注AI结果结构无效")
    unresolved = [str(value) for value in result["unresolved"]]
    bluff_review = result["bluffs"]
    if (type(bluff_review.get("reviewed")) is not bool
            or type(bluff_review.get("no_bluff")) is not bool
            or not isinstance(bluff_review.get("items"), list)):
        raise ReviewApplyError(f"{review_id} 悍跳备注结果结构无效")
    if (bluff_review["items"] or bluff_review["no_bluff"]) and not bluff_review["reviewed"]:
        unresolved.append("悍跳备注有人工结论但未标记reviewed")
    seen_bluff_seats = set()
    for row in bluff_review["items"]:
        if (not isinstance(row, dict) or type(row.get("seat")) is not int
                or row.get("decision") not in {"yes", "no", "uncertain"}
                or (row.get("success") is not None and type(row.get("success")) is not bool)
                or (row.get("decision") != "yes" and row.get("success") is not None)
                or not isinstance(row.get("note"), str) or not row["note"]
                or row["note"] not in note or row["seat"] in seen_bluff_seats):
            raise ReviewApplyError(f"{review_id} 悍跳备注须有唯一座位、明确结论和原备注摘录")
        seen_bluff_seats.add(row["seat"])
    if bluff_review["no_bluff"] and any(row["decision"] != "no" for row in bluff_review["items"]):
        unresolved.append("无人悍跳判断与座位结论冲突，需先解决")
    if not result["patches"] and not (bluff_review["no_bluff"] or bluff_review["items"]):
        unresolved.append("非空备注没有可应用的结构修正，需先解决备注含义")
    updated = deepcopy(candidate)
    seen = set()
    for patch in result["patches"]:
        if (not isinstance(patch, dict) or not isinstance(patch.get("path"), str)
                or "value" not in patch or not isinstance(patch.get("note_quote"), str)
                or patch["note_quote"] not in note or not patch["note_quote"]):
            raise ReviewApplyError(f"{review_id} 备注AI补丁缺少范围引用")
        pointer = patch["path"]
        if pointer in seen:
            raise ReviewApplyError(f"{review_id} 备注AI补丁路径重复：{pointer}")
        seen.add(pointer)
        _patch_pointer(updated, pointer, patch["value"])
    before = candidate["dossier"]
    after = updated["dossier"]
    for field in IMMUTABLE_DOSSIER_FIELDS:
        if before.get(field) != after.get(field):
            raise ReviewApplyError(f"{review_id} 备注修改了锁定字段 {field}")
    if unresolved:
        return deepcopy(candidate), deepcopy(result["patches"]), deepcopy(bluff_review), unresolved
    return updated, deepcopy(result["patches"]), deepcopy(bluff_review), []


def _manifest_path(candidate: dict, entry: dict, root: Path, season: str) -> Path:
    media = next((row for row in candidate["dossier"].get("files", [])
                  if isinstance(row, dict) and row.get("role") == "manifest"), None)
    choices = [entry.get("manifest_path"), entry.get("manifest"),
               media.get("path") if media else None]
    page = int(entry.get("page") or 1)
    choices += [f"data/raw/bilibili/{entry['bvid']}/p{page:02d}/manifest.json",
                (work_dir(root, season, entry) / "manifest.json").relative_to(root).as_posix()]
    for relative in choices:
        if isinstance(relative, str):
            path = (root / relative).resolve()
            if path.is_relative_to((root / "data").resolve()) and path.is_file():
                return path
    raise ReviewApplyError(f"{entry['bvid']} 缺少已采集的本地媒体manifest")


def _formal_path(root: Path, season: str, entry: dict, dossier: dict) -> Path:
    try:
        event_date = date.fromisoformat(dossier["date"]).isoformat()
        number = dossier["game_number"]
        if type(number) is not int or number < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ReviewApplyError(f"{dossier.get('slug')} 缺少可用于正式归档的日期或局次") from None
    name = f"{event_date}_g{number:02d}_{entry['bvid']}"
    if int(entry.get("page") or 1) > 1:
        name += f"_p{int(entry['page']):02d}"
    return root / "data" / "games" / season / name


def _source_owner(dossier: dict) -> set[str]:
    return {str(row.get("external_key")) for row in dossier.get("files", [])
            if isinstance(row, dict) and row.get("platform") == "bilibili"
            and isinstance(row.get("external_key"), str)}


def _check_formal_ownership(root: Path, season: str, item: dict,
                            destination: Path, entry: dict, dossier: dict,
                            outputs: dict[str, object]) -> str:
    relative = destination.relative_to(root).as_posix()
    owned = item.get("formal_dir")
    if owned is not None and owned != relative:
        raise ReviewApplyError(f"{entry['bvid']} 已登记正式目录 {owned}，拒绝换目录覆盖")
    expected_key = f"{entry['bvid']}:{entry['cid']}"
    for dossier_path in (root / "data" / "games" / season).glob("*/dossier.json"):
        existing = _read_json(dossier_path)
        if not isinstance(existing, dict):
            raise ReviewApplyError(f"现有正式档案格式异常：{dossier_path}")
        same_slug = existing.get("slug") == dossier.get("slug")
        same_source = expected_key in _source_owner(existing)
        if (same_slug or same_source) and dossier_path.parent.resolve() != destination.resolve():
            raise ReviewApplyError(f"{entry['bvid']} 已在其他正式目录出现：{dossier_path.parent}")
    if destination.exists() and owned != relative:
        raise ReviewApplyError(f"正式目录已存在但未由增量状态拥有：{destination}")
    for name, expected in outputs.items():
        path = destination / name
        if path.is_file() and _read_json(path) != expected:
            raise ReviewApplyError(f"已登记的正式档案内容与当前复核版本冲突：{path}")
    return relative


def _review_record(candidate: dict, entry: dict, game: dict, note: str,
                   patches: list[dict], manual_source_path: str,
                   manual_sha256: str, bluff_review: dict | None = None) -> dict:
    record = {
        "format": "masters-incremental-confirmed-v1", "season": candidate["dossier"]["season"],
        "review_id": game["review_id"], "bvid": game["bvid"], "cid": game["cid"],
        "page": game["page"], "reviewed": True,
        "manual_source_path": manual_source_path, "manual_sha256": manual_sha256,
        "source_sha256": game["source_sha256"], "candidate_sha256": game["candidate_sha256"], "note": note,
        "patches": patches, "evidence": candidate.get("evidence", []),
        "issues": candidate.get("issues", []), "bluffs_review": bluff_review or {
            "reviewed": False, "no_bluff": False, "items": []},
        "entry": {"bvid": entry["bvid"], "cid": entry["cid"], "page": entry.get("page", 1)},
    }
    if "bluffs" in game:
        record["bluffs_input"] = deepcopy(game["bluffs"])
    return record


def _selected_bluffs(game: dict, candidate: dict, *, required: bool) -> dict:
    """Interpret explicit controls directly; blanks are not human conclusions."""
    rows = game.get("bluffs")
    result = {"reviewed": False, "no_bluff": False, "items": []}
    if rows is None and not required:
        return result
    seats = {row["seat"] for row in candidate["dossier"]["seats"]}
    if not isinstance(rows, list) or len(rows) != len(seats):
        raise ReviewApplyError("悍跳选择必须完整对应本局座位")
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"seat", "decision", "success"}
                or type(row["seat"]) is not int or row["seat"] not in seats or row["seat"] in seen
                or not isinstance(row["decision"], str) or not isinstance(row["success"], str)
                or row["decision"] not in {"", "yes", "no", "uncertain"}
                or row["success"] not in {"", "success", "failure", "uncertain"}
                or row["decision"] != "yes" and row["success"] != ""):
            raise ReviewApplyError("悍跳选择存在座位重复、非法选项或非悍跳座位填写成功结果")
        seen.add(row["seat"])
        if not row["decision"]:
            continue
        decision = {"yes": "是", "no": "否", "uncertain": "待定"}[row["decision"]]
        success = {"": "未填写", "success": "成功", "failure": "失败", "uncertain": "待定"}[row["success"]]
        result["items"].append({"seat": row["seat"], "decision": row["decision"],
            "success": {"success": True, "failure": False}.get(row["success"]),
            "success_selected": row["success"] != "", "input_method": "selection",
            "note": f"{row['seat']}号：是否悍跳={decision}；是否成功={success}。"})
    result["reviewed"] = bool(result["items"])
    return result


def _combine_bluff_reviews(note_review: dict, selections: dict) -> dict:
    result = deepcopy(note_review)
    by_seat = {row["seat"]: row for row in result["items"]}
    for row in selections["items"]:
        prior = by_seat.get(row["seat"])
        if prior and (prior["decision"] != row["decision"]
                      or row["success_selected"] and prior["success"] != row["success"]):
            raise ReviewApplyError(f"{row['seat']}号的备注与悍跳选择冲突，请先在当前窗口明确结论")
        if prior and not row["success_selected"]:
            continue
        by_seat[row["seat"]] = deepcopy(row)
    if result.get("no_bluff") and any(row["decision"] != "no" for row in by_seat.values()):
        raise ReviewApplyError("无人悍跳备注与座位选择冲突")
    result["items"] = sorted(by_seat.values(), key=lambda row: row["seat"])
    result["reviewed"] = result["reviewed"] or selections["reviewed"]
    return result


def _prepare_export(review_path: Path, season: str, *, root: Path = ROOT,
                    run_ai: bool = True, codex: str = "codex") -> tuple[dict, list[dict]]:
    payload = _read_json(review_path)
    if (not isinstance(payload, dict) or payload.get("format") not in {REVIEW_FORMAT, REVIEW_FORMAT_V2}
            or payload.get("season") != season or not isinstance(payload.get("games"), list)):
        raise ReviewApplyError(f"复核文件必须为 {REVIEW_FORMAT} 或 {REVIEW_FORMAT_V2}，且赛季为 {season}")
    state = load_state(root, season)
    manual_sha = sha256_file(review_path)
    archive_relative = f"data/reports/{season}/incremental/reviews/{manual_sha}.json"
    prepared = []
    seen = set()
    for game in payload["games"]:
        if not isinstance(game, dict):
            raise ReviewApplyError("复核 games 条目必须是对象")
        if type(game.get("reviewed")) is not bool or not isinstance(game.get("note"), str):
            raise ReviewApplyError("复核条目 reviewed/note 类型不正确")
        if not game["reviewed"]:
            continue
        required = ("review_id", "bvid", "cid", "page", "candidate_sha256", "source_sha256")
        if any(field not in game for field in required):
            raise ReviewApplyError("已复核条目缺少身份或候选版本字段")
        if (not isinstance(game["review_id"], str) or not isinstance(game["bvid"], str)
                or type(game["page"]) is not int or game["page"] < 1):
            raise ReviewApplyError("已复核条目身份字段格式错误")
        key, item, entry, candidate_path, source_path = _state_item(state, game, root, season)
        if key in seen:
            raise ReviewApplyError(f"复核文件重复包含 {game['review_id']}")
        seen.add(key)
        candidate = _read_json(candidate_path)
        if not isinstance(candidate, dict):
            raise ReviewApplyError(f"{game['review_id']} 候选必须是JSON对象")
        _verify_disk_identity(game, item, entry, candidate, candidate_path, source_path, season)
        from analyze_incremental import validate_candidate
        candidate = validate_candidate(candidate, entry, source_path, root=root)
        selected_bluffs = _selected_bluffs(game, candidate, required=payload["format"] == REVIEW_FORMAT_V2)
        patches: list[dict] = []
        folder = work_dir(root, season, entry)
        accepted_path = folder / "accepted_candidate.json"
        review_record_path = folder / "accepted_review.json"
        accepted_formal_path = folder / "accepted_formal.json"
        phases = item.get("phases", {})
        bluff_review = {"reviewed": False, "no_bluff": False, "items": []}
        manual_source_path = archive_relative
        saved_review = None
        unresolved: list[str] = []
        cached_formal = None
        if accepted_path.is_file() and review_record_path.is_file():
            accepted_record = _read_json(review_record_path)
            if (not isinstance(accepted_record, dict)
                    or accepted_record.get("candidate_sha256") != game["candidate_sha256"]
                    or accepted_record.get("source_sha256") != game["source_sha256"]):
                if phases.get("database") == "done":
                    raise ReviewApplyError(f"{game['review_id']} 已入库记录与当前候选版本不符")
                accepted_record = None
            if (accepted_record is not None and accepted_record.get("note", "") == game["note"]
                    and accepted_record.get("bluffs_input") == game.get("bluffs")
                    and accepted_formal_path.is_file()):
                accepted = _read_json(accepted_path)
                cached_formal = _read_json(accepted_formal_path)
                if not isinstance(accepted, dict) or not isinstance(cached_formal, dict):
                    raise ReviewApplyError(f"{game['review_id']} 已准备候选缓存损坏")
                validate_candidate(accepted, entry, source_path, root=root)
                note = accepted_record.get("note", "")
                patches = accepted_record.get("patches", [])
                bluff_review = accepted_record.get("bluffs_review", bluff_review)
                manual_source_path = accepted_record.get("manual_source_path", archive_relative)
                saved_review = accepted_record
            elif phases.get("database") == "done":
                raise ReviewApplyError(f"{game['review_id']} 已入库备注或悍跳选择与当前导出不同；请走正式修订流程")
            else:
                note = game["note"]
                if note.strip():
                    if not run_ai:
                        raise ReviewApplyError(f"{game['review_id']} 有备注；请由当前窗口模型准备结构化修订后再应用")
                    candidate, patches, bluff_review, unresolved = _apply_note(
                        candidate, note, game["review_id"], root=root, codex=codex)
                    if not unresolved:
                        candidate = validate_candidate(candidate, entry, source_path, root=root)
                accepted = candidate
        else:
            note = game["note"]
            if note.strip():
                if not run_ai:
                    raise ReviewApplyError(f"{game['review_id']} 有备注；请由当前窗口模型准备结构化修订后再应用")
                candidate, patches, bluff_review, unresolved = _apply_note(
                    candidate, note, game["review_id"], root=root, codex=codex)
                if not unresolved:
                    candidate = validate_candidate(candidate, entry, source_path, root=root)
            accepted = candidate
        if not saved_review:
            bluff_review = _combine_bluff_reviews(bluff_review, selected_bluffs)
        from game_records import validate as validate_game
        from voting_records import validate as validate_voting
        validate_game(accepted["dossier"], check_files=True, allow_incomplete=True)
        validate_voting(accepted["voting"])
        endgame = {"schema_version": 1, "game_slug": accepted["dossier"]["slug"], "phases": []}
        if cached_formal is not None and not unresolved:
            from game_derivations import apply_precomputed, fingerprint
            try:
                if cached_formal.get("endgame") != endgame:
                    raise ValueError("保存的终局占位档案已变化")
                if (cached_formal["derivations"].get("input_hashes", {}).get("endgame")
                        != fingerprint(endgame)):
                    raise ValueError("保存的规则派生未绑定当前终局档案")
                checked = apply_precomputed(accepted["dossier"], accepted["voting"],
                                            cached_formal["derivations"])
                if (checked["dossier"] != cached_formal["dossier"]
                        or checked["voting"] != cached_formal["voting"]):
                    raise ValueError("保存的规则派生输出不一致")
                prepared_formal = cached_formal
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                if phases.get("database") == "done":
                    raise ReviewApplyError(f"{game['review_id']} 已入库规则派生已失效：{exc}") from exc
                prepared_formal = None
        else:
            prepared_formal = None
        if prepared_formal is None:
            from game_derivations import derive_game
            derived = derive_game(accepted["dossier"], accepted["voting"], endgame=endgame)
            prepared_formal = {"dossier": derived["dossier"], "voting": derived["voting"],
                               "endgame": endgame, "derivations": derived["derivations"]}
        validate_game(prepared_formal["dossier"], check_files=True, allow_incomplete=True)
        validate_voting(prepared_formal["voting"])
        media_entry = {**entry, "manifest_path": item.get("manifest_path", entry.get("manifest_path"))}
        manifest = _manifest_path(accepted, media_entry, root, season)
        from media_ingest import validate_media
        checked_media = validate_media(manifest, game["bvid"], game["page"])
        if str(checked_media["manifest"]["cid"]) != str(game["cid"]):
            raise ReviewApplyError(f"{game['review_id']} 媒体manifest CID与复核身份不一致")
        destination = _formal_path(root, season, entry, prepared_formal["dossier"])
        manual_sha_for_game = saved_review.get("manual_sha256") if saved_review else manual_sha
        review_record = _review_record(accepted, entry, game, note, patches,
                                       manual_source_path, manual_sha_for_game, bluff_review)
        if saved_review:
            # Retain exact original export provenance on retries; a later export
            # may contain unrelated games or formatting changes.
            review_record["manual_source_path"] = saved_review["manual_source_path"]
            review_record["manual_sha256"] = saved_review["manual_sha256"]
        archive_path = (root / review_record["manual_source_path"]).resolve()
        if not archive_path.is_relative_to((root / "data").resolve()):
            raise ReviewApplyError(f"{game['review_id']} 复核原件路径超出data目录")
        if saved_review and archive_path.is_file() and sha256_file(archive_path) != review_record["manual_sha256"]:
            raise ReviewApplyError(f"{game['review_id']} 归档的人工复核原件哈希不匹配")
        review_record["dossier_sha256"] = _json_sha256(prepared_formal["dossier"])
        review_record["voting_sha256"] = _json_sha256(prepared_formal["voting"])
        outputs = {
            "dossier.json": prepared_formal["dossier"],
            "voting.json": prepared_formal["voting"],
            "endgame.json": prepared_formal["endgame"],
            "rule_derivations.json": prepared_formal["derivations"],
            "incremental_review.json": review_record,
        }
        relative = _check_formal_ownership(root, season, item, destination, entry,
                                           prepared_formal["dossier"], outputs)
        prepared.append({"key": key, "game": game, "item": item, "entry": entry,
                         "candidate": accepted, "prepared_formal": prepared_formal,
                         "accepted_path": accepted_path,
                         "accepted_formal_path": accepted_formal_path,
                         "review_record_path": review_record_path,
                         "review_record": review_record,
                         "manifest": manifest, "formal_dir": destination,
                         "formal_dir_relative": relative, "source_path": source_path,
                         "candidate_path": candidate_path,
                         "patches": patches, "unresolved": unresolved,
                         "manual_export_path": Path(review_path).resolve(),
                         "manual_archive_path": archive_path})
    return state, prepared


def _persist_accepted(plan: dict, state: dict, season: str, root: Path, *,
                      claim_owner: bool = True) -> None:
    item = plan["item"]
    if (sha256_file(plan["candidate_path"]) != plan["game"]["candidate_sha256"]
            or sha256_file(plan["source_path"]) != plan["game"]["source_sha256"]):
        raise ReviewApplyError(f"{plan['game']['review_id']} 原文或候选在预检后变化")
    if claim_owner:
        item["formal_dir"] = plan["formal_dir_relative"]
    item["phases"] = dict(item.get("phases", {}))
    archive_path = plan["manual_archive_path"]
    expected_manual_sha = plan["review_record"]["manual_sha256"]
    if archive_path.is_file():
        if sha256_file(archive_path) != expected_manual_sha:
            raise ReviewApplyError(f"人工复核原件归档哈希冲突：{archive_path}")
    else:
        source = plan["manual_export_path"]
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_manual_sha:
            raise ReviewApplyError(f"复核导出在预检后发生变化：{source}")
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = archive_path.with_suffix(archive_path.suffix + ".tmp")
        temporary.write_bytes(raw)
        temporary.replace(archive_path)
    write_json(plan["accepted_path"], plan["candidate"])
    write_json(plan["review_record_path"], plan["review_record"])
    write_json(plan["accepted_formal_path"], plan["prepared_formal"])
    item["accepted_candidate_path"] = plan["accepted_path"].relative_to(root).as_posix()
    item["accepted_candidate_sha256"] = sha256_file(plan["accepted_path"])
    item["review_record_path"] = plan["review_record_path"].relative_to(root).as_posix()
    item["accepted_formal_path"] = plan["accepted_formal_path"].relative_to(root).as_posix()
    item["accepted_formal_sha256"] = sha256_file(plan["accepted_formal_path"])
    item["prepared_candidate_sha256"] = plan["game"]["candidate_sha256"]
    item["prepared_source_sha256"] = plan["game"]["source_sha256"]
    save_state(root, season, state)


def _import_database(plan: dict, state: dict, season: str, root: Path) -> dict:
    item = plan["item"]
    phases = item.setdefault("phases", {})
    if phases.get("database") == "done":
        return item.get("database_receipt", {"resumed": True})
    from database import import_media
    from database import connect
    from game_records import import_game
    from voting_records import import_voting

    if (sha256_file(plan["candidate_path"]) != plan["game"]["candidate_sha256"]
            or sha256_file(plan["source_path"]) != plan["game"]["source_sha256"]):
        raise ReviewApplyError(f"{plan['game']['review_id']} 原文或候选在数据库导入前变化")
    media_receipt = import_media(plan["manifest"], plan["game"]["bvid"], plan["game"]["page"])
    with connect() as conn:
        game_receipt = import_game(plan["prepared_formal"]["dossier"], allow_incomplete=True,
                                   conn=conn, derivations=plan["prepared_formal"]["derivations"])
        voting_receipt = import_voting(plan["prepared_formal"]["voting"], conn=conn)
    item["database_receipt"] = {"media": media_receipt, "game": game_receipt,
                                "voting": voting_receipt}
    phases["database"] = "done"
    item["applied"] = True
    save_state(root, season, state)
    return item["database_receipt"]


def _write_formal(plan: dict, state: dict, season: str, root: Path) -> None:
    if (sha256_file(plan["candidate_path"]) != plan["game"]["candidate_sha256"]
            or sha256_file(plan["source_path"]) != plan["game"]["source_sha256"]):
        raise ReviewApplyError(f"{plan['game']['review_id']} 原文或候选在正式归档前变化")
    destination = plan["formal_dir"]
    destination.mkdir(parents=True, exist_ok=True)
    outputs = {
        "dossier.json": plan["prepared_formal"]["dossier"],
        "voting.json": plan["prepared_formal"]["voting"],
        "endgame.json": plan["prepared_formal"]["endgame"],
        "rule_derivations.json": plan["prepared_formal"]["derivations"],
    }
    for name, value in outputs.items():
        target = destination / name
        if target.is_file() and _read_json(target) != value:
            raise ReviewApplyError(f"增量拥有的正式文件与复核版本冲突：{target}")
        write_json(target, value)
    review_record = deepcopy(plan["review_record"])
    review_record.update(format="masters-incremental-confirmed-v1", reviewed=True,
                         dossier_sha256=sha256_file(destination / "dossier.json"),
                         voting_sha256=sha256_file(destination / "voting.json"))
    archive_path = (root / review_record["manual_source_path"]).resolve()
    if (not archive_path.is_file()
            or sha256_file(archive_path) != review_record.get("manual_sha256")):
        raise ReviewApplyError(f"正式复核旁证原件缺失或SHA不匹配：{archive_path}")
    review_path = destination / "incremental_review.json"
    if review_path.is_file() and _read_json(review_path) != review_record:
        raise ReviewApplyError(f"已登记的增量复核旁证与当前复核版本冲突：{review_path}")
    write_json(review_path, review_record)
    plan["review_record"] = review_record
    write_json(plan["review_record_path"], review_record)
    plan["item"].setdefault("phases", {})["formal"] = "done"
    plan["item"]["formal_files"] = {name: sha256_file(destination / name)
                                     for name in (*outputs, "incremental_review.json")}
    save_state(root, season, state)


def _new_bluff_assessments(game: dict, plan: dict, bluffs_module) -> list[dict]:
    review = plan["review_record"].get("bluffs_review") or {}
    items = {row["seat"]: row for row in review.get("items", [])}
    physical = {seat["seat"] for seat in game.get("seats", [])
                if bluffs_module.physical_wolf(game, seat)}
    seats = {seat["seat"]: seat for seat in game.get("seats", [])}
    explicit = {number for number, row in items.items()
                if number in physical or row.get("decision") == "yes"}
    if review.get("no_bluff"):
        explicit.update(physical)
    unknown_note = "本次增量复核没有对该座位作出悍跳判断，保留未知。"
    result = []
    for number in sorted(physical | explicit):
        seat = seats.get(number)
        if seat is None:
            raise ReviewApplyError(f"{game.get('id')} 悍跳备注提及不存在的 {number} 号座位")
        item = items.get(number)
        if item is None and not review.get("no_bluff"):
            assessment = {
                "seat": number, "name": seat.get("name"), "physical_role": seat.get("role"),
                "decision": "uncertain", "claimed_role": None, "confidence": "low",
                "claim_day": None, "actual_claim_day": None, "first_day_claim": None,
                "decision_note": unknown_note, "verification_status": "assistant_inferred",
                "review_questions": [unknown_note], "evidence": [],
                "review_stage": "assistant_pending", "requires_user_review": False,
            }
        else:
            text = item["note"] if item else plan["review_record"].get("note", "")
            evidence = ([{"kind": "user_confirmation", "text": text,
                          "interpretation": ("来自人工悍跳选择。" if item and item.get("input_method") == "selection"
                                             else "直接摘自增量人工复核备注。"),
                          "source_sha256": plan["review_record"]["manual_sha256"]}]
                        if text else [])
            decision = item.get("decision") if item else "no"
            assessment = {
                "seat": number, "name": seat.get("name"), "physical_role": seat.get("role"),
                "decision": decision, "claimed_role": None,
                "confidence": "high", "claim_day": None, "actual_claim_day": None,
                "first_day_claim": None, "decision_note": text or "用户明确确认本局无人悍跳。",
                "verification_status": "user_uncertain" if decision == "uncertain" else "user_confirmed",
                "review_questions": [text] if decision == "uncertain" else [],
                "evidence": evidence, "review_stage": "reviewed",
                "requires_user_review": decision == "uncertain",
                "manual_source_sha256": plan["review_record"]["manual_sha256"],
                "manual_review_id": plan["review_record"]["review_id"],
                "manual_game_note": plan["review_record"].get("note", ""),
                "manual_note": text,
            }
            if not bluffs_module.physical_wolf(game, seat) and decision == "yes":
                # Mixed-blood and other nonphysical rows count only when the
                # user explicitly named them in the reviewed note.
                assessment["manual_included"] = True
            if item and decision == "yes" and item.get("success_selected", True):
                assessment["manual_success"] = item["success"]
        evidence = assessment.get("evidence", [])
        assessment["evidence_source_fingerprint"] = bluffs_module.evidence_source_fingerprint(evidence)
        assessment["claim_fingerprint"] = bluffs_module.claim_fingerprint(game, assessment)
        assessment["success_fingerprint"] = bluffs_module.success_fingerprint(
            game, number, bluffs_module.assessment_success_day(assessment))
        result.append(assessment)
    return result


def _merge_bluff_records(root: Path, season: str, plans: list[dict], state: dict) -> None:
    """Merge new signature-bound rows while preserving every existing game."""
    if not plans:
        return
    asset_path = root / "website" / "assets" / "bluffs" / f"{season}.json"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    if asset_path.is_file():
        payload = _read_json(asset_path)
        if not isinstance(payload, dict) or payload.get("season", season) != season:
            raise ReviewApplyError(f"悍跳复核资产赛季错误：{asset_path}")
    else:
        payload = {"schema_version": 1, "season": season,
                   "inference_version": "incremental-notes-v1", "games": []}
    if not isinstance(payload.get("games"), list):
        raise ReviewApplyError(f"悍跳复核资产 games 必须是数组：{asset_path}")
    payload.setdefault("schema_version", 1)
    payload.setdefault("season", season)
    payload.setdefault("inference_version", "incremental-notes-v1")
    from website.api import bluffs, publisher
    try:
        entries, _, _ = publisher.load_publication(root, season)
    except Exception as exc:
        raise ReviewApplyError(f"不能构建当前发布快照以计算悍跳指纹：{exc}") from exc
    names = {seat.get("name") for entry in entries for seat in entry["dossier"].get("seats", [])}
    person_ids = {name: str(uuid.uuid5(publisher.PERSON_NAMESPACE, name.strip().casefold()))
                  for name in names if isinstance(name, str)}
    games = {}
    for entry in entries:
        public_game = publisher._public_game(
            entry["dossier"], entry["voting"], entry["endgame"], entry.get("audit"),
            entry["board"], person_ids, source_voting=entry.get("source_voting"),
            derivations=entry.get("derivations"))
        games[public_game["id"]] = public_game
    by_id = {}
    for row in payload["games"]:
        if not isinstance(row, dict) or not isinstance(row.get("game_id"), str):
            raise ReviewApplyError("悍跳复核包含无效游戏记录，保留原文件并停止")
        if row["game_id"] in by_id:
            raise ReviewApplyError(f"悍跳复核游戏重复：{row['game_id']}")
        by_id[row["game_id"]] = row
    changed = False
    for plan in plans:
        slug = plan["candidate"]["dossier"]["slug"]
        game = games.get(slug)
        if game is None or game.get("source", {}).get("bvid") != plan["game"]["bvid"]:
            raise ReviewApplyError(f"{slug} 不在当前发布快照或媒体身份冲突")
        fingerprint = bluffs.source_fingerprint(game)
        generated = {"game_id": slug, "bvid": plan["game"]["bvid"],
                     "source_fingerprint": fingerprint, "coverage": "incremental_notes",
                     "assessments": _new_bluff_assessments(game, plan, bluffs)}
        current = by_id.get(slug)
        if current is None:
            by_id[slug] = generated
            changed = True
        else:
            if (current.get("bvid") != generated["bvid"]
                    or current.get("source_fingerprint") != fingerprint):
                raise ReviewApplyError(f"{slug} 的现有悍跳来源已变化；保留旧记录，需重新复核")
            existing_by_seat = {row.get("seat"): row for row in current.get("assessments", [])
                                if isinstance(row, dict)}
            generated_by_seat = {row["seat"]: row for row in generated["assessments"]}
            # Explicit user notes replace only the named seat(s); all unmentioned
            # conclusions already in the asset remain intact.
            for number, new_row in generated_by_seat.items():
                if new_row.get("verification_status") in {"user_confirmed", "user_uncertain"}:
                    old_row = existing_by_seat.get(number, {})
                    if (new_row.get("decision") == old_row.get("decision") == "yes"
                            and "manual_success" not in new_row and "manual_success" in old_row):
                        continue
                    existing_by_seat[number] = new_row
                else:
                    existing_by_seat.setdefault(number, new_row)
            merged = sorted(existing_by_seat.values(), key=lambda row: row["seat"])
            if current.get("assessments") != merged:
                current["assessments"] = merged
                changed = True
        plan["item"].setdefault("phases", {})["bluffs"] = "done"
        plan["item"]["bluffs_source_fingerprint"] = fingerprint
    # The publication contract covers every game in the release. A game without
    # any bluff judgment gets explicit uncertain rows for physical wolves so
    # its facts can publish while its bluff count remains unknown.
    for slug, game in games.items():
        if slug in by_id:
            continue
        synthetic_plan = {
            "game": {"bvid": game.get("source", {}).get("bvid")},
            "candidate": {"dossier": {"slug": slug}},
            "review_record": {"bluffs_review": {"reviewed": False,
                "no_bluff": False, "items": []}, "note": ""},
        }
        by_id[slug] = {
            "game_id": slug, "bvid": game.get("source", {}).get("bvid"),
            "source_fingerprint": bluffs.source_fingerprint(game),
            "coverage": "unknown_unreviewed",
            "assessments": _new_bluff_assessments(game, synthetic_plan, bluffs),
        }
        changed = True
    payload["games"] = [by_id[key] for key in sorted(by_id)]
    if changed or not asset_path.is_file():
        write_json(asset_path, payload)
    for plan in plans:
        plan["item"]["bluffs_asset_sha256"] = sha256_file(asset_path)
    save_state(root, season, state)


def _run_jobs(jobs: list[list[str]], root: Path) -> None:
    for job in jobs:
        subprocess.run(job, cwd=root, check=True)


def _publish(plans: list[dict], state: dict, season: str, root: Path) -> None:
    pending = [plan for plan in plans
               if plan["item"].get("phases", {}).get("publish") != "done"]
    if not pending:
        return
    import workflow
    _merge_bluff_records(root, season, pending, state)
    jobs = workflow.stage_commands("publish", season, root=root, photos=True)
    seasons = workflow.formal_seasons(root)
    workflow.ensure_retained_seasons(seasons)
    for plan in pending:
        plan["item"].setdefault("phases", {})["publish"] = "running"
    save_state(root, season, state)
    try:
        _run_jobs(jobs, root)
    except Exception:
        for plan in pending:
            plan["item"].setdefault("phases", {})["publish"] = "failed"
        save_state(root, season, state)
        raise
    for plan in pending:
        plan["item"].setdefault("phases", {})["publish"] = "done"
    save_state(root, season, state)


def _verify(plans: list[dict], state: dict, season: str, root: Path) -> None:
    import workflow
    unique = {}
    for plan in plans:
        unique.setdefault(plan["game"]["bvid"], plan)
    for bvid, plan in unique.items():
        if plan["item"].get("phases", {}).get("verify") == "done":
            continue
        plan["item"].setdefault("phases", {})["verify"] = "running"
        save_state(root, season, state)
        try:
            _run_jobs(workflow.stage_commands("verify", season, root=root, bvid=bvid), root)
        except Exception:
            plan["item"].setdefault("phases", {})["verify"] = "failed"
            save_state(root, season, state)
            raise
        plan["item"].setdefault("phases", {})["verify"] = "done"
        save_state(root, season, state)


def apply_review(review_path: Path, *, season: str = "S23", root: Path = ROOT,
                 apply: bool = False, publish: bool = False, codex: str = "codex",
                 backup: bool = True, run_ai: bool = True) -> dict:
    if publish and not apply:
        raise ReviewApplyError("--publish 必须与 --apply 一起使用")
    state, plans = _prepare_export(review_path, season, root=root, run_ai=run_ai, codex=codex)
    # A pending publication from an earlier successful DB/formal phase can be
    # resumed even if that review row was later removed from the export.
    if apply and publish:
        planned_keys = {plan["key"] for plan in plans}
        for key, item in state.get("items", {}).items():
            phases = item.get("phases", {}) if isinstance(item, dict) else {}
            if (key in planned_keys or phases.get("formal") != "done"
                    or phases.get("publish") == "done"):
                continue
            entry = _state_entry(item)
            folder = work_dir(root, season, entry)
            accepted_path = folder / "accepted_candidate.json"
            review_record_path = folder / "accepted_review.json"
            accepted_formal_path = folder / "accepted_formal.json"
            if (not accepted_path.is_file() or not review_record_path.is_file()
                    or not accepted_formal_path.is_file()):
                raise ReviewApplyError(f"{key} 缺少已应用候选，不能恢复发布")
            accepted = _read_json(accepted_path)
            record = _read_json(review_record_path)
            prepared_formal = _read_json(accepted_formal_path)
            source_path = root / item["source_path"]
            if (sha256_file(source_path) != item.get("source_sha256")
                    or sha256_file(folder / "candidate.json") != item.get("candidate_sha256")
                    or record.get("source_sha256") != item.get("source_sha256")
                    or record.get("candidate_sha256") != item.get("candidate_sha256")):
                raise ReviewApplyError(f"{key} 已应用版本与磁盘不一致，不能恢复发布")
            if (not isinstance(prepared_formal, dict)
                    or sha256_file(accepted_formal_path) != item.get("accepted_formal_sha256")):
                raise ReviewApplyError(f"{key} 已应用规则派生缓存不完整，不能恢复发布")
            manual_source = (root / record["manual_source_path"]).resolve()
            if (not manual_source.is_relative_to((root / "data").resolve())
                    or not manual_source.is_file()
                    or sha256_file(manual_source) != record.get("manual_sha256")):
                raise ReviewApplyError(f"{key} 人工复核原件缺失或SHA不匹配，不能恢复发布")
            game = {"review_id": record["review_id"], "bvid": entry["bvid"],
                    "cid": entry["cid"], "page": entry.get("page", 1),
                    "source_sha256": item["source_sha256"],
                    "candidate_sha256": item["candidate_sha256"], "reviewed": True,
                    "note": record.get("note", "")}
            plans.append({"key": key, "game": game, "item": item, "entry": entry,
                          "candidate": accepted, "prepared_formal": prepared_formal,
                          "formal_dir": root / item["formal_dir"],
                          "formal_dir_relative": item["formal_dir"],
                          "accepted_path": accepted_path, "accepted_formal_path": accepted_formal_path,
                          "review_record_path": review_record_path,
                          "review_record": record})
    blockers = [f"{plan['game']['review_id']}: {'; '.join(plan.get('unresolved', []))}"
                for plan in plans if plan.get("unresolved")]
    report = {
        "season": season, "reviewed_games": len(plans),
        "notes_with_patches": sum(bool(plan.get("patches")) for plan in plans),
        "apply": apply, "publish": publish,
        "state": "needs_resolution" if blockers else "prepared",
        "blocked_games": blockers,
        "games": [{
            "review_id": plan["game"]["review_id"],
            "formal_dir": plan["formal_dir_relative"],
            "candidate_sha256": plan["game"]["candidate_sha256"],
            "source_sha256": plan["game"]["source_sha256"],
            "patches": deepcopy(plan.get("patches", plan["review_record"].get("patches", []))),
            "unresolved": list(plan.get("unresolved", [])),
            "unknown": deepcopy(plan["prepared_formal"]["derivations"].get("gaps", [])),
            "issues": list(plan["candidate"].get("issues", []))
                      + list(plan["prepared_formal"]["derivations"].get("issues", [])),
            "bluffs": deepcopy(plan["review_record"].get("bluffs_review", {})),
            "phases": deepcopy(plan["item"].get("phases", {})),
        } for plan in plans],
    }
    if blockers and apply:
        raise ReviewApplyError("备注存在未解决内容，所有选中游戏均未写入：" + " | ".join(blockers))
    if not apply:
        if not blockers and plans:
            for plan in plans:
                _persist_accepted(plan, state, season, root, claim_owner=False)
            report["state"] = "prepared_cached"
        preview_path = (root / "data" / "reports" / season / "incremental" /
                        "previews" / f"{sha256_file(review_path)}.json")
        report["preview_path"] = preview_path.relative_to(root).as_posix()
        write_json(preview_path, report)
        return report
    if not plans:
        report["state"] = "nothing_to_apply"
        return report
    # Preflight every selected game's media, source, schema, ownership and note
    # before creating a backup, writing state, or touching the database.
    if backup and any(plan["item"].get("phases", {}).get("database") != "done" for plan in plans):
        subprocess.run([sys.executable, str(root / "scripts" / "backup_database.py")],
                       cwd=root, check=True)
    # Persist all fully preflighted semantic output before the first database
    # transaction, so retries reuse the exact note and derived rule inputs.
    for plan in plans:
        if plan["item"].get("phases", {}).get("database") != "done":
            _persist_accepted(plan, state, season, root)
    for plan in plans:
        if plan["item"].get("phases", {}).get("database") != "done":
            _import_database(plan, state, season, root)
        if plan["item"].get("phases", {}).get("formal") != "done":
            _write_formal(plan, state, season, root)
    if publish:
        _publish(plans, state, season, root)
        _verify(plans, state, season, root)
    report["state"] = "completed"
    report["games"] = [{"review_id": plan["game"]["review_id"],
                         "formal_dir": plan["formal_dir_relative"],
                         "phases": deepcopy(plan["item"].get("phases", {}))}
                        for plan in plans]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_export", type=Path, help="masters-incremental-review-v1 JSON")
    parser.add_argument("--season", choices=("S23",), default="S23")
    parser.add_argument("--apply", action="store_true", help="写入数据库、正式档案和增量状态")
    parser.add_argument("--publish", action="store_true", help="完整发布并验收所选BVID；必须同时指定--apply")
    parser.add_argument("--codex", default="codex")
    args = parser.parse_args(argv)
    try:
        report = apply_review(args.review_export, season=args.season, apply=args.apply,
                              publish=args.publish, codex=args.codex, run_ai=False)
    except (ReviewApplyError, ValueError, OSError, RuntimeError,
            subprocess.CalledProcessError) as exc:
        print(json.dumps({"state": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
