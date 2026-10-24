"""Focused safety tests for S22 frame-seat name imports."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import batch_s22 as batch
import s22_frame_seats as frames


NAMES = ["二妖", "谢朵儿", "狼行", "华仔仔", "李晋晔", "KS", "JY", "牛肉干", "董鲸鱼", "章亿阳", "宝玉妹妹", "陈俊洁"]


def dossier(roster: list[str] | None = None) -> dict:
    return {
        "slug": "bili-BVtest-p01-g03", "season": "S22", "date": "2026-05-26",
        "phase": "showmatch", "episode": None, "day_in_episode": 1, "game_number": 3,
        "board": "wolf_king_knight", "winner": None,
        "roster": roster or ["二妖", "谢朵儿", "狼行", "赵鑫华", "李晋晔", "KS", "JY", "牛肉干", "董鲸鱼", "章亿阳", "宝玉妹妹", "陈俊洁"],
        "commentators": [], "referee": None,
        "seats": [{"seat": n, "name": None, "role": "预言家" if n == 1 else None,
                   "faction": "good" if n == 1 else None, "learning_target": None, "learned_role": None}
                  for n in range(1, 13)],
        "rounds": [{"number": 1, "night": [{"slot": "seer_check", "action": "unknown", "actor": 1,
                                               "targets": [], "result": None, "effects": [], "votes": []}],
                    "day": []}],
        "files": [],
    }


def annotation(names: list[str] | None = None) -> dict:
    names = names or NAMES
    seats = []
    for number, name in enumerate(names, 1):
        visible = "鲸鱼" if number == 9 and name == "董鲸鱼" else name
        seats.append({"seat": number, "visible_label": visible, "name": name})
    return {"season": "S22", "bvid": "BVtest", "scope": "seat_name_only",
            "source": {"kind": "video_frame", "frame_path": "data/extractions/S22/video_checks/test.png",
                       "frame_time_ms": 12345}, "seats": seats}


class S22FrameSeatTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data/weibo/2026-05-26_2026-10-20/参赛名单").mkdir(parents=True)
        photo = self.root / "data/weibo/2026-05-26_2026-10-20/参赛名单/人名去重_照片映射.csv"
        photo.write_text(
            "赛季,纳入参赛名单,原图名字,复核行名字,去重后姓名\n"
            "S22,是,鲸鱼,董鲸鱼,董鲸鱼\n"
            "S22,是,华仔仔,华仔仔,华仔仔\n", encoding="utf-8-sig")
        total = self.root / "data/weibo/2026-05-26_2026-10-20/参赛名单/京城大师赛_S22至今_参赛人名总表.csv"
        total.write_text(
            "参与赛季,姓名,原图名字\nS22、S23,董鲸鱼,鲸鱼\nS22、S23,华仔仔,华仔仔\n", encoding="utf-8-sig")

    def tearDown(self):
        self.temporary.cleanup()

    def test_verified_aliases_and_complete_frames_align_roster_without_merging_names(self):
        original = dossier()
        original["seats"][1]["name"] = "谢朵儿"
        original["seats"][8]["name"] = "董鲸鱼"
        original["rounds"][0]["night"][0]["targets"] = [2]
        value, record = frames.merge_frame_names(original, annotation(), "BVtest",
                                                  self.root / "annotation.json", root=self.root)

        self.assertEqual([seat["name"] for seat in value["seats"]], NAMES)
        self.assertEqual(value["roster"], NAMES)
        self.assertEqual(record["previous_roster"], original["roster"])
        self.assertEqual(record["roster_differences"], {"schedule_only": ["赵鑫华"], "frame_only": ["华仔仔"]})
        self.assertEqual(record["questions"], [])
        whale = record["seats"][8]
        self.assertEqual((whale["visible_label"], whale["name"], whale["status"]), ("鲸鱼", "董鲸鱼", "already_present"))
        self.assertTrue(any(item["row"].get("原图名字") == "鲸鱼" for item in whale["mapping_evidence"]))
        self.assertEqual(value["seats"][0]["role"], original["seats"][0]["role"])
        self.assertEqual(value["rounds"], original["rounds"])

    def test_existing_different_name_is_preserved_with_both_candidates(self):
        original = dossier()
        original["seats"][0]["name"] = "二叔"
        proposed = annotation()
        proposed["seats"][0]["visible_label"] = "二妖"
        proposed["seats"][0]["name"] = "二妖"
        value, record = frames.merge_frame_names(original, proposed, "BVtest",
                                                  self.root / "annotation.json", root=self.root)

        self.assertEqual(value["seats"][0]["name"], "二叔")
        self.assertEqual(len(record["questions"]), 1)
        candidate = record["questions"][0]["candidate"]
        self.assertEqual((candidate["existing_name"], candidate["proposed_name"]), ("二叔", "二妖"))
        self.assertEqual(value["rounds"], original["rounds"])

    def test_user_confirmed_name_can_replace_current_name(self):
        original = dossier()
        original["seats"][0]["name"] = "二叔"
        proposed = annotation()
        proposed["seats"][0].update(visible_label="二妖", name="二妖", resolution="user_confirmed")
        value, record = frames.merge_frame_names(original, proposed, "BVtest",
                                                  self.root / "annotation.json", root=self.root)

        self.assertEqual(value["seats"][0]["name"], "二妖")
        self.assertTrue(any(change["field"] == "seats[1].name" and change["basis"] == "user_confirmed"
                            for change in record["changes"]))

    def test_unlisted_unmapped_nickname_is_not_paired_by_remaining_seat(self):
        proposed = annotation()
        proposed["seats"][0].update(visible_label="鲍鱼", name="鲍鱼")
        value, record = frames.merge_frame_names(dossier(), proposed, "BVtest",
                                                  self.root / "annotation.json", root=self.root)

        self.assertIsNone(value["seats"][0]["name"])
        self.assertEqual(record["questions"][0]["candidate"]["visible_label"], "鲍鱼")
        self.assertIn("未按剩余名额推配", record["questions"][0]["reason"])

    def test_null_ocr_name_is_not_reconstructed_from_visible_label(self):
        proposed = annotation()
        proposed["seats"][0]["name"] = None
        proposed["seats"][0]["visible_label"] = "二妖"
        original = dossier()
        original["seats"][0]["name"] = "二叔"

        value, record = frames.merge_frame_names(original, proposed, "BVtest",
                                                  self.root / "annotation.json", root=self.root)

        self.assertEqual(value["seats"][0]["name"], "二叔")
        self.assertEqual(record["seats"][0]["status"], "needs_review")
        self.assertIn("没有明确规范姓名", record["questions"][0]["reason"])

    def test_low_confidence_ocr_name_does_not_replace_existing_name(self):
        proposed = annotation()
        proposed["seats"][0].update(name="二妖", visible_label="二妖", confidence=0.2)
        original = dossier()
        original["seats"][0]["name"] = "二叔"

        value, record = frames.merge_frame_names(original, proposed, "BVtest",
                                                  self.root / "annotation.json", root=self.root)

        self.assertEqual(value["seats"][0]["name"], "二叔")
        self.assertEqual(record["seats"][0]["status"], "needs_review")
        self.assertIn("置信度低", record["questions"][0]["reason"])

    def test_same_day_annotation_requires_trusted_basis_and_preserves_row_sources(self):
        proposed = annotation()
        proposed["source"] = {"kind": "same_day_frame", "date": "2026-05-26", "source_date": "2026-05-26",
                               "source_bvid": "BVsource", "source_bvids": ["BVsource"],
                               "frame_path": "data/extractions/S22/frame_seats/BVsource/frame.png",
                               "frame_time_ms": 1000, "user_rule": "同日座位不变",
                               "same_day_rule": "同日座位不变"}
        proposed["seats"][0].update(name="二妖", visible_label="二妖", resolution="same_day_propagated",
                                    same_day_trust_basis=["canonical_name"], source_bvid="BVsource",
                                    frame_path="data/extractions/S22/frame_seats/BVsource/frame.png",
                                    frame_time_ms=1000,
                                    same_day_sources=[{"source_bvid": "BVsource", "frame_path": "data/extractions/S22/frame_seats/BVsource/frame.png",
                                                       "frame_time_ms": 1000}])
        value, record = frames.merge_frame_names(dossier(), proposed, "BVtest",
                                                  self.root / "annotation.json", root=self.root)

        self.assertEqual(value["seats"][0]["name"], "二妖")
        self.assertEqual(record["seats"][0]["status"], "added")
        self.assertEqual(record["seats"][0]["source"]["source_bvid"], "BVsource")
        self.assertEqual(record["seats"][0]["source"]["source_date"], "2026-05-26")
        self.assertEqual(record["seats"][0]["source"]["user_rule"], "同日座位不变")
        self.assertEqual(record["seats"][0]["source"]["same_day_sources"][0]["source_bvid"], "BVsource")
        self.assertEqual(record["source"]["source_bvids"], ["BVsource"])

    def test_same_day_questions_and_representative_source_are_preserved_in_review(self):
        proposed = annotation()
        proposed["source"] = {"kind": "same_day_frame", "date": "2026-05-26", "source_date": "2026-05-26",
                               "source_bvid": "BVsource", "source_bvids": ["BVsource"],
                               "frame_path": "data/extractions/S22/frame_seats/BVsource/frame.png",
                               "frame_time_ms": 1000, "user_rule": "同日座位不变"}
        proposed["seats"][0].update(name=None, visible_label=None, resolution=None,
                                    source_bvid="BVsource", frame_path=None, frame_time_ms=None)
        proposed["questions"] = [{"id": "daily-question", "field": "seats[1].name", "label": "1号姓名",
                                  "reason": "同日来源冲突", "candidates": [{"name": "甲", "sources": []}] }]

        _value, record = frames.merge_frame_names(dossier(), proposed, "BVtest",
                                                   self.root / "annotation.json", root=self.root)

        self.assertEqual(record["source"]["frame_path"], "data/extractions/S22/frame_seats/BVsource/frame.png")
        self.assertEqual(record["source"]["frame_time_ms"], 1000)
        self.assertEqual(record["seats"][0]["source"]["frame_path"], "data/extractions/S22/frame_seats/BVsource/frame.png")
        self.assertEqual(record["seats"][0]["source"]["source_bvid"], "BVsource")
        self.assertEqual([question["id"] for question in record["questions"] if question.get("field") == "seats[1].name"],
                         ["daily-question"])
        self.assertEqual(record["seats"][0]["status"], "needs_review")

    def test_same_day_annotation_with_null_name_stays_unresolved(self):
        proposed = annotation()
        proposed["source"] = {"kind": "same_day_frame", "date": "2026-05-26"}
        proposed["seats"][0].update(name=None, visible_label="二妖", resolution="same_day_propagated",
                                    same_day_trust_basis=["canonical_name"])
        value, record = frames.merge_frame_names(dossier(), proposed, "BVtest",
                                                  self.root / "annotation.json", root=self.root)
        self.assertIsNone(value["seats"][0]["name"])
        self.assertEqual(record["seats"][0]["status"], "needs_review")

    def test_successful_apply_writes_separate_frame_review_and_keeps_game_unreviewed(self):
        bvid = "BVtest"
        annotation_dir = self.root / "data/extractions/S22/frame_seats"
        game_dir = self.root / "data/games/S22/game"
        report_dir = self.root / "data/reports"
        annotation_dir.mkdir(parents=True)
        game_dir.mkdir(parents=True)
        report_dir.mkdir(parents=True)
        (annotation_dir / f"{bvid}.json").write_text(json.dumps(annotation(), ensure_ascii=False), encoding="utf-8")
        (game_dir / "dossier.json").write_text(json.dumps(dossier(), ensure_ascii=False), encoding="utf-8")
        (game_dir / "复核记录.json").write_text(json.dumps({"state": "imported", "issues": [],
            "text_review": {"questions": [{"id": "transcript-question"}]}}, ensure_ascii=False), encoding="utf-8")
        main_progress = report_dir / "main.json"
        main_progress.write_text(json.dumps({"season": "S22", "items": {bvid: {"bvid": bvid,
            "index": 3, "state": "imported", "output_dir": "data/games/S22/game"}}}, ensure_ascii=False), encoding="utf-8")
        progress_path = report_dir / "frame.json"
        receipt = {"game_id": "game-id", "slug": "bili-BVtest-p01-g03", "seats": 12}

        with patch.object(frames, "ROOT", self.root), patch.object(frames, "ANNOTATION_DIR", annotation_dir), \
             patch.object(frames, "PROGRESS_FILE", progress_path), patch.object(batch, "ROOT", self.root), \
             patch.object(batch, "STATE_FILE", main_progress), patch.object(batch, "JOURNAL_FILE", report_dir / "main.jsonl"), \
             patch.object(batch, "batch_lock", return_value=nullcontext()), patch.object(batch, "backup_database"), \
             patch("game_records.validate"), patch("game_records.import_game", return_value=receipt), \
             patch("batch_review.render_game"):
            result = frames.apply(bvid)

        updated = json.loads((game_dir / "dossier.json").read_text(encoding="utf-8"))
        review = json.loads((game_dir / "复核记录.json").read_text(encoding="utf-8"))
        updated_state = json.loads(main_progress.read_text(encoding="utf-8"))
        self.assertEqual(result["results"][0]["status"], "imported")
        self.assertEqual(updated["roster"], NAMES)
        self.assertEqual(review["frame_seats"]["source"]["kind"], "video_frame")
        self.assertEqual(review["frame_seats"]["previous_roster"][3], "赵鑫华")
        self.assertEqual(review["frame_seats"]["roster_differences"]["frame_only"], ["华仔仔"])
        self.assertIn("text_review", review)
        self.assertEqual(updated_state["items"][bvid]["state"], "imported")
        self.assertNotEqual(updated_state["items"][bvid]["state"], "reviewed")

    def test_first_frame_import_backup_is_recorded_in_frame_progress_only(self):
        report_dir = self.root / "data/reports"
        report_dir.mkdir(parents=True)
        progress_path = report_dir / "frame.json"
        main_path = report_dir / "main.json"
        main_path.write_text('{"keep":"main progress"}', encoding="utf-8")
        backup = self.root / "data/backups/frame.dump"
        backup.parent.mkdir(parents=True)
        progress = {"season": "S22", "items": {}}
        calls = []

        def fake_backup(value):
            calls.append(1)
            backup.write_bytes(b"dump")
            value["backup"] = "data/backups/frame.dump"
            batch.checkpoint(value, {"stage": "database_backup"})

        with patch.object(frames, "ROOT", self.root), patch.object(frames, "PROGRESS_FILE", progress_path), \
             patch.object(batch, "ROOT", self.root), patch.object(batch, "STATE_FILE", main_path), \
             patch.object(batch, "backup_database", side_effect=fake_backup):
            frames._backup_frame_database(progress, self.root)
            frames._backup_frame_database(progress, self.root)

        saved = json.loads(progress_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["backup"], "data/backups/frame.dump")
        self.assertEqual(calls, [1])
        self.assertEqual(main_path.read_text(encoding="utf-8"), '{"keep":"main progress"}')

    def test_apply_rolls_back_dossier_if_database_import_fails(self):
        bvid = "BVtest"
        annotation_dir = self.root / "data/extractions/S22/frame_seats"
        game_dir = self.root / "data/games/S22/game"
        report_dir = self.root / "data/reports"
        annotation_dir.mkdir(parents=True)
        game_dir.mkdir(parents=True)
        report_dir.mkdir(parents=True)
        (annotation_dir / f"{bvid}.json").write_text(json.dumps(annotation(), ensure_ascii=False), encoding="utf-8")
        original = dossier()
        dossier_path = game_dir / "dossier.json"
        dossier_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        main_progress = report_dir / "main.json"
        main_progress.write_text(json.dumps({"season": "S22", "items": {bvid: {"bvid": bvid,
            "index": 3, "state": "imported", "output_dir": "data/games/S22/game"}}}, ensure_ascii=False), encoding="utf-8")
        progress_path = report_dir / "frame.json"

        patches = [
            patch.object(frames, "ROOT", self.root), patch.object(frames, "ANNOTATION_DIR", annotation_dir),
            patch.object(frames, "PROGRESS_FILE", progress_path), patch.object(batch, "ROOT", self.root),
            patch.object(batch, "STATE_FILE", main_progress), patch.object(batch, "JOURNAL_FILE", report_dir / "main.jsonl"),
            patch.object(batch, "batch_lock", return_value=nullcontext()), patch.object(batch, "backup_database"),
            patch("game_records.validate"), patch("game_records.import_game", side_effect=RuntimeError("rollback")),
            patch("batch_review.render_game"),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = frames.apply(bvid)

        self.assertEqual(result["results"][0]["status"], "failed")
        self.assertEqual(json.loads(dossier_path.read_text(encoding="utf-8")), original)
        self.assertEqual(json.loads(progress_path.read_text(encoding="utf-8"))["items"][bvid]["status"], "failed")
        self.assertFalse((game_dir / "database_receipt.json").exists())

    def test_same_annotation_hash_skips_a_second_database_import(self):
        bvid = "BVtest"
        annotation_dir = self.root / "data/extractions/S22/frame_seats"
        game_dir = self.root / "data/games/S22/game"
        report_dir = self.root / "data/reports"
        annotation_dir.mkdir(parents=True)
        game_dir.mkdir(parents=True)
        report_dir.mkdir(parents=True)
        annotation_path = annotation_dir / f"{bvid}.json"
        value = annotation()
        annotation_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        dossier_path = game_dir / "dossier.json"
        dossier_path.write_text(json.dumps(dossier(), ensure_ascii=False), encoding="utf-8")
        main_progress = report_dir / "main.json"
        main_progress.write_text(json.dumps({"season": "S22", "items": {bvid: {"bvid": bvid,
            "index": 3, "state": "imported", "output_dir": "data/games/S22/game"}}}, ensure_ascii=False), encoding="utf-8")
        progress_path = report_dir / "frame.json"
        progress_path.write_text(json.dumps({"season": "S22", "items": {bvid: {
            "annotation_sha256": frames.annotation_digest(value), "importer_version": frames.FRAME_REVIEW_VERSION,
            "status": "imported"}}}, ensure_ascii=False), encoding="utf-8")

        with patch.object(frames, "ROOT", self.root), patch.object(frames, "ANNOTATION_DIR", annotation_dir), \
             patch.object(frames, "PROGRESS_FILE", progress_path), patch.object(batch, "ROOT", self.root), \
             patch.object(batch, "STATE_FILE", main_progress), patch.object(batch, "JOURNAL_FILE", report_dir / "main.jsonl"), \
             patch.object(batch, "batch_lock", return_value=nullcontext()), patch("game_records.import_game") as importer:
            result = frames.apply(bvid)

        self.assertEqual(result["results"][0]["status"], "skipped_same_annotation")
        importer.assert_not_called()

    def test_entire_queue_is_saved_before_first_import_for_resume(self):
        annotation_dir = self.root / "annotations"
        annotation_dir.mkdir()
        progress_path = self.root / "frame-progress.json"
        state = {"items": {"BVone": {"index": 1}, "BVtwo": {"index": 2}}}
        for bvid in state["items"]:
            value = annotation()
            value["bvid"] = bvid
            (annotation_dir / f"{bvid}.json").write_text(json.dumps(value), encoding="utf-8")

        def interrupt_before_import(*args, **kwargs):
            saved = json.loads(progress_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["summary"]["pending"], 2)
            self.assertEqual(saved["next_frame_bvid"], "BVone")
            raise KeyboardInterrupt

        with patch.object(frames, "PROGRESS_FILE", progress_path), \
             patch.object(batch, "load_state", return_value=state), \
             patch.object(batch, "batch_lock", return_value=nullcontext()), \
             patch.object(frames, "_apply_one", side_effect=interrupt_before_import):
            with self.assertRaises(KeyboardInterrupt):
                frames.apply(annotation_dir=annotation_dir)


if __name__ == "__main__":
    unittest.main()
