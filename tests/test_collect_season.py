"""Regression coverage for local-only season acquisition."""

import importlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_season
from collect_bilibili_audio import CollectionError
import media_ingest


class FakeCollector:
    responses = []
    calls = []

    def __init__(self, auth, cookies, quiet=False):
        self.auth = auth
        self.cookies = cookies

    def collect(self, bvid, page, out, audio, max_bitrate, max_bytes,
                expected_owner=None, *, subtitles_first=False):
        type(self).calls.append({"bvid": bvid, "page": page, "audio": audio,
                                 "expected_owner": expected_owner,
                                 "subtitles_first": subtitles_first})
        response = type(self).responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class CollectSeasonTests(unittest.TestCase):
    def setUp(self):
        FakeCollector.responses = []
        FakeCollector.calls = []
        task_tmp = Path(__file__).resolve().parents[1] / "tmp"
        task_tmp.mkdir(exist_ok=True)
        self.temporary = TemporaryDirectory(dir=task_tmp)
        self.root = Path(self.temporary.name)
        self.state_path = self.root / "data/reports/S22/S22_采集进度.json"
        self.root_patch = patch.object(collect_season, "ROOT", self.root)
        self.state_patch = patch.object(collect_season, "STATE", self.state_path)
        self.collector_patch = patch.object(collect_season, "Collector", FakeCollector)
        self.root_patch.start()
        self.state_patch.start()
        self.collector_patch.start()

    def tearDown(self):
        self.collector_patch.stop()
        self.state_patch.stop()
        self.root_patch.stop()
        self.temporary.cleanup()

    def plan(self, count=2):
        entries = [{"index": index, "bvid": f"BV000000000{index}", "cid": 100 + index,
                    "page": 1, "title": f"测试第{index}局", "duration_seconds": 10}
                   for index in range(1, count + 1)]
        return {"season": collect_season.SEASON,
                "collection_id": collect_season.COLLECTION_ID,
                "declared_count": count, "entry_count": count,
                "entries": entries}

    @staticmethod
    def manifest(entry, *, tracks=None, audio=None, cid=None):
        return {"bvid": entry["bvid"], "page": entry["page"],
                "cid": entry["cid"] if cid is None else cid,
                "subtitles": {"status": "visible_tracks" if tracks else "none_visible",
                              "tracks": tracks or []},
                "audio": audio}

    def test_import_does_not_require_database_or_pyav(self):
        with patch.dict(sys.modules, {"psycopg": None, "database": None, "av": None}):
            importlib.reload(collect_season)
        self.assertFalse(hasattr(collect_season, "database"))
        self.assertFalse(hasattr(collect_season, "validate_media"))
        self.assertFalse(hasattr(collect_season, "probe_audio"))

    def test_all_entries_use_subtitles_first_and_audio_fallback_is_success(self):
        plan = self.plan()
        FakeCollector.responses = [
            self.manifest(plan["entries"][0], tracks=[{"language": "zh-CN"}]),
            self.manifest(plan["entries"][1], audio={"bytes": 12, "sha256": "a" * 64}),
        ]
        with patch.dict(sys.modules, {"psycopg": None, "database": None, "av": None}):
            with patch.object(media_ingest, "validate_media", side_effect=AssertionError) as validate, \
                 patch.object(media_ingest, "probe_audio", side_effect=AssertionError) as probe, \
                 patch.object(collect_season, "ROOT", self.root), \
                 patch.object(collect_season, "STATE", self.state_path), \
                 patch.object(collect_season, "Collector", FakeCollector):
                self.assertEqual(collect_season.run(plan, "none", None), 0)
                validate.assert_not_called()
                probe.assert_not_called()
        self.assertEqual(len(FakeCollector.calls), 2)
        self.assertTrue(all(call["subtitles_first"] for call in FakeCollector.calls))
        self.assertTrue(all(call["audio"] for call in FakeCollector.calls))
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["items"]["BV0000000001:101"]["status"], "complete")
        self.assertEqual(state["items"]["BV0000000002:102"]["status"], "audio_only")
        self.assertEqual(state["summary"]["successful"], 2)
        self.assertEqual(state["current_run"]["state"], "finished")

    def test_collection_error_is_recorded_and_stops_before_next_entry(self):
        plan = self.plan()
        FakeCollector.responses = [CollectionError("字幕查询失败")]
        result = collect_season.run(plan, "none", None)
        self.assertEqual(result, 1)
        self.assertEqual(len(FakeCollector.calls), 1)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["items"]["BV0000000001:101"]["status"], "failed")
        self.assertEqual(state["current_run"]["state"], "stopped")
        self.assertNotIn("BV0000000002:102", state["items"])

    def test_network_errors_do_not_persist_signed_urls(self):
        import requests
        plan = self.plan()
        FakeCollector.responses = [requests.exceptions.InvalidURL('https://example.test/?token=PRIVATE')]
        self.assertEqual(collect_season.run(plan, "none", None), 1)
        contents = self.state_path.read_text(encoding="utf-8")
        self.assertNotIn('PRIVATE', contents)
        self.assertIn('InvalidURL', contents)

    def test_cid_mismatch_is_not_success_and_stops_before_next_entry(self):
        plan = self.plan()
        FakeCollector.responses = [self.manifest(plan["entries"][0], cid=999)]
        result = collect_season.run(plan, "none", None)
        self.assertEqual(result, 1)
        self.assertEqual(len(FakeCollector.calls), 1)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        item = state["items"]["BV0000000001:101"]
        self.assertEqual(item["status"], "failed")
        self.assertIn("CID", item["reason"])
        self.assertEqual(state["summary"]["successful"], 0)


if __name__ == "__main__":
    unittest.main()
