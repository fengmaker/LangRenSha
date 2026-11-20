"""Explicitly build, publish, and verify the static Pages archive."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from http.client import IncompleteRead
import json
import os
from pathlib import Path
import shutil
from ssl import SSLEOFError
import stat
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, getproxies, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from website.static_publish.build_static import build, timed_stage, write_json
from website.static_publish.cleanup_local import cleanup

ORIGIN = "https://github.com/fengmaker/langrensha-site.git"
REPOSITORY = "https://github.com/fengmaker/langrensha-site"
WEB_URL = "https://fengmaker.github.io/langrensha-site"
GITHUB_API = "https://api.github.com/repos/fengmaker/langrensha-site"
PUBLICATION_TIMEZONE = timezone(timedelta(hours=8))
ONLINE_REQUEST_TIMEOUT = 45
ONLINE_RETRY_DELAYS = (1, 2, 4)


class PublicationCheckError(RuntimeError):
    """A deployment check failed after the publication commit was pushed."""

    def __init__(self, commit: str, stage: str, cause: Exception):
        self.commit = commit
        self.stage = stage
        stage_label = "查询 Pages 部署状态" if stage == "deployment" else "核验线上版本"
        super().__init__(f"已推送 {commit[:12]}，{stage_label}失败：{cause}")


def _ordinary_directory(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (stat.S_ISLNK(info.st_mode)
            or os.name == "nt" and info.st_reparse_tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)):
        raise ValueError(f"Generated paths cannot be links: {path}")
    return info


def _scan_site(root: Path) -> tuple[dict[str, int], list[Path]]:
    files = {}
    directories = []
    for path in root.rglob("*"):
        info = _ordinary_directory(path)
        if info is not None and stat.S_ISREG(info.st_mode):
            files[path.relative_to(root).as_posix()] = info.st_size
        elif info is not None and stat.S_ISDIR(info.st_mode):
            directories.append(path)
    return files, directories


def _file_hash(path: Path) -> bytes:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").digest()


def _site_inventory(root: Path) -> dict[str, tuple[int, bytes]]:
    sizes, _ = _scan_site(root)
    return {name: (size, _file_hash(root / name))
            for name, size in sizes.items()}


def sync_tree(source: Path, destination: Path, *,
              source_files: dict[str, tuple[int, bytes]] | None = None,
              timings: dict[str, float] | None = None) -> dict[str, int]:
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

    if source_files is None:
        source_files = _site_inventory(source)
    if timings is None:
        timings = {}
    with timed_stage(timings, "scan_target"):
        existing, directories = _scan_site(target)
    with timed_stage(timings, "compare_target"):
        changed = []
        for relative, (size, digest) in sorted(source_files.items()):
            if existing.pop(relative, None) != size or _file_hash(target / relative) != digest:
                changed.append(relative)
    with timed_stage(timings, "copy_files"):
        known_directories = {target, *directories}
        for relative in changed:
            path, output = source / relative, target / relative
            _ordinary_directory(path)
            if output.parent not in known_directories:
                output.parent.mkdir(parents=True, exist_ok=True)
                known_directories.add(output.parent)
            shutil.copy2(path, output)
    with timed_stage(timings, "remove_stale_files"):
        for relative in existing:
            (target / relative).unlink()
        for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
    return {"written": len(changed), "unchanged": len(source_files) - len(changed),
            "removed": len(existing)}


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


def _read_online(request: Request, *, deadline: float | None = None) -> bytes:
    url = request.full_url
    for attempt in range(len(ONLINE_RETRY_DELAYS) + 1):
        remaining = ONLINE_REQUEST_TIMEOUT if deadline is None else deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"等待部署超时：{url}")
        try:
            with urlopen(request, timeout=min(ONLINE_REQUEST_TIMEOUT, remaining)) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}：{url}")
                return response.read()
        except (OSError, IncompleteRead) as error:
            if isinstance(error, HTTPError):
                error.close()
                retryable = error.code in {502, 503, 504}
            else:
                reason = error.reason if isinstance(error, URLError) else error
                retryable = isinstance(reason, (SSLEOFError, ConnectionError, TimeoutError, IncompleteRead))
            if not retryable:
                raise
            if attempt < len(ONLINE_RETRY_DELAYS):
                delay = ONLINE_RETRY_DELAYS[attempt]
                if deadline is None or time.monotonic() + delay < deadline:
                    if attempt == 0:
                        print(f"线上请求暂时失败，等待后重试：{url}", flush=True)
                    time.sleep(delay)
                    continue
            raise RuntimeError(f"读取 {url} 失败（已尝试 {attempt + 1} 次）：{error}") from error


def wait_for_deployment(commit: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    url = GITHUB_API + f"/actions/workflows/deploy-pages.yml/runs?head_sha={commit}&branch=main&per_page=5"
    request = Request(url, headers={"Accept": "application/vnd.github+json",
                                   "User-Agent": "LangRenSha-Pages-sync"})
    while time.monotonic() < deadline:
        result = json.loads(_read_online(request, deadline=deadline))
        runs = [run for run in result["workflow_runs"] if run["head_sha"] == commit]
        if runs:
            run = runs[0]
            if run["status"] == "completed":
                if run["conclusion"] != "success":
                    raise RuntimeError(f"Pages deployment {run['conclusion']}: {run['html_url']}")
                return {"id": run["id"], "url": run["html_url"], "conclusion": run["conclusion"]}
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(10, remaining))
    raise TimeoutError(f"Pages deployment is still pending; inspect {REPOSITORY}/actions")


def verify_online(ready: Path, manifest: dict) -> dict:
    url = WEB_URL + "/data/manifest.json?build_id=" + quote(manifest["build_id"], safe="")
    request = Request(url, headers={"Cache-Control": "no-cache"})
    actual = json.loads(_read_online(request))
    if actual != manifest:
        raise RuntimeError("Online manifest does not match the locally built static site")
    release = ready / "data" / "releases" / manifest["snapshot_id"]
    games = json.loads((release / "games/index.json").read_text(encoding="utf-8"))["items"]
    routes = ["/"]
    for season in manifest["seasons"]:
        game = next(item for item in games if item["season"] == season["id"])
        routes.append("/games/" + quote(game["id"], safe="") + "/")
    for route in routes:
        if b"<main" not in _read_online(Request(WEB_URL + route)):
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


def publish_site(ready: Path, repository: Path, *, timeout: int = 1800,
                 timings: dict[str, float] | None = None) -> dict:
    ready = Path(ready).absolute()
    _ordinary_directory(ready)
    ready = ready.resolve()
    if not ready.is_relative_to(ROOT / "tmp") or ready == ROOT / "tmp":
        raise ValueError("Static output must be under this workspace's tmp/")
    manifest_path = ready / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("complete") is not True or manifest.get("base_path") != "/langrensha-site":
        raise ValueError("Only a complete static build for /langrensha-site can be published")
    if timings is None:
        timings = {}
    print("正在同步发布仓库…", flush=True)
    with timed_stage(timings, "publication_preflight"):
        target, templates = _check_repository(Path(repository).absolute())
    with timed_stage(timings, "hash_source"):
        source_files = _site_inventory(ready)

    with timed_stage(timings, "sync_files"):
        counts = sync_tree(ready, target, source_files=source_files, timings=timings)
    with timed_stage(timings, "verify_files"):
        if _site_inventory(target) != source_files:
            raise RuntimeError("Published working tree does not match the local build")

    with timed_stage(timings, "commit"):
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
    # Retry pushing even when the local tree is unchanged: a previous run can
    # have committed successfully and then failed before the remote push.
    with timed_stage(timings, "push"):
        git(target.parent, "push", "origin", "main")
    print(f"已推送 {commit[:12]}，等待 Pages 部署…", flush=True)
    stage = "deployment"
    try:
        with timed_stage(timings, stage):
            workflow = wait_for_deployment(commit, timeout)
        print("部署完成，正在核验线上版本…", flush=True)
        stage = "verify_online"
        with timed_stage(timings, stage):
            online = verify_online(ready, manifest)
    except Exception as error:
        raise PublicationCheckError(commit, stage, error) from error
    return {"state": "passed", "repository": REPOSITORY, "branch": "main", "build_id": manifest["build_id"],
            "commit": commit, "commit_created": changed, "files": counts,
            "workflow": workflow, "online": online, "url": WEB_URL + "/",
            "timings_seconds": timings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/pages-preview/langrensha-site")
    parser.add_argument("--publish-dir", type=Path, default=ROOT.parent / "langrensha-site")
    parser.add_argument("--check-only", action="store_true", help="Build and validate locally without publishing")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary materials after successful deployment")
    parser.add_argument("--timeout", type=int, default=1800, help="Maximum wait for Pages deployment")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    timings = {}
    report_path = None
    try:
        built = build("/langrensha-site", args.output)
        if args.check_only:
            print(f"本地检查通过：{args.output}", flush=True)
            return 0
        timings.update(built["timings_seconds"])
        report_path = ROOT / "tmp/pages-build" / built["build_id"] / "sync-result.json"
        with timed_stage(timings, "publication_total"):
            published = publish_site(args.output, args.publish_dir, timeout=args.timeout, timings=timings)
        timings["total"] = round(time.perf_counter() - started, 3)
        result = {**published, "build": built, "timings_seconds": timings}
        write_json(report_path, result)
        if not args.keep_temp:
            try:
                with timed_stage(timings, "cleanup"):
                    result["cleanup"] = cleanup(ROOT, args.output, built["build_id"], built["source_hash"])
            except Exception as error:
                result["cleanup"] = {"state": "failed", "errors": [str(error)]}
            timings["total"] = round(time.perf_counter() - started, 3)
            write_json(report_path, result)
        print(f"上线成功：{published.get('url', WEB_URL + '/')}（总耗时 {timings['total']:.1f} 秒）", flush=True)
        if args.keep_temp:
            print("已按 --keep-temp 保留本地临时资料。", flush=True)
        elif result["cleanup"]["state"] == "passed":
            cleaned = result["cleanup"]
            summary = f"清理完成：{cleaned['completed_games']} 局资料"
            if cleaned["pending_games"]:
                summary += f"，保留 {cleaned['pending_games']} 局未完成资料"
            print(summary + "。", flush=True)
        else:
            print(f"清理未完成，不影响上线；详情：{report_path.relative_to(ROOT)}", file=sys.stderr)
        return 0
    except Exception as error:
        if report_path is not None:
            timings["total"] = round(time.perf_counter() - started, 3)
            result = {"state": "failed", "build": built,
                      "timings_seconds": timings, "error": str(error)}
            if isinstance(error, PublicationCheckError):
                result.update(commit=error.commit, push_succeeded=True, failed_stage=error.stage)
            write_json(report_path, result)
        print(str(error), file=sys.stderr)
        if report_path is not None:
            print(f"详情：{report_path.relative_to(ROOT)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
