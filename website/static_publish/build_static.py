"""Export, build and accept a static site before replacing the ready directory."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter
import uuid

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "website/web"
FRONTEND_MODE = "data_separated_shells_v1"
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
            digest.update(bytes.fromhex(hashlib.sha256(path.read_bytes()).hexdigest()))
    return digest.hexdigest()


def source_receipt() -> dict:
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", *args], cwd=ROOT)
    files = git("ls-files", "--cached", "--others", "--exclude-standard", "-z", "website", "scripts",
                "config", "requirements", ".github").split(b"\0")
    digest = hashlib.sha256()
    for name in sorted(set(files)):
        if not name:
            continue
        path = ROOT / name.decode("utf-8")
        digest.update(name)
        digest.update(hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b"DELETED")
    locks = [WEB / "package-lock.json", ROOT / "requirements/web.txt"]
    return {"source_commit": git("rev-parse", "HEAD").decode().strip(),
            "source_dirty": bool(git("status", "--porcelain")),
            "build_input_hash": digest.hexdigest(),
            "dependency_hashes": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in locks}}


def frontend_input_hash() -> str:
    """Identify compiler inputs independently from exported data and API code."""
    web = ROOT / "website/web"
    files = list((web / "src").rglob("*"))
    files.extend(path for path in web.glob("*") if path.is_file())
    files.extend(path for path in (web / "public").rglob("*")
                 if path.is_file() and not path.relative_to(web / "public").parts[0] in {"data", "media"})
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        if (path.is_file() and not path.name.endswith(".tsbuildinfo")
                and path.name not in {"README.md", ".gitignore", "next-env.d.ts"}):
            digest.update(path.relative_to(web).as_posix().encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def accepted_previous(output: Path, base_path: str) -> dict | None:
    receipt_path = output.parent / "acceptance.json"
    if not receipt_path.is_file() or not (output / "data/manifest.json").is_file():
        return None
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("state") != "passed" or receipt.get("mode") != "complete" or not receipt.get("artifact_hash"):
        return None
    manifest = json.loads((output / "data/manifest.json").read_text(encoding="utf-8"))
    if manifest.get("base_path") != base_path or manifest.get("complete") is not True:
        return None
    if receipt.get("build_id") != manifest.get("build_id"):
        raise RuntimeError("Previous accepted site and receipt have different build IDs")
    if tree_hash(output) != receipt["artifact_hash"]:
        raise RuntimeError("Previous accepted artifact was modified; use --full to rebuild it")
    return receipt


def assert_source_unchanged(receipt: dict) -> None:
    if (source_receipt().get("build_input_hash") != receipt.get("build_input_hash")
            or frontend_input_hash() != receipt["frontend_input_hash"]):
        raise RuntimeError("Source inputs changed during the build; rerun after edits finish")


def normalize_rsc_paths(out: Path) -> int:
    """Correct Next 16 Windows export separators, without duplicating payloads.

    Upstream: https://github.com/vercel/next.js/issues/92339
    Next's exporter passes path.relative() backslashes to a slash-only encoder.
    Linux and fixed Next versions already emit flat files, so need no changes.
    """
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
        for directory in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if directory.is_dir():
                directory.rmdir()
        folder.rmdir()
    return changed


def replace_generated(source: Path | None, destination: Path) -> None:
    """Only replace inputs inside the dedicated static-build workspace."""
    workspace = (WEB / ".static-build").resolve()
    allowed = [workspace / "src", workspace / "public", workspace / ".static-snapshot/data"]
    if (destination.resolve() not in [p.resolve() for p in allowed]
            or not destination.resolve().is_relative_to(workspace) or destination.is_symlink()
            or (hasattr(destination, "is_junction") and destination.is_junction())):
        raise RuntimeError(f"Refusing generated-directory replacement: {destination}")
    if destination.exists():
        shutil.rmtree(destination)
    if source is not None and source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.mkdir(parents=True, exist_ok=True)


def prepare_static_workspace(snapshot: Path) -> Path:
    """Keep Next's native .next and out in a child project, away from local serving."""
    workspace = WEB / ".static-build"
    if workspace.is_symlink() or (hasattr(workspace, "is_junction") and workspace.is_junction()):
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
    # Public inputs are copied as regular files; generated snapshots never come
    # from the running maintenance application's public directory.
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
    """Keep the compiler's data-independent dynamic pages for later updates."""
    for family in ROUTE_FAMILIES:
        shell = site / family / SHELL_ID
        if not (shell / "index.html").is_file():
            raise RuntimeError(f"Frontend did not export the {family} route shell: {shell}")
        destination = site / SHELL_DIRECTORY / family
        destination.parent.mkdir(parents=True, exist_ok=True)
        shell.rename(destination)


def materialize_snapshot(site: Path, snapshot: Path) -> dict[str, int]:
    """Refresh snapshot files and clone page shells for exactly the current IDs."""
    manifest = json.loads((snapshot / "data/manifest.json").read_text(encoding="utf-8"))
    release = snapshot / "data/releases" / manifest["snapshot_id"]
    routes = {family: [row["id"] for row in json.loads(
        (release / family / "index.json").read_text(encoding="utf-8"))["items"]]
              for family in ("games", "players")}
    routes["seasons"] = [row["id"] for row in manifest["seasons"]]
    for family, ids in routes.items():
        root = site / family
        template = site / SHELL_DIRECTORY / family
        if not (template / "index.html").is_file():
            raise RuntimeError(f"Accepted frontend has no retained {family} route shell")
        # The family root also contains the fixed list page and its payloads.
        # Only its child directories are generated dynamic routes.
        for child in root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
        for route_id in ids:
            destination = root / route_id
            if destination.resolve().parent != root.resolve():
                raise RuntimeError(f"Route ID leaves its generated directory: {route_id}")
            shutil.copytree(template, destination)
            if family == "seasons" and route_id != "S23" and (destination / "bluff-review").is_dir():
                # The season-specific review entry is currently supported for S23.
                shutil.rmtree(destination / "bluff-review")
    for name in ("data", "media"):
        destination = site / name
        if destination.exists():
            shutil.rmtree(destination)
        if (snapshot / name).is_dir():
            shutil.copytree(snapshot / name, destination)
    return {family: len(ids) for family, ids in routes.items()}


def promote(site: Path, target: Path, receipt: dict) -> None:
    """Restore both previous site and receipt if promotion cannot complete."""
    site = site.resolve()
    target = target.resolve()
    if not target.is_relative_to(ROOT / "tmp") or target == ROOT / "tmp":
        raise RuntimeError("Ready output must be a subdirectory of this workspace's tmp/")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise RuntimeError("Ready output cannot be a symlink")
    if not site.is_relative_to(ROOT) or site == ROOT or site == target:
        raise RuntimeError("Candidate site must be a separate directory inside this workspace")
    backup = target.with_name(f".{target.name}-previous-{receipt['build_id']}")
    receipt_path = target.parent / "acceptance.json"
    previous_receipt = receipt_path.read_bytes() if receipt_path.exists() else None
    had_previous = target.exists()
    replaced = False
    try:
        if had_previous:
            target.rename(backup)
        site.rename(target)
        replaced = True
        temporary_receipt = target.parent / f".acceptance-{receipt['build_id']}.json"
        write_json(temporary_receipt, receipt)
        temporary_receipt.replace(receipt_path)
    except BaseException:
        if replaced:
            target.rename(site)
        if backup.exists():
            backup.rename(target)
        if previous_receipt is not None:
            receipt_path.write_bytes(previous_receipt)
        else:
            receipt_path.unlink(missing_ok=True)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def build(api_url: str, base_path: str, output: Path, *, browser_channel: str = "chrome",
          partial_season: str | None = None, incremental: bool = True,
          skip_browser_check: bool = False, full_check: bool = False,
          stage_seconds: dict | None = None) -> dict:
    from website.static_publish.export_static import export_snapshot
    from website.static_publish.check_static import check, check_basic
    if base_path and (not base_path.startswith("/") or base_path.endswith("/") or ".." in base_path):
        raise ValueError("base_path must be empty or a leading-slash path without a trailing slash")
    output = output.resolve()
    if not output.is_relative_to(ROOT / "tmp") or output == ROOT / "tmp":
        raise ValueError("Ready output must be a subdirectory of this workspace's tmp/")
    prior_manifest = output / "data/manifest.json"
    if partial_season and prior_manifest.exists() and json.loads(prior_manifest.read_text(encoding="utf-8"))["complete"]:
        raise ValueError("Use a separate output directory for a partial development sample")
    build_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    candidate = ROOT / "tmp/pages-build" / build_id
    candidate.mkdir(parents=True)
    input_started = perf_counter()
    receipt = {"build_id": build_id, "generated_at": datetime.now(timezone.utc).isoformat(),
               "base_path": base_path, "mode": "partial" if partial_season else "complete",
               "check_scope": "full" if full_check else "basic",
               "state": "building", "frontend_input_hash": frontend_input_hash(),
               "frontend_mode": FRONTEND_MODE, **source_receipt()}
    # Share the current attempt's timings with the publisher, including failures.
    receipt["stage_seconds"] = stage_seconds if stage_seconds is not None else {}
    receipt["stage_seconds"]["inputs"] = round(perf_counter() - input_started, 3)

    @contextmanager
    def stage(name: str):
        started = perf_counter()
        try:
            yield
        finally:
            receipt["stage_seconds"][name] = round(perf_counter() - started, 3)

    step = "export"
    try:
        try:
            with stage("baseline_check"):
                previous = accepted_previous(output, base_path) if not partial_season else None
        except RuntimeError:
            if incremental:
                raise
            # --full can recover a damaged baseline by rebuilding independently.
            previous = None
        previous_index = previous.get("export_index") if previous else None
        reuse_frontend = bool(previous and previous.get("frontend_mode") == FRONTEND_MODE
                              and previous.get("frontend_input_hash") == receipt["frontend_input_hash"])
        if (incremental and reuse_frontend and previous_index
                and previous.get("build_input_hash") == receipt.get("build_input_hash")
                and previous.get("frontend_input_hash") == receipt["frontend_input_hash"]):
            from website.static_publish.export_static import _request_json
            if (_request_json(api_url, "/health").get("status") == "ok"
                    and _request_json(api_url, "/api/v1/export-manifest") == previous_index["metadata"]
                    and _request_json(api_url, "/api/v1/releases") == json.loads(
                        (output / "data/releases" / previous["snapshot_id"] / "releases.json").read_text(encoding="utf-8"))):
                updated = {**previous, "check_scope": receipt["check_scope"]}
                if full_check:
                    step = "acceptance"
                    print(f"[{build_id}] Unchanged; running requested full acceptance", flush=True)
                    with stage("acceptance"):
                        updated["acceptance"] = check(output, base_path, api_url, browser_channel=browser_channel,
                            output=candidate / "acceptance.json", export_index=previous_index,
                            previous_export_index=previous_index, skip_browser_check=skip_browser_check)
                    if tree_hash(output) != previous["artifact_hash"]:
                        raise RuntimeError("Accepted artifact changed during acceptance")
                    updated["browser_check"] = "skipped" if skip_browser_check else "passed"
                else:
                    updated["browser_check"] = "skipped"
                updated["acceptance_reused"] = not full_check
                step = "source_consistency"
                with stage("source_consistency"):
                    assert_source_unchanged(receipt)
                if updated.get("acceptance") != previous.get("acceptance"):
                    temporary = output.parent / f".acceptance-{build_id}.json"
                    write_json(temporary, updated)
                    temporary.replace(output.parent / "acceptance.json")
                updated.update(update_status="unchanged", frontend_build="reused",
                               stage_seconds=receipt["stage_seconds"])
                write_json(candidate / "receipt.json", {**receipt, "state": "unchanged",
                           "reused_build_id": previous["build_id"], "frontend_build": "reused",
                           "browser_check": updated["browser_check"],
                           "acceptance_reused": updated["acceptance_reused"]})
                print(f"[{build_id}] Unchanged; keeping accepted build {previous['build_id']}", flush=True)
                return updated
        print(f"[{build_id}] Exporting published API", flush=True)
        with stage("export"):
            export_snapshot(api_url, candidate / "snapshot", base_path=base_path, build_id=build_id,
                            partial_season=partial_season,
                            reuse_from=output if previous and incremental else None,
                            reuse_index=previous_index if incremental else None)
        manifest = json.loads((candidate / "snapshot/data/manifest.json").read_text(encoding="utf-8"))
        receipt.update(snapshot_id=manifest["snapshot_id"], release_id=manifest["release_id"])
        index_path = candidate / "snapshot/export-index.json"
        export_index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else None
        if export_index is not None:
            receipt["export_index"] = export_index
            print(f"[{build_id}] Export reuse: {json.dumps(export_index.get('metrics', {}), ensure_ascii=False)}", flush=True)
        receipt["frontend_build"] = "reused" if reuse_frontend else "compiled"
        if reuse_frontend:
            step = "frontend_reuse"
            print(f"[{build_id}] Reusing accepted frontend assets and route shells", flush=True)
            with stage(step):
                shutil.copytree(output, candidate / "site", ignore=lambda directory, names:
                                ["data", "media"] if Path(directory) == output else [])
            receipt["typecheck"] = "reused"
        else:
            step = "sync"
            with stage(step):
                build_web = prepare_static_workspace(candidate / "snapshot")
            node = node_binary()
            env = {**os.environ, "NEXT_PUBLIC_SITE_MODE": "static", "NEXT_PUBLIC_BASE_PATH": base_path,
                   "NEXT_TELEMETRY_DISABLED": "1"}
            env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
            npm = str(Path(node).with_name("npm.cmd")) if os.name == "nt" else shutil.which("npm", path=env["PATH"])
            if not npm:
                raise RuntimeError("npm is unavailable")
            receipt["typecheck"] = "pending"
            for step in ("build", "typecheck"):
                print(f"[{build_id}] Frontend {step}", flush=True)
                with stage("frontend_" + step):
                    with (candidate / f"{step}.log").open("w", encoding="utf-8") as log:
                        result = subprocess.run([npm, "run", step], cwd=build_web, env=env, stdout=log,
                                                stderr=subprocess.STDOUT, timeout=1800)
                    if result.returncode:
                        raise RuntimeError(f"Frontend {step} failed; see {candidate / (step + '.log')}")
                if step == "typecheck":
                    receipt["typecheck"] = "passed"
            receipt["rsc_paths_normalized"] = normalize_rsc_paths(build_web / "out")
            shutil.copytree(build_web / "out", candidate / "site")
            retain_route_shells(candidate / "site")
        step = "materialize"
        with stage(step):
            receipt["materialized_routes"] = materialize_snapshot(candidate / "site", candidate / "snapshot")
        step = "source_consistency_before_acceptance"
        with stage(step):
            assert_source_unchanged(receipt)
        step = "acceptance"
        print(f"[{build_id}] {'Full API/browser acceptance' if full_check else 'Basic file/version checks'}", flush=True)
        with stage(step):
            if full_check:
                acceptance = check(candidate / "site", base_path, api_url, browser_channel=browser_channel,
                                   output=candidate / "acceptance.json", export_index=export_index,
                                   previous_export_index=previous_index, skip_browser_check=skip_browser_check)
            else:
                acceptance = check_basic(candidate / "site", base_path, output=candidate / "acceptance.json")
        receipt.update(state="partial" if not manifest["complete"] else "passed", acceptance=acceptance,
                       browser_check="passed" if full_check and not skip_browser_check else "skipped")
        step = "artifact_hash"
        with stage(step):
            receipt["artifact_hash"] = tree_hash(candidate / "site")
        step = "source_consistency"
        with stage(step):
            assert_source_unchanged(receipt)
        step = "promote"
        write_json(candidate / "receipt.json", receipt)
        # Partial samples are reviewable locally, but are never a full release receipt.
        promote(candidate / "site", output, receipt)
        print(f"[{build_id}] {receipt['state']}: {output}", flush=True)
        return receipt
    except BaseException as error:
        receipt.update(state="failed", failed_step=step, error=str(error))
        write_json(candidate / "receipt.json", receipt)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--base-path", default="/langrensha-site")
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/pages-preview/langrensha-site")
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--partial-season", help="Development sample only; never a complete release")
    parser.add_argument("--full", action="store_true", help="Fetch every API response instead of reusing unchanged JSON")
    parser.add_argument("--full-check", action="store_true", help="Run full API/browser acceptance instead of basic file/version checks")
    parser.add_argument("--skip-browser-check", action="store_true", help="Skip browser checks during --full-check; default builds already use basic checks")
    args = parser.parse_args()
    try:
        build(args.api_url, args.base_path, args.output, browser_channel=args.browser_channel,
              partial_season=args.partial_season, incremental=not args.full,
              skip_browser_check=args.skip_browser_check, full_check=args.full_check)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
