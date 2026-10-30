"""Behavioral tests for incremental source discovery and resumable acquisition state."""

import hashlib
import io
import json
from datetime import date, datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import collect_season
import media_ingest
from incremental_common import entry_key, load_state, ready_media, save_state, state_path, work_dir
import update_incremental as incremental


class FakeTimelineCollector:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get_timeline_page(self, uid, cursor):
        self.calls.append((uid, cursor))
        return self.pages.pop(0)


def status(post_id, published, uid="7525583841"):
    return {"idstr": post_id, "created_at": published,
            "user": {"idstr": uid, "screen_name": "test"}, "text": "test"}


def page(statuses, *, cursor="", has_more=False):
    return {"cards": [{"card_type": 9, "mblog": item} for item in statuses],
            "cardlistInfo": {"since_id": cursor, "has_more": has_more},
            "has_more": has_more}


class IncrementalCollectTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(__file__).resolve().parents[1]
        temp_root = workspace / "tmp"
        temp_root.mkdir(exist_ok=True)
        self.temporary = TemporaryDirectory(dir=temp_root)
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def entry(cid=10, page_number=1, phase="regular"):
        return {"bvid": "BV1AbCdeFgHi", "cid": cid, "page": page_number,
                "title": "测试正赛第1局",
                "labels": {"season": "S23", "phase_candidate": phase}}

    def write_media(self, entry, *, subtitle_body=None, audio=None):
        folder = (self.root / "data" / "raw" / "bilibili" / entry["bvid"] /
                  f"p{int(entry.get('page') or 1):02d}")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "metadata.raw.json").write_text(json.dumps({"data": {
            "bvid": entry["bvid"], "owner": {"mid": incremental.BILIBILI_MID},
            "pages": [{"page": int(entry.get("page") or 1), "cid": entry["cid"], "duration": 10}],
        }}), encoding="utf-8")
        subtitles = {"status": "visible_tracks", "tracks": []}
        if subtitle_body is not None:
            (folder / "subtitle.json").write_text(json.dumps({"body": subtitle_body}), encoding="utf-8")
            subtitles["tracks"].append({"platform": "bilibili", "provenance": "platform_visible_subtitle",
                                        "language": "ai-zh", "file": "subtitle.json"})
        manifest = {"bvid": entry["bvid"], "cid": entry["cid"],
                    "page": int(entry.get("page") or 1), "duration_seconds": 10,
                    "owner": {"mid": incremental.BILIBILI_MID}, "subtitles": subtitles}
        if audio is not None:
            payload, declared = audio
            (folder / "audio.m4a").write_bytes(payload)
            manifest["audio"] = {"file": "audio.m4a", "bytes": len(declared),
                                 "sha256": hashlib.sha256(declared).hexdigest(),
                                 "video_downloaded": False}
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return folder

    def test_source_key_includes_bvid_cid_and_page(self):
        self.assertEqual(entry_key(self.entry()), "BV1AbCdeFgHi:10:p01")
        self.assertEqual(entry_key(self.entry(cid=11)), "BV1AbCdeFgHi:11:p01")
        self.assertEqual(entry_key(self.entry(page_number=2)), "BV1AbCdeFgHi:10:p02")
        self.assertEqual(work_dir(self.root, "S23", self.entry()).as_posix().split("/")[-1],
                         "BV1AbCdeFgHi_p01_cid10")

    def test_state_round_trip_uses_required_shape_and_preserves_item_fields(self):
        state = load_state(self.root, "S23")
        entry = self.entry()
        key = entry_key(entry)
        state["items"][key] = {"entry": entry, "acquisition": "failed",
                                "analysis": "ready", "applied": True,
                                "custom_field": {"keep": True}}
        state["weibo"]["custom"] = "keep"
        save_state(self.root, "S23", state)
        loaded = load_state(self.root, "S23")
        self.assertEqual(set(loaded), {"schema_version", "season", "items", "weibo"})
        self.assertEqual(loaded["items"][key]["custom_field"], {"keep": True})
        self.assertEqual(loaded["weibo"]["custom"], "keep")
        self.assertTrue(state_path(self.root, "S23").is_file())

    def test_cid_change_adds_a_new_source_without_resetting_old_analysis_state(self):
        old = self.entry(cid=10)
        new = self.entry(cid=20)
        state = load_state(self.root, "S23")
        state["items"][entry_key(old)] = {
            "entry": old, "acquisition": "failed", "analysis": "ready",
            "applied": True, "review_note": "keep",
        }
        incremental._item_for_entry(state, self.root, old, False, "in_scope", None, False)
        incremental._item_for_entry(state, self.root, new, True, "in_scope", None, False)
        self.assertEqual(state["items"][entry_key(old)]["analysis"], "ready")
        self.assertTrue(state["items"][entry_key(old)]["applied"])
        self.assertEqual(state["items"][entry_key(old)]["review_note"], "keep")
        self.assertEqual(state["items"][entry_key(new)]["acquisition"], "ready")
        self.assertEqual(state["items"][entry_key(new)]["analysis"], "pending")
        self.assertFalse(state["items"][entry_key(new)]["applied"])

    def test_first_discovery_excludes_frozen_state_and_formal_sources(self):
        frozen = self.entry(cid=10)
        tracked = {**self.entry(cid=20), "bvid": "BV2AbCdeFgHi"}
        formal = {**self.entry(cid=30), "bvid": "BV3AbCdeFgHi"}
        fresh = {**self.entry(cid=40), "bvid": "BV4AbCdeFgHi"}
        state = {"items": {entry_key(tracked): {"acquisition": "failed"}}}
        result = incremental.first_discovered_entries(
            [frozen, tracked, formal, fresh], [frozen], state,
            {incremental._source_tuple(formal)})
        self.assertEqual(result, [fresh])

    def test_ready_media_requires_matching_source_and_valid_chinese_subtitle(self):
        entry = self.entry()
        self.write_media(entry, subtitle_body=[{"from": 0, "to": 1.25, "content": "字幕"}])
        with patch.object(media_ingest, "ROOT", self.root):
            self.assertTrue(ready_media(entry, self.root))
            self.assertFalse(ready_media(self.entry(cid=99), self.root))

    def test_ready_media_rejects_partial_subtitle_and_accepts_verified_audio(self):
        entry = self.entry()
        folder = self.write_media(entry, subtitle_body=[])
        manifest_path = folder / "manifest.json"
        with patch.object(media_ingest, "ROOT", self.root):
            self.assertFalse(ready_media(entry, self.root))
        payload = b"verified-audio"
        (folder / "subtitle.json").write_text(json.dumps({"body": [
            {"from": 0, "to": 1, "content": "valid"}]}), encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["audio"] = {"file": "audio.m4a", "bytes": len(payload),
                             "sha256": hashlib.sha256(payload).hexdigest(),
                             "video_downloaded": False}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (folder / "audio.m4a").write_bytes(payload)
        with patch.object(media_ingest, "ROOT", self.root), \
                patch.object(media_ingest, "probe_audio", return_value={"first_frame_decoded": True}):
            self.assertTrue(ready_media(entry, self.root))
            (folder / "audio.m4a").write_bytes(payload + b"partial")
            self.assertFalse(ready_media(entry, self.root))

    def test_weibo_cli_completion_predicate_ignores_partial_summary_label(self):
        manifest = {"status": "partial", "window_scan_status": "completed",
                    "counts": {"unparseable_dates_skipped": 0,
                               "images_not_downloaded": 0,
                               "long_posts_expanded": 2, "long_posts": 2}}
        self.assertTrue(incremental.archive_complete(manifest))
        manifest["window_scan_status"] = "in_progress"
        self.assertFalse(incremental.archive_complete(manifest))
        manifest["window_scan_status"] = "completed"
        manifest["counts"]["images_not_downloaded"] = 1
        self.assertFalse(incremental.archive_complete(manifest))
        manifest["counts"]["images_not_downloaded"] = 0
        manifest["counts"].pop("long_posts")
        self.assertFalse(incremental.archive_complete(manifest))

    def test_completed_window_still_exposes_the_next_day_and_incomplete_window_resumes(self):
        base = self.root / "data" / "raw" / "weibo"
        complete_dir = base / "complete"
        complete_dir.mkdir(parents=True)
        (complete_dir / "manifest.json").write_text(json.dumps({
            "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                "since": "2026-10-20", "until": "2026-10-30", "list_backend": "mobile"},
            "window_scan_status": "completed",
            "counts": {"unparseable_dates_skipped": 0, "images_not_downloaded": 0,
                       "long_posts_expanded": 0, "long_posts": 0}, "posts": []}), encoding="utf-8")
        incomplete_dir = incremental._archive_dir(
            self.root, date(2026, 10, 31), date(2026, 10, 31), incremental.WEIBO_UID)
        incomplete_dir.mkdir(parents=True)
        (incomplete_dir / "manifest.json").write_text(json.dumps({
            "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                "since": "2026-10-31", "until": "2026-10-31", "list_backend": "desktop"},
            "window_scan_status": "in_progress", "counts": {}, "posts": []}), encoding="utf-8")
        plan = incremental.plan_weibo_windows(self.root, incremental.WEIBO_UID,
                                               date(2026, 10, 20), date(2026, 10, 31))
        self.assertIn((date(2026, 10, 31), date(2026, 10, 31)),
                      [(window["since"], window["until"]) for window in plan["windows"]])
        resumed = [window for window in plan["windows"] if window["resume"]]
        self.assertEqual(len(resumed), 1)
        self.assertEqual(resumed[0]["path"], incomplete_dir)

    def test_incomplete_mobile_window_migrates_to_desktop_folder_with_seed(self):
        since, until = date(2026, 10, 20), date(2026, 10, 30)
        mobile_dir = incremental._archive_dir(self.root, since, until, incremental.WEIBO_UID)
        mobile_dir.mkdir(parents=True)
        mobile_manifest = mobile_dir / "manifest.json"
        original = {
            "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                "since": since.isoformat(), "until": until.isoformat()},
            "window_scan_status": "in_progress", "pagination": {"next_cursor": "legacy-mobile-cursor"},
            "counts": {}, "posts": [],
        }
        mobile_manifest.write_text(json.dumps(original), encoding="utf-8")

        plan = incremental.plan_weibo_windows(
            self.root, incremental.WEIBO_UID, since, until, scan_date=date(2026, 10, 31))

        self.assertEqual(len(plan["windows"]), 1)
        window = plan["windows"][0]
        self.assertEqual(window["path"], incremental._desktop_archive_dir(
            self.root, since, until, incremental.WEIBO_UID))
        self.assertFalse(window["resume"])
        self.assertEqual(window["seed_path"], mobile_manifest)
        self.assertEqual(json.loads(mobile_manifest.read_text(encoding="utf-8")), original)

    def test_existing_desktop_counterpart_resumes_without_mobile_seed(self):
        since, until = date(2026, 10, 20), date(2026, 10, 30)
        mobile_dir = incremental._archive_dir(self.root, since, until, incremental.WEIBO_UID)
        mobile_dir.mkdir(parents=True)
        (mobile_dir / "manifest.json").write_text(json.dumps({
            "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                "since": since.isoformat(), "until": until.isoformat()},
            "window_scan_status": "in_progress", "counts": {}, "posts": [],
        }), encoding="utf-8")
        desktop_dir = incremental._desktop_archive_dir(self.root, since, until,
                                                       incremental.WEIBO_UID)
        desktop_dir.mkdir(parents=True)
        (desktop_dir / "manifest.json").write_text(json.dumps({
            "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                "since": since.isoformat(), "until": until.isoformat(),
                "list_backend": "desktop"},
            "window_scan_status": "in_progress", "counts": {}, "posts": [],
        }), encoding="utf-8")

        plan = incremental.plan_weibo_windows(
            self.root, incremental.WEIBO_UID, since, until, scan_date=date(2026, 10, 31))

        self.assertEqual(len(plan["windows"]), 1)
        window = plan["windows"][0]
        self.assertEqual(window["path"], desktop_dir)
        self.assertTrue(window["resume"])
        self.assertIsNone(window["seed_path"])

    def test_completed_desktop_coverage_suppresses_an_older_mobile_partial(self):
        since, yesterday, today = date(2026, 10, 20), date(2026, 10, 29), date(2026, 10, 30)
        mobile_dir = incremental._archive_dir(self.root, since, yesterday, incremental.WEIBO_UID)
        mobile_dir.mkdir(parents=True)
        (mobile_dir / "manifest.json").write_text(json.dumps({
            "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                "since": since.isoformat(), "until": yesterday.isoformat()},
            "window_scan_status": "in_progress", "counts": {}, "posts": [],
        }), encoding="utf-8")
        desktop_dir = incremental._desktop_archive_dir(self.root, since, yesterday,
                                                       incremental.WEIBO_UID)
        desktop_dir.mkdir(parents=True)
        (desktop_dir / "manifest.json").write_text(json.dumps({
            "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                "since": since.isoformat(), "until": yesterday.isoformat(),
                "list_backend": "desktop"},
            "window_scan_status": "completed",
            "counts": {"unparseable_dates_skipped": 0, "images_not_downloaded": 0,
                       "long_posts_expanded": 0, "long_posts": 0},
            "posts": [],
        }), encoding="utf-8")

        plan = incremental.plan_weibo_windows(
            self.root, incremental.WEIBO_UID, since, today, scan_date=date(2026, 10, 31))

        self.assertEqual([(window["since"], window["until"]) for window in plan["windows"]],
                         [(today, today)])

    def test_combined_complete_archives_suppress_a_redundant_legacy_partial(self):
        base = self.root / "data" / "raw" / "weibo"
        completed_counts = {"unparseable_dates_skipped": 0, "images_not_downloaded": 0,
                            "long_posts_expanded": 0, "long_posts": 0}
        for name, since, until, backend, completed_at in [
                ("old_complete", "2026-09-01", "2026-10-19", "mobile", "2026-10-20T02:00:00Z"),
                ("new_complete", "2026-10-20", "2026-10-30", "desktop", "2026-10-30T10:00:00Z"),
                ("old_partial", "2026-09-20", "2026-10-20", "mobile", None)]:
            folder = base / name
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(json.dumps({
                "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                    "since": since, "until": until, "list_backend": backend},
                "window_scan_status": "completed" if completed_at else "in_progress",
                "updated_at_utc": completed_at,
                "counts": completed_counts if completed_at else {}, "posts": [],
            }), encoding="utf-8")
        partial_path = base / "old_partial" / "manifest.json"
        original_partial = partial_path.read_bytes()

        plan = incremental.plan_weibo_windows(
            self.root, incremental.WEIBO_UID, date(2026, 9, 1), date(2026, 10, 30),
            scan_date=date(2026, 10, 30))

        self.assertEqual([(window["since"], window["until"]) for window in plan["windows"]],
                         [(date(2026, 10, 30), date(2026, 10, 30))])
        self.assertEqual(partial_path.read_bytes(), original_partial)

    def test_weibo_metadata_scan_returns_exact_new_post_diff_and_handles_no_posts(self):
        collector = FakeTimelineCollector([page([
            status("known01", "Thu Oct 29 10:00:00 +0800 2026"),
            status("newpost1", "Thu Oct 29 11:00:00 +0800 2026"),
        ], has_more=False)])
        result = incremental.scan_weibo_window(collector, incremental.WEIBO_UID,
                                               date(2026, 10, 21), date(2026, 10, 29),
                                               {"known01"})
        self.assertTrue(result["window_scan_status"] == "completed")
        self.assertEqual([row["post_id"] for row in result["new_posts"]], ["newpost1"])
        self.assertEqual(result["newest_visible_online"], "2026-10-29")

        empty = FakeTimelineCollector([page([], has_more=False)])
        result = incremental.scan_weibo_window(empty, incremental.WEIBO_UID,
                                               date(2026, 10, 21), date(2026, 10, 29), set())
        self.assertEqual(result["new_posts"], [])
        self.assertIsNone(result["newest_visible_online"])
        self.assertEqual(result["window_scan_status"], "completed")

    def test_unknown_and_formal_cid_conflict_are_reported_as_scope_gaps(self):
        entry = self.entry(phase="unknown")
        scope, reason = incremental.scope_for_entry(entry, {})
        self.assertEqual((scope, reason), ("scope_gap", "unknown_phase"))
        scope, reason = incremental.scope_for_entry(
            self.entry(cid=20), {(entry["bvid"], 1): {entry["cid"]}})
        self.assertEqual((scope, reason), ("scope_gap", "formal_source_cid_conflict"))

    def test_run_limits_counts_readiness_and_state_updates_to_match_phases(self):
        def make_entry(number, phase):
            return {"bvid": f"BV{number:010d}", "cid": number + 1000, "page": 1,
                    "title": f"测试来源 {number}",
                    "labels": {"season": "S23", "phase_candidate": phase,
                               "event_date_candidate": "2026-09-01"}}

        showmatches = [make_entry(i, "showmatch") for i in range(1, 13)]
        regular = [make_entry(i, "regular") for i in range(101, 110)]
        formal = [make_entry(i, "regular") for i in range(201, 276)]
        unknown = make_entry(301, "unknown")
        live_entries = showmatches + [unknown] + regular + formal
        formal_sources = {incremental._source_tuple(entry) for entry in formal}
        state = {"season": "S23", "items": {}, "weibo": {}}
        for entry in showmatches + formal:
            state["items"][entry_key(entry)] = {
                "entry": entry, "scope": "out_of_scope" if entry in showmatches else "in_scope",
                "acquisition": "failed", "analysis": "ready", "applied": True,
                "custom_field": "preserve",
            }
        showmatch_before = {entry_key(entry): dict(state["items"][entry_key(entry)])
                            for entry in showmatches}

        plan_path = self.root / "data" / "indexes" / "S23_采集计划.json"
        plan_path.parent.mkdir(parents=True)
        plan_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        ready_calls = []

        def ready_media_spy(entry, root):
            ready_calls.append(entry_key(entry))
            return False

        args = type("Args", (), {
            "season": "S23", "cookies_file": None, "weibo_cookies_file": None,
            "auth": "none", "since": date(2026, 9, 1), "until": date(2026, 9, 2),
            "check_only": True, "yes": False,
        })()
        output = io.StringIO()
        with patch.object(collect_season, "configure_season"), \
                patch.object(incremental, "discover_live_plan", return_value={
                    "season": "S23", "entries": live_entries}), \
                patch.object(incremental, "formal_dossier_sources",
                             return_value=(formal_sources, {})), \
                patch.object(incremental, "load_state", return_value=state), \
                patch.object(incremental, "ready_media", side_effect=ready_media_spy), \
                patch.object(incremental, "formal_media_present", return_value=True), \
                patch.object(incremental, "raw_cid_conflict", return_value=None) as cid_check, \
                patch.object(incremental, "weibo_local_snapshot", return_value={
                    "local_latest": None, "earliest_collection": None,
                    "archives": [], "complete_intervals": []}), \
                patch.object(incremental, "plan_weibo_windows", return_value={
                    "windows": [], "scan_windows": [], "known_ids": set(),
                    "local_latest": None, "contiguous_complete": None,
                    "latest_requested_until": None, "missing_ranges": []}), \
                patch.object(incremental, "scan_weibo",
                             side_effect=AssertionError("daily flow must not scan timeline")), \
                patch.object(incremental, "save_state") as save, \
                patch.object(collect_season, "Collector") as bili_collector, \
                patch("sys.stdout", output):
            result = incremental.run(args, self.root)

        self.assertEqual(result, 0)
        report = output.getvalue()
        self.assertIn("官方合集更新范围：在线 84 条；可进入增量状态 9 条", report)
        self.assertIn("本次首次发现的官方来源：9 条", report)
        self.assertEqual(report.count("  增量来源："), 9)
        self.assertIn("范围缺口：BV0000000301:1301:p01 unknown 已知来源 unknown_phase", report)
        self.assertNotIn("showmatch", report)
        self.assertFalse(set(ready_calls) & {entry_key(entry) for entry in showmatches})
        self.assertEqual(set(ready_calls), {entry_key(entry) for entry in regular})
        self.assertEqual(cid_check.call_count, len(regular) + len(formal))
        for entry in showmatches:
            self.assertEqual(state["items"][entry_key(entry)], showmatch_before[entry_key(entry)])
        for entry in formal:
            item = state["items"][entry_key(entry)]
            self.assertEqual((item["analysis"], item["applied"], item["custom_field"]),
                             ("ready", True, "preserve"))
        self.assertEqual(sum(entry_key(entry) in state["items"] for entry in formal), 75)
        save.assert_not_called()
        bili_collector.assert_not_called()

    def test_only_exact_formal_dossier_source_is_excluded_from_new_queue(self):
        dossier = self.root / "data" / "games" / "S23" / "2026-09-01_g01_BV1AbCdeFgHi-p02-g01" / "dossier.json"
        dossier.parent.mkdir(parents=True)
        dossier.write_text(json.dumps({
            "season": "S23", "slug": "bili-BV1AbCdeFgHi-p02-g01",
            "files": [{"role": "manifest", "external_key": "BV1AbCdeFgHi:10"}],
        }), encoding="utf-8")
        exact, by_page = incremental.formal_dossier_sources(self.root, "S23")
        self.assertIn(("BV1AbCdeFgHi", 10, 2), exact)
        self.assertEqual(by_page[("BV1AbCdeFgHi", 2)], {10})
        self.assertNotIn(("BV1AbCdeFgHi", 11, 2), exact)

    def test_raw_cid_conflict_is_reported_without_overwriting_the_source(self):
        entry = self.entry(cid=20)
        folder = self.root / "data" / "raw" / "bilibili" / entry["bvid"] / "p01"
        folder.mkdir(parents=True)
        manifest_path = folder / "manifest.json"
        original = {"bvid": entry["bvid"], "cid": 10, "page": 1, "marker": "keep"}
        manifest_path.write_text(json.dumps(original), encoding="utf-8")
        self.assertEqual(incremental.raw_cid_conflict(self.root, entry), 10)

        class FakeCollector:
            calls = 0
            def api(self, path, params):
                return {"data": {"pages": [{"page": 1, "cid": 30}]}}
            def collect(self, *args, **kwargs):
                self.calls += 1
                return {}

        with self.assertRaises(incremental.CollectionError):
            incremental._download_one(entry, self.root, FakeCollector())
        self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8")), original)

    def test_season_opening_does_not_use_an_older_cross_season_archive(self):
        plan = {"entries": [
            {"labels": {"event_date_candidate": "2026-09-01"}},
            {"labels": {"event_date_candidate": "2026-09-03"}},
        ]}
        archive = self.root / "data" / "raw" / "weibo" / "prior-season" / "manifest.json"
        archive.parent.mkdir(parents=True)
        archive.write_text(json.dumps({
            "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                "since": "2026-05-26", "until": "2026-10-20"},
            "window_scan_status": "completed",
            "counts": {"unparseable_dates_skipped": 0, "images_not_downloaded": 0,
                       "long_posts_expanded": 0, "long_posts": 0},
            "updated_at_utc": "2026-10-20T15:02:00+00:00", "posts": [],
        }), encoding="utf-8")
        snapshot = incremental.weibo_local_snapshot(self.root, incremental.WEIBO_UID)
        self.assertEqual(snapshot["earliest_collection"], date(2026, 5, 26))
        self.assertEqual(incremental.default_weibo_start(plan), date(2026, 9, 1))

    def test_daily_plan_starts_at_existing_coverage_gap_and_targets_today(self):
        window_start = date(2026, 9, 1)
        yesterday = date(2026, 10, 29)
        today = date(2026, 10, 30)
        archive = incremental._archive_dir(self.root, window_start, yesterday,
                                           incremental.WEIBO_UID)
        archive.mkdir(parents=True)
        (archive / "manifest.json").write_text(json.dumps({
            "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                "since": window_start.isoformat(), "until": yesterday.isoformat()},
            "window_scan_status": "completed",
            "counts": {"unparseable_dates_skipped": 0, "images_not_downloaded": 0,
                       "long_posts_expanded": 0, "long_posts": 0},
            "incremental_scan_completed_at_utc": "2026-10-30T10:00:00+00:00",
            "posts": [{"post_id": "local123", "published_date": "2026-10-28"}],
        }), encoding="utf-8")
        entry = self.entry(phase="regular")
        entry["labels"]["event_date_candidate"] = window_start.isoformat()
        index = self.root / "data" / "indexes" / "S23_采集计划.json"
        index.parent.mkdir(parents=True)
        index.write_text(json.dumps({"entries": []}), encoding="utf-8")
        args = type("Args", (), {
            "season": "S23", "cookies_file": None, "weibo_cookies_file": None,
            "auth": "none", "since": None, "until": None,
            "check_only": True, "yes": False,
        })()
        output = io.StringIO()
        with patch.object(collect_season, "configure_season"), \
                patch.object(incremental, "discover_live_plan", return_value={
                    "season": "S23", "entries": [entry]}), \
                patch.object(incremental, "formal_dossier_sources", return_value=(set(), {})), \
                patch.object(incremental, "ready_media", return_value=True), \
                patch.object(incremental, "scan_weibo",
                             side_effect=AssertionError("daily flow must not scan timeline")), \
                patch.object(incremental, "save_state") as save, \
                patch.object(collect_season, "Collector"), \
                patch.object(incremental, "beijing_today", return_value=today), \
                patch("sys.stdout", output):
            result = incremental.run(args, self.root)

        self.assertEqual(result, 0)
        report = output.getvalue()
        self.assertIn("微博目标日期范围：2026-10-30 至 2026-10-30", report)
        self.assertIn("本地归档请求最大日期：2026-10-29", report)
        self.assertIn("本地最新帖子：2026-10-28", report)
        self.assertIn("微博待补日期缺口：2026-10-30..2026-10-30", report)
        self.assertIn("微博新帖数量：采集后统计", report)
        self.assertNotIn("线上最新", report)
        save.assert_not_called()

    def test_confirmation_precedes_any_weibo_collection(self):
        entry = self.entry(phase="regular")
        entry["labels"]["event_date_candidate"] = "2026-09-01"
        index = self.root / "data" / "indexes" / "S23_采集计划.json"
        index.parent.mkdir(parents=True)
        index.write_text(json.dumps({"entries": []}), encoding="utf-8")
        args = type("Args", (), {
            "season": "S23", "cookies_file": None, "weibo_cookies_file": None,
            "auth": "none", "since": date(2026, 9, 1), "until": date(2026, 9, 2),
            "check_only": False, "yes": False,
        })()
        observed = []
        with patch.object(collect_season, "configure_season"), \
                patch.object(incremental, "discover_live_plan", return_value={
                    "season": "S23", "entries": [entry]}), \
                patch.object(incremental, "formal_dossier_sources", return_value=(set(), {})), \
                patch.object(incremental, "ready_media", return_value=True), \
                patch.object(incremental, "weibo_local_snapshot", return_value={
                    "local_latest": None, "earliest_collection": None,
                    "archives": [], "complete_intervals": []}), \
                patch.object(incremental, "plan_weibo_windows", return_value={
                    "windows": [{"since": date(2026, 9, 2), "until": date(2026, 9, 2),
                                 "path": None, "resume": False}],
                    "scan_windows": [], "known_ids": set(), "local_latest": None,
                    "contiguous_complete": None, "latest_requested_until": None,
                    "missing_ranges": [(date(2026, 9, 2), date(2026, 9, 2))]}), \
                patch.object(incremental, "scan_weibo",
                             side_effect=AssertionError("daily flow must not scan timeline")), \
                patch.object(incremental, "_confirm", side_effect=lambda yes: observed.append("confirm") or False), \
                patch.object(incremental, "_new_desktop_weibo_collector",
                             side_effect=lambda session: observed.append("collector") or object()), \
                patch.object(incremental, "collect_archive",
                             side_effect=lambda *args, **kwargs: observed.append("collect")), \
                patch.object(incremental, "save_state") as save:
            result = incremental.run(args, self.root)
        self.assertEqual(result, 0)
        self.assertEqual(observed, ["confirm"])
        save.assert_not_called()

    def test_default_auth_does_not_pass_cookie_path_in_anonymous_mode(self):
        cookie_path = self.root / "bilibili.cookies.txt"
        self.assertEqual(incremental.resolve_auth(None, cookie_path), ("none", None))
        cookie_path.write_text("cookie file", encoding="utf-8")
        self.assertEqual(incremental.resolve_auth(None, cookie_path), ("cookies", cookie_path))
        self.assertEqual(incremental.resolve_auth("none", cookie_path), ("none", None))

    def test_daily_weibo_collector_is_the_desktop_backend(self):
        collector = incremental._new_desktop_weibo_collector(incremental.requests.Session())
        self.assertEqual(collector.list_backend, "desktop")

    def test_completed_noon_archive_rescans_its_unclosed_day_in_a_refresh_archive(self):
        start = end = date(2026, 10, 30)
        canonical = incremental._archive_dir(self.root, start, end, incremental.WEIBO_UID)
        canonical.mkdir(parents=True)
        canonical_manifest = canonical / "manifest.json"
        old_manifest = {
            "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                "since": start.isoformat(), "until": end.isoformat(), "list_backend": "desktop"},
            "window_scan_status": "completed",
            "counts": {"unparseable_dates_skipped": 0, "images_not_downloaded": 0,
                       "long_posts_expanded": 0, "long_posts": 0},
            "updated_at_utc": "2026-10-30T04:00:00+00:00", "posts": [],
        }
        canonical_manifest.write_text(json.dumps(old_manifest), encoding="utf-8")
        plan = incremental.plan_weibo_windows(
            self.root, incremental.WEIBO_UID, start, end, scan_date=date(2026, 10, 31))
        self.assertEqual(plan["missing_ranges"], [(start, end)])
        self.assertEqual(len(plan["windows"]), 1)
        window = plan["windows"][0]
        self.assertIn("_late_scan_20261031", window["path"].name)
        self.assertEqual(window["seed_path"], canonical_manifest)

        completed = {**old_manifest, "updated_at_utc": "2026-10-31T02:00:00+00:00"}
        state = {"season": "S23", "items": {}, "weibo": {}}
        with patch.object(incremental, "_new_desktop_weibo_collector", return_value=object()), \
                patch.object(incremental, "collect_archive", return_value=completed) as collect:
            self.assertTrue(incremental._collect_weibo_windows(
                self.root, incremental.WEIBO_UID, plan["windows"], "none", None, state,
                completed_at=datetime(2026, 10, 31, 2, tzinfo=timezone.utc)))
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(collect.call_args.args[1], window["path"])
        self.assertEqual(collect.call_args.kwargs["seed_path"], canonical_manifest)
        self.assertEqual(json.loads(canonical_manifest.read_text(encoding="utf-8")), old_manifest)
        refreshed = json.loads((window["path"] / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(refreshed["incremental_scan_completed_at_utc"], "2026-10-31T02:00:00+00:00")
        refreshed_snapshot = incremental.weibo_local_snapshot(self.root, incremental.WEIBO_UID)
        self.assertEqual(refreshed_snapshot["complete_intervals"], [(start, end)])

    def test_repairing_completed_scan_preserves_legacy_scan_time_basis(self):
        start = end = date(2026, 10, 30)
        canonical = incremental._archive_dir(self.root, start, end, incremental.WEIBO_UID)
        canonical.mkdir(parents=True)
        manifest_path = canonical / "manifest.json"
        old = {
            "mode": "author", "request": {"uid": incremental.WEIBO_UID,
                "since": start.isoformat(), "until": end.isoformat(), "list_backend": "desktop"},
            "window_scan_status": "completed",
            "counts": {"unparseable_dates_skipped": 0, "images_not_downloaded": 1,
                       "long_posts_expanded": 0, "long_posts": 0},
            "updated_at_utc": "2026-10-30T04:00:00+00:00", "posts": [],
        }
        manifest_path.write_text(json.dumps(old), encoding="utf-8")
        plan = incremental.plan_weibo_windows(
            self.root, incremental.WEIBO_UID, start, end, scan_date=date(2026, 10, 31))
        self.assertEqual(len(plan["windows"]), 2)
        repair = next(row for row in plan["windows"] if row["resume"])
        refresh = next(row for row in plan["windows"] if not row["resume"])
        repaired = {**old, "counts": {"unparseable_dates_skipped": 0,
                    "images_not_downloaded": 0, "long_posts_expanded": 0, "long_posts": 0},
                    "updated_at_utc": "2026-10-31T02:00:00+00:00"}
        rescanned = {**repaired}
        state = {"season": "S23", "items": {}, "weibo": {}}
        with patch.object(incremental, "_new_desktop_weibo_collector", return_value=object()), \
                patch.object(incremental, "collect_archive", side_effect=[repaired, rescanned]):
            self.assertTrue(incremental._collect_weibo_windows(
                self.root, incremental.WEIBO_UID, plan["windows"], "none", None, state,
                completed_at=datetime(2026, 10, 31, 2, tzinfo=timezone.utc)))
        repaired_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(repaired_manifest["incremental_coverage_basis_utc"], old["updated_at_utc"])
        self.assertNotIn("incremental_scan_completed_at_utc", repaired_manifest)
        refreshed_manifest = json.loads((refresh["path"] / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(refreshed_manifest["incremental_scan_completed_at_utc"],
                         "2026-10-31T02:00:00+00:00")

    def test_discovery_plan_builder_uses_temporary_output_root(self):
        observed = {}
        def fake_build(auth, cookies):
            observed["auth"] = auth
            observed["root"] = collect_season.ROOT
            target = Path(collect_season.ROOT, "written-in-temp.json")
            target.write_text("{}", encoding="utf-8")
            observed["written"] = target.is_file()
            return {"entries": [], "season": "S23"}

        original_root = collect_season.ROOT
        with patch.object(collect_season, "build_plan", side_effect=fake_build):
            result = incremental.discover_live_plan("S23", "none", None)
        self.assertEqual(result["season"], "S23")
        self.assertEqual(observed["auth"], "none")
        self.assertNotEqual(observed["root"], original_root)
        self.assertTrue(observed["written"])

    def test_prompt_defaults_to_no(self):
        with patch("builtins.input", return_value=""):
            self.assertFalse(incremental._confirm(False))
        with patch("builtins.input", return_value="Y"):
            self.assertTrue(incremental._confirm(False))

    def test_no_prompt_without_new_state_acquisition_or_weibo_windows(self):
        self.assertFalse(incremental.needs_confirmation([], [], []))
        self.assertTrue(incremental.needs_confirmation([self.entry()], [], []))
        self.assertTrue(incremental.needs_confirmation([], [], [{"since": date.today()}]))

    def test_weibo_acquisition_stops_after_first_incomplete_window(self):
        class FakeCollector:
            def __init__(self, session=None):
                pass

        partial = {"window_scan_status": "in_progress", "counts": {
            "unparseable_dates_skipped": 0, "images_not_downloaded": 0,
            "long_posts_expanded": 0, "long_posts": 0}, "termination_reason": "api_rejected"}
        complete = {"window_scan_status": "completed", "counts": {
            "unparseable_dates_skipped": 0, "images_not_downloaded": 0,
            "long_posts_expanded": 0, "long_posts": 0}, "termination_reason": "api_end_marker"}
        state = {"season": "S23", "items": {}, "weibo": {}}
        windows = [
            {"since": date(2026, 9, 1), "until": date(2026, 9, 2), "path": None, "resume": False},
            {"since": date(2026, 9, 3), "until": date(2026, 9, 4), "path": None, "resume": False},
        ]
        with patch.object(incremental, "_new_desktop_weibo_collector", return_value=FakeCollector()), \
                patch.object(incremental, "collect_archive", side_effect=[partial, complete]) as collect:
            success = incremental._collect_weibo_windows(
                self.root, incremental.WEIBO_UID, windows, "none", None, state)
        self.assertFalse(success)
        self.assertEqual(collect.call_count, 1)
        self.assertFalse(state["weibo"]["windows"][0]["complete"])

    def test_weibo_timeline_is_not_scanned_and_user_can_decline_before_weibo_collection(self):
        entry = self.entry(phase="regular")
        entry["labels"]["event_date_candidate"] = "2026-09-01"
        live_plan = {"season": "S23", "entries": [entry]}
        index = self.root / "data" / "indexes" / "S23_采集计划.json"
        index.parent.mkdir(parents=True)
        index.write_text(json.dumps({"entries": []}), encoding="utf-8")
        for check_only in (True, False):
            args = type("Args", (), {
                "season": "S23", "cookies_file": None, "weibo_cookies_file": None,
                "auth": None, "since": date(2026, 9, 1), "until": date(2026, 9, 2),
                "check_only": check_only, "yes": False,
            })()
            output = io.StringIO()
            with patch.object(collect_season, "configure_season"), \
                    patch.object(incremental, "discover_live_plan", return_value=live_plan), \
                    patch.object(incremental, "formal_dossier_sources", return_value=(set(), {})), \
                    patch.object(incremental, "ready_media", return_value=True), \
                    patch.object(incremental, "weibo_local_snapshot", return_value={
                        "local_latest": None, "earliest_collection": None,
                        "archives": [], "complete_intervals": []}), \
                    patch.object(incremental, "plan_weibo_windows", return_value={
                        "windows": [], "scan_windows": [], "known_ids": set(),
                        "local_latest": None, "contiguous_complete": None,
                        "latest_requested_until": None, "missing_ranges": []}), \
                    patch.object(incremental, "scan_weibo",
                                 side_effect=AssertionError("daily flow must not scan timeline")), \
                    patch.object(incremental, "_new_desktop_weibo_collector",
                                 side_effect=AssertionError("declining must not create a Weibo collector")), \
                    patch.object(incremental, "save_state") as save, \
                    patch.object(incremental, "_confirm", return_value=False) as confirm, \
                    patch.object(collect_season, "Collector") as bili_collector, \
                    patch("sys.stdout", output):
                result = incremental.run(args, self.root)
            self.assertEqual(result, 0)
            report = output.getvalue()
            self.assertIn("Bilibili 官方合集更新范围：在线 1 条", report)
            self.assertIn("微博新帖数量：采集后统计", report)
            self.assertNotIn("线上", report)
            save.assert_not_called()
            self.assertEqual(confirm.call_count, 0 if check_only else 1)
            bili_collector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
