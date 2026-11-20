"""Turn a reviewed incremental export into final public game JSON."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from incremental_common import ROOT, entry_key, load_state, save_state, work_dir, write_json
from season_config import season_codes

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ReviewApplyError(ValueError):
    """A reviewed candidate, source, ownership, or final record is invalid."""


REVIEW_FORMAT = "masters-incremental-review-v1"
REVIEW_FORMAT_V2 = "masters-incremental-review-v2"
NOTE_REVISIONS_FORMAT = "masters-incremental-note-revisions-v1"
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
IMMUTABLE_DOSSIER_FIELDS = {"slug", "season", "board", "phase", "files"}


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _json_sha256(value: object) -> str:
    raw = _json_bytes(value).replace(b"\n", __import__("os").linesep.encode("ascii"))
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
    key = entry_key({"bvid": bvid, "cid": cid, "page": page})
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
        raise ReviewApplyError(f"{game['review_id']} 尚无可入库候选")
    folder = work_dir(root, season, entry)
    candidate_path = folder / "candidate.json"
    source_value = item.get("source_path") or entry.get("source_path")
    if not isinstance(source_value, str):
        raise ReviewApplyError(f"{game['review_id']} 缺少原文路径")
    source_path = (root / source_value).resolve()
    if not source_path.is_relative_to((root / "data").resolve()) or not source_path.is_file():
        raise ReviewApplyError(f"{game['review_id']} 原文不存在或超出data目录")
    if not candidate_path.is_file():
        raise ReviewApplyError(f"{game['review_id']} 候选文件不存在")
    return key, item, entry, candidate_path, source_path


def _verify_disk_identity(game: dict, item: dict, entry: dict, candidate: dict,
                          candidate_path: Path, source_path: Path, season: str) -> None:
    candidate_hash = sha256_file(candidate_path)
    source_hash = sha256_file(source_path)
    if candidate_hash != item.get("candidate_sha256") or candidate_hash != game["candidate_sha256"]:
        raise ReviewApplyError(f"{game['review_id']} 候选版本不匹配；旧导出不能用于变化后的候选")
    if source_hash != item.get("source_sha256") or source_hash != game["source_sha256"]:
        raise ReviewApplyError(f"{game['review_id']} 原文版本不匹配")
    if not HASH_RE.fullmatch(str(candidate_hash or "")) or not HASH_RE.fullmatch(str(source_hash or "")):
        raise ReviewApplyError(f"{game['review_id']} 的版本SHA格式无效")
    dossier, voting = candidate.get("dossier"), candidate.get("voting")
    if not isinstance(dossier, dict) or not isinstance(voting, dict):
        raise ReviewApplyError(f"{game['review_id']} 候选缺少 dossier 或 voting")
    if dossier.get("season") != season or voting.get("game_slug") != dossier.get("slug"):
        raise ReviewApplyError(f"{game['review_id']} 候选赛季或对局关联不一致")
    external_key = f"{game['bvid']}:{game['cid']}"
    if not any(isinstance(row, dict) and row.get("external_key") == external_key
               for row in dossier.get("files", [])):
        raise ReviewApplyError(f"{game['review_id']} 候选源身份与BVID/CID不一致")
    try:
        source = _read_json(source_path)
    except ReviewApplyError:
        source = None
    if isinstance(source, dict):
        identity = source.get("source") if isinstance(source.get("source"), dict) else source
        expected_identity = game
        for file in dossier["files"]:
            if isinstance(file, dict) and file.get("role") == "subtitle" and "page" in file:
                source_bvid, _, source_cid = file["external_key"].partition(":")
                expected_identity = {"bvid": source_bvid, "cid": source_cid, "page": file["page"]}
                break
        for field in ("bvid", "cid", "page"):
            actual = identity.get(field)
            expected = expected_identity[field]
            if actual is not None and str(actual) != str(expected):
                raise ReviewApplyError(f"{game['review_id']} 原文内 {field} 身份不一致")


def _patch_pointer(document: dict, pointer: str, value: object) -> None:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ReviewApplyError("备注补丁必须使用非空JSON Pointer")
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
    if isinstance(current, list) and leaf.isdigit() and int(leaf) < len(current):
        current[int(leaf)] = deepcopy(value)
    elif isinstance(current, dict) and leaf in current:
        current[leaf] = deepcopy(value)
    else:
        raise ReviewApplyError(f"备注补丁只能替换现有字段：{pointer}")


def _apply_note_result(candidate: dict, note: str, review_id: str,
                       result: dict) -> tuple[dict, list[dict], dict, list[str]]:
    if (not isinstance(result, dict) or not isinstance(result.get("patches"), list)
            or not isinstance(result.get("unresolved"), list)
            or not isinstance(result.get("bluffs"), dict)):
        raise ReviewApplyError(f"{review_id} 备注修订结构无效")
    unresolved = [str(value) for value in result["unresolved"]]
    bluff_review = result["bluffs"]
    if (type(bluff_review.get("reviewed")) is not bool
            or type(bluff_review.get("no_bluff")) is not bool
            or not isinstance(bluff_review.get("items"), list)):
        raise ReviewApplyError(f"{review_id} 悍跳备注结构无效")
    if (bluff_review["items"] or bluff_review["no_bluff"]) and not bluff_review["reviewed"]:
        unresolved.append("悍跳备注有人工结论但未标记reviewed")
    seen_bluff_seats: set[int] = set()
    for row in bluff_review["items"]:
        if (not isinstance(row, dict) or type(row.get("seat")) is not int
                or row.get("decision") not in {"yes", "no", "uncertain"}
                or (row.get("success") is not None and type(row.get("success")) is not bool)
                or ("success_selected" in row and type(row["success_selected"]) is not bool)
                or (row.get("decision") != "yes" and row.get("success") is not None)
                or (row.get("decision") != "yes" and row.get("success_selected") is True)
                or not isinstance(row.get("note"), str) or not row["note"]
                or row["note"] not in note or row["seat"] in seen_bluff_seats):
            raise ReviewApplyError(f"{review_id} 悍跳备注须有唯一座位、明确结论和原备注摘录")
        row.setdefault("success_selected", row.get("success") is not None)
        seen_bluff_seats.add(row["seat"])
    if bluff_review["no_bluff"] and any(row["decision"] != "no" for row in bluff_review["items"]):
        unresolved.append("无人悍跳判断与座位结论冲突，需先解决")
    if not result["patches"] and not (bluff_review["no_bluff"] or bluff_review["items"]):
        unresolved.append("非空备注没有可应用的结构修正，需先解决备注含义")

    updated = deepcopy(candidate)
    seen_patches: set[str] = set()
    for patch in result["patches"]:
        if (not isinstance(patch, dict) or not isinstance(patch.get("path"), str)
                or "value" not in patch or not isinstance(patch.get("note_quote"), str)
                or not patch["note_quote"] or patch["note_quote"] not in note):
            raise ReviewApplyError(f"{review_id} 备注补丁缺少范围引用")
        pointer = patch["path"]
        if pointer in seen_patches:
            raise ReviewApplyError(f"{review_id} 备注补丁路径重复：{pointer}")
        seen_patches.add(pointer)
        _patch_pointer(updated, pointer, patch["value"])
    for field in IMMUTABLE_DOSSIER_FIELDS:
        if candidate["dossier"].get(field) != updated["dossier"].get(field):
            raise ReviewApplyError(f"{review_id} 备注修改了锁定字段 {field}")
    if unresolved:
        return deepcopy(candidate), deepcopy(result["patches"]), deepcopy(bluff_review), unresolved
    return updated, deepcopy(result["patches"]), deepcopy(bluff_review), []


def _load_note_revisions(path: Path | None, payload: dict, season: str) -> dict[str, dict]:
    if path is None:
        return {}
    document = _read_json(path)
    if (not isinstance(document, dict) or document.get("format") != NOTE_REVISIONS_FORMAT
            or document.get("season") != season or not isinstance(document.get("games"), list)):
        raise ReviewApplyError(f"备注修订文件必须为 {NOTE_REVISIONS_FORMAT}，且赛季为 {season}")
    selected = {game.get("review_id"): game for game in payload["games"]
                if isinstance(game, dict) and game.get("reviewed") is True
                and isinstance(game.get("review_id"), str)}
    revisions: dict[str, dict] = {}
    for revision in document["games"]:
        if not isinstance(revision, dict) or not isinstance(revision.get("review_id"), str):
            raise ReviewApplyError("备注修订缺少复核ID")
        review_id = revision["review_id"]
        game = selected.get(review_id)
        if game is None or review_id in revisions:
            raise ReviewApplyError(f"备注修订必须唯一对应本次已勾选对局：{review_id}")
        if any(field not in revision or revision[field] != game.get(field)
               for field in ("candidate_sha256", "source_sha256", "note")):
            raise ReviewApplyError(f"{review_id} 备注修订与候选版本、原文版本或备注原文不匹配")
        if not isinstance(revision["note"], str) or not revision["note"].strip():
            raise ReviewApplyError(f"{review_id} 备注修订必须绑定非空备注")
        revisions[review_id] = revision
    return revisions


def _manifest_path(candidate: dict, entry: dict, root: Path, season: str) -> Path:
    media = next((row for row in candidate["dossier"].get("files", [])
                  if isinstance(row, dict) and row.get("role") == "manifest"), None)
    page = int(entry.get("page") or 1)
    choices = [entry.get("manifest_path"), entry.get("manifest"), media.get("path") if media else None,
               f"data/raw/bilibili/{entry['bvid']}/p{page:02d}/manifest.json",
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
    suffix = f"_p{int(entry.get('page') or 1):02d}" if int(entry.get("page") or 1) > 1 else ""
    return root / "data" / "games" / season / f"{event_date}_g{number:02d}_{entry['bvid']}{suffix}"


def _source_media(game: dict) -> set[tuple[str, str, int]]:
    source = game.get("source")
    media = source.get("media", []) if isinstance(source, dict) else []
    return {
        (row["bvid"], str(row["cid"]), row["page"])
        for row in media if isinstance(row, dict) and isinstance(row.get("bvid"), str)
        and row.get("cid") is not None and type(row.get("page")) is int
    }


def _check_formal_ownership(root: Path, season: str, item: dict,
                            destination: Path, entry: dict, final_game: dict) -> str:
    relative = destination.relative_to(root).as_posix()
    owned = item.get("formal_dir")
    if owned is not None and owned != relative:
        raise ReviewApplyError(f"{entry['bvid']} 已登记正式目录 {owned}，拒绝换目录覆盖")
    expected_media = (entry["bvid"], str(entry["cid"]), int(entry.get("page") or 1))
    for game_path in (root / "data" / "games" / season).glob("*/game.json"):
        existing = _read_json(game_path)
        if not isinstance(existing, dict):
            raise ReviewApplyError(f"现有正式游戏格式异常：{game_path}")
        same_game = existing.get("id") == final_game.get("id")
        same_source = expected_media in _source_media(existing)
        if (same_game or same_source) and game_path.parent.resolve() != destination.resolve():
            raise ReviewApplyError(f"{entry['bvid']} 已在其他正式目录出现：{game_path.parent}")
    target = destination / "game.json"
    if destination.exists() and owned != relative:
        raise ReviewApplyError(f"正式目录已存在但未由增量状态拥有：{destination}")
    if target.is_file() and _read_json(target) != final_game:
        raise ReviewApplyError(f"已应用的正式游戏与当前复核结果冲突：{target}")
    if destination.exists() and not target.exists() and any(destination.iterdir()):
        raise ReviewApplyError(f"正式目录已有其他内容：{destination}")
    return relative


def _selected_bluffs(game: dict, candidate: dict, *, required: bool) -> dict:
    """Interpret the explicit per-seat controls; a blank is not a conclusion."""
    rows = game.get("bluffs")
    result = {"reviewed": False, "no_bluff": False, "items": []}
    if rows is None and not required:
        return result
    seats = {row["seat"] for row in candidate["dossier"].get("seats", [])
             if isinstance(row, dict) and type(row.get("seat")) is int}
    if not isinstance(rows, list) or len(rows) != len(seats):
        raise ReviewApplyError("悍跳选择必须完整对应本局座位")
    seen: set[int] = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"seat", "decision", "success"}
                or type(row["seat"]) is not int or row["seat"] not in seats or row["seat"] in seen
                or not isinstance(row["decision"], str) or not isinstance(row["success"], str)
                or row["decision"] not in {"", "yes", "no", "uncertain"}
                or row["success"] not in {"", "success", "failure", "uncertain"}
                or row["decision"] != "yes" and row["success"] != ""):
            raise ReviewApplyError("悍跳选择存在重复座位、非法选项或非悍跳座位填写成功结果")
        seen.add(row["seat"])
        if not row["decision"]:
            continue
        result["items"].append({
            "seat": row["seat"], "decision": row["decision"],
            "success": {"success": True, "failure": False}.get(row["success"]),
            "success_selected": row["success"] != "",
            "input_method": "selection",
            "note": f"{row['seat']}号：是否悍跳={row['decision']}；是否成功={row['success'] or '未填写'}。",
        })
    result["reviewed"] = bool(result["items"])
    return result


def _combine_bluff_reviews(note_review: dict, selections: dict) -> dict:
    result = deepcopy(note_review)
    by_seat = {row["seat"]: row for row in result.get("items", [])}
    for row in selections["items"]:
        prior = by_seat.get(row["seat"])
        if prior and prior["decision"] != row["decision"]:
            raise ReviewApplyError(f"{row['seat']}号的备注与悍跳选择冲突，请先明确结论")
        if (prior and row.get("success_selected") and prior.get("success_selected")
                and prior["success"] != row["success"]):
            raise ReviewApplyError(f"{row['seat']}号的备注与悍跳成功选择冲突，请先明确结论")
        if prior and not row.get("success_selected"):
            continue
        by_seat[row["seat"]] = deepcopy(row)
    if result.get("no_bluff") and any(row["decision"] != "no" for row in by_seat.values()):
        raise ReviewApplyError("无人悍跳备注与座位选择冲突")
    result["items"] = sorted(by_seat.values(), key=lambda row: row["seat"])
    result["reviewed"] = bool(result.get("reviewed") or selections.get("reviewed"))
    return result


def _review_supplemental(folder: Path, candidate: dict, season: str) -> dict | None:
    """Carry verified supplemental events into the final game projection."""
    from game_derivations import fingerprint
    path = folder / "supplemental.json"
    value = _read_json(path) if path.is_file() else {}
    if value:
        report_path = folder / "rule_derivations.json"
        if report_path.is_file():
            inputs = _read_json(report_path).get("input_hashes", {})
            if (inputs.get("supplemental") != fingerprint(value)
                    or any(inputs.get(key) != fingerprint(candidate[key]) for key in ("dossier", "voting"))):
                raise ReviewApplyError("补充事实与已复核候选的规则推导不一致")
    events = deepcopy(value.get("events", []))
    for row in (candidate["dossier"].get("_publication_context") or {}).get("supplemental_events", []):
        if row not in events:
            events.append(deepcopy(row))
    if not value and not events:
        return None
    slug = candidate["dossier"]["slug"]
    if value.get("game_slug", slug) != slug:
        raise ReviewApplyError("补充事实与对局slug不一致")
    return {**value, "schema_version": 1, "game_slug": slug, "season": season, "events": events}


def _review_record(candidate: dict, entry: dict, game: dict, note: str, patches: list[dict],
                   manual_sha256: str, bluff_review: dict) -> dict:
    return {
        "format": "masters-incremental-confirmed-v1",
        "season": candidate["dossier"]["season"],
        "review_id": game["review_id"], "bvid": game["bvid"], "cid": game["cid"],
        "page": game["page"], "reviewed": True,
        "manual_sha256": manual_sha256,
        "source_sha256": game["source_sha256"], "candidate_sha256": game["candidate_sha256"],
        "note": note, "patches": deepcopy(patches),
        "evidence": deepcopy(candidate.get("evidence", [])),
        "issues": deepcopy(candidate.get("issues", [])),
        "bluffs_input": deepcopy(game.get("bluffs")),
        "bluffs_review": deepcopy(bluff_review),
        "entry": {"bvid": entry["bvid"], "cid": entry["cid"], "page": entry.get("page", 1)},
    }


def _public_bluffs(game: dict, review_record: dict) -> list[dict]:
    """Project only current-batch manual bluff conclusions into the final game."""
    from website.api.bluffs import evaluate_success, physical_wolf

    review = review_record.get("bluffs_review") or {}
    items = {row["seat"]: row for row in review.get("items", [])}
    seats = {row["seat"]: row for row in game.get("seats", [])}
    physical = {number for number, seat in seats.items() if physical_wolf(game, seat)}
    complete_wolf_list = any(number in physical and row.get("decision") == "yes"
                             for number, row in items.items())
    selected = {number for number, row in items.items()
                if number in physical or row.get("decision") == "yes"}
    output = []
    for number in sorted(physical | selected):
        seat = seats.get(number)
        if seat is None:
            raise ReviewApplyError(f"{game.get('id')} 悍跳备注提及不存在的 {number} 号座位")
        item = items.get(number)
        inferred = item is None and not review.get("no_bluff") and not complete_wolf_list
        decision = item["decision"] if item else "uncertain" if inferred else "no"
        success = None
        success_source = "rules"
        if decision == "yes":
            manual_success = item.get("success") if item else None
            if item and item.get("success_selected") is True:
                success, success_source = manual_success, "user"
            else:
                success = evaluate_success(game, number).get("value")
                success_source = "rules"
        uncertain = decision == "uncertain"
        success_pending = decision == "yes" and success is None
        output.append({
            "game_id": game["id"], "bvid": game["source"]["bvid"],
            "player_id": seat["person_id"], "seat": number, "name": seat["name"],
            "physical_role": seat["role"], "claimed_role": None,
            "decision": decision, "claim_day": None, "actual_claim_day": None,
            "first_day_claim": None,
            "verification_status": ("assistant_inferred" if inferred else
                                     "user_uncertain" if uncertain and item else "user_confirmed"),
            "success": success, "success_source": success_source,
            "manual_included": bool(not physical_wolf(game, seat) and decision == "yes"),
            "needs_review": uncertain or success_pending,
            "requires_user_review": bool(uncertain and item),
            "assistant_pending": inferred,
            "claim_needs_review": uncertain,
            "success_needs_review": success_pending,
        })
    return output


def _final_game(formal: dict, media_manifest: dict, review_record: dict, root: Path) -> dict:
    """Build one website game record from the shared pure public projections."""
    from scripts.board_config import load_canonical_template, load_template
    from website.api.people import load_people
    from website.game_data import _public_game, _public_supplemental_events

    dossier = deepcopy(formal["dossier"])
    board = load_template(dossier["board"], root)
    canonical_board = load_canonical_template(dossier["board"], root)
    board["_public_board"] = {"code": canonical_board["code"], "name": canonical_board["name"]}
    supplemental = formal.get("supplemental")
    supplemental_events = _public_supplemental_events(supplemental) if supplemental else []
    context = deepcopy(dossier.get("_publication_context") or {})
    context["supplemental_events"] = supplemental_events
    terminal = (formal.get("derivations") or {}).get("terminal")
    if terminal is None:
        context.pop("terminal_observation", None)
    elif (not isinstance(terminal, dict) or type(terminal.get("round")) is not int
          or terminal.get("phase") not in {"night", "day"}):
        raise ReviewApplyError(f"{dossier.get('slug')} 规则推导终局边界格式无效")
    else:
        context["terminal_observation"] = {
            "round": terminal["round"], "phase": terminal["phase"],
        }
    dossier["_publication_context"] = context
    names = {seat["name"] for seat in dossier.get("seats", [])}
    person_ids = load_people(root / "website/assets/people.json").ids_for(names)
    game = _public_game(dossier, formal["voting"], formal["endgame"], None, board,
                        person_ids, derivations=formal["derivations"])
    media = {key: media_manifest.get(key) for key in ("bvid", "cid", "page", "url")}
    if (media["bvid"] != game["source"]["bvid"]
            or str(media["cid"]) != str(review_record["cid"])
            or media["page"] != review_record["page"]
            or not isinstance(media["url"], str) or not media["url"]):
        raise ReviewApplyError(f"{review_record['review_id']} 媒体来源与复核身份不一致")
    game["schema_version"] = 1
    game["bluff_review_available"] = True
    game["source"]["media"] = [media]
    game["supplemental_events"] = supplemental_events
    game["bluffs"] = _public_bluffs(game, review_record)
    game.pop("release_id", None)
    game.pop("presentation", None)
    return game


def _prepare_export(review_path: Path, season: str, *, root: Path = ROOT,
                    note_revisions: Path | None = None) -> tuple[dict, list[dict]]:
    payload = _read_json(review_path)
    if (not isinstance(payload, dict) or payload.get("format") not in {REVIEW_FORMAT, REVIEW_FORMAT_V2}
            or payload.get("season") != season or not isinstance(payload.get("games"), list)):
        raise ReviewApplyError(f"复核文件必须为 {REVIEW_FORMAT} 或 {REVIEW_FORMAT_V2}，且赛季为 {season}")
    revisions = _load_note_revisions(note_revisions, payload, season)
    state = load_state(root, season)
    manual_sha = sha256_file(review_path)
    plans: list[dict] = []
    seen: set[str] = set()

    for game in payload["games"]:
        if not isinstance(game, dict):
            raise ReviewApplyError("复核 games 条目必须是对象")
        if type(game.get("reviewed")) is not bool or not isinstance(game.get("note"), str):
            raise ReviewApplyError("复核条目 reviewed/note 类型不正确")
        if not game["reviewed"]:
            continue
        if any(field not in game for field in ("review_id", "bvid", "cid", "page",
                                                "candidate_sha256", "source_sha256")):
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

        selection = _selected_bluffs(game, candidate, required=payload["format"] == REVIEW_FORMAT_V2)
        folder = work_dir(root, season, entry)
        supplemental = _review_supplemental(folder, candidate, season)
        accepted_path = folder / "accepted_candidate.json"
        review_record_path = folder / "accepted_review.json"
        accepted_formal_path = folder / "accepted_formal.json"
        phases = item.get("phases", {})
        revision = revisions.get(game["review_id"])
        saved_review = None
        cached_formal = None
        patches: list[dict] = []
        unresolved: list[str] = []
        bluff_review = {"reviewed": False, "no_bluff": False, "items": []}

        if accepted_path.is_file() and review_record_path.is_file() and accepted_formal_path.is_file():
            prior = _read_json(review_record_path)
            cache_hashes_match = (
                sha256_file(accepted_path) == item.get("accepted_candidate_sha256")
                and sha256_file(review_record_path) == item.get("accepted_review_sha256")
                and sha256_file(accepted_formal_path) == item.get("accepted_formal_sha256")
            )
            if not cache_hashes_match:
                if phases.get("formal") == "done":
                    raise ReviewApplyError(f"{game['review_id']} 已应用 accepted 缓存哈希不匹配")
                prior = None
            if (prior is None or not isinstance(prior, dict)
                    or prior.get("candidate_sha256") != game["candidate_sha256"]
                    or prior.get("source_sha256") != game["source_sha256"]):
                if phases.get("formal") == "done":
                    raise ReviewApplyError(f"{game['review_id']} 已应用版本与当前候选不符")
                prior = None
            if (prior is not None and prior.get("note", "") == game["note"]
                    and prior.get("bluffs_input") == game.get("bluffs")
                    and (revision is None or prior.get("note_revision") == revision)):
                accepted = _read_json(accepted_path)
                cached_formal = _read_json(accepted_formal_path)
                if not isinstance(accepted, dict) or not isinstance(cached_formal, dict):
                    raise ReviewApplyError(f"{game['review_id']} 当前批次 accepted 缓存损坏")
                validate_candidate(accepted, entry, source_path, root=root)
                patches = prior.get("patches", [])
                bluff_review = prior.get("bluffs_review", bluff_review)
                saved_review = prior
            elif phases.get("formal") == "done":
                raise ReviewApplyError(f"{game['review_id']} 已应用备注或悍跳结论不同，拒绝覆盖")

        if saved_review is None:
            accepted = candidate
            if game["note"].strip():
                if revision is None:
                    raise ReviewApplyError(
                        f"{game['review_id']} 有备注；需由当前窗口模型准备结构化修订并传入 --note-revisions")
                accepted, patches, bluff_review, unresolved = _apply_note_result(
                    candidate, game["note"], game["review_id"], revision)
                if not unresolved:
                    accepted = validate_candidate(accepted, entry, source_path, root=root)
            bluff_review = _combine_bluff_reviews(bluff_review, selection)

        from game_records import validate as validate_game
        from voting_core import validate as validate_voting
        validate_game(accepted["dossier"], check_files=True, allow_incomplete=True)
        validate_voting(accepted["voting"])
        from endgame_records import validate as validate_endgame
        endgame = deepcopy(accepted.get("endgame", {
            "schema_version": 1, "game_slug": accepted["dossier"]["slug"], "phases": []}))
        if not isinstance(endgame, dict) or endgame.get("game_slug") != accepted["dossier"]["slug"]:
            raise ReviewApplyError(f"{game['review_id']} 终局与对局slug不一致")
        validate_endgame(endgame)

        prepared_formal = None
        if cached_formal is not None and not unresolved:
            from game_derivations import apply_precomputed, fingerprint
            try:
                if cached_formal.get("endgame") != endgame or cached_formal.get("supplemental") != supplemental:
                    raise ValueError("已缓存的终局或补充资料已变化")
                if cached_formal["derivations"].get("input_hashes", {}).get("endgame") != fingerprint(endgame):
                    raise ValueError("缓存规则派生未绑定当前终局资料")
                checked = apply_precomputed(accepted["dossier"], accepted["voting"],
                                            cached_formal["derivations"])
                if checked["dossier"] != cached_formal["dossier"] or checked["voting"] != cached_formal["voting"]:
                    raise ValueError("缓存规则派生输出不一致")
                prepared_formal = cached_formal
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                if phases.get("formal") == "done":
                    raise ReviewApplyError(f"{game['review_id']} 已应用规则派生失效：{exc}") from exc
        if prepared_formal is None:
            from game_derivations import derive_game
            derived = derive_game(accepted["dossier"], accepted["voting"],
                                  supplemental=supplemental, endgame=endgame)
            prepared_formal = {"dossier": derived["dossier"], "voting": derived["voting"],
                               "endgame": endgame, "derivations": derived["derivations"]}
            if supplemental is not None:
                prepared_formal["supplemental"] = supplemental
        validate_game(prepared_formal["dossier"], check_files=True, allow_incomplete=True)
        validate_voting(prepared_formal["voting"])

        media_entry = {**entry, "manifest_path": item.get("manifest_path", entry.get("manifest_path"))}
        manifest_path = _manifest_path(accepted, media_entry, root, season)
        from media_ingest import validate_media
        checked_media = validate_media(manifest_path, game["bvid"], game["page"])
        manifest = checked_media["manifest"]
        if str(manifest.get("cid")) != str(game["cid"]):
            raise ReviewApplyError(f"{game['review_id']} 媒体manifest CID与复核身份不一致")

        note = saved_review.get("note", "") if saved_review else game["note"]
        manual_hash = saved_review.get("manual_sha256", manual_sha) if saved_review else manual_sha
        review_record = _review_record(accepted, entry, game, note, patches, manual_hash, bluff_review)
        if revision is not None:
            review_record["note_revision"] = deepcopy(revision)
        elif saved_review and "note_revision" in saved_review:
            review_record["note_revision"] = deepcopy(saved_review["note_revision"])
        final_game = _final_game(prepared_formal, manifest, review_record, root)
        destination = _formal_path(root, season, entry, prepared_formal["dossier"])
        relative = _check_formal_ownership(root, season, item, destination, entry, final_game)
        plans.append({
            "key": key, "game": game, "item": item, "entry": entry,
            "candidate": accepted, "prepared_formal": prepared_formal,
            "final_game": final_game, "accepted_path": accepted_path,
            "accepted_formal_path": accepted_formal_path,
            "review_record_path": review_record_path, "review_record": review_record,
            "manifest": manifest_path, "formal_dir": destination,
            "formal_dir_relative": relative, "source_path": source_path,
            "candidate_path": candidate_path, "patches": patches, "unresolved": unresolved,
        })
    return state, plans


def _persist_accepted(plan: dict, state: dict, season: str, root: Path, *,
                      claim_owner: bool = True) -> None:
    if (sha256_file(plan["candidate_path"]) != plan["game"]["candidate_sha256"]
            or sha256_file(plan["source_path"]) != plan["game"]["source_sha256"]):
        raise ReviewApplyError(f"{plan['game']['review_id']} 原文或候选在预检后变化")
    item = plan["item"]
    if claim_owner:
        item["formal_dir"] = plan["formal_dir_relative"]
    write_json(plan["accepted_path"], plan["candidate"])
    write_json(plan["review_record_path"], plan["review_record"])
    write_json(plan["accepted_formal_path"], plan["prepared_formal"])
    item["accepted_candidate_path"] = plan["accepted_path"].relative_to(root).as_posix()
    item["accepted_candidate_sha256"] = sha256_file(plan["accepted_path"])
    item["review_record_path"] = plan["review_record_path"].relative_to(root).as_posix()
    item["accepted_review_sha256"] = sha256_file(plan["review_record_path"])
    item["accepted_formal_path"] = plan["accepted_formal_path"].relative_to(root).as_posix()
    item["accepted_formal_sha256"] = sha256_file(plan["accepted_formal_path"])
    item["prepared_candidate_sha256"] = plan["game"]["candidate_sha256"]
    item["prepared_source_sha256"] = plan["game"]["source_sha256"]
    save_state(root, season, state)


def _write_formal(plan: dict, state: dict, season: str, root: Path) -> None:
    if (sha256_file(plan["candidate_path"]) != plan["game"]["candidate_sha256"]
            or sha256_file(plan["source_path"]) != plan["game"]["source_sha256"]):
        raise ReviewApplyError(f"{plan['game']['review_id']} 原文或候选在正式归档前变化")
    destination = plan["formal_dir"]
    target = destination / "game.json"
    destination.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        if _read_json(target) != plan["final_game"]:
            raise ReviewApplyError(f"已应用的正式游戏与当前复核结果冲突：{target}")
    else:
        write_json(target, plan["final_game"])
    item = plan["item"]
    item["formal_dir"] = plan["formal_dir_relative"]
    item["phases"] = {"formal": "done"}
    item["applied"] = True
    item["game_sha256"] = sha256_file(target)
    save_state(root, season, state)


def apply_review(review_path: Path, *, season: str, root: Path = ROOT,
                 apply: bool = False, publish: bool = False,
                 note_revisions: Path | None = None) -> dict:
    if publish and not apply:
        raise ReviewApplyError("--publish 必须与 --apply 一起使用")
    state, plans = _prepare_export(review_path, season, root=root, note_revisions=note_revisions)
    blockers = [f"{plan['game']['review_id']}: {'; '.join(plan['unresolved'])}"
                for plan in plans if plan["unresolved"]]
    report = {
        "season": season, "reviewed_games": len(plans),
        "apply": apply, "publish": publish,
        "state": "needs_resolution" if blockers else "prepared",
        "blocked_games": blockers,
        "games": [{
            "review_id": plan["game"]["review_id"],
            "formal_dir": plan["formal_dir_relative"],
            "candidate_sha256": plan["game"]["candidate_sha256"],
            "source_sha256": plan["game"]["source_sha256"],
            "patches": deepcopy(plan["patches"]),
            "unresolved": list(plan["unresolved"]),
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
        return report
    if not plans:
        report["state"] = "nothing_to_apply"
        return report

    # Every selected game's source, candidate, media, derivation, and target path
    # has been checked before the first final JSON is written.
    for plan in plans:
        _persist_accepted(plan, state, season, root)
    for plan in plans:
        _write_formal(plan, state, season, root)
    if publish:
        exporter = root / "website/static_publish/export_static.py"
        subprocess.run([sys.executable, str(exporter), "--root", str(root)], cwd=root, check=True)
    report["state"] = "completed"
    report["games"] = [{"review_id": plan["game"]["review_id"],
                        "formal_dir": plan["formal_dir_relative"],
                        "phases": deepcopy(plan["item"].get("phases", {})),
                        "applied": plan["item"].get("applied", False)}
                       for plan in plans]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_export", type=Path, help=f"{REVIEW_FORMAT} JSON")
    parser.add_argument("--season", choices=season_codes(ROOT), required=True)
    parser.add_argument("--apply", action="store_true", help="生成正式 game.json")
    parser.add_argument("--publish", action="store_true", help="应用后导出本地静态JSON")
    parser.add_argument("--note-revisions", type=Path,
                        help="当前窗口模型准备的结构化备注修订JSON")
    args = parser.parse_args(argv)
    try:
        report = apply_review(args.review_export, season=args.season, apply=args.apply,
                              publish=args.publish, note_revisions=args.note_revisions)
    except (ReviewApplyError, ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"state": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2),
              file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
