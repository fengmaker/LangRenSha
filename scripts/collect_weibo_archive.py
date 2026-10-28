"""Resume a dated Weibo archive, reusing existing posts and media."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit

import requests

from collect_weibo import (
    CollectionError, MOBILE_ROOT, ROOT, WeiboCollector, configure_auth,
    new_manifest, normalize_post, plain_text, post_date, save_json,
    timeline_statuses,
)
from weibo_naming import artifact_paths


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise CollectionError("文件路径超出本次采集目录", reason="invalid_archive_path")
    return path


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rename_manifest(path: Path) -> dict:
    """Rename existing artifacts in place without changing their contents."""
    root = path.resolve().parent
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("source") != MOBILE_ROOT:
        raise CollectionError("不是本项目的微博清单", reason="invalid_manifest")
    mappings: list[dict] = []

    def move(old: str, new: str) -> None:
        source, target = inside(root, old), inside(root, new)
        if source == target:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if source.exists() and file_hash(source) != file_hash(target):
                raise CollectionError("命名目标存在不同内容", reason="filename_collision")
        else:
            source.rename(target)
        mappings.append({"old": old.replace("\\", "/"), "new": new,
                         "sha256": file_hash(target)})

    for post in manifest["posts"]:
        source = inside(root, post["raw_file"])
        if not source.is_file():
            raise CollectionError("原始帖子丢失，不能重命名", reason="missing_raw_post")
        raw = json.loads(source.read_text(encoding="utf-8"))
        names = artifact_paths(raw)
        move(post["raw_file"], names["raw_file"])
        post.update(raw_file=names["raw_file"], filename_stem=names["stem"],
                    image_base=names["image_base"], published_at_utc8=names.get("published_at_utc8"))
        if post.get("full_text_file"):
            move(post["full_text_file"], names["full_text_file"])
            post["full_text_file"] = names["full_text_file"]
        if post.get("detail_file"):
            move(post["detail_file"], names["detail_file"])
            post["detail_file"] = names["detail_file"]
        for index, image in enumerate(post.get("images", []), 1):
            if image.get("file"):
                suffix = Path(image["file"]).suffix.lower()
                target = f"{names['image_base']}_图{index:02}{suffix}"
                move(image["file"], target)
                image["file"] = target
        save_json(path, manifest)
    manifest["naming_version"] = 1
    save_json(path, manifest)
    return {"source_manifest": str(path.resolve()), "files": mappings,
            "renamed_files": len(mappings), "posts": len(manifest["posts"])}


def reuse_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if file_hash(source) != file_hash(target):
            raise CollectionError("复用目标存在不同内容", reason="filename_collision")
        return
    try:
        target.hardlink_to(source)
    except OSError:
        shutil.copy2(source, target)


def seed_archive(seed_path: Path, root: Path, manifest: dict) -> None:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    since, until = manifest["request"]["since"], manifest["request"]["until"]
    existing = {post["post_id"] for post in manifest["posts"]}
    for original in seed["posts"]:
        if (original["post_id"] in existing or original["author_uid"] != manifest["request"]["uid"]
                or not since <= (original.get("published_date") or "") <= until):
            continue
        post = deepcopy(original)
        post.pop("matched_keywords", None)
        post.pop("keyword_candidate", None)
        for key in ("raw_file", "full_text_file", "detail_file"):
            if post.get(key):
                reuse_file(inside(seed_path.parent, post[key]), inside(root, post[key]))
        for image in post.get("images", []):
            if image.get("status") == "downloaded":
                reuse_file(inside(seed_path.parent, image["file"]), inside(root, image["file"]))
        post["reused_from_manifest"] = str(seed_path.resolve())
        manifest["posts"].append(post)
        existing.add(post["post_id"])
    manifest["seed_posts"] = len(manifest["posts"])


def summarize(manifest: dict) -> None:
    images = [image for post in manifest["posts"] for image in post.get("images", [])]
    manifest["counts"] = {
        "pages_fetched": len(manifest["pages"]),
        "target_posts_seen": sum(page["target_author_posts"] for page in manifest["pages"]),
        "date_window_posts_seen": sum(page["in_date_window"] for page in manifest["pages"]),
        "posts_saved": len(manifest["posts"]),
        "seed_posts_reused": manifest.get("seed_posts", 0),
        "new_posts_saved": len(manifest["posts"]) - manifest.get("seed_posts", 0),
        "images_downloaded": sum(image.get("status") == "downloaded" for image in images),
        "images_not_downloaded": sum(image.get("status") != "downloaded" for image in images),
        "long_posts": sum(post.get("is_long_text", bool(post.get("full_text_file"))) for post in manifest["posts"]),
        "long_posts_expanded": sum(post.get("full_text_status") == "expanded" for post in manifest["posts"]),
        "unparseable_dates_skipped": sum(page["skipped_unparseable_date"] for page in manifest["pages"]),
    }
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()


def expand_post(post: dict, root: Path, collector: WeiboCollector) -> None:
    if not post.get("is_long_text"):
        post["full_text_status"] = "not_needed"
        return
    path = inside(root, post["full_text_file"])
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = collector.get_long_text(post["post_id"])
        save_json(path, payload)
    post["text"] = plain_text(payload["data"]["longTextContent"])
    post["full_text_status"] = "expanded"


def complete_image_list(raw: dict, post: dict, root: Path, collector: WeiboCollector) -> dict | None:
    """The mobile timeline exposes only the first nine images of larger posts."""
    expected = int(raw.get("pic_num") or len(post.get("images", [])))
    if expected <= len(post.get("images", [])):
        if post.get("detail_file"):
            return json.loads(inside(root, post["detail_file"]).read_text(encoding="utf-8"))
        return None
    names = artifact_paths(raw)
    detail_path = inside(root, names["detail_file"])
    if detail_path.is_file():
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
    else:
        detail = collector.get_post_data(post["post_id"])
        save_json(detail_path, detail)
    author = detail.get("user") or {}
    if (str(detail.get("idstr") or detail.get("id")) != post["post_id"]
            or str(author.get("idstr") or author.get("id")) != post["author_uid"]):
        raise CollectionError("图片详情的作者或帖子 ID 不符", "partial", "image_detail_mismatch")
    full_images = normalize_post(detail)["images"]
    if len(full_images) < expected:
        raise CollectionError("详情接口仍未提供声明的全部图片", "partial", "incomplete_image_list")
    for index, original in enumerate(post.get("images", [])):
        old_id = Path(urlsplit(original["source_url"]).path).stem
        new_id = Path(urlsplit(full_images[index]["source_url"]).path).stem
        if old_id != new_id:
            raise CollectionError("列表与详情的图片顺序不符", "partial", "image_order_mismatch")
        full_images[index] = original
    post["images"] = full_images
    post["detail_file"] = names["detail_file"]
    post["declared_image_count"] = expected
    return detail


def collect_archive(collector: WeiboCollector, root: Path, uid: str, since: date, until: date,
                    *, max_pages: int = 300, seed_path: Path | None = None) -> dict:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    request = {"uid": uid, "since": since.isoformat(), "until": until.isoformat(),
               "max_pages": max_pages, "request_interval_seconds": collector.request_interval}
    if path.is_file():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for key in ("uid", "since", "until"):
            if manifest["request"][key] != request[key]:
                raise CollectionError("归档目录对应另一日期窗口或账号", reason="archive_window_mismatch")
        manifest["request"].update(request)
        manifest["request"].pop("keywords", None)
        for post in manifest["posts"]:
            post.pop("matched_keywords", None)
            post.pop("keyword_candidate", None)
    else:
        manifest = new_manifest("author", request)
        manifest.update(auth_mode="cookies", naming_version=1, output_dir=str(root), seed_posts=0,
                        pagination={"next_cursor": "", "older_page_streak": 0},
                        window_scan_status="in_progress")
        if seed_path:
            seed_archive(seed_path.resolve(), root, manifest)
    manifest["coverage_note"] = (
        "顺序读取官方账号可见时间线；连续3个完整页面的可解析帖子均早于起始日期后停止，"
        "以免置顶旧帖触发提前结束。分页原件与日期范围均保存。删除、不可见或接口缺页仍可能遗漏；"
        "窗口扫描完成不代表恢复了已删除内容或账号全部历史。"
    )
    manifest["status"] = "partial"
    by_id = {post["post_id"]: post for post in manifest["posts"]}
    summarize(manifest)
    save_json(path, manifest)
    try:
        for post in manifest["posts"]:
            raw = json.loads(inside(root, post["raw_file"]).read_text(encoding="utf-8"))
            post["is_long_text"] = bool(raw.get("isLongText"))
            needs_images = (int(raw.get("pic_num") or 0) > len(post.get("images", [])) or
                            any(image.get("status") != "downloaded" for image in post.get("images", [])))
            if needs_images:
                detail = complete_image_list(raw, post, root, collector)
                save_json(path, manifest)
                if detail is not None:
                    collector.save_post(raw, post, root, True, image_source=detail)
                else:
                    collector.save_post(raw, post, root, True)
                summarize(manifest)
                save_json(path, manifest)
                print(f"repaired_images post={post['post_id']} count={len(post['images'])}", flush=True)
            if post.get("full_text_status") == "pending":
                expand_post(post, root, collector)
                summarize(manifest)
                save_json(path, manifest)
    except CollectionError as error:
        manifest["termination_reason"] = error.reason
        manifest["warnings"].append(str(error))
        summarize(manifest)
        save_json(path, manifest)
        return manifest
    if manifest.get("window_scan_status") == "completed":
        return manifest
    for page_number in range(len(manifest["pages"]) + 1, max_pages + 1):
        cursor = manifest["pagination"]["next_cursor"]
        try:
            data = collector.get_timeline_page(uid, cursor)
            statuses = timeline_statuses(data)
            page = {"page": page_number, "cards_seen": len(data["cards"]),
                    "status_cards": len(statuses), "target_author_posts": 0,
                    "in_date_window": 0, "skipped_unparseable_date": 0,
                    "post_ids": [], "oldest_date": None, "newest_date": None}
            dates: list[date] = []
            for raw in statuses:
                post = normalize_post(raw, expected_uid=uid)
                if post["author_uid"] != uid:
                    continue
                page["target_author_posts"] += 1
                page["post_ids"].append(post["post_id"])
                published = post_date(raw.get("created_at"))
                if published is None:
                    page["skipped_unparseable_date"] += 1
                    continue
                dates.append(published)
                if not since <= published <= until:
                    continue
                page["in_date_window"] += 1
                if post["post_id"] in by_id:
                    previous = by_id[post["post_id"]]
                    if previous.get("full_text_status") == "pending":
                        expand_post(previous, root, collector)
                    continue
                names = artifact_paths(raw)
                post.update(raw_file=names["raw_file"], image_base=names["image_base"],
                            filename_stem=names["stem"], published_at_utc8=names.get("published_at_utc8"),
                            is_long_text=bool(raw.get("isLongText")))
                if post["is_long_text"]:
                    post.update(full_text_file=names["full_text_file"], full_text_status="pending")
                detail = complete_image_list(raw, post, root, collector)
                if detail is not None:
                    collector.save_post(raw, post, root, True, image_source=detail)
                else:
                    collector.save_post(raw, post, root, True)
                manifest["posts"].append(post)
                by_id[post["post_id"]] = post
                summarize(manifest)
                save_json(path, manifest)
                expand_post(post, root, collector)
                summarize(manifest)
                save_json(path, manifest)
            page["oldest_date"] = min(dates).isoformat() if dates else None
            page["newest_date"] = max(dates).isoformat() if dates else None
            page["old_page"] = (len(dates) >= 5 and len(dates) == page["target_author_posts"]
                                and max(dates) < since)
            page_file = (f"pages/第{page_number:04}页_发帖{page['oldest_date'] or '未知日期'}"
                         f"_至_{page['newest_date'] or '未知日期'}.列表原始.json")
            save_json(root / page_file, data)
            page["raw_file"] = page_file
            repeated = bool(manifest["pages"] and page["post_ids"] and
                            page["post_ids"] == manifest["pages"][-1]["post_ids"])
            manifest["pages"].append(page)
            pagination = manifest["pagination"]
            pagination["older_page_streak"] = pagination["older_page_streak"] + 1 if page["old_page"] else 0
            next_cursor = str((data.get("cardlistInfo") or {}).get("since_id") or "")
            pagination["next_cursor"] = next_cursor
            has_more = data.get("has_more", (data.get("cardlistInfo") or {}).get("has_more"))
            reason = None
            if repeated:
                reason = "repeated_page_boundary"
            elif has_more is False or has_more == 0:
                reason = "api_end_marker"
                manifest["window_scan_status"] = "completed"
            elif not statuses:
                reason = "empty_page_without_end_marker"
            elif pagination["older_page_streak"] >= 3:
                reason = "date_window_passed_3_pages"
                manifest["window_scan_status"] = "completed"
            elif not next_cursor or next_cursor == "0" or next_cursor == cursor:
                reason = "cursor_missing_or_repeated"
            manifest["termination_reason"] = reason or "in_progress"
            summarize(manifest)
            save_json(path, manifest)
            counts = manifest["counts"]
            print(f"page={page_number} dates={page['oldest_date']}..{page['newest_date']} "
                  f"posts={counts['posts_saved']} images={counts['images_downloaded']} "
                  f"long_text={counts['long_posts_expanded']}/{counts['long_posts']}", flush=True)
            if reason:
                break
        except CollectionError as error:
            manifest["termination_reason"] = error.reason
            manifest["warnings"].append(str(error))
            break
    else:
        manifest["termination_reason"] = "max_pages_reached"
    manifest["posts"].sort(key=lambda post: (post.get("published_at_utc8") or post["published_date"], post["post_id"]), reverse=True)
    summarize(manifest)
    save_json(path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uid", default="7525583841")
    parser.add_argument("--since", type=date.fromisoformat, default=date(2026, 5, 26))
    parser.add_argument("--until", type=date.fromisoformat, default=date(2026, 10, 20))
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--seed-manifest", type=Path)
    parser.add_argument("--rename-manifest", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--cookies-file", default=".secrets/weibo.cookies.txt")
    parser.add_argument("--request-interval", type=float, default=1.5)
    parser.add_argument("--max-pages", type=int, default=300)
    args = parser.parse_args()
    try:
        if args.rename_manifest:
            report = rename_manifest(args.rename_manifest)
            if args.report:
                save_json(args.report, report)
            print(f"renamed_files={report['renamed_files']} posts={report['posts']}")
            return 0
        if (not args.uid.isdigit() or args.since > args.until or not 1 <= args.max_pages <= 1000
                or not 1 <= args.request_interval <= 60):
            parser.error("账号、日期范围、页数或请求间隔无效")
        root = args.archive_dir or ROOT / "data/raw/weibo" / f"{args.since}_{args.until}_京城大师赛_UID{args.uid}"
        session = requests.Session()
        configure_auth(session, "cookies", args.cookies_file)
        collector = WeiboCollector(session=session, request_interval=args.request_interval)
        result = collect_archive(collector, root, args.uid, args.since, args.until,
                                 max_pages=args.max_pages, seed_path=args.seed_manifest)
        counts = result["counts"]
        complete = (result["window_scan_status"] == "completed"
                    and counts["unparseable_dates_skipped"] == 0
                    and counts["images_not_downloaded"] == 0
                    and counts["long_posts_expanded"] == counts["long_posts"])
        print(json.dumps({"status": "completed" if complete else "partial",
                          "window_scan_status": result["window_scan_status"],
                          "reason": result["termination_reason"], "counts": counts,
                          "manifest": str(root / "manifest.json")}, ensure_ascii=False))
        return 0 if complete else 2
    except (CollectionError, OSError, ValueError, KeyError) as error:
        print(f"归档失败（{type(error).__name__}）", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
