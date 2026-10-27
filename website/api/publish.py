"""CLI for preparing immutable Masters website releases."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import traceback
import uuid

import psycopg

from . import publisher


def _preflight(root: Path, season: str | list[str], sample: str | None) -> dict:
    seasons = publisher.publication_seasons(season)
    entries, source_hash, rules_hash = publisher.load_release(root, seasons, sample)
    names = {seat["name"] for item in entries for seat in item["dossier"].get("seats", [])}
    identities = {
        name: str(uuid.uuid5(publisher.PERSON_NAMESPACE, name.strip().casefold())) for name in names
    }
    rounds = ballots = votes = seats = 0
    for item in entries:
        doc = publisher._public_game(item["dossier"], item["voting"], item["endgame"], item["audit"],
                                     item["board"], identities)
        rounds += doc["round_count"]
        ballots += doc["ballot_count"]
        votes += sum(len(ballot["votes"]) for ballot in doc["voting"]["ballots"])
        seats += len(doc["seats"])
    return {"valid": True, "seasons": seasons, "game_count": len(entries), "seat_count": seats,
            "round_count": rounds, "ballot_count": ballots, "vote_count": votes,
            "source_hash": source_hash, "rules_hash": rules_hash,
            "release_id": publisher._release_id("_".join(seasons), source_hash, rules_hash)}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path,
                        default=Path(os.environ.get("MASTERS_SOURCE_ROOT", publisher.DEFAULT_SOURCE_ROOT)))
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--season", default=None)
    selection.add_argument("--seasons", nargs="+", help="publish all selected seasons in one atomic release")
    parser.add_argument("--sample", metavar="BVID", help="publish only the selected sample video")
    parser.add_argument("--list", action="store_true", help="list current in-scope game IDs")
    parser.add_argument("--activate", metavar="RELEASE", help="activate an existing immutable release")
    parser.add_argument("--check", action="store_true", help="validate source and publication data without writes")
    parser.add_argument("--debug", action="store_true", help="print a local traceback on command failure")
    args = parser.parse_args(argv)
    args.season = args.seasons or args.season or "S22"
    if args.sample and not re.fullmatch(r"BV[0-9A-Za-z]{10}", args.sample):
        parser.error("--sample expects a valid BVID")
    if args.activate and (args.sample or args.check or args.list):
        parser.error("--activate cannot be combined with source selection options")
    try:
        if args.list:
            result = {"season": args.season, "items": publisher.list_games(args.root, args.season)}
        elif args.activate:
            result = publisher.activate(args.activate)
        elif args.check:
            result = _preflight(args.root, args.season, args.sample)
        else:
            result = publisher.publish(args.root, args.season, args.sample)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except publisher.PublishError as exc:
        print(json.dumps({"error": "publication_failed", "message": str(exc)}, ensure_ascii=False))
        return 2
    except psycopg.Error:
        print(json.dumps({"error": "database_error", "message": "数据库操作失败；请检查连接和 schema 权限。"},
                         ensure_ascii=False))
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"error": "source_error", "message": "源数据或配置无法读取。"}, ensure_ascii=False))
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"error": "internal_error", "message": f"内部错误类型：{type(exc).__name__}；可本机加 --debug 检查。"},
                         ensure_ascii=False))
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
