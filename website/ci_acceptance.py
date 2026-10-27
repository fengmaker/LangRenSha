"""Disposable GitHub Actions acceptance. Never point this at a real database."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import signal
import shutil
import re
import sys
import time
from urllib.parse import urlparse
from urllib.request import urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "website/artifacts/ci"
EXPECTED = {"S22": 148, "S23": 75}


def require_disposable_database() -> None:
    url = urlparse(os.environ.get("DATABASE_URL", ""))
    if (os.environ.get("CI") != "true" or url.hostname != "127.0.0.1"
            or url.port != 5432 or url.path != "/masters_ci" or url.username != "masters_ci"):
        raise RuntimeError("Refusing: requires CI=true and the disposable loopback masters_ci database")


def require_test_execution(path: Path, required: set[str]) -> int:
    cases = ET.parse(path).findall(".//testcase")
    if not cases or any(case.find(tag) is not None for case in cases
                        for tag in ("skipped", "failure", "error")):
        raise RuntimeError("Tests must actually execute: empty, skipped, failed or errored JUnit result")
    names = {case.attrib["name"] for case in cases}
    if not required.issubset(names):
        raise RuntimeError("Required database integration tests did not run")
    return len(cases)


def command(label: str, args: list[str], env: dict | None = None, timeout: int = 600) -> None:
    print(f"Running {label}", flush=True)
    with (OUT / f"{label}.log").open("w", encoding="utf-8") as log:
        subprocess.run(args, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def ready(url: str, process: subprocess.Popen, timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Server exited before readiness; inspect server log")
        try:
            with urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return
        except (OSError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError("Server readiness deadline exceeded")


def verify_reader(reader_url: str) -> None:
    import psycopg
    with psycopg.connect(reader_url) as conn:
        assert conn.execute("SELECT current_user").fetchone()[0] == "masters_web_reader"
        assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        assert not any(conn.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
                                    "FROM pg_roles WHERE rolname=current_user").fetchone())
        rows = conn.execute("SELECT g.season,count(*) FROM masters_web.games g "
                            "JOIN masters_web.active_release a ON a.release_id=g.release_id "
                            "GROUP BY g.season").fetchall()
        assert dict(rows) == EXPECTED
        rows = conn.execute("SELECT b.season FROM masters_web.active_bluff_reviews b "
                            "JOIN masters_web.active_release a ON a.release_id=b.release_id").fetchall()
        assert sorted(row[0] for row in rows) == sorted(EXPECTED)
        # Read-only defaults can be overridden. Verify actual grants, not just that setting.
        conn.rollback()
        conn.execute("SET TRANSACTION READ WRITE")
        try:
            conn.execute("UPDATE masters_web.active_release SET singleton=singleton WHERE false")
        except psycopg.errors.InsufficientPrivilege:
            conn.rollback()
        else:
            conn.rollback()
            raise RuntimeError("Reader can UPDATE publication tables")
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='masters_web'").fetchall()
        assert tables
        for (table,) in tables:
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                assert not conn.execute("SELECT has_table_privilege(current_user,%s,%s)",
                                        (f"masters_web.{table}", privilege)).fetchone()[0]
        assert not conn.execute("SELECT has_schema_privilege(current_user,'masters_web','CREATE')").fetchone()[0]



def stage_artifacts(source: Path, destination: Path) -> None:
    """Only copy allowlisted sanitized evidence to the directory Actions uploads."""
    destination.mkdir(parents=True, exist_ok=True)
    for path in [*source.glob("*.log"), *source.glob("*.json")]:
        if path.is_symlink():
            raise RuntimeError("Refusing artifact symlink")
        value = path.read_text(encoding="utf-8", errors="replace")
        value = re.sub(r"postgres(?:ql)?://[^\s\"']+", "[DATABASE_URL REDACTED]", value)
        owner_password = urlparse(os.environ.get("DATABASE_URL", "")).password
        if owner_password:
            value = value.replace(owner_password, "[REDACTED]")
        for name in ("MASTERS_READER_PASSWORD", "DATABASE_URL"):
            if os.environ.get(name):
                value = value.replace(os.environ[name], "[REDACTED]")
        value = value.replace(str(ROOT), "[WORKSPACE]")
        (destination / path.name).write_text(value, encoding="utf-8")
    for path in (source / "screenshots").glob("*.png"):
        if path.is_symlink():
            raise RuntimeError("Refusing screenshot symlink")
        (destination / "screenshots").mkdir(exist_ok=True)
        shutil.copyfile(path, destination / "screenshots" / path.name)

def main() -> None:
    require_disposable_database()
    OUT.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    processes, logs = [], []
    try:
        command("preflight", [py, "-m", "website.api.publish", "--seasons", "S22", "S23", "--check"])
        # The existing publisher applies website/api/schema.sql; no JCMS migrations are used.
        command("publish", [py, "-m", "website.api.publish", "--seasons", "S22", "S23"])
        for season in EXPECTED:
            command(f"bluffs-check-{season}", [py, "-m", "website.api.publish_bluffs", "--season", season, "--check"])
            command(f"bluffs-{season}", [py, "-m", "website.api.publish_bluffs", "--season", season])
        junit = OUT / "tests.xml"
        command("tests", [py, "-m", "pytest", "website/tests", "-q", "--tb=short", f"--junitxml={junit}"])
        executed = require_test_execution(junit, {
            "test_publish_failure_does_not_change_active_release",
            "test_publish_is_idempotent_and_can_leave_active_pointer_unchanged",
            "test_read_only_contract_filtering_pagination_and_details",
            "test_published_bluff_data_does_not_depend_on_local_review_files",
        })
        command("reader-setup", [py, "-m", "website.grant_reader"])
        reader_url = "postgresql://masters_web_reader:" + os.environ["MASTERS_READER_PASSWORD"] + "@127.0.0.1:5432/masters_ci"
        verify_reader(reader_url)
        reader_env = {**os.environ, "DATABASE_URL": reader_url}
        for label, args, url in (
            ("api", [py, "-m", "uvicorn", "website.api.app:app", "--host", "127.0.0.1", "--port", "8000"], "http://127.0.0.1:8000/health"),
            ("web", ["npm", "run", "start", "--prefix", "website/web", "--", "--hostname", "127.0.0.1"], "http://127.0.0.1:3000"),
        ):
            if label == "web":
                command("build", ["npm", "run", "build", "--prefix", "website/web"], env=reader_env)
                command("typecheck", ["npm", "run", "typecheck", "--prefix", "website/web"])
            log = (OUT / f"{label}.log").open("w", encoding="utf-8")
            logs.append(log)
            process = subprocess.Popen(args, cwd=ROOT, env=reader_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            processes.append(process)
            ready(url, process)
        command("acceptance", [py, "-m", "website.check_publication", "--seasons", "S22", "S23",
                              "--browser-channel", "chromium", "--screenshots", str(OUT / "screenshots"),
                              "--output", str(OUT / "acceptance.json")], env=reader_env, timeout=900)
        report = json.loads((OUT / "acceptance.json").read_text())
        assert report["api"]["paginated_games"] == report["api"]["source_games_matched"] == 223
        assert report["browser"]["page_count"] >= 36
        assert report["api"]["photos"]["api_assets_checked"] > 0
        for season in EXPECTED:
            assert report["api"]["photos"]["leaderboard_photos"][season] > 0
            assert report["api"]["bluff_bindings"][season]["inference_version"]
        (OUT / "result.json").write_text(json.dumps({"state": "passed", "games": 223,
            "tests_executed_without_skips": executed, "reader_permissions_verified": True,
            "browser_pages": report["browser"]["page_count"]}, indent=2) + "\n")
        print("223-game database/API/browser acceptance passed", flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is not None:
                continue
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        for log in logs:
            log.close()
        stage_artifacts(OUT, ROOT / "website/artifacts/ci-upload")


if __name__ == "__main__":
    main()
