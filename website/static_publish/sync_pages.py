"""Explicitly build, publish, and verify the static Pages archive."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
from urllib.parse import quote
from urllib.request import Request, getproxies, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from website.static_publish.build_static import build, tree_hash

ORIGIN = "https://github.com/fengmaker/langrensha-site.git"
REPOSITORY = "https://github.com/fengmaker/langrensha-site"
WEB_URL = "https://fengmaker.github.io/langrensha-site"
GITHUB_API = "https://api.github.com/repos/fengmaker/langrensha-site"
PUBLICATION_TIMEZONE = timezone(timedelta(hours=8))


def _ordinary_directory(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (stat.S_ISLNK(info.st_mode)
            or os.name == "nt" and info.st_reparse_tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)):
        raise ValueError(f"Generated paths cannot be links: {path}")
    return info


def sync_tree(source: Path, destination: Path) -> dict[str, int]:
    """Mirror generated files into the publication repository's dedicated site/ directory."""
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"Static source does not exist: {source}")
    _ordinary_directory(destination)
    destination.mkdir(parents=True, exist_ok=True)
    _ordinary_directory(destination)
    target = destination.resolve()
    if target.name != "site" or target.parent == target:
        raise ValueError("Published files must be in the repository's dedicated site/ directory")

    existing: dict[str, Path] = {}
    for path in target.rglob("*"):
        info = _ordinary_directory(path)
        if info is not None and stat.S_ISREG(info.st_mode):
            existing[path.relative_to(target).as_posix()] = path
    counts = {"written": 0, "unchanged": 0, "removed": 0}
    source_paths = sorted(source.rglob("*"))
    for path in source_paths:
        info = _ordinary_directory(path)
        if info is None or not stat.S_ISREG(info.st_mode):
            continue
        relative = path.relative_to(source).as_posix()
        previous = existing.pop(relative, None)
        if (previous is not None and previous.stat().st_size == info.st_size
                and hashlib.sha256(previous.read_bytes()).digest() == hashlib.sha256(path.read_bytes()).digest()):
            counts["unchanged"] += 1
            continue
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, output)
        counts["written"] += 1
    for path in existing.values():
        path.unlink()
        counts["removed"] += 1
    for path in sorted(target.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return counts


def git(repository: Path, *args: str) -> str:
    env = None
    if args[:1] == ("push",):
        proxies = getproxies()
        env = {**os.environ, **{f"{scheme.upper()}_PROXY": value
                                for scheme, value in proxies.items()
                                if scheme in {"http", "https", "all", "no"}}}
    result = subprocess.run(["git", "-C", str(repository), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", env=env)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout.rstrip("\r\n")


def get_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/vnd.github+json",
                                   "User-Agent": "LangRenSha-Pages-sync"})
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def wait_for_deployment(commit: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = get_json(GITHUB_API + f"/actions/workflows/deploy-pages.yml/runs?head_sha={commit}&branch=main&per_page=5")
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
    url = WEB_URL + "/data/manifest.json?build_id=" + quote(manifest["build_id"], safe="")
    request = Request(url, headers={"Cache-Control": "no-cache"})
    with urlopen(request, timeout=45) as response:
        actual = json.load(response)
    if actual != manifest:
        raise RuntimeError("Online manifest does not match the locally built static site")
    release = ready / "data" / "releases" / manifest["snapshot_id"]
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


def _check_repository(repository: Path) -> tuple[Path, dict[str, Path]]:
    _ordinary_directory(repository)
    repository = repository.resolve()
    actual_root = git(repository, "rev-parse", "--show-toplevel").replace("\\", "/").lower()
    if actual_root != repository.as_posix().lower():
        raise ValueError("Publish directory must be a repository root")
    if (git(repository, "remote", "get-url", "origin") != ORIGIN
            or git(repository, "branch", "--show-current") != "main"):
        raise ValueError("Publishing requires the configured langrensha-site origin and main branch")
    templates = {
        ".github/workflows/deploy-pages.yml": ROOT / "website/static_publish/templates/deploy-pages.yml",
        "README.md": ROOT / "website/static_publish/templates/published-README.md",
    }
    dirty = git(repository, "status", "--porcelain=v1", "--untracked-files=all")
    for row in dirty.splitlines():
        name = row[3:]
        if name.startswith("site/"):
            continue
        path = repository / name
        if name not in templates or not path.is_file() or path.read_bytes() != templates[name].read_bytes():
            raise RuntimeError("Publication repository has independent edits; preserve them before syncing")
    target = repository / "site"
    _ordinary_directory(target)
    if target.resolve() != repository / "site":
        raise ValueError("Published site must stay inside the publication repository")
    return target, templates


def publish_site(ready: Path, repository: Path, *, timeout: int = 1800) -> dict:
    ready = Path(ready).absolute()
    _ordinary_directory(ready)
    ready = ready.resolve()
    if not ready.is_relative_to(ROOT / "tmp") or ready == ROOT / "tmp":
        raise ValueError("Static output must be under this workspace's tmp/")
    manifest_path = ready / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("complete") is not True or manifest.get("base_path") != "/langrensha-site":
        raise ValueError("Only a complete static build for /langrensha-site can be published")
    artifact_hash = tree_hash(ready)
    target, templates = _check_repository(Path(repository).absolute())

    print("Synchronizing generated files to the publication repository", flush=True)
    counts = sync_tree(ready, target)
    if tree_hash(target) != artifact_hash:
        raise RuntimeError("Published working tree does not match the local build")
    for name, source in templates.items():
        output = target.parent / name
        for parent in output.relative_to(target.parent).parents:
            if parent != Path("."):
                _ordinary_directory(target.parent / parent)
        _ordinary_directory(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(source.read_bytes())

    git(target.parent, "add", "--", "site", *templates)
    staged = git(target.parent, "diff", "--cached", "--no-renames", "--name-only").splitlines()
    if any(not name.startswith("site/") and name not in templates for name in staged):
        raise RuntimeError("Refusing to commit unrelated staged files")
    changed = bool(staged)
    if changed:
        git(target.parent, "-c", "maintenance.auto=false", "commit", "--quiet", "-m",
            f"Update static archive {manifest['build_id']}")
    commit = git(target.parent, "rev-parse", "HEAD")
    print(f"Pushing publication main {commit[:12]}", flush=True)
    # Retry pushing even when the local tree is unchanged: a previous run can
    # have committed successfully and then failed before the remote push.
    git(target.parent, "push", "origin", "main")
    workflow = wait_for_deployment(commit, timeout)
    online = verify_online(ready, manifest)
    return {"state": "passed", "repository": REPOSITORY, "branch": "main", "build_id": manifest["build_id"],
            "commit": commit, "commit_created": changed, "files": counts,
            "workflow": workflow, "online": online, "url": WEB_URL + "/"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/pages-preview/langrensha-site")
    parser.add_argument("--publish-dir", type=Path, default=ROOT.parent / "langrensha-site")
    parser.add_argument("--check-only", action="store_true", help="Build and validate locally without publishing")
    parser.add_argument("--timeout", type=int, default=1800, help="Maximum wait for Pages deployment")
    args = parser.parse_args(argv)
    try:
        built = build("/langrensha-site", args.output)
        if args.check_only:
            print(json.dumps(built, ensure_ascii=False, indent=2))
            return 0
        published = publish_site(args.output, args.publish_dir, timeout=args.timeout)
        print(json.dumps(published, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
