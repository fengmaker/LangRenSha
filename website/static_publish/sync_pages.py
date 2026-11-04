"""Incrementally build, push the accepted site, and verify its Pages deployment."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from website.static_publish.build_static import build, tree_hash, write_json

ORIGIN = "https://github.com/fengmaker/langrensha-site.git"
REPOSITORY = "https://github.com/fengmaker/langrensha-site"
WEB_URL = "https://fengmaker.github.io/langrensha-site"
API_URL = "https://api.github.com/repos/fengmaker/langrensha-site"


@contextmanager
def published_api(api_url: str | None):
    """Use an explicit API, or own a temporary read-only API for this sync."""
    if api_url:
        yield api_url
        return
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    log_dir = ROOT / "tmp/pages-build"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"sync-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.log"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "website.api.app:app", "--host",
                                    "127.0.0.1", "--port", str(port)], cwd=ROOT,
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Temporary API failed to start; see {log_path}")
                try:
                    with urlopen(url + "/health", timeout=0.5) as response:
                        if json.load(response).get("status") == "ok":
                            break
                except OSError:
                    pass
                time.sleep(0.1)
            else:
                raise TimeoutError(f"Temporary API did not become ready; see {log_path}")
            print(f"Using temporary published API: {url}", flush=True)
            yield url
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repository), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout.rstrip("\r\n")


def _ordinary_directory(path: Path) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError(f"Generated paths cannot be links: {path}")


def sync_tree(source: Path, destination: Path) -> dict[str, int]:
    """Mirror this dedicated site tree, writing only changed files."""
    source = source.resolve()
    _ordinary_directory(destination)
    destination.mkdir(parents=True, exist_ok=True)
    _ordinary_directory(destination)
    target = destination.resolve()
    if target.name != "site" or target.parent == target:
        raise ValueError("Published files must be in the repository's dedicated site/ directory")
    existing = {}
    for path in target.rglob("*"):
        _ordinary_directory(path)
        if path.is_file():
            existing[path.relative_to(target).as_posix()] = path
    counts = {"written": 0, "unchanged": 0, "removed": 0}
    for path in sorted(source.rglob("*")):
        _ordinary_directory(path)
        if not path.is_file():
            continue
        name = path.relative_to(source).as_posix()
        old = existing.pop(name, None)
        if (old is not None and old.stat().st_size == path.stat().st_size
                and hashlib.sha256(old.read_bytes()).digest() == hashlib.sha256(path.read_bytes()).digest()):
            counts["unchanged"] += 1
            continue
        output = target / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, output)
        counts["written"] += 1
    for path in existing.values():
        path.unlink()
        counts["removed"] += 1
    for path in sorted(target.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return counts


def get_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "LangRenSha-Pages-sync"})
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def wait_for_deployment(commit: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = get_json(API_URL + f"/actions/workflows/deploy-pages.yml/runs?head_sha={commit}&branch=main&per_page=5")
        runs = [run for run in result["workflow_runs"] if run["head_sha"] == commit]
        if runs:
            run = runs[0]
            if run["status"] == "completed":
                if run["conclusion"] != "success":
                    raise RuntimeError(f"Pages deployment {run['conclusion']}: {run['html_url']}")
                return {"id": run["id"], "url": run["html_url"], "conclusion": run["conclusion"]}
        time.sleep(10)
    raise TimeoutError(f"Pages deployment is still pending; inspect {REPOSITORY}/actions")


def verify_online(ready: Path, manifest: dict) -> dict:
    actual = get_json(WEB_URL + "/data/manifest.json?build_id=" + quote(manifest["build_id"], safe=""))
    if actual != manifest:
        raise RuntimeError("Online manifest does not match the accepted build")
    release = ready / "data/releases" / manifest["snapshot_id"]
    games = json.loads((release / "games/index.json").read_text(encoding="utf-8"))["items"]
    routes = ["/"]
    for season in manifest["seasons"]:
        game = next(item for item in games if item["season"] == season["id"])
        routes.append("/games/" + quote(game["id"], safe="") + "/")
    for route in routes:
        with urlopen(WEB_URL + route, timeout=45) as response:
            if response.status != 200 or b"<main" not in response.read():
                raise RuntimeError(f"Online route failed: {route}")
    return {"state": "passed", "manifest_matches": True, "routes": routes}


def publish_site(ready: Path, receipt: dict, repository: Path, *, timeout: int = 1200) -> dict:
    ready = ready.resolve()
    repository = repository.absolute()
    _ordinary_directory(repository)
    repository = repository.resolve()
    if git(repository, "rev-parse", "--show-toplevel").replace("\\", "/").lower() != repository.as_posix().lower():
        raise ValueError("Publish directory must be a repository root")
    if git(repository, "remote", "get-url", "origin") != ORIGIN or git(repository, "branch", "--show-current") != "main":
        raise ValueError("Publishing requires the configured langrensha-site origin and main branch")
    templates = {".github/workflows/deploy-pages.yml": ROOT / "website/static_publish/templates/deploy-pages.yml",
                 "README.md": ROOT / "website/static_publish/templates/published-README.md"}
    dirty = git(repository, "status", "--porcelain=v1", "--untracked-files=all")
    for row in dirty.splitlines():
        name = row[3:]
        if name.startswith("site/"):
            continue
        path = repository / name
        if name not in templates or not path.is_file() or path.read_bytes() != templates[name].read_bytes():
            raise RuntimeError("Publication repository has independent edits; preserve them before syncing")
    manifest = json.loads((ready / "data/manifest.json").read_text(encoding="utf-8"))
    if (receipt.get("state") != "passed" or receipt.get("mode") != "complete"
            or manifest.get("complete") is not True or manifest.get("base_path") != "/langrensha-site"
            or manifest.get("build_id") != receipt.get("build_id")):
        raise ValueError("Only a complete accepted build can be published")
    if tree_hash(ready) != receipt.get("artifact_hash"):
        raise ValueError("Accepted build changed before publication")
    target = repository / "site"
    _ordinary_directory(target)
    if target.resolve() != repository / "site":
        raise ValueError("Published site must stay inside the publication repository")
    record_path = ready.parent / "publication.json"
    record = {"repository": REPOSITORY, "branch": "main", "build_id": manifest["build_id"],
              "artifact_hash": receipt["artifact_hash"], "web_url": WEB_URL + "/", "state": "preparing"}
    try:
        print("Synchronizing accepted files to publication repository", flush=True)
        record["files"] = sync_tree(ready, target)
        if tree_hash(target) != receipt["artifact_hash"]:
            raise RuntimeError("Published working tree does not match the accepted artifact")
        for name, source in templates.items():
            target_file = repository / name
            for parent in target_file.relative_to(repository).parents:
                _ordinary_directory(repository / parent)
            _ordinary_directory(target_file)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_bytes(source.read_bytes())
        git(repository, "add", "--", "site", *templates)
        staged = git(repository, "diff", "--cached", "--name-only").splitlines()
        if any(not name.startswith("site/") and name not in templates for name in staged):
            raise RuntimeError("Refusing to commit unrelated staged files")
        changed = bool(staged)
        if changed:
            git(repository, "-c", "maintenance.auto=false", "commit", "--quiet", "-m", f"Update static archive {manifest['build_id']}")
        record["commit"] = git(repository, "rev-parse", "HEAD")
        record["state"] = "pushing"
        write_json(record_path, record)
        print(f"Pushing publication main {record['commit'][:12]}", flush=True)
        git(repository, "push", "origin", "main")
        record["state"] = "deploying"
        write_json(record_path, record)
        print("Waiting for automatic Pages deployment", flush=True)
        record["workflow"] = wait_for_deployment(record["commit"], timeout)
        record["online"] = verify_online(ready, manifest)
        record.update(state="passed", checked_at=datetime.now(timezone.utc).isoformat())
        write_json(record_path, record)
        print(f"Published {manifest['build_id']}: {WEB_URL}/", flush=True)
        return record
    except BaseException as error:
        record.update(state="failed", error=str(error))
        write_json(record_path, record)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", help="Reuse this API instead of starting an isolated temporary read-only API")
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/pages-preview/langrensha-site")
    parser.add_argument("--publish-dir", type=Path, default=ROOT.parent / "langrensha-site")
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--full", action="store_true", help="Fetch and verify every API response; unchanged frontend assets can still be reused")
    parser.add_argument("--skip-browser-check", action="store_true", help="Skip only browser acceptance; structure and API checks still run")
    args = parser.parse_args()
    try:
        with published_api(args.api_url) as api_url:
            receipt = build(api_url, "/langrensha-site", args.output, browser_channel=args.browser_channel,
                            incremental=not args.full, skip_browser_check=args.skip_browser_check)
        publish_site(args.output, receipt, args.publish_dir)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
