"""Read S22 video-frame nameplates into seat-name-only review candidates.

Install the official, bundled-model OCR package in the workspace venv with:
    .venv/Scripts/python -m pip install rapidocr onnxruntime

The script never writes game dossiers or database records. It reads one local
game dossier roster, OCRs the visible left/right seat strips, and writes a
separate JSON review candidate beside the captured frame folders.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FRAME_ROOT = ROOT / "data/extractions/S22/frame_seats"
GAME_ROOT = ROOT / "data/games/S22"
ALIAS_CSV = ROOT / "data/weibo/2026-05-26_2026-10-20/参赛名单/人名去重_照片映射.csv"
READY_CONFIDENCE = 0.85
SIDE_ROW_RATIOS = (0.181, 0.342, 0.500, 0.658, 0.817, 0.977)


def norm(value: str) -> str:
    return re.sub(r"[\s_\-·.（）()「」『』【】\[\]{}]+", "", value).casefold()


def load_alias_map(path: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, str]]]:
    """Return approved alias->canonical, all local label targets, and evidence rows."""
    alias_to_canonical: dict[str, set[str]] = {}
    all_label_targets: dict[str, set[str]] = {}
    evidence: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return alias_to_canonical, all_label_targets, evidence
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("赛季") != "S22":
                continue
            label = (row.get("原图名字") or "").strip()
            canonical = (row.get("去重后姓名") or "").strip()
            state = (row.get("原人工确认状态") or "").strip()
            if not label or not canonical:
                continue
            all_label_targets.setdefault(norm(label), set()).add(canonical)
            all_label_targets.setdefault(norm(canonical), set()).add(canonical)
            if state not in {"确认无误", "已修正"}:
                continue
            alias_to_canonical.setdefault(norm(label), set()).add(canonical)
            alias_to_canonical.setdefault(norm(canonical), set()).add(canonical)
            evidence.setdefault(norm(label), row)
    return alias_to_canonical, all_label_targets, evidence


def dossier_path_for(bvid: str) -> Path | None:
    matches = list(GAME_ROOT.glob(f"*_{bvid}/dossier.json"))
    return matches[0] if len(matches) == 1 else None


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_frame_path(value: str | None, frame_dir: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if path.is_file():
        return path.resolve()
    fallback = frame_dir / Path(value).name
    return fallback.resolve() if fallback.is_file() else None


def output_rel(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def bbox_from_points(points: Any, x0: float = 0, y0: float = 0, scale: float = 1) -> list[list[float]]:
    return [[round(x0 + float(point[0]) / scale, 2), round(y0 + float(point[1]) / scale, 2)] for point in points]


def run_pass(engine: Any, image: Any, pass_name: str, x0: int = 0, y0: int = 0, scale: int = 1) -> tuple[list[dict[str, Any]], float]:
    result = engine(image)
    lines: list[dict[str, Any]] = []
    boxes = result.boxes if result.boxes is not None else []
    for box, text, score in zip(boxes, result.txts or [], result.scores or []):
        text = str(text).strip()
        if not text:
            continue
        lines.append({
            "text": text,
            "confidence": round(float(score), 5),
            "bbox": bbox_from_points(box, x0=x0, y0=y0, scale=scale),
            "ocr_pass": pass_name,
        })
    return lines, float(result.elapse or 0)


def line_center(line: dict[str, Any]) -> tuple[float, float]:
    points = line["bbox"]
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def names_in_text(text: str, candidate_names: list[str], alias_to_canonical: dict[str, set[str]]) -> list[tuple[str, str, str]]:
    """Return (canonical, matched label, match kind), with no fuzzy Hanzi repair."""
    text_n = norm(text)
    hits: dict[str, tuple[str, str]] = {}
    for canonical in candidate_names:
        canonical_n = norm(canonical)
        if len(canonical_n) >= 2 and canonical_n in text_n:
            hits[canonical] = (canonical, "exact_or_canonical_substring")
    for alias_n, canonicals in alias_to_canonical.items():
        if len(alias_n) < 2 or alias_n not in text_n:
            continue
        for canonical in canonicals:
            if canonical in candidate_names:
                existing = hits.get(canonical)
                label = alias_n if existing is None else existing[0]
                kind = "approved_local_alias" if alias_n != norm(canonical) else "canonical_name"
                hits[canonical] = (label, kind)
    result = []
    for canonical, (matched_label, kind) in hits.items():
        result.append((canonical, matched_label, kind))
    # Prefer the longest literal match so a name such as 华仔仔 is not
    # reported as ambiguous with a shorter contained name such as 华仔.
    if result:
        longest = max(len(norm(row[1])) for row in result)
        result = [row for row in result if len(norm(row[1])) == longest]
    return sorted(result, key=lambda row: len(norm(row[1])), reverse=True)


def known_name_targets(text: str, all_label_targets: dict[str, set[str]]) -> list[tuple[str, str]]:
    text_n = norm(text)
    found: list[tuple[str, str]] = []
    for label_n, canonical_names in all_label_targets.items():
        if len(label_n) >= 2 and label_n in text_n:
            found.extend((label_n, canonical) for canonical in canonical_names)
    return found


def row_index(y: float, height: int) -> int | None:
    target_y = [ratio * height for ratio in SIDE_ROW_RATIOS]
    nearest = min(range(6), key=lambda index: abs(target_y[index] - y))
    return nearest if abs(target_y[nearest] - y) <= max(24, 0.055 * height) else None


def side_of_line(x: float, width: int) -> str | None:
    if x <= 0.11 * width:
        return "left"
    if x >= 0.89 * width:
        return "right"
    return None


def is_label_like(line: dict[str, Any]) -> bool:
    text = re.sub(r"\s+", "", line["text"])
    if not text or re.fullmatch(r"[0-9０-９]+", text):
        return False
    return len(text) >= 2


def choose_label_line(lines: list[dict[str, Any]], side: str, row: int, width: int, height: int,
                      candidate_names: list[str], alias_to_canonical: dict[str, set[str]]) -> dict[str, Any] | None:
    target_y = SIDE_ROW_RATIOS[row] * height
    candidates: list[tuple[tuple[float, float, float, float], dict[str, Any]]] = []
    for line in lines:
        center_x, center_y = line_center(line)
        if side_of_line(center_x, width) != side or row_index(center_y, height) != row or not is_label_like(line):
            continue
        hits = names_in_text(line["text"], candidate_names, alias_to_canonical)
        preferred = 1.0 if hits else 0.0
        # Prefer a direct label detection near the seat's row; use confidence to
        # break ties across full-frame and upscaled-strip passes.
        exactish = max((1.0 if kind != "approved_local_alias" else 0.8 for _, _, kind in hits), default=0.0)
        rank = (preferred, exactish, float(line["confidence"]), -abs(center_y - target_y))
        candidates.append((rank, line))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def make_seat(seat_number: int, visible: dict[str, Any] | None, frame_path: Path, frame_time_ms: int | None,
              roster: list[str], candidate_names: list[str], alias_to_canonical: dict[str, set[str]], all_label_targets: dict[str, set[str]],
              width: int, height: int, layout: str) -> dict[str, Any]:
    side = "left" if seat_number <= 6 else "right"
    row = seat_number - 1 if seat_number <= 6 else seat_number - 7
    if visible is None:
        return {
            "seat": seat_number, "visible_label": None, "name": None, "confidence": None,
            "bbox": None, "frame_path": output_rel(frame_path), "frame_time_ms": frame_time_ms,
            "seat_assignment": {"layout": layout, "method": "sidebar_row_position", "side": side, "row_top_to_bottom": row + 1},
            "match": None,
        }
    text = visible["text"]
    hits = names_in_text(text, candidate_names, alias_to_canonical)
    candidates = sorted({hit[0] for hit in hits})
    name = candidates[0] if len(candidates) == 1 else None
    match_info = None
    if len(candidates) == 1:
        chosen = next(hit for hit in hits if hit[0] == name)
        match_info = {"matched_label": chosen[1], "kind": chosen[2]}
        if name not in roster:
            match_info["roster_difference"] = {"dossier_roster_name": None, "local_canonical_name": name}
    elif len(candidates) > 1:
        match_info = {"ambiguous_names": candidates}
    else:
        outside = known_name_targets(text, all_label_targets)
        outside_names = sorted({canonical for _, canonical in outside})
        if outside_names:
            match_info = {"known_local_names_outside_dossier_roster": outside_names}
    return {
        "seat": seat_number,
        "visible_label": text,
        "name": name,
        "confidence": visible["confidence"],
        "bbox": visible["bbox"],
        "frame_path": output_rel(frame_path),
        "frame_time_ms": frame_time_ms,
        "seat_assignment": {"layout": layout, "method": "sidebar_row_position", "side": side, "row_top_to_bottom": row + 1},
        "ocr_pass": visible["ocr_pass"],
        "match": match_info,
    }


def analyze_frame(frame_path: Path, frame_time_ms: int | None, bvid: str, dossier: dict[str, Any],
                  engine: Any, alias_to_canonical: dict[str, set[str]], all_label_targets: dict[str, set[str]],
                  alias_csv: Path) -> dict[str, Any]:
    import cv2

    image = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot read frame image: {frame_path}")
    height, width = image.shape[:2]
    # Keep the visible nameplate lane tight. A few pixels of the adjacent role
    # panel can suppress short labels such as 二妖 on the 852x480 stream frame.
    panel_w = max(1, round(width * 0.1033))
    scale = max(1, min(4, round(3400 / width)))
    left_crop = cv2.resize(image[:, :panel_w], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    left_lines, left_elapsed = run_pass(engine, left_crop, f"left_strip_x{scale}", scale=scale)
    right_x0 = width - panel_w
    right_crop = cv2.resize(image[:, right_x0:], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    right_lines, right_elapsed = run_pass(engine, right_crop, f"right_strip_x{scale}", x0=right_x0, scale=scale)
    # The nameplates live in the two side lanes. Avoid a full-frame pass here:
    # it is much slower on some ONNX runs and adds unrelated chat/role text.
    all_lines = left_lines + right_lines
    elapsed = 0.0
    roster = [str(name).strip() for name in dossier.get("roster", []) if str(name).strip()]
    local_canonical_names = sorted({name for values in alias_to_canonical.values() for name in values})
    candidate_names = list(dict.fromkeys(roster + local_canonical_names))

    # Detect the standard left/right six-seat layout from readable plate text
    # in the six expected rows. The seat number is the visible fixed row/side
    # position in the stream layout; no name is inferred from roster order.
    visible_rows: dict[tuple[str, int], dict[str, Any]] = {}
    for side in ("left", "right"):
        for row in range(6):
            best = choose_label_line(all_lines, side, row, width, height, candidate_names, alias_to_canonical)
            if best is not None:
                visible_rows[(side, row)] = best
    exact_rows = sum(
        bool(names_in_text(line["text"], candidate_names, alias_to_canonical))
        for line in visible_rows.values()
    )
    layout = "two_column_six_rows" if exact_rows >= 4 else "unresolved"

    # Retry only the special seat-7 Latin label and up to two other visible
    # unknown labels. Blank rows are not retried: a frame without side labels
    # should be queued for recapture rather than triggering twelve crop OCRs.
    if layout != "unresolved":
        retry_scale = max(2, min(8, round(2880 / height)))
        retry_numbers: list[int] = []
        seat7_line = visible_rows.get(("right", 0))
        seat7_hits = names_in_text(seat7_line["text"], candidate_names, alias_to_canonical) if seat7_line else []
        if not seat7_hits or float(seat7_line["confidence"]) < READY_CONFIDENCE:
            retry_numbers.append(7)
        unknown_rows = []
        for number in range(1, 13):
            if number == 7:
                continue
            side = "left" if number <= 6 else "right"
            row = number - 1 if number <= 6 else number - 7
            best = visible_rows.get((side, row))
            if best is not None and not names_in_text(best["text"], candidate_names, alias_to_canonical):
                unknown_rows.append((float(best["confidence"]), number))
        retry_numbers.extend(number for _, number in sorted(unknown_rows, reverse=True)[:2])
        for number in retry_numbers:
            side = "left" if number <= 6 else "right"
            row = number - 1 if number <= 6 else number - 7
            best = visible_rows.get((side, row))
            hits = names_in_text(best["text"], candidate_names, alias_to_canonical) if best else []
            if number != 7 and (best is None or hits):
                continue
            center_y = SIDE_ROW_RATIOS[row] * height
            y0 = max(0, round(center_y - 19 * height / 480))
            y1 = min(height, round(center_y + 14 * height / 480))
            if side == "left":
                x0, x1 = 0, max(1, round(width * 0.1033))
            else:
                x0, x1 = round(width * 0.915), min(width, round(width * 0.986))
            crop = image[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, None, fx=retry_scale, fy=retry_scale, interpolation=cv2.INTER_CUBIC)
            retry_lines, retry_elapsed = run_pass(
                engine, gray, f"seat{number}_nameplate_gray_x{retry_scale}", x0=x0, y0=y0, scale=retry_scale)
            all_lines.extend(retry_lines)
            elapsed += retry_elapsed
            best = choose_label_line(all_lines, side, row, width, height, candidate_names, alias_to_canonical)
            if best is not None:
                visible_rows[(side, row)] = best

    seats: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for number in range(1, 13):
        side = "left" if number <= 6 else "right"
        row = number - 1 if number <= 6 else number - 7
        visible = visible_rows.get((side, row)) if layout != "unresolved" else None
        seat = make_seat(number, visible, frame_path, frame_time_ms, roster, candidate_names, alias_to_canonical,
                         all_label_targets, width, height, layout)
        seats.append(seat)
        if visible is None:
            issues.append({"seat": number, "kind": "label_unreadable", "detail": "未能从该座位姓名牌区域读出完整标签；保留空值待人工核对。"})
        elif seat["name"] is None:
            known = (seat.get("match") or {}).get("known_local_names_outside_dossier_roster")
            if known:
                issues.append({"seat": number, "kind": "label_not_in_dossier_roster", "detail": f"画面牌名 {visible['text']} 在本地映射中指向 {', '.join(known)}，但不在本局 roster；没有跨名硬配。"})
            elif (seat.get("match") or {}).get("ambiguous_names"):
                issues.append({"seat": number, "kind": "ambiguous_candidate", "detail": f"OCR 标签可能对应多个本局 roster 候选：{', '.join(seat['match']['ambiguous_names'])}。"})
            else:
                issues.append({"seat": number, "kind": "no_roster_match", "detail": f"OCR 牌名 {visible['text']} 未精确匹配本局 roster 或已核实别名；保留原始标签。"})
        if seat.get("name") and float(seat["confidence"] or 0) < READY_CONFIDENCE:
            issues.append({"seat": number, "kind": "low_ocr_confidence", "detail": f"候选 {seat['name']} 的 OCR 置信度 {seat['confidence']:.3f} 低于 {READY_CONFIDENCE:.2f}。"})
        if seat.get("name") and seat["name"] not in roster:
            issues.append({"seat": number, "kind": "roster_difference", "detail": f"画面牌名在本地人名表中唯一匹配规范姓名 {seat['name']}，但该姓名不在本局 dossier.roster；保留画面姓名，不改配到名单中的其他人。"})

    assigned = [seat["name"] for seat in seats if seat.get("name")]
    duplicates = sorted({name for name in assigned if assigned.count(name) > 1})
    for name in duplicates:
        issues.append({"kind": "duplicate_name_candidate", "detail": f"本局多个座位匹配到同一姓名 {name}；需人工消歧。"})
    if len(roster) != 12:
        issues.append({"kind": "roster_size_mismatch", "detail": f"本局 dossier.roster 有 {len(roster)} 人，预期 12 人。"})
    if layout == "unresolved":
        issues.append({"kind": "needs_new_frame", "detail": "未检测到至少4个本地姓名候选牌；不做逐座小框重试，建议在游戏进行中重截可见左右姓名栏的画面。"})
    ready = (layout != "unresolved" and len(roster) == 12 and len(assigned) == 12 and
             len(set(assigned)) == 12 and all(float(seat["confidence"] or 0) >= READY_CONFIDENCE for seat in seats))
    try:
        import importlib.metadata as metadata
        engine_version = metadata.version("rapidocr")
    except Exception:
        engine_version = "unknown"
    return {
        "bvid": bvid,
        "scope": "seat_name_only",
        "status": "ready" if ready else ("needs_new_frame" if layout == "unresolved" else "pending"),
        "date": dossier.get("date") or dossier.get("_capture_date"),
        "source": {"kind": "video_frame", "frame_path": output_rel(frame_path), "frame_time_ms": frame_time_ms,
                   "frame_sha256": hashlib.sha256(frame_path.read_bytes()).hexdigest()},
        "dossier": {"path": output_rel(Path(dossier.get("_path", ""))) if dossier.get("_path") else None,
                    "roster": roster, "roster_count": len(roster)},
        "engine": {"name": "rapidocr", "version": engine_version, "backend": "onnxruntime", "upscale": f"side strips x{scale}"},
        "frame": {"width": width, "height": height, "layout": layout},
        "seats": seats,
        "issues": issues,
        "raw_ocr_lines": all_lines,
        "ocr_elapsed_seconds": round(elapsed + left_elapsed + right_elapsed, 3),
        "alias_evidence": {"path": output_rel(alias_csv), "rule": "仅采用S22人名表中状态为确认无误/已修正的原名到规范名映射；不按roster顺序推测，画面精确匹配的本地规范名可保留并标注roster_difference。"},
    }


def process_folder(frame_dir: Path, engine: Any, alias_to_canonical: dict[str, set[str]],
                   all_label_targets: dict[str, set[str]], alias_csv: Path, dossier_override: Path | None = None,
                   frame_override: Path | None = None, frame_time_override: int | None = None) -> dict[str, Any]:
    capture_path = frame_dir / "capture.json"
    capture = read_json(capture_path) if capture_path.is_file() else {}
    bvid = str(capture.get("bvid") or frame_dir.name)
    dossier_path = dossier_override or dossier_path_for(bvid)
    if dossier_path is None or not dossier_path.is_file():
        raise ValueError(f"no local dossier found for {bvid}; pass --dossier explicitly")
    dossier = read_json(dossier_path)
    dossier["_path"] = str(dossier_path)
    dossier["_capture_date"] = capture.get("date")
    if str(dossier.get("season", "S22")) != "S22":
        raise ValueError(f"dossier is not S22: {dossier_path}")
    if len(dossier.get("roster", [])) != 12:
        # Still emit a review file so the roster mismatch remains visible.
        pass
    frame_path = frame_override or resolve_frame_path(capture.get("frame_path"), frame_dir)
    if frame_path is None:
        images = sorted(frame_dir.glob("frame_*.png")) or sorted(frame_dir.glob("*.png"))
        frame_path = images[0].resolve() if images else None
    if frame_path is None or not frame_path.is_file():
        raise ValueError(f"no captured PNG found for {bvid} in {frame_dir}")
    frame_time_ms = frame_time_override if frame_time_override is not None else capture.get("frame_time_ms")
    if not isinstance(frame_time_ms, int):
        match = re.search(r"_(\d+(?:\.\d+)?)\.png$", frame_path.name)
        frame_time_ms = round(float(match.group(1)) * 1000) if match else None
    return analyze_frame(frame_path, frame_time_ms, bvid, dossier, engine,
                         alias_to_canonical, all_label_targets, alias_csv)


def capture_for_folder(frame_dir: Path) -> dict[str, Any]:
    capture_path = frame_dir / "capture.json"
    capture = read_json(capture_path) if capture_path.is_file() else {}
    bvid = str(capture.get("bvid") or frame_dir.name)
    date = capture.get("date")
    if not date:
        dossier_path = dossier_path_for(bvid)
        if dossier_path and dossier_path.is_file():
            dossier = read_json(dossier_path)
            date = dossier.get("date")
        if not date:
            match = re.match(r"(\d{4}-\d{2}-\d{2})_", (dossier_path.parent.name if dossier_path else ""))
            date = match.group(1) if match else None
    return {**capture, "bvid": bvid, "date": date}


def day_coverage(frame_root: Path, frame_dirs: list[Path]) -> dict[str, Any]:
    by_seat: dict[int, list[tuple[str, str, float | None, bool]]] = {seat: [] for seat in range(1, 13)}
    for frame_dir in frame_dirs:
        bvid = frame_dir.name
        output_path = frame_root / f"{bvid}.json"
        if not output_path.is_file():
            continue
        try:
            result = read_json(output_path)
        except Exception:
            continue
        manual = result.get("manual_verified") is True
        for item in result.get("seats", []):
            try:
                seat_number = int(item.get("seat"))
                confidence = float(item.get("confidence")) if item.get("confidence") is not None else None
            except (TypeError, ValueError):
                continue
            name = str(item.get("name") or "").strip()
            if seat_number not in by_seat or not name or (not manual and (confidence is None or confidence < READY_CONFIDENCE)):
                continue
            by_seat[seat_number].append((name, bvid, confidence, manual))

    chosen: dict[int, str] = {}
    conflicts: dict[int, list[str]] = {}
    for seat_number, evidence in by_seat.items():
        # A human-verified label supersedes OCR candidates for the same seat.
        manual_evidence = [entry for entry in evidence if entry[3]]
        usable = manual_evidence or evidence
        names = sorted({entry[0] for entry in usable})
        if len(names) == 1:
            chosen[seat_number] = names[0]
        elif names:
            conflicts[seat_number] = names
    name_seats: dict[str, list[int]] = {}
    for seat_number, name in chosen.items():
        name_seats.setdefault(name, []).append(seat_number)
    duplicate_seats = sorted(seat for seats in name_seats.values() if len(seats) > 1 for seat in seats)
    missing = sorted(set(range(1, 13)) - set(chosen) | set(conflicts) | set(duplicate_seats))
    complete = not missing and len(chosen) == 12 and len(set(chosen.values())) == 12
    return {
        "covered_seats": sorted(chosen), "missing_seats": missing,
        "conflicts": {str(k): v for k, v in sorted(conflicts.items())},
        "duplicate_seats": duplicate_seats, "complete": complete,
    }


def output_matches_capture(output_path: Path, capture: dict[str, Any]) -> bool:
    if not output_path.is_file():
        return False
    try:
        result = read_json(output_path)
    except Exception:
        return False
    source = result.get("source") or {}
    if result.get("manual_verified") is True:
        return True
    result_time = source.get("frame_time_ms")
    capture_time = capture.get("frame_time_ms")
    if result_time is not None and capture_time is not None and result_time != capture_time:
        return False
    result_hash = source.get("frame_sha256")
    capture_hash = capture.get("frame_sha256")
    if result_hash and capture_hash:
        return result_hash == capture_hash
    # Legacy OCR results did not store a frame hash. Matching timestamps are
    # enough to avoid needlessly rerunning the old, unchanged screenshot.
    return result_time == capture_time


def archive_previous(output_path: Path, frame_root: Path, bvid: str) -> Path | None:
    if not output_path.is_file():
        return None
    history_dir = frame_root / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    prior = read_json(output_path)
    prior_time = (prior.get("source") or {}).get("frame_time_ms")
    stem = f"{bvid}_{prior_time if prior_time is not None else 'legacy'}"
    archived = history_dir / f"{stem}.json"
    suffix = 2
    while archived.exists():
        archived = history_dir / f"{stem}_{suffix}.json"
        suffix += 1
    archived.write_bytes(output_path.read_bytes())
    return archived


def fill_uncovered_days(frame_root: Path, alias_csv: Path, alias_to_canonical: dict[str, set[str]],
                        all_label_targets: dict[str, set[str]], engine: Any, max_per_day: int,
                        selected_dates: set[str] | None = None, dry_run: bool = False,
                        date_plan: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    folders_by_date: dict[str, list[Path]] = {}
    for folder in frame_root.iterdir():
        if not folder.is_dir() or not folder.name.startswith("BV"):
            continue
        capture = capture_for_folder(folder)
        date = str(capture.get("date") or "unknown")
        folders_by_date.setdefault(date, []).append(folder)

    report: dict[str, Any] = {"dates": {}, "processed_games": 0, "elapsed_seconds": 0.0}
    for date, folders in sorted(folders_by_date.items()):
        if date == "unknown" or (selected_dates and date not in selected_dates):
            continue
        before = day_coverage(frame_root, folders)
        if date == "2026-07-03":
            sources = []
            for folder in folders:
                capture = capture_for_folder(folder)
                sources.append({"bvid": capture.get("bvid"), "frame_path": capture.get("frame_path"),
                                "frame_time_ms": capture.get("frame_time_ms")})
            report["dates"][date] = {"before": before, "after": before, "attempted_bvids": [],
                                     "status": "needs_manual_lineup/no_sidebar_labels", "source_frames": sources}
            print(f"DATE {date} status=needs_manual_lineup/no_sidebar_labels frames={len(sources)}")
            continue
        if before["complete"]:
            report["dates"][date] = {"before": before, "after": before, "attempted_bvids": [], "status": "already_covered"}
            continue
        if date_plan is not None and date not in date_plan:
            no_sidebar = date == "2026-07-03"
            sources = []
            for folder in folders:
                capture = capture_for_folder(folder)
                sources.append({"bvid": capture.get("bvid"), "frame_path": capture.get("frame_path"),
                                "frame_time_ms": capture.get("frame_time_ms")})
            status = "needs_manual_lineup/no_sidebar_labels" if no_sidebar else "no_selected_frame_in_plan"
            report["dates"][date] = {"before": before, "after": before, "attempted_bvids": [],
                                     "status": status, "source_frames": sources}
            print(f"DATE {date} status={status} frames={len(sources)}")
            continue
        planned = date_plan.get(date) if date_plan else None
        candidates: list[tuple[int, str, Path, dict[str, Any], Path | None]] = []
        selection_folders = folders
        if planned:
            planned_bvid = str(planned.get("bvid") or "")
            selection_folders = [folder for folder in folders if folder.name == planned_bvid]
        for folder in selection_folders:
            capture = capture_for_folder(folder)
            if planned:
                capture = {**capture, **{k: planned[k] for k in ("bvid", "date", "frame_time_ms", "frame_path", "frame_sha256", "game_number", "captured_at") if k in planned}}
            output_path = frame_root / f"{capture['bvid']}.json"
            if output_path.exists():
                try:
                    previous = read_json(output_path)
                except Exception:
                    previous = {}
                if previous.get("manual_verified") is True:
                    continue
            # The daily plan intentionally selects the best nameplate frame.
            # If an older OCR pass exists for that same BVID, rerun this single
            # selected frame with the narrowed OCR and archive the old JSON.
            if output_matches_capture(output_path, capture) and not planned:
                continue
            # Prefer recently captured frames (for example a deliberately
            # recaptured live nameplate view), then stable game order.
            frame_path = resolve_frame_path(str(capture.get("frame_path") or ""), folder) if capture.get("frame_path") else None
            candidates.append((int(capture.get("game_number") or 99), str(capture.get("captured_at") or ""), folder, capture, frame_path))
        candidates.sort(key=lambda item: (item[1], -item[0]), reverse=True)
        attempted: list[str] = []
        for _, _, folder, capture, frame_override in candidates:
            if len(attempted) >= max_per_day or day_coverage(frame_root, folders)["complete"]:
                break
            bvid = capture["bvid"]
            attempted.append(bvid)
            try:
                result = process_folder(folder, engine, alias_to_canonical, all_label_targets, alias_csv,
                                        frame_override=frame_override, frame_time_override=capture.get("frame_time_ms"))
                if not dry_run:
                    out_path = frame_root / f"{bvid}.json"
                    previous_path = archive_previous(out_path, frame_root, bvid) if out_path.exists() else None
                    if previous_path:
                        result["supersedes"] = output_rel(previous_path)
                    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                report["processed_games"] += 1
                report["elapsed_seconds"] += float(result.get("ocr_elapsed_seconds") or 0)
                print(f"{date} {bvid} {result['status']} names={sum(bool(s.get('name')) for s in result['seats'])}/12 layout={result['frame']['layout']} ocr={result['ocr_elapsed_seconds']:.2f}s")
            except Exception as exc:
                print(f"error {bvid}: {exc}", file=sys.stderr)
        after = day_coverage(frame_root, folders)
        report["dates"][date] = {
            "before": before, "after": after, "attempted_bvids": attempted,
            "status": "covered" if after["complete"] else ("no_unprocessed_frame" if not attempted else "still_incomplete"),
        }
        print(f"DATE {date} covered={len(after['covered_seats'])}/12 missing={after['missing_seats']} conflicts={after['conflicts']}")
    report["elapsed_seconds"] = round(report["elapsed_seconds"], 2)
    print("COVERAGE_REPORT " + json.dumps(report, ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR S22 game seat-name labels from local video frames.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="process all direct BVID folders under frame_seats")
    target.add_argument("--bvid", action="append", help="process a BVID frame folder; may be repeated")
    target.add_argument("--fill-uncovered-days", action="store_true", help="OCR only the selected frame for each uncovered date, using the daily plan")
    parser.add_argument("--dossier", type=Path, help="override the auto-discovered local dossier (single BVID only)")
    parser.add_argument("--frame-path", type=Path, help="override the capture.json frame path (single BVID only)")
    parser.add_argument("--frame-root", type=Path, default=FRAME_ROOT)
    parser.add_argument("--alias-csv", type=Path, default=ALIAS_CSV)
    parser.add_argument("--date-plan", type=Path, default=ROOT / "data/reports/S22/S22_按日座位截图计划.json", help="daily BVID/frame selection JSON")
    parser.add_argument("--date", action="append", help="limit --fill-uncovered-days to this date; may be repeated")
    parser.add_argument("--max-per-date", type=int, default=3, help="maximum candidate frames to OCR per date (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="print per-game review summary without writing JSON")
    parser.add_argument("--overwrite", action="store_true", help="replace existing per-BVID OCR review JSON")
    args = parser.parse_args()
    if (args.dossier or args.frame_path) and (args.all or args.fill_uncovered_days or len(args.bvid or []) != 1):
        parser.error("--dossier and --frame-path apply only with a single --bvid")
    if args.date and not args.fill_uncovered_days:
        parser.error("--date applies only with --fill-uncovered-days")
    if args.max_per_date < 1:
        parser.error("--max-per-date must be at least 1")
    frame_root = args.frame_root if args.frame_root.is_absolute() else (ROOT / args.frame_root)
    alias_csv = args.alias_csv if args.alias_csv.is_absolute() else (ROOT / args.alias_csv)
    alias_to_canonical, all_label_targets, _ = load_alias_map(alias_csv)
    if not alias_to_canonical:
        print(f"warning: no approved S22 alias rows loaded from {alias_csv}", file=sys.stderr)
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        print("RapidOCR is missing. Install with: .venv/Scripts/python -m pip install rapidocr onnxruntime", file=sys.stderr)
        raise SystemExit(2) from exc
    engine = RapidOCR()
    if args.fill_uncovered_days:
        plan_path = args.date_plan if args.date_plan.is_absolute() else (ROOT / args.date_plan)
        date_plan = read_json(plan_path).get("days", {}) if plan_path.is_file() else {}
        if not date_plan:
            parser.error(f"daily plan has no days: {plan_path}")
        fill_uncovered_days(frame_root, alias_csv, alias_to_canonical, all_label_targets, engine,
                           args.max_per_date, set(args.date) if args.date else None, args.dry_run, date_plan)
        return 0
    folders = sorted((path for path in frame_root.iterdir() if path.is_dir() and path.name.startswith("BV")), key=lambda p: p.name) if args.all else [frame_root / bvid for bvid in args.bvid]
    totals = {"games": 0, "ready": 0, "pending": 0, "needs_new_frame": 0, "seat_candidates": 0, "mean_seat_confidence": None, "elapsed_seconds": 0.0}
    all_scores: list[float] = []
    for folder in folders:
        try:
            result = process_folder(folder, engine, alias_to_canonical, all_label_targets, alias_csv,
                                   dossier_override=args.dossier, frame_override=args.frame_path)
            out_path = frame_root / f"{result['bvid']}.json"
            if out_path.exists() and not args.dry_run:
                previous = read_json(out_path)
                if previous.get("manual_verified") is True:
                    print(f"skip {result['bvid']}: manual_verified output is protected")
                    continue
                if not args.overwrite:
                    print(f"skip {result['bvid']}: output exists (use --overwrite)")
                    continue
                previous_path = archive_previous(out_path, frame_root, result["bvid"])
                if previous_path:
                    result["supersedes"] = output_rel(previous_path)
            if not args.dry_run:
                out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            candidate_count = sum(seat.get("name") is not None for seat in result["seats"])
            confidences = [float(seat["confidence"]) for seat in result["seats"] if seat.get("name") and seat.get("confidence") is not None]
            all_scores.extend(confidences)
            totals["games"] += 1
            totals[result["status"]] += 1
            totals["seat_candidates"] += candidate_count
            totals["elapsed_seconds"] += result["ocr_elapsed_seconds"]
            print(f"{result['bvid']} {result['status']} names={candidate_count}/12 layout={result['frame']['layout']} ocr={result['ocr_elapsed_seconds']:.2f}s issues={len(result['issues'])}")
        except Exception as exc:
            print(f"error {folder.name}: {exc}", file=sys.stderr)
    totals["mean_seat_confidence"] = round(sum(all_scores) / len(all_scores), 4) if all_scores else None
    totals["elapsed_seconds"] = round(totals["elapsed_seconds"], 2)
    print("TOTAL " + json.dumps(totals, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
