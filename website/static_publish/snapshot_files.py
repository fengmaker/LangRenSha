"""Resolve archived responses through the snapshot that selected their content."""

from pathlib import Path
import re


SNAPSHOT_SCHEMA_VERSION = 3


def object_path(data_root: Path, digest: str) -> Path:
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"Invalid static document hash: {digest}")
    return data_root / "objects" / f"{digest}.json"


def document_path(data_root: Path, manifest: dict, relative: str) -> Path:
    digest = manifest.get("document_hashes", {}).get(relative)
    if digest is not None:
        return object_path(data_root, digest)
    return data_root / "releases" / manifest["snapshot_id"] / relative
