"""Export, build and accept a static site before replacing the ready directory."""
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

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "website/web"
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


def replace_generated(source: Path, destination: Path) -> None:
    """Only replace the dedicated snapshot and two generated media directories."""
    allowed = [WEB / ".static-snapshot", WEB / "public/media/player-photos", WEB / "public/media/bluff-frames"]
    if destination.resolve() not in [p.resolve() for p in allowed] or destination.is_symlink():
        raise RuntimeError(f"Refusing generated-directory replacement: {destination}")
    if destination.exists():
        shutil.rmtree(destination)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.mkdir(parents=True, exist_ok=True)


def promote(site: Path, target: Path, receipt: dict) -> None:
    """Restore both previous site and receipt if promotion cannot complete."""
    target = target.resolve()
    if not target.is_relative_to(ROOT / "tmp") or target == ROOT / "tmp":
        raise RuntimeError("Ready output must be a subdirectory of this workspace's tmp/")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise RuntimeError("Ready output cannot be a symlink")
    staged = target.with_name(f".{target.name}-{receipt['build_id']}")
    backup = target.with_name(f".{target.name}-previous-{receipt['build_id']}")
    receipt_path = target.parent / "acceptance.json"
    previous_receipt = receipt_path.read_bytes() if receipt_path.exists() else None
    shutil.copytree(site, staged)
    had_previous = target.exists()
    replaced = False
    try:
        if had_previous:
            target.replace(backup)
        staged.replace(target)
        replaced = True
        temporary_receipt = target.parent / f".acceptance-{receipt['build_id']}.json"
        write_json(temporary_receipt, receipt)
        temporary_receipt.replace(receipt_path)
    except BaseException:
        if replaced:
            shutil.rmtree(target)
        if backup.exists():
            backup.replace(target)
        if previous_receipt is not None:
            receipt_path.write_bytes(previous_receipt)
        else:
            receipt_path.unlink(missing_ok=True)
        raise
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    if backup.exists():
        shutil.rmtree(backup)


def build(api_url: str, base_path: str, output: Path, *, browser_channel: str = "chrome",
          partial_season: str | None = None) -> dict:
    from website.export_static import export_snapshot
    from website.check_static import check
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
    receipt = {"build_id": build_id, "generated_at": datetime.now(timezone.utc).isoformat(),
               "base_path": base_path, "mode": "partial" if partial_season else "complete",
               "state": "building", **source_receipt()}
    step = "export"
    try:
        print(f"[{build_id}] Exporting published API", flush=True)
        export_snapshot(api_url, candidate / "snapshot", base_path=base_path, build_id=build_id,
                        partial_season=partial_season)
        manifest = json.loads((candidate / "snapshot/data/manifest.json").read_text(encoding="utf-8"))
        receipt.update(snapshot_id=manifest["snapshot_id"], release_id=manifest["release_id"])
        step = "sync"
        replace_generated(candidate / "snapshot", WEB / ".static-snapshot")
        for kind in ("player-photos", "bluff-frames"):
            replace_generated(candidate / "snapshot/media" / kind, WEB / "public/media" / kind)
        # Only generated data is copied here; unrelated public assets remain intact.
        public_data = WEB / "public/data"
        if public_data.is_symlink():
            raise RuntimeError("Generated public/data cannot be a symlink")
        if public_data.exists():
            shutil.rmtree(public_data)
        shutil.copytree(candidate / "snapshot/data", public_data)
        node = node_binary()
        env = {**os.environ, "NEXT_PUBLIC_SITE_MODE": "static", "NEXT_PUBLIC_BASE_PATH": base_path,
               "NEXT_TELEMETRY_DISABLED": "1"}
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        npm = str(Path(node).with_name("npm.cmd")) if os.name == "nt" else shutil.which("npm", path=env["PATH"])
        if not npm:
            raise RuntimeError("npm is unavailable")
        for step in ("build", "typecheck"):
            print(f"[{build_id}] Frontend {step}", flush=True)
            with (candidate / f"{step}.log").open("w", encoding="utf-8") as log:
                result = subprocess.run([npm, "run", step], cwd=WEB, env=env, stdout=log,
                                        stderr=subprocess.STDOUT, timeout=1800)
            if result.returncode:
                raise RuntimeError(f"Frontend {step} failed; see {candidate / (step + '.log')}")
        step = "acceptance"
        receipt["rsc_paths_normalized"] = normalize_rsc_paths(WEB / "out")
        shutil.copytree(WEB / "out", candidate / "site")
        print(f"[{build_id}] Static/API/browser acceptance", flush=True)
        acceptance = check(candidate / "site", base_path, api_url, browser_channel=browser_channel,
                           output=candidate / "acceptance.json")
        receipt.update(state="partial" if not manifest["complete"] else "passed", acceptance=acceptance,
                       artifact_hash=tree_hash(candidate / "site"))
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
    args = parser.parse_args()
    try:
        build(args.api_url, args.base_path, args.output, browser_channel=args.browser_channel,
              partial_season=args.partial_season)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
