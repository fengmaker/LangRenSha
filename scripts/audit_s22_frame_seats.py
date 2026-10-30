"""Read-only acceptance audit for S22 same-day frame seat names."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
from pathlib import Path
from pathlib import PurePosixPath
import re
import sys
from typing import Any
import zipfile

import batch_s22 as batch
import consolidate_s22_day_seats as seats_plan
from database import connect
from s22_frame_seats import annotation_digest


ROOT = batch.ROOT
REPORT = ROOT / "data/reports/S22/S22_画面座位验收.json"
DAY_DIR = ROOT / "data/extractions/S22/按日座位表"
ANNOTATION_DIR = ROOT / "data/extractions/S22/day_frame_seats"
PROGRESS_FILE = ROOT / "data/reports/S22/S22_画面座位补全进度.json"
ARCHIVE_DIR = ROOT / "data/archive/S22_frame_seats"
INFERENCE_REPORT = ROOT / "data/reports/S22/S22_疑点推理复核.json"
RULE_ALIGNMENT_REPORT = ROOT / "data/reports/S22/S22_正式规则对齐记录.json"
RULE_ALIGNMENT_ARCHIVE = ROOT / "data/archive/S22_formal_rule_alignment"
REVIEW_BASE = "http://127.0.0.1:8766/#"


@dataclass(frozen=True)
class FrameStageSnapshot:
    dossier: dict
    sha256: str
    source: str


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def add_error(errors: list[dict], category: str, message: str, *, bvid: str | None = None,
              date: str | None = None, field: str | None = None,
              path: str | None = None) -> None:
    item: dict[str, Any] = {"check": category, "message": message}
    if bvid:
        item["bvid"] = bvid
    if date:
        item["date"] = date
    if field:
        item["field"] = field
    if path:
        item["path"] = path
    errors.append(item)


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def frame_path_exists(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.is_file()


def numeric_time(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and value >= 0)


def projection_without_names_or_roster(value: dict) -> dict:
    """Keep every dossier business field except roster and seat names."""
    result = {key: item for key, item in value.items() if key != "roster"}
    if isinstance(result.get("seats"), list):
        result["seats"] = [
            {key: item for key, item in seat.items() if key != "name"}
            if isinstance(seat, dict) else seat
            for seat in result["seats"]
        ]
    return result


def differing_fields(left: Any, right: Any, prefix: str = "") -> list[str]:
    if type(left) is not type(right):
        return [prefix or "$"]
    if isinstance(left, dict):
        fields = []
        for key in sorted(set(left) | set(right)):
            name = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                fields.append(name)
            else:
                fields.extend(differing_fields(left[key], right[key], name))
            if len(fields) >= 8:
                return fields[:8]
        return fields
    if isinstance(left, list):
        fields = []
        if len(left) != len(right):
            fields.append(f"{prefix}.length")
        for index, (a, b) in enumerate(zip(left, right)):
            fields.extend(differing_fields(a, b, f"{prefix}[{index}]"))
            if len(fields) >= 8:
                return fields[:8]
        return fields
    return [] if left == right else [prefix or "$"]


def preimport_projection_diff(frame_stage: dict, archived: dict) -> list[str]:
    return differing_fields(projection_without_names_or_roster(frame_stage),
                            projection_without_names_or_roster(archived))


def review_url(bvid: str, receipt: dict | None, annotation: dict | None) -> str:
    if isinstance(receipt, dict) and isinstance(receipt.get("review_url"), str):
        return receipt["review_url"]
    if isinstance(annotation, dict) and isinstance(annotation.get("review_url"), str):
        return annotation["review_url"]
    return REVIEW_BASE + bvid


def safe_project_file(path_value: Any, root: Path, allowed_root: Path) -> Path | None:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    raw = Path(path_value)
    path = (raw if raw.is_absolute() else root / raw).resolve()
    boundary_raw = Path(allowed_root)
    if boundary_raw.is_absolute():
        try:
            boundary_relative = boundary_raw.resolve().relative_to(ROOT.resolve())
        except ValueError:
            boundary = boundary_raw.resolve()
        else:
            boundary = (root / boundary_relative).resolve()
    else:
        boundary = (root / boundary_raw).resolve()
    return path if path.is_relative_to(boundary) else None


def dossier_zip_member(output_dir: str) -> str | None:
    if not isinstance(output_dir, str) or not output_dir.strip():
        return None
    relative = PurePosixPath(output_dir.replace("\\", "/"))
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    return relative.joinpath("dossier.json").as_posix()


def _snapshot_from_bytes(raw: bytes, expected_sha256: str, source: str) -> FrameStageSnapshot | None:
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        return None
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    return FrameStageSnapshot(value, expected_sha256, source)


def _alignment_rows(report: dict, bvid: str) -> list[dict]:
    return [row for row in report.get("items", [])
            if isinstance(row, dict) and row.get("bvid") == bvid and row.get("state") == "applied"]


def resolve_frame_stage_snapshot(bvid: str, output_dir: str, receipt_sha256: str,
                                 inference_report: dict, alignment_report: dict,
                                 *, root: Path = ROOT) -> FrameStageSnapshot | None:
    """Find the exact dossier bytes covered by a frame-import receipt."""
    member = dossier_zip_member(output_dir)
    if not member or not isinstance(receipt_sha256, str):
        return None

    backup = inference_report.get("backup", {})
    if inference_report.get("state") == "complete" and isinstance(backup, dict):
        archive_path = safe_project_file(backup.get("files"), root, root / "data/backups")
        if archive_path and archive_path.is_file():
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    raw = archive.read(member)
                snapshot = _snapshot_from_bytes(raw, receipt_sha256, "inference_backup")
                if snapshot:
                    return snapshot
            except (OSError, KeyError, zipfile.BadZipFile):
                pass

    expected_file = PurePosixPath(output_dir.replace("\\", "/")).joinpath("dossier.json").as_posix()
    for row in _alignment_rows(alignment_report, bvid):
        if row.get("before_sha256") != receipt_sha256 or row.get("file", "").replace("\\", "/") != expected_file:
            continue
        snapshot_path = safe_project_file(row.get("before_snapshot"), root, RULE_ALIGNMENT_ARCHIVE)
        if not snapshot_path or not snapshot_path.is_file():
            continue
        try:
            snapshot = _snapshot_from_bytes(snapshot_path.read_bytes(), receipt_sha256,
                                            "rule_alignment_before_snapshot")
        except OSError:
            continue
        if snapshot:
            return snapshot
    return None


def replay_inference_changes(dossier: dict, changes: list[dict]) -> dict:
    from s22_inference_review import changed_value
    return changed_value(dossier, changes, allow_legacy_treasure_faction=True)


def later_rule_alignment_is_valid(bvid: str, before_sha256: str, current_sha256: str,
                                  cache: dict) -> bool:
    from s22_inference_review import later_rule_alignment_valid
    return later_rule_alignment_valid(bvid, before_sha256, current_sha256, cache)


def _alignment_before_value(bvid: str, output_dir: str, before_sha256: str,
                            alignment_report: dict, *, root: Path = ROOT) -> dict | None:
    expected_file = PurePosixPath(output_dir.replace("\\", "/")).joinpath("dossier.json").as_posix()
    rows = [row for row in _alignment_rows(alignment_report, bvid)
            if row.get("before_sha256") == before_sha256
            and row.get("file", "").replace("\\", "/") == expected_file]
    if len(rows) != 1:
        return None
    snapshot_path = safe_project_file(rows[0].get("before_snapshot"), root, RULE_ALIGNMENT_ARCHIVE)
    if not snapshot_path or not snapshot_path.is_file():
        return None
    try:
        snapshot = _snapshot_from_bytes(snapshot_path.read_bytes(), before_sha256, "rule_alignment_before_snapshot")
    except OSError:
        return None
    return snapshot.dossier if snapshot else None


def verify_frame_stage_lineage(bvid: str, output_dir: str, receipt_sha256: str,
                               snapshot: FrameStageSnapshot, current_path: Path,
                               current_sha256: str, current_dossier: dict,
                               inference_report: dict, alignment_report: dict,
                               cache: dict, *, root: Path = ROOT) -> tuple[bool, str | None]:
    """Accept only unchanged receipt bytes or a fully replayed sourced edit chain."""
    if (snapshot.sha256 != receipt_sha256 or not current_path.is_file()
            or batch.digest(current_path) != current_sha256):
        return False, None
    if current_sha256 == receipt_sha256:
        return True, "receipt_unchanged"

    inference_rows = ([row for row in inference_report.get("items", [])
                       if isinstance(row, dict) and row.get("bvid") == bvid]
                      if inference_report.get("state") == "complete" else [])
    if len(inference_rows) == 1:
        item = inference_rows[0]
        if (item.get("output_dir") == output_dir
                and item.get("dossier_sha256") == receipt_sha256
                and isinstance(item.get("after_sha256"), str)
                and isinstance(item.get("changes"), list)):
            try:
                replayed = replay_inference_changes(snapshot.dossier, item["changes"])
            except Exception:
                replayed = None
            after_sha256 = item["after_sha256"]
            if replayed is not None and current_sha256 == after_sha256 and replayed == current_dossier:
                return True, "inference_replay"
            if replayed is not None:
                alignment_before = _alignment_before_value(
                    bvid, output_dir, after_sha256, alignment_report, root=root)
                if (alignment_before == replayed
                        and later_rule_alignment_is_valid(bvid, after_sha256, current_sha256, cache)):
                    return True, "inference_then_rule_alignment"

    try:
        if later_rule_alignment_is_valid(bvid, receipt_sha256, current_sha256, cache):
            return True, "rule_alignment_from_frame_stage"
    except Exception:
        pass
    return False, None


def audit() -> dict:
    errors: list[dict] = []
    counts: dict[str, Any] = {}
    checks: dict[str, Any] = {}
    review_items: list[dict] = []
    source_basis_counts: Counter[str] = Counter()
    archive_file_count = 0
    known_source_count = 0
    checked_source_frames = 0
    named_seat_total = 0
    full_name_games = 0
    db_rows_checked = 0
    dossiers_checked = 0
    frame_stage_dossiers: dict[str, dict] = {}
    frame_snapshot_sources: Counter[str] = Counter()
    frame_chain_counts: Counter[str] = Counter()
    evidence_cache: dict[Path, str] = {}

    try:
        state = batch.load_state()
        plan = seats_plan.build_plan(state)
        entries = state["items"]
        dates = plan["daily"]
        expanded = plan["expanded"]
        expected_dates = {entry.get("date") for entry in entries.values()
                          if isinstance(entry.get("date"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["date"])}
        protected_bvids = set(plan.get("protected_bvids", []))
        expected_annotations = set(entries) - protected_bvids
        counts.update({
            "date_count": len(dates),
            "complete_dates": sum(value["coverage_status"] == "ready" for value in dates.values()),
            "game_count": len(entries),
            "games_with_12_named_seats": 0,
            "named_seat_total": 0,
            "frame_annotation_count": len(expanded),
        })

        checks["recomputed_plan"] = {
            "pass": plan.get("target_count") == len(entries)
                    and set(dates) == expected_dates
                    and set(expanded) == expected_annotations,
            "dates": len(dates), "games": len(entries), "annotations_expected": len(expanded),
            "expected_dates": len(expected_dates), "expected_games": len(entries),
            "expected_annotations": len(expected_annotations),
            "source_annotations_used": plan.get("source_count", 0),
        }
        if not checks["recomputed_plan"]["pass"]:
            add_error(errors, "recomputed_plan", "批次计划数量与预期不符。")

        expected_day_files = {f"{date}.json" for date in dates}
        actual_day_files = {path.name for path in DAY_DIR.glob("*.json")} if DAY_DIR.is_dir() else set()
        matched_day_files = 0
        for date, expected in dates.items():
            path = DAY_DIR / f"{date}.json"
            try:
                actual = read_json(path)
                if actual != expected:
                    add_error(errors, "daily_table", "按日座位表与重算计划不一致。", date=date,
                              path=rel(path))
                else:
                    matched_day_files += 1
            except Exception as exc:
                add_error(errors, "daily_table", f"无法读取或比较按日座位表：{type(exc).__name__}。",
                          date=date, path=rel(path))
        for extra in sorted(actual_day_files - expected_day_files):
            add_error(errors, "daily_table", "存在计划外按日座位表。", path=rel(DAY_DIR / extra))
        checks["daily_tables"] = {
            "pass": matched_day_files == len(dates) and actual_day_files == expected_day_files,
            "expected": len(dates), "actual": len(actual_day_files), "matched": matched_day_files,
        }

        expected_annotation_files = {f"{bvid}.json" for bvid in expanded}
        actual_annotation_files = {path.name for path in ANNOTATION_DIR.glob("*.json")} if ANNOTATION_DIR.is_dir() else set()
        matched_annotations = 0
        for bvid, expected in expanded.items():
            path = ANNOTATION_DIR / f"{bvid}.json"
            try:
                actual = read_json(path)
                if actual != expected:
                    add_error(errors, "game_annotations", "逐局画面座位注释与重算计划不一致。",
                              bvid=bvid, date=expected.get("date"), path=rel(path))
                else:
                    matched_annotations += 1
            except Exception as exc:
                add_error(errors, "game_annotations", f"无法读取或比较逐局注释：{type(exc).__name__}。",
                          bvid=bvid, date=expected.get("date"), path=rel(path))
        for extra in sorted(actual_annotation_files - expected_annotation_files):
            add_error(errors, "game_annotations", "存在计划外逐局画面座位注释。",
                      path=rel(ANNOTATION_DIR / extra))
        checks["game_annotations"] = {
            "pass": matched_annotations == len(expanded) and actual_annotation_files == expected_annotation_files,
            "expected": len(expanded), "actual": len(actual_annotation_files), "matched": matched_annotations,
        }

        # Every selected or overridden named source must belong to this date and
        # point to an existing frame with a numeric timestamp.
        for date, daily in dates.items():
            target_bvids = set(daily.get("target_bvids", []))
            for row in daily.get("seats", []):
                if not row.get("name"):
                    continue
                named_sources = list(row.get("sources", [])) + list(row.get("overridden_sources", []))
                for source in named_sources:
                    known_source_count += 1
                    source_bvid = source.get("source_bvid")
                    entry = entries.get(source_bvid, {}) if isinstance(source_bvid, str) else {}
                    field = f"seats[{row.get('seat')}].name"
                    if source_bvid not in target_bvids or entry.get("date") != date:
                        add_error(errors, "name_sources", "姓名来源BVID不属于同一比赛日。",
                                  bvid=source_bvid, date=date, field=field)
                    if not frame_path_exists(source.get("frame_path")):
                        add_error(errors, "name_sources", "姓名来源截图不存在。", bvid=source_bvid,
                                  date=date, field=field, path=str(source.get("frame_path")))
                    if not numeric_time(source.get("frame_time_ms")):
                        add_error(errors, "name_sources", "姓名来源截图时间不是非负数值。", bvid=source_bvid,
                                  date=date, field=field)
                    source_basis_counts.update([str(source.get("trust_basis") or "unspecified")])
            for source in daily.get("source_frames", []):
                checked_source_frames += 1
                source_bvid = source.get("source_bvid")
                entry = entries.get(source_bvid, {}) if isinstance(source_bvid, str) else {}
                if source_bvid not in target_bvids or entry.get("date") != date:
                    add_error(errors, "source_frames", "比赛日截图来源BVID不属于同一比赛日。",
                              bvid=source_bvid, date=date, field="source_frames")
                if not frame_path_exists(source.get("frame_path")):
                    add_error(errors, "source_frames", "比赛日截图文件不存在。", bvid=source_bvid,
                              date=date, field="source_frames", path=str(source.get("frame_path")))
                if not numeric_time(source.get("frame_time_ms")):
                    add_error(errors, "source_frames", "比赛日截图时间不是非负数值。", bvid=source_bvid,
                              date=date, field="source_frames")
        checks["name_sources"] = {
            "pass": not any(error["check"] in {"name_sources", "source_frames"} for error in errors),
            "named_source_records": known_source_count,
            "daily_frame_records": checked_source_frames,
            "trust_basis_counts": dict(sorted(source_basis_counts.items())),
        }

        # List unresolved questions at per-game granularity for the review page.
        progress: dict = {}
        try:
            progress = read_json(PROGRESS_FILE)
            if not isinstance(progress, dict) or not isinstance(progress.get("items"), dict):
                raise ValueError("progress items missing")
        except Exception as exc:
            add_error(errors, "frame_import_receipts",
                      f"无法读取画面补全进度：{type(exc).__name__}。", path=rel(PROGRESS_FILE))
            progress = {"items": {}}
        progress_items = progress.get("items", {})
        try:
            inference_report = read_json(INFERENCE_REPORT)
            if not isinstance(inference_report, dict):
                inference_report = {}
        except Exception:
            inference_report = {}
        try:
            alignment_report = read_json(RULE_ALIGNMENT_REPORT)
            if not isinstance(alignment_report, dict):
                alignment_report = {}
        except Exception:
            alignment_report = {}

        for date, daily in dates.items():
            questions = [q for q in daily.get("questions", [])
                         if isinstance(q.get("field"), str) and q["field"].endswith(".name")]
            if daily.get("coverage_status") == "ready" and not questions:
                continue
            if not questions:
                questions = [{"field": "seats.name", "reason": "该日座位表尚未完整确认。"}]
            for bvid in daily.get("target_bvids", []):
                receipt = progress_items.get(bvid, {})
                annotation = None
                try:
                    annotation_path = ANNOTATION_DIR / f"{bvid}.json"
                    if annotation_path.is_file():
                        annotation = read_json(annotation_path)
                except Exception:
                    annotation = None
                url = review_url(bvid, receipt, annotation)
                for question in questions:
                    review_items.append({
                        "date": date, "bvid": bvid, "field": question["field"],
                        "reason": question.get("reason"), "review_url": url,
                    })

        # Current dossier names must contain every confirmed daily seat name.
        dossier_names: dict[str, list[dict]] = {}
        for bvid, entry in entries.items():
            dossier_path = ROOT / entry["output_dir"] / "dossier.json"
            try:
                dossier = read_json(dossier_path)
                dossiers_checked += 1
                seat_rows = dossier.get("seats", [])
                names = {seat.get("seat"): seat.get("name") for seat in seat_rows if isinstance(seat, dict)}
                dossier_names[bvid] = seat_rows
                date = entry.get("date")
                daily = dates.get(date, {})
                for daily_seat in daily.get("seats", []):
                    if daily_seat.get("status") != "confirmed" or not daily_seat.get("name"):
                        continue
                    seat_number = daily_seat.get("seat")
                    if names.get(seat_number) != daily_seat["name"]:
                        add_error(errors, "dossier_names", "档案姓名与同日已确认座位姓名不一致。",
                                  bvid=bvid, date=date, field=f"seats[{seat_number}].name",
                                  path=rel(dossier_path))
                named_count = sum(bool(seat.get("name")) for seat in seat_rows if isinstance(seat, dict))
                named_seat_total += named_count
                full_name_games += named_count == 12
            except Exception as exc:
                add_error(errors, "dossier_names", f"无法读取档案或核对姓名：{type(exc).__name__}。",
                          bvid=bvid, date=entry.get("date"), path=rel(dossier_path))
        counts["games_with_12_named_seats"] = full_name_games
        counts["named_seat_total"] = named_seat_total
        checks["dossier_names"] = {
            "pass": not any(error["check"] == "dossier_names" for error in errors),
            "games_checked": dossiers_checked,
            "confirmed_names_checked": sum(
                len([row for row in value.get("seats", []) if row.get("status") == "confirmed" and row.get("name")])
                * len(value.get("target_bvids", [])) for value in dates.values()),
            "protected_sample_checked": seats_plan.PROTECTED_BVID in entries,
        }

        seed_date = "2026-05-26"
        seed_name = "二妖"
        if seed_date not in dates:
            checks["2026-05-26_seat_1_er_yao"] = {
                "pass": True, "skipped": True, "reason": "日期不在当前有效范围。",
            }
        else:
            seed_daily = dates[seed_date]
            seed_row = next((row for row in seed_daily.get("seats", []) if row.get("seat") == 1), {})
            seed_bvids = seed_daily.get("target_bvids", [])
            seed_matches = 0
            for bvid in seed_bvids:
                rows = dossier_names.get(bvid, [])
                seat_one = next((row for row in rows if isinstance(row, dict) and row.get("seat") == 1), {})
                seed_matches += seat_one.get("name") == seed_name
            seed_check_pass = (seed_row.get("name") == seed_name
                               and seed_row.get("status") == "confirmed"
                               and seed_matches == len(seed_bvids) and bool(seed_bvids))
            checks["2026-05-26_seat_1_er_yao"] = {
                "pass": seed_check_pass,
                "expected_name": seed_name,
                "daily_table_name": seed_row.get("name"),
                "daily_table_status": seed_row.get("status"),
                "games_checked": len(seed_bvids),
                "dossier_matches": seed_matches,
            }
            if not seed_check_pass:
                add_error(errors, "seed_seat1", "5月26日1号位“二妖”未在按日表和当日所有档案中一致确认。",
                          date=seed_date, field="seats[1].name")

        # Receipt hashes identify the exact frame-import dossier. Later AI and
        # rule edits are accepted only when their saved transformations replay.
        receipt_count = 0
        active_progress_items = {bvid: progress_items[bvid] for bvid in entries if bvid in progress_items}
        for bvid, receipt in active_progress_items.items():
            annotation_relative = receipt.get("annotation_file")
            if not annotation_relative:
                add_error(errors, "frame_import_receipts", "进度收据缺少annotation_file。", bvid=bvid)
                continue
            annotation_path = ROOT / annotation_relative
            dossier_path = ROOT / entries[bvid]["output_dir"] / "dossier.json"
            if not annotation_path.is_file():
                add_error(errors, "frame_import_receipts", "收据对应的画面注释文件不存在。", bvid=bvid,
                          path=str(annotation_relative))
                continue
            receipt_count += 1
            try:
                if annotation_digest(read_json(annotation_path)) != receipt.get("annotation_sha256"):
                    add_error(errors, "frame_import_receipts", "annotation_sha256与文件不一致。", bvid=bvid,
                              path=str(annotation_relative), field="annotation_sha256")
                if not dossier_path.is_file():
                    add_error(errors, "frame_import_receipts", "收据对应的档案文件不存在。", bvid=bvid,
                              field="dossier_sha256")
                    continue
                current_dossier = read_json(dossier_path)
                current_sha256 = batch.digest(dossier_path)
                receipt_sha256 = receipt.get("dossier_sha256")
                if current_sha256 == receipt_sha256:
                    frame_stage_dossiers[bvid] = current_dossier
                    frame_snapshot_sources["current_receipt"] += 1
                    frame_chain_counts["receipt_unchanged"] += 1
                    continue
                snapshot = resolve_frame_stage_snapshot(
                    bvid, entries[bvid]["output_dir"], receipt_sha256,
                    inference_report, alignment_report, root=ROOT)
                if snapshot is None:
                    add_error(errors, "frame_import_receipts",
                              "找不到与画面阶段收据哈希完全匹配的历史档案。", bvid=bvid,
                              path=rel(dossier_path), field="dossier_sha256")
                    continue
                valid_chain, chain_source = verify_frame_stage_lineage(
                    bvid, entries[bvid]["output_dir"], receipt_sha256, snapshot,
                    dossier_path, current_sha256, current_dossier,
                    inference_report, alignment_report, evidence_cache)
                if not valid_chain:
                    add_error(errors, "frame_import_receipts",
                              "当前档案与画面阶段收据哈希不同，且未通过推理重放/证据规则对齐链验证。",
                              bvid=bvid, path=rel(dossier_path), field="dossier_sha256")
                    continue
                frame_stage_dossiers[bvid] = snapshot.dossier
                frame_snapshot_sources[snapshot.source] += 1
                frame_chain_counts[str(chain_source)] += 1
            except Exception as exc:
                add_error(errors, "frame_import_receipts", f"无法核对收据哈希：{type(exc).__name__}。",
                          bvid=bvid, path=str(annotation_relative))
        missing_receipts = sorted(set(expanded) - set(active_progress_items))
        for bvid in missing_receipts:
            add_error(errors, "frame_import_receipts", "逐局画面注释缺少进度收据。", bvid=bvid)
        checks["frame_import_receipts"] = {
            "pass": not any(error["check"] == "frame_import_receipts" for error in errors),
            "receipts_checked": receipt_count, "expected_imported_receipts": len(expanded),
            "missing_expected_receipts": len(missing_receipts),
            "frame_stage_snapshots_resolved": len(frame_stage_dossiers),
            "snapshot_sources": dict(sorted(frame_snapshot_sources.items())),
            "verified_chain_counts": dict(sorted(frame_chain_counts.items())),
        }

        # Compare every dossier's current seat names with PostgreSQL in a
        # read-only transaction. No database details or credentials are emitted.
        database_ok = True
        try:
            with connect() as conn:
                conn.execute("SET TRANSACTION READ ONLY")
                for bvid, entry in entries.items():
                    try:
                        dossier_path = ROOT / entry["output_dir"] / "dossier.json"
                        dossier = read_json(dossier_path)
                        game = conn.execute("""SELECT g.id FROM games g
                            JOIN game_details d ON d.game_id=g.id WHERE g.slug=%s""",
                                            (dossier["slug"],)).fetchone()
                        if not game:
                            database_ok = False
                            add_error(errors, "database_seat_names", "数据库中找不到对应对局。", bvid=bvid,
                                      date=entry.get("date"), field="games.slug")
                            continue
                        actual = conn.execute("""SELECT s.seat_number AS seat, p.name
                            FROM game_seats s LEFT JOIN people p ON p.id=s.person_id
                            WHERE s.game_id=%s ORDER BY s.seat_number""", (game["id"],)).fetchall()
                        expected_names = [{"seat": seat.get("seat"), "name": seat.get("name")}
                                          for seat in sorted(dossier.get("seats", []), key=lambda item: item.get("seat", 0))]
                        actual_names = [{"seat": row["seat"], "name": row["name"]} for row in actual]
                        db_rows_checked += len(actual_names)
                        if actual_names != expected_names:
                            database_ok = False
                            add_error(errors, "database_seat_names", "数据库game_seats/people姓名与当前档案不一致。",
                                      bvid=bvid, date=entry.get("date"), field="game_seats.name")
                    except Exception as exc:
                        database_ok = False
                        add_error(errors, "database_seat_names",
                                  f"无法核对数据库座位姓名：{type(exc).__name__}。",
                                  bvid=bvid, date=entry.get("date"), field="game_seats.name")
        except Exception as exc:
            database_ok = False
            add_error(errors, "database_seat_names",
                      f"无法建立数据库只读核对：{type(exc).__name__}。")
        checks["database_seat_names"] = {
            "pass": database_ok, "games_checked": len(entries) if database_ok else None,
            "seat_rows_checked": db_rows_checked,
        }

        # Each game must have a pre-import archive with unchanged non-name,
        # non-roster dossier fields. Any exact projection match is sufficient.
        archive_games_checked = 0
        archive_games_matched = 0
        games_without_required_archive = 0
        games_missing_required_archive = 0
        for bvid, entry in entries.items():
            current_path = ROOT / entry["output_dir"] / "dossier.json"
            game_archive_dir = ARCHIVE_DIR / bvid
            candidates = sorted(game_archive_dir.glob("*.json")) if game_archive_dir.is_dir() else []
            archive_file_count += len(candidates)
            receipt = progress_items.get(bvid, {})
            seats_applied = receipt.get("seat_names_applied", 0)
            try:
                seats_applied = int(seats_applied)
            except (TypeError, ValueError):
                seats_applied = 0
            protected = entry.get("state") == "preserved"
            archive_required = not protected and seats_applied > 0
            if not candidates and not archive_required:
                # No dossier mutation means the importer had no reason to make
                # a pre-write archive. Keep the protected sample untouched.
                games_without_required_archive += 1
                continue
            if not candidates:
                games_missing_required_archive += 1
                add_error(errors, "preimport_archives", "姓名已写入档案但缺少导入前档案。",
                          bvid=bvid, date=entry.get("date"), path=rel(game_archive_dir))
                continue
            archive_games_checked += 1
            try:
                # Later AI/rule edits may legitimately change business fields.
                # Compare against the dossier identified by the frame receipt,
                # while current names are independently checked above/against DB.
                frame_stage = frame_stage_dossiers.get(bvid)
                if frame_stage is None:
                    add_error(errors, "preimport_archives",
                              "缺少经画面收据哈希验证的历史档案，无法核对导入前业务字段。",
                              bvid=bvid, date=entry.get("date"), path=rel(game_archive_dir))
                    continue
                matching_archive = None
                differences: list[tuple[str, list[str]]] = []
                for archive_path in candidates:
                    try:
                        archived = read_json(archive_path)
                        diff = preimport_projection_diff(frame_stage, archived)
                        if not diff:
                            matching_archive = archive_path
                            break
                        differences.append((rel(archive_path), diff))
                    except Exception as exc:
                        differences.append((rel(archive_path), [f"读取失败:{type(exc).__name__}"]))
                if matching_archive:
                    archive_games_matched += 1
                else:
                    first_difference = differences[0][1] if differences else []
                    add_error(errors, "preimport_archives",
                              "找不到非姓名/roster业务字段完全一致的导入前档案。",
                              bvid=bvid, date=entry.get("date"), field=", ".join(first_difference[:8]) or None,
                              path=rel(game_archive_dir))
            except Exception as exc:
                add_error(errors, "preimport_archives", f"无法比较导入前档案：{type(exc).__name__}。",
                          bvid=bvid, date=entry.get("date"), path=rel(current_path))
        checks["preimport_archives"] = {
            "pass": not any(error["check"] == "preimport_archives" for error in errors),
            "games_with_archives_checked": archive_games_checked,
            "games_with_matching_archive": archive_games_matched,
            "games_missing_required_archive": games_missing_required_archive,
            "games_without_required_archive": games_without_required_archive,
            "archives_required": sum(
                not (entry.get("state") == "preserved"
                     or progress_items.get(bvid, {}).get("seat_names_applied", 0) == 0)
                for bvid, entry in entries.items()),
            "games_expected": len(entries),
            "archive_files_checked": archive_file_count,
            "projection": "frame-receipt-stage dossier fields except root roster and seats[].name",
        }

        pending_by_date: dict[str, dict] = {}
        for item in review_items:
            date_info = pending_by_date.setdefault(item["date"], {"date": item["date"], "bvids": [], "fields": []})
            if item["bvid"] not in date_info["bvids"]:
                date_info["bvids"].append(item["bvid"])
            if item["field"] not in date_info["fields"]:
                date_info["fields"].append(item["field"])

        counts["pending_dates"] = len(pending_by_date)
        counts["pending_review_items"] = len(review_items)
        report = {
            "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            "valid": not errors,
            "counts": counts,
            "checks": checks,
            "pending_dates": list(pending_by_date.values()),
            "pending_review_items": review_items,
            "source_counts": {
                "plan_source_annotations": plan.get("source_count", 0),
                "named_source_records": known_source_count,
                "daily_frame_records": checked_source_frames,
                "named_source_trust_basis": dict(sorted(source_basis_counts.items())),
                "frame_import_receipts": len(active_progress_items),
                "preimport_archive_files": archive_file_count,
            },
            "errors": errors,
            "note": "本报告核对文件、来源链、档案与数据库的一致性；不等于对截图姓名已完成人工事实确认。7月3日特辑没有常规左右姓名栏，未根据画面外信息补名。",
        }
        return report
    except Exception as exc:
        return {
            "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            "valid": False, "counts": counts, "checks": checks,
            "pending_dates": [], "pending_review_items": [],
            "source_counts": {},
            "errors": [{"check": "audit", "message": f"验收脚本遇到未处理异常：{type(exc).__name__}"}],
            "note": "本报告核对文件、来源链、档案与数据库的一致性；不等于对截图姓名已完成人工事实确认。",
        }


def main() -> int:
    report = audit()
    try:
        batch.atomic_json(REPORT, report)
    except Exception as exc:
        print(json.dumps({"valid": False, "report_write_error": type(exc).__name__}, ensure_ascii=False))
        return 2
    summary = {key: report.get(key) for key in ("valid", "counts", "checks", "source_counts")}
    summary["error_count"] = len(report.get("errors", []))
    summary["report"] = rel(REPORT)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
