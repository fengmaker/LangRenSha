"""Capture one source-video frame per game for visible seat-name labels."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

import batch_s22 as batch
from capture_bilibili_frame import capture

BASE = batch.ROOT / "data/extractions/S22/frame_seats"
PROGRESS = batch.ROOT / "data/reports/S22_画面截帧进度.json"


def capture_one(entry, fraction=0.45, force=False):
    bvid = entry["bvid"]
    folder = BASE / bvid
    receipt = folder / "capture.json"
    if receipt.exists() and not force:
        previous = batch.read_json(receipt)
        if (batch.ROOT / previous["frame_path"]).is_file():
            return previous
    metadata = batch.read_json(batch.ROOT / "data/raw/bilibili" / bvid / "p01/metadata.raw.json")["data"]
    page = next((p for p in metadata.get("pages", []) if int(p["cid"]) == entry["cid"]), {})
    duration = float(page.get("duration") or metadata["duration"])
    second = round(max(10, min(duration - 5, duration * fraction)), 3)
    capture(bvid, entry["cid"], [second], folder)
    frame = folder / f"{bvid}_{second:09.3f}.png"
    value = {"bvid": bvid, "cid": entry["cid"], "date": entry["date"], "game_number": entry.get("game_number"),
             "source_kind": "video_frame", "frame_time_ms": round(second * 1000),
             "frame_path": batch.relative(frame), "frame_sha256": batch.digest(frame),
             "video_duration_ms": round(duration * 1000), "captured_at": batch.now()}
    batch.atomic_json(receipt, value)
    return value


def run(args):
    entries = list(batch.load_state()["items"].values())
    selected = [e for e in entries if e["state"] != "preserved" and (not args.bvid or e["bvid"] == args.bvid)]
    if args.limit:
        selected = [e for e in selected if not (BASE / e["bvid"] / "capture.json").is_file()][:args.limit]
    progress = batch.read_json(PROGRESS) if PROGRESS.exists() else {"items": {}, "created_at": batch.now()}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(capture_one, e, args.fraction, args.force): e for e in selected}
        for future in as_completed(futures):
            entry = futures[future]
            bvid = entry["bvid"]
            try:
                progress["items"][bvid] = {"status": "captured", **future.result()}
            except Exception as exc:
                # AV exceptions can contain temporary signed stream URLs.
                progress["items"][bvid] = {"status": "failed", "error_type": type(exc).__name__, "attempted_at": batch.now()}
                print(f"[{entry['index']}/163] {bvid}: capture failed {type(exc).__name__}", flush=True)
            pending = [e for e in entries if e["state"] != "preserved" and progress["items"].get(e["bvid"], {}).get("status") != "captured"]
            progress.update(updated_at=batch.now(), last_processed=bvid,
                            captured=sum(v.get("status") == "captured" for v in progress["items"].values()),
                            pending=len(pending), next_bvid=pending[0]["bvid"] if pending else None)
            batch.atomic_json(PROGRESS, progress)
    print({k: v for k, v in progress.items() if k != "items"})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bvid")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=3, choices=[1, 2, 3, 4])
    parser.add_argument("--fraction", type=float, default=0.45)
    parser.add_argument("--force", action="store_true")
    run(parser.parse_args())
