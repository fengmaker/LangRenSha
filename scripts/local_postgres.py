"""Project-local PostgreSQL for Windows; no service or global PATH changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "18.6-5"
URL = f"https://get.enterprisedb.com/postgresql/postgresql-{VERSION}-windows-x64-binaries.zip"
SHA256 = "e2246ba91d22345bc3d017586c09ede52d9df180b1eeb480f050445f1cad84e2"
BIN = ROOT / ".tools" / "postgresql" / "pgsql" / "bin"
DATA = ROOT / ".local" / "postgresql"
CONFIG = ROOT / ".secrets" / "database.json"


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    # Do not print credential-bearing config or environment variables.
    return subprocess.run(args, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kwargs)


def install() -> None:
    if (BIN / "postgres.exe").exists():
        print("PostgreSQL 二进制已存在")
        return
    archive = ROOT / ".cache" / "downloads" / f"postgresql-{VERSION}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        print(f"下载 PostgreSQL {VERSION} 官方发行二进制", flush=True)
        with urllib.request.urlopen(URL, timeout=40) as response, archive.with_suffix(".part").open("wb") as out:
            total = 0
            last_report = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > 600 * 1024 * 1024:
                    raise RuntimeError("发行包超过下载上限")
                out.write(block)
                if total - last_report >= 50 * 1024 * 1024:
                    print(f"已下载 {total // (1024 * 1024)} MiB", flush=True)
                    last_report = total
        archive.with_suffix(".part").replace(archive)
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != SHA256:
        raise RuntimeError("发行包 SHA-256 与发布方提供值不同；未执行或解压")
    destination = ROOT / ".tools" / "postgresql"
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            parts = PurePosixPath(item.filename).parts
            if ".." in parts or not parts or parts[0] != "pgsql":
                continue
            # Exclude pgAdmin, debugging symbols, docs and installer extras.
            if len(parts) > 1 and parts[1] in {"bin", "lib", "share"} and not item.filename.endswith(".pdb"):
                target = (destination / Path(*parts)).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise RuntimeError("归档路径超出项目目录")
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(item) as src, target.open("wb") as out:
                        while block := src.read(1024 * 1024):
                            out.write(block)
    (destination / "download-manifest.json").write_text(json.dumps({
        "version": VERSION, "source": URL, "sha256": actual,
        "checksum_source": "https://github.com/EnterpriseDB/edb-installers/issues/733",
    }, indent=2) + "\n", encoding="utf-8")
    # Delete only the exact verified archive within this workspace.
    if archive.resolve().is_relative_to(ROOT.resolve()):
        archive.unlink()
    print("二进制校验并解压完成；已移除下载 ZIP", flush=True)


def configuration(port: int) -> dict:
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    data = {"host": "127.0.0.1", "port": port, "user": "jcms",
            "password": secrets.token_urlsafe(32), "dbname": "jcms", "schema": "jcms"}
    CONFIG.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "start", "stop", "status"])
    parser.add_argument("--port", type=int, default=55432)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("此便携启动入口仅适用于 Windows；其他系统可使用现有 PostgreSQL")
    if args.action == "setup":
        install()
    if not (BIN / "pg_ctl.exe").exists():
        raise SystemExit("请先运行 local_postgres.py setup")
    config = configuration(args.port)
    if args.action == "setup" and not (DATA / "PG_VERSION").exists():
        password_file = ROOT / ".secrets" / "pg-init-password.txt"
        password_file.write_text(config["password"] + "\n", encoding="utf-8")
        DATA.parent.mkdir(parents=True, exist_ok=True)
        try:
            run([str(BIN / "initdb.exe"), "-D", str(DATA), "-U", config["user"],
                 "--pwfile", str(password_file), "--auth-host=scram-sha-256",
                 "--auth-local=trust", "--encoding=UTF8", "--locale=C"])
        finally:
            password_file.unlink(missing_ok=True)
    if args.action in {"setup", "start"}:
        status = subprocess.run([str(BIN / "pg_ctl.exe"), "status", "-D", str(DATA)],
                                capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if status.returncode != 0:
            run([str(BIN / "pg_ctl.exe"), "start", "-D", str(DATA), "-l", str(DATA.parent / "postgresql.log"),
                 "-o", f"-h 127.0.0.1 -p {config['port']} -c max_connections=30 -c shared_buffers=64MB", "-w"])
        if args.action == "setup":
            env = os.environ.copy()
            env["PGPASSWORD"] = config["password"]
            result = run([str(BIN / "psql.exe"), "-h", config["host"], "-p", str(config["port"]),
                          "-U", config["user"], "-d", "postgres", "-tAc",
                          "SELECT 1 FROM pg_database WHERE datname='jcms'"], env=env, capture_output=True)
            if result.stdout.strip() != b"1":
                run([str(BIN / "createdb.exe"), "-h", config["host"], "-p", str(config["port"]),
                     "-U", config["user"], config["dbname"]], env=env)
        print(f"开发数据库可用：{config['host']}:{config['port']}/{config['dbname']}；凭据仅存 .secrets/database.json")
    elif args.action == "stop":
        run([str(BIN / "pg_ctl.exe"), "stop", "-D", str(DATA), "-m", "fast", "-w"])
    else:
        result = subprocess.run([str(BIN / "pg_ctl.exe"), "status", "-D", str(DATA)],
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
