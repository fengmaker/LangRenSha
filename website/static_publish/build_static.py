"""Build a local static site from final game JSON and validate representative routes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "website" / "web"
SHELL_ID = "__static__"
SHELL_DIRECTORY = ".static-shells"
ROUTE_FAMILIES = ("games", "players", "seasons")
sys.path.insert(0, str(ROOT))

from website.run import node_binary


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


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
    allowed = [workspace / "src", workspace / "public", workspace / ".static-snapshot/data"]
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


def prepare_static_workspace(snapshot: Path) -> Path:
    """Build in a child project so Next output never overwrites the local app."""
    workspace = WEB / ".static-build"
    if _is_link(workspace):
        raise RuntimeError("Static build workspace cannot be a link")
    workspace.mkdir(parents=True, exist_ok=True)
    for path in workspace.iterdir():
        if path.is_file() and not path.name.endswith(".tsbuildinfo"):
            path.unlink()
    for path in WEB.iterdir():
        if (path.is_file() and path.name != "next-env.d.ts"
                and (path.suffix in {".json", ".ts", ".js", ".mjs", ".cjs"}
                     or path.name.startswith(".env"))):
            shutil.copy2(path, workspace / path.name)
    replace_generated(WEB / "src", workspace / "src")
    replace_generated(snapshot / "data", workspace / ".static-snapshot/data")
    public = workspace / "public"
    replace_generated(None, public)
    source_public = WEB / "public"
    if source_public.is_dir():
        for path in source_public.iterdir():
            if path.name in {"data", "media"}:
                continue
            if path.is_dir():
                shutil.copytree(path, public / path.name)
            else:
                shutil.copy2(path, public / path.name)
    shutil.copytree(snapshot / "data", public / "data")
    if (snapshot / "media").is_dir():
        shutil.copytree(snapshot / "media", public / "media")
    return workspace


def retain_route_shells(site: Path) -> None:
    """Keep one data-independent compiled template for each dynamic route."""
    for family in ROUTE_FAMILIES:
        shell = site / family / SHELL_ID
        if not (shell / "index.html").is_file():
            raise RuntimeError(f"Frontend did not export the {family} route shell: {shell}")
        destination = site / SHELL_DIRECTORY / family
        destination.parent.mkdir(parents=True, exist_ok=True)
        shell.rename(destination)


def materialize_snapshot(site: Path, snapshot: Path) -> dict[str, int]:
    """Clone route shells for the IDs in this snapshot and copy public data/media."""
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
        destination = site / name
        if destination.exists():
            shutil.rmtree(destination)
        if (snapshot / name).is_dir():
            shutil.copytree(snapshot / name, destination)
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
            output.rename(backup)
            replaced = True
        site.rename(output)
    except BaseException:
        if output.exists() and not site.exists():
            output.rename(site)
        if replaced and backup.exists():
            backup.rename(output)
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
    try:
        print(f"[{build_id}] Exporting final game JSON", flush=True)
        manifest = export_direct_snapshot(root, candidate_root / "snapshot/data",
                                          base_path=base_path, build_id=build_id)
        workspace = prepare_static_workspace(candidate_root / "snapshot")
        node = node_binary()
        env = {**os.environ, "NEXT_PUBLIC_SITE_MODE": "static", "NEXT_PUBLIC_BASE_PATH": base_path,
               "NEXT_TELEMETRY_DISABLED": "1"}
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        npm = str(Path(node).with_name("npm.cmd")) if os.name == "nt" else shutil.which("npm", path=env["PATH"])
        if not npm:
            raise RuntimeError("npm is unavailable")
        for step in ("build", "typecheck"):
            print(f"[{build_id}] Frontend {step}", flush=True)
            with (candidate_root / f"{step}.log").open("w", encoding="utf-8") as log:
                result = subprocess.run([npm, "run", step], cwd=workspace, env=env, stdout=log,
                                        stderr=subprocess.STDOUT, timeout=1800)
            if result.returncode:
                raise RuntimeError(f"Frontend {step} failed; see {candidate_root / (step + '.log')}")
        out = workspace / "out"
        normalize_rsc_paths(out)
        site = candidate_root / "site"
        shutil.copytree(out, site)
        retain_route_shells(site)
        route_counts = materialize_snapshot(site, candidate_root / "snapshot")
        report = check(site, base_path)
        _promote(site, output, build_id, root=root)
        result = {"state": "passed", "build_id": build_id, "snapshot_id": manifest["snapshot_id"],
                  "release_id": manifest["release_id"], "source_hash": manifest["source_hash"],
                  "routes": route_counts, "check": report, "output": str(output)}
        write_json(candidate_root / "result.json", result)
        print(f"[{build_id}] Static site ready: {output}", flush=True)
        return result
    except BaseException:
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base-path", default="/langrensha-site")
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/pages-preview/langrensha-site")
    args = parser.parse_args(argv)
    try:
        result = build(args.base_path, args.output, root=args.root)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
