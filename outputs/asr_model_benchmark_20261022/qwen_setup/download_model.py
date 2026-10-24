"""Download and hash-check the pinned Qwen3-ASR model snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests


REPO_ID = "Qwen/Qwen3-ASR-0.6B"
REVISION = "5eb144179a02acc5e5ba31e748d22b0cf3e303b0"
API_URL = f"https://huggingface.co/api/models/{REPO_ID}?blobs=true"
ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = ROOT / ".models" / "qwen3-asr-0.6b"
MANIFEST_PATH = Path(__file__).resolve().parent / "model_download_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_json(url: str) -> dict:
    response = requests.get(url, timeout=(20, 90))
    response.raise_for_status()
    return response.json()


def download_file(entry: dict) -> dict:
    name = entry["rfilename"]
    expected_size = int(entry["size"])
    expected_sha = (entry.get("lfs") or {}).get("sha256")
    destination = MODEL_DIR / name
    partial = destination.with_name(destination.name + ".part")
    url = f"https://huggingface.co/{REPO_ID}/resolve/{REVISION}/{quote(name, safe='/')}?download=true"

    if destination.exists() and destination.stat().st_size == expected_size:
        digest = sha256_file(destination)
        if expected_sha and digest != expected_sha:
            destination.unlink()
        else:
            return {
                "file": name,
                "size_bytes": expected_size,
                "sha256": digest,
                "lfs_sha256": expected_sha,
                "status": "already_present_verified",
            }

    existing = partial.stat().st_size if partial.exists() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    response = requests.get(url, headers=headers, stream=True, timeout=(30, 120))
    response.raise_for_status()
    append = existing > 0 and response.status_code == 206
    if not append and partial.exists():
        partial.unlink()

    mode = "ab" if append else "wb"
    downloaded = existing if append else 0
    last_log = downloaded
    print(f"Downloading {name} ({expected_size:,} bytes)", flush=True)
    with partial.open(mode) as stream:
        for block in response.iter_content(chunk_size=8 * 1024 * 1024):
            if not block:
                continue
            stream.write(block)
            downloaded += len(block)
            if downloaded - last_log >= 64 * 1024 * 1024:
                print(f"  {name}: {downloaded:,}/{expected_size:,} bytes", flush=True)
                last_log = downloaded
    response.close()

    if downloaded != expected_size:
        raise RuntimeError(f"{name}: got {downloaded} bytes, expected {expected_size}")

    digest = sha256_file(partial)
    if expected_sha and digest != expected_sha:
        raise RuntimeError(f"{name}: SHA-256 mismatch: {digest} != {expected_sha}")
    os.replace(partial, destination)
    print(f"  verified {name}: sha256={digest}", flush=True)
    return {
        "file": name,
        "size_bytes": expected_size,
        "sha256": digest,
        "lfs_sha256": expected_sha,
        "status": "downloaded_and_verified",
    }


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    metadata = fetch_json(API_URL)
    actual_revision = metadata.get("sha")
    if actual_revision != REVISION:
        raise RuntimeError(f"Pinned revision mismatch: {actual_revision} != {REVISION}")

    files = []
    for entry in metadata.get("siblings", []):
        files.append(download_file(entry))

    report = {
        "repository": REPO_ID,
        "revision": REVISION,
        "source": API_URL,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    MANIFEST_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {MANIFEST_PATH}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted; any .part file can be resumed on the next run.", file=sys.stderr)
        raise
