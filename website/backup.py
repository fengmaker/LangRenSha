"""Back up only masters_web and optionally restore into a disposable database."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

import psycopg
from psycopg import sql

from website.api.publisher import _connect

ROOT = Path(__file__).resolve().parents[1]


def binary(name: str) -> str:
    installed = shutil.which(name)
    if installed:
        return installed
    local = ROOT / ".tools" / "postgresql" / "pgsql" / "bin" / (name + ".exe")
    if local.is_file():
        return str(local)
    raise RuntimeError(f"找不到 {name}，请安装与数据库兼容的 PostgreSQL 客户端。")


def fingerprint(conn) -> str:
    content = []
    tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='masters_web' AND table_type='BASE TABLE' ORDER BY table_name").fetchall()
    for entry in tables:
        table = entry["table_name"]
        rows = conn.execute(sql.SQL("SELECT row_to_json(t)::text AS value FROM masters_web.{} t ORDER BY row_to_json(t)::text").format(sql.Identifier(table))).fetchall()
        content.append([table, [row["value"] for row in rows]])
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-restore", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    destination = args.output or ROOT / "website" / "artifacts" / ("masters-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + ".dump")
    destination = destination.resolve()
    if destination.exists():
        raise SystemExit("备份目标已存在，停止以避免覆盖。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        before = fingerprint(conn)
        env = {**os.environ, "PGHOST": conn.info.host, "PGPORT": str(conn.info.port),
               "PGUSER": conn.info.user, "PGPASSWORD": conn.info.password,
               "PGDATABASE": conn.info.dbname, "PGCONNECT_TIMEOUT": "10"}
        conn.rollback()
        result = subprocess.run([binary("pg_dump"), "--schema=masters_web", "--format=custom",
                                 "--no-owner", "--no-privileges", "--file", str(destination)],
                                env=env, capture_output=True)
        if result.returncode:
            raise SystemExit("发布库备份失败，请检查 PostgreSQL 客户端版本和连接权限。")
        report = {"backup": str(destination), "bytes": destination.stat().st_size,
                  "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                  "restore_verified": False}
        if args.verify_restore:
            verification_db = "masters_verify_" + uuid.uuid4().hex[:16]
            # The only dropped database is this newly-created random verification target.
            conn.autocommit = True
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(verification_db)))
            try:
                restored = subprocess.run([binary("pg_restore"), "--dbname", verification_db,
                                           "--no-owner", "--no-privileges", "--exit-on-error", str(destination)],
                                          env=env, capture_output=True)
                if restored.returncode:
                    raise RuntimeError("备份恢复失败。")
                with psycopg.connect(host=env["PGHOST"], port=env["PGPORT"], user=env["PGUSER"],
                                     password=env["PGPASSWORD"], dbname=verification_db,
                                     row_factory=psycopg.rows.dict_row) as restored_conn:
                    after = fingerprint(restored_conn)
                if before != after:
                    raise RuntimeError("恢复后的发布库与备份前内容不同；请检查是否有并发发布。")
                report["restore_verified"] = True
                report["content_sha256"] = after
            finally:
                conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(verification_db)))
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
