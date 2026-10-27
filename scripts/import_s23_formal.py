"""Prepare, validate, and atomically import the current S23 formal snapshot.

The source of game facts is candidate_dossiers in the current review snapshot.
This command never reads a dossier.reviewed.json or writes the database unless
--import-db is supplied explicitly.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from database import ReviewError, connect
import game_records
import voting_records

SCOPE_PATH = ROOT / "config/S23_game_scope.json"
RULES_PATH = ROOT / "config/S23_formal_rules.json"
REVIEW_RULES_PATH = ROOT / "config/S23_review_rules.json"
REPORT_PATH = ROOT / "data/reports/S23_逐局复核进度.json"
DAILY_REPORT_PATH = ROOT / "data/reports/S23_逐日复核交付_20261026.json"
AUDIT_REPORT_PATH = ROOT / "data/reports/S23_逐局复核校验.json"
AUTHORIZATION_PATH = ROOT / "data/extractions/S23/用户授权_20261026_正式入库与网站上线.txt"
EULOGY_POLICY_PATH = ROOT / "data/extractions/S23/处理说明_20261026_10号遗言诈身份计数口径.txt"
FORMAL_FILES = (
    "dossier.json", "voting.json", "endgame.json", "supplemental.json",
    "vote_control.json", "formal_context.json", "formal_import_receipt.json",
)
EVENT_FIELDS = (
    "slot", "action", "actor", "targets", "result", "start_seat", "direction",
    "votes", "random_point", "speech_scope", "availability", "effects",
)
PUBLIC_EVENT_FLAGS = ("invalidated", "blocked_by_game_end")
_HASH_CACHE: dict[tuple[str, int, int], str] = {}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    path = path.resolve()
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key in _HASH_CACHE:
        return _HASH_CACHE[key]
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    _HASH_CACHE[key] = digest
    return digest


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"无法读取JSON {path.relative_to(ROOT)}: {exc}") from exc


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(payload, encoding="utf-8", newline="\n")
    temp.replace(path)


def load_inputs() -> tuple[dict, dict, dict, dict, dict]:
    scope = read_json(SCOPE_PATH)
    rules = read_json(RULES_PATH)
    progress = read_json(REPORT_PATH)
    daily = read_json(DAILY_REPORT_PATH)
    audit = read_json(AUDIT_REPORT_PATH)
    if scope.get("season") != "S23" or rules.get("season") != "S23":
        raise ReviewError("S23 scope/formal rules season mismatch")
    snapshot_id = progress.get("snapshot_id")
    if snapshot_id != scope.get("authoritative_snapshot_id") or snapshot_id != rules.get("authoritative_snapshot_id"):
        raise ReviewError("当前复核快照与S23正式入库配置不一致")
    if daily.get("snapshot_id") != snapshot_id:
        raise ReviewError("逐日复核交付与逐局复核进度不是同一快照")
    if audit.get("season") != "S23" or audit.get("planned") != 75 or audit.get("errors"):
        raise ReviewError("S23逐局复核校验报告未通过")
    if progress.get("planned") != 75 or len(progress.get("candidate_dossiers", [])) != 75:
        raise ReviewError("正式范围必须恰好包含复核报告当前快照的75个候选档案")
    if progress.get("missing_ai_reviews"):
        raise ReviewError("候选报告仍缺AI复核文件")
    if not AUTHORIZATION_PATH.is_file() or "OK，开始写入数据库，并上线到网站吧" not in AUTHORIZATION_PATH.read_text(encoding="utf-8"):
        raise ReviewError("缺少S23整体入库与上线授权记录")
    if not EULOGY_POLICY_PATH.is_file():
        raise ReviewError("缺少10号遗言诈身份的单独统计口径记录")
    mapping = rules.get("board_code_map", {})
    if set(mapping) != {"mechanical_wolf_seer", "mixed_blood", "guile_realm", "masquerade", "treasure_master", "qingqiu_night", "magic_duel"}:
        raise ReviewError("S23 board_code_map覆盖范围不完整")
    return scope, rules, progress, daily, audit


def bvid_from_slug(slug: str) -> str:
    match = re.search(r"(BV[0-9A-Za-z]+)", slug)
    if not match:
        raise ReviewError(f"无法从slug读取BVID: {slug}")
    return match.group(1)


def source_record(role: str, path: Path, kind: str, external_key: str) -> dict:
    if not path.is_file() or not path.resolve().is_relative_to((ROOT / "data").resolve()):
        raise ReviewError(f"来源文件缺失或越界: {path}")
    return {"role": role, "path": rel(path), "kind": kind,
            "platform": "bilibili", "external_key": external_key}


def resolve_source_files(dossier: dict) -> tuple[list[dict], dict]:
    bvid = bvid_from_slug(dossier["slug"])
    manifest_path = ROOT / "data/raw/bilibili" / bvid / "p01/manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("bvid") != bvid or manifest.get("page") != 1:
        raise ReviewError(f"媒体manifest的BVID/page与对局不匹配: {bvid}")
    cid = str(manifest.get("cid"))
    external_key = f"{bvid}:{cid}"
    raw_dir = manifest_path.parent
    audio_meta = manifest.get("audio") or {}
    raw_audio = raw_dir / str(audio_meta.get("file", ""))
    if not raw_audio.is_file() or sha256_file(raw_audio) != audio_meta.get("sha256"):
        raise ReviewError(f"原始音轨与manifest哈希不一致: {bvid}")

    files: list[dict] = []
    for item in dossier.get("files", []):
        path = (ROOT / item["path"]).resolve()
        rec = dict(item)
        rec["path"] = rel(path)
        rec["platform"] = rec.get("platform") or "bilibili"
        rec["external_key"] = rec.get("external_key") or external_key
        if rec["platform"] != "bilibili" or rec["external_key"] != external_key:
            raise ReviewError(f"候选来源外键与媒体manifest不匹配: {bvid}/{rec.get('role')}")
        if not path.is_file() or not path.resolve().is_relative_to((ROOT / "data").resolve()):
            raise ReviewError(f"候选所列来源文件不存在或越界: {rec['path']}")
        if rec.get("role") == "audio" and sha256_file(path) != audio_meta.get("sha256"):
            raise ReviewError(f"候选音频与manifest音轨哈希不一致: {bvid}")
        files.append(rec)

    by_role = {f["role"]: f for f in files}
    if len(by_role) != len(files):
        raise ReviewError(f"一个对局有重复来源角色: {bvid}")
    required = {
        "audio": (raw_audio, "audio"),
        "manifest": (manifest_path, "manifest"),
        "metadata": (raw_dir / "metadata.raw.json", "metadata"),
    }
    for role, (path, kind) in required.items():
        if role not in by_role:
            files.append(source_record(role, path, kind, external_key))
    if "subtitle" not in by_role:
        subtitle_meta = next((t for t in (manifest.get("subtitles") or {}).get("tracks", [])
                              if t.get("language") == "ai-zh"), None)
        subtitle_name = (subtitle_meta or {}).get("file") or "subtitle.01.raw.json"
        subtitle = raw_dir / subtitle_name
        if subtitle.is_file():
            files.append(source_record("subtitle", subtitle, "subtitle", external_key))
    files.sort(key=lambda x: (x["role"], x["path"]))
    return files, {"bvid": bvid, "cid": cid, "external_key": external_key,
                   "manifest_path": rel(manifest_path), "manifest_sha256": sha256_file(manifest_path),
                   "audio_sha256": audio_meta["sha256"], "audio_path": rel(raw_audio),
                   "audio_bytes": raw_audio.stat().st_size}


def empty_event(slot: str) -> dict:
    return {"slot": slot, "action": "unknown", "actor": None, "targets": [],
            "result": None, "start_seat": None, "direction": None, "votes": [],
            "random_point": None, "speech_scope": None, "availability": None, "effects": []}


def normalize_event(event: dict, *, slug: str, round_no: int, phase: str,
                    extensions: list[dict], transforms: list[dict], voting_facts: dict | None = None) -> dict:
    extra = {k: copy.deepcopy(v) for k, v in event.items() if k not in EVENT_FIELDS}
    if extra:
        extensions.append({"round": round_no, "phase": phase, "slot": event.get("slot"), "fields": extra})
    normalized = empty_event(str(event.get("slot", "")))
    for key in EVENT_FIELDS:
        if key in event:
            normalized[key] = copy.deepcopy(event[key])
    for key in PUBLIC_EVENT_FLAGS:
        if key in event:
            normalized[key] = copy.deepcopy(event[key])
    slot_kind = {"sheriff_vote": "sheriff", "exile_vote": "exile", "second_exile_vote": "exile"}.get(normalized["slot"])
    if normalized["action"] == "vote" and not normalized["votes"]:
        ballot_group = [ballot for ballot in (voting_facts or {}).get("ballots", [])
                        if ballot.get("day") == round_no and ballot.get("kind") == slot_kind]
        if not slot_kind or not ballot_group:
            raise ReviewError(f"{slug}/{round_no}/{normalized['slot']}: 已发生投票但voting.candidate无对应逐人票型")
        normalized["votes"] = [
            {"round": ballot["number"], "voter": vote["voter"], "target": vote["target"],
             "abstained": vote["state"] == "abstained"}
            for ballot in ballot_group for vote in ballot["votes"]
        ]
        transforms.append({"round": round_no, "phase": phase, "slot": normalized["slot"],
                           "from": [], "to": copy.deepcopy(normalized["votes"]),
                           "basis": "candidate action/result indicates a vote; paired to voting.candidate ballots by day/kind",
                           "ballot_ids": [ballot["id"] for ballot in ballot_group]})
    if normalized["votes"] and any(set(vote) != {"round", "voter", "target", "abstained"} for vote in normalized["votes"]):
        pair_key = lambda vote: (vote.get("voter"), -1 if vote.get("target") is None else vote.get("target"))
        raw_pairs = sorted(pair_key(vote) for vote in normalized["votes"])
        matches = []
        if voting_facts is not None and slot_kind is not None:
            for ballot in voting_facts.get("ballots", []):
                ballot_pairs = sorted(pair_key(vote) for vote in ballot.get("votes", []))
                if ballot.get("day") == round_no and ballot.get("kind") == slot_kind and ballot_pairs == raw_pairs:
                    matches.append(ballot)
        if len(matches) != 1:
            raise ReviewError(f"{slug}/{round_no}/{normalized['slot']}: 候选事件票型无法唯一匹配 voting.candidate ballot")
        ballot = matches[0]
        normalized["votes"] = [{"round": ballot["number"], "voter": vote["voter"],
                                 "target": vote["target"], "abstained": vote["target"] is None}
                                for vote in normalized["votes"]]
        transforms.append({"round": round_no, "phase": phase, "slot": normalized["slot"],
                           "from": copy.deepcopy(event["votes"]), "to": copy.deepcopy(normalized["votes"]),
                           "basis": f"paired to voting.candidate ballot {ballot['id']} (day/kind/seat-target set match)"})
    if normalized["slot"] == "treasure_choice" and normalized["action"] == "choose" and isinstance(normalized["result"], str):
        treasure_roles = ("盗宝大师", "摄梦人", "通灵师", "蒙面人", "平民", "毒师", "猎人", "狼王", "狼人")
        if normalized["result"] in treasure_roles:
            selected_role = normalized["result"]
        else:
            match = re.search(r"(?:选择|选取)([^，。；;]+?)(?:身份)?$", normalized["result"])
            selected_role = match.group(1).strip() if match and match.group(1).strip() in treasure_roles else None
        if selected_role and normalized["result"] != selected_role:
            transforms.append({"round": round_no, "phase": phase, "slot": "treasure_choice",
                               "from": normalized["result"], "to": selected_role,
                               "basis": "candidate wording normalized to the exact role name in the S23 treasure pool"})
            normalized["result"] = selected_role
    if (normalized["slot"] == "sheriff_result" and normalized["action"] == "elected"
            and normalized["actor"] is None and not normalized["targets"]
            and isinstance(normalized["result"], str) and "延期" in normalized["result"]
            and ("平票" in normalized["result"] or "PK" in normalized["result"])):
        normalized["action"] = "deferred"
        transforms.append({"round": round_no, "phase": phase, "slot": "sheriff_result",
                           "from": "elected", "to": "deferred",
                           "basis": "candidate result explicitly records tie/PK delayed; no elected seat is recorded"})
    if (slug == "bili-BV1zmpB6PEcF-p01-g02" and round_no == 3 and phase == "night"
            and normalized["slot"] == "wolf_attack" and normalized["action"] == "unavailable"
            and event.get("invalidated") is True and event.get("confirmation_status") == "user_confirmed"):
        normalized["action"] = "invalidated_by_dq"
        transforms.append({"round": 3, "phase": "night", "slot": "wolf_attack",
                           "from": "unavailable", "to": "invalidated_by_dq",
                           "basis": "user-confirmed per-game DQ supplement"})
    return normalized


def sidecar(path: Path, slug: str) -> tuple[dict, dict]:
    value = read_json(path)
    if value.get("game_slug") != slug:
        raise ReviewError(f"旁证game_slug不匹配: {rel(path)}")
    return value, {"path": rel(path), "sha256": sha256_file(path)}


def matching_context_rows(values: list[dict], bvid: str) -> list[dict]:
    return [copy.deepcopy(row) for row in values if row.get("bvid") == bvid]


def prepare_game(candidate_path: Path, scope: dict, rules: dict, progress: dict,
                 daily: dict, audit: dict) -> dict:
    candidate_path = candidate_path.resolve()
    if not candidate_path.is_relative_to((ROOT / "data/games/S23").resolve()) or candidate_path.name != "dossier.candidate.json":
        raise ReviewError(f"候选路径不属于S23当前候选目录: {candidate_path}")
    source = read_json(candidate_path)
    if source.get("season") != "S23":
        raise ReviewError(f"非S23候选进入正式范围: {candidate_path}")
    slug = source["slug"]
    bvid = bvid_from_slug(slug)
    storage_code = rules["board_code_map"].get(source.get("board"))
    if not storage_code:
        raise ReviewError(f"缺少canonical board映射: {source.get('board')}")
    template_path = ROOT / "config/board_templates" / f"{storage_code}.json"
    template = read_json(template_path)
    if template.get("code") != storage_code:
        raise ReviewError(f"S23版型模板代码不一致: {template_path}")

    source_files, media = resolve_source_files(source)
    ai_path = candidate_path.with_name("ai_review.json")
    ai_review = read_json(ai_path)
    if ai_review.get("slug") not in {None, slug} and ai_review.get("game_slug") not in {None, slug}:
        raise ReviewError(f"ai_review对局关联不匹配: {rel(ai_path)}")
    ai_hash = sha256_file(ai_path)
    sidecars = {}
    sidecar_paths = {}
    for key, filename in (("voting", "voting.candidate.json"), ("endgame", "endgame.candidate.json"),
                          ("supplemental", "supplemental.candidate.json"), ("vote_control", "vote_control.candidate.json")):
        path = candidate_path.with_name(filename)
        value, record = sidecar(path, slug)
        sidecars[key] = value
        sidecar_paths[key] = record
    voting_records.validate(sidecars["voting"])

    daily_path = ROOT / "data/extractions/S23/game_reviews" / bvid / "daily_audit.json"
    daily_audit = read_json(daily_path)
    if daily_audit.get("bvid") != bvid:
        raise ReviewError(f"逐日复核审计与BVID不匹配: {bvid}")

    source_extensions: list[dict] = []
    transforms: list[dict] = []
    missing_slots: list[dict] = []
    normalized = copy.deepcopy(source)
    # The public dossier keeps the canonical name for the website. The database
    # import uses a temporary copy with the S23 namespace.
    normalized["board"] = source["board"]
    normalized["files"] = source_files
    templates_by_phase = {phase: template[phase + "_slots"] for phase in ("night", "day")}
    all_unknown_before = 0
    all_unknown_after = 0
    for round_ in normalized["rounds"]:
        raw_round = next(r for r in source["rounds"] if r["number"] == round_["number"])
        for phase in ("night", "day"):
            raw_events = raw_round.get(phase, [])
            by_slot = {}
            for raw_event in raw_events:
                slot = raw_event.get("slot")
                if slot in by_slot:
                    raise ReviewError(f"同一轮重复事件槽: {slug}/{round_['number']}/{phase}/{slot}")
                by_slot[slot] = normalize_event(raw_event, slug=slug, round_no=round_["number"],
                                                phase=phase, extensions=source_extensions, transforms=transforms,
                                                voting_facts=sidecars["voting"])
                if raw_event.get("action") == "unknown":
                    all_unknown_before += 1
            ordered = []
            terminal_index = None
            for index, slot_def in enumerate(templates_by_phase[phase]):
                slot = slot_def["code"]
                event = by_slot.pop(slot, None)
                if event is None:
                    event = empty_event(slot)
                    missing_slots.append({"round": round_["number"], "phase": phase,
                                          "slot": slot, "action": "unknown"})
                ordered.append(event)
                if slot == "game_end" and event["action"] != "unknown":
                    terminal_index = index
                    break
            if by_slot:
                raise ReviewError(f"候选事件未映射到S23固定模板: {slug}/{phase}/{sorted(by_slot)}")
            if terminal_index is not None:
                for later in templates_by_phase[phase][terminal_index + 1:]:
                    missing_slots.append({"round": round_["number"], "phase": phase,
                                          "slot": later["code"], "action": "not_created_after_game_end"})
            round_[phase] = ordered
            all_unknown_after += sum(e["action"] == "unknown" for e in ordered)
    # Check the special user-confirmed transformations remain separate from the
    # regular game action fields and are not rewritten as pass/no-op.
    if slug == "bili-BV1zmpB6PEcF-p01-g02":
        event = next(e for r in normalized["rounds"] if r["number"] == 3 for e in r["night"] if e["slot"] == "wolf_attack")
        if event["action"] != "invalidated_by_dq" or event["actor"] != 8 or event["targets"]:
            raise ReviewError("10月13日DQ狼刀用户确认补正未保留")
        if not any(e.get("event", {}).get("action") == "disqualify" for e in sidecars["supplemental"].get("events", [])):
            raise ReviewError("10月13日DQ旁证事件缺失")

    role_counts = Counter(seat.get("role") for seat in normalized["seats"])
    if source["board"] in rules.get("role_profiles", {}):
        expected = Counter(rules["role_profiles"][source["board"]])
        if role_counts != expected:
            raise ReviewError(f"S23新板型角色数量不匹配: {slug}")
    if source["board"] == "masquerade":
        group = rules["role_profiles"]["masquerade_role_group"]
        if sum(role_counts[x] for x in group["one_of"]) != group["count"]:
            raise ReviewError(f"假面舞会白神/白痴替代槽位数量不符: {slug}")

    db_dossier = copy.deepcopy(normalized)
    db_dossier["board"] = storage_code
    for round_ in db_dossier["rounds"]:
        for phase in ("night", "day"):
            for event in round_[phase]:
                for flag in (*PUBLIC_EVENT_FLAGS, "confirmation_status"):
                    event.pop(flag, None)
    try:
        game_records.validate(db_dossier, allow_incomplete=True)
    except ReviewError as exc:
        raise ReviewError(f"{slug}: {exc}") from exc
    source_hashes = {
        "candidate": {"path": rel(candidate_path), "sha256": sha256_file(candidate_path)},
        "ai_review": {"path": rel(ai_path), "sha256": ai_hash},
        "daily_audit": {"path": rel(daily_path), "sha256": sha256_file(daily_path)},
        **sidecar_paths,
    }
    for entry in source_files:
        path = ROOT / entry["path"]
        source_hashes[f"source:{entry['role']}:{entry['path']}"] = {
            "path": entry["path"], "sha256": sha256_file(path), "kind": entry["kind"],
            "external_key": entry["external_key"],
        }
    source_hashes["media_manifest"] = {"path": media["manifest_path"], "sha256": media["manifest_sha256"]}
    source_hashes["audio_manifest"] = {"path": media["audio_path"], "sha256": media["audio_sha256"]}

    review_rules = read_json(REVIEW_RULES_PATH)
    accepted_rules = {item["id"]: item for item in review_rules.get("rules", [])}
    terminal_observations = []
    for source_round in source["rounds"]:
        for phase in ("night", "day"):
            for event in source_round[phase]:
                if event.get("blocked_by_game_end") is True:
                    rule = accepted_rules.get("last_god_hunter_terminal_user_confirmed", {})
                    terminal_observations.append({
                        "round": source_round["number"], "phase": phase, "slot": event["slot"],
                        "action": event["action"], "actor": event.get("actor"),
                        "blocked_by_game_end": True,
                        "source_confirmation_status": event.get("confirmation_status"),
                        "public_text": "终局结算已结束对局；该猎人没有后续开枪窗口。此记录表示结算阻断，不表示猎人主动不开枪。",
                        "result": event.get("result"),
                        "rule_id": rule.get("id"), "rule_statement": rule.get("statement"),
                        "rule_evidence": copy.deepcopy(rule.get("evidence", [])),
                    })
    unpublished_terminal_checks = [
        copy.deepcopy(row) for row in daily.get("unpublished_source_records", [])
        if row.get("bvid") == bvid and "seer_check" in str(row.get("field", ""))
    ]
    for row in unpublished_terminal_checks:
        row["public_text"] = "终局查验未记录；可能因前序技能或狼刀结算已结束对局。保留未知，不补目标，也不据此确定从未查验。"
        row["status"] = row.get("status") or "not_observed"
    public_notes = [row["public_text"] for row in unpublished_terminal_checks]
    if bvid == "BV1U3p86dEJY":
        public_notes.append("10号在遗言阶段自称通灵师；作为遗言诈身份候选单列，暂不计入已确认的常规悍跳次数，具体统计口径仍待用户确认。")
    # Publish only the boundary fields confirmed by daily_audit. Keep the full
    # source explanation/evidence in the separate review context and bind the
    # source file hash above; never infer a later phase from a game-end event.
    source_terminal_observation = daily_audit.get("terminal_observation")
    terminal_observation = None
    if isinstance(source_terminal_observation, dict):
        if type(source_terminal_observation.get("round")) is not int or source_terminal_observation.get("phase") not in ("night", "day"):
            raise ReviewError(f"逐日复核终局观察字段无效: {bvid}")
        terminal_observation = {
            "round": source_terminal_observation["round"],
            "phase": source_terminal_observation["phase"],
        }

    formal_context = {
        "schema_version": 1,
        "game_slug": slug,
        "source_snapshot_id": progress["snapshot_id"],
        "authorization": {
            "scope": scope["scope_code"],
            "record_path": rel(AUTHORIZATION_PATH),
            "record_sha256": sha256_file(AUTHORIZATION_PATH),
            "field_level_confirmation": "not_claimed_by_batch_authorization",
        },
        "source_hashes": source_hashes,
        "normalization": {
            "canonical_board": source["board"],
            "database_board_code": storage_code,
            "filled_slots_as_unknown": [x for x in missing_slots if x["action"] == "unknown"],
            "not_created_after_game_end": [x for x in missing_slots if x["action"] == "not_created_after_game_end"],
            "source_event_extensions": source_extensions,
            "explicit_transformations": transforms,
            "unknown_count_before": all_unknown_before,
            "unknown_count_after": all_unknown_after,
            "round_numbers_before": [r["number"] for r in source["rounds"]],
            "round_numbers_after": [r["number"] for r in normalized["rounds"]],
        },
        "terminal_observations": terminal_observations,
        "unpublished_terminal_checks": unpublished_terminal_checks,
        "public_notes": public_notes,
        "terminal_observation": terminal_observation,
        "separate_review_context": {
            "daily_human_questions": copy.deepcopy(daily_audit.get("human_questions", [])),
            "bluff_overrides": copy.deepcopy(daily_audit.get("bluff_overrides", [])),
            "daily_terminal_observation_source": copy.deepcopy(source_terminal_observation),
            "report_human_questions": matching_context_rows(daily.get("required_user_questions", []), bvid),
            "report_unpublished_source_items": matching_context_rows(daily.get("unpublished_source_records", []), bvid),
            "eulogy_statistic_policy": ({"path": rel(EULOGY_POLICY_PATH), "sha256": sha256_file(EULOGY_POLICY_PATH),
                                         "handling": rules["separate_review_context"]["eulogy_bluff_statistic"]}
                                        if bvid == "BV1U3p86dEJY" else None),
        },
        "field_confirmation_note": "批量授权不代表逐字段确认；candidate中unknown保持unknown。",
    }
    if all_unknown_after < all_unknown_before:
        raise ReviewError(f"未知项在正式转换中减少: {slug}")
    if formal_context["normalization"]["round_numbers_before"] != formal_context["normalization"]["round_numbers_after"]:
        raise ReviewError(f"导出时不得新增或删除实际对局轮次: {slug}")

    return {
        "slug": slug, "bvid": bvid, "candidate_path": rel(candidate_path),
        "candidate_sha256": sha256_file(candidate_path), "canonical_board": source["board"],
        "storage_board": storage_code, "dossier": normalized, "db_dossier": db_dossier,
        "voting": sidecars["voting"], "endgame": sidecars["endgame"],
        "supplemental": sidecars["supplemental"], "vote_control": sidecars["vote_control"],
        "formal_context": formal_context, "source_files": source_files,
        "media": media, "source_hashes": source_hashes,
        "normalization": formal_context["normalization"],
    }


def build_batch() -> dict:
    scope, rules, progress, daily, audit = load_inputs()
    games = [prepare_game(ROOT / rel_path, scope, rules, progress, daily, audit)
             for rel_path in progress["candidate_dossiers"]]
    slugs = [game["slug"] for game in games]
    if len(slugs) != 75 or len(set(slugs)) != 75:
        raise ReviewError("候选slug必须唯一且恰好75局")
    board_counts = Counter(game["canonical_board"] for game in games)
    if set(board_counts) != set(rules["board_code_map"]):
        raise ReviewError("正式候选版型集合与S23映射不一致")
    source_hashes = {
        "scope": sha256_file(SCOPE_PATH),
        "formal_rules": sha256_file(RULES_PATH),
        "review_rules": sha256_file(REVIEW_RULES_PATH),
        "snapshot_report": sha256_file(REPORT_PATH),
        "daily_review_report": sha256_file(DAILY_REPORT_PATH),
        "validation_report": sha256_file(AUDIT_REPORT_PATH),
        "authorization": sha256_file(AUTHORIZATION_PATH),
        "eulogy_statistic_policy": sha256_file(EULOGY_POLICY_PATH),
    }
    batch_key = f"{scope['scope_code']}:{progress['snapshot_id']}:{source_hashes['formal_rules']}:{source_hashes['authorization']}"
    return {"scope": scope, "rules": rules, "progress": progress, "daily": daily,
            "audit": audit, "games": games, "board_counts": board_counts,
            "source_hashes": source_hashes, "batch_key": batch_key}


def expected_formal_outputs(game: dict) -> dict[str, Any]:
    return {
        "dossier.json": game["dossier"],
        "voting.json": game["voting"],
        "endgame.json": game["endgame"],
        "supplemental.json": game["supplemental"],
        "vote_control.json": game["vote_control"],
        "formal_context.json": game["formal_context"],
    }


def materialize(batch: dict) -> dict:
    aggregate = {"generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                 "snapshot_id": batch["progress"]["snapshot_id"], "batch_key": batch["batch_key"],
                 "scope_code": batch["scope"]["scope_code"], "candidate_game_count": len(batch["games"]),
                 "board_counts": dict(batch["board_counts"]), "games": []}
    for game in batch["games"]:
        folder = ROOT / Path(game["candidate_path"]).parent
        formal_hashes = {}
        for filename, payload in expected_formal_outputs(game).items():
            path = folder / filename
            write_json(path, payload)
            formal_hashes[filename] = sha256_file(path)
        receipt = {
            "schema_version": 1, "game_slug": game["slug"], "batch_key": batch["batch_key"],
            "snapshot_id": batch["progress"]["snapshot_id"], "candidate_path": game["candidate_path"],
            "candidate_sha256": game["candidate_sha256"], "canonical_board": game["canonical_board"],
            "storage_board": game["storage_board"], "formal_files": formal_hashes,
            "source_files": game["source_hashes"], "normalization": game["normalization"],
            "overall_batch_authorized": True,
            "field_confirmation": "not_claimed_by_batch_authorization",
        }
        write_json(folder / "formal_import_receipt.json", receipt)
        aggregate["games"].append({"slug": game["slug"], "path": rel(folder / "dossier.json"),
                                   "candidate_sha256": game["candidate_sha256"],
                                   "formal_file_hashes": formal_hashes,
                                   "unknown_count_before": game["normalization"]["unknown_count_before"],
                                   "unknown_count_after": game["normalization"]["unknown_count_after"],
                                   "rounds": len(game["dossier"]["rounds"]),
                                   "source_audio_sha256": game["media"]["audio_sha256"]})
    report_path = ROOT / "data/reports/S23_正式入库预检.json"
    write_json(report_path, {**aggregate, "status": "prepared; database not written", "database_write": False,
                             "source_hashes": batch["source_hashes"]})
    return {"report": rel(report_path), "games": len(batch["games"]), "batch_key": batch["batch_key"]}


def verify_prepared_files(batch: dict) -> list[str]:
    errors = []
    for game in batch["games"]:
        folder = ROOT / Path(game["candidate_path"]).parent
        for filename, payload in expected_formal_outputs(game).items():
            path = folder / filename
            if not path.is_file():
                errors.append(f"missing:{rel(path)}")
            elif read_json(path) != payload:
                errors.append(f"stale:{rel(path)}")
        receipt_path = folder / "formal_import_receipt.json"
        if not receipt_path.is_file():
            errors.append(f"missing:{rel(receipt_path)}")
    return errors


def db_season_fingerprint(conn, code: str) -> dict:
    season = conn.execute("SELECT id FROM seasons WHERE code=%s", (code,)).fetchone()
    if season is None:
        return {"season_exists": False}
    sid = season["id"]
    queries = {
        "games": "SELECT count(*) AS n FROM games WHERE season_id=%s",
        "details": "SELECT count(*) AS n FROM game_details d JOIN games g ON g.id=d.game_id WHERE g.season_id=%s",
        "seats": "SELECT count(*) AS n FROM game_seats s JOIN games g ON g.id=s.game_id WHERE g.season_id=%s",
        "rounds": "SELECT count(*) AS n FROM game_rounds r JOIN games g ON g.id=r.game_id WHERE g.season_id=%s",
        "events": "SELECT count(*) AS n FROM game_event_records e JOIN games g ON g.id=e.game_id WHERE g.season_id=%s",
        "targets": "SELECT count(*) AS n FROM game_event_targets e JOIN games g ON g.id=e.game_id WHERE g.season_id=%s",
        "event_votes": "SELECT count(*) AS n FROM game_event_votes e JOIN games g ON g.id=e.game_id WHERE g.season_id=%s",
        "effects": "SELECT count(*) AS n FROM game_event_effects e JOIN games g ON g.id=e.game_id WHERE g.season_id=%s",
        "ballots": "SELECT count(*) AS n FROM game_ballots b JOIN games g ON g.id=b.game_id WHERE g.season_id=%s",
        "choices": "SELECT count(*) AS n FROM game_ballot_choices c JOIN game_ballots b ON b.id=c.ballot_id JOIN games g ON g.id=b.game_id WHERE g.season_id=%s",
        "voting_days": "SELECT count(*) AS n FROM game_voting_days v JOIN games g ON g.id=v.game_id WHERE g.season_id=%s",
        "sheriff_registrations": "SELECT count(*) AS n FROM game_sheriff_registrations r JOIN games g ON g.id=r.game_id WHERE g.season_id=%s",
        "files": "SELECT count(*) AS n FROM game_files f JOIN games g ON g.id=f.game_id WHERE g.season_id=%s",
    }
    result = {"season_exists": True}
    for key, query in queries.items():
        result[key] = conn.execute(query, (sid,)).fetchone()["n"]
    formal_tables = {
        name: conn.execute("SELECT to_regclass(%s) AS name", (name,)).fetchone()["name"] is not None
        for name in ("game_formal_import_receipts", "game_formal_annotations")
    }
    result["formal_receipts"] = None
    result["formal_annotations"] = None
    if formal_tables["game_formal_import_receipts"]:
        result["formal_receipts"] = conn.execute(
            "SELECT count(*) AS n FROM game_formal_import_receipts r JOIN games g ON g.id=r.game_id WHERE g.season_id=%s", (sid,)
        ).fetchone()["n"]
    if formal_tables["game_formal_annotations"]:
        result["formal_annotations"] = conn.execute(
            "SELECT count(*) AS n FROM game_formal_annotations a JOIN games g ON g.id=a.game_id WHERE g.season_id=%s", (sid,)
        ).fetchone()["n"]
    result["formal_tables_present"] = formal_tables

    # A content digest over stable natural keys, deliberately excluding UUIDs
    # and timestamps. This detects edits even when all table counts stay equal.
    content_queries = {
        "games": """SELECT g.slug,s.platform AS source_platform,s.external_key AS source_key
            FROM games g LEFT JOIN sources s ON s.id=g.primary_source_id
            WHERE g.season_id=%s ORDER BY g.slug""",
        "details": """SELECT g.slug,d.board_code,d.event_date,d.phase,d.episode,d.day_in_episode,
            d.game_number,d.winning_faction FROM game_details d JOIN games g ON g.id=d.game_id
            WHERE g.season_id=%s ORDER BY g.slug""",
        "seats": """SELECT g.slug,s.seat_number,p.name AS person_name,s.role,s.faction,
            s.learning_target_seat,s.learned_role FROM game_seats s JOIN games g ON g.id=s.game_id
            LEFT JOIN people p ON p.id=s.person_id WHERE g.season_id=%s ORDER BY g.slug,s.seat_number""",
        "staff": """SELECT g.slug,s.duty,s.position,p.name AS person_name FROM game_staff s
            JOIN game_details d ON d.game_id=s.game_id JOIN games g ON g.id=d.game_id
            JOIN people p ON p.id=s.person_id WHERE g.season_id=%s ORDER BY g.slug,s.duty,s.position""",
        "rounds": """SELECT g.slug,r.round_number FROM game_rounds r JOIN games g ON g.id=r.game_id
            WHERE g.season_id=%s ORDER BY g.slug,r.round_number""",
        "events": """SELECT g.slug,e.round_number,e.board_code,e.phase,e.slot_code,e.action,e.actor_seat,
            e.result_code,e.start_seat,e.direction,e.random_point,e.speech_scope,e.availability
            FROM game_event_records e JOIN games g ON g.id=e.game_id WHERE g.season_id=%s
            ORDER BY g.slug,e.round_number,e.phase,e.slot_code""",
        "targets": """SELECT g.slug,e.round_number,e.phase,e.slot_code,t.position,t.seat_number
            FROM game_event_targets t JOIN game_event_records e ON e.id=t.event_id
            JOIN games g ON g.id=e.game_id WHERE g.season_id=%s
            ORDER BY g.slug,e.round_number,e.phase,e.slot_code,t.position""",
        "event_votes": """SELECT g.slug,e.round_number,e.phase,e.slot_code,v.ballot_round,
            v.voter_seat,v.target_seat,v.abstained FROM game_event_votes v
            JOIN game_event_records e ON e.id=v.event_id JOIN games g ON g.id=e.game_id
            WHERE g.season_id=%s ORDER BY g.slug,e.round_number,e.phase,e.slot_code,v.ballot_round,v.voter_seat""",
        "effects": """SELECT g.slug,e.round_number,e.phase,e.slot_code,f.position,f.kind,
            f.intended_target,f.dead_seat,f.shield_actor FROM game_event_effects f
            JOIN game_event_records e ON e.id=f.event_id JOIN games g ON g.id=e.game_id
            WHERE g.season_id=%s ORDER BY g.slug,e.round_number,e.phase,e.slot_code,f.position""",
        "ballots": """SELECT g.slug,b.ballot_key,b.day_number,b.kind,b.ballot_number,b.stage,b.status,
            b.candidates,b.eligible_voters,b.tied_candidates,b.winner_seat FROM game_ballots b
            JOIN games g ON g.id=b.game_id WHERE g.season_id=%s ORDER BY g.slug,b.ballot_key""",
        "ballot_choices": """SELECT g.slug,b.ballot_key,c.voter_seat,c.target_seat,c.state
            FROM game_ballot_choices c JOIN game_ballots b ON b.id=c.ballot_id
            JOIN games g ON g.id=b.game_id WHERE g.season_id=%s
            ORDER BY g.slug,b.ballot_key,c.voter_seat""",
        "voting_days": """SELECT g.slug,v.day_number,v.sheriff_status,v.exile_status
            FROM game_voting_days v JOIN games g ON g.id=v.game_id WHERE g.season_id=%s
            ORDER BY g.slug,v.day_number""",
        "sheriff_registrations": """SELECT g.slug,r.registration_key,r.day_number,r.seat_number,r.registered
            FROM game_sheriff_registrations r JOIN games g ON g.id=r.game_id WHERE g.season_id=%s
            ORDER BY g.slug,r.registration_key,r.seat_number""",
        "files": """SELECT g.slug,f.file_role,a.kind,a.sha256 FROM game_files f
            JOIN game_details d ON d.game_id=f.game_id JOIN games g ON g.id=d.game_id
            JOIN artifacts a ON a.id=f.artifact_id WHERE g.season_id=%s ORDER BY g.slug,f.file_role""",
        "formal_receipts": """SELECT g.slug,r.batch_key,r.canonical_board_code,r.storage_board_code,
            r.candidate_path,r.candidate_sha256,r.formal_files,r.source_files,r.normalization,
            r.overall_batch_authorized,r.field_confirmation FROM game_formal_import_receipts r
            JOIN games g ON g.id=r.game_id WHERE g.season_id=%s ORDER BY g.slug""",
        "formal_annotations": """SELECT g.slug,a.annotation_key,a.annotation_type,a.source_path,
            a.source_sha256,a.payload FROM game_formal_annotations a JOIN games g ON g.id=a.game_id
            WHERE g.season_id=%s ORDER BY g.slug,a.annotation_key""",
    }
    natural_content = {}
    for key, query in content_queries.items():
        if key == "formal_receipts" and not formal_tables["game_formal_import_receipts"]:
            natural_content[key] = []
            continue
        if key == "formal_annotations" and not formal_tables["game_formal_annotations"]:
            natural_content[key] = []
            continue
        natural_content[key] = [dict(row) for row in conn.execute(query, (sid,)).fetchall()]

    # Include the shared S22-era templates; S23-prefixed templates are
    # intentionally excluded because this importer appends its own namespace.
    natural_content["legacy_templates"] = [dict(row) for row in conn.execute("""
        SELECT t.code,t.name,t.seat_count,t.role_counts,t.wake_order,
               s.phase,s.code AS slot_code,s.position,s.label,s.actor_role,s.allowed_actions
        FROM board_templates t LEFT JOIN board_event_slots s ON s.board_code=t.code
        WHERE left(t.code,4)<>'s23_' ORDER BY t.code,s.phase,s.position
    """).fetchall()]
    digest_bytes = json.dumps(natural_content, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), default=str).encode("utf-8")
    result["content_sha256"] = sha256_bytes(digest_bytes)
    result["content_row_counts"] = {key: len(rows) for key, rows in natural_content.items()}
    return result


def verify_database(batch: dict, *, write: bool, verify_idempotency: bool = False) -> dict:
    from database import configuration
    config = configuration()
    schema = config.get("schema", "jcms")
    with connect(schema) as conn:
        core_tables = ("game_ballots", "game_event_records", "game_event_targets", "game_event_votes",
                       "game_event_effects", "game_files", "game_voting_days", "game_sheriff_registrations")
        missing_core = [name for name in core_tables if conn.execute("SELECT to_regclass(%s) AS name", (name,)).fetchone()["name"] is None]
        if missing_core:
            raise ReviewError("正式库缺少现有核心表: " + ",".join(missing_core))
        formal_tables = ("game_formal_import_batches", "game_formal_import_receipts", "game_formal_annotations")
        missing_formal = [name for name in formal_tables if conn.execute("SELECT to_regclass(%s) AS name", (name,)).fetchone()["name"] is None]
        season = conn.execute("SELECT id FROM seasons WHERE code='S23'").fetchone()
        keys = sorted({g["media"]["external_key"] for g in batch["games"]})
        rows = conn.execute("""SELECT s.external_key,a.sha256 FROM sources s
            JOIN artifacts a ON a.source_id=s.id AND a.kind='audio'
            WHERE s.platform='bilibili' AND s.external_key=ANY(%s)""", (keys,)).fetchall()
        by_key: dict[str, set[str]] = {}
        for row in rows:
            by_key.setdefault(row["external_key"], set()).add(row["sha256"])
        missing_audio = [g["media"]["external_key"] for g in batch["games"]
                         if g["media"]["audio_sha256"] not in by_key.get(g["media"]["external_key"], set())]
        if missing_audio:
            raise ReviewError(f"DB已登记audio artifact与manifest哈希不匹配或缺失: {len(set(missing_audio))}条")
        s22_before = db_season_fingerprint(conn, "S22")
        s23_before = db_season_fingerprint(conn, "S23")
        if not write:
            return {"database_checked": True, "database_write": False, "audio_sources": len(keys),
                    "audio_artifacts_matching_manifest": len(keys), "s22_fingerprint": s22_before,
                    "s23_before": s23_before, "schema": schema, "s23_season_registered": season is not None,
                    "formal_import_ready": not missing_formal, "missing_formal_tables": missing_formal}
        if missing_formal:
            raise ReviewError("正式库缺少S23迁移或所需表: " + ",".join(missing_formal))
        if not season:
            season = conn.execute(
                "INSERT INTO seasons(code,name,metadata) VALUES('S23','昆仑归墟',%s::jsonb) RETURNING id",
                (json.dumps({"scope_config": rel(SCOPE_PATH), "authorization": rel(AUTHORIZATION_PATH)}, ensure_ascii=False),),
            ).fetchone()
        if verify_prepared_files(batch):
            raise ReviewError("正式JSON文件未准备或已与当前候选快照不一致；先运行--prepare")
        if not verify_idempotency:
            raise ReviewError("正式库写入需要--verify-idempotency；批次两次导入一致性会在同一事务内检查")
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("s23-formal-import-" + batch["progress"]["snapshot_id"],))
        batch_payload = {
            "batch_key": batch["batch_key"], "season_id": season["id"],
            "scope_code": batch["scope"]["scope_code"], "snapshot_id": batch["progress"]["snapshot_id"],
            "source_report_path": rel(REPORT_PATH), "source_report_sha256": batch["source_hashes"]["snapshot_report"],
            "rules_path": rel(RULES_PATH), "rules_sha256": batch["source_hashes"]["formal_rules"],
            "authorization_path": rel(AUTHORIZATION_PATH), "authorization_sha256": batch["source_hashes"]["authorization"],
            "authorization_text": AUTHORIZATION_PATH.read_text(encoding="utf-8").strip(),
            "source_candidate_count": 75,
            "idempotency_note": "one outer transaction; second pass replaces the same 75 slugs and upserts the same receipt/annotation keys",
        }

        def import_pass() -> None:
            conn.execute("""INSERT INTO game_formal_import_batches
                (batch_key,season_id,scope_code,snapshot_id,source_report_path,source_report_sha256,
                 rules_path,rules_sha256,authorization_path,authorization_sha256,authorization_text,
                 source_candidate_count,idempotency_note)
                VALUES(%(batch_key)s,%(season_id)s,%(scope_code)s,%(snapshot_id)s,%(source_report_path)s,
                       %(source_report_sha256)s,%(rules_path)s,%(rules_sha256)s,%(authorization_path)s,
                       %(authorization_sha256)s,%(authorization_text)s,%(source_candidate_count)s,%(idempotency_note)s)
                ON CONFLICT(batch_key) DO UPDATE SET source_report_sha256=EXCLUDED.source_report_sha256,
                    rules_sha256=EXCLUDED.rules_sha256,authorization_sha256=EXCLUDED.authorization_sha256,
                    authorization_text=EXCLUDED.authorization_text,source_candidate_count=EXCLUDED.source_candidate_count""",
                batch_payload)
            for game in batch["games"]:
                game_records.import_game(game["db_dossier"], allow_incomplete=True, conn=conn)
                voting_records.import_voting(game["voting"], conn=conn)
                row = conn.execute("SELECT id FROM games WHERE slug=%s", (game["slug"],)).fetchone()
                if row is None:
                    raise ReviewError(f"入库后未能读取game: {game['slug']}")
                game_id = row["id"]
                annotations = [
                    ("supplemental", "supplemental_observations", "supplemental.json", game["supplemental"]),
                    ("vote_control", "vote_control", "vote_control.json", game["vote_control"]),
                    ("endgame", "endgame", "endgame.json", game["endgame"]),
                    ("review_context", "review_context", "formal_context.json", game["formal_context"]["separate_review_context"]),
                    ("terminal_observations", "terminal_observations", "formal_context.json",
                     {"observations": game["formal_context"]["terminal_observations"],
                      "unpublished_terminal_checks": game["formal_context"]["unpublished_terminal_checks"]}),
                ]
                conn.execute("DELETE FROM game_formal_annotations WHERE game_id=%s", (game_id,))
                for key, kind, filename, payload in annotations:
                    annotation_path = ROOT / Path(game["candidate_path"]).parent / filename
                    source_path = (ROOT / Path(game["candidate_path"]).parent / f"{key}.candidate.json")
                    if key == "review_context":
                        source_path = ROOT / "data/extractions/S23/game_reviews" / game["bvid"] / "daily_audit.json"
                    if not source_path.is_file():
                        source_path = annotation_path
                    conn.execute("""INSERT INTO game_formal_annotations
                        (game_id,annotation_key,annotation_type,source_path,source_sha256,payload)
                        VALUES(%s,%s,%s,%s,%s,%s)""",
                        (game_id, key, kind, rel(source_path), sha256_file(source_path),
                         __import__("psycopg.types.json", fromlist=["Jsonb"]).Jsonb(payload)))
                folder = ROOT / Path(game["candidate_path"]).parent
                formal_hashes = {filename: sha256_file(folder / filename) for filename in FORMAL_FILES[:-1]}
                conn.execute("""INSERT INTO game_formal_import_receipts
                    (game_id,batch_key,slug,canonical_board_code,storage_board_code,candidate_path,candidate_sha256,
                     formal_files,source_files,normalization,overall_batch_authorized,field_confirmation)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,'not_claimed_by_batch_authorization')
                    ON CONFLICT(game_id) DO UPDATE SET batch_key=EXCLUDED.batch_key,slug=EXCLUDED.slug,
                        canonical_board_code=EXCLUDED.canonical_board_code,storage_board_code=EXCLUDED.storage_board_code,
                        candidate_path=EXCLUDED.candidate_path,candidate_sha256=EXCLUDED.candidate_sha256,
                        formal_files=EXCLUDED.formal_files,source_files=EXCLUDED.source_files,
                        normalization=EXCLUDED.normalization,overall_batch_authorized=true,
                        field_confirmation='not_claimed_by_batch_authorization',recorded_at=now()""",
                    (game_id, batch["batch_key"], game["slug"], game["canonical_board"], game["storage_board"],
                     game["candidate_path"], game["candidate_sha256"],
                     __import__("psycopg.types.json", fromlist=["Jsonb"]).Jsonb(formal_hashes),
                     __import__("psycopg.types.json", fromlist=["Jsonb"]).Jsonb(game["source_hashes"]),
                     __import__("psycopg.types.json", fromlist=["Jsonb"]).Jsonb(game["normalization"])))

        import_pass()
        after_first = db_season_fingerprint(conn, "S23")
        import_pass()
        after_second = db_season_fingerprint(conn, "S23")
        s22_after = db_season_fingerprint(conn, "S22")
        if after_first != after_second:
            raise ReviewError("S23第二次导入后行数指纹变化，幂等性检查失败；事务将回滚")
        if s22_before != s22_after:
            raise ReviewError("导入过程改变了S22行数指纹；事务将回滚")
        # Returning normally commits the single outer transaction.
        return {"database_checked": True, "database_write": True, "database_write_passes": 2,
                "verified_idempotent": True, "games": len(batch["games"]), "batch_key": batch["batch_key"],
                "s22_unchanged": True, "s22_fingerprint": s22_after,
                "s23_before": s23_before, "s23_after": after_second, "schema": schema}


def make_report(batch: dict, mode: str, database: dict | None = None) -> dict:
    output = {
        "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "season": "S23", "scope_code": batch["scope"]["scope_code"],
        "snapshot_id": batch["progress"]["snapshot_id"], "batch_key": batch["batch_key"],
        "status": mode, "database_write": bool(database and database.get("database_write")),
        "candidate_games": len(batch["games"]), "board_counts": dict(batch["board_counts"]),
        "unknown_events_before": sum(g["normalization"]["unknown_count_before"] for g in batch["games"]),
        "unknown_events_after": sum(g["normalization"]["unknown_count_after"] for g in batch["games"]),
        "unknown_slots_added": sum(len(g["normalization"]["filled_slots_as_unknown"]) for g in batch["games"]),
        "candidate_paths": [g["candidate_path"] for g in batch["games"]],
        "source_hashes": batch["source_hashes"], "database": database,
        "notes": [
            "游戏事实全部由复核进度报告当前candidate_dossiers读取；不读取reviewed档案。",
            "整体数据库/上线授权与逐字段确认分别记录；整体授权没有提升任一unknown字段的确认状态。",
            "补槽只增加unknown；不会把unknown改为pass/unavailable，也不会新增候选没有的轮次。",
            "DQ作为独立补充观察保存；无效狼刀保留invalidated_by_dq，不作为主动空刀。",
            "10号遗言诈身份保存在独立统计复核上下文，不并入常规悍跳。",
        ],
    }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="检查75局与源哈希；不写正式对局表")
    modes.add_argument("--prepare", action="store_true", help="检查并生成正式JSON旁证；不写数据库")
    modes.add_argument("--check-db", action="store_true", help="只读检查已登记媒体hash、迁移表和S22基线")
    modes.add_argument("--import-db", action="store_true", help="写入正式库；需要已备份数据库")
    parser.add_argument("--verify-idempotency", action="store_true", help="同一事务内导入两次并核对S23稳定及S22不变")
    parser.add_argument("--report", type=Path, default=ROOT / "data/reports/S23_正式入库预检.json")
    args = parser.parse_args()
    mode = "check" if not any((args.check, args.prepare, args.check_db, args.import_db)) else None
    if args.check: mode = "check"
    if args.prepare: mode = "prepare"
    if args.check_db: mode = "check_db"
    if args.import_db: mode = "import_db"
    if args.verify_idempotency and not args.import_db:
        parser.error("--verify-idempotency 只能与--import-db一起使用")
    try:
        batch = build_batch()
        if mode == "prepare":
            result = materialize(batch)
            report = make_report(batch, "prepared; database not written")
            write_json(args.report, report)
            print(json.dumps({**result, "database_write": False, "status": "prepared"}, ensure_ascii=False, indent=2))
            return 0
        if mode == "check":
            errors = verify_prepared_files(batch)
            # In check-only mode the preflight report is still an explicit, reviewable artifact.
            report = make_report(batch, "files_validated; database not written")
            report["prepared_files_present"] = not errors
            report["prepared_file_errors"] = errors
            write_json(args.report, report)
            print(json.dumps({"valid": not errors, "games": len(batch["games"]),
                              "board_counts": dict(batch["board_counts"]),
                              "unknown_events_before": report["unknown_events_before"],
                              "unknown_events_after": report["unknown_events_after"],
                              "unknown_slots_added": report["unknown_slots_added"],
                              "prepared_files_present": not errors, "report": rel(args.report),
                              "database_write": False}, ensure_ascii=False, indent=2))
            return 0 if not errors else 2
        database = verify_database(batch, write=mode == "import_db", verify_idempotency=args.verify_idempotency)
        status = "database imported twice in one transaction; idempotency and S22 fingerprints verified" if mode == "import_db" else "database read-only check passed"
        report = make_report(batch, status, database)
        write_json(args.report, report)
        print(json.dumps({"valid": True, "games": len(batch["games"]), "database": database,
                          "report": rel(args.report)}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"valid": False, "error": str(exc), "database_write": False}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
