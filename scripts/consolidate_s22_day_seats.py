"""Consolidate confirmed S22 seat-name evidence within each game day.

This is a review-artifact generator only: it never writes to the game database
or edits the original per-game OCR annotations. Daily summaries and propagated
annotations are stored in separate directories.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import quote

import batch_s22 as batch

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data/extractions/S22/frame_seats"
MANUAL_DIR = ROOT / "data/extractions/S22/manual_day_seats"
DAY_OUTPUT_DIR = ROOT / "data/extractions/S22/按日座位表"
ANNOTATION_OUTPUT_DIR = ROOT / "data/extractions/S22/day_frame_seats"
SEATS = tuple(range(1, 13))
SEED_BVID = "BV1jJVT6SEWc"
PROTECTED_BVID = "BV1yt7v6QE3Q"
NO_SIDEBAR_DATES = {"2026-07-03"}
RELIABLE_MATCH_KINDS = {"canonical_name", "approved_local_alias"}
MIN_OCR_CONFIDENCE = 0.80
USER_RULE = "同一天的对局座位号是一样的；本表只在同一比赛日内复用座位姓名，不跨日期推移。"
_BVID_RE = re.compile(r"BV[0-9A-Za-z]+\Z")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON根节点不是对象：{path}")
    return value


def digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _rel(path: str | Path | None, root: Path) -> str | None:
    if path in (None, ""):
        return None
    candidate = Path(str(path))
    absolute = candidate if candidate.is_absolute() else root / candidate
    try:
        return absolute.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        # Annotation paths are evidence metadata. Keep external paths explicit
        # rather than silently rewriting them into project-relative paths.
        return str(path)


def _source_record(bvid: str, row: dict, top_source: dict, root: Path,
                   *, trust_basis: str, visible_label: Any = None) -> dict[str, Any]:
    frame_path = row.get("frame_path") or top_source.get("frame_path")
    frame_time_ms = row.get("frame_time_ms")
    if frame_time_ms is None:
        frame_time_ms = top_source.get("frame_time_ms")
    return {
        "source_bvid": bvid,
        "frame_path": _rel(frame_path, root),
        "frame_time_ms": frame_time_ms,
        "visible_label": visible_label if visible_label is not None else row.get("visible_label"),
        "trust_basis": trust_basis,
    }


def _user_corrected_name(annotation: dict, row: dict) -> str | None:
    seat_number = row.get("seat")
    for correction in annotation.get("user_corrections", []):
        if correction.get("seat") == seat_number and isinstance(correction.get("after"), str):
            after = correction["after"].strip()
            if after:
                return after
    if row.get("resolution") == "user_confirmed" or row.get("user_confirmed") is True:
        name = row.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _qualified_ocr(row: dict) -> tuple[bool, str]:
    name = row.get("name")
    if not isinstance(name, str) or not name.strip():
        return False, "name_missing"
    match = row.get("match")
    kind = match.get("kind") if isinstance(match, dict) else None
    if kind not in RELIABLE_MATCH_KINDS:
        return False, "unverified_match"
    confidence = row.get("confidence")
    if confidence is not None:
        try:
            if float(confidence) < MIN_OCR_CONFIDENCE:
                return False, "low_confidence"
        except (TypeError, ValueError):
            return False, "invalid_confidence"
    return True, kind


def _annotation_candidates(bvid: str, annotation: dict, root: Path) -> tuple[dict[int, list[dict]], dict[int, list[dict]]]:
    """Return trusted and excluded evidence by seat, without label inference."""
    top_source = annotation.get("source") if isinstance(annotation.get("source"), dict) else {}
    trusted: dict[int, list[dict]] = defaultdict(list)
    excluded: dict[int, list[dict]] = defaultdict(list)
    is_primary_seed = bvid == SEED_BVID
    for row in annotation.get("seats", []):
        if not isinstance(row, dict) or type(row.get("seat")) is not int or row["seat"] not in SEATS:
            continue
        seat_number = row["seat"]
        corrected = _user_corrected_name(annotation, row)
        if corrected:
            trusted[seat_number].append({
                "name": corrected,
                "priority": 100,
                "trust_basis": "user_correction",
                "source": _source_record(bvid, row, top_source, root,
                                          trust_basis="user_correction", visible_label=row.get("visible_label")),
            })
            continue

        # This is the specifically reviewed three-game seed named in the task:
        # its 12 canonical names and explicit corrections were visually checked
        # by the primary agent, and seat 1 carries the user's correction above.
        if is_primary_seed:
            name = row.get("name")
            if isinstance(name, str) and name.strip():
                trusted[seat_number].append({
                    "name": name.strip(), "priority": 80,
                    "trust_basis": "primary_agent_visual_seed",
                    "source": _source_record(bvid, row, top_source, root,
                                              trust_basis="primary_agent_visual_seed"),
                })
                continue

        eligible, basis = _qualified_ocr(row)
        if eligible:
            name = row["name"].strip()
            trusted[seat_number].append({
                "name": name,
                "priority": 60,
                "trust_basis": basis,
                "source": _source_record(bvid, row, top_source, root, trust_basis=basis),
            })
        else:
            excluded[seat_number].append({
                "name": None,
                "visible_label": row.get("visible_label"),
                "reason": basis,
                "source": _source_record(bvid, row, top_source, root, trust_basis=basis),
            })
    return trusted, excluded


def _manual_candidates(path: Path, date: str, valid_bvids: set[str], root: Path) -> tuple[dict[int, list[dict]], list[str]]:
    trusted: dict[int, list[dict]] = defaultdict(list)
    notes: list[str] = []
    if not path.is_file():
        return trusted, notes
    annotation = read_json(path)
    if annotation.get("date") != date:
        notes.append(f"忽略日期不匹配的目视文件：{path.name}")
        return trusted, notes
    for row in annotation.get("seats", []):
        if not isinstance(row, dict) or type(row.get("seat")) is not int or row["seat"] not in SEATS:
            notes.append(f"目视记录座位号无效：{path.name}")
            continue
        bvid = row.get("source_bvid")
        if not isinstance(bvid, str) or bvid not in valid_bvids:
            notes.append(f"目视记录BVID不属于本日批次：{path.name} seat={row.get('seat')}")
            continue
        name = row.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        method = row.get("reading_method")
        if method not in {"assistant_visual", "user_visual", "user_confirmed"}:
            notes.append(f"目视记录缺少明确阅读方式：{path.name} seat={row.get('seat')}")
            continue
        source = {
            "source_bvid": bvid,
            "frame_path": _rel(row.get("frame_path"), root),
            "frame_time_ms": row.get("frame_time_ms"),
            "visible_label": row.get("visible_label"),
            "trust_basis": method,
            "source_origin": _rel(path, root),
        }
        trusted[row["seat"]].append({
            "name": name.strip(),
            "priority": 100 if method == "user_confirmed" else 80,
            "trust_basis": method,
            "source": source,
        })
    return trusted, notes


def _day_frame_sources(date: str, day_entries: list[dict], source_dir: Path, root: Path,
                      *, reason: str = "captured_game_frame") -> list[dict]:
    sources: list[dict] = []
    for entry in day_entries:
        bvid = entry["bvid"]
        capture_path = source_dir / bvid / "capture.json"
        if not capture_path.is_file():
            continue
        try:
            capture = read_json(capture_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if capture.get("date") not in (None, date) or capture.get("bvid") not in (None, bvid):
            continue
        sources.append({
            "source_bvid": bvid,
            "frame_path": _rel(capture.get("frame_path"), root),
            "frame_time_ms": capture.get("frame_time_ms"),
            "source_kind": capture.get("source_kind", "video_frame"),
            "game_number": entry.get("game_number"),
            "reason": reason,
        })
    return sources


def _source_sort_key(candidate: dict) -> tuple[str, int, str]:
    source = candidate.get("source", {})
    time = source.get("frame_time_ms")
    return (str(source.get("source_bvid") or ""), time if type(time) is int else -1,
            str(source.get("frame_path") or ""))


def _number_key(value: Any) -> int:
    return value if type(value) is int else 0


def build_plan(state: dict, *, source_dir: Path = SOURCE_DIR, manual_dir: Path = MANUAL_DIR,
               root: Path = ROOT, protected_bvids: set[str] | None = None) -> dict[str, Any]:
    """Build date summaries and per-game annotations entirely in memory."""
    entries = state.get("items")
    if not isinstance(entries, dict):
        raise ValueError("S22批次进度缺少items映射")
    protected = {PROTECTED_BVID, *(protected_bvids or set())}
    by_date: dict[str, list[dict]] = defaultdict(list)
    entry_by_bvid: dict[str, dict] = {}
    for bvid, entry in entries.items():
        date = entry.get("date")
        if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue
        if not _BVID_RE.fullmatch(str(bvid)):
            continue
        by_date[date].append(entry)
        entry_by_bvid[bvid] = entry
        if entry.get("state") == "preserved":
            protected.add(bvid)

    daily: dict[str, dict] = {}
    expanded: dict[str, dict] = {}
    source_count = 0
    for date, day_entries in sorted(by_date.items()):
        day_entries.sort(key=lambda item: (_number_key(item.get("game_number")),
                                           _number_key(item.get("index")), item["bvid"]))
        day_bvids = {item["bvid"] for item in day_entries}
        candidates: dict[int, list[dict]] = defaultdict(list)
        excluded: dict[int, list[dict]] = defaultdict(list)
        day_notes: list[str] = []
        used_source_bvids: list[str] = []
        for entry in day_entries:
            bvid = entry["bvid"]
            if bvid in protected:
                continue
            path = source_dir / f"{bvid}.json"
            if not path.is_file():
                continue
            annotation = read_json(path)
            if annotation.get("bvid") not in (None, bvid):
                day_notes.append(f"忽略BVID字段与文件名不一致的来源：{bvid}")
                continue
            if annotation.get("date") not in (None, date):
                day_notes.append(f"忽略日期与主批次不一致的来源：{bvid} annotation_date={annotation.get('date')}")
                continue
            trusted, not_trusted = _annotation_candidates(bvid, annotation, root)
            if trusted or not_trusted:
                source_count += 1
                used_source_bvids.append(bvid)
            for seat_number, records in trusted.items():
                candidates[seat_number].extend(records)
            for seat_number, records in not_trusted.items():
                excluded[seat_number].extend(records)
        manual_path = manual_dir / f"{date}.json"
        manual, manual_notes = _manual_candidates(manual_path, date, day_bvids - protected, root)
        day_notes.extend(manual_notes)
        for seat_number, records in manual.items():
            candidates[seat_number].extend(records)

        seat_rows: list[dict] = []
        questions: list[dict] = []
        resolved_names: dict[str, list[int]] = defaultdict(list)
        for seat_number in SEATS:
            records = sorted(candidates.get(seat_number, []), key=_source_sort_key)
            user_records = [record for record in records if record["priority"] >= 100]
            if user_records:
                eligible = user_records
                # A direct user correction is highest priority; retain all other
                # evidence for audit without making it a competing candidate.
                suppressed = [record for record in records if record not in user_records]
            else:
                eligible = records
                suppressed = []
            names = sorted({record["name"] for record in eligible})
            if len(names) == 1:
                name = names[0]
                selected = [record for record in eligible if record["name"] == name]
                sources = [record["source"] for record in selected]
                row_status = "confirmed"
                resolved_names[name].append(seat_number)
            elif len(names) > 1:
                name = None
                selected = eligible
                sources = [record["source"] for record in eligible]
                row_status = "conflict"
                question = {
                    "id": digest({"date": date, "seat": seat_number, "names": names})[:14],
                    "field": f"seats[{seat_number}].name",
                    "label": f"{seat_number}号姓名",
                    "reason": "同日高可信姓名来源不一致，保留双方候选，需人工核对。",
                    "candidates": [{"name": candidate_name,
                                    "sources": [record["source"] for record in eligible if record["name"] == candidate_name]}
                                   for candidate_name in names],
                }
                questions.append(question)
            else:
                name = None
                selected = []
                sources = []
                row_status = "missing"

            labels = sorted({str(record["source"].get("visible_label")) for record in selected
                             if record["source"].get("visible_label") not in (None, "")})
            seat_rows.append({
                "seat": seat_number,
                "name": name,
                "visible_label": labels[0] if len(labels) == 1 else (labels if labels else None),
                "status": row_status,
                "sources": sources,
                "source_bvid": sources[0]["source_bvid"] if sources else None,
                "frame_path": sources[0]["frame_path"] if sources else None,
                "frame_time_ms": sources[0]["frame_time_ms"] if sources else None,
                "trust_basis": sorted({record["trust_basis"] for record in selected}),
                "overridden_sources": [record["source"] for record in suppressed],
                "untrusted_sources": [record["source"] for record in excluded.get(seat_number, [])],
            })

        for name, seats in resolved_names.items():
            if len(seats) > 1:
                for seat_number in seats:
                    row = seat_rows[seat_number - 1]
                    row["status"] = "duplicate"
                    row["name"] = None
                    questions.append({
                        "id": digest({"date": date, "name": name, "seat": seat_number})[:14],
                        "field": f"seats[{seat_number}].name",
                        "label": f"{seat_number}号姓名",
                        "reason": f"同日座位表中“{name}”重复出现在座位{seats}，需核对。",
                        "candidates": [{"name": name, "seats": seats,
                                        "sources": [source for other in seats for source in seat_rows[other - 1]["sources"]]}],
                    })

        ready = all(row["name"] for row in seat_rows) and len({row["name"] for row in seat_rows}) == 12 and not questions
        no_sidebar = date in NO_SIDEBAR_DATES
        captured_sources = _day_frame_sources(
            date, day_entries, source_dir, root,
            reason="no_sidebar_labels" if no_sidebar else "captured_game_frame")
        special_sources = captured_sources if no_sidebar else []
        if no_sidebar:
            day_notes.append("京师和Ta的朋友们3特辑无常规左右姓名栏；不根据脸、遮挡桌牌或其他日期推断姓名。")
            for seat_number in SEATS:
                questions.append({
                    "id": digest({"date": date, "seat": seat_number, "reason": "no_sidebar_labels"})[:14],
                    "field": f"seats[{seat_number}].name",
                    "label": f"{seat_number}号姓名",
                    "reason": "特辑画面无常规姓名栏，需手工确认本日12座名册。",
                    "source_frames": special_sources,
                })
        daily_value = {
            "season": "S22", "date": date,
            "status": "needs_manual_lineup" if no_sidebar else "pending",
            "coverage_status": "no_sidebar_labels" if no_sidebar else ("ready" if ready else "pending"),
            "same_day_rule": USER_RULE,
            "target_bvids": [entry["bvid"] for entry in day_entries],
            "source_bvids": sorted(set(used_source_bvids)),
            "source_frames": captured_sources,
            "seats": seat_rows,
            "questions": questions,
            "notes": day_notes,
        }
        daily[date] = daily_value

        for entry in day_entries:
            bvid = entry["bvid"]
            if bvid in protected:
                continue
            annotation_rows = []
            contributing_bvids: set[str] = set()
            for daily_row in seat_rows:
                row_sources = daily_row["sources"]
                untrusted_row_sources = daily_row["untrusted_sources"]
                contributing_bvids.update(source["source_bvid"] for source in row_sources if source.get("source_bvid"))
                first = (row_sources[0] if row_sources else
                         untrusted_row_sources[0] if untrusted_row_sources else
                         captured_sources[0] if captured_sources else {})
                same_day_question = next((question for question in questions
                                          if question.get("field") == f"seats[{daily_row['seat']}].name"), None)
                annotation_rows.append({
                    "seat": daily_row["seat"],
                    "visible_label": daily_row["visible_label"] if isinstance(daily_row["visible_label"], str) else None,
                    "name": daily_row["name"],
                    "match": {"kind": "same_day_propagated", "basis": daily_row["trust_basis"]} if daily_row["name"] else None,
                    "same_day_trust_basis": daily_row["trust_basis"],
                    "same_day_sources": row_sources,
                    "untrusted_sources": untrusted_row_sources,
                    "same_day_question": same_day_question,
                    "source_bvid": first.get("source_bvid"),
                    "frame_path": first.get("frame_path"),
                    "frame_time_ms": first.get("frame_time_ms"),
                    "resolution": "same_day_propagated" if daily_row["name"] else None,
                    "user_confirmed": daily_row["status"] == "confirmed" and "user_correction" in daily_row["trust_basis"],
                })
            chosen_sources = [source for row in seat_rows for source in row["sources"]]
            untrusted_sources = [source for row in seat_rows for source in row["untrusted_sources"]]
            representative_source = (chosen_sources[0] if chosen_sources else
                                     untrusted_sources[0] if untrusted_sources else
                                     captured_sources[0] if captured_sources else {})
            contributing_bvids.update(item.get("source_bvid") for item in special_sources if item.get("source_bvid"))
            contributing_bvids.update(item.get("source_bvid") for item in captured_sources if item.get("source_bvid"))
            source = {
                "kind": "same_day_frame",
                "date": date,
                "source_date": date,
                "source_bvid": representative_source.get("source_bvid") or next(iter(sorted(contributing_bvids)), None),
                "source_bvids": sorted(contributing_bvids),
                "frame_path": representative_source.get("frame_path"),
                "frame_time_ms": representative_source.get("frame_time_ms"),
                "description": USER_RULE,
                "user_rule": USER_RULE,
                "same_day_rule": USER_RULE,
                "source_frames": captured_sources,
            }
            expanded[bvid] = {
                "season": "S22", "date": date, "bvid": bvid,
                "scope": "seat_name_only", "status": "needs_manual_lineup" if no_sidebar else "pending",
                "coverage_status": "no_sidebar_labels" if no_sidebar else ("ready" if ready else "pending"),
                "same_day_rule": USER_RULE,
                "source": source,
                "seats": annotation_rows,
                "questions": questions,
                "source_day_summary": f"data/extractions/S22/按日座位表/{date}.json",
            }

    return {
        "daily": daily,
        "expanded": expanded,
        "date_count": len(by_date),
        "target_count": sum(len(entries) for entries in by_date.values()),
        "annotation_target_count": len(expanded),
        "protected_bvids": sorted(protected.intersection(entry_by_bvid)),
        "source_count": source_count,
        "missing_dates": [date for date, value in daily.items() if value["coverage_status"] != "ready"],
        "missing_sidebar_dates": [date for date, value in daily.items()
                                  if value["coverage_status"] == "pending"],
        "needs_manual_lineup_dates": [date for date, value in daily.items()
                                      if value["coverage_status"] == "no_sidebar_labels"],
        "dates_without_sources": [date for date, value in daily.items() if not value["source_bvids"]],
    }


def write_day_index(daily: dict, output_dir: Path) -> None:
    """Expose the shared lineups as a readable table with source-frame links."""
    columns = ["比赛日期", "姓名覆盖", *[f"{seat}号" for seat in SEATS], "复核入口"]
    records, rows = [], []
    esc = html.escape
    for date, day in sorted(daily.items()):
        by_seat = {row["seat"]: row for row in day["seats"]}
        coverage = "12座齐全" if day["coverage_status"] == "ready" else "名册待确认"
        review_url = "http://127.0.0.1:8766/#" + day["target_bvids"][0]
        names = [by_seat[seat].get("name") or "待确认" for seat in SEATS]
        records.append([date, coverage, *names, review_url])
        cells = [f'<td>{esc(date)}</td>', f'<td>{esc(coverage)}</td>']
        for seat, name in zip(SEATS, names):
            row = by_seat[seat]
            if row.get("frame_path"):
                path = Path(row["frame_path"])
                source_path = path if path.is_absolute() else ROOT / path
                try:
                    href = Path(os.path.relpath(source_path, output_dir)).as_posix()
                except ValueError:
                    href = source_path.as_posix()
                seconds = int((row.get("frame_time_ms") or 0) / 1000)
                label = f"{row.get('source_bvid')} · {seconds//3600}:{seconds//60%60:02}:{seconds%60:02}"
                content = f'<a href="{esc(quote(href, safe="/:"))}" title="{esc(label)}" target="_blank">{esc(name)}</a>'
            else:
                content = '<span class="missing">' + esc(name) + '</span>'
            cells.append('<td>' + content + '</td>')
        cells.append(f'<td><a href="{esc(review_url)}">保存更正</a></td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    with (output_dir / "按日座位表.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(records)
    header = ''.join('<th>' + esc(column) + '</th>' for column in columns)
    ready_days = sum(day["coverage_status"] == "ready" for day in daily.values())
    pending_days = '、'.join(date for date, day in sorted(daily.items()) if day["coverage_status"] != "ready")
    coverage_note = f'{ready_days}/{len(daily)}个比赛日姓名齐全。' + (f'待确认日期：{pending_days}。' if pending_days else '')
    document = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>S22 按日座位表</title><style>body{font:15px/1.6 system-ui,sans-serif;margin:24px;color:#172335}'
        'table{border-collapse:collapse;min-width:1250px}th,td{border:1px solid #d4dde7;padding:9px;white-space:nowrap}'
        'th{background:#eaf1f8;position:sticky;top:0}a{color:#195ca3}.missing{color:#b45309}'
        'tbody tr:nth-child(even){background:#f6f8fb}.scroll{overflow:auto;max-height:78vh}</style>'
        '<h1>S22 按日座位表</h1><p>同日各局使用相同座位。点击姓名可查看实际来源截图；'
        '“保存更正”进入可编辑工作台。游戏身份和事件分别按各局转写记录。</p>'
        '<p>' + esc(coverage_note) + 'AI整理结果保留来源，尚未标记用户人工复核完成。'
        '<a href="按日座位表.csv">下载CSV</a></p>'
        '<div class="scroll"><table><thead><tr>' + header + '</tr></thead><tbody>' + ''.join(rows)
        + '</tbody></table></div></html>')
    (output_dir / "按日座位表.html").write_text(document, encoding="utf-8")


def write_plan(plan: dict, *, day_output_dir: Path = DAY_OUTPUT_DIR,
               annotation_output_dir: Path = ANNOTATION_OUTPUT_DIR,
               source_dir: Path = SOURCE_DIR) -> dict[str, int]:
    """Atomically write generated outputs in their dedicated output dirs."""
    source_resolved = Path(source_dir).resolve()
    for output_dir in (day_output_dir, annotation_output_dir):
        if output_dir.resolve() == source_resolved or source_resolved in output_dir.resolve().parents:
            raise ValueError("输出目录不能位于原始OCR frame_seats目录内")
    day_output_dir.mkdir(parents=True, exist_ok=True)
    annotation_output_dir.mkdir(parents=True, exist_ok=True)
    for date, value in plan["daily"].items():
        batch.atomic_json(day_output_dir / f"{date}.json", value)
    write_day_index(plan["daily"], day_output_dir)
    for bvid, value in plan["expanded"].items():
        if bvid == PROTECTED_BVID:
            continue
        batch.atomic_json(annotation_output_dir / f"{bvid}.json", value)
    return {"daily_files": len(plan["daily"]), "annotations": len(plan["expanded"])}


def _filtered(plan: dict, date: str | None, bvid: str | None) -> dict:
    result = dict(plan)
    if bvid and not date:
        selected_annotation = plan["expanded"].get(bvid)
        date = selected_annotation.get("date") if selected_annotation else None
    if date:
        result["daily"] = {key: value for key, value in plan["daily"].items() if key == date}
        result["expanded"] = {key: value for key, value in plan["expanded"].items()
                              if value.get("date") == date}
    if bvid:
        result["expanded"] = {key: value for key, value in result["expanded"].items() if key == bvid}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "preview", "write"), nargs="?", default="status")
    parser.add_argument("--date")
    parser.add_argument("--bvid")
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--manual-dir", type=Path, default=MANUAL_DIR)
    parser.add_argument("--day-output-dir", type=Path, default=DAY_OUTPUT_DIR)
    parser.add_argument("--annotation-output-dir", type=Path, default=ANNOTATION_OUTPUT_DIR)
    args = parser.parse_args(argv)
    if args.bvid and not _BVID_RE.fullmatch(args.bvid):
        parser.error("BVID格式不合法")
    state = batch.load_state()
    plan = build_plan(state, source_dir=args.source_dir, manual_dir=args.manual_dir, root=ROOT)
    if args.action == "write":
        writes = write_plan(plan, day_output_dir=args.day_output_dir,
                            annotation_output_dir=args.annotation_output_dir,
                            source_dir=args.source_dir)
        output = {"summary": {key: value for key, value in plan.items()
                              if key not in {"daily", "expanded"}}, "writes": writes}
    elif args.action == "status":
        coverage = [{"date": date, "coverage_status": value["coverage_status"],
                     "missing_seats": [row["seat"] for row in value["seats"] if not row["name"]],
                     "questions": len(value["questions"]), "source_bvids": value["source_bvids"]}
                    for date, value in plan["daily"].items()]
        output = {"summary": {key: value for key, value in plan.items()
                              if key not in {"daily", "expanded"}},
                  "coverage": coverage}
    else:
        selected = _filtered(plan, args.date, args.bvid)
        output = {
            "summary": {key: value for key, value in plan.items() if key not in {"daily", "expanded"}},
            "daily": selected["daily"],
            "expanded": selected["expanded"] if args.action == "preview" else None,
        }
    print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
