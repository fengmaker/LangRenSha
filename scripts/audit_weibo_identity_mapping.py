"""Audit the existing S22/S23 Weibo name/photo chain without changing source data.

Rebuild schedule and reviewed roster exports in a temporary directory, verify
every source-image occurrence, and check website photos against reviewed names
and formal seat-name coverage. This is a consistency audit, not a new visual
review of names or seat numbers. No network or database access is used.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import export_reviewed_weibo_roster
import export_weibo_schedule
from website import prepare_photos

WEIBO = ROOT / "data/weibo/2026-05-26_2026-10-20"
MANIFEST = ROOT / "data/raw/weibo/2026-05-26_2026-10-20_京城大师赛_UID7525583841/manifest.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit() -> dict:
    review_root = WEIBO / "人名复核"
    roster_root = WEIBO / "参赛名单"
    review_file = review_root / "S22-S23_照片人名_人工复核.csv"
    evidence_file = review_root / "照片人名_候选结果.json"
    index_file = review_root / "照片人名_来源索引.json"
    mapping_file = roster_root / "人名去重_照片映射.csv"
    schedule_file = WEIBO / "比赛排班.csv"
    photo_file = ROOT / "website/api/player_photos.json"
    protected = [MANIFEST, review_file, evidence_file, index_file, mapping_file,
                 schedule_file, photo_file, roster_root / "参赛人名名单.json"]
    before = {p: digest(p) for p in protected}
    errors: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    manifest = read_json(MANIFEST)
    index = read_json(index_file)
    candidate = read_json(evidence_file)
    reviews = read_csv(review_file)
    mappings = read_csv(mapping_file)
    schedules = read_csv(schedule_file)
    photos = read_json(photo_file)
    pictures = index["pictures"]
    ids = [p["picture_id"] for p in pictures]
    check(len(ids) == len(set(ids)), "来源索引的照片编号重复")
    check(set(ids) == {p["id"] for p in candidate["pictures"]}, "候选照片与来源索引编号不一致")
    check(len(reviews) == len(ids) == len(mappings), "复核、来源索引与映射行数不一致")
    check({r["照片编号"] for r in reviews} == set(ids), "人工复核编号与来源索引不一致")
    check({r["照片编号"] for r in mappings} == set(ids), "映射编号与来源索引不一致")
    check(Path(index["source_manifest"]).resolve() == MANIFEST.resolve(), "来源索引指向其他归档")

    posts = {p["post_id"]: p for p in manifest["posts"]}
    schedule_by_post = {r["原帖链接"].rsplit("/", 1)[-1]: r for r in schedules}
    expected_occurrences = set()
    for post_id in schedule_by_post:
        check(post_id in posts, f"排班原帖未归档：{post_id}")
        if post_id in posts:
            expected_occurrences.update((post_id, i) for i in range(1, len(posts[post_id]["images"]) + 1))
    seen_occurrences = set()
    hash_cache: dict[Path, str] = {}
    for picture in pictures:
        pid = picture["picture_id"]
        source = Path(picture["source_image"])
        check(source.is_file() and digest(source) == picture["image_sha256"], f"代表原图缺失或哈希不符：{pid}")
        check((review_root / picture["crop_file"]).is_file(), f"名牌裁图缺失：{pid}")
        for event in picture["occurrences"]:
            key = (event["post_id"], event["image_index"])
            check(key not in seen_occurrences, f"照片引用重复：{key}")
            seen_occurrences.add(key)
            post = posts.get(event["post_id"], {})
            image_number = event["image_index"] - 1
            images = post.get("images", [])
            check(0 <= image_number < len(images), f"引用图片序号越界：{pid}/{key}")
            if not 0 <= image_number < len(images):
                continue
            image = images[image_number]
            image_path = MANIFEST.parent / event["image_file"]
            if image_path.is_file() and image_path not in hash_cache:
                hash_cache[image_path] = digest(image_path)
            check(image_path.is_file() and hash_cache.get(image_path) == picture["image_sha256"]
                  == image.get("sha256"), f"原图引用哈希不符：{pid}/{key}")
            check(image_path.resolve() == (MANIFEST.parent / image.get("file", "")).resolve(),
                  f"原图引用路径不符：{pid}/{key}")
            schedule = schedule_by_post.get(event["post_id"], {})
            check(event["source_url"] == post.get("post_url") == schedule.get("原帖链接")
                  and event["event_date"] == schedule.get("比赛日期")
                  and picture["season"] == schedule.get("赛季"), f"引用赛季、赛日或原帖不符：{pid}/{key}")
    check(seen_occurrences == expected_occurrences, "来源索引未恰好覆盖排班帖全部配图")

    # Export into temporary paths: never overwrite accepted human review or maps.
    # The export format uses relative paths, so Windows needs the same drive.
    with TemporaryDirectory(prefix="weibo-mapping-audit-", dir=ROOT) as temporary:
        temporary_root = Path(temporary)
        export_weibo_schedule.export(MANIFEST, temporary_root / "schedule")
        regenerated = read_csv(temporary_root / "schedule/比赛排班.csv")
        # Relative evidence paths differ with the destination; references are
        # checked directly against the manifest above.
        def stable(rows):
            return [{k: v for k, v in row.items() if k not in {"正文原件", "图片"}} for row in rows]
        check(stable(regenerated) == stable(schedules), "从原件重建的排班与现有排班不一致")
        summary = export_reviewed_weibo_roster.export(review_file, evidence_file, temporary_root / "roster")
        for name in ("人名去重_照片映射.csv", "京城大师赛_S22至今_参赛人名总表.csv",
                     "已排除_仅7月3日娱乐赛人员.csv"):
            check(read_csv(temporary_root / "roster" / name) == read_csv(roster_root / name), f"从人工复核重建结果不一致：{name}")
        for name in ("京城大师赛_S22至今_参赛人名名单.txt", "S22_参赛人名名单.txt", "S23_参赛人名名单.txt"):
            check((temporary_root / "roster" / name).read_text("utf-8-sig") ==
                  (roster_root / name).read_text("utf-8-sig"), f"重建名单不一致：{name}")
        accepted = read_json(roster_root / "参赛人名名单.json")
        rebuilt = read_json(temporary_root / "roster/参赛人名名单.json")
        for key in ("people", "excluded_people", "groups", "photo_name_mapping"):
            check(accepted[key] == rebuilt[key], f"结构化名单不一致：{key}")

    mappings_by_name = defaultdict(list)
    for row in mappings:
        mappings_by_name[(row["赛季"], row["去重后姓名"])].append(row)
    reviews_by_id = {r["照片编号"]: r for r in reviews}
    pictures_by_sha = {p["image_sha256"]: p for p in pictures}
    coverage = {}
    aliases = []
    for season, records in photos["players"].items():
        if season not in {"S22", "S23"}:
            continue
        for name, record in records.items():
            if record.get("name_mapping"):
                alias = prepare_photos.S23_ALIAS_EVIDENCE.get(name) if season == "S23" else None
                choice = None
                if alias:
                    choice, _ = prepare_photos.choose_for_player(season, alias["photo_name"],
                        mappings_by_name, reviews_by_id, pictures_by_sha)
                supported = bool(alias and choice and prepare_photos.alias_is_supported(
                    name, alias, choice, schedules, reviews_by_id))
                if supported:
                    expected = prepare_photos.record_for_choice(season, choice)
                    expected["name_mapping"] = {"type": "confirmed_same_post_alias", "photo_name": alias["photo_name"],
                        "evidence_url": alias["source_url"], "evidence_date": alias["source_date"], "evidence": alias["evidence"]}
                    supported = record == expected
                asset = ROOT / "website/assets/player-photos" / record["asset"]
                check(supported and asset.is_file() and digest(asset) == record["sha256"], f"别名照片缺少完整证据：{season}/{name}")
                aliases.append({"season": season, "name": name, **record["name_mapping"]})
            else:
                check(prepare_photos.manifest_record_is_reviewed(season, name, record,
                    mappings_by_name, reviews_by_id, pictures_by_sha, ROOT / "website/assets/player-photos"),
                    f"网站照片未通过人工复核及原图校验：{season}/{name}")
        dossier_paths = sorted((ROOT / "data/games" / season).glob("*/dossier.json"))
        names = {s["name"] for p in dossier_paths for s in read_json(p)["seats"] if s.get("name")}
        missing = sorted(names - set(records))
        check(not missing, f"正式座位姓名缺少照片：{season}/{missing}")
        coverage[season] = {"formal_games": len(dossier_paths), "formal_player_names": len(names),
                            "manifest_entries": len(records), "covered": len(names) - len(missing), "missing": missing}

    unchanged = all(digest(p) == sha for p, sha in before.items())
    check(unchanged, "验收过程中来源文件发生变化")
    return {"schema_version": 1, "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "passed" if not errors else "needs_attention", "errors": errors,
            "archive_window": manifest["request"], "archive_counts": manifest["counts"],
            "schedule_posts": len(schedules), "unique_pictures": len(pictures),
            "image_occurrences_checked": len(seen_occurrences), "source_images_hashed": len(hash_cache),
            "human_status_counts": dict(Counter(r["人工确认"] for r in reviews)),
            "pending_photo_ids": [r["照片编号"] for r in reviews if r["人工确认"] == "待确认"],
            "roster_people": summary["unique_people"], "roster_season_people": summary["season_people"],
            "excluded_people": summary["excluded_people_names"], "formal_photo_coverage": coverage,
            "aliases": aliases, "source_files_unchanged": unchanged,
            "input_sha256": {p.relative_to(ROOT).as_posix(): sha for p, sha in before.items()},
            "limits": ["仅验收现有S22/S23批次；未扩展采集日期、联网、写库或发布。",
                       "检查引用、复核状态、映射重建及正式座位姓名照片覆盖；未重新逐图识读或逐局确认座位。",
                       "待确认照片保持待确认；同名已确认记录不能确认此张照片。"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "data/reports/微博_姓名照片映射验收.json")
    args = parser.parse_args()
    result = audit()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    brief = {k: v for k, v in result.items() if k not in {"input_sha256", "aliases", "errors"}}
    brief.update(error_count=len(result["errors"]), errors=result["errors"][:20])
    print(json.dumps(brief, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
