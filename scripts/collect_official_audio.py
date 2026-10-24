"""Stage 1: official audio acquisition, local validation and raw-source registration."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid
from urllib.parse import parse_qs, urlsplit

import psycopg
import requests

from auth_support import AuthConfigurationError
from collect_bilibili_audio import CollectionError, Collector, parse_bvid, save_json
import database
from media_ingest import MediaValidationError, OFFICIAL_BILIBILI_MID, validate_media

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video",help="一条官方 BVID 或视频链接")
    parser.add_argument("--page",type=int,help="分 P；未指定时读取链接中的 p 参数，否则为 1")
    parser.add_argument("--auth",choices=["none","cookies"],default="none")
    parser.add_argument("--cookies-file",type=Path)
    parser.add_argument("--max-mib",type=int,default=200)
    parser.add_argument("--max-bitrate",type=int,default=128000)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--register-existing",action="store_true",help="离线校验并登记已有音轨，不请求 B 站")
    modes.add_argument("--check-only",action="store_true",help="仅离线检查已有音轨，不访问网络或数据库")
    args = parser.parse_args()
    try:
        linked_page = int(parse_qs(urlsplit(args.video).query).get("p",["1"])[0])
    except (ValueError,TypeError):
        parser.error("链接的 p 参数应为正整数")
    if args.page is None:
        args.page = linked_page
    elif "p" in parse_qs(urlsplit(args.video).query) and args.page != linked_page:
        parser.error("--page 与链接中的 p 参数不一致，请明确选择一个分 P")
    if args.page < 1 or args.max_mib < 1 or args.max_bitrate < 1:
        parser.error("分 P、文件上限和码率必须为正数")
    if args.auth == "none" and args.cookies_file:
        parser.error("使用 Cookie 时请显式指定 --auth cookies")
    if args.auth == "cookies" and not args.cookies_file:
        parser.error("--auth cookies 必须指定 --cookies-file")
    if (args.check_only or args.register_existing) and (args.auth != "none" or args.cookies_file):
        parser.error("离线模式不使用登录参数")
    try:
        bvid = parse_bvid(args.video)
    except CollectionError as error:
        parser.error(str(error))
    mode = "check_only" if args.check_only else "register_existing" if args.register_existing else "download_and_register"
    manifest_path = ROOT / "data/raw/bilibili" / bvid / f"p{args.page:02d}" / "manifest.json"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = ROOT / "data/reports/acquisition" / f"{stamp}_{bvid}_p{args.page:02d}_{uuid.uuid4().hex[:8]}.json"
    report = {"stage":1,"mode":mode,"bvid":bvid,"page":args.page,"auth_mode":args.auth,
              "started_at_utc":datetime.now(timezone.utc).isoformat(),"status":"started", "raw_registered":False,
              "transcription_started":False,"game_facts_changed":False}
    phase = "download" if mode == "download_and_register" else "validation"
    try:
        if mode == "download_and_register":
            Collector(args.auth,args.cookies_file).collect(bvid,args.page,ROOT / "data/raw/bilibili",True,
                args.max_bitrate,args.max_mib*1024*1024,expected_owner=OFFICIAL_BILIBILI_MID)
        phase = "validation" if args.check_only else "validation_and_raw_registration"
        if args.check_only:
            report["validation"] = validate_media(manifest_path,bvid,args.page)["summary"]
            report["status"] = "validated_only"
        else:
            report["database"] = database.import_media(manifest_path,bvid,args.page)
            report["raw_registered"] = True
            report["status"] = "raw_registered"
    except (CollectionError,AuthConfigurationError,MediaValidationError,database.ReviewError) as error:
        report.update(status="failed",failed_phase=phase,error=str(error))
    except (requests.RequestException,psycopg.Error,OSError,ValueError,KeyError,TypeError) as error:
        # Do not expose credential-bearing connection/network/parser exceptions.
        report.update(status="failed",failed_phase=phase,error=type(error).__name__)
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_json(report_path,report)
    print(json.dumps({**report,"report_file":str(report_path.relative_to(ROOT))},ensure_ascii=False,indent=2))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
