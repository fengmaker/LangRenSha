"""Join visual label readings to schedule photos and build offline review artifacts.

Does not alter raw photos, the source schedule or the formal player registry.
Readings are visual transcription candidates. Human approval starts pending.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote


DEFAULT_ROOT = Path("data/weibo/2026-05-26_2026-10-20/人名复核")
HEADERS = ["照片编号", "图上名字_候选", "人工确认", "修正名字", "人工备注", "识读状态",
           "识读备注", "赛季", "首次赛日", "最后赛日", "引用次数", "引用赛日",
           "名牌裁图", "代表原图", "代表原帖", "图片SHA256"]


def dump_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def relative(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path, root)).as_posix()


def build(root: Path) -> dict:
    root = root.resolve()
    index = json.loads((root / "照片人名_来源索引.json").read_text(encoding="utf-8"))
    labels: dict[str, dict] = {}
    for name in ["S22_A.json", "S22_B.json", "S23.json"]:
        for row in json.loads((root / "识读记录" / name).read_text(encoding="utf-8-sig")):
            if row["picture_id"] in labels:
                raise ValueError(f"Duplicate reading {row['picture_id']}")
            labels[row["picture_id"]] = row
    for row in json.loads((root / "识读记录/主复查修订.json").read_text(encoding="utf-8")):
        if row["picture_id"] not in labels:
            raise ValueError(f"Unknown correction {row['picture_id']}")
        labels[row["picture_id"]] = row
    expected = {row["picture_id"] for row in index["pictures"]}
    if set(labels) != expected:
        raise ValueError("Visual readings must cover exactly the indexed pictures")

    raw_root = Path(index["source_manifest"]).parent
    reviews, occurrences, cards = [], [], []
    by_name: dict[str, list] = defaultdict(list)
    source_hashes: dict[str, str] = {}
    for picture in index["pictures"]:
        pid = picture["picture_id"]
        label = labels[pid]
        if label["confidence"] not in {"清楚", "存疑", "无法辨认"}:
            raise ValueError(f"Invalid reading status {pid}")
        name = label["name"].strip()
        if not name or name == "无法辨认":
            raise ValueError(f"Missing candidate {pid}; record an empty candidate explicitly if needed")
        source = Path(picture["source_image"])
        crop = root / picture["crop_file"]
        if not source.is_file() or not crop.is_file():
            raise ValueError(f"Missing evidence for {pid}")
        events = picture["occurrences"]
        dates = sorted({row["event_date"] for row in events})
        review = dict(zip(HEADERS, [pid, name, "待确认", "", "", label["confidence"],
            label["note"], picture["season"], dates[0], dates[-1], len(events), "；".join(dates),
            picture["crop_file"], relative(source, root), events[0]["source_url"], picture["image_sha256"]]))
        reviews.append(review)
        by_name[name].append(review)
        card = {"id": pid, "name": name, "confidence": label["confidence"], "note": label["note"],
                "season": picture["season"], "crop": quote(picture["crop_file"], safe="/"),
                "original": quote(relative(source, root), safe="/"), "first": dates[0], "last": dates[-1],
                "count": len(events), "sha256": picture["image_sha256"], "occurrences": []}
        for event in events:
            actual = raw_root / event["image_file"]
            if not actual.is_file():
                raise ValueError(f"Missing occurrence image {actual}")
            # Verify every occurrence before assigning a deduplicated visual reading.
            key = str(actual)
            if key not in source_hashes:
                source_hashes[key] = hashlib.sha256(actual.read_bytes()).hexdigest()
            if source_hashes[key] != picture["image_sha256"]:
                raise ValueError(f"Source hash mismatch for {pid}: {actual}")
            occurrence = {"比赛日期": event["event_date"], "赛季": picture["season"], "阶段": event["phase"],
                "微博ID": event["post_id"], "原帖图片序号": event["image_index"], "照片编号": pid,
                "图上名字_候选": name, "识读状态": label["confidence"], "人工确认": "待确认",
                "修正名字": "", "人工备注": "", "原图": relative(actual, root), "原帖": event["source_url"],
                "图片SHA256": picture["image_sha256"]}
            occurrences.append(occurrence)
            card["occurrences"].append({"date": event["event_date"], "index": event["image_index"],
                "url": event["source_url"], "original": quote(relative(actual, root), safe="/"),
                "players": event["text_players"], "commentators": event["text_commentators"], "judge": event["text_judge"]})
        cards.append(card)

    occurrences.sort(key=lambda r: (r["比赛日期"], r["微博ID"], r["原帖图片序号"]))
    write_csv(root / "照片人名_逐图复核.csv", HEADERS, reviews)
    write_csv(root / "照片人名_逐帖对应.csv", list(occurrences[0]), occurrences)
    stats = {"scope": "S22/S23的79份比赛排班帖配图", "schedule_posts": len({r["微博ID"] for r in occurrences}),
        "image_occurrences": len(occurrences), "unique_pictures": len(reviews), "distinct_candidate_spellings": len(by_name),
        "uncertain_picture_ids": [r["照片编号"] for r in reviews if r["识读状态"] != "清楚"],
        "human_review_status": "待确认", "method": "视觉读取照片名牌文字，按SHA-256复用相同图片的识读结果，逐图复查。照片序号不是座位号；未按正文名单顺序匹配人物。",
        "season_counts": {season: {"unique_pictures": sum(r["赛季"] == season for r in reviews),
            "image_occurrences": sum(r["赛季"] == season for r in occurrences)} for season in ["S22", "S23"]},
        "evidence_files_checked": len(source_hashes), "all_occurrence_hashes_match": True}
    dump_json(root / "照片人名_候选结果.json", {"schema_version": 1, "summary": stats, "pictures": cards})
    template = Path(__file__).with_name("weibo_name_review.html").read_text(encoding="utf-8")
    payload = json.dumps({"summary": stats, "pictures": cards}, ensure_ascii=False).replace("<", "\\u003c")
    (root / "照片人名_复核.html").write_text(template.replace("__REVIEW_DATA__", payload), encoding="utf-8")
    dump_json(root / "照片人名_验收.json", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    print(json.dumps(build(args.review_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
