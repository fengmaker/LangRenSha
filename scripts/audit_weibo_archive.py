"""Verify an archived date window and write a readable artifact catalog."""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from collect_weibo import plain_text, save_json, timeline_statuses
from collect_weibo_archive import inside
from weibo_naming import artifact_paths


def audit(manifest_path: Path, report_path: Path) -> dict:
    root = manifest_path.resolve().parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    request = manifest["request"]
    errors, warnings, files, catalog = [], [], [], []
    post_ids = [post["post_id"] for post in manifest["posts"]]
    if len(set(post_ids)) != len(post_ids):
        errors.append("帖子 ID 重复")

    def check_file(relative: str, kind: str, expected: dict | None = None) -> None:
        path = inside(root, relative)
        if not path.is_file():
            errors.append(f"文件缺失：{relative}")
            return
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        size = path.stat().st_size
        if expected and (size != expected.get("size_bytes") or digest != expected.get("sha256")):
            errors.append(f"文件大小或哈希不符：{relative}")
        files.append({"file": relative, "kind": kind, "size_bytes": size, "sha256": digest})

    for post in manifest["posts"]:
        post_id = post["post_id"]
        if post["author_uid"] != request["uid"]:
            errors.append(f"作者不符：{post_id}")
        if not request["since"] <= post["published_date"] <= request["until"]:
            errors.append(f"发帖日期越界：{post_id}")
        raw_path = inside(root, post["raw_file"])
        if not raw_path.is_file():
            errors.append(f"原始帖子缺失：{post_id}")
            continue
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        if str(raw.get("idstr") or raw.get("id")) != post_id:
            errors.append(f"原始 ID 不符：{post_id}")
        names = artifact_paths(raw)
        if post["raw_file"] != names["raw_file"]:
            errors.append(f"帖子命名不符：{post_id}")
        if post.get("published_at_utc8") != names["published_at_utc8"]:
            errors.append(f"发帖时间不符：{post_id}")
        check_file(post["raw_file"], "post")
        if post.get("detail_file"):
            detail_relative = post["detail_file"]
            check_file(detail_relative, "post_detail")
            if inside(root, detail_relative).is_file():
                detail = json.loads(inside(root, detail_relative).read_text(encoding="utf-8"))
                if str(detail.get("idstr") or detail.get("id")) != post_id:
                    errors.append(f"详情帖子 ID 不符：{post_id}")
                if detail_relative != names["detail_file"]:
                    errors.append(f"详情命名不符：{post_id}")
        if raw.get("isLongText"):
            full_relative = post.get("full_text_file")
            if not full_relative or post.get("full_text_status") != "expanded":
                errors.append(f"长文未补齐：{post_id}")
            elif inside(root, full_relative).is_file():
                payload = json.loads(inside(root, full_relative).read_text(encoding="utf-8"))
                if payload.get("ok") != 1 or plain_text(payload["data"]["longTextContent"]) != post["text"]:
                    errors.append(f"长文与响应不符：{post_id}")
                if full_relative != names["full_text_file"]:
                    errors.append(f"长文命名不符：{post_id}")
                check_file(full_relative, "long_text")
            else:
                errors.append(f"长文文件缺失：{post_id}")
        image_refs = []
        for index, image in enumerate(post.get("images", []), 1):
            if image.get("status") != "downloaded":
                errors.append(f"图片未下载：{post_id} 图{index} {image.get('reason')}")
                continue
            relative = image["file"].replace("\\", "/")
            expected_prefix = names["image_base"] + f"_图{index:02}"
            if not relative.startswith(expected_prefix + "."):
                errors.append(f"图片命名不符：{relative}")
            image_refs.append(relative)
            check_file(relative, "image", image)
        if isinstance(raw.get("pic_num"), int) and raw["pic_num"] > len(post.get("images", [])):
            warnings.append(f"{post_id}：接口声明{raw['pic_num']}张图，本页提供{len(post.get('images', []))}个图片地址")
        catalog.append({
            "发帖日期": post["published_date"], "发帖时间": post.get("published_at_utc8") or "",
            "微博ID": post_id, "内容标签": names["stem"][20:].rsplit("__WB", 1)[0],
            "原始帖子": post["raw_file"], "完整长文": post.get("full_text_file") or "",
            "完整图片详情": post.get("detail_file") or "",
            "图片数量": len(image_refs), "图片文件": "；".join(image_refs),
            "原帖链接": post["post_url"], "正文摘要": post["text"].replace("\n", " ")[:100],
        })
    for page in manifest["pages"]:
        relative = page.get("raw_file")
        if not relative:
            errors.append(f"分页原件未登记：第{page['page']}页")
            continue
        check_file(relative, "timeline_page")
        if inside(root, relative).is_file():
            data = json.loads(inside(root, relative).read_text(encoding="utf-8"))
            ids = [str(item.get("idstr") or item.get("id")) for item in timeline_statuses(data)
                   if str((item.get("user") or {}).get("idstr") or (item.get("user") or {}).get("id")) == request["uid"]]
            if ids != page["post_ids"]:
                errors.append(f"分页记录与原件不符：第{page['page']}页")
    fields = ["发帖日期", "发帖时间", "微博ID", "内容标签", "原始帖子", "完整长文", "完整图片详情", "图片数量", "图片文件", "原帖链接", "正文摘要"]
    with (root / "微博原件目录.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(catalog, key=lambda row: (row["发帖时间"], row["微博ID"])))
    if manifest.get("window_scan_status") != "completed":
        errors.append("日期窗口扫描尚未完成")
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path.resolve()), "request": request,
        "status": "passed" if not errors and not warnings else "needs_attention",
        "window_scan_status": manifest.get("window_scan_status"),
        "termination_reason": manifest["termination_reason"], "counts": manifest["counts"],
        "post_date_range": [min(post["published_date"] for post in manifest["posts"]),
                            max(post["published_date"] for post in manifest["posts"])] if manifest["posts"] else [],
        "posts_by_month": dict(sorted(Counter(post["published_date"][:7] for post in manifest["posts"]).items())),
        "artifact_counts": dict(Counter(item["kind"] for item in files)),
        "artifact_bytes": sum(item["size_bytes"] for item in files),
        "errors": errors, "warnings": warnings,
        "coverage_boundary_pages": manifest["pages"][-3:],
        "coverage_note": manifest["coverage_note"], "files": files,
    }
    save_json(report_path, report)
    return report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.manifest, args.report)
    print(json.dumps({key: result[key] for key in ("status", "artifact_counts", "post_date_range", "posts_by_month", "errors", "warnings")}, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "passed" else 2)
