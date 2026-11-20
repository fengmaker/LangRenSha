"""Build a local static site from final game JSON and validate representative routes."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any
import uuid
from zipfile import BadZipFile, ZipFile
from zlib import error as CompressionError

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "website" / "web"
SHELL_ID = "__static__"
SHELL_DIRECTORY = ".static-shells"
ROUTE_FAMILIES = ("games", "players", "seasons")
FRONTEND_CACHE_VERSION = 1
sys.path.insert(0, str(ROOT))

from website.run import node_binary
from website.static_publish.generated_dirs import rename_generated_directory


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@contextmanager
def timed_stage(timings: dict[str, float], name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        timings[name] = round(time.perf_counter() - started, 3)


def normalize_rsc_paths(out: Path) -> int:
    """Correct Next 16 Windows export separators, without duplicating payloads."""
    out = out.resolve()
    changed = 0
    for folder in list(out.rglob("__next.*")):
        if not folder.is_dir():
            continue
        for source in list(folder.rglob("*.txt")):
            target = folder.parent / (folder.name + "." + ".".join(source.relative_to(folder).parts))
            if not target.resolve().is_relative_to(out) or target.exists():
                raise RuntimeError(f"RSC output path collision: {target}")
            source.replace(target)
            changed += 1
        for directory in sorted(folder.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if directory.is_dir():
                directory.rmdir()
        folder.rmdir()
    return changed


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _generated_path(path: Path, root: Path, label: str) -> Path:
    """Resolve lexically under tmp/ and reject linked path components before writes."""
    tmp_root = Path(os.path.abspath(root / "tmp"))
    absolute = Path(os.path.abspath(path))
    if absolute == tmp_root or not absolute.is_relative_to(tmp_root):
        raise ValueError(f"{label} must be a subdirectory of this workspace's tmp/")
    cursor = absolute
    while cursor != tmp_root:
        if _is_link(cursor):
            raise ValueError(f"{label} cannot contain symlinks or junctions: {cursor}")
        cursor = cursor.parent
    if _is_link(tmp_root):
        raise ValueError(f"Workspace tmp/ cannot be a symlink or junction: {tmp_root}")
    return absolute


def replace_generated(source: Path | None, destination: Path) -> None:
    """Replace one of the explicit generated inputs inside Next's workspace."""
    workspace = (WEB / ".static-build").resolve()
    allowed = [workspace / "src", workspace / "public"]
    resolved = destination.resolve()
    if (resolved not in [path.resolve() for path in allowed]
            or not resolved.is_relative_to(workspace) or _is_link(destination)):
        raise RuntimeError(f"Refusing generated-directory replacement: {destination}")
    if destination.exists():
        shutil.rmtree(destination)
    if source is not None and source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.mkdir(parents=True, exist_ok=True)


def _frontend_configs() -> list[Path]:
    return sorted(path for path in WEB.iterdir()
                  if path.is_file() and path.name != "next-env.d.ts"
                  and (path.suffix in {".json", ".ts", ".js", ".mjs", ".cjs"}
                       or path.name.startswith(".env")))


def _public_assets() -> list[Path]:
    public = WEB / "public"
    return sorted(path for path in public.iterdir() if path.name not in {"data", "media"}) if public.is_dir() else []


def _frontend_cache_key(node: str, env: dict[str, str]) -> str | None:
    installed_lock = WEB / "node_modules/.package-lock.json"
    if not installed_lock.is_file():
        return None
    node_path = Path(node).resolve()
    node_stat = node_path.stat()
    build_env = {key: value for key, value in env.items()
                 if key.startswith("NEXT_") or key in {"CI", "NODE_ENV", "NODE_OPTIONS"}}
    digest = hashlib.sha256(json.dumps(
        [FRONTEND_CACHE_VERSION, str(node_path), node_stat.st_size, node_stat.st_mtime_ns, build_env],
        sort_keys=True,
    ).encode("utf-8"))
    paths = [installed_lock, *_frontend_configs()]
    for folder in (WEB / "src", *_public_assets()):
        if _is_link(folder):
            return None
        paths.append(folder)
        if folder.is_dir():
            paths.extend(folder.rglob("*"))
    for path in sorted(paths):
        if _is_link(path):
            return None
        if path.is_file():
            with path.open("rb") as stream:
                file_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            digest.update(json.dumps([path.relative_to(WEB).as_posix(), file_hash]).encode("utf-8"))
    return digest.hexdigest()


def _restore_frontend(cache_file: Path, destination: Path, snapshot_id: str) -> bool:
    try:
        with ZipFile(cache_file) as archive:
            if archive.comment != snapshot_id.encode("ascii"):
                return False
            entries = set(archive.namelist())
            required = {"index.html", "404.html", *(
                f"{SHELL_DIRECTORY}/{family}/index.html" for family in ROUTE_FAMILIES
            )}
            if (not required <= entries or not any(
                    name.startswith("_next/static/") and not name.endswith("/") for name in entries)
                    or archive.testzip() is not None):
                return False
            archive.extractall(destination)
    except (OSError, BadZipFile, CompressionError):
        if destination.exists():
            raise
        return False
    return True


def prepare_static_workspace() -> Path:
    """Build in a child project so Next output never overwrites the local app."""
    workspace = WEB / ".static-build"
    if _is_link(workspace):
        raise RuntimeError("Static build workspace cannot be a link")
    workspace.mkdir(parents=True, exist_ok=True)
    for path in workspace.iterdir():
        if path.is_file() and not path.name.endswith(".tsbuildinfo"):
            path.unlink()
    for path in _frontend_configs():
        shutil.copy2(path, workspace / path.name)
    replace_generated(WEB / "src", workspace / "src")
    public = workspace / "public"
    replace_generated(None, public)
    for path in _public_assets():
        if path.is_dir():
            shutil.copytree(path, public / path.name)
        else:
            shutil.copy2(path, public / path.name)
    return workspace


def retain_route_shells(site: Path) -> None:
    """Keep one data-independent compiled template for each dynamic route."""
    for family in ROUTE_FAMILIES:
        shell = site / family / SHELL_ID
        if not (shell / "index.html").is_file():
            raise RuntimeError(f"Frontend did not export the {family} route shell: {shell}")
        destination = site / SHELL_DIRECTORY / family
        destination.parent.mkdir(parents=True, exist_ok=True)
        rename_generated_directory(shell, destination)


def materialize_snapshot(site: Path, snapshot: Path) -> dict[str, int]:
    """Clone route shells and move the snapshot into the same build's candidate site."""
    if _is_link(site) or _is_link(snapshot):
        raise ValueError("Candidate site and snapshot cannot be links")
    site, snapshot = site.resolve(), snapshot.resolve()
    if site == snapshot or site.parent != snapshot.parent:
        raise ValueError("Candidate site and snapshot must be separate directories in the same build")

    manifest = json.loads((snapshot / "data/manifest.json").read_text(encoding="utf-8"))
    release = snapshot / "data" / "releases" / manifest["snapshot_id"]
    routes = {family: [row["id"] for row in json.loads(
        (release / family / "index.json").read_text(encoding="utf-8"))["items"]]
              for family in ("games", "players")}
    routes["seasons"] = [row["id"] for row in manifest["seasons"]]
    for family, ids in routes.items():
        root = site / family
        template = site / SHELL_DIRECTORY / family
        if not (template / "index.html").is_file():
            raise RuntimeError(f"Static build has no retained {family} route shell")
        for child in root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
        for route_id in ids:
            destination = root / route_id
            if destination.resolve().parent != root.resolve():
                raise RuntimeError(f"Route ID leaves its generated directory: {route_id}")
            shutil.copytree(template, destination)
    for name in ("data", "media"):
        source = snapshot / name
        destination = site / name
        if _is_link(source) or _is_link(destination):
            raise ValueError(f"Generated {name} directories cannot be links")
        if destination.exists():
            shutil.rmtree(destination)
        if source.is_dir():
            rename_generated_directory(source, destination)
    return {family: len(ids) for family, ids in routes.items()}


def _promote(site: Path, output: Path, build_id: str, *, root: Path | None = None) -> None:
    root = Path(root or ROOT).resolve()
    output = _generated_path(Path(output), root, "Ready output")
    site = _generated_path(Path(site), root, "Candidate site")
    if site == output or not site.is_dir():
        raise ValueError("Candidate site must be a separate directory inside this workspace tmp/")
    if output.exists() and not output.is_dir():
        raise ValueError(f"Ready output must be a directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    backup = output.with_name(f".{output.name}-previous-{build_id}")
    if backup.exists():
        raise ValueError(f"Build backup already exists: {backup}")
    replaced = False
    try:
        if output.exists():
            rename_generated_directory(output, backup)
            replaced = True
        rename_generated_directory(site, output)
    except BaseException:
        if output.exists() and not site.exists():
            rename_generated_directory(output, site)
        if replaced and backup.exists():
            rename_generated_directory(backup, output)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def build(base_path: str, output: Path, *, root: Path = ROOT) -> dict[str, Any]:
    from website.static_publish.check_static import check
    from website.static_publish.export_static import export_direct_snapshot

    if base_path and (not base_path.startswith("/") or base_path.endswith("/") or ".." in base_path):
        raise ValueError("base_path must be empty or a leading-slash path without a trailing slash")
    root = Path(root).resolve()
    output = _generated_path(Path(output), root, "Ready output")

    build_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    candidate_root = root / "tmp" / "pages-build" / build_id
    candidate_root.mkdir(parents=True)
    timings = {}
    started = time.perf_counter()
    try:
        print("正在构建静态网站…", flush=True)
        with timed_stage(timings, "export_json"):
            manifest = export_direct_snapshot(root, candidate_root / "snapshot/data",
                                              base_path=base_path, build_id=build_id)
        node = node_binary()
        env = {**os.environ, "NEXT_PUBLIC_SITE_MODE": "static", "NEXT_PUBLIC_BASE_PATH": base_path,
               "NEXT_TELEMETRY_DISABLED": "1",
               "ARCHIVE_PRERENDER_DATA": str(candidate_root / "snapshot/data")}
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        site = candidate_root / "site"
        with timed_stage(timings, "frontend_cache_lookup"):
            key = _frontend_cache_key(node, env)
            cache_file = root / ".cache/static-publish/frontend" / f"{key}.zip" if key else None
            reused = cache_file is not None and _restore_frontend(cache_file, site, manifest["snapshot_id"])
        archive = None
        if not reused:
            with timed_stage(timings, "prepare_workspace"):
                workspace = prepare_static_workspace()
            npm = str(Path(node).with_name("npm.cmd")) if os.name == "nt" else shutil.which("npm", path=env["PATH"])
            if not npm:
                raise RuntimeError("npm is unavailable")
            for step in ("build", "typecheck"):
                with timed_stage(timings, f"frontend_{step}"):
                    with (candidate_root / f"{step}.log").open("w", encoding="utf-8") as log:
                        result = subprocess.run([npm, "run", step], cwd=workspace, env=env, stdout=log,
                                                stderr=subprocess.STDOUT, timeout=1800)
                    if result.returncode:
                        raise RuntimeError(f"Frontend {step} failed; see {candidate_root / (step + '.log')}")
            with timed_stage(timings, "frontend_prepare_output"):
                out = workspace / "out"
                normalize_rsc_paths(out)
                shutil.copytree(out, site)
                retain_route_shells(site)
                if cache_file is not None and _frontend_cache_key(node, env) == key:
                    archive = Path(shutil.make_archive(str(candidate_root / "frontend"), "zip", site))
                    with ZipFile(archive, "a") as cached:
                        cached.comment = manifest["snapshot_id"].encode("ascii")
        with timed_stage(timings, "materialize_pages"):
            route_counts = materialize_snapshot(site, candidate_root / "snapshot")
        with timed_stage(timings, "check_static"):
            report = check(site, base_path)
        if archive is not None and cache_file is not None:
            with suppress(OSError):
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                archive.replace(cache_file)
        with timed_stage(timings, "promote_output"):
            _promote(site, output, build_id, root=root)
        timings["build_total"] = round(time.perf_counter() - started, 3)
        result = {"state": "passed", "build_id": build_id, "snapshot_id": manifest["snapshot_id"],
                  "release_id": manifest["release_id"], "source_hash": manifest["source_hash"],
                  "routes": route_counts, "check": report, "output": str(output),
                  "frontend_cache": "hit" if reused else "miss",
                  "timings_seconds": timings}
        write_json(candidate_root / "result.json", result)
        print(f"构建通过：{route_counts['games']} 场对局、{route_counts['players']} 位选手，"
              f"耗时 {timings['build_total']:.1f} 秒。", flush=True)
        return result
    except BaseException:
        timings["build_total"] = round(time.perf_counter() - started, 3)
        write_json(candidate_root / "result.json", {
            "state": "failed", "build_id": build_id, "timings_seconds": timings,
        })
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base-path", default="/langrensha-site")
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/pages-preview/langrensha-site")
    args = parser.parse_args(argv)
    try:
        build(args.base_path, args.output, root=args.root)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"本地成品：{args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
