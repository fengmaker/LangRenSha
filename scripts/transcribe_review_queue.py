"""Batch full-audio FunASR for the selected season's review queue.

The queue is selected from all rows marked ``no_zh_subtitle`` or ``needs_review``
in the preferred review CSV, kept in CSV order.
This wrapper validates FunASR's full transcript and raw chunk checkpoints before
it records completion or copies the derived files beside the source audio.
"""

from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Iterator

from season_config import load_season, season_codes

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEASON = season_codes(ROOT)[0]
SEASON = DEFAULT_SEASON
SEASON_CONFIG = load_season(SEASON, ROOT)
DEFAULT_CSV = ROOT / f"data/seasons/{SEASON}/{SEASON}_中文优先复核目录.csv"
PLAN_PATH = ROOT / f"data/reports/{SEASON}_全文补转写计划.json"
STATE_PATH = ROOT / f"data/reports/{SEASON}_全文补转写进度.json"
SUMMARY_CSV = ROOT / f"data/seasons/{SEASON}/{SEASON}_全文补转写目录.csv"
LOG_DIR = ROOT / f"data/reports/{SEASON}_全文补转写日志"
TRANSCRIBER = ROOT / "scripts/transcribe_funasr.py"
QUALITY_FIELD = "质量筛查"
SELECTED_QUALITIES = ("no_zh_subtitle", "needs_review")
INDEX_FIELDS = ("本地转写状态", "本地全文JSON", "本地全文SRT", "本地全文阅读版", "本地转写范围")
OUTPUT_NAMES = {
    "json": "transcript.json",
    "srt": "transcript.srt",
    "reading": "transcript.阅读.txt",
}
DERIVED_SUFFIXES = {
    "json": ".本地全文转写_funasr.json",
    "srt": ".本地全文转写_funasr.srt",
    "reading": ".本地全文转写_funasr.阅读.txt",
}


class QueueError(RuntimeError):
    """Raised when the review index or task artifacts cannot be trusted."""


def configure_season(season: str) -> None:
    global SEASON, SEASON_CONFIG, DEFAULT_CSV, PLAN_PATH, STATE_PATH, SUMMARY_CSV, LOG_DIR
    SEASON_CONFIG = load_season(season, ROOT)
    SEASON = season
    DEFAULT_CSV = ROOT / f"data/seasons/{season}/{season}_中文优先复核目录.csv"
    PLAN_PATH = plan_path_for(ROOT)
    STATE_PATH = state_path_for(ROOT)
    SUMMARY_CSV = summary_path_for(ROOT)
    LOG_DIR = ROOT / f"data/reports/{season}_全文补转写日志"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise QueueError(f"CSV has no header: {path}")
        return list(reader.fieldnames), list(reader)


def selected_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Select only the two review statuses, without relying on column position."""
    chosen = [row for row in rows if row.get(QUALITY_FIELD) in SELECTED_QUALITIES]
    bvids = [row.get("BVID", "").strip() for row in chosen]
    if len(set(bvids)) != len(bvids) or "" in bvids:
        raise QueueError("Review queue has missing or duplicate BVIDs")
    return chosen


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def manifest_path_for(row: dict[str, str], root: Path) -> Path:
    bvid = row.get("BVID", "").strip()
    if not bvid:
        raise QueueError("Selected CSV row has no BVID")
    return root / "data/raw/bilibili" / bvid / "p01/manifest.json"


def output_path_for(row: dict[str, str], root: Path) -> Path:
    bvid = row.get("BVID", "").strip()
    return root / f"data/transcripts/{SEASON}" / f"{bvid}_p01_funasr_full"


def reason_for(row: dict[str, str]) -> str:
    reason = row.get("字幕待核事项", "").strip()
    if reason:
        return reason
    if row.get(QUALITY_FIELD) == "no_zh_subtitle":
        return "没有可用的中文字幕轨道"
    return "中文字幕质量筛查标记为 needs_review"


def make_plan(csv_path: Path, root: Path, *, created_at: str | None = None) -> dict[str, Any]:
    _, rows = read_csv(csv_path)
    chosen = selected_rows(rows)
    entries: list[dict[str, Any]] = []
    for row in chosen:
        audio_rel = row.get("音频文件", "").strip()
        if not audio_rel:
            raise QueueError(f"{row.get('BVID')}: missing 音频文件")
        audio_path = root / Path(audio_rel)
        manifest = manifest_path_for(row, root)
        manifest_sha = None
        manifest_error = None
        try:
            manifest_data = load_json(manifest)
            manifest_audio = manifest_data["audio"]
            if manifest_data.get("bvid") != row.get("BVID"):
                raise QueueError("manifest BVID does not match the CSV row")
            if str(manifest_data.get("cid")) != str(row.get("CID", "")):
                raise QueueError("manifest CID does not match the CSV row")
            if int(manifest_data.get("page", 0)) != 1:
                raise QueueError("manifest page is not 1")
            manifest_sha = manifest_audio["sha256"]
            manifest_duration_seconds = float(manifest_data["duration_seconds"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, QueueError) as error:
            manifest_error = str(error)
            manifest_duration_seconds = None
        prefix = audio_path.stem
        if prefix.endswith(".音频"):
            prefix = prefix[:-len(".音频")]
        exports = {
            kind: relative(audio_path.parent / f"{prefix}{suffix}", root)
            for kind, suffix in DERIVED_SUFFIXES.items()
        }
        entries.append({
            "row_number": int(row.get("目录序号", len(entries) + 1)),
            "bvid": row["BVID"],
            "cid": str(row.get("CID", "")),
            "quality": row.get(QUALITY_FIELD, ""),
            "reason": reason_for(row),
            "audio_file": relative(audio_path, root),
            "manifest_file": relative(manifest, root),
            "manifest_audio_sha256": manifest_sha,
            "manifest_duration_seconds": manifest_duration_seconds,
            "manifest_error": manifest_error,
            "output_dir": relative(output_path_for(row, root), root),
            "exports": exports,
        })
    durations = [entry["manifest_duration_seconds"] for entry in entries
                 if entry["manifest_duration_seconds"] is not None]
    total_seconds = sum(durations)
    return {
        "schema_version": 1,
        "created_at_utc": created_at or utc_now(),
        "source_csv": relative(csv_path, root),
        "selection": {"field": QUALITY_FIELD, "values": list(SELECTED_QUALITIES),
                      "counts": {quality: sum(row.get(QUALITY_FIELD) == quality for row in chosen)
                                 for quality in SELECTED_QUALITIES}, "row_order": "source_csv"},
        "season": SEASON,
        "entry_count": len(entries),
        "total_audio_duration_seconds": total_seconds,
        "total_audio_duration_hours": round(total_seconds / 3600, 3),
        "entries": entries,
    }


def plan_row_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["bvid"]: entry for entry in plan["entries"]}


@contextmanager
def process_lock(root: Path) -> Iterator[None]:
    """Hold a nonblocking cross-platform process lock for the entire batch run."""
    lock_path = root / f"data/reports/.{SEASON}_全文补转写.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if handle.read(1) == b"":
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise QueueError("Another review-queue batch is already running") from error
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise QueueError("Another review-queue batch is already running") from error
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def state_for(plan: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing if isinstance(existing, dict) else {}
    previous = existing.get("items", {})
    items: dict[str, Any] = {}
    for entry in plan["entries"]:
        old = previous.get(entry["bvid"], {})
        items[entry["bvid"]] = {
            **old,
            "row_number": entry["row_number"],
            "quality": entry["quality"],
            "reason": entry["reason"],
            "audio_file": entry["audio_file"],
            "manifest_file": entry["manifest_file"],
            "manifest_audio_sha256": entry["manifest_audio_sha256"],
            "manifest_duration_seconds": entry.get("manifest_duration_seconds"),
            "output_dir": entry["output_dir"],
            "exports": entry["exports"],
            "status": old.get("status", "pending"),
        }
    return {"schema_version": 1, "updated_at_utc": utc_now(),
            "plan_file": relative(PLAN_PATH, ROOT), "items": items}


def expected_data(entry: dict[str, Any], root: Path) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    audio = root / Path(entry["audio_file"])
    manifest_path = root / Path(entry["manifest_file"])
    manifest = load_json(manifest_path)
    if entry.get("manifest_error"):
        raise QueueError(f"invalid source manifest: {entry['manifest_error']}")
    actual_sha = sha256_file(audio)
    manifest_sha = manifest["audio"]["sha256"]
    if actual_sha != manifest_sha:
        raise QueueError(f"audio SHA-256 mismatch against manifest: {actual_sha} != {manifest_sha}")
    if entry.get("manifest_audio_sha256") != manifest_sha:
        raise QueueError("manifest audio SHA-256 changed since the saved plan")
    if manifest.get("bvid") != entry["bvid"] or str(manifest.get("cid")) != str(entry["cid"]):
        raise QueueError("manifest source identity does not match the plan")
    manifest_duration = float(manifest["duration_seconds"])
    return_duration = manifest_duration
    return manifest, audio, {"audio_sha256": actual_sha, "manifest_duration_seconds": return_duration}


def _int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise QueueError(f"{label} is not an integer")
    try:
        converted = int(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise QueueError(f"{label} is not an integer") from error
    if converted != value:
        raise QueueError(f"{label} is not an integer")
    return converted


def validate_output(entry: dict[str, Any], root: Path) -> dict[str, Any]:
    """Return validated transcript details; raise on any incomplete or stale artifact."""
    manifest, audio, source_hash = expected_data(entry, root)
    output = root / Path(entry["output_dir"])
    transcript_path = output / OUTPUT_NAMES["json"]
    srt_path = output / OUTPUT_NAMES["srt"]
    reading_path = output / OUTPUT_NAMES["reading"]
    for path in (transcript_path, srt_path, reading_path):
        if not path.is_file() or path.stat().st_size == 0:
            raise QueueError(f"missing or empty output file: {relative(path, root)}")

    transcript = load_json(transcript_path)
    if transcript.get("full_audio_processed") is not True:
        raise QueueError("transcript does not declare full_audio_processed=true")
    duration = _int(transcript.get("audio_duration_ms"), "audio_duration_ms")
    if duration <= 0:
        raise QueueError("audio_duration_ms must be positive")
    if abs(duration / 1000 - float(manifest["duration_seconds"])) > 2:
        raise QueueError("transcript duration differs from manifest duration by more than 2 seconds")
    source = transcript.get("source") or {}
    if source.get("audio_sha256") != source_hash["audio_sha256"]:
        raise QueueError("transcript audio SHA-256 does not match the manifest and source audio")
    if source.get("bvid") != entry["bvid"] or str(source.get("cid")) != str(entry["cid"]):
        raise QueueError("transcript source identity does not match the plan")
    if source.get("manifest") and Path(source["manifest"]).resolve() != (root / entry["manifest_file"]).resolve():
        raise QueueError("transcript manifest path does not match the plan")

    plan_path = output / "vad_plan.json"
    if not plan_path.is_file():
        raise QueueError("missing vad_plan.json")
    vad_plan = load_json(plan_path)
    if vad_plan.get("audio_sha256") != source_hash["audio_sha256"]:
        raise QueueError("VAD plan audio SHA-256 does not match the manifest")
    if _int(vad_plan.get("audio_duration_ms"), "VAD audio_duration_ms") != duration:
        raise QueueError("VAD plan duration differs from transcript duration")
    ranges = vad_plan.get("chunks")
    chunks = transcript.get("chunks")
    if not isinstance(ranges, list) or not ranges or not isinstance(chunks, list) or len(chunks) != len(ranges):
        raise QueueError("transcript chunk list does not match the VAD plan")
    normalized_ranges: list[tuple[int, int]] = []
    for index, raw_range in enumerate(ranges, 1):
        if not isinstance(raw_range, list) or len(raw_range) != 2:
            raise QueueError(f"invalid VAD planned range at chunk {index}")
        start, end = (_int(raw_range[0], "planned chunk start"), _int(raw_range[1], "planned chunk end"))
        if start < 0 or end <= start or end > duration:
            raise QueueError(f"invalid VAD planned range at chunk {index}: {start}..{end}")
        normalized_ranges.append((start, end))
    if normalized_ranges[0][0] != 0 or normalized_ranges[-1][1] != duration:
        raise QueueError("VAD chunk plan does not start at zero and end at audio duration")
    for previous, current in zip(normalized_ranges, normalized_ranges[1:]):
        if previous[1] != current[0]:
            raise QueueError("VAD chunk plan has a gap or overlap")

    raw_dir = output / "raw"
    for index, ((start, end), chunk) in enumerate(zip(normalized_ranges, chunks), 1):
        if (_int(chunk.get("index"), "chunk index"), _int(chunk.get("start_ms"), "chunk start"),
                _int(chunk.get("end_ms"), "chunk end")) != (index, start, end):
            raise QueueError(f"transcript checkpoint range differs from VAD plan at chunk {index}")
        checkpoint_path = raw_dir / f"chunk_{index:04}.json"
        if not checkpoint_path.is_file():
            raise QueueError(f"missing raw checkpoint: {checkpoint_path.name}")
        checkpoint = load_json(checkpoint_path)
        if (_int(checkpoint.get("index"), "raw checkpoint index"),
                _int(checkpoint.get("start_ms"), "raw checkpoint start"),
                _int(checkpoint.get("end_ms"), "raw checkpoint end")) != (index, start, end):
            raise QueueError(f"raw checkpoint range differs from VAD plan at chunk {index}")

    segments = transcript.get("segments")
    if not isinstance(segments, list) or not segments:
        raise QueueError("full transcript has no segments")
    for position, segment in enumerate(segments, 1):
        start = _int(segment.get("start_ms"), f"segment {position} start_ms")
        end = _int(segment.get("end_ms"), f"segment {position} end_ms")
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            raise QueueError(f"segment {position} has no text")
        if not (0 <= start < end <= duration):
            raise QueueError(f"segment {position} has invalid time range {start}..{end}")
        if segment.get("chunk_index") not in range(1, len(normalized_ranges) + 1):
            raise QueueError(f"segment {position} references an unknown chunk")
    srt_text = srt_path.read_text(encoding="utf-8")
    if srt_text.count(" --> ") != len(segments):
        raise QueueError("SRT cue count differs from transcript segment count")
    reading_text = reading_path.read_text(encoding="utf-8")
    if not reading_text.strip():
        raise QueueError("reading transcript is empty")
    return {"duration_ms": duration, "sentence_count": len(segments),
            "audio_sha256": source_hash["audio_sha256"], "manifest": manifest,
            "audio_file": audio, "output_dir": output, "transcript": transcript}


def derived_paths(entry: dict[str, Any], root: Path) -> dict[str, Path]:
    return {kind: root / Path(value) for kind, value in entry["exports"].items()}


def copy_exports(entry: dict[str, Any], root: Path, validated: dict[str, Any]) -> None:
    source_by_kind = {
        "json": validated["output_dir"] / OUTPUT_NAMES["json"],
        "srt": validated["output_dir"] / OUTPUT_NAMES["srt"],
        "reading": validated["output_dir"] / OUTPUT_NAMES["reading"],
    }
    for kind, source in source_by_kind.items():
        destination = derived_paths(entry, root)[kind]
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp",
                                              dir=destination.parent)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


def update_indexes(csv_path: Path, root: Path, plan: dict[str, Any], state: dict[str, Any],
                   validation: dict[str, dict[str, Any]] | None = None) -> None:
    """Append/update the five local-ASR columns in both established indexes."""
    validation = validation or {}
    headers, rows = read_csv(csv_path)
    entries_by_bvid = plan_row_map(plan)
    json_path = csv_path.with_suffix(".json")
    index = None
    index_rows = None
    if json_path.is_file():
        index = load_json(json_path)
        index_rows = index.get("entries") if isinstance(index, dict) else None
        if not isinstance(index_rows, list):
            raise QueueError(f"JSON review index has no entries list: {json_path}")
        json_bvids = [row.get("BVID") for row in index_rows if isinstance(row, dict)]
        missing = [bvid for bvid in entries_by_bvid if json_bvids.count(bvid) != 1]
        if missing:
            raise QueueError(f"JSON review index is missing or duplicates selected BVIDs: {missing}")
    for field in INDEX_FIELDS:
        if field not in headers:
            headers.append(field)
    for row in rows:
        bvid = row.get("BVID", "")
        if bvid not in entries_by_bvid:
            continue
        entry = entries_by_bvid[bvid]
        item = state["items"][bvid]
        details = validation.get(bvid)
        row["本地转写状态"] = item.get("status", "pending")
        row["本地全文JSON"] = entry["exports"]["json"]
        row["本地全文SRT"] = entry["exports"]["srt"]
        row["本地全文阅读版"] = entry["exports"]["reading"]
        row["本地转写范围"] = (f"0-{details['duration_ms']}ms; full_audio_processed"
                               if details else "整段音频")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{csv_path.name}.", suffix=".tmp", dir=csv_path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, csv_path)
    finally:
        temporary.unlink(missing_ok=True)

    if index is not None and index_rows is not None:
        for row in index_rows:
            bvid = row.get("BVID") if isinstance(row, dict) else None
            if bvid not in entries_by_bvid:
                continue
            entry = entries_by_bvid[bvid]
            item = state["items"][bvid]
            details = validation.get(bvid)
            row.update({
                "本地转写状态": item.get("status", "pending"),
                "本地全文JSON": entry["exports"]["json"],
                "本地全文SRT": entry["exports"]["srt"],
                "本地全文阅读版": entry["exports"]["reading"],
                "本地转写范围": (f"0-{details['duration_ms']}ms; full_audio_processed"
                               if details else "整段音频"),
            })
        save_json(json_path, index)


def summary_rows(plan: dict[str, Any], state: dict[str, Any],
                 validation: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "目录序号": entry["row_number"], "BVID": entry["bvid"], "CID": entry["cid"],
        "质量筛查": entry["quality"], "原因": entry["reason"],
        "状态": state["items"][entry["bvid"]].get("status", "pending"),
        "音频文件": entry["audio_file"], "本地全文JSON": entry["exports"]["json"],
        "本地全文SRT": entry["exports"]["srt"], "本地全文阅读版": entry["exports"]["reading"],
        "完整时长毫秒": validation.get(entry["bvid"], {}).get("duration_ms", ""),
        "句数": validation.get(entry["bvid"], {}).get("sentence_count", ""),
    } for entry in plan["entries"]]


def write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["目录序号", "BVID", "CID", "质量筛查", "原因", "状态", "音频文件",
              "本地全文JSON", "本地全文SRT", "本地全文阅读版", "完整时长毫秒", "句数"]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def inspect_queue(plan: dict[str, Any], state: dict[str, Any], root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    valid: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for entry in plan["entries"]:
        bvid = entry["bvid"]
        try:
            valid[bvid] = validate_output(entry, root)
            state["items"][bvid]["status"] = "complete"
            state["items"][bvid].pop("error", None)
            state["items"][bvid]["completed_at_utc"] = utc_now()
        except (OSError, KeyError, TypeError, ValueError, QueueError, json.JSONDecodeError) as error:
            state["items"][bvid]["status"] = "needs_resume"
            state["items"][bvid]["error"] = str(error)
            issues.append(f"{bvid}: {error}")
    state["updated_at_utc"] = utc_now()
    return valid, issues


def status(plan_path: Path, csv_path: Path, root: Path) -> dict[str, Any]:
    if not plan_path.is_file():
        plan = make_plan(csv_path, root)
    else:
        plan = load_json(plan_path)
    current_state_path = state_path_for(root)
    existing = load_json(current_state_path) if current_state_path.is_file() else None
    state = state_for(plan, existing)
    valid, issues = inspect_queue(plan, state, root)
    summary_path = summary_path_for(root)
    return {"entry_count": len(plan["entries"]),
            "complete": sum(item["status"] == "complete" for item in state["items"].values()),
            "needs_resume": len(issues), "issues": issues,
            "summary_csv": relative(summary_path, root),
            "state_file": relative(state_path_for(root), root),
            "read_only": True}


def state_path_for(root: Path) -> Path:
    return root / f"data/reports/{SEASON}_全文补转写进度.json"


def plan_path_for(root: Path) -> Path:
    return root / f"data/reports/{SEASON}_全文补转写计划.json"


def summary_path_for(root: Path) -> Path:
    return root / f"data/seasons/{SEASON}/{SEASON}_全文补转写目录.csv"


def log_path_for(entry: dict[str, Any], root: Path) -> Path:
    return root / f"data/reports/{SEASON}_全文补转写日志" / f"{entry['bvid']}.log"


def run_one(entry: dict[str, Any], root: Path, state: dict[str, Any],
            runner: Callable[..., Any] = subprocess.run) -> tuple[bool, dict[str, Any] | None]:
    """Run or resume one entry; the injected runner keeps tests away from GPU/ASR."""
    bvid = entry["bvid"]
    item = state["items"][bvid]
    try:
        validated = validate_output(entry, root)
    except (OSError, KeyError, TypeError, ValueError, QueueError, json.JSONDecodeError):
        validated = None
    if validated is not None:
        try:
            copy_exports(entry, root, validated)
            item.update({"status": "complete", "completed_at_utc": utc_now(),
                         "duration_ms": validated["duration_ms"],
                         "sentence_count": validated["sentence_count"]})
            item.pop("error", None)
            return True, validated
        except Exception as error:
            item.update({"status": "failed", "failed_at_utc": utc_now(),
                         "error": f"copying verified exports failed: {error}"})
            return False, None

    try:
        manifest, audio, _ = expected_data(entry, root)
        if not TRANSCRIBER.is_file() and root == ROOT:
            raise QueueError(f"FunASR script not found: {TRANSCRIBER}")
        out = root / Path(entry["output_dir"])
        log_path = log_path_for(entry, root)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        item.update({"status": "running", "started_at_utc": utc_now(), "error": None,
                     "log_file": relative(log_path, root)})
        state["updated_at_utc"] = utc_now()
        save_json(state_path_for(root), state)
        command = [sys.executable, str(root / "scripts/transcribe_funasr.py"), str(audio),
                   "--out", str(out), "--manifest", str(root / entry["manifest_file"]),
                   "--no-speakers"]
        with log_path.open("a", encoding="utf-8", newline="") as log:
            log.write(f"\n[{utc_now()}] {' '.join(command)}\n")
            log.flush()
            completed = runner(command, cwd=str(root), stdout=log, stderr=subprocess.STDOUT,
                               check=False)
            log.write(f"[{utc_now()}] returncode={completed.returncode}\n")
        item["last_returncode"] = completed.returncode
        validated = validate_output(entry, root)
        copy_exports(entry, root, validated)
        item.update({"status": "complete", "completed_at_utc": utc_now(),
                     "duration_ms": validated["duration_ms"],
                     "sentence_count": validated["sentence_count"]})
        item.pop("error", None)
        return True, validated
    except Exception as error:
        item.update({"status": "failed", "failed_at_utc": utc_now(), "error": str(error)})
        return False, None


def run_batch(csv_path: Path | None = None, root: Path = ROOT,
              runner: Callable[..., Any] = subprocess.run) -> int:
    csv_path = csv_path or DEFAULT_CSV
    with process_lock(root):
        plan = make_plan(csv_path, root)
        plan_file = plan_path_for(root)
        save_json(plan_file, plan)
        state_file = state_path_for(root)
        existing = load_json(state_file) if state_file.is_file() else None
        state = state_for(plan, existing)
        state["plan_file"] = relative(plan_file, root)
        # A prior "complete" marker is not evidence until this run rechecks
        # the transcript, source hash, VAD ranges, checkpoints and exports.
        for item in state["items"].values():
            if item.get("status") == "complete":
                item["status"] = "pending"
        save_json(state_file, state)
        validation: dict[str, dict[str, Any]] = {}
        failures = 0
        for entry in plan["entries"]:
            success, details = run_one(entry, root, state, runner=runner)
            if success and details is not None:
                validation[entry["bvid"]] = details
            else:
                failures += 1
            state["updated_at_utc"] = utc_now()
            save_json(state_file, state)
            update_indexes(csv_path, root, plan, state, validation)
            write_summary(summary_path_for(root), summary_rows(plan, state, validation))
        state["updated_at_utc"] = utc_now()
        state["failure_count"] = failures
        save_json(state_file, state)
        update_indexes(csv_path, root, plan, state, validation)
        write_summary(summary_path_for(root), summary_rows(plan, state, validation))
        return 1 if failures else 0


def do_plan(csv_path: Path, root: Path) -> dict[str, Any]:
    plan = make_plan(csv_path, root)
    plan_file = plan_path_for(root)
    save_json(plan_file, plan)
    write_summary(summary_path_for(root), summary_rows(
        plan, state_for(plan), {}))
    return {"entry_count": len(plan["entries"]), "counts": plan["selection"]["counts"],
            "plan_file": relative(plan_file, root), "summary_csv": relative(summary_path_for(root), root)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run", "status"))
    parser.add_argument("--season", choices=season_codes(ROOT), default=DEFAULT_SEASON)
    parser.add_argument("--csv", type=Path,
                        help="preferred review index CSV (default: the selected season's review index)")
    args = parser.parse_args(argv)
    configure_season(args.season)
    selected_csv = args.csv or DEFAULT_CSV
    csv_path = selected_csv if selected_csv.is_absolute() else ROOT / selected_csv
    try:
        if args.command == "plan":
            result = do_plan(csv_path, ROOT)
            code = 0
        elif args.command == "run":
            code = run_batch(csv_path, ROOT)
            result = {"exit_code": code, "state_file": relative(STATE_PATH, ROOT),
                      "summary_csv": relative(SUMMARY_CSV, ROOT)}
        else:
            result = status(plan_path_for(ROOT), csv_path, ROOT)
            code = 0 if result["needs_resume"] == 0 else 1
    except (QueueError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
