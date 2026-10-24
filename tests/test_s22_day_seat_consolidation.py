"""Focused tests for date-scoped S22 seat evidence consolidation."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import consolidate_s22_day_seats as consolidate


def state(entries: list[tuple[str, str, int, str]]) -> dict:
    return {"season": "S22", "items": {
        bvid: {"bvid": bvid, "date": date, "game_number": number, "index": number,
               "state": entry_state, "output_dir": f"data/games/S22/{date}_g{number:02d}_{bvid}"}
        for bvid, date, number, entry_state in entries
    }}


def ocr_annotation(bvid: str, rows: dict[int, tuple[str, str, float | None]]) -> dict:
    seats = []
    for seat in range(1, 13):
        name, visible, confidence = rows.get(seat, (None, None, None))
        row = {"seat": seat, "name": name, "visible_label": visible,
               "frame_path": f"data/extractions/S22/frame_seats/{bvid}/{bvid}.png",
               "frame_time_ms": 12000 + seat}
        if confidence is not None:
            row["confidence"] = confidence
        row["match"] = {"kind": "canonical_name"} if name else None
        seats.append(row)
    return {"season": "S22", "bvid": bvid, "scope": "seat_name_only",
            "source": {"kind": "video_frame", "frame_path": f"data/extractions/S22/frame_seats/{bvid}/{bvid}.png",
                       "frame_time_ms": 12000}, "seats": seats}


class S22DaySeatConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "frame_seats"
        self.manual = self.root / "manual_day_seats"
        self.source.mkdir()
        self.manual.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def save_source(self, value: dict) -> None:
        (self.source / f"{value['bvid']}.json").write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_multiple_games_same_day_expand_only_within_day_and_keep_sources(self):
        first, second, next_day = "BVsource1", "BVsource2", "BVnextday"
        self.save_source(ocr_annotation(first, {2: ("谢朵儿", "谢朵儿", 0.97)}))
        self.save_source(ocr_annotation(second, {3: ("狼行", "狼行", 0.99)}))
        self.save_source(ocr_annotation(next_day, {2: ("隔日姓名", "隔日姓名", 0.99)}))
        manual = {"date": "2026-05-26", "seats": [{
            "seat": 4, "visible_label": "华仔仔", "name": "华仔仔", "source_bvid": first,
            "frame_path": "data/manual/2026-05-26.png", "frame_time_ms": 2000,
            "reading_method": "assistant_visual",
        }]}
        (self.manual / "2026-05-26.json").write_text(json.dumps(manual, ensure_ascii=False), encoding="utf-8")

        result = consolidate.build_plan(
            state([(first, "2026-05-26", 1, "imported"),
                   (second, "2026-05-26", 2, "imported"),
                   (next_day, "2026-05-27", 1, "imported")]),
            source_dir=self.source, manual_dir=self.manual, root=self.root,
            protected_bvids=set())

        same_day = result["daily"]["2026-05-26"]
        self.assertEqual(same_day["seats"][1]["name"], "谢朵儿")
        self.assertEqual(same_day["seats"][1]["source_bvid"], first)
        self.assertEqual(same_day["seats"][2]["name"], "狼行")
        self.assertEqual(same_day["seats"][2]["source_bvid"], second)
        self.assertEqual(same_day["seats"][3]["name"], "华仔仔")
        self.assertEqual(same_day["seats"][3]["sources"][0]["trust_basis"], "assistant_visual")
        self.assertEqual(result["daily"]["2026-05-27"]["seats"][1]["name"], "隔日姓名")

        expanded_first = result["expanded"][first]
        expanded_second = result["expanded"][second]
        self.assertEqual(expanded_first["source"]["kind"], "same_day_frame")
        self.assertEqual(expanded_first["source"]["source_date"], "2026-05-26")
        self.assertEqual(expanded_first["seats"][1]["name"], "谢朵儿")
        self.assertEqual(expanded_first["seats"][1]["source_bvid"], first)
        self.assertEqual(expanded_first["seats"][2]["source_bvid"], second)
        self.assertEqual(expanded_second["seats"][1]["name"], "谢朵儿")
        self.assertNotIn("隔日姓名", {row["name"] for row in expanded_first["seats"] if row["name"]})
        self.assertEqual(result["expanded"][next_day]["seats"][1]["name"], "隔日姓名")
        self.assertEqual(expanded_first["status"], "pending")

    def test_conflicting_trusted_names_remain_candidates_and_do_not_propagate(self):
        first, second, target = "BVconflict1", "BVconflict2", "BVtarget"
        self.save_source(ocr_annotation(first, {1: ("甲", "甲", 0.99)}))
        self.save_source(ocr_annotation(second, {1: ("乙", "乙", 0.99)}))
        result = consolidate.build_plan(
            state([(first, "2026-05-26", 1, "imported"),
                   (second, "2026-05-26", 2, "imported"),
                   (target, "2026-05-26", 3, "imported")]),
            source_dir=self.source, manual_dir=self.manual, root=self.root,
            protected_bvids=set())

        daily_seat = result["daily"]["2026-05-26"]["seats"][0]
        self.assertIsNone(daily_seat["name"])
        self.assertEqual(daily_seat["status"], "conflict")
        self.assertEqual({item["name"] for item in result["daily"]["2026-05-26"]["questions"][0]["candidates"]}, {"甲", "乙"})
        target_row = result["expanded"][target]["seats"][0]
        self.assertIsNone(target_row["name"])
        self.assertEqual(result["expanded"][target]["status"], "pending")

    def test_manual_visual_and_reliable_ocr_conflict_is_not_silently_ranked(self):
        bvid = "BVvisualconflict"
        self.save_source(ocr_annotation(bvid, {5: ("OCR姓名", "OCR姓名", 0.99)}))
        manual = {"date": "2026-05-26", "seats": [{
            "seat": 5, "visible_label": "目视姓名", "name": "目视姓名", "source_bvid": bvid,
            "frame_path": "data/manual/visual.png", "frame_time_ms": 5000,
            "reading_method": "assistant_visual",
        }]}
        (self.manual / "2026-05-26.json").write_text(json.dumps(manual, ensure_ascii=False), encoding="utf-8")
        result = consolidate.build_plan(
            state([(bvid, "2026-05-26", 1, "imported")]),
            source_dir=self.source, manual_dir=self.manual, root=self.root,
            protected_bvids=set())

        seat = result["daily"]["2026-05-26"]["seats"][4]
        self.assertIsNone(seat["name"])
        self.assertEqual(seat["status"], "conflict")
        self.assertEqual({candidate["name"] for candidate in result["daily"]["2026-05-26"]["questions"][0]["candidates"]},
                         {"OCR姓名", "目视姓名"})

    def test_unmatched_and_low_confidence_names_are_not_recovered_from_labels(self):
        bvid = "BVlow"
        value = ocr_annotation(bvid, {1: (None, "不可推配", 0.99), 2: ("低置信", "低置信", 0.4)})
        value["seats"][1]["match"] = {"kind": "canonical_name"}
        self.save_source(value)
        result = consolidate.build_plan(
            state([(bvid, "2026-05-26", 1, "imported")]),
            source_dir=self.source, manual_dir=self.manual, root=self.root,
            protected_bvids=set())

        rows = result["daily"]["2026-05-26"]["seats"]
        self.assertIsNone(rows[0]["name"])
        self.assertIsNone(rows[1]["name"])
        self.assertEqual(rows[0]["untrusted_sources"][0]["trust_basis"], "name_missing")
        self.assertEqual(rows[1]["untrusted_sources"][0]["trust_basis"], "low_confidence")

    def test_protected_sample_is_not_expanded_or_overwritten(self):
        protected = consolidate.PROTECTED_BVID
        self.save_source(ocr_annotation(protected, {1: ("不能覆盖", "不能覆盖", 0.99)}))
        result = consolidate.build_plan(
            state([(protected, "2026-06-25", 3, "preserved")]),
            source_dir=self.source, manual_dir=self.manual, root=self.root)
        self.assertNotIn(protected, result["expanded"])
        self.assertIn(protected, result["protected_bvids"])
        self.assertEqual(result["daily"]["2026-06-25"]["source_bvids"], [])

    def test_july_3_special_has_no_inferred_names_and_retains_all_three_frames(self):
        bvids = ["BVspecial1", "BVspecial2", "BVspecial3"]
        entries = [(bvid, "2026-07-03", n, "imported") for n, bvid in enumerate(bvids, 1)]
        for n, bvid in enumerate(bvids, 1):
            folder = self.source / bvid
            folder.mkdir()
            capture = {"bvid": bvid, "date": "2026-07-03", "game_number": n,
                       "source_kind": "video_frame", "frame_path": f"data/{bvid}.png",
                       "frame_time_ms": n * 1000}
            (folder / "capture.json").write_text(json.dumps(capture), encoding="utf-8")

        result = consolidate.build_plan(state(entries), source_dir=self.source,
                                        manual_dir=self.manual, root=self.root,
                                        protected_bvids=set())
        day = result["daily"]["2026-07-03"]
        self.assertEqual(day["status"], "needs_manual_lineup")
        self.assertEqual(day["coverage_status"], "no_sidebar_labels")
        self.assertEqual({row["name"] for row in day["seats"]}, {None})
        self.assertEqual({source["source_bvid"] for source in day["source_frames"]}, set(bvids))
        self.assertEqual(len(day["questions"]), 12)
        self.assertTrue(all(item["status"] == "needs_manual_lineup" for item in result["expanded"].values()))

    def test_write_plan_uses_only_separate_output_directories(self):
        bvid = "BVwrite"
        self.save_source(ocr_annotation(bvid, {1: ("姓名", "姓名", 0.99)}))
        original_path = self.source / f"{bvid}.json"
        original_bytes = original_path.read_bytes()
        result = consolidate.build_plan(
            state([(bvid, "2026-05-26", 1, "imported")]),
            source_dir=self.source, manual_dir=self.manual, root=self.root,
            protected_bvids=set())
        day_out = self.root / "按日座位表"
        annotation_out = self.root / "day_frame_seats"
        writes = consolidate.write_plan(result, day_output_dir=day_out,
                                        annotation_output_dir=annotation_out,
                                        source_dir=self.source)

        self.assertEqual(writes, {"daily_files": 1, "annotations": 1})
        self.assertEqual(original_path.read_bytes(), original_bytes)
        output = json.loads((annotation_out / f"{bvid}.json").read_text(encoding="utf-8"))
        self.assertEqual(output["source"]["kind"], "same_day_frame")
        self.assertEqual(output["status"], "pending")


if __name__ == "__main__":
    unittest.main()
