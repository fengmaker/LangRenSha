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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WEIBO_ROOT = ROOT / "data" / "weibo" / "2026-05-26_2026-10-20"
MAPPING_CSV = WEIBO_ROOT / "参赛名单" / "人名去重_照片映射.csv"
SOURCE_INDEX_JSON = WEIBO_ROOT / "人名复核" / "照片人名_来源索引.json"
REVIEW_CSV = WEIBO_ROOT / "人名复核" / "S22-S23_照片人名_人工复核.csv"
S23_PROGRESS_JSON = ROOT / "data" / "reports" / "S23_逐局复核进度.json"
S23_SCHEDULE_CSV = WEIBO_ROOT / "比赛排班.csv"

OUTPUT_JSON = ROOT / "website" / "api" / "player_photos.json"
OUTPUT_ASSETS = ROOT / "website" / "assets" / "player-photos"
OUTPUT_REPORT = ROOT / "data" / "reports" / "S23_网站照片准备验收.json"

APPROVED_STATUSES = {"确认无误", "已修正"}
PHASE_PRIORITY = {"决赛周": 0, "正赛": 1, "表演赛": 2}
S23_ALIAS_EVIDENCE = {
    "天天的星_": {
        "photo_name": "天星",
        "photo_id": "P0205",
        "source_url": "https://m.weibo.cn/detail/5349233155638005",
        "source_date": "2026-10-01",
        "evidence": (
            "S23第4期官方阵容排班与人工确认照片P0205来自同一官方微博帖；"
            "P0205原图名牌经人工确认是‘天星’，该帖正文与同日排班均列canonical handle‘天天的星_’。"
        ),
    },
}


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


def s23_candidate_names() -> tuple[set[str], list[str]]:
    """Use canonical names in the 75 reviewed candidate dossiers, not the Weibo roster."""
    progress = read_json(S23_PROGRESS_JSON)
    dossier_paths = progress.get("candidate_dossiers")
    if progress.get("planned") != 75 or not isinstance(dossier_paths, list) or len(dossier_paths) != 75:
        raise ValueError("S23 photo targets require the 75 candidate dossiers in the review progress file")

    names: set[str] = set()
    normalized_paths: list[str] = []
    for relative_path in dossier_paths:
        if not isinstance(relative_path, str):
            raise ValueError("S23 candidate dossier paths must be strings")
        dossier_path = (ROOT / relative_path).resolve()
        if not dossier_path.is_relative_to((ROOT / "data" / "games" / "S23").resolve()):
            raise ValueError(f"S23 candidate dossier path is outside data/games/S23: {relative_path}")
        if not dossier_path.is_file():
            raise FileNotFoundError(dossier_path)
        dossier = read_json(dossier_path)
        seats = dossier.get("seats")
        if not isinstance(seats, list) or not seats:
            raise ValueError(f"S23 candidate dossier has no seats: {relative_path}")
        missing_seats = [
            seat for seat in seats
            if not isinstance(seat, dict)
            or not isinstance(seat.get("name"), str)
            or not seat["name"].strip()
        ]
        if missing_seats:
            raise ValueError(f"S23 candidate dossier has unnamed seats: {relative_path}")
        names.update(seat["name"].strip() for seat in seats)
        normalized_paths.append(relative_path.replace("\\", "/"))

    return names, normalized_paths


def alias_is_supported(
    canonical_name: str,
    alias: dict[str, str],
    choice: dict[str, Any],
    schedule_rows: list[dict[str, str]],
    review_rows: dict[str, dict[str, str]],
) -> bool:
    """Require the explicit same-post schedule and human-reviewed photo evidence."""
    if choice["photo_id"] != alias["photo_id"]:
        return False
    picture = choice["picture"]
    if picture.get("season") != "S23" or picture.get("image_sha256") != choice["sha256"]:
        return False

    review = review_rows.get(alias["photo_id"], {})
    if (
        review.get("人工确认") not in APPROVED_STATUSES
        or review.get("确认后的名字", "").strip() != alias["photo_name"]
        or review.get("图片SHA256", "").strip() != choice["sha256"]
    ):
        return False

    same_post_picture = any(
        item.get("source_url") == alias["source_url"]
        and item.get("event_date") == alias["source_date"]
        and item.get("text_players")
        and canonical_name in item["text_players"].split("、")
        for item in picture.get("occurrences", [])
    )
    same_day_schedule = any(
        row.get("赛季") == "S23"
        and row.get("比赛日期") == alias["source_date"]
        and row.get("原帖链接") == alias["source_url"]
        and canonical_name in row.get("选手", "").split("、")
        for row in schedule_rows
    )
    return same_post_picture and same_day_schedule


def existing_s22_players() -> dict[str, dict[str, str]] | None:
    """Keep a prior S22 photo index byte-for-byte at the record level when present."""
    if not OUTPUT_JSON.is_file():
        return None
    prior = read_json(OUTPUT_JSON)
    players = prior.get("players", {})
    s22 = players.get("S22")
    if not isinstance(s22, dict):
        raise ValueError("Existing photo manifest has no S22 index to preserve")
    if set(s22) != official_s22_names():
        raise ValueError("Existing S22 photo index does not match the retained S22 dossiers")
    for name, record in s22.items():
        asset = record.get("asset", "")
        asset_path = OUTPUT_ASSETS / asset
        if (
            record.get("season") != "S22"
            or not asset.startswith("S22/")
            or not asset_path.is_file()
            or sha256_file(asset_path) != record.get("sha256")
        ):
            raise ValueError(f"Cannot preserve invalid S22 photo record for {name}")
    return s22


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
    mapping_rows = read_csv(MAPPING_CSV)
    review_rows = read_csv(REVIEW_CSV)
    source_index = read_json(SOURCE_INDEX_JSON)
    schedule_rows = read_csv(S23_SCHEDULE_CSV)

    mappings_by_name: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in mapping_rows:
        mappings_by_name[(row.get("赛季", ""), row.get("去重后姓名", "").strip())].append(row)

    reviews_by_id = {row["照片编号"]: row for row in review_rows}
    pictures_by_sha = {picture["image_sha256"]: picture for picture in source_index.get("pictures", [])}

    s23_names, candidate_dossiers = s23_candidate_names()
    preserved_s22 = existing_s22_players()
    old_manifest = read_json(OUTPUT_JSON) if OUTPUT_JSON.is_file() else {"players": {}, "missing": []}
    prior_players = old_manifest.get("players", {})
    players: dict[str, dict[str, dict[str, Any]]] = {}
    if preserved_s22 is not None:
        players["S22"] = preserved_s22
    else:
        players["S22"] = {}
    for season, records in prior_players.items():
        if season not in {"S22", "S23"} and isinstance(records, dict):
            players[season] = dict(records)
    players["S23"] = dict(prior_players.get("S23", {}))
    if preserved_s22 is None:
        # Keep fresh builds functional; subsequent builds preserve this exact S22 index.
        for name in sorted(official_s22_names()):
            choice, reason = choose_for_player("S22", name, mappings_by_name, reviews_by_id, pictures_by_sha)
            if choice is None:
                raise ValueError(f"Cannot initialize the required S22 photo index: {name}: {reason}")
            players["S22"][name] = record_for_choice("S22", choice)
            copy_asset("S22", choice)

    missing: list[dict[str, str]] = []
    direct_count = 0
    alias_records: list[dict[str, str]] = []

    for name in sorted(s23_names):
        current_record = players["S23"].get(name)
        if current_record:
            existing_alias = current_record.get("name_mapping")
            alias = S23_ALIAS_EVIDENCE.get(name) if existing_alias else None
            if alias:
                alias_choice, _ = choose_for_player(
                    "S23", alias["photo_name"], mappings_by_name, reviews_by_id, pictures_by_sha
                )
                if (
                    alias_choice is None
                    or not alias_is_supported(name, alias, alias_choice, schedule_rows, reviews_by_id)
                    or existing_alias.get("type") != "confirmed_same_post_alias"
                    or existing_alias.get("photo_name") != alias["photo_name"]
                    or existing_alias.get("evidence_url") != alias["source_url"]
                    or existing_alias.get("evidence_date") != alias["source_date"]
                    or existing_alias.get("evidence") != alias["evidence"]
                    or current_record.get("photo_id") != alias["photo_id"]
                    or current_record.get("sha256") != alias_choice["sha256"]
                    or current_record.get("asset") != f"S23/{alias_choice['sha256']}.jpg"
                    or current_record.get("source_url") != alias["source_url"]
                    or current_record.get("source_date") != alias["source_date"]
                    or not (OUTPUT_ASSETS / current_record.get("asset", "")).is_file()
                    or sha256_file(OUTPUT_ASSETS / current_record.get("asset", "")) != alias_choice["sha256"]
                ):
                    raise ValueError(f"Existing S23 alias record is not backed by its reviewed source: {name}")
                alias_records.append(alias_record_for(name, alias, alias_choice, current_record["asset"]))
            else:
                if not manifest_record_is_reviewed(
                    "S23", name, current_record, mappings_by_name, reviews_by_id,
                    pictures_by_sha, OUTPUT_ASSETS,
                ):
                    raise ValueError(f"Existing S23 photo record is not backed by its reviewed source: {name}")
                direct_count += 1
            continue

        choice, reason = choose_for_player("S23", name, mappings_by_name, reviews_by_id, pictures_by_sha)
        mapping_kind = "exact_name"
        alias = None
        if choice is None and not mappings_by_name.get(("S23", name)):
            alias = S23_ALIAS_EVIDENCE.get(name)
            if alias:
                choice, reason = choose_for_player(
                    "S23", alias["photo_name"], mappings_by_name, reviews_by_id, pictures_by_sha
                )
                if choice is not None and alias_is_supported(name, alias, choice, schedule_rows, reviews_by_id):
                    mapping_kind = "confirmed_same_post_alias"
                else:
                    choice = None

        if choice is None:
            missing.append({"season": "S23", "name": name, "reason": reason or "无可用照片"})
            continue

        players["S23"][name] = record_for_choice("S23", choice)
        copy_asset("S23", choice)
        if alias:
            alias_record = alias_record_for(name, alias, choice, players["S23"][name]["asset"])
            players["S23"][name]["name_mapping"] = {
                "type": mapping_kind,
                "photo_name": alias["photo_name"],
                "evidence_url": alias["source_url"],
                "evidence_date": alias["source_date"],
                "evidence": alias["evidence"],
            }
            alias_records.append(alias_record)
        else:
            direct_count += 1

    retained_missing = [
        item for item in old_manifest.get("missing", [])
        if item.get("season") != "S23"
    ]
    result = {
        "schema_version": 1,
        "players": players,
        "missing": [*retained_missing, *missing],
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    covered = len(s23_names) - len(missing)
    missing_names = {item["name"] for item in missing}
    OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_REPORT.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "season": "S23",
                "target_source": "data/reports/S23_逐局复核进度.json candidate_dossiers canonical seat names",
                "candidate_dossier_count": len(candidate_dossiers),
                "candidate_dossiers": candidate_dossiers,
                "target_player_count": len(s23_names),
                "target_player_names": sorted(s23_names),
                "directly_matched_count": direct_count,
                "alias_matched_count": len(alias_records),
                "covered_player_count": covered,
                "covered_player_names": sorted(s23_names - missing_names),
                "coverage_rate": round(covered / len(s23_names), 6) if s23_names else 1,
                "missing": missing,
                "aliases_used": alias_records,
                "manifest": str(OUTPUT_JSON.relative_to(ROOT)).replace("\\", "/"),
                "assets": str(OUTPUT_ASSETS.relative_to(ROOT)).replace("\\", "/"),
                "retained_manifest_player_counts": {
                    season: len(records) for season, records in players.items()
                },
                "inputs": [
                    str(S23_PROGRESS_JSON.relative_to(ROOT)).replace("\\", "/"),
                    str(MAPPING_CSV.relative_to(ROOT)).replace("\\", "/"),
                    str(REVIEW_CSV.relative_to(ROOT)).replace("\\", "/"),
                    str(SOURCE_INDEX_JSON.relative_to(ROOT)).replace("\\", "/"),
                    str(S23_SCHEDULE_CSV.relative_to(ROOT)).replace("\\", "/"),
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def record_for_choice(season: str, choice: dict[str, Any]) -> dict[str, Any]:
    occurrence = choice["occurrence"]
    image_sha = choice["sha256"]
    return {
        "asset": f"{season}/{image_sha}.jpg",
        "source_url": occurrence["source_url"],
        "source_date": occurrence["event_date"],
        "photo_id": choice["photo_id"],
        "sha256": image_sha,
        "season": season,
    }


def alias_record_for(
    canonical_name: str,
    alias: dict[str, str],
    choice: dict[str, Any],
    asset: str,
) -> dict[str, str]:
    return {
        "canonical_name": canonical_name,
        "photo_name": alias["photo_name"],
        "photo_id": alias["photo_id"],
        "sha256": choice["sha256"],
        "source_url": alias["source_url"],
        "source_date": alias["source_date"],
        "evidence": alias["evidence"],
        "asset": asset,
    }


def copy_asset(season: str, choice: dict[str, Any]) -> None:
    image_sha = choice["sha256"]
    asset_path = OUTPUT_ASSETS / season / f"{image_sha}.jpg"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    if not asset_path.is_file() or sha256_file(asset_path) != image_sha:
        shutil.copyfile(choice["source_path"], asset_path)
    if sha256_file(asset_path) != image_sha:
        raise ValueError(f"Copied asset hash mismatch for {season}/{image_sha}")


def manifest_record_is_reviewed(
    season: str,
    name: str,
    record: dict[str, Any],
    mappings_by_name: dict[tuple[str, str], list[dict[str, str]]],
    reviews_by_id: dict[str, dict[str, str]],
    pictures_by_sha: dict[str, dict[str, Any]],
    assets_root: Path,
) -> bool:
    """Validate a retained manifest entry without changing its selected image."""
    photo_id = record.get("photo_id", "")
    image_sha = record.get("sha256", "")
    if record.get("season") != season or record.get("asset") != f"{season}/{image_sha}.jpg":
        return False
    mapping = next((
        row for row in mappings_by_name.get((season, name), [])
        if row.get("照片编号") == photo_id
        and row.get("去重后姓名", "").strip() == name
        and row.get("原人工确认状态") in APPROVED_STATUSES
        and row.get("纳入参赛名单") == "是"
        and row.get("图片SHA256", "").strip() == image_sha
    ), None)
    review = reviews_by_id.get(photo_id, {})
    picture = pictures_by_sha.get(image_sha)
    if (
        mapping is None
        or review.get("人工确认") not in APPROVED_STATUSES
        or review.get("确认后的名字", "").strip() != name
        or review.get("图片SHA256", "").strip() != image_sha
        or picture is None
        or picture.get("season") != season
    ):
        return False
    if not any(
        item.get("source_url") == record.get("source_url")
        and item.get("event_date") == record.get("source_date")
        for item in picture.get("occurrences", [])
    ):
        return False
    asset_path = assets_root / record["asset"]
    return asset_path.is_file() and sha256_file(asset_path) == image_sha


if __name__ == "__main__":
    output = build()
    report = read_json(OUTPUT_REPORT)
    print(
        json.dumps(
            {
                "S22": len(output["players"]["S22"]),
                "S23_manifest_entries": len(output["players"]["S23"]),
                "S23_target_players": report["target_player_count"],
                "S23_covered": report["covered_player_count"],
                "S23_coverage_rate": report["coverage_rate"],
                "S23_missing": [item["name"] for item in report["missing"]],
                "S23_aliases": report["aliases_used"],
                "manifest": str(OUTPUT_JSON.relative_to(ROOT)),
                "report": str(OUTPUT_REPORT.relative_to(ROOT)),
                "assets": str(OUTPUT_ASSETS.relative_to(ROOT)),
            },
            ensure_ascii=False,
        )
    )
