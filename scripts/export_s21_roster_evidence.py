"""Create an S21-only Weibo schedule and image-source evidence index.

This script consumes the existing offline schedule export and archive manifest.
It deliberately does not map a portrait to a name based on the order of players
in the post body. Only manually viewed nameplate observations are included as
image-level name evidence.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


SEASON = "S21"
SEASON_START = date(2026, 2, 24)
SEASON_END = date(2026, 5, 15)
TARGET_UID = "7525583841"
S21_MARKER_RE = re.compile(r"(?<![A-Za-z0-9])S\s*21(?!\d)|第\s*21\s*季", re.IGNORECASE)
SPECIAL_EVENT_RE = re.compile(r"京师和Ta的朋友们|全员阵容海报|朋友搭档满员集结")

DEFAULT_OUTPUT_DIR = Path("data/weibo/2026-02-24_2026-05-26")
DEFAULT_ARCHIVE_DIR = Path(
    "data/raw/weibo/2026-02-24_2026-05-26_京城大师赛_UID7525583841"
)
DEFAULT_NAME_MAP = Path(
    "data/weibo/2026-05-26_2026-10-20/参赛名单/人名去重_照片映射.csv"
)

# These are the only images actually opened with view_image during this run.
# The labels below are direct visual transcriptions, not computer OCR. The
# February showmatch observations remain local history and are excluded from
# this round's regular/finals review counts.
MANUAL_NAMEPLATE_READS: dict[str, dict[str, Any]] = {
    "images/2026-02/2026-02-24_16-01-56_S21_期数待核_阵容公告__WB5269877281786142_图01.jpg": {
        "read_text": "JY",
        "read_status": "已识读_缩写",
        "label_type": "图上缩写",
        "normalized_name": "JY",
        "normalization_status": "复用既有确认规范名",
        "read_note": "原图右侧布偶衣身竖排字母可读为J、Y；图片没有显示完整中文姓名，本条不依据人像判断身份。",
        "view_method": "view_image查看原图",
    },
    "images/2026-02/2026-02-24_16-01-56_S21_期数待核_阵容公告__WB5269877281786142_图02.jpg": {
        "read_text": "崔丁",
        "read_status": "已识读_待核完整规范名",
        "label_type": "图上姓名文字",
        "normalized_name": "",
        "normalization_status": "待核",
        "read_note": "原图右侧布偶衣身可直接读到“崔丁”；未据此将图像连到正文名单中的任何账号，需主代理核完整规范名或别名。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图01.jpg": {
        "read_text": "JY", "read_status": "已识读_复用既有规范名", "label_type": "图上缩写",
        "normalized_name": "JY", "normalization_status": "复用既有确认规范名",
        "read_note": "原图右侧布偶衣身竖排字母清楚显示JY；同名规范名沿用S22/S23已确认记录。只依名牌文字记录，不作人像判断或座位映射。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图02.jpg": {
        "read_text": "海王慕", "read_status": "已识读_复用既有规范名", "label_type": "图上姓名文字",
        "normalized_name": "海王慕", "normalization_status": "复用既有确认规范名",
        "read_note": "布偶衣身文字清楚显示“海王慕”；同名规范名沿用S22/S23已确认记录。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图03.jpg": {
        "read_text": "Jamie", "read_status": "已识读_复用既有规范名", "label_type": "图上姓名文字",
        "normalized_name": "Jamie", "normalization_status": "复用既有确认规范名",
        "read_note": "布偶衣身英文字母清楚显示“Jamie”；同名规范名沿用S22/S23已确认记录。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图04.jpg": {
        "read_text": "KS", "read_status": "已识读_复用既有规范名", "label_type": "图上缩写",
        "normalized_name": "KS", "normalization_status": "复用既有确认规范名",
        "read_note": "布偶衣身竖排字母清楚显示K、S；同名规范名沿用S22/S23已确认记录。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图05.jpg": {
        "read_text": "圈圈", "read_status": "已识读_复用既有规范名", "label_type": "图上姓名文字",
        "normalized_name": "圈圈", "normalization_status": "复用既有确认规范名",
        "read_note": "布偶衣身文字清楚显示两个“圈”字；同名规范名沿用S22/S23已确认记录。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图06.jpg": {
        "read_text": "李舒服", "read_status": "已识读_复用既有规范名", "label_type": "图上姓名文字",
        "normalized_name": "李舒服", "normalization_status": "复用既有确认规范名",
        "read_note": "布偶衣身文字清楚显示“李舒服”；同名规范名沿用S22/S23已确认记录。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图07.jpg": {
        "read_text": "陈俊洁", "read_status": "已识读_复用既有规范名", "label_type": "图上姓名文字",
        "normalized_name": "陈俊洁", "normalization_status": "复用既有确认规范名",
        "read_note": "布偶衣身文字清楚显示“陈俊洁”；同名规范名沿用S22/S23已确认记录。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图08.jpg": {
        "read_text": "郭小炜", "read_status": "已识读_复用既有规范名", "label_type": "图上姓名文字",
        "normalized_name": "郭小炜", "normalization_status": "复用既有确认规范名",
        "read_note": "布偶衣身文字清楚显示“郭小炜”；同名规范名沿用S22/S23已确认记录。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图09.jpg": {
        "read_text": "陈明峻", "read_status": "已识读_复用既有规范名", "label_type": "图上姓名文字",
        "normalized_name": "陈明峻", "normalization_status": "复用既有确认规范名",
        "read_note": "布偶衣身文字清楚显示“陈明峻”；同名规范名沿用S22/S23已确认记录。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图10.jpg": {
        "read_text": "翼风", "read_status": "已识读_复用既有规范名", "label_type": "图上姓名文字",
        "normalized_name": "翼风", "normalization_status": "复用既有确认规范名",
        "read_note": "布偶衣身文字清楚显示“翼风”；同名规范名沿用S22/S23已确认记录。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图11.jpg": {
        "read_text": "牛肉干", "read_status": "已识读_复用既有规范名", "label_type": "图上姓名文字",
        "normalized_name": "牛肉干", "normalization_status": "复用既有确认规范名",
        "read_note": "布偶衣身文字清楚显示“牛肉干”；同名规范名沿用S22/S23已确认记录。",
        "view_method": "view_image查看原图",
    },
    "images/2026-03/2026-03-03_15-30-38_S21_第01期_阵容公告__WB5272406119153984_图12.jpg": {
        "read_text": "小张", "read_status": "已识读_复用既有规范名", "label_type": "图上姓名文字",
        "normalized_name": "小张", "normalization_status": "复用既有确认规范名",
        "read_note": "布偶衣身文字清楚显示“小张”；同名规范名沿用S22/S23已确认记录。",
        "view_method": "view_image查看原图",
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON顶层不是对象：{path}")
    return value


def _rel(value: Any) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _project_ref(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _load_confirmed_names(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    by_label: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            if row.get("原人工确认状态") != "确认无误":
                continue
            label = (row.get("原图名字") or "").strip()
            normalized = (row.get("去重后姓名") or "").strip()
            if label and normalized:
                by_label.setdefault(label, {
                    "normalized_name": normalized,
                    "mapping_file": path.as_posix(),
                    "mapping_row": str(line_number),
                    "mapping_photo_id": row.get("照片编号", ""),
                    "mapping_season": row.get("赛季", ""),
                    "mapping_sha256": row.get("图片SHA256", ""),
                })
    return by_label


def _load_crop_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    value = _read_json(path)
    items = value.get("photos")
    if not isinstance(items, list):
        return {}
    return {
        _rel(item.get("archive_file")): item
        for item in items
        if isinstance(item, dict) and item.get("archive_file")
    }


def _load_manual_nameplate_reads(
    path: Path,
    confirmed_names: dict[str, dict[str, str]],
    crop_index: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    reads = {key: dict(value) for key, value in MANUAL_NAMEPLATE_READS.items()}
    if path.is_file():
        value = _read_json(path)
        items = value.get("records")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict) or not item.get("archive_file"):
                    continue
                key = _rel(item["archive_file"])
                observation = dict(reads.get(key, {}))
                observation.update({
                    field: item[field]
                    for field in (
                        "read_text", "read_status", "label_type", "normalized_name", "normalization_status",
                        "read_note", "view_method", "viewed_source", "crop_file", "crop_rect",
                        "contact_sheet_file", "review_batch", "included_for_review", "scope_category",
                    )
                    if field in item
                })
                reads[key] = observation
    for key, observation in reads.items():
        crop = crop_index.get(key)
        if crop:
            for field in ("crop_file", "crop_rect", "contact_sheet_file", "review_batch", "crop_note"):
                if field in crop and field not in observation:
                    observation[field] = crop[field]
        if observation.get("read_status", "").startswith("已识读") and observation.get("read_text"):
            confirmed = confirmed_names.get(str(observation["read_text"]).strip())
            if confirmed and not observation.get("normalized_name"):
                observation["normalized_name"] = confirmed["normalized_name"]
                observation["normalization_status"] = "复用既有确认规范名"
            elif not confirmed and not observation.get("normalized_name"):
                observation["normalized_name"] = ""
                observation.setdefault("normalization_status", "新标签待复核，不与相似读音合并")
    return reads


def _date_in_scope(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _select_s21_schedule(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    for post in candidates:
        if post.get("candidate_category") != "排班候选":
            continue
        if str(post.get("author_uid") or "") != TARGET_UID:
            continue
        if int(post.get("season") or 0) != 21:
            continue
        text = post.get("text") if isinstance(post.get("text"), str) else ""
        if not S21_MARKER_RE.search(text):
            continue
        game_dates = post.get("game_dates")
        if not isinstance(game_dates, list) or len(game_dates) != 1:
            continue
        game_date = _date_in_scope(game_dates[0])
        published_date = _date_in_scope(post.get("published_date"))
        if game_date is None or not (SEASON_START <= game_date <= SEASON_END):
            continue
        if published_date is None or not (SEASON_START <= published_date <= SEASON_END):
            continue
        selected.append(post)
    return sorted(selected, key=lambda item: (item.get("game_dates", [""])[0], item.get("post_id", "")))


def _schedule_row(post: dict[str, Any]) -> dict[str, Any]:
    images = post.get("images") if isinstance(post.get("images"), list) else []
    players = post.get("players") if isinstance(post.get("players"), list) else []
    phase = post.get("phase") or "阶段待核"
    included = phase in {"正赛", "决赛周"}
    return {
        "season": SEASON,
        "season_name": "傀趣奇谭",
        "episode": post.get("episode"),
        "phase": phase,
        "included_for_review": included,
        "scope_category": "included_for_review" if included else "excluded_local_only",
        "game_date": (post.get("game_dates") or [""])[0],
        "published_date": post.get("published_date"),
        "published_at_utc8": post.get("published_at_utc8"),
        "post_id": post.get("post_id"),
        "post_url": post.get("post_url"),
        "player_count_extracted": len(players),
        "players_body_extracted": players,
        "commentators_body_extracted": post.get("commentators") or [],
        "judges_body_extracted": post.get("judges") or [],
        "board_body_extracted": post.get("board") or "",
        "start_time_body_extracted": post.get("start_time") or "",
        "review_flags": post.get("review_flags") or [],
        "post_body": post.get("text") or "",
        "raw_file_ref": post.get("raw_file_ref") or "",
        "full_text_file_ref": post.get("full_text_file_ref") or "",
        "detail_file_ref": post.get("detail_file_ref") or "",
        "image_ref_count": len(images),
        "image_refs": post.get("image_refs") or [],
        "image_source_urls": post.get("image_source_urls") or [],
    }


def _select_special_posts(candidates: list[dict[str, Any]], included_post_ids: set[str]) -> list[dict[str, Any]]:
    selected = []
    for post in candidates:
        post_id = str(post.get("post_id") or "")
        text = post.get("text") if isinstance(post.get("text"), str) else ""
        if (
            post_id not in included_post_ids
            and str(post.get("author_uid") or "") == TARGET_UID
            and post.get("candidate_category") == "排班候选"
            and SPECIAL_EVENT_RE.search(text)
        ):
            selected.append(post)
    return sorted(selected, key=lambda item: (item.get("published_date") or "", item.get("post_id") or ""))


def export(
    candidate_json: Path,
    all_posts_csv: Path,
    manifest_path: Path,
    output_dir: Path,
    report_path: Path,
    name_map_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    candidate_data = _read_json(candidate_json)
    manifest = _read_json(manifest_path)
    candidates = candidate_data.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("排班候选.json缺少candidates列表")
    schedule_posts = _select_s21_schedule(candidates)
    schedule_rows = [_schedule_row(post) for post in schedule_posts]
    for post, row in zip(schedule_posts, schedule_rows):
        post["_included_for_review"] = row["included_for_review"]
        post["_source_scope_category"] = row["scope_category"]
        post["_source_type"] = "S21排班原帖"
    schedule_post_ids = {str(post.get("post_id") or "") for post in schedule_posts}
    special_posts = _select_special_posts(candidates, schedule_post_ids)
    for post in special_posts:
        post["_included_for_review"] = False
        post["_source_scope_category"] = "excluded_local_only"
        post["_source_type"] = "特辑/特别活动原帖"
    evidence_posts = schedule_posts + special_posts

    manifest_file_meta: dict[str, dict[str, Any]] = {}
    for item in manifest.get("files", []):
        if isinstance(item, dict) and item.get("file"):
            manifest_file_meta[_rel(item["file"])] = item

    archive_root = manifest_path.parent.resolve()
    confirmed_names = _load_confirmed_names(name_map_path)
    crop_index_path = output_dir / "S21_名牌裁区索引.json"
    crop_index = _load_crop_index(crop_index_path)
    manual_reads_path = output_dir / "S21_人工名牌识读.json"
    manual_nameplate_reads = _load_manual_nameplate_reads(
        manual_reads_path, confirmed_names, crop_index
    )
    unique_photos: dict[str, dict[str, Any]] = {}
    photo_occurrences: list[dict[str, Any]] = []
    missing_photos: list[dict[str, Any]] = []
    sha_mismatches: list[dict[str, Any]] = []
    for post in evidence_posts:
        image_items = post.get("images") if isinstance(post.get("images"), list) else []
        body_players = post.get("players") if isinstance(post.get("players"), list) else []
        game_date = (post.get("game_dates") or [""])[0]
        included_for_review = bool(post.get("_included_for_review"))
        scope_category = str(post.get("_source_scope_category") or "excluded_local_only")
        source_type = str(post.get("_source_type") or "未分类")
        for ordinal, image in enumerate(image_items, start=1):
            if not isinstance(image, dict):
                continue
            archive_rel = _rel(image.get("file"))
            image_path = (archive_root / Path(archive_rel)).resolve() if archive_rel else None
            manifest_meta = manifest_file_meta.get(archive_rel, {})
            exists = bool(image_path and image_path.is_file())
            actual_sha = _sha256(image_path) if exists and image_path else ""
            expected_sha = str(manifest_meta.get("sha256") or "")
            sha = actual_sha or expected_sha
            size = image_path.stat().st_size if exists and image_path else manifest_meta.get("size_bytes")
            project_image_ref = _project_ref(image_path, project_root) if exists and image_path else ""
            if not exists:
                missing_photos.append({
                    "post_id": post.get("post_id"),
                    "image_ordinal": ordinal,
                    "archive_file": archive_rel,
                    "manifest_sha256": expected_sha,
                })
            if expected_sha and actual_sha and expected_sha != actual_sha:
                sha_mismatches.append({
                    "post_id": post.get("post_id"),
                    "image_ordinal": ordinal,
                    "archive_file": archive_rel,
                    "manifest_sha256": expected_sha,
                    "actual_sha256": actual_sha,
                })

            observation = manual_nameplate_reads.get(archive_rel)
            if observation:
                observation = dict(observation)
                crop_metadata = crop_index.get(archive_rel, {})
                for field in ("crop_file", "crop_rect", "contact_sheet_file", "review_batch", "crop_note"):
                    if field in crop_metadata:
                        observation.setdefault(field, crop_metadata[field])
            occurrence = {
                "game_date": game_date,
                "published_date": post.get("published_date"),
                "phase": post.get("phase"),
                "episode": post.get("episode"),
                "post_id": post.get("post_id"),
                "post_url": post.get("post_url"),
                "included_for_review": included_for_review,
                "scope_category": scope_category,
                "source_type": source_type,
                "image_ordinal": ordinal,
                "image_path": project_image_ref,
                "archive_file": archive_rel,
                "image_sha256": sha,
                "manifest_sha256": expected_sha,
                "image_size_bytes": size,
                "image_source_url": image.get("source_url") or "",
                "body_players_context_only": body_players,
                "post_body": post.get("text") or "",
                "raw_file_ref": post.get("raw_file_ref") or "",
                "full_text_file_ref": post.get("full_text_file_ref") or "",
                "detail_file_ref": post.get("detail_file_ref") or "",
                "body_order_used_for_image_identity": False,
                "nameplate_observation": observation,
            }
            photo_occurrences.append(occurrence)

            dedupe_key = sha or f"MISSING::{archive_rel}"
            record = unique_photos.setdefault(dedupe_key, {
                "sha256": sha,
                "image_size_bytes": size,
                "primary_source_image": project_image_ref,
                "archive_file": archive_rel,
                "primary_source_included_for_review": included_for_review,
                "source_occurrences": [],
                "source_urls": [],
                "nameplate_observations": [],
            })
            record["source_occurrences"].append(occurrence)
            if included_for_review and not record["primary_source_included_for_review"]:
                record["primary_source_image"] = project_image_ref
                record["archive_file"] = archive_rel
                record["image_size_bytes"] = size
                record["primary_source_included_for_review"] = True
            record.setdefault("included_for_review", False)
            record["included_for_review"] = record["included_for_review"] or included_for_review
            record.setdefault("excluded_local_only", True)
            record["excluded_local_only"] = record["excluded_local_only"] and not included_for_review
            if occurrence["image_source_url"] and occurrence["image_source_url"] not in record["source_urls"]:
                record["source_urls"].append(occurrence["image_source_url"])
            if observation and observation not in record["nameplate_observations"]:
                record["nameplate_observations"].append(observation)

    sorted_keys = sorted(unique_photos, key=lambda key: (not bool(unique_photos[key]["sha256"]), key))
    photo_id_by_key = {key: f"S21-P{index:04d}" for index, key in enumerate(sorted_keys, start=1)}

    photo_index_rows: list[dict[str, Any]] = []
    photo_index_json: list[dict[str, Any]] = []
    for key in sorted_keys:
        record = unique_photos[key]
        photo_id = photo_id_by_key[key]
        observations = record["nameplate_observations"]
        read_texts = sorted({
            item.get("read_text", "") for item in observations
            if item.get("read_status", "").startswith("已识读") and item.get("read_text")
        })
        normalized_names: list[str] = []
        normalization_refs: list[dict[str, str]] = []
        for observation in observations:
            normalized = observation.get("normalized_name") or ""
            if normalized:
                normalized_names.append(normalized)
                if observation.get("normalization_status") == "复用既有确认规范名":
                    mapping = confirmed_names.get(observation.get("read_text", ""), {})
                    if mapping:
                        normalization_refs.append(mapping)

        enriched_occurrences = []
        for occurrence in record["source_occurrences"]:
            enriched = dict(occurrence)
            enriched["photo_id"] = photo_id
            enriched_occurrences.append(enriched)
        has_excluded_occurrence = any(
            not occurrence["included_for_review"] for occurrence in record["source_occurrences"]
        )
        index_record = {
            "photo_id": photo_id,
            "image_sha256": record["sha256"],
            "image_size_bytes": record["image_size_bytes"],
            "primary_source_image": record["primary_source_image"],
            "archive_file": record["archive_file"],
            "primary_source_included_for_review": record["primary_source_included_for_review"],
            "included_for_review": record.get("included_for_review", False),
            "excluded_local_only": record.get("excluded_local_only", True),
            "has_excluded_local_only_occurrences": has_excluded_occurrence,
            "scope_status": (
                "included_for_review_and_excluded_local_only_occurrences"
                if record.get("included_for_review") and has_excluded_occurrence
                else "included_for_review"
                if record.get("included_for_review")
                else "excluded_local_only"
            ),
            "source_occurrence_count": len(record["source_occurrences"]),
            "source_urls": record["source_urls"],
            "source_occurrences": enriched_occurrences,
            "nameplate_status": (
                "正赛/决赛周图片已查看并留有名牌记录"
                if read_texts and record.get("included_for_review")
                else "excluded_local_only图片已查看并留有历史记录"
                if observations and not record.get("included_for_review")
                else "图片已查看；未发现人物名牌或属于规则图"
                if observations
                else "未查看，姓名未识读"
            ),
            "nameplate_read_texts": read_texts,
            "normalized_names_from_nameplate": sorted(set(normalized_names)),
            "normalization_references": normalization_refs,
            "nameplate_observations": observations,
            "identity_mapping_note": "正文名单仅作原帖上下文；没有依据正文顺序把照片映射到姓名或座位。",
        }
        photo_index_json.append(index_record)
        photo_index_rows.append({
            "photo_id": photo_id,
            "image_sha256": record["sha256"],
            "image_size_bytes": record["image_size_bytes"],
            "source_image": record["primary_source_image"],
            "primary_source_included_for_review": record["primary_source_included_for_review"],
            "included_for_review": index_record["included_for_review"],
            "excluded_local_only": index_record["excluded_local_only"],
            "has_excluded_local_only_occurrences": index_record["has_excluded_local_only_occurrences"],
            "scope_status": index_record["scope_status"],
            "source_occurrence_count": len(record["source_occurrences"]),
            "source_posts_json": [
                {
                    "post_id": item["post_id"],
                    "post_url": item["post_url"],
                    "game_date": item["game_date"],
                    "image_ordinal": item["image_ordinal"],
                    "image_path": item["image_path"],
                }
                for item in enriched_occurrences
            ],
            "source_urls": record["source_urls"],
            "nameplate_status": index_record["nameplate_status"],
            "nameplate_read_texts": read_texts,
            "normalized_names_from_nameplate": sorted(set(normalized_names)),
            "normalization_references": normalization_refs,
            "nameplate_observations": observations,
            "identity_mapping_note": index_record["identity_mapping_note"],
        })

    for occurrence in photo_occurrences:
        key = occurrence["image_sha256"] or f"MISSING::{occurrence['archive_file']}"
        occurrence["photo_id"] = photo_id_by_key[key]

    context_posts: list[dict[str, Any]] = []
    if all_posts_csv.is_file():
        with all_posts_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("author_uid") or "") != TARGET_UID:
                    continue
                text = row.get("text") or ""
                if not S21_MARKER_RE.search(text):
                    continue
                context_posts.append({
                    "published_date": row.get("published_date"),
                    "post_id": row.get("post_id"),
                    "candidate_category": row.get("candidate_category"),
                    "schedule_candidate": row.get("schedule_candidate"),
                    "season_parsed_by_existing_exporter": row.get("season"),
                    "episode_parsed_by_existing_exporter": row.get("episode"),
                    "post_url": row.get("post_url"),
                    "raw_file_ref": row.get("raw_file_ref"),
                    "post_body": text,
                })
    included_post_ids = {str(row.get("post_id") or "") for row in schedule_posts}
    other_s21_posts = [item for item in context_posts if item["post_id"] not in included_post_ids]

    schedule_dates = sorted({row["game_date"] for row in schedule_rows})
    player_count_distribution: dict[str, int] = {}
    for row in schedule_rows:
        n = str(row["player_count_extracted"])
        player_count_distribution[n] = player_count_distribution.get(n, 0) + 1
    schedule_duplicate_dates = sorted(
        value for value in set(schedule_dates) if sum(row["game_date"] == value for row in schedule_rows) > 1
    )
    included_unique_photos = [item for item in photo_index_json if item["included_for_review"]]
    excluded_only_unique_photos = [item for item in photo_index_json if item["excluded_local_only"]]

    manual_read_count = sum(
        1 for item in photo_index_json
        if item["nameplate_observations"] and item["included_for_review"]
    )
    local_manual_read_count = sum(
        1 for item in photo_index_json
        if item["nameplate_observations"] and item["excluded_local_only"]
    )
    excluded_read_occurrence_count = sum(
        1 for item in photo_occurrences
        if item["nameplate_observation"] and not item["included_for_review"]
    )
    excluded_read_sha_count = len({
        item["image_sha256"] for item in photo_occurrences
        if item["nameplate_observation"] and not item["included_for_review"] and item["image_sha256"]
    })
    canonicalized_read_count = sum(
        1 for item in photo_index_json
        if item["normalized_names_from_nameplate"] and item["included_for_review"]
    )
    readable_nameplate_count = sum(
        1 for item in photo_index_json if item["nameplate_read_texts"] and item["included_for_review"]
    )
    included_viewed_without_nameplate = [
        item for item in included_unique_photos
        if item["nameplate_observations"] and not item["nameplate_read_texts"]
    ]
    unmapped_direct_name_labels = sorted({
        label
        for item in included_unique_photos
        if not item["normalized_names_from_nameplate"]
        for label in item["nameplate_read_texts"]
    })
    included_image_references = [item for item in photo_occurrences if item["included_for_review"]]
    excluded_image_references = [item for item in photo_occurrences if not item["included_for_review"]]
    included_photo_shas = {
        item["image_sha256"] for item in included_image_references if item["image_sha256"]
    }
    excluded_photo_shas = {
        item["image_sha256"] for item in excluded_image_references if item["image_sha256"]
    }
    included_schedule_rows = [row for row in schedule_rows if row["included_for_review"]]
    excluded_schedule_rows = [row for row in schedule_rows if not row["included_for_review"]]
    included_schedule_dates = sorted({row["game_date"] for row in included_schedule_rows})
    excluded_special_posts = [{
        "post_id": post.get("post_id"),
        "published_date": post.get("published_date"),
        "post_url": post.get("post_url"),
        "source_type": post.get("_source_type"),
        "scope_category": post.get("_source_scope_category"),
        "image_ref_count": len(post.get("images") or []),
        "post_body": post.get("text") or "",
    } for post in special_posts]
    output_dir.mkdir(parents=True, exist_ok=True)
    schedule_json_path = output_dir / "S21_比赛日排班.json"
    schedule_csv_path = output_dir / "S21_比赛日排班.csv"
    photo_index_json_path = output_dir / "S21_姓名照片来源索引.json"
    photo_index_csv_path = output_dir / "S21_姓名照片来源索引.csv"
    photo_occurrences_csv_path = output_dir / "S21_照片原帖引用.csv"
    readings_json_path = output_dir / "S21_图片名牌识读记录.json"

    schedule_metadata = {
        "season": SEASON,
        "season_name": "傀趣奇谭",
        "season_start": SEASON_START.isoformat(),
        "season_end": SEASON_END.isoformat(),
        "source_manifest": _project_ref(manifest_path, project_root),
        "existing_export": _project_ref(candidate_json, project_root),
        "schedule_row_count": len(schedule_rows),
        "included_for_review_schedule_row_count": sum(1 for row in schedule_rows if row["included_for_review"]),
        "excluded_local_only_schedule_row_count": sum(1 for row in schedule_rows if not row["included_for_review"]),
        "schedule_unique_game_dates": schedule_dates,
        "scope_note": "表演赛行保留并标为excluded_local_only；included_for_review仅含正赛/决赛周。名单与板型来自微博正文自动提取；排班名单不代表实际局内座位。",
    }
    schedule_json_path.write_text(
        json.dumps({"metadata": schedule_metadata, "schedule": schedule_rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    schedule_csv_fields = [
        "season", "season_name", "episode", "phase", "included_for_review", "scope_category", "game_date", "published_date", "published_at_utc8",
        "post_id", "post_url", "player_count_extracted", "players_body_extracted", "commentators_body_extracted",
        "judges_body_extracted", "board_body_extracted", "start_time_body_extracted", "review_flags", "post_body",
        "raw_file_ref", "full_text_file_ref", "detail_file_ref", "image_ref_count", "image_refs", "image_source_urls",
    ]
    _write_csv(schedule_csv_path, schedule_csv_fields, schedule_rows)

    photo_index_json_path.write_text(
        json.dumps({
            "metadata": {
                "season": SEASON,
                "source_manifest": _project_ref(manifest_path, project_root),
                "schedule_post_count": len(schedule_rows),
                "image_reference_count": len(photo_occurrences),
                "unique_photo_sha256_count": sum(bool(item["image_sha256"]) for item in photo_index_json),
                "unique_photo_record_count": len(photo_index_json),
                "nameplate_review_policy": "只记录实际用view_image查看的名牌文字；不凭人脸、正文顺序或图片序号建立姓名/座位对应。",
            },
            "photos": photo_index_json,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    photo_index_fields = [
        "photo_id", "image_sha256", "image_size_bytes", "source_image", "primary_source_included_for_review", "included_for_review", "excluded_local_only", "has_excluded_local_only_occurrences", "scope_status", "source_occurrence_count", "source_posts_json",
        "source_urls", "nameplate_status", "nameplate_read_texts", "normalized_names_from_nameplate",
        "normalization_references", "nameplate_observations", "identity_mapping_note",
    ]
    _write_csv(photo_index_csv_path, photo_index_fields, photo_index_rows)
    occurrence_fields = [
        "photo_id", "image_sha256", "manifest_sha256", "image_size_bytes", "image_path", "archive_file", "game_date",
        "published_date", "phase", "episode", "post_id", "post_url", "included_for_review", "scope_category", "source_type", "image_ordinal", "image_source_url",
        "body_players_context_only", "post_body", "raw_file_ref", "full_text_file_ref", "detail_file_ref",
        "body_order_used_for_image_identity", "nameplate_observation",
    ]
    _write_csv(photo_occurrences_csv_path, occurrence_fields, photo_occurrences)

    nameplate_records: list[dict[str, Any]] = []
    for key, observation in manual_nameplate_reads.items():
        matching = [item for item in photo_occurrences if item["archive_file"] == key]
        if not matching:
            nameplate_records.append({
                "archive_file": key,
                "included_in_s21_image_index": False,
                "observation": observation,
            })
            continue
        occurrence = matching[0]
        normalization_reference = None
        if observation.get("normalization_status") == "复用既有确认规范名":
            normalization_reference = confirmed_names.get(observation.get("read_text", ""))
        nameplate_records.append({
            "photo_id": occurrence["photo_id"],
            "image_sha256": occurrence["image_sha256"],
            "source_image": occurrence["image_path"],
            "archive_file": key,
            "post_id": occurrence["post_id"],
            "post_url": occurrence["post_url"],
            "game_date": occurrence["game_date"],
            "image_ordinal": occurrence["image_ordinal"],
            "included_for_review": occurrence["included_for_review"],
            "scope_category": occurrence["scope_category"],
            "excluded_local_only": not occurrence["included_for_review"],
            "crop_file": observation.get("crop_file", ""),
            "crop_rect": observation.get("crop_rect", []),
            "contact_sheet_file": observation.get("contact_sheet_file", ""),
            "review_batch": observation.get("review_batch", ""),
            "crop_note": observation.get("crop_note", ""),
            "viewed_source": occurrence["image_path"],
            "view_method": observation["view_method"],
            "read_text": observation["read_text"],
            "read_status": observation["read_status"],
            "label_type": observation["label_type"],
            "normalized_name": observation["normalized_name"],
            "normalization_status": observation["normalization_status"],
            "normalization_reference": normalization_reference,
            "read_note": observation["read_note"],
        })
    readings_json_path.write_text(
        json.dumps({
            "policy": "仅对已用view_image实际打开的原图记录直接可见文字，不推断人脸身份或正文顺序对应。",
            "read_records": nameplate_records,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": (
            "needs_source_integrity_review"
            if missing_photos or sha_mismatches
            else "passed_with_nameplate_review_remaining"
            if manual_read_count < len(included_unique_photos)
            else "passed_nameplates_viewed_with_new_labels_for_name_review"
            if unmapped_direct_name_labels
            else "passed_nameplate_review"
        ),
        "season": {
            "id": SEASON,
            "name": "傀趣奇谭",
            "start_date": SEASON_START.isoformat(),
            "end_date": SEASON_END.isoformat(),
            "config_season_status": "media_transcribed",
            "config_collection_id": 7520632,
            "config_source": _project_ref(project_root / "config/seasons.json", project_root),
        },
        "official_media_context": {
            "count_given_in_task_context": 137,
            "verified_by_this_report": False,
            "scope_note": "137条指另行提供的S21官方媒体数量；本报告计的是微博排班帖与配图，不将其作为微博帖子数或照片数。",
        },
        "weibo_source": {
            "account_uid": TARGET_UID,
            "manifest": _project_ref(manifest_path, project_root),
            "archive_window": [manifest.get("request", {}).get("since"), manifest.get("request", {}).get("until")],
            "manifest_status": manifest.get("status"),
            "window_scan_status": manifest.get("window_scan_status"),
            "termination_reason": manifest.get("termination_reason"),
            "window_post_count": len(manifest.get("posts", [])),
            "archive_image_file_count": sum(1 for item in manifest.get("files", []) if item.get("kind") == "image"),
            "upstream_collection_audit": "data/reports/微博_2026-02-24_2026-05-26_采集验收.json",
        },
        "schedule": {
            "candidate_source": _project_ref(candidate_json, project_root),
            "row_count_all_explicit_s21_schedule_posts": len(schedule_rows),
            "included_for_review_row_count": len(included_schedule_rows),
            "excluded_local_only_row_count": len(excluded_schedule_rows),
            "unique_game_date_count_all_s21": len(schedule_dates),
            "game_date_range_all_s21": [schedule_dates[0], schedule_dates[-1]] if schedule_dates else [],
            "game_dates": schedule_dates,
            "included_for_review_unique_game_date_count": len(included_schedule_dates),
            "included_for_review_game_dates": included_schedule_dates,
            "excluded_local_only_schedule_posts": [
                {"post_id": row["post_id"], "game_date": row["game_date"], "phase": row["phase"], "image_ref_count": row["image_ref_count"]}
                for row in excluded_schedule_rows
            ],
            "player_count_distribution": player_count_distribution,
            "duplicate_game_dates": schedule_duplicate_dates,
            "posts_with_explicit_s21_marker_in_export": len(context_posts),
            "explicit_s21_posts_not_in_schedule_output": other_s21_posts,
            "excluded_local_only_special_posts": excluded_special_posts,
            "files": {
                "csv": _project_ref(schedule_csv_path, project_root),
                "json": _project_ref(schedule_json_path, project_root),
            },
            "extraction_note": "CSV/JSON保留全部正文明确S21且日期在赛期内的排班帖。included_for_review仅含正赛/决赛周；表演赛、3条特辑均标excluded_local_only。正文名单自动提取，不作座位映射。",
        },
        "photo_evidence": {
            "image_reference_count_all_indexed": len(photo_occurrences),
            "included_for_review_image_reference_count": len(included_image_references),
            "excluded_local_only_image_reference_count": len(excluded_image_references),
            "unique_photo_sha256_count": sum(bool(item["image_sha256"]) for item in photo_index_json),
            "unique_photo_record_count": len(photo_index_json),
            "deduplicated_references": len(photo_occurrences) - len(photo_index_json),
            "included_for_review_unique_photo_sha256_count": len(included_photo_shas),
            "excluded_local_only_only_unique_photo_sha256_count": len(excluded_photo_shas - included_photo_shas),
            "included_for_review_unique_photo_count": len(included_unique_photos),
            "excluded_local_only_only_unique_photo_count": len(excluded_only_unique_photos),
            "bytes_across_unique_images": sum(
                int(item["image_size_bytes"] or 0) for item in photo_index_json
            ),
            "bytes_across_included_for_review_unique_images": sum(
                int(item["image_size_bytes"] or 0) for item in included_unique_photos
            ),
            "manifest_hash_matches": len(photo_occurrences) - len(sha_mismatches) - sum(
                1 for item in photo_occurrences if not item["image_sha256"]
            ),
            "missing_image_references": missing_photos,
            "sha256_mismatches": sha_mismatches,
            "nameplate_review": {
                "unique_images_actually_viewed": manual_read_count,
                "unique_images_with_direct_label_transcription": readable_nameplate_count,
                "unique_images_with_existing_confirmed_normalized_name": canonicalized_read_count,
                "unique_images_viewed_without_person_nameplate": len(included_viewed_without_nameplate),
                "included_for_review_review_complete": manual_read_count == len(included_unique_photos),
                "included_for_review_unique_images_not_viewed": len(included_unique_photos) - manual_read_count,
                "coverage_fraction_included_for_review": f"{manual_read_count}/{len(included_unique_photos)}",
                "new_direct_nameplate_labels_not_in_existing_confirmed_map": unmapped_direct_name_labels,
                "excluded_local_only_only_unique_images_viewed_kept_as_history": local_manual_read_count,
                "excluded_local_only_read_occurrence_records_kept_as_history": excluded_read_occurrence_count,
                "excluded_local_only_read_unique_sha256_count": excluded_read_sha_count,
                "records": _project_ref(readings_json_path, project_root),
                "human_annotation_input": _project_ref(manual_reads_path, project_root),
                "crop_index": _project_ref(crop_index_path, project_root) if crop_index_path.is_file() else "",
                "summary": (
                    f"正赛/决赛周目前实际查看{manual_read_count}/{len(included_unique_photos)}张不同SHA图片；"
                    f"其中{readable_nameplate_count}张直接识读到名牌文字，"
                    f"{canonicalized_read_count}张复用S22/S23已确认规范名。"
                    f"另有{len(included_viewed_without_nameplate)}张已查看但不是人物名牌图。"
                    "2/24表演赛的2条原帖图片识读记录留在excluded_local_only来源记录中，不计入本轮覆盖；"
                    "其中JY图SHA也出现在3/3正赛帖，覆盖只依据included_for_review记录中的实际查看。"
                ),
            },
            "files": {
                "unique_index_csv": _project_ref(photo_index_csv_path, project_root),
                "unique_index_json": _project_ref(photo_index_json_path, project_root),
                "all_post_image_references_csv": _project_ref(photo_occurrences_csv_path, project_root),
            },
            "identity_policy": "每张照片保留独立SHA256、原帖、图片序号和正文；正文名单只作上下文，未按正文顺序或人脸推断图像身份。",
        },
        "name_map_reuse": {
            "source": _project_ref(name_map_path, project_root),
            "reuse_scope": "仅复用已确认的既有规范名/别名文字；不复用旧照片替代新S21照片。",
            "new_photo_evidence_preserved": "S21原图SHA256、原帖ID/URL、名牌直接读取文字及识读状态各自保留。",
        },
        "review_items_for_primary_agent": [
            *([{
                "item": "S21正赛/决赛周尚有未查看图片",
                "detail": f"included_for_review有{len(included_unique_photos)}张不同SHA图片，目前实际查看{manual_read_count}张，其余 {len(included_unique_photos) - manual_read_count} 张未识读；索引列出了逐图来源和SHA。",
            }] if manual_read_count < len(included_unique_photos) else []),
            *([{
                "item": "直接读出的新增名牌暂未归并",
                "detail": f"以下名牌文字未命中S22/S23已确认规范名，原样保留为待核新标签，不按相似读音合并：{'、'.join(unmapped_direct_name_labels)}。",
            }] if unmapped_direct_name_labels else []),
            {
                "item": "表演赛和特辑来源仅留本地索引",
                "detail": "它们在排班与图片索引中标为excluded_local_only，不计入正赛/决赛周排班、图片覆盖或对局范围。",
            },
            {
                "item": "微博排班自动字段需人工复核",
                "detail": "排班名单、解说、法官和板型来自现有导出器正文解析；有正文原件及图片引用可回查。",
            },
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "schedule_rows": len(schedule_rows),
        "included_schedule_rows": len(included_schedule_rows),
        "game_date_range": report["schedule"]["game_date_range_all_s21"],
        "included_unique_game_dates": len(included_schedule_dates),
        "image_references": len(photo_occurrences),
        "unique_photo_sha256": report["photo_evidence"]["unique_photo_sha256_count"],
        "included_unique_photo_sha256": len(included_photo_shas),
        "included_images_viewed": manual_read_count,
        "special_posts_excluded_local_only": len(special_posts),
        "missing_images": len(missing_photos),
        "sha_mismatches": len(sha_mismatches),
        "report": _project_ref(report_path, project_root),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--report", type=Path, default=Path("data/reports/S21_微博排班与照片来源验收.json"))
    parser.add_argument("--name-map", type=Path, default=DEFAULT_NAME_MAP)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path.cwd().resolve()
    output_dir = args.output_dir.resolve()
    archive_dir = args.archive_dir.resolve()
    candidate_json = output_dir / "排班候选.json"
    all_posts_csv = output_dir / "全部微博.csv"
    manifest_path = archive_dir / "manifest.json"
    try:
        summary = export(
            candidate_json=candidate_json,
            all_posts_csv=all_posts_csv,
            manifest_path=manifest_path,
            output_dir=output_dir,
            report_path=args.report.resolve(),
            name_map_path=args.name_map.resolve(),
            project_root=project_root,
        )
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(f"S21排班/照片来源导出失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
