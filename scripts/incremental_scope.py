"""Extend the frozen S23 publication count only with source-bound human approvals."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"增量确认文件必须为对象：{path.name}")
    return value


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def approved_incremental_count(root: Path, season: str) -> int:
    """Keep the original fixed snapshot intact; approvals account for extra games."""
    if season != "S23":
        return 0
    root = Path(root).resolve()
    markers = sorted((root / "data/games" / season).glob("*/incremental_review.json"))
    if not markers:
        return 0
    baseline = _read(root / "data/reports/S23/S23_逐局复核计划.json")
    original_bvids = {row["bvid"] for row in baseline["entries"] if row["phase"] == "regular"}
    identities = set()
    for marker in markers:
        approval = _read(marker)
        if approval.get("format") != "masters-incremental-confirmed-v1" or approval.get("reviewed") is not True:
            raise ValueError(f"新增正式对局缺少人工确认：{marker.parent.name}")
        for filename, field in (("dossier.json", "dossier_sha256"), ("voting.json", "voting_sha256")):
            if _hash(marker.parent / filename) != approval.get(field):
                raise ValueError(f"新增正式文件与人工确认版本不一致：{marker.parent.name}/{filename}")
        manual_path = (root / approval["manual_source_path"]).resolve()
        if not manual_path.is_relative_to(root / "data") or _hash(manual_path) != approval.get("manual_sha256"):
            raise ValueError("新增对局人工复核原件缺失或哈希不匹配")
        manual = _read(manual_path)
        if manual.get("format") != "masters-incremental-review-v1" or manual.get("season") != season:
            raise ValueError("新增对局人工复核原件格式或赛季错误")
        matches = [row for row in manual["games"] if row.get("review_id") == approval.get("review_id")]
        if len(matches) != 1 or matches[0].get("reviewed") is not True:
            raise ValueError("新增对局不在用户已勾选复核范围内")
        row = matches[0]
        identity = (row.get("bvid"), row.get("cid"), row.get("page"))
        if any(approval.get(key) != row.get(key) for key in ("bvid", "cid", "page")):
            raise ValueError("新增正式对局与人工复核来源不一致")
        if identity in identities or identity[0] in original_bvids:
            raise ValueError("新增范围重复或包含原75局，不能重复增加发布局数")
        dossier = _read(marker.parent / "dossier.json")
        if dossier.get("season") != season or not any(
                file.get("external_key") == f"{identity[0]}:{identity[1]}"
                for file in dossier.get("files", [])):
            raise ValueError("新增正式档案未绑定已确认录像来源")
        identities.add(identity)
    return len(identities)
