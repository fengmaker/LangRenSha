"""Independent final checks for the authorized S22 full-audio ASR batch."""
import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import transcribe_review_queue as queue
from transcribe_funasr import decode_audio, normalize, save_json


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def verify():
    plan = queue.load_json(queue.PLAN_PATH)
    before = read_rows(ROOT / "data/reports/baselines/S22_中文优先复核目录_全文转写前.csv")
    after = read_rows(queue.DEFAULT_CSV)
    if len(before) != 163 or len(after) != 163:
        raise ValueError("Review catalog row count changed")
    for old, new in zip(before, after):
        if any(new.get(key) != value for key, value in old.items()):
            raise ValueError(f"Original catalog fields changed for {old['BVID']}")
    index_json = queue.load_json(queue.DEFAULT_CSV.with_suffix(".json"))
    original_json = queue.load_json(ROOT / "data/reports/baselines/S22_中文优先复核目录_全文转写前.json")
    if len(original_json["entries"]) != 163 or len(index_json["entries"]) != 163:
        raise ValueError("JSON review catalog row count changed")
    if sum(row.get("本地转写状态") == "complete" for row in after) != 25:
        raise ValueError("Review catalog must link exactly 25 completed full-audio ASR results")
    for old, new in zip(original_json["entries"], index_json["entries"]):
        if any(new.get(key) != value for key, value in old.items()):
            raise ValueError(f"Original JSON catalog fields changed for {old['BVID']}")
    rows_by_bvid = {row["BVID"]: row for row in after}
    checks = []
    for entry in plan["entries"]:
        details = queue.validate_output(entry, ROOT)
        transcript = details["transcript"]
        waveform = decode_audio(details["audio_file"])
        decoded_ms = round(len(waveform) / 16)
        del waveform
        if decoded_ms != details["duration_ms"]:
            raise ValueError(f"Decoded full source duration differs: {entry['bvid']}")
        reconstructed = []
        for chunk in transcript["chunks"]:
            checkpoint = queue.load_json(details["output_dir"] / "raw" / f"chunk_{chunk['index']:04}.json")
            reconstructed.extend(normalize(checkpoint["result"], chunk["index"], chunk["start_ms"], chunk["end_ms"]))
        if reconstructed != transcript["segments"]:
            raise ValueError(f"Normalized export does not match raw checkpoints: {entry['bvid']}")
        hashes = {}
        for kind, name in queue.OUTPUT_NAMES.items():
            source = details["output_dir"] / name
            target = ROOT / entry["exports"][kind]
            if source.read_bytes() != target.read_bytes():
                raise ValueError(f"Derived export differs: {target}")
            hashes[kind] = hashlib.sha256(target.read_bytes()).hexdigest()
        row = rows_by_bvid[entry["bvid"]]
        if row["本地转写状态"] != "complete" or any(
            row[field] != entry["exports"][kind] for field, kind in
            [("本地全文JSON", "json"), ("本地全文SRT", "srt"), ("本地全文阅读版", "reading")]
        ):
            raise ValueError(f"Catalog does not link the completed files: {entry['bvid']}")
        checks.append({"bvid": entry["bvid"], "audio_sha256": details["audio_sha256"],
                       "decoded_duration_ms": decoded_ms, "chunk_count": len(transcript["chunks"]),
                       "sentence_count": details["sentence_count"],
                       "characters": sum(len(segment["text"]) for segment in transcript["segments"]),
                       "first_text_ms": transcript["segments"][0]["start_ms"],
                       "last_text_ms": transcript["segments"][-1]["end_ms"],
                       "full_audio_processed": True, "exports_sha256": hashes})
        print(f"Verified {len(checks)}/25: {entry['bvid']}", flush=True)
    report = {"verified_at_utc": datetime.now(timezone.utc).isoformat(),
              "selected_count": len(checks), "complete": len(checks),
              "audio_hours": sum(item["decoded_duration_ms"] for item in checks) / 3600000,
              "sentences": sum(item["sentence_count"] for item in checks),
              "characters": sum(item["characters"] for item in checks),
              "original_catalog_fields_preserved": True,
              "checks": ["full source SHA-256 matches manifest", "full source decoded duration matches output",
                         "all chunk intervals continuously cover 0 to full duration",
                         "raw checkpoint normalization exactly matches transcript",
                         "JSON/SRT/reading exports match their originals", "review catalog links completed exports"],
              "accuracy_verified": False, "game_facts_created": False, "entries": checks}
    save_json(ROOT / "data/reports/S22/S22_全文补转写验收.json", report)
    print(json.dumps({key: value for key, value in report.items() if key != "entries"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    verify()
