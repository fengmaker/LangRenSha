"""Add current-season player photos while preserving the published baseline."""

from __future__ import annotations

import hashlib
import json
import shutil
import argparse
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_JSON = ROOT / "website" / "api" / "player_photos.json"
OUTPUT_ASSETS = ROOT / "website" / "assets" / "player-photos"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def formal_names(season: str) -> tuple[set[str], list[str]]:
    """Include every finalized game in the requested season."""
    game_paths = sorted((ROOT / "data/games" / season).glob("*/game.json"))
    if not game_paths:
        raise ValueError(f"{season} photo targets require final game records")
    names: set[str] = set()
    normalized_paths: list[str] = []
    for game_path in game_paths:
        relative_path = game_path.relative_to(ROOT).as_posix()
        game = read_json(game_path)
        players = game.get("players")
        if not isinstance(players, list) or not players:
            raise ValueError(f"{season} final game has no players: {relative_path}")
        missing_seats = [
            player for player in players
            if not isinstance(player, dict)
            or not isinstance(player.get("name"), str)
            or not player["name"].strip()
        ]
        if missing_seats:
            raise ValueError(f"{season} final game has unnamed players: {relative_path}")
        names.update(player["name"].strip() for player in players)
        normalized_paths.append(relative_path.replace("\\", "/"))
    return names, normalized_paths


def occurrence_key(occurrence: dict[str, Any]) -> tuple[int, str]:
    # Prefer the latest official photo when a newcomer has multiple reviewed images.
    return (-date.fromisoformat(occurrence["event_date"]).toordinal(), occurrence["source_url"])


def incremental_photo_choices(
    required_names: set[str],
    season: str,
) -> tuple[dict[str, dict[str, Any]], list[Path]]:
    """Read evidence only for target names missing from the stable baseline."""
    choices: dict[str, dict[str, Any]] = {}
    indexes: list[Path] = []
    if not required_names:
        return choices, indexes

    raw_root = (ROOT / "data/raw/weibo").resolve()
    index_name = f"{season}_增量照片名牌核对.json"
    for index_path in sorted((ROOT / "data/weibo").glob(f"*/{index_name}")):
        index = read_json(index_path)
        rows = [row for row in index.get("photos", []) if row.get("name", "").strip() in required_names]
        if not rows:
            continue
        if (index.get("season") != season
                or index.get("verification_method") != "assistant_nameplate_read"):
            raise ValueError(f"Invalid incremental photo nameplate index: {index_path}")

        manifest_path = (ROOT / index["source_manifest"]).resolve()
        if not manifest_path.is_relative_to(raw_root):
            raise ValueError("Incremental photo manifest must be inside data/raw/weibo")
        archive = read_json(manifest_path)
        if str(archive["request"]["uid"]) != "7525583841":
            raise ValueError("Incremental photos must come from the official Weibo account")
        posts = {str(post["post_id"]): post for post in archive["posts"]}

        for row in rows:
            name, label = row["name"].strip(), row["nameplate_text"].strip()
            alias_evidence = row.get("alias_evidence", "").strip()
            if not name or not label or (name.casefold() != label.casefold() and not alias_evidence):
                raise ValueError(f"Incremental photo needs a readable nameplate and name evidence: {name}")
            post = posts[str(row["post_id"])]
            season_number = season[1:]
            if (str(post.get("author_uid")) != "7525583841"
                    or (f"第{season_number}季" not in post.get("text", "")
                        and season not in post.get("text", ""))):
                raise ValueError(f"Incremental photo is not an official {season} post: {name}")
            number = row["image_index"]
            if type(number) is not int or not 1 <= number <= len(post["images"]):
                raise ValueError(f"Incremental photo image index is invalid: {name}")
            image = post["images"][number - 1]
            source = (ROOT / row["source_image"]).resolve()
            archived_source = (manifest_path.parent / image["file"].replace("\\", "/")).resolve()
            if (not source.is_relative_to(raw_root) or source != archived_source
                    or image.get("status") != "downloaded"
                    or image.get("sha256") != row["sha256"]
                    or sha256_file(source) != row["sha256"]
                    or row["source_url"] != post["post_url"]):
                raise ValueError(f"Incremental photo original post, path or hash mismatch: {name}")
            date.fromisoformat(row["source_date"])
            choice = {
                "photo_id": f"WB{row['post_id']}_{number:02d}",
                "sha256": row["sha256"],
                "source_path": source,
                "occurrence": {"event_date": row["source_date"], "source_url": row["source_url"]},
                "nameplate_text": label,
                "alias_evidence": alias_evidence,
                "source_index": index_path.relative_to(ROOT).as_posix(),
            }
            prior = choices.get(name)
            if prior is None or occurrence_key(choice["occurrence"]) < occurrence_key(prior["occurrence"]):
                choices[name] = choice
        indexes.append(index_path)
    return choices, indexes


def validate_baseline(manifest: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Keep existing name-to-photo IDs fixed and ensure every referenced asset survives."""
    players = manifest.get("players")
    if not isinstance(players, dict) or not players:
        raise ValueError("Photo baseline manifest has no player mapping")
    assets_root = OUTPUT_ASSETS.resolve()
    for season, records in players.items():
        if not isinstance(records, dict):
            raise ValueError(f"Photo baseline season is invalid: {season}")
        for name, record in records.items():
            if not isinstance(record, dict):
                raise ValueError(f"Photo baseline record is invalid: {season}/{name}")
            image_sha = record.get("sha256", "")
            asset = record.get("asset", "")
            if (record.get("season") != season
                    or len(image_sha) != 64
                    or any(character not in "0123456789abcdef" for character in image_sha)
                    or asset != f"{season}/{image_sha}.jpg"):
                raise ValueError(f"Photo baseline mapping is invalid: {season}/{name}")
            asset_path = (assets_root / asset).resolve()
            if (not asset_path.is_relative_to(assets_root)
                    or not asset_path.is_file()
                    or sha256_file(asset_path) != image_sha):
                raise ValueError(f"Cannot preserve invalid photo baseline record for {name}")
    return players


def record_for_choice(season: str, choice: dict[str, Any]) -> dict[str, Any]:
    occurrence = choice["occurrence"]
    image_sha = choice["sha256"]
    record = {
        "asset": f"{season}/{image_sha}.jpg",
        "source_url": occurrence["source_url"],
        "source_date": occurrence["event_date"],
        "photo_id": choice["photo_id"],
        "sha256": image_sha,
        "season": season,
    }
    if choice.get("alias_evidence"):
        record["name_mapping"] = {
            "type": "verified_incremental_nameplate_alias",
            "photo_name": choice["nameplate_text"],
            "evidence": choice["alias_evidence"],
        }
    return record


def copy_asset(season: str, choice: dict[str, Any]) -> None:
    image_sha = choice["sha256"]
    asset_path = OUTPUT_ASSETS / season / f"{image_sha}.jpg"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    if not asset_path.is_file() or sha256_file(asset_path) != image_sha:
        shutil.copyfile(choice["source_path"], asset_path)
    if sha256_file(asset_path) != image_sha:
        raise ValueError(f"Copied asset hash mismatch for {season}/{image_sha}")


def build(season: str = "S23") -> dict[str, Any]:
    from scripts.season_config import season_codes
    if season not in season_codes(ROOT):
        raise ValueError(f"Unsupported photo season: {season}")
    if not OUTPUT_JSON.is_file():
        raise ValueError(f"Photo baseline manifest is required: {OUTPUT_JSON}")
    old_manifest = read_json(OUTPUT_JSON)
    baseline_players = validate_baseline(old_manifest)
    players = {season: dict(records) for season, records in baseline_players.items()}

    target_names, _ = formal_names(season)
    new_names = target_names - set(players.get(season, {}))
    incremental_choices, _ = incremental_photo_choices(new_names, season)

    missing: list[dict[str, str]] = []
    for name in sorted(target_names):
        current_record = players.get(season, {}).get(name)
        if current_record is not None:
            continue
        choice = incremental_choices.get(name)
        if choice is None:
            missing.append({"season": season, "name": name, "reason": "没有适用于新增选手的核对照片"})
            continue
        players.setdefault(season, {})[name] = record_for_choice(season, choice)
        copy_asset(season, choice)

    old_missing = old_manifest.get("missing", [])
    retained_missing = [item for item in old_missing if item.get("season") != season]
    result = {"schema_version": 1, "players": players, "missing": [*retained_missing, *missing]}
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return result


if __name__ == "__main__":
    from scripts.season_config import season_codes
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", choices=season_codes(ROOT), default="S23")
    args = parser.parse_args()
    output = build(args.season)
    target_names, _ = formal_names(args.season)
    missing = [item["name"] for item in output["missing"] if item.get("season") == args.season]
    covered = len(target_names) - len(missing)
    print(
        json.dumps(
            {
                "season": args.season,
                "manifest_entries": len(output["players"].get(args.season, {})),
                "target_players": len(target_names),
                "covered": covered,
                "coverage_rate": round(covered / len(target_names), 6) if target_names else 1,
                "missing": missing,
                "manifest": str(OUTPUT_JSON.relative_to(ROOT)),
                "assets": str(OUTPUT_ASSETS.relative_to(ROOT)),
            },
            ensure_ascii=False,
        )
    )
