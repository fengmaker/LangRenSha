"""Acquire a frozen official season collection to local Bilibili files."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import requests

from auth_support import AuthConfigurationError
from collect_bilibili_audio import CollectionError, Collector, save_json
from export_collection_index import export
from media_ingest import OFFICIAL_BILIBILI_MID
from season_naming import naming
from season_config import load_season, season_codes

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEASON = season_codes(ROOT)[0]
SEASON = DEFAULT_SEASON
SEASON_CONFIG = load_season(SEASON, ROOT)
PLAN = ROOT / f"data/indexes/{SEASON}_采集计划.json"
STATE = ROOT / f"data/reports/{SEASON}/{SEASON}_采集进度.json"
COLLECTION_ID = SEASON_CONFIG["collection_id"]
SEED_BVID = SEASON_CONFIG["seed_bvid"]


def configure_season(season: str) -> None:
    """Keep each season's frozen plan and collection progress separate."""
    global SEASON, SEASON_CONFIG, COLLECTION_ID, SEED_BVID, PLAN, STATE
    SEASON_CONFIG = load_season(season, ROOT)
    COLLECTION_ID = SEASON_CONFIG["collection_id"]
    SEED_BVID = SEASON_CONFIG["seed_bvid"]
    SEASON = season
    PLAN = ROOT / f"data/indexes/{season}_采集计划.json"
    STATE = ROOT / f"data/reports/{season}/{season}_采集进度.json"


def build_plan(auth: str, cookies: Path | None) -> dict:
    collector = Collector(auth, cookies, quiet=True)
    raw = collector.api("/x/web-interface/view", {"bvid": SEED_BVID})
    view = raw["data"]
    collection = view.get("ugc_season") or {}
    if (str(view["owner"]["mid"]) != OFFICIAL_BILIBILI_MID or
            collection.get("id") != COLLECTION_ID or
            str(collection.get("mid")) != OFFICIAL_BILIBILI_MID):
        raise ValueError(f"不是目标官方 {SEASON} 合集")
    raw_path = ROOT / f"data/raw/bilibili/{SEASON}_collection.view.raw.json"
    save_json(raw_path, raw)
    csv_path = ROOT / f"data/indexes/{SEASON}_官方合集_候选索引.csv"
    export(raw_path, csv_path)
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != collection.get("ep_count"):
        raise ValueError("返回条目数与官方合集声明数量不一致，未开始批量下载")
    keys = {(row["bvid"], row["cid"]) for row in rows}
    if len(keys) != len(rows):
        raise ValueError("合集含重复 BV/CID，需先核对目录")
    opening = min(row["event_date_candidate"] for row in rows
                  if row["phase_candidate"] == "showmatch" and row["event_date_candidate"])
    anchor = datetime.strptime(opening, "%Y%m%d").date().isoformat()
    entries = []
    for index, row in enumerate(rows, start=1):
        entry = {"index": index, "bvid": row["bvid"], "cid": int(row["cid"]),
                 "page": int(row["page"] or 1), "title": row["title"],
                 "duration_seconds": int(row["duration_seconds"] or 0)}
        entry["labels"] = naming(entry["title"], entry["bvid"], entry["cid"],
                                 entry["page"], anchor, SEASON)
        entries.append(entry)
    value = {"schema_version": 1, "season": SEASON, "collection_id": COLLECTION_ID,
             "collection_title": collection["title"], "owner_mid": OFFICIAL_BILIBILI_MID,
             "created_at_utc": datetime.now(timezone.utc).isoformat(),
             "collection_source": raw_path.relative_to(ROOT).as_posix(), "anchor": anchor,
             "declared_count": collection["ep_count"], "entry_count": len(entries),
             "entries": entries,
             "coverage_note": "完整保存本次官方合集实际返回的媒体条目；不保证已找齐合集外、已删除或未公开的历史对局。",
             "total_duration_seconds": sum(item["duration_seconds"] for item in entries)}
    save_json(PLAN, value)
    return value


def source_key(entry: dict) -> str:
    return f"{entry['bvid']}:{entry['cid']}"


def collect_one(entry: dict, collector: Collector) -> dict:
    manifest = collector.collect(
        entry["bvid"], entry["page"], ROOT / "data/raw/bilibili", True,
        128000, 200 * 1024**2, expected_owner=OFFICIAL_BILIBILI_MID,
        subtitles_first=True,
    )
    if manifest["cid"] != entry["cid"]:
        raise CollectionError("实际 CID 与冻结合集清单不符")
    subtitles = manifest["subtitles"]
    tracks = subtitles["tracks"]
    audio = manifest.get("audio")
    return {
        "status": "complete" if tracks else "audio_only",
        "bvid": entry["bvid"], "cid": entry["cid"], "page": entry["page"],
        "manifest": (ROOT / "data/raw/bilibili" / entry["bvid"] /
                     f"p{entry['page']:02d}" / "manifest.json").relative_to(ROOT).as_posix(),
        "subtitle_status": subtitles.get("status"), "subtitle_tracks": len(tracks),
        "audio_bytes": audio.get("bytes") if audio else None,
        "audio_sha256": audio.get("sha256") if audio else None,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def run(plan: dict, auth: str, cookies: Path | None) -> int:
    if plan["season"] != SEASON or plan["collection_id"] != COLLECTION_ID:
        raise ValueError("冻结计划与目标赛季不一致")
    collector = Collector(auth, cookies, quiet=True)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {
        "season": SEASON, "items": {}}
    if state.get("season", SEASON) != SEASON:
        raise ValueError("旧进度不是同一个赛季")
    if state.get("collection_id", COLLECTION_ID) != plan["collection_id"]:
        raise ValueError("旧进度不是同一个合集")
    state["collection_id"] = plan["collection_id"]
    state["current_run"] = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "state": "running",
    }
    summary = {"planned": len(plan["entries"]), "successful": 0, "failed": 0}
    state["summary"] = summary
    save_json(STATE, state)

    for index, entry in enumerate(plan["entries"], start=1):
        key = source_key(entry)
        try:
            result = collect_one(entry, collector)
        except (CollectionError, AuthConfigurationError, requests.RequestException,
                ValueError, OSError) as error:
            result = {"status": "failed", "bvid": entry["bvid"], "cid": entry["cid"],
                      "page": entry["page"],
                      "reason": str(error) if isinstance(error, (CollectionError, AuthConfigurationError))
                      else type(error).__name__,
                      "finished_at_utc": datetime.now(timezone.utc).isoformat()}
        state["items"][key] = result
        summary["failed" if result["status"] == "failed" else "successful"] += 1
        save_json(STATE, state)
        print(f"[{index}/{summary['planned']}] {entry['bvid']} "
              f"{result['status']} 字幕{result.get('subtitle_tracks', 0)}轨 "
              f"{result.get('reason', '')}", flush=True)
        if result["status"] == "failed":
            break

    run_state = state["current_run"]
    run_state["state"] = "finished" if summary["successful"] == summary["planned"] else "stopped"
    run_state["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_json(STATE, state)
    print(json.dumps(state["summary"], ensure_ascii=False, indent=2), flush=True)
    return 0 if run_state["state"] == "finished" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "run", "status"])
    parser.add_argument("--season", choices=season_codes(ROOT), default=DEFAULT_SEASON)
    parser.add_argument("--auth", choices=["none", "cookies"], default="none")
    parser.add_argument("--cookies-file", type=Path)
    args = parser.parse_args()
    configure_season(args.season)
    if args.action == "plan":
        value = build_plan(args.auth, args.cookies_file)
        print(json.dumps({"plan": str(PLAN.relative_to(ROOT)), "entries": value["entry_count"],
                          "hours": value["total_duration_seconds"] / 3600},
                         ensure_ascii=False, indent=2))
    elif args.action == "status":
        state = json.loads(STATE.read_text(encoding="utf-8"))
        print(json.dumps({**state["summary"], "current_run": state.get("current_run")},
                         ensure_ascii=False, indent=2))
    else:
        raise SystemExit(run(json.loads(PLAN.read_text(encoding="utf-8")),
                             args.auth, args.cookies_file))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        main()
    except (AuthConfigurationError, CollectionError, ValueError, OSError,
            requests.RequestException) as error:
        message = str(error) if isinstance(error, (AuthConfigurationError, CollectionError, ValueError)) else type(error).__name__
        print("采集停止：" + message, file=sys.stderr)
        raise SystemExit(1)
