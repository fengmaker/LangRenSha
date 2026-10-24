"""Export L0 candidates from a saved Bilibili view response; no network access."""

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def export(raw_path: Path, output: Path) -> dict:
    view = json.loads(raw_path.read_text(encoding="utf-8"))["data"]
    collection = view.get("ugc_season") or {}
    rows = []
    numbers = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    for section in collection.get("sections") or []:
        for episode in section.get("episodes") or []:
            title = episode.get("title") or ""
            page = episode.get("page") or {}
            published = (episode.get("arc") or {}).get("pubdate")
            day = re.search(r"(?<!\d)(20\d{6})(?!\d)", title)
            game = re.search(r"第([一二三四五六七八九十]|\d+)局", title)
            game_number = None
            if game:
                value = game.group(1)
                game_number = int(value) if value.isdigit() else numbers[value]
            phase = ("showmatch" if "表演赛" in title else
                     "finals_week" if "决赛" in title else
                     "regular" if "正赛" in title else "unknown")
            bvid = episode.get("bvid") or ""
            rows.append({
                "collection_id": collection.get("id"),
                "collection_title": collection.get("title"),
                "collection_owner_mid": collection.get("mid"),
                "section_title": section.get("title"),
                "bvid": bvid, "aid": episode.get("aid"),
                "cid": episode.get("cid") or page.get("cid"),
                "page": page.get("page"), "title": title,
                "duration_seconds": page.get("duration"),
                "published_timestamp": published,
                "published_date_utc8": datetime.fromtimestamp(published, timezone(timedelta(hours=8))).date().isoformat() if published else "",
                "url": f"https://www.bilibili.com/video/{bvid}/",
                "event_date_candidate": day.group(1) if day else "",
                "phase_candidate": phase,
                "game_number_candidate": game_number,
                "is_extra_game": "", "scoring_eligible": "",
                "game_facts_reviewed": False,
                "classification_method": "title_pattern_candidate_only",
                "source_response": str(raw_path.as_posix()),
                "source_api_url": f"https://api.bilibili.com/x/web-interface/view?bvid={view['bvid']}",
            })
    if not rows:
        raise ValueError("响应没有合集条目")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "collection_title": collection.get("title"), "collection_id": collection.get("id"),
        "entry_count": len(rows), "unique_bvid_count": len({r['bvid'] for r in rows}),
        "phase_candidate_counts": {key: sum(r['phase_candidate'] == key for r in rows)
                                   for key in ['showmatch', 'regular', 'finals_week', 'unknown']},
        "reviewed_game_count": 0,
        "event_date_candidate_range": {
            "first": min((r['event_date_candidate'] for r in rows if r['event_date_candidate']), default=None),
            "last": max((r['event_date_candidate'] for r in rows if r['event_date_candidate']), default=None),
        },
        "note": "视频合集候选条目，不代表已核验赛事全集；阶段和局次仅由标题提取。",
    }
    output.with_suffix(".summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_response", type=Path)
    parser.add_argument("output_csv", type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.raw_response, args.output_csv), ensure_ascii=False))
