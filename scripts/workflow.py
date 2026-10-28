"""One season workflow: inspect, preview or execute a named stage."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys

from season_config import load_season, season_codes

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("collect", "transcribe", "review", "import", "publish", "verify")
PYTHON = ROOT / ".venv/Scripts/python.exe"
ASR_PYTHON = ROOT / ".venv-funasr39/Scripts/python.exe"


def formal_seasons(root: Path = ROOT) -> list[str]:
    return [season for season in season_codes(root)
            if any((root / "data/games" / season).glob("*/dossier.json"))]


def command(script: str, *args: str, asr: bool = False) -> list[str]:
    return [str(ASR_PYTHON if asr else PYTHON), script, *args]


def stage_commands(stage: str, season: str, *, root: Path = ROOT,
                   auth: str = "none", cookies: str = ".secrets/bilibili.cookies.txt",
                   bvid: str | None = None, photos: bool = False,
                   full_season: bool = False) -> list[list[str]]:
    config = load_season(season, root)
    if stage == "collect":
        auth_args = ["--auth", auth]
        if auth == "cookies":
            auth_args += ["--cookies-file", cookies]
        jobs = []
        if not (root / f"data/indexes/{season}_采集计划.json").is_file():
            jobs.append(command("scripts/collect_season.py", "plan", "--season", season, *auth_args))
        jobs.append(command("scripts/collect_season.py", "run", "--season", season, *auth_args))
        return jobs
    if stage == "transcribe":
        return [command("scripts/transcribe_review_queue.py", "run", "--season", season, asr=True)]
    if stage == "review":
        if not full_season:
            raise ValueError("局部复核按docs/02第六步给AI指定BV、字段及证据片段，直接只读核对；"
                             "此review流水线会生成整季报告，确需整季结构检查时加--full-season")
        if bvid:
            raise ValueError("--full-season会检查整季，不能用--bvid限制范围；局部复核按第六步执行")
        if config.get("review_profile") == "s22_text_review":
            return [command("scripts/audit_s22_batch.py"), command("scripts/formal_entry.py", "audit")]
        if config.get("review_profile") == "s23_game_review":
            return [command("scripts/audit_s23_review.py"),
                    command("scripts/build_s23_review.py", "--require-complete"),
                    command("scripts/check_s23_review_page.py", "--require-complete"),
                    command("scripts/check_s23_phase_review.py"),
                    command("scripts/check_s23_phase_consistency.py"),
                    command("scripts/check_s23_daily_audit.py")]
        raise ValueError(f"{season}尚无复核适配；先完成证据包和逐局判断，不能用空校验代替")
    if stage == "import":
        jobs = [command("scripts/backup_database.py")]
        if config.get("import_profile") == "s23_formal_import":
            return jobs + [command("scripts/import_s23_formal.py", "--prepare"),
                           command("scripts/import_s23_formal.py", "--import-db", "--verify-idempotency")]
        if config.get("import_profile") == "s21_formal_import":
            selected = ["--bvid", bvid] if bvid else []
            return jobs + [command(config["import_entry"], "--prepare", *selected),
                           command(config["import_entry"], "--import-db", *selected)]
        if config.get("import_profile") == "s22_formal_entry":
            if not bvid:
                raise ValueError("S22修订导入请指定--bvid；新建草稿使用formal_entry.py init/check/import")
            return jobs + [command("scripts/batch_s22.py", "import-edits", "--bvid", bvid)]
        raise ValueError(f"{season}尚无正式导入适配；不能复用其他季的固定快照")
    if stage == "publish":
        seasons = formal_seasons(root)
        if season not in seasons:
            raise ValueError(f"{season}还没有正式dossier.json，不能发布候选文件")
        builders = [load_season(code, root)["bluff_entry"] for code in seasons]
        jobs = [command(builder, "--check") for builder in builders]
        jobs += [[str(PYTHON), "-m", "website.api.publish", "--seasons", *seasons, "--check"],
                 [str(PYTHON), "-m", "website.api.publish", "--seasons", *seasons]]
        for code, builder in zip(seasons, builders):
            jobs += [command(builder),
                     [str(PYTHON), "-m", "website.api.publish_bluffs", "--season", code, "--check"],
                     [str(PYTHON), "-m", "website.api.publish_bluffs", "--season", code]]
        if photos:
            jobs.append(command("website/prepare_photos.py"))
        return jobs
    if stage == "verify":
        seasons = formal_seasons(root)
        if season not in seasons:
            raise ValueError(f"{season}还没有正式档案；采集与转写验收分别使用对应阶段报告")
        return [[str(PYTHON), "-m", "website.api.publish", "--seasons", *seasons, "--check"],
                command("website/check_publication.py")]
    raise ValueError(f"Unknown workflow stage: {stage}")


def status(season: str, root: Path = ROOT) -> dict:
    config = load_season(season, root)
    reports = {}
    for suffix in ("采集进度", "采集验收", "全文补转写进度", "转写入库验收", "发言截图进度", "逐局复核进度"):
        path = root / f"data/reports/{season}_{suffix}.json"
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            summary = value.get("summary")
            if summary is None:
                summary = {key: value[key] for key in
                           ("state", "planned", "registered", "completed", "errors", "failure_count",
                            "official_collection_entries", "audio_verified", "with_chinese_subtitles",
                            "without_chinese_subtitles", "captured", "visual_verified", "ai_reviewed",
                            "daily_audited_games", "remaining_games", "unpublished_unique_items", "snapshot_id")
                           if key in value}
                items = value.get("items", [])
                rows = items.values() if isinstance(items, dict) else items
                counts = Counter(item["status"] for item in rows if isinstance(item, dict) and "status" in item)
                if counts:
                    summary["status_counts"] = dict(counts)
            reports[suffix] = {"path": path.relative_to(root).as_posix(), "summary": summary}
    return {"season": season, "name": config["name"], "formal_games": len(list((root / "data/games" / season).glob("*/dossier.json"))),
            "scope": config["scope_file"], "rules": config["formal_rules_file"], "reports": reports,
            "note": "文件存在和进度数量不等于逐字段人工确认；证据、未知和用户意见分别核对。"}


def ensure_retained_seasons(seasons: list[str]) -> None:
    from website.api.publisher import _connect
    with _connect() as conn:
        rows = conn.execute("SELECT DISTINCT g.season FROM games g JOIN active_release a ON a.release_id=g.release_id").fetchall()
    missing = {row["season"] for row in rows} - set(seasons)
    if missing:
        raise ValueError("当前活动批次的赛季缺少本地正式档案，停止替换：" + ", ".join(sorted(missing)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "plan", "run"))
    parser.add_argument("--season", choices=season_codes(ROOT), required=True)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--auth", choices=("none", "cookies"))
    parser.add_argument("--cookies-file", default=".secrets/bilibili.cookies.txt")
    parser.add_argument("--bvid", help="S21指定入库媒体或S22指定修订对局")
    parser.add_argument("--photos", action="store_true", help="publish时重建现有照片清单，随后须重启API")
    parser.add_argument("--full-season", action="store_true", help="显式运行review整季结构检查/生成，非AI逐项复核")
    args = parser.parse_args()
    if args.full_season and args.stage != "review":
        parser.error("--full-season只用于--stage review")
    if args.action == "status":
        print(json.dumps(status(args.season), ensure_ascii=False, indent=2))
        return 0
    if args.action == "run" and not args.stage:
        parser.error("run必须指定一个--stage；先用plan预览，每个阶段独立执行")
    auth = args.auth or ("cookies" if (ROOT / args.cookies_file).is_file() else "none")
    stages = [args.stage] if args.stage else list(STAGES)
    plans = []
    for stage in stages:
        try:
            jobs = stage_commands(stage, args.season, auth=auth, cookies=args.cookies_file,
                                  bvid=args.bvid, photos=args.photos, full_season=args.full_season)
            plans.append({"stage": stage, "commands": jobs})
        except ValueError as error:
            if args.action == "run":
                raise
            plans.append({"stage": stage, "manual": str(error), "commands": []})
    if args.action == "plan":
        print("局部事实复核按docs/02第六步执行；review --full-season仅运行整季结构检查/生成。")
        for plan in plans:
            print(f"\n[{plan['stage']}]")
            if "manual" in plan:
                print(plan["manual"])
            for job in plan["commands"]:
                print("& " + subprocess.list2cmdline(job))
        return 0
    os.chdir(ROOT)
    if args.stage == "publish":
        ensure_retained_seasons(formal_seasons())
    for job in plans[0]["commands"]:
        print("& " + subprocess.list2cmdline(job), flush=True)
        subprocess.run(job, cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(ROOT))
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
