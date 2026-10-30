"""Check transcript-only supplementation, resumable state and review entries."""
from collections import Counter
import hashlib
import json
import sys

import batch_s22 as batch
from s22_text_review import load_annotations, progress_summary, PROGRESS, REVIEW_VERSION


def audit():
    state, progress, annotations = batch.load_state(), batch.read_json(PROGRESS), load_annotations()
    errors, checked, scopes = [], 0, Counter()
    entries = state["items"]
    expected_checked = sum(entry.get("state") != "preserved" for entry in entries.values())
    for bvid, entry in entries.items():
        if entry["state"] == "preserved":
            continue
        try:
            annotation = annotations[bvid]
            folder = batch.ROOT / entry["output_dir"]
            review = batch.read_json(folder / "复核记录.json")
            applied = progress["items"][bvid]
            assert annotation["scope"] in {"recap_text", "full_transcript"}, "范围不是转写文字"
            assert batch.digest(folder / "复盘原文.txt") == annotation["recap_sha256"], "复盘来源哈希变化"
            assert applied["status"] in {"text_checked", "questions", "no_recap", "user_reviewed"}, "尚未完成文字整理"
            if applied["status"] != "user_reviewed":
                signature = hashlib.sha256(json.dumps(annotation, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                assert signature == applied["annotation_sha256"], "新核对结果尚未写回"
                assert applied.get("review_version") == REVIEW_VERSION, "补充规则版本尚未更新"
                assert len(review["text_review"]["questions"]) == applied["question_count"], "疑点数量与进度不符"
            assert (batch.ROOT / "data/archive/S22_text_review" / (bvid + ".before.json")).is_file(), "缺少补充前档案"
            segments = batch.load_segments(batch.ROOT / entry["source_path"])
            maximum = max(s["end_ms"] for s in segments)
            for q in annotation.get("corrections", []) + annotation.get("unresolved", []):
                start, end = q.get("start_ms"), q.get("end_ms")
                assert start is None or type(start) is int, "起始时间必须为整数毫秒"
                assert end is None or type(end) is int, "结束时间必须为整数毫秒"
                assert start is None or 0 <= start <= maximum + 1000, "起始时间超出转写范围"
                assert end is None or 0 <= end <= maximum + 1000, "结束时间超出转写范围"
                assert start is None or end is None or start <= end, "时间范围反向"
            assert "http://127.0.0.1:8766/" in (folder / "复核.html").read_text(encoding="utf-8"), "缺少可编辑入口"
            checked += 1
            scopes[annotation["scope"]] += 1
        except (KeyError, AssertionError, ValueError) as exc:
            errors.append({"bvid": bvid, "index": entry["index"], "error": str(exc)})
    report = {"checked_at": batch.now(), "valid": checked == expected_checked and not errors,
              "checked_games": checked, "expected_checked_games": expected_checked,
              "scope": dict(scopes), "summary": progress_summary(state, progress),
              "review_url": "http://127.0.0.1:8766/", "errors": errors,
              "note": "只检查转写来源、补充版本、毫秒时间、续接进度与复核入口；不代替用户确认疑点。"}
    batch.atomic_json(batch.ROOT / "data/reports/S22/S22_转写补充验收.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        return audit()
    except Exception as exc:
        print(json.dumps({"valid": False, "audit_error": type(exc).__name__}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
