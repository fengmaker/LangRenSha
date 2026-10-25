"""Prepare season-scoped player photo assets from reviewed Weibo images.

The source mapping and human review files are authoritative for image/name
assignments. This script never recognizes faces or edits image content.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WEIBO_ROOT = ROOT / "data" / "weibo" / "2026-05-26_2026-10-20"
MAPPING_CSV = WEIBO_ROOT / "参赛名单" / "人名去重_照片映射.csv"
ROSTER_JSON = WEIBO_ROOT / "参赛名单" / "参赛人名名单.json"
SOURCE_INDEX_JSON = WEIBO_ROOT / "人名复核" / "照片人名_来源索引.json"
REVIEW_CSV = WEIBO_ROOT / "人名复核" / "S22-S23_照片人名_人工复核.csv"
S23_ROSTER_TXT = WEIBO_ROOT / "参赛名单" / "S23_参赛人名名单.txt"

OUTPUT_JSON = ROOT / "website" / "api" / "player_photos.json"
OUTPUT_ASSETS = ROOT / "website" / "assets" / "player-photos"

APPROVED_STATUSES = {"确认无误", "已修正"}
PHASE_PRIORITY = {"决赛周": 0, "正赛": 1, "表演赛": 2}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def official_s22_names() -> set[str]:
    """Use names actually seated in the retained S22 game dossiers."""
    names: set[str] = set()
    for dossier_path in sorted((ROOT / "data" / "games" / "S22").glob("*/dossier.json")):
        dossier = read_json(dossier_path)
        names.update(
            seat["name"]
            for seat in dossier.get("seats", [])
            if isinstance(seat.get("name"), str) and seat["name"].strip()
        )
    if len(names) != 62:
        raise ValueError(f"Expected 62 unique S22 dossier seat names; found {len(names)}")
    return names


def s23_names() -> set[str]:
    names = {
        line.strip()
        for line in S23_ROSTER_TXT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    return names


def occurrence_key(occurrence: dict[str, Any]) -> tuple[int, int, str]:
    phase = occurrence.get("phase", "")
    return (
        PHASE_PRIORITY.get(phase, 3),
        # Prefer the latest matching formal/final occurrence, then latest fallback.
        -date.fromisoformat(occurrence.get("event_date", "1970-01-01")).toordinal(),
        occurrence.get("source_url", ""),
    )


def choose_for_player(
    season: str,
    name: str,
    mappings_by_name: dict[tuple[str, str], list[dict[str, str]]],
    reviews_by_id: dict[str, dict[str, str]],
    pictures_by_sha: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    rejected: list[str] = []
    candidates: list[tuple[tuple[int, str, str, str, str], dict[str, Any]]] = []

    for row in mappings_by_name.get((season, name), []):
        photo_id = row["照片编号"]
        review = reviews_by_id.get(photo_id)
        if review is None:
            rejected.append("缺少人工复核记录")
            continue
        if row.get("原人工确认状态") not in APPROVED_STATUSES:
            rejected.append("照片人名尚未人工确认无误或修正")
            continue
        if review.get("人工确认") not in APPROVED_STATUSES:
            rejected.append("照片人名尚未人工确认无误或修正")
            continue
        if row.get("纳入参赛名单") != "是":
            rejected.append("照片未纳入参赛名单")
            continue

        confirmed_name = review.get("确认后的名字", "").strip()
        if confirmed_name != name or row.get("去重后姓名", "").strip() != name:
            rejected.append("映射姓名与人工复核姓名不一致")
            continue

        image_sha = row.get("图片SHA256", "").strip()
        if not image_sha or review.get("图片SHA256", "").strip() != image_sha:
            rejected.append("照片哈希与人工复核记录不一致")
            continue
        picture = pictures_by_sha.get(image_sha)
        if picture is None or picture.get("season") != season:
            # The season must agree in both the human mapping and source index.
            rejected.append("找不到同赛季来源图片")
            continue

        occurrences = [
            item
            for item in picture.get("occurrences", [])
            if item.get("source_url") and item.get("event_date")
        ]
        if not occurrences:
            rejected.append("来源索引没有可用的微博链接和日期")
            continue
        occurrence = min(occurrences, key=occurrence_key)

        source_path = Path(picture["source_image"])
        if not source_path.is_file():
            rejected.append("原始来源图片不可用")
            continue
        if sha256_file(source_path) != image_sha:
            rejected.append("原始图片哈希与来源索引不一致")
            continue

        rank, date_rank, _ = occurrence_key(occurrence)
        candidate_key = (rank, date_rank, image_sha, photo_id, occurrence["source_url"])
        candidates.append((candidate_key, {
            "photo_id": photo_id,
            "sha256": image_sha,
            "picture": picture,
            "occurrence": occurrence,
            "source_path": source_path,
        }))

    if not candidates:
        reason = rejected[0] if rejected else "没有找到同赛季人工确认无误或已修正的照片"
        return None, reason
    candidates.sort(key=lambda candidate: candidate[0])
    return candidates[0][1], None


def build() -> dict[str, Any]:
    roster = read_json(ROSTER_JSON)
    # Keep the supplied roster file in the dependency set and verify its schema.
    if roster.get("schema_version") != 1 or not isinstance(roster.get("people"), list):
        raise ValueError("Unexpected season roster JSON schema")

    mapping_rows = read_csv(MAPPING_CSV)
    review_rows = read_csv(REVIEW_CSV)
    source_index = read_json(SOURCE_INDEX_JSON)

    mappings_by_name: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in mapping_rows:
        mappings_by_name[(row.get("赛季", ""), row.get("去重后姓名", "").strip())].append(row)

    reviews_by_id = {row["照片编号"]: row for row in review_rows}
    pictures_by_sha = {picture["image_sha256"]: picture for picture in source_index.get("pictures", [])}

    targets = {
        "S22": official_s22_names(),
        "S23": s23_names(),
    }
    players: dict[str, dict[str, dict[str, str]]] = {"S22": {}, "S23": {}}
    missing: list[dict[str, str]] = []

    for season, names in targets.items():
        for name in sorted(names):
            choice, reason = choose_for_player(
                season, name, mappings_by_name, reviews_by_id, pictures_by_sha
            )
            if choice is None:
                missing.append({"season": season, "name": name, "reason": reason or "无可用照片"})
                continue

            image_sha = choice["sha256"]
            asset_relative = f"{season}/{image_sha}.jpg"
            asset_path = OUTPUT_ASSETS / season / f"{image_sha}.jpg"
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(choice["source_path"], asset_path)

            if sha256_file(asset_path) != image_sha:
                raise ValueError(f"Copied asset hash mismatch for {season}/{name}")

            occurrence = choice["occurrence"]
            players[season][name] = {
                "asset": asset_relative,
                "source_url": occurrence["source_url"],
                "source_date": occurrence["event_date"],
                "photo_id": choice["photo_id"],
                "sha256": image_sha,
                "season": season,
            }

    result = {"schema_version": 1, "players": players, "missing": missing}
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    output = build()
    print(
        json.dumps(
            {
                "S22": len(output["players"]["S22"]),
                "S23": len(output["players"]["S23"]),
                "missing": len(output["missing"]),
                "manifest": str(OUTPUT_JSON.relative_to(ROOT)),
            },
            ensure_ascii=False,
        )
    )
