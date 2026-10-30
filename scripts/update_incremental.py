"""Check new S23 matches and extend local Weibo date windows after confirmation."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
import tempfile

import requests

import collect_season
from auth_support import AuthConfigurationError
from collect_bilibili_audio import CollectionError
from collect_weibo import CollectionError as WeiboCollectionError
from collect_weibo import WeiboCollector, configure_auth, normalize_post, post_date, timeline_statuses
from collect_weibo_archive import collect_archive
from incremental_common import ROOT, entry_key, load_state, ready_media, save_state, write_json


WEIBO_UID = "7525583841"
BILIBILI_MID = "19106800"
BEIJING = timezone(timedelta(hours=8))
DEFAULT_BILI_COOKIES = Path(".secrets/bilibili.cookies.txt")
DEFAULT_WEIBO_COOKIES = Path(".secrets/weibo.cookies.txt")
MAX_WEIBO_PAGES = 300


def archive_complete(manifest: dict) -> bool:
    """Use the same completion predicate as collect_weibo_archive's CLI."""
    counts = manifest.get("counts") or {}
    try:
        return (manifest.get("window_scan_status") == "completed"
                and counts["unparseable_dates_skipped"] == 0
                and counts["images_not_downloaded"] == 0
                and counts["long_posts_expanded"] == counts["long_posts"])
    except KeyError:
        return False


def beijing_yesterday(now: datetime | None = None) -> date:
    current = now or datetime.now(BEIJING)
    if current.tzinfo is not None:
        current = current.astimezone(BEIJING)
    return current.date() - timedelta(days=1)


def beijing_today(now: datetime | None = None) -> date:
    current = now or datetime.now(BEIJING)
    if current.tzinfo is not None:
        current = current.astimezone(BEIJING)
    return current.date()


def discover_live_plan(season: str, auth: str, cookies: Path | None) -> dict:
    """Call the existing official collector plan builder with temporary output paths."""
    collect_season.configure_season(season)
    with tempfile.TemporaryDirectory(prefix="langrensha-incremental-plan-") as folder:
        original_root, original_plan = collect_season.ROOT, collect_season.PLAN
        try:
            collect_season.ROOT = Path(folder)
            collect_season.PLAN = Path(folder) / "plan.json"
            return collect_season.build_plan(auth, cookies)
        finally:
            collect_season.ROOT = original_root
            collect_season.PLAN = original_plan


def _source_tuple(entry: dict) -> tuple[str, int, int]:
    return entry["bvid"], int(entry["cid"]), int(entry.get("page") or 1)


def _state_source_keys(state: dict) -> set[tuple[str, int, int]]:
    found = set()
    key_pattern = re.compile(r"(BV[0-9A-Za-z]{10}):(\d+)(?::p(\d+))?")
    for key, item in (state.get("items") or {}).items():
        entry = item.get("entry") if isinstance(item, dict) else None
        if isinstance(entry, dict):
            phase = (entry.get("labels") or {}).get("phase_candidate", "unknown")
            if phase not in {"regular", "finals_week"}:
                continue
            try:
                found.add(_source_tuple(entry))
                continue
            except (KeyError, TypeError, ValueError):
                pass
        elif isinstance(item, dict) and item.get("scope") == "out_of_scope":
            continue
        match = key_pattern.fullmatch(str(key))
        if match:
            bvid, cid, page = match.groups()
            found.add((bvid, int(cid), int(page or 1)))
    return found


def first_discovered_entries(live_entries: list[dict], frozen_entries: list[dict],
                             state: dict, formal_sources: set[tuple[str, int, int]]) -> list[dict]:
    known = {_source_tuple(entry) for entry in frozen_entries}
    known.update(_state_source_keys(state))
    known.update(formal_sources)
    return [entry for entry in live_entries if _source_tuple(entry) not in known]


def season_opening_date(plan: dict) -> date | None:
    dates = []
    for entry in plan.get("entries", []):
        candidate = (entry.get("labels") or {}).get("event_date_candidate")
        try:
            if candidate:
                dates.append(date.fromisoformat(candidate))
        except ValueError:
            continue
    return min(dates, default=None)


def default_weibo_start(plan: dict, explicit_since: date | None = None) -> date | None:
    return explicit_since or season_opening_date(plan)


def resolve_auth(explicit_auth: str | None, cookie_path: Path | None) -> tuple[str, Path | None]:
    mode = explicit_auth or ("cookies" if cookie_path and cookie_path.is_file() else "none")
    return mode, cookie_path if mode == "cookies" else None


def formal_dossier_sources(root: Path, season: str) -> tuple[set[tuple[str, int, int]], dict[tuple[str, int], set[int]]]:
    """Return source identities represented by formal dossier.json files, without a DB read."""
    exact: set[tuple[str, int, int]] = set()
    by_bvid_page: dict[tuple[str, int], set[int]] = {}
    pattern = re.compile(r"(BV[0-9A-Za-z]{10}):(\d+)(?::p(\d+))?")
    dossiers = Path(root) / "data" / "games" / season
    if not dossiers.is_dir():
        return exact, by_bvid_page
    for path in dossiers.glob("*/dossier.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if document.get("season") != season:
            continue
        slug = str(document.get("slug") or path.parent.name)
        page_match = re.search(r"-p(\d+)(?:-|$)", slug, re.IGNORECASE)
        default_page = int(page_match.group(1)) if page_match else 1
        sources = document.get("files")
        if isinstance(sources, dict):
            source_rows = sources.values()
        elif isinstance(sources, list):
            source_rows = sources
        else:
            source_rows = []
        for source in source_rows:
            if not isinstance(source, dict):
                continue
            identity = source.get("external_key")
            match = pattern.fullmatch(str(identity or ""))
            if not match:
                continue
            bvid, cid_text, page_text = match.groups()
            cid = int(cid_text)
            page_number = int(page_text) if page_text else default_page
            exact.add((bvid, cid, page_number))
            by_bvid_page.setdefault((bvid, page_number), set()).add(cid)
    return exact, by_bvid_page


def scope_for_entry(entry: dict, formal_by_bvid_page: dict[tuple[str, int], set[int]]) -> tuple[str, str | None]:
    labels = entry.get("labels") or {}
    phase = labels.get("phase_candidate", "unknown")
    bvid, cid, page = _source_tuple(entry)
    formal_cids = formal_by_bvid_page.get((bvid, page), set())
    if formal_cids and cid not in formal_cids:
        return "scope_gap", "formal_source_cid_conflict"
    if phase in {"regular", "finals_week"}:
        return "in_scope", None
    if phase == "unknown":
        return "scope_gap", "unknown_phase"
    return "out_of_scope", f"analysis_phase_{phase}"


def raw_cid_conflict(root: Path, entry: dict) -> int | None:
    path = (Path(root) / "data" / "raw" / "bilibili" / entry["bvid"] /
            f"p{int(entry.get('page') or 1):02d}" / "manifest.json")
    if not path.is_file():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("bvid") != entry["bvid"]:
            return -1
        cid = int(manifest["cid"])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return cid if cid != int(entry["cid"]) else None


def formal_media_present(entry: dict, root: Path) -> bool:
    """Cheaply report whether a formal source's matching raw files are present."""
    folder = (Path(root) / "data" / "raw" / "bilibili" / entry["bvid"] /
              f"p{int(entry.get('page') or 1):02d}")
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        raw = json.loads((folder / "metadata.raw.json").read_text(encoding="utf-8")).get("data") or {}
        page_number = int(entry.get("page") or 1)
        page = next((row for row in raw.get("pages", []) if int(row.get("page") or 0) == page_number), None)
        if (manifest.get("bvid") != entry["bvid"] or int(manifest.get("cid")) != int(entry["cid"])
                or int(manifest.get("page")) != page_number
                or str((manifest.get("owner") or {}).get("mid")) != BILIBILI_MID
                or raw.get("bvid") != entry["bvid"]
                or str((raw.get("owner") or {}).get("mid")) != BILIBILI_MID
                or page is None or int(page.get("cid") or 0) != int(entry["cid"])):
            return False
        for track in (manifest.get("subtitles") or {}).get("tracks", []):
            language = str(track.get("language") or "").lower().replace("_", "-")
            if language == "zh" or language == "ai-zh" or language.startswith(("zh-", "ai-zh-")):
                media_path = (folder / str(track.get("file") or "")).resolve()
                if media_path.is_relative_to(folder.resolve()) and media_path.is_file() and media_path.stat().st_size > 0:
                    return True
        audio = manifest.get("audio") or {}
        media_path = (folder / str(audio.get("file") or "")).resolve()
        return (media_path.is_relative_to(folder.resolve()) and media_path.is_file()
                and int(audio.get("bytes") or 0) > 0
                and media_path.stat().st_size == int(audio["bytes"]))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def _archive_paths(root: Path, uid: str) -> list[Path]:
    base = Path(root) / "data" / "raw" / "weibo"
    manifests = []
    if not base.is_dir():
        return manifests
    for path in base.glob("*/manifest.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        request = value.get("request") or {}
        if request.get("uid") == uid and value.get("mode") == "author":
            manifests.append(path)
    return manifests


def _archive_interval(manifest: dict) -> tuple[date, date] | None:
    try:
        request = manifest["request"]
        return date.fromisoformat(request["since"]), date.fromisoformat(request["until"])
    except (KeyError, TypeError, ValueError):
        return None


def _timestamp_beijing_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(BEIJING).date()


def _coverage_until(manifest: dict, start: date, requested_until: date) -> date:
    if "incremental_coverage_basis_utc" in manifest:
        basis = manifest.get("incremental_coverage_basis_utc")
        scan_day = _timestamp_beijing_date(basis)
        if basis is None:
            return start - timedelta(days=1)
    else:
        basis = manifest.get("incremental_scan_completed_at_utc")
        if basis is None:
            basis = manifest.get("updated_at_utc") or manifest.get("created_at_utc")
        scan_day = _timestamp_beijing_date(basis)
        if scan_day is None:
            # Legacy manifests without a completion timestamp retain their stated range.
            return requested_until
    return min(requested_until, scan_day - timedelta(days=1))


def _merge_intervals(intervals: list[tuple[date, date]]) -> list[tuple[date, date]]:
    merged: list[list[date]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + timedelta(days=1):
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _missing_ranges(since: date, until: date, covered: list[tuple[date, date]]) -> list[tuple[date, date]]:
    ranges = []
    cursor = since
    for start, end in _merge_intervals([
            (max(since, start), min(until, end))
            for start, end in covered if start <= until and end >= since]):
        if cursor < start:
            ranges.append((cursor, start - timedelta(days=1)))
        cursor = max(cursor, end + timedelta(days=1))
    if cursor <= until:
        ranges.append((cursor, until))
    return ranges


def weibo_local_snapshot(root: Path, uid: str, *, post_since: date | None = None,
                         post_until: date | None = None) -> dict:
    archives = []
    known_ids: set[str] = set()
    local_latest: date | None = None
    latest_requested_until: date | None = None
    collection_starts: list[date] = []
    complete_intervals: list[tuple[date, date]] = []
    incomplete: list[dict] = []
    for path in _archive_paths(root, uid):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        interval = _archive_interval(manifest)
        if interval is None:
            continue
        start, end = interval
        latest_requested_until = end if latest_requested_until is None else max(latest_requested_until, end)
        collection_starts.append(start)
        for post in manifest.get("posts", []):
            post_id = str(post.get("post_id") or "")
            if post_id:
                known_ids.add(post_id)
            try:
                published = date.fromisoformat(post.get("published_date") or "")
            except ValueError:
                continue
            if ((post_since is not None and published < post_since)
                    or (post_until is not None and published > post_until)):
                continue
            local_latest = published if local_latest is None else max(local_latest, published)
        item = {"path": path, "manifest": manifest, "since": start, "until": end}
        archives.append(item)
        if archive_complete(manifest):
            closed_until = _coverage_until(manifest, start, end)
            if closed_until >= start:
                complete_intervals.append((start, closed_until))
        else:
            incomplete.append(item)
    return {
        "archives": archives,
        "known_ids": known_ids,
        "local_latest": local_latest,
        "latest_requested_until": latest_requested_until,
        "earliest_collection": min(collection_starts) if collection_starts else None,
        "complete_intervals": _merge_intervals(complete_intervals),
        "incomplete": incomplete,
    }


def _newest_complete_component(intervals: list[tuple[date, date]], since: date, until: date) -> tuple[date, date] | None:
    clipped = [(max(since, start), min(until, end)) for start, end in intervals
               if start <= until and end >= since]
    merged = _merge_intervals(clipped)
    # Report the longest/latest contiguous coverage component without treating
    # a local post timestamp as evidence that intervening days were scanned.
    return max(merged, key=lambda interval: (interval[1], interval[0])) if merged else None


def plan_weibo_windows(root: Path, uid: str, since: date, until: date,
                       *, scan_date: date | None = None) -> dict:
    snapshot = weibo_local_snapshot(root, uid)
    gaps = _missing_ranges(since, until, snapshot["complete_intervals"])
    windows = []
    scheduled: set[tuple[date, date, str]] = set()
    scan_date = scan_date or beijing_today()
    for start, end in gaps:
        canonical = _archive_dir(root, start, end, uid)
        canonical_manifest = canonical / "manifest.json"
        existing = None
        if canonical_manifest.is_file():
            try:
                existing = json.loads(canonical_manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = None
        if existing and existing.get("window_scan_status") == "completed":
            if _archive_backend(existing) == "desktop":
                destination = canonical.with_name(f"{canonical.name}_late_scan_{scan_date:%Y%m%d}")
                seed_path = canonical_manifest
            else:
                destination = _desktop_archive_dir(root, start, end, uid)
                desktop_manifest = destination / "manifest.json"
                desktop = None
                if desktop_manifest.is_file():
                    try:
                        desktop = json.loads(desktop_manifest.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        pass
                if desktop and desktop.get("window_scan_status") != "completed":
                    window = {"since": start, "until": end, "path": destination,
                              "resume": True, "seed_path": None}
                    windows.append(window)
                    scheduled.add((start, end, str(destination)))
                    continue
                if desktop:
                    destination = destination.with_name(
                        f"{destination.name}_late_scan_{scan_date:%Y%m%d}")
                    seed_path = desktop_manifest
                else:
                    seed_path = canonical_manifest
            window = {"since": start, "until": end, "path": destination,
                      "resume": False, "seed_path": seed_path}
        elif existing is not None:
            if _archive_backend(existing) == "desktop":
                window = {"since": start, "until": end, "path": canonical,
                          "resume": True, "seed_path": None}
            else:
                destination = _desktop_archive_dir(root, start, end, uid)
                desktop_manifest = destination / "manifest.json"
                desktop = None
                if desktop_manifest.is_file():
                    try:
                        desktop = json.loads(desktop_manifest.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        pass
                if desktop and desktop.get("window_scan_status") != "completed":
                    window = {"since": start, "until": end, "path": destination,
                              "resume": True, "seed_path": None}
                elif desktop:
                    destination = destination.with_name(
                        f"{destination.name}_late_scan_{scan_date:%Y%m%d}")
                    window = {"since": start, "until": end, "path": destination,
                              "resume": False, "seed_path": desktop_manifest}
                else:
                    window = {"since": start, "until": end, "path": destination,
                              "resume": False, "seed_path": canonical_manifest}
        else:
            window = {"since": start, "until": end, "path": None,
                      "resume": False, "seed_path": None}
        key = (start, end, str(window["path"] or canonical))
        windows.append(window)
        scheduled.add(key)
    # Move unfinished mobile windows into a fresh desktop archive while reusing
    # their saved posts. The union of completed archive coverage can make an
    # older partial archive redundant, regardless of its original backend.
    for item in snapshot["incomplete"]:
        start, end = item["since"], item["until"]
        if since <= start <= end <= until:
            if not _missing_ranges(start, end, snapshot["complete_intervals"]):
                continue
            backend = _archive_backend(item["manifest"])
            if backend != "desktop" and any(
                    window["since"] <= end and window["until"] >= start for window in windows):
                continue
            if backend == "desktop":
                archive_root = item["path"].parent
                resume = True
                seed_path = None
            else:
                archive_root = _desktop_archive_dir(root, start, end, uid)
                desktop_manifest = archive_root / "manifest.json"
                seed_path = None
                resume = False
                if desktop_manifest.is_file():
                    try:
                        desktop = json.loads(desktop_manifest.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        desktop = None
                    if desktop and desktop.get("window_scan_status") != "completed":
                        resume = True
                    elif desktop:
                        archive_root = archive_root.with_name(
                            f"{archive_root.name}_late_scan_{scan_date:%Y%m%d}")
                        seed_path = desktop_manifest
                    else:
                        seed_path = item["path"] / "manifest.json"
                else:
                    seed_path = item["path"] / "manifest.json"
            key = (start, end, str(archive_root))
            if key not in scheduled:
                windows.append({"since": start, "until": end, "path": archive_root,
                                "resume": resume, "seed_path": seed_path})
                scheduled.add(key)
    ordered = sorted(windows, key=lambda item: (item["since"], item["until"],
                                                not item["resume"], str(item["path"] or "")))
    scan_windows = []
    seen_ranges = set()
    for window in ordered:
        key = (window["since"], window["until"])
        if key in seen_ranges:
            continue
        scan_windows.append({"since": window["since"], "until": window["until"]})
        seen_ranges.add(key)
    return {
        **snapshot,
        "windows": ordered,
        "scan_windows": scan_windows,
        "missing_ranges": gaps,
        "contiguous_complete": _newest_complete_component(snapshot["complete_intervals"], since, until),
    }


def scan_weibo_window(collector: WeiboCollector, uid: str, since: date, until: date,
                      known_ids: set[str], *, max_pages: int = MAX_WEIBO_PAGES,
                      first_page: dict | None = None) -> dict:
    """Scan timeline metadata only and return the exact in-window unseen post IDs."""
    cursor = ""
    older_page_streak = 0
    previous_post_ids: list[str] | None = None
    pages = 0
    unparseable_dates = 0
    unidentified_posts = 0
    new_posts: dict[str, str | None] = {}
    newest_visible: date | None = None
    scan_status = "in_progress"
    termination_reason = "max_pages_reached"
    for page_number in range(1, max_pages + 1):
        data = first_page if page_number == 1 and first_page is not None else collector.get_timeline_page(uid, cursor)
        statuses = timeline_statuses(data)
        ids: list[str] = []
        page_dates: list[date] = []
        for raw in statuses:
            post = normalize_post(raw, expected_uid=uid)
            if post["author_uid"] != uid:
                continue
            post_id = post["post_id"]
            ids.append(post_id)
            if not post_id:
                unidentified_posts += 1
                continue
            published = post_date(raw.get("created_at"))
            if published is None:
                unparseable_dates += 1
                continue
            page_dates.append(published)
            newest_visible = published if newest_visible is None else max(newest_visible, published)
            if since <= published <= until and post_id not in known_ids:
                new_posts[post_id] = published.isoformat()
        pages += 1
        page_old = (len(page_dates) >= 5 and len(page_dates) == len(ids) and max(page_dates) < since)
        older_page_streak = older_page_streak + 1 if page_old else 0
        repeated = bool(previous_post_ids and ids and ids == previous_post_ids)
        previous_post_ids = ids
        next_cursor = str((data.get("cardlistInfo") or {}).get("since_id") or "")
        has_more = data.get("has_more", (data.get("cardlistInfo") or {}).get("has_more"))
        if has_more is False or has_more == 0:
            scan_status, termination_reason = "completed", "api_end_marker"
            break
        if older_page_streak >= 3:
            scan_status, termination_reason = "completed", "date_window_passed_3_pages"
            break
        if repeated:
            termination_reason = "repeated_page_boundary"
            break
        if not statuses:
            termination_reason = "empty_page_without_end_marker"
            break
        if not next_cursor or next_cursor == "0" or next_cursor == cursor:
            termination_reason = "cursor_missing_or_repeated"
            break
        cursor = next_cursor
    return {"since": since.isoformat(), "until": until.isoformat(),
            "pages_scanned": pages, "window_scan_status": scan_status,
            "termination_reason": termination_reason,
            "unparseable_dates_skipped": unparseable_dates,
            "unidentified_posts": unidentified_posts,
            "new_posts": [{"post_id": post_id, "published_date": published}
                          for post_id, published in sorted(new_posts.items(), key=lambda row: (row[1] or "", row[0]))],
            "newest_visible_online": newest_visible.isoformat() if newest_visible else None}


def scan_weibo(collector: WeiboCollector, uid: str, windows: list[dict], known_ids: set[str],
               *, max_pages: int = MAX_WEIBO_PAGES) -> dict:
    first_page = collector.get_timeline_page(uid, "")
    visible_dates = [post_date(raw.get("created_at")) for raw in timeline_statuses(first_page)
                     if str(((raw.get("user") or {}).get("idstr") or
                             (raw.get("user") or {}).get("id") or "")) == uid]
    newest_visible = max((value for value in visible_dates if value is not None), default=None)
    scans = []
    seen_ids = set(known_ids)
    for index, window in enumerate(windows):
        first = first_page if index == 0 else None
        result = scan_weibo_window(collector, uid, window["since"], window["until"],
                                   seen_ids, max_pages=max_pages, first_page=first)
        scans.append(result)
        seen_ids.update(item["post_id"] for item in result["new_posts"])
        if result["window_scan_status"] != "completed" or result["unparseable_dates_skipped"]:
            break
        if result["unidentified_posts"]:
            break
    new_posts = {item["post_id"]: item for scan in scans for item in scan["new_posts"]}
    for item in visible_dates:
        if item is not None:
            newest_visible = max(newest_visible, item) if newest_visible else item
    return {"scans": scans,
            "new_posts": sorted(new_posts.values(), key=lambda item: (item.get("published_date") or "", item["post_id"])),
            "newest_visible_online": newest_visible.isoformat() if newest_visible else None,
            "complete": all(scan["window_scan_status"] == "completed"
                             and scan["unparseable_dates_skipped"] == 0
                             and scan["unidentified_posts"] == 0 for scan in scans)}


def _phase(entry: dict) -> str:
    return str((entry.get("labels") or {}).get("phase_candidate") or "unknown")


def _match_entries(entries: list[dict]) -> list[dict]:
    return [entry for entry in entries if _phase(entry) in {"regular", "finals_week"}]


def _unknown_phase_gaps(entries: list[dict]) -> list[dict]:
    return [{**entry, "_scope_reason": "unknown_phase"}
            for entry in entries if _phase(entry) == "unknown"]


def _state_match_keys(state: dict) -> set[str]:
    keys = set()
    for key, item in (state.get("items") or {}).items():
        entry = item.get("entry") if isinstance(item, dict) else None
        if isinstance(entry, dict) and _phase(entry) in {"regular", "finals_week"}:
            keys.add(key)
    return keys


def _item_for_entry(state: dict, root: Path, entry: dict, media_ready: bool,
                    scope: str, scope_reason: str | None, formal: bool) -> dict:
    key = entry_key(entry)
    previous = state["items"].get(key, {})
    item = dict(previous)
    item["entry"] = entry
    if media_ready:
        item["acquisition"] = "ready"
        item["acquisition_error"] = None
    elif item.get("acquisition") not in {"failed", "pending"}:
        item["acquisition"] = "pending"
    else:
        item.setdefault("acquisition", "pending")
    item.setdefault("analysis", "pending")
    item.setdefault("applied", False)
    item["scope"] = scope
    item["formal_dossier"] = bool(formal)
    item["scope_reason"] = scope_reason
    if media_ready:
        manifest_path = (Path(root) / "data" / "raw" / "bilibili" / entry["bvid"] /
                         f"p{int(entry.get('page') or 1):02d}" / "manifest.json")
        item["manifest_path"] = manifest_path.relative_to(root).as_posix()
    state["items"][key] = item
    return item


def _download_one(entry: dict, root: Path, collector: collect_season.Collector) -> Path:
    output = Path(root) / "data" / "raw" / "bilibili"
    page_number = int(entry.get("page") or 1)
    original_api = collector.api

    def check_live_source(path: str, params: dict) -> dict:
        response = original_api(path, params)
        if path == "/x/web-interface/view" and params.get("bvid") == entry["bvid"]:
            data = response.get("data") or {}
            page = next((row for row in data.get("pages", [])
                         if int(row.get("page") or 0) == page_number), None)
            if page is None or int(page.get("cid") or 0) != int(entry["cid"]):
                raise CollectionError("官方视频当前 CID 与确认时的合集条目不同；未覆盖本地来源")
        return response

    collector.api = check_live_source
    try:
        manifest = collector.collect(
            entry["bvid"], page_number, output, True, 128000, 200 * 1024**2,
            expected_owner=BILIBILI_MID, subtitles_first=True,
        )
    finally:
        collector.api = original_api
    if int(manifest.get("cid") or 0) != int(entry["cid"]):
        raise CollectionError("实际 CID 与官方合集条目不符")
    manifest_path = output / entry["bvid"] / f"p{page_number:02d}" / "manifest.json"
    if not ready_media(entry, root):
        raise CollectionError("下载后的中文字幕、独立音轨或来源清单未通过完整性检查")
    return manifest_path


def _archive_dir(root: Path, since: date, until: date, uid: str) -> Path:
    return Path(root) / "data" / "raw" / "weibo" / f"{since}_{until}_京城大师赛_UID{uid}"


def _desktop_archive_dir(root: Path, since: date, until: date, uid: str) -> Path:
    canonical = _archive_dir(root, since, until, uid)
    return canonical.with_name(f"{canonical.name}_desktop")


def _archive_backend(manifest: dict) -> str:
    return str((manifest.get("request") or {}).get("list_backend") or "mobile")


def _choose_seed(snapshot: dict, root: Path, since: date, until: date) -> Path | None:
    candidates = []
    target = _archive_dir(root, since, until, WEIBO_UID)
    for item in snapshot["archives"]:
        if item["path"].parent == target:
            continue
        count = sum(since.isoformat() <= str(post.get("published_date") or "") <= until.isoformat()
                    for post in item["manifest"].get("posts", []))
        if count:
            candidates.append((count, item["path"]))
    return max(candidates, default=(0, None), key=lambda value: value[0])[1]


def _collect_weibo_windows(root: Path, uid: str, windows: list[dict],
                           auth: str, cookies: Path | None, state: dict,
                           *, completed_at: datetime | None = None) -> bool:
    session = requests.Session()
    configure_auth(session, auth, str(cookies) if cookies else None)
    collector = _new_desktop_weibo_collector(session)
    state_weibo = state.setdefault("weibo", {})
    stored = state_weibo.setdefault("windows", [])
    success = True
    for window in windows:
        since, until = window["since"], window["until"]
        archive_root = window["path"] or _archive_dir(root, since, until, uid)
        manifest_path = archive_root / "manifest.json"
        previous_manifest = None
        if manifest_path.is_file():
            try:
                previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous_manifest = None
        scan_was_complete = bool(previous_manifest and
                                 previous_manifest.get("window_scan_status") == "completed")
        seed = window.get("seed_path")
        if seed is None and not window["resume"]:
            seed = _choose_seed(weibo_local_snapshot(root, uid), root, since, until)
        try:
            manifest = collect_archive(collector, archive_root, uid, since, until,
                                      max_pages=MAX_WEIBO_PAGES, seed_path=seed)
            did_scan = (not scan_was_complete and
                        manifest.get("window_scan_status") == "completed")
            if did_scan:
                stamp = completed_at or datetime.now(timezone.utc)
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                manifest["incremental_scan_completed_at_utc"] = stamp.astimezone(timezone.utc).isoformat()
                write_json(manifest_path, manifest)
            elif scan_was_complete and previous_manifest is not None:
                if ("incremental_scan_completed_at_utc" not in previous_manifest
                        and "incremental_coverage_basis_utc" not in previous_manifest):
                    # Preserve the legacy timestamp basis across artifact repair; the repair
                    # updates updated_at_utc but did not rescan timeline coverage.
                    manifest["incremental_coverage_basis_utc"] = (
                        previous_manifest.get("updated_at_utc") or
                        previous_manifest.get("created_at_utc"))
                    write_json(manifest_path, manifest)
            complete = archive_complete(manifest)
            record = {"since": since.isoformat(), "until": until.isoformat(),
                      "path": archive_root.relative_to(root).as_posix(),
                      "window_scan_status": manifest.get("window_scan_status"),
                      "scan_completed_at_utc": (manifest.get("incremental_scan_completed_at_utc") or
                                                 manifest.get("incremental_coverage_basis_utc") or
                                                 manifest.get("updated_at_utc")),
                      "complete": complete, "termination_reason": manifest.get("termination_reason"),
                      "counts": manifest.get("counts", {})}
        except (WeiboCollectionError, OSError, ValueError, KeyError) as error:
            record = {"since": since.isoformat(), "until": until.isoformat(),
                      "path": archive_root.relative_to(root).as_posix(),
                      "window_scan_status": "partial", "complete": False,
                      "termination_reason": (error.reason if isinstance(error, WeiboCollectionError)
                                             else type(error).__name__)}
        previous = next((row for row in stored if (row.get("since"), row.get("until"), row.get("path")) ==
                         (record["since"], record["until"], record["path"])), None)
        if previous is not None:
            previous.update(record)
        else:
            stored.append(record)
        save_state(root, state["season"], state)
        success = success and record["complete"]
        if not record["complete"]:
            break
    return success


def _new_desktop_weibo_collector(session: requests.Session):
    from collect_weibo import DesktopWeiboCollector
    return DesktopWeiboCollector(session=session)


def _print_summary(live_plan: dict, candidates: list[dict], formal_missing: list[dict],
                   acquisition_candidates: list[dict], scope_gaps: list[dict],
                   local_latest: date | None, live_latest: date | None,
                   first_discovered: list[dict],
                   frozen_missing: list[dict],
                   ready_count: int, formal_present_count: int,
                   weibo_plan: dict,
                   media_ready_by_key: dict[str, bool], tracked_keys: set[str]) -> None:
    coverage = weibo_plan["contiguous_complete"]
    print(f"Bilibili 官方合集更新范围：在线 {len(live_plan['entries'])} 条；可进入增量状态 {len(candidates)} 条；"
          f"增量来源媒体有效 {ready_count} 条；正式来源文件在位 {formal_present_count} 条；"
          f"待采集 {len(acquisition_candidates)} 条；"
          f"已正式归档但媒体缺失 {len(formal_missing)} 条")
    print(f"Bilibili 本地有效来源最新标题日期：{local_latest or '无'}；"
          f"官方合集最新标题日期：{live_latest or '无'}")
    print(f"本次首次发现的官方来源：{len(first_discovered)} 条")
    print(f"冻结计划中已不在当前在线合集的来源：{len(frozen_missing)} 条（仅报告，不自动移除）")
    print(f"微博目标日期范围：{weibo_plan['since']} 至 {weibo_plan['until']}；"
          f"本地归档请求最大日期：{weibo_plan['latest_requested_until'] or '无'}；"
          f"本地最新帖子：{weibo_plan['local_latest'] or '无'}")
    print(f"微博连续完整覆盖：{coverage[0]} 至 {coverage[1]}" if coverage else
          "微博连续完整覆盖：无")
    if weibo_plan["missing_ranges"]:
        print("微博待补日期缺口：" + ", ".join(
            f"{start}..{end}" for start, end in weibo_plan["missing_ranges"]))
    else:
        print("微博待补日期缺口：无")
    print("微博新帖数量：采集后统计")
    if weibo_plan["windows"]:
        print("微博待扫描/恢复窗口：" + ", ".join(
            f"{row['since']}..{row['until']}{' (resume)' if row['resume'] else ''}"
            for row in weibo_plan["windows"]))
    else:
        print("微博待扫描/恢复窗口：无")
    first_keys = {entry_key(item) for item in first_discovered}
    scope_gap_keys = {entry_key(item) for item in scope_gaps}
    for item in candidates:
        if entry_key(item) in scope_gap_keys:
            continue
        status = "媒体有效" if media_ready_by_key.get(entry_key(item), False) else "媒体待采集"
        discovery = ("本次首次发现" if entry_key(item) in first_keys else
                     "已跟踪" if entry_key(item) in tracked_keys else "已知来源")
        print(f"  增量来源：{entry_key(item)} {_phase(item)} {status} {discovery} {item.get('title', '')}")
    for item in formal_missing:
        print(f"  正式来源媒体缺失：{entry_key(item)} {item.get('title', '')}")
    for item in frozen_missing:
        print(f"  冻结计划来源未见于在线合集：{entry_key(item)} {item.get('title', '')}")
    for item in scope_gaps:
        discovery = ("本次首次发现" if entry_key(item) in first_keys else
                     "已跟踪" if entry_key(item) in tracked_keys else "已知来源")
        print(f"  范围缺口：{entry_key(item)} {_phase(item)} {discovery} {item.get('_scope_reason', '')} "
              f"{item.get('title', '')}")


def _confirm(yes: bool) -> bool:
    if yes:
        return True
    try:
        answer = input("开始采集上述视频和微博内容？ [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def needs_confirmation(new_state_entries: list, acquisition_candidates: list,
                       weibo_windows: list[dict]) -> bool:
    return bool(new_state_entries or acquisition_candidates or weibo_windows)


def run(args: argparse.Namespace, root: Path = ROOT) -> int:
    season = args.season
    collect_season.configure_season(season)
    bili_cookie_path = args.cookies_file
    weibo_cookie_path = args.weibo_cookies_file
    bili_auth, bili_cookies = resolve_auth(args.auth, bili_cookie_path)
    weibo_auth, weibo_cookies = resolve_auth(args.auth, weibo_cookie_path)

    live_plan = discover_live_plan(season, bili_auth, bili_cookies)
    plan_path = Path(root) / "data" / "indexes" / f"{season}_采集计划.json"
    if not plan_path.is_file():
        raise ValueError(f"缺少冻结采集计划：{plan_path}")
    baseline_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    live_entries = _match_entries(live_plan["entries"])
    frozen_entries = _match_entries(baseline_plan.get("entries", []))
    scoped_live_plan = {**live_plan, "entries": live_entries}
    formal_keys, formal_by_bvid_page = formal_dossier_sources(root, season)
    state = load_state(root, season)
    first_discovered = first_discovered_entries(
        live_entries, frozen_entries, state, formal_keys)

    candidates = []
    acquisition_candidates = []
    formal_missing = []
    scope_gaps = _unknown_phase_gaps(live_plan["entries"])
    media_ready_by_key = {}
    local_present_by_key = {}
    formal_present_count = 0
    previous_item_keys = set(state["items"])
    new_state_entries = []
    for entry in live_entries:
        key_tuple = _source_tuple(entry)
        key = entry_key(entry)
        formal = key_tuple in formal_keys
        scope, reason = scope_for_entry(entry, formal_by_bvid_page)
        conflicting_cid = raw_cid_conflict(root, entry)
        if conflicting_cid is not None:
            scope, reason = "scope_gap", "existing_raw_cid_conflict"
        if formal:
            present = formal_media_present(entry, root)
            local_present_by_key[key] = present
            formal_present_count += int(present)
            if not present:
                formal_missing.append(entry)
            if scope == "scope_gap":
                scope_gaps.append({**entry, "_scope_reason": reason})
            prior = state["items"].get(key)
            if prior is not None:
                prior["entry"] = entry
                prior["scope"] = "scope_gap" if scope == "scope_gap" else "out_of_scope"
                prior["scope_reason"] = reason if scope == "scope_gap" else "formal_dossier_exists"
                prior["formal_dossier"] = True
            continue
        media_ready = ready_media(entry, root)
        media_ready_by_key[key] = media_ready
        local_present_by_key[key] = media_ready
        _item_for_entry(state, root, entry, media_ready, scope, reason, False)
        if key not in previous_item_keys:
            new_state_entries.append(entry)
        candidates.append(entry)
        if scope == "scope_gap":
            scope_gaps.append({**entry, "_scope_reason": reason})
        elif not media_ready:
            acquisition_candidates.append(entry)

    for entry in frozen_entries:
        key = entry_key(entry)
        if key not in local_present_by_key:
            if _source_tuple(entry) in formal_keys:
                local_present_by_key[key] = formal_media_present(entry, root)
                formal_present_count += int(local_present_by_key[key])
            else:
                media_ready_by_key[key] = ready_media(entry, root)
                local_present_by_key[key] = media_ready_by_key[key]

    season_start = default_weibo_start(live_plan, args.since)
    until = args.until or beijing_today()
    if season_start is None:
        raise ValueError("无法从官方合集标题推断赛季起始日期；请传 --since YYYY-MM-DD")
    if season_start > until:
        raise ValueError("微博 --since 不能晚于 --until")
    local = weibo_local_snapshot(root, WEIBO_UID, post_since=season_start, post_until=until)
    since = args.since or season_start
    reported_since = since
    if args.since is None:
        missing = _missing_ranges(season_start, until, local["complete_intervals"])
        if missing:
            reported_since = missing[0][0]
    weibo_plan = plan_weibo_windows(root, WEIBO_UID, since, until)
    local_archives_in_scope = [item for item in local["archives"]
                               if item["since"] <= until and item["until"] >= season_start]
    latest_requested_until = max((item["until"] for item in local_archives_in_scope), default=None)
    weibo_plan.update(since=reported_since.isoformat(), until=until.isoformat(),
                      latest_requested_until=latest_requested_until,
                      local_latest=local["local_latest"])
    date_candidates = []
    local_date_candidates = []
    for entry in live_entries:
        raw_date = (entry.get("labels") or {}).get("event_date_candidate")
        try:
            candidate_date = date.fromisoformat(raw_date) if raw_date else None
        except ValueError:
            candidate_date = None
        if candidate_date:
            date_candidates.append(candidate_date)
    local_entries = {entry_key(entry): entry for entry in frozen_entries}
    local_entries.update({entry_key(entry): entry for entry in live_entries})
    for entry in local_entries.values():
        raw_date = (entry.get("labels") or {}).get("event_date_candidate")
        try:
            candidate_date = date.fromisoformat(raw_date) if raw_date else None
        except ValueError:
            candidate_date = None
        if candidate_date and local_present_by_key.get(entry_key(entry), False):
            local_date_candidates.append(candidate_date)
    live_latest = max(date_candidates, default=None)
    local_latest = max(local_date_candidates, default=None)
    live_source_keys = {_source_tuple(entry) for entry in live_entries}
    frozen_missing = [entry for entry in frozen_entries
                     if _source_tuple(entry) not in live_source_keys]
    _print_summary(scoped_live_plan, candidates, formal_missing, acquisition_candidates,
                   scope_gaps, local_latest, live_latest,
                   first_discovered, frozen_missing,
                   sum(media_ready_by_key.get(entry_key(entry), False)
                       for entry in live_entries), formal_present_count,
                   weibo_plan, media_ready_by_key, _state_match_keys(state))

    if args.check_only:
        return 0
    has_action = needs_confirmation(new_state_entries, acquisition_candidates, weibo_plan["windows"])
    if not has_action and not args.yes:
        print("没有新增来源、待采集视频或微博缺失窗口。")
        return 0
    if not _confirm(args.yes):
        print("未开始采集。")
        return 0

    save_state(root, season, state)

    try:
        bili_collector = collect_season.Collector(bili_auth, bili_cookies, quiet=True)
    except AuthConfigurationError as error:
        print(f"Bilibili 认证配置失败：{error}", file=sys.stderr)
        return 2
    all_successful = True
    for entry in acquisition_candidates:
        key = entry_key(entry)
        item = state["items"][key]
        item["acquisition"] = "pending"
        save_state(root, season, state)
        try:
            manifest_path = _download_one(entry, root, bili_collector)
            item["acquisition"] = "ready"
            item["acquisition_error"] = None
            item["manifest_path"] = manifest_path.relative_to(root).as_posix()
        except (CollectionError, AuthConfigurationError, requests.RequestException, OSError, ValueError) as error:
            item["acquisition"] = "failed"
            item["acquisition_error"] = (str(error) if isinstance(error, CollectionError)
                                         else type(error).__name__)
            all_successful = False
        save_state(root, season, state)
        print(f"{key} acquisition={item['acquisition']} {item.get('acquisition_error', '')}")
        if item["acquisition"] == "failed":
            break

    if not all_successful:
        print("增量采集因 Bilibili 媒体来源失败而停止。", file=sys.stderr)
        return 2

    if not _collect_weibo_windows(root, WEIBO_UID, weibo_plan["windows"],
                                  weibo_auth, weibo_cookies, state):
        all_successful = False
    print(f"增量采集状态：{'完成' if all_successful else '部分完成'}")
    return 0 if all_successful else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", choices=("S23",), default="S23")
    parser.add_argument("--auth", choices=("none", "cookies"),
                        help="同时指定 Bilibili 与 Weibo 认证模式；默认各自按 Cookie 文件是否存在选择")
    parser.add_argument("--cookies-file", type=Path, default=ROOT / DEFAULT_BILI_COOKIES)
    parser.add_argument("--weibo-cookies-file", type=Path, default=ROOT / DEFAULT_WEIBO_COOKIES)
    parser.add_argument("--since", type=date.fromisoformat, help="微博窗口起始日期，含当天")
    parser.add_argument("--until", type=date.fromisoformat, help="微博窗口结束日期，含当天；默认北京时间今天")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-only", action="store_true", help="只查看差异，不提示、不下载、不写状态")
    mode.add_argument("--yes", action="store_true", help="明确同意立即开始下载")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (CollectionError, WeiboCollectionError, AuthConfigurationError,
            requests.RequestException, OSError, ValueError, KeyError) as error:
        message = str(error) if isinstance(error, (CollectionError, WeiboCollectionError,
                                                   AuthConfigurationError, ValueError)) else type(error).__name__
        print(f"增量检查停止：{message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
