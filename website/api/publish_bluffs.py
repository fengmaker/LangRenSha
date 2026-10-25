"""Validate or publish a reviewed season bluff dataset to masters_web."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback

import psycopg

from . import bluff_store


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="S22")
    parser.add_argument("--path", type=Path, help="review JSON; defaults to website/assets/bluffs/<season>.json")
    parser.add_argument("--check", action="store_true", help="validate against active DB snapshots without writes")
    parser.add_argument("--debug", action="store_true", help="print a local traceback on command failure")
    args = parser.parse_args(argv)
    try:
        result = bluff_store.publish_review(args.season, args.path, check=args.check)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except bluff_store.BluffReviewError as exc:
        print(json.dumps({"error": "bluff_review_failed", "message": str(exc)}, ensure_ascii=False))
        return 2
    except psycopg.Error:
        print(json.dumps({"error": "database_error", "message": "数据库操作失败；请检查连接和 schema 权限。"},
                         ensure_ascii=False))
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
