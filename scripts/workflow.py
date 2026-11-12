"""Collection, current-batch review, final data and local export."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from season_config import load_season, season_codes

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("collect", "process", "review", "finalize", "export", "verify")


def formal_seasons(root: Path = ROOT) -> list[str]:
    return [s for s in season_codes(root) if any((root / "data/games" / s).glob("*/game.json"))]


def stage_commands(stage: str, season: str, *, root: Path = ROOT,
                   bvid: str | None = None, review_export: str | None = None,
                   note_revisions: str | None = None) -> list[list[str]]:
    load_season(season, root)
    python = str(root / ".venv/Scripts/python.exe")
    selected = ["--bvid", bvid] if bvid else []
    if stage == "collect":
        return [[python, "scripts/update_incremental.py", "--season", season]]
    if stage == "process":
        return [[python, "scripts/analyze_incremental.py", "--season", season, *selected]]
    if stage == "review":
        return [[python, "scripts/analyze_incremental.py", "--season", season,
                 "--validate-candidates", *selected]]
    if stage == "finalize":
        if not review_export:
            raise ValueError("finalize需要--review-export；先完成当前批次人工复核")
        revisions = ["--note-revisions", note_revisions] if note_revisions else []
        return [[python, "scripts/apply_incremental_review.py", review_export,
                 "--season", season, "--apply", *revisions]]
    if stage in {"export", "verify"}:
        return [[python, "website/static_publish/export_static.py",
                 *(["--check"] if stage == "verify" else [])]]
    raise ValueError(f"Unknown workflow stage: {stage}")


def status(season: str, root: Path = ROOT) -> dict:
    config = load_season(season, root)
    path = root / f"data/reports/{season}/incremental/state.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"items": {}}
    pending = [item for item in state["items"].values()
               if not item.get("applied") and not item.get("formal_dossier")]
    return {"season": season, "name": config["name"],
            "formal_games": len(list((root / "data/games" / season).glob("*/game.json"))),
            "pending": len(pending),
            "analysis": dict(Counter(item.get("analysis", "pending") for item in pending))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "plan", "run"))
    parser.add_argument("--season", choices=season_codes(ROOT), required=True)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--bvid")
    parser.add_argument("--review-export")
    parser.add_argument("--note-revisions")
    args = parser.parse_args()
    if args.action == "status":
        print(json.dumps(status(args.season), ensure_ascii=False, indent=2))
        return 0
    if args.action == "run" and not args.stage:
        parser.error("run必须指定--stage")
    for stage in [args.stage] if args.stage else STAGES:
        try:
            jobs = stage_commands(stage, args.season, bvid=args.bvid,
                                  review_export=args.review_export, note_revisions=args.note_revisions)
        except ValueError as error:
            if args.action == "run":
                raise
            print(f"[{stage}] {error}")
            continue
        for job in jobs:
            print("& " + subprocess.list2cmdline(job), flush=True)
            if args.action == "run":
                subprocess.run(job, cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
