"""Import S22 seat names read from per-game video frames.

Annotations live in ``data/extractions/S22/frame_seats/{BVID}.json``. They are
source notes, not business records. Each annotation has a 12-row ``seats``
array with ``seat``, ``visible_label``, ``name`` (or ``canonical_name``), and
optional per-seat ``frame_path`` / ``frame_time_ms``. A top-level ``source``
with ``kind``, ``frame_path``, and ``frame_time_ms`` supplies defaults.

Only names are merged. Existing differing names remain in the frame review
questions unless the row says ``resolution: "user_confirmed"``. Clear names
that have a reviewed S22 alias but are absent from the scheduled roster are
added to that game's roster as screen-confirmed names; the schedule name is
kept separately and the discrepancy remains visible in the review record.
"""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import sys

import batch_s22 as batch
import batch_people

ROOT = Path(__file__).resolve().parents[1]
ANNOTATION_DIR = ROOT / "data/extractions/S22/frame_seats"
PROGRESS_FILE = ROOT / "data/reports/S22/S22_画面座位补全进度.json"
FRAME_REVIEW_VERSION = 2
USER_CONFIRMED = "user_confirmed"
MIN_OCR_CONFIDENCE = 0.80
SAME_DAY_TRUST_BASES = {"canonical_name", "approved_local_alias", "primary_agent_visual_seed",
                        "assistant_visual", "user_visual", "user_confirmed", "user_correction"}
_BVID_RE = re.compile(r"BV[0-9A-Za-z]+\Z")


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def annotation_digest(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _safe_frame_path(raw: object, root: Path) -> str | None:
    if raw in (None, ""):
        return None
    path = Path(str(raw))
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("frame_path必须位于项目目录内")
    return resolved.relative_to(root.resolve()).as_posix()


def _frame_time(raw: object) -> int | None:
    if raw is None or raw == "":
        return None
    if type(raw) is not int or raw < 0:
        raise ValueError("frame_time_ms必须是非负整数或null")
    return raw


def _alias_evidence(label: str, canonical: str, root: Path) -> list[dict]:
    """Return local rows that directly support a visible-label mapping."""
    from batch_people import PHOTO_NAMES_REL, TOTAL_NAMES_REL

    evidence: list[dict] = []
    for rel, fields in (
        (PHOTO_NAMES_REL, ("原图名字", "复核行名字", "去重后姓名")),
        (TOTAL_NAMES_REL, ("姓名", "原图名字")),
    ):
        path = root / rel
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = csv.DictReader(stream)
                for row in rows:
                    if rel == PHOTO_NAMES_REL and (row.get("赛季") != "S22" or row.get("纳入参赛名单") != "是"):
                        continue
                    if rel == TOTAL_NAMES_REL and "S22" not in (row.get("参与赛季") or ""):
                        continue
                    canonical_value = (row.get("去重后姓名") or "").strip() if rel == PHOTO_NAMES_REL else (row.get("姓名") or "").strip()
                    aliases = [piece.strip() for field in fields for piece in re.split(r"[、,，;；|/]+", row.get(field, "") or "") if piece.strip()]
                    if canonical_value == canonical and any(batch_people._key(alias) == batch_people._key(label) for alias in aliases):
                        evidence.append({
                            "path": rel.as_posix(),
                            "row": dict(row),
                        })
        except (OSError, UnicodeError, csv.Error):
            continue
    return evidence


def _roster_match(label: str, roster: list[str]) -> str | None:
    key = batch_people._key(label)
    if not key:
        return None
    matches = {name for name in roster if batch_people._key(name) == key}
    return next(iter(matches)) if len(matches) == 1 else None


def _name_resolution(row: dict, roster: list[str], aliases: dict[str, set[str]], root: Path,
                     *, source_kind: str | None = None) -> dict:
    label = str(row.get("visible_label") or "").strip()
    # An explicit null/empty OCR name means the recognizer did not accept a
    # canonical match. Never reconstruct it from visible_label or the roster.
    # Legacy canonical_name-only rows remain supported when the name key is
    # absent, but name:null deliberately blocks that fallback.
    if "name" in row:
        declared = str(row.get("name") or "").strip()
    else:
        declared = str(row.get("canonical_name") or "").strip()
    resolution = row.get("resolution")
    if source_kind == "same_day_frame" or resolution == "same_day_propagated":
        basis = set(row.get("same_day_trust_basis") or [])
        if not declared:
            return {"name": None, "status": "name_missing", "reason": "同日座位补全没有已确认规范姓名；不从姓名牌文字反推。", "evidence": []}
        if source_kind != "same_day_frame" or not basis or not basis.issubset(SAME_DAY_TRUST_BASES):
            return {"name": None, "status": "unsupported_same_day", "reason": "同日座位补全缺少可信来源依据。", "evidence": []}
        return {"name": declared, "status": "same_day_confirmed", "reason": None, "evidence": [],
                "same_day_sources": row.get("same_day_sources", [])}

    if not label:
        return {"name": None, "status": "unreadable", "reason": "画面姓名牌未读清，保留空姓名。", "evidence": []}

    alias_name, alias_status = batch_people._resolve_name(label, aliases)
    roster_name = _roster_match(label, roster)
    confirmed = resolution == USER_CONFIRMED
    if confirmed and declared:
        return {"name": declared, "status": "user_confirmed", "reason": None, "evidence": []}
    if not declared:
        return {"name": None, "status": "name_missing",
                "reason": "OCR行没有明确规范姓名；不从visible_label或剩余名额推配。", "evidence": []}
    if source_kind in (None, "video_frame") and row.get("confidence") is not None and not confirmed:
        try:
            if float(row["confidence"]) < MIN_OCR_CONFIDENCE:
                return {"name": None, "status": "low_confidence",
                        "reason": "OCR置信度低于导入阈值；保留当前姓名，不按visible_label重新匹配。", "evidence": []}
        except (TypeError, ValueError):
            return {"name": None, "status": "invalid_confidence",
                    "reason": "OCR置信度无效；保留当前姓名。", "evidence": []}
    if alias_name:
        if declared and batch_people._key(declared) != batch_people._key(alias_name) and not confirmed:
            return {"name": None, "status": "mapping_conflict",
                    "reason": "画面昵称在本地别名表与标注规范名不一致，未选择其中一方。",
                    "evidence": _alias_evidence(label, alias_name, root), "alias_name": alias_name,
                    "declared_name": declared}
        canonical = declared if confirmed and declared else alias_name
        return {"name": canonical, "status": "alias_mapped", "reason": None,
                "evidence": _alias_evidence(label, alias_name, root), "alias_name": alias_name}

    if alias_status == "ambiguous":
        return {"name": None, "status": "ambiguous_alias", "reason": "画面昵称在本地别名表对应多个规范姓名。", "evidence": []}

    if roster_name:
        if declared and batch_people._key(declared) != batch_people._key(roster_name) and not confirmed:
            return {"name": None, "status": "mapping_conflict",
                    "reason": "画面姓名与本局名单规范姓名不同，且没有明确别名依据。", "evidence": [],
                    "roster_name": roster_name, "declared_name": declared}
        return {"name": declared if confirmed and declared else roster_name,
                "status": "roster_exact", "reason": None, "evidence": []}

    if declared:
        if batch_people._key(declared) == batch_people._key(label):
            # Adding a new visually explicit participant is allowed, but the
            # annotation must make that decision explicit when no S22 alias
            # or same-game roster entry supports it.
            if row.get("allow_roster_absent") is True or confirmed:
                return {"name": declared, "status": "screen_name_added", "reason": None, "evidence": []}
            return {"name": None, "status": "outside_roster", "reason": "画面姓名未出现在本局名单或S22规范别名中；未按剩余名额推配。", "evidence": [], "declared_name": declared}
        if confirmed:
            return {"name": declared, "status": "user_confirmed", "reason": None, "evidence": []}
        return {"name": None, "status": "unsupported_mapping", "reason": "规范姓名与画面昵称不同，缺少本地别名或用户确认依据。", "evidence": [], "declared_name": declared}

    return {"name": None, "status": "outside_roster", "reason": "画面姓名未出现在本局名单或S22规范别名中；未按剩余名额推配。", "evidence": []}


def validate_annotation(value: dict, bvid: str, *, root: Path | None = None) -> None:
    root = Path(root or ROOT)
    if not isinstance(value, dict) or value.get("season") not in (None, "S22"):
        raise ValueError("画面座位标注不是S22记录")
    if value.get("bvid") not in (None, bvid):
        raise ValueError("标注中的BVID与文件名不一致")
    if value.get("scope") not in (None, "seat_name_only"):
        raise ValueError("画面标注超出seat_name_only范围")
    rows = value.get("seats")
    if not isinstance(rows, list) or sorted(
            row.get("seat") for row in rows if isinstance(row, dict) and type(row.get("seat")) is int
    ) != list(range(1, 13)) or len(rows) != 12:
        raise ValueError("每局标注必须包含1到12号座位，各一行")
    source = value.get("source") or {}
    if not isinstance(source, dict):
        raise ValueError("source必须是对象")
    if not (value.get("source_kind") or source.get("kind")):
        raise ValueError("标注缺少source kind")
    for row in rows:
        if not isinstance(row, dict) or type(row.get("seat")) is not int or not 1 <= row["seat"] <= 12:
            raise ValueError("座位号不合法")
        _safe_frame_path(row.get("frame_path", source.get("frame_path")), root)
        _frame_time(row.get("frame_time_ms", source.get("frame_time_ms")))


def _question(bvid: str, seat_number: int, reason: str, candidate: dict) -> dict:
    identity = {"bvid": bvid, "seat": seat_number, "reason": reason, "candidate": candidate}
    question_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:14]
    return {"id": question_id, "field": f"seats[{seat_number}].name", "label": f"{seat_number}号姓名",
            "reason": reason, "candidate": candidate}


def merge_frame_names(value: dict, annotation: dict, bvid: str, annotation_path: Path,
                      *, root: Path | None = None, previous_roster: list[str] | None = None) -> tuple[dict, dict]:
    """Return a name-only dossier merge and its separate review segment."""
    root = Path(root or ROOT)
    validate_annotation(annotation, bvid, root=root)
    result = copy.deepcopy(value)
    roster = list(result.get("roster", []))
    schedule_roster = list(previous_roster if previous_roster is not None else roster)
    alias_issues: list[str] = []
    aliases = batch_people._name_aliases(root, alias_issues)
    seat_map = {seat["seat"]: seat for seat in result.get("seats", [])}
    if set(seat_map) != set(range(1, 13)):
        raise ValueError("对局档案必须包含1到12号座位")

    source = copy.deepcopy(annotation.get("source") or {})
    source_kind = annotation.get("source_kind") or source.get("kind")
    source_path = _safe_frame_path(source.get("frame_path"), root)
    source_time = _frame_time(source.get("frame_time_ms"))
    segment = {
        "checked_at": now(),
        "source": {"kind": source_kind, "frame_path": source_path, "frame_time_ms": source_time,
                   "annotation_path": _relative(annotation_path, root),
                   "annotation_sha256": annotation_digest(annotation),
                   "description": source.get("description"),
                   "source_bvid": source.get("source_bvid"),
                   "source_bvids": copy.deepcopy(source.get("source_bvids", [])),
                   "source_date": source.get("source_date"),
                   "user_rule": source.get("user_rule"),
                   "same_day_rule": source.get("same_day_rule")},
        "seats": [], "questions": [], "changes": [], "issues": [], "notes": [],
        "previous_roster": schedule_roster,
    }
    assigned_names = {seat["name"]: seat["seat"] for seat in result["seats"] if seat.get("name") is not None}
    rows = sorted(annotation["seats"], key=lambda item: item["seat"])
    incoming_questions = [copy.deepcopy(question) for question in annotation.get("questions", [])
                         if isinstance(question, dict) and question.get("field") and question.get("reason")]
    incoming_question_fields = {question["field"] for question in incoming_questions}
    for row in rows:
        number = row["seat"]
        seat = seat_map[number]
        label = str(row.get("visible_label") or "").strip() or None
        row_frame_path = row.get("frame_path")
        if row_frame_path in (None, ""):
            row_frame_path = source.get("frame_path")
        row_frame_time = row.get("frame_time_ms")
        if row_frame_time is None:
            row_frame_time = source.get("frame_time_ms")
        row_source = {
            "kind": row.get("source_kind") or source_kind,
            "frame_path": _safe_frame_path(row_frame_path, root),
            "frame_time_ms": _frame_time(row_frame_time),
            "source_bvid": row.get("source_bvid") or source.get("source_bvid"),
            "source_date": source.get("source_date"),
            "user_rule": source.get("user_rule"),
        }
        if isinstance(row.get("same_day_sources"), list):
            row_source["same_day_sources"] = copy.deepcopy(row["same_day_sources"])
        mapped = _name_resolution(row, roster, aliases, root, source_kind=source_kind)
        proposed = mapped.get("name")
        item = {"seat": number, "visible_label": label, "name": proposed,
                "existing_name": seat.get("name"), "status": mapped["status"], "source": row_source,
                "mapping_evidence": mapped.get("evidence", [])}
        if mapped.get("same_day_sources"):
            item["same_day_sources"] = copy.deepcopy(mapped["same_day_sources"])

        if mapped.get("reason"):
            if source_kind == "same_day_frame" and f"seats[{number}].name" in incoming_question_fields:
                item["status"] = "needs_review"
                segment["seats"].append(item)
                continue
            candidate = {"visible_label": label, "proposed_name": row.get("canonical_name") or row.get("name"),
                         "existing_name": seat.get("name"), "roster": roster,
                         "resolution_status": mapped["status"], "alias_name": mapped.get("alias_name"),
                         "roster_name": mapped.get("roster_name"),
                         "mapping_evidence": mapped.get("evidence", []), "source": row_source}
            question = _question(bvid, number, mapped["reason"], candidate)
            segment["questions"].append(question)
            item["status"] = "needs_review"
            segment["issues"].append(question["reason"] + f"（{number}号画面标注：{label or '姓名未读'}）")
            segment["seats"].append(item)
            continue

        if not proposed:
            segment["seats"].append(item)
            continue
        user_confirmed = (row.get("resolution") == USER_CONFIRMED or
                          (source_kind == "same_day_frame" and
                           "user_correction" in set(row.get("same_day_trust_basis") or [])))
        current = seat.get("name")
        if current == proposed:
            item["status"] = "already_present"
            segment["seats"].append(item)
            continue
        if current is not None and not user_confirmed:
            reason = "画面姓名与当前已知姓名不同；保留两方来源，未覆盖。"
            question = _question(bvid, number, reason, {
                "visible_label": label, "proposed_name": proposed, "existing_name": current,
                "source": row_source, "mapping_evidence": mapped.get("evidence", []),
            })
            segment["questions"].append(question)
            segment["issues"].append(reason + f"（{number}号：当前“{current}”，画面候选“{proposed}”）")
            item.update(status="name_conflict", name=proposed)
            segment["seats"].append(item)
            continue
        other_seat = assigned_names.get(proposed)
        if other_seat is not None and other_seat != number:
            reason = f"画面姓名“{proposed}”已用于{other_seat}号；未重复归座。"
            question = _question(bvid, number, reason, {
                "visible_label": label, "proposed_name": proposed, "existing_seat": other_seat,
                "source": row_source, "mapping_evidence": mapped.get("evidence", []),
            })
            segment["questions"].append(question)
            segment["issues"].append(reason)
            item.update(status="duplicate_name", name=proposed)
            segment["seats"].append(item)
            continue

        seat["name"] = proposed
        assigned_names.pop(current, None) if current is not None else None
        assigned_names[proposed] = number
        item["status"] = "user_confirmed" if user_confirmed else "added"
        item["existing_name"] = current
        segment["changes"].append({"field": f"seats[{number}].name", "before": current, "after": proposed,
                                   "basis": "user_confirmed" if user_confirmed else mapped["status"],
                                   "visible_label": label, "source": row_source,
                                   "mapping_evidence": mapped.get("evidence", [])})
        segment["seats"].append(item)
    for question in incoming_questions:
        if not any(existing.get("id") == question.get("id") for existing in segment["questions"]):
            segment["questions"].append(question)
            segment["issues"].append(str(question["reason"]))
    seat_names = [seat_map[number].get("name") for number in range(1, 13)]
    complete_unique = (not segment["questions"] and all(isinstance(name, str) and name.strip() for name in seat_names)
                       and len(set(seat_names)) == 12)
    if complete_unique:
        # For a fully resolved 12-seat lineup, the frame establishes this
        # game's actual roster. Preserve the original schedule roster alongside
        # the evidence so discrepancies stay reviewable instead of forcing a
        # speculative identity merge.
        result["roster"] = seat_names
        schedule_only = [name for name in schedule_roster if name not in seat_names]
        frame_only = [name for name in seat_names if name not in schedule_roster]
        segment["roster_differences"] = {"schedule_only": schedule_only, "frame_only": frame_only}
        if schedule_only or frame_only:
            segment["notes"].append(
                "12个座位姓名均已由画面唯一确认；本局roster按座位表更新，排班名单差异保留在previous_roster/roster_differences，未推断不同姓名是否同一人。"
            )
        if roster != seat_names:
            segment["changes"].append({"field": "roster", "before": roster, "after": seat_names,
                                       "basis": "all_12_unique_frame_names"})
    else:
        # With an unreadable name or unresolved collision, retain every prior
        # schedule name and add only clearly mapped seat names.
        before_roster = list(roster)
        for name in seat_names:
            if isinstance(name, str) and name not in roster:
                roster.append(name)
        result["roster"] = roster
        if roster != before_roster:
            segment["changes"].append({"field": "roster", "before": before_roster, "after": roster,
                                       "basis": "preserve_schedule_roster_with_clear_frame_names"})
        segment["roster_differences"] = None
    return result, segment


def _load_progress() -> dict:
    if PROGRESS_FILE.is_file():
        value = read_json(PROGRESS_FILE)
        if value.get("season") != "S22" or not isinstance(value.get("items"), dict):
            raise ValueError("画面座位补全进度文件结构异常，保留原文件并停止")
        from game_scope import exclusion_reason
        value["items"] = {bvid: item for bvid, item in value["items"].items()
                          if not exclusion_reason({**item, "bvid": bvid}, root=ROOT)}
        return value
    return {"season": "S22", "stage": "seat_names_from_frames", "items": {}, "created_at": now()}


def _save_progress(progress: dict) -> None:
    progress["updated_at"] = now()
    items = list(progress.get("items", {}).values())
    summary = {
        "total": len(items),
        "imported": sum(item.get("status") in {"imported", "imported_with_questions", "recorded"} for item in items),
        "needs_review": sum(item.get("status") == "imported_with_questions" for item in items),
        "failed": sum(item.get("status") == "failed" for item in items),
        "pending": sum(item.get("status", item.get("state")) in {None, "prepared_pending_import", "pending"}
                        for item in items),
        "last_processed": progress.get("last_processed"),
    }
    ordered = sorted(progress.get("items", {}).items(),
                     key=lambda pair: (pair[1].get("index", 10000), pair[0]))
    progress["next_frame_bvid"] = next((bvid for bvid, item in ordered
        if item.get("status", item.get("state")) in {None, "prepared_pending_import", "pending", "failed"}), None)
    progress["next_frame_review_bvid"] = next((bvid for bvid, item in ordered
        if item.get("status") == "imported_with_questions"), None)
    progress["summary"] = summary
    progress["state"] = ("in_progress" if summary["failed"] or summary["pending"] else
                         "imported_with_review" if summary["needs_review"] else "complete")
    batch.atomic_json(PROGRESS_FILE, progress)


def status_report(bvid: str | None = None, *, annotation_dir: Path | None = None) -> dict:
    annotation_dir = Path(annotation_dir or ANNOTATION_DIR)
    progress = _load_progress()
    items = progress.get("items", {})
    if bvid:
        return {"season": "S22", "bvid": bvid, "item": items.get(bvid),
                "annotation": _relative(annotation_dir / f"{bvid}.json", ROOT),
                "annotation_exists": (annotation_dir / f"{bvid}.json").is_file()}
    return {"season": "S22", "state": progress.get("state"),
            "summary": progress.get("summary") or {
                "total": len(items),
                "pending": sum(item.get("status", item.get("state")) in {None, "prepared_pending_import", "pending"}
                               for item in items.values()),
                "imported": sum(item.get("status") in {"imported", "imported_with_questions", "recorded"}
                                for item in items.values()),
                "needs_review": sum(item.get("status") == "imported_with_questions" for item in items.values()),
                "failed": sum(item.get("status") == "failed" for item in items.values()),
            }, "items": items,
            "annotation_dir": _relative(annotation_dir, ROOT)}


def _review_record(out: Path) -> dict:
    path = out / "复核记录.json"
    return read_json(path) if path.is_file() else {"issues": []}


def _archive_before(root: Path, bvid: str, dossier: dict) -> None:
    path = root / "data/archive/S22_frame_seats" / bvid / (hashlib.sha256(
        json.dumps(dossier, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest() + ".json")
    if not path.is_file():
        batch.atomic_json(path, dossier)


def _backup_frame_database(progress: dict, root: Path) -> None:
    backup = progress.get("backup")
    if backup and (root / backup).is_file():
        return
    # batch.backup_database owns credential handling and the actual pg_dump,
    # but its checkpoint normally writes the main game progress file. Redirect
    # just that checkpoint to this independent frame-import progress record.
    checkpoint = batch.checkpoint

    def save_frame_checkpoint(state: dict, event=None, *, render=True):
        if state is progress:
            if event:
                progress["last_event"] = event
            _save_progress(progress)
        else:
            checkpoint(state, event, render=render)

    batch.checkpoint = save_frame_checkpoint
    try:
        batch.backup_database(progress)
    finally:
        batch.checkpoint = checkpoint


def _apply_one(bvid: str, state: dict, progress: dict, *, root: Path,
               annotation_dir: Path | None = None) -> dict:
    annotation_dir = Path(annotation_dir or ANNOTATION_DIR)
    annotation_path = annotation_dir / f"{bvid}.json"
    annotation = read_json(annotation_path)
    validate_annotation(annotation, bvid, root=root)
    signature = annotation_digest(annotation)
    previous_progress = progress["items"].get(bvid, {})
    if (previous_progress.get("annotation_sha256") == signature
            and previous_progress.get("importer_version") == FRAME_REVIEW_VERSION
            and previous_progress.get("status") in {"imported", "imported_with_questions", "recorded", "preserved"}):
        return {"bvid": bvid, "status": "skipped_same_annotation"}
    if bvid not in state.get("items", {}):
        raise KeyError("画面标注BVID不在S22批处理进度中：" + bvid)
    entry = state["items"][bvid]
    if entry.get("state") == "preserved":
        progress["items"][bvid] = {**previous_progress, "status": "preserved", "annotation_sha256": signature,
                                   "state": "preserved", "importer_version": FRAME_REVIEW_VERSION, "checked_at": now()}
        return {"bvid": bvid, "status": "preserved"}

    out = root / entry["output_dir"]
    dossier_path = out / "dossier.json"
    old_dossier = read_json(dossier_path)
    existing_review = _review_record(out)
    prior_frame_record = existing_review.get("frame_seats", {})
    prior_roster = prior_frame_record.get("previous_roster") if isinstance(prior_frame_record, dict) else None
    incoming, frame_record = merge_frame_names(old_dossier, annotation, bvid, annotation_path, root=root,
                                               previous_roster=prior_roster if isinstance(prior_roster, list) else None)
    changed = bool(frame_record["changes"])
    if changed:
        from game_records import validate, import_game

        _backup_frame_database(progress, root)
        validate(incoming, allow_incomplete=True)
        _archive_before(root, bvid, old_dossier)
        batch.atomic_json(dossier_path, incoming)
        committed = False
        receipt = None
        try:
            receipt = import_game(incoming, allow_incomplete=True)
            committed = True
        except Exception:
            batch.atomic_json(dossier_path, old_dossier)
            raise
        review = existing_review
        frame_record["database_receipt"] = receipt
        review["frame_seats"] = frame_record
        review["db_receipt"] = receipt
        review["state"] = "imported"
        review["issues"] = list(dict.fromkeys([*review.get("issues", []), *frame_record["issues"]]))
        batch.atomic_json(out / "database_receipt.json", receipt)
        batch.atomic_json(out / "复核记录.json", review)
        from batch_review import render_game
        render_game(out, incoming, review)
        entry.update(batch.coverage(incoming), state="imported", auto_protected=True,
                     db_receipt=receipt, imported_dossier_sha256=batch.digest(dossier_path), updated_at=batch.now())
        entry.pop("generated_dossier_sha256", None)
        entry["issues"] = list(dict.fromkeys([*entry.get("issues", []), *frame_record["issues"]]))
        outcome = "imported_with_questions" if frame_record["questions"] else "imported"
        if committed:
            progress["last_processed"] = f"原目录#{entry.get('index', '?')} {bvid}"
    else:
        review = existing_review
        frame_record["database_receipt"] = review.get("db_receipt")
        review["frame_seats"] = frame_record
        review["issues"] = list(dict.fromkeys([*review.get("issues", []), *frame_record["issues"]]))
        batch.atomic_json(out / "复核记录.json", review)
        from batch_review import render_game
        render_game(out, old_dossier, review)
        if frame_record["questions"]:
            if entry.get("state") == "reviewed":
                entry["state"] = "imported"
                review["state"] = "imported"
            entry["issues"] = list(dict.fromkeys([*entry.get("issues", []), *frame_record["issues"]]))
            outcome = "imported_with_questions"
        else:
            outcome = "recorded"

    progress["items"][bvid] = {
        **previous_progress,
        "status": outcome,
        "state": outcome,
        "annotation_sha256": signature,
        "importer_version": FRAME_REVIEW_VERSION,
        "source_kind": frame_record["source"]["kind"],
        "annotation_file": _relative(annotation_path, root),
        "seat_names_applied": len(frame_record["changes"]),
        "question_count": len(frame_record["questions"]),
        "issue_count": len(frame_record["issues"]),
        "note_count": len(frame_record["notes"]),
        "dossier_sha256": batch.digest(dossier_path),
        "db_receipt": frame_record.get("database_receipt"),
        "checked_at": frame_record["checked_at"],
    }
    return {"bvid": bvid, "status": outcome, "seat_names_applied": len(frame_record["changes"]),
            "question_count": len(frame_record["questions"]), "issue_count": len(frame_record["issues"]),
            "note_count": len(frame_record["notes"])}


def apply(bvid: str | None = None, *, annotation_dir: Path | None = None) -> dict:
    if bvid and not _BVID_RE.fullmatch(bvid):
        raise ValueError("BVID格式不合法")
    annotation_dir = Path(annotation_dir or ANNOTATION_DIR)
    annotation_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with batch.batch_lock():
        state = batch.load_state()
        progress = _load_progress()
        annotations = [annotation_dir / f"{bvid}.json"] if bvid else sorted(annotation_dir.glob("BV*.json"))
        if bvid and not annotations[0].is_file():
            raise FileNotFoundError("没有找到画面座位标注：" + _relative(annotations[0], ROOT))
        if bvid and bvid not in state["items"]:
            raise ValueError("该局不在当前S22对局范围，不能导入：" + bvid)
        annotations = [path for path in annotations if path.stem in state["items"]]
        progress["active_annotation_dir"] = _relative(annotation_dir, ROOT)
        progress["last_run_started_at"] = now()
        # Register the entire queue before the first database write so an
        # interrupted run does not report zero pending after its first game.
        for path in annotations:
            item_bvid = path.stem
            if not _BVID_RE.fullmatch(item_bvid):
                continue
            item = progress["items"].setdefault(item_bvid, {})
            entry = state.get("items", {}).get(item_bvid, {})
            item.update(index=entry.get("index", 10000), date=entry.get("date"))
            try:
                signature = annotation_digest(read_json(path))
            except (ValueError, OSError):
                signature = None
            if (signature is None or item.get("annotation_sha256") != signature
                    or item.get("importer_version") != FRAME_REVIEW_VERSION
                    or item.get("status") not in {"imported", "imported_with_questions", "recorded", "preserved"}):
                item.update(status="pending", state="pending", queued_annotation_sha256=signature)
        _save_progress(progress)
        for path in annotations:
            item_bvid = path.stem
            if not _BVID_RE.fullmatch(item_bvid):
                continue
            try:
                result = _apply_one(item_bvid, state, progress, root=ROOT, annotation_dir=annotation_dir)
            except Exception as exc:
                old = progress["items"].get(item_bvid, {})
                progress["items"][item_bvid] = {**old, "status": "failed", "state": "failed", "error": type(exc).__name__ + ": " + str(exc),
                                                  "checked_at": now()}
                result = {"bvid": item_bvid, "status": "failed", "error": type(exc).__name__ + ": " + str(exc)}
            if result["status"] != "skipped_same_annotation":
                _save_progress(progress)
                batch.checkpoint(state, {"bvid": item_bvid, "stage": "frame_seats_imported", "status": result["status"]}, render=False)
            results.append(result)
        progress["last_run_finished_at"] = now()
        _save_progress(progress)
    return {"results": results, "summary": progress.get("summary", {})}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["apply", "status"])
    parser.add_argument("--bvid")
    parser.add_argument("--annotation-dir", type=Path, help="使用独立标注目录；默认data/extractions/S22/frame_seats")
    args = parser.parse_args(argv)
    if args.bvid and not _BVID_RE.fullmatch(args.bvid):
        parser.error("BVID格式不合法")
    if args.action == "status":
        result = status_report(args.bvid, annotation_dir=args.annotation_dir)
    else:
        result = apply(args.bvid, annotation_dir=args.annotation_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
