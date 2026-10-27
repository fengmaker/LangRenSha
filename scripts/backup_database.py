"""Back up the whole database and record every retained season's source baseline."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from season_config import season_codes
from website.api.publisher import _connect, load_publication
from website.backup import binary, fingerprint


def backup(output: Path, seasons: list[str]) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    sources = {}
    for season in seasons:
        entries, source_hash, rules_hash = load_publication(ROOT, season)
        sources[season] = {
            "games": len(entries), "source_hash": source_hash, "rules_hash": rules_hash,
            "files": {item["dossier"]["slug"]: item["source_hashes"] for item in entries},
        }
    with _connect() as conn:
        active = conn.execute("SELECT release_id FROM active_release WHERE singleton=true").fetchone()
        baseline = fingerprint(conn)
        counts = conn.execute(
            "SELECT s.code AS season,count(*) AS games FROM jcms.games g "
            "JOIN jcms.seasons s ON s.id=g.season_id GROUP BY s.code ORDER BY s.code"
        ).fetchall()
        env = {**os.environ, "PGHOST": conn.info.host, "PGPORT": str(conn.info.port),
               "PGUSER": conn.info.user, "PGPASSWORD": conn.info.password,
               "PGDATABASE": conn.info.dbname, "PGCONNECT_TIMEOUT": "10"}
        conn.rollback()
        dump = output / "database.dump"
        for command in (
            [binary("pg_dump"), "--format=custom", "--no-owner", "--no-privileges", "--file", str(dump)],
            [binary("pg_restore"), "--list", str(dump)],
        ):
            result = subprocess.run(command, env=env, capture_output=True,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                raise RuntimeError("整库备份或备份目录校验失败；未进行正式写入")
    with dump.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    receipt = {
        "created_at": datetime.now(timezone.utc).isoformat(), "backup": str(dump),
        "bytes": dump.stat().st_size, "sha256": digest, "archive_catalog_valid": True,
        "restore_verified": False, "active_release": active, "formal_counts": counts,
        "web_content_sha256": baseline, "seasons": sources,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="新的备份目录，不能覆盖已有目录")
    parser.add_argument("--seasons", nargs="+", help="记录源文件基线的季；默认全部已有正式档案的注册季")
    args = parser.parse_args()
    seasons = args.seasons or [season for season in season_codes(ROOT)
                               if any((ROOT / "data/games" / season).glob("*/dossier.json"))]
    output = args.output or ROOT / "data/backups" / datetime.now(timezone.utc).strftime("workflow-%Y%m%dT%H%M%S")
    receipt = backup(output.resolve(), seasons)
    print(json.dumps({key: value for key, value in receipt.items() if key != "seasons"}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
