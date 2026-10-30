"""Resume boundaries, original transcript selection, and lossy-parse guards."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import batch_s22 as batch


class BatchS22Tests(unittest.TestCase):
    def test_batch_runtime_files_share_the_season_report_directory(self):
        self.assertEqual(batch.REPORT_DIR, ROOT / "data/reports/S22")
        self.assertEqual(batch.STATE_FILE.name, "S22_对局批处理进度.json")
        self.assertEqual(batch.JOURNAL_FILE.name, "S22_对局批处理日志.jsonl")
        self.assertEqual(batch.LOCK_FILE.name, "S22_对局批处理.lock")

    def test_derived_survival_and_existing_votes_share_one_import_transaction(self):
        with patch("database.connect") as connect, patch("game_records.import_game", return_value={"slug": "g"}) as game_import, \
                patch("voting_records.import_voting", return_value={"ballots": 1}) as vote_import:
            conn = connect.return_value.__enter__.return_value
            result = batch.import_prepared_records({"slug": "g"}, {"ballots": [1]}, {"version": 1})
            self.assertEqual(result["voting"], {"ballots": 1})
            self.assertIs(game_import.call_args.kwargs["conn"], conn)
            self.assertIs(vote_import.call_args.kwargs["conn"], conn)
            vote_import.side_effect = RuntimeError("vote import failed")
            with self.assertRaisesRegex(RuntimeError, "vote import failed"):
                batch.import_prepared_records({"slug": "g"}, {"ballots": [1]}, {"version": 1})
            self.assertIs(connect.return_value.__exit__.call_args.args[0], RuntimeError)

    def test_missing_vote_file_does_not_create_or_replace_vote_records(self):
        with patch("database.connect"), patch("game_records.import_game", return_value={"slug": "g"}), \
                patch("voting_records.import_voting") as vote_import:
            batch.import_prepared_records({"slug": "g"}, None, {"version": 1})
            vote_import.assert_not_called()

    def test_complete_asr_takes_priority_over_truncated_subtitle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("full.json", "partial.json"):
                (root / name).write_text("{}", encoding="utf-8")
            path, origin = batch.choose_transcript({"字幕原件": "partial.json"},
                {"本地全文JSON": "full.json", "中文字幕原件": "partial.json"}, root=root)
            self.assertEqual(path.name, "full.json")
            self.assertEqual(origin, "本地全文转写")

    def test_normalization_keeps_millisecond_asr_and_seconds_subtitles_aligned(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.json"
            expected = [{"start_ms": 1200, "end_ms": 2600, "text": "原文"}]
            path.write_text(json.dumps({"segments": expected}), encoding="utf-8")
            self.assertEqual(batch.load_segments(path), expected)
            path.write_text(json.dumps({"body": [{"from": 1.2, "to": 2.6, "content": "原文"}]}), encoding="utf-8")
            self.assertEqual(batch.load_segments(path), expected)

    def test_derivation_reads_only_existing_sidecars_and_never_creates_voting(self):
        from unittest.mock import patch
        import game_derivations
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            dossier = {"slug": "fixture"}
            with patch.object(game_derivations, "derive_game", return_value={
                    "dossier": {"slug": "fixture", "derived": True},
                    "voting": None, "derivations": {"version": 1}}) as derive:
                result = batch.derive_formal_records(dossier, folder)
            derive.assert_called_once_with(dossier, None, supplemental=None, endgame=None, speech_evidence=None)
            self.assertEqual(result, ({"slug": "fixture", "derived": True}, None, {"version": 1}))
            self.assertEqual(list(folder.iterdir()), [])

            voting = {"schema_version": 1, "ballots": [], "days": []}
            batch.atomic_json(folder / "voting.json", voting)
            with patch.object(game_derivations, "derive_game", return_value={
                    "dossier": dossier, "voting": voting, "derivations": {"version": 1}}) as derive:
                batch.derive_formal_records(dossier, folder)
            derive.assert_called_once_with(dossier, voting, supplemental=None, endgame=None, speech_evidence=None)

    def test_atomic_checkpoint_failure_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "progress.json"
            batch.atomic_json(path, {"last": "committed"})
            with patch.object(batch.os, "replace", side_effect=OSError("simulated interruption")):
                with self.assertRaises(OSError):
                    batch.atomic_json(path, {"last": "uncommitted"})
            self.assertEqual(batch.read_json(path), {"last": "committed"})
            self.assertEqual(list(Path(temporary).glob("*.tmp")), [])

    def test_existing_manual_file_is_protected_and_machine_file_can_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out = root / "game"
            out.mkdir()
            dossier = out / "dossier.json"
            dossier.write_text('{"manually_corrected":true}', encoding="utf-8")
            entry = {"output_dir": "game"}
            with patch.object(batch, "ROOT", root):
                self.assertTrue(batch.protect_existing(entry, {}))
                ownership = {"generated_dossier_sha256": batch.digest(dossier)}
                self.assertFalse(batch.protect_existing(entry, ownership))
                dossier.write_text('{"new_manual_correction":true}', encoding="utf-8")
                self.assertTrue(batch.protect_existing(entry, ownership))

    def test_atomic_checkpoint_retries_a_temporary_windows_reader_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "progress.json"
            batch.atomic_json(path, {"state": "before"})
            real_replace = batch.os.replace
            calls = []
            def transient_lock(source, destination):
                calls.append(1)
                if len(calls) == 1:
                    raise PermissionError("temporary reader")
                return real_replace(source, destination)
            with patch.object(batch.os, "replace", side_effect=transient_lock), patch.object(batch.time, "sleep"):
                batch.atomic_json(path, {"state": "committed"})
            self.assertEqual(len(calls), 2)
            self.assertEqual(batch.read_json(path), {"state": "committed"})

    def test_catalog_metadata_changes_invalidate_resume_signature(self):
        entry = batch.entries_from_catalog()[0]
        old_signature = batch.input_digest(entry)
        changed = {**entry, "date": "2026-05-25"}
        self.assertNotEqual(old_signature, batch.input_digest(changed))

    def test_refresh_catalog_keeps_commit_but_refreshes_input_path(self):
        state = {"items": {"BVexample": {"state": "imported", "source_path": "old.json", "db_receipt": {"game_id": "x"}}}}
        with patch.object(batch, "entries_from_catalog", return_value=[{"bvid": "BVexample", "source_path": "new.json"}]):
            batch.initialize(state)
        self.assertEqual(state["items"]["BVexample"]["state"], "imported")
        self.assertEqual(state["items"]["BVexample"]["db_receipt"]["game_id"], "x")
        self.assertEqual(state["items"]["BVexample"]["source_path"], "new.json")

    def entry(self):
        return {"board": "mixed_blood", "bvid": "BVsynthetic", "cid": 1, "page": 1,
                "title": "20260526 表演赛 Day-1 第一局-预女猎白混", "date": "2026-05-26",
                "phase": "showmatch", "episode": None, "game_number": 1,
                "source_path": None, "transcript_origin": "", "audio_path": "not-present.m4a"}

    def test_unknown_roles_do_not_become_the_remaining_villagers(self):
        value, _, _ = batch.build_dossier(self.entry(), {"seats": [{"seat": 1, "role": "预言家"}], "rounds": []})
        self.assertEqual(len(value["seats"]), 12)
        self.assertEqual(value["seats"][0]["role"], "预言家")
        self.assertTrue(all(s["role"] is None for s in value["seats"][1:]))
        self.assertEqual(value["rounds"], [])

    def test_treasure_master_is_wolf_aligned_when_batch_building_dossier(self):
        entry = {**self.entry(), "board": "treasure_master"}
        value, _, _ = batch.build_dossier(entry, {
            "seats": [{"seat": 12, "role": "盗宝大师"}], "rounds": []})
        self.assertEqual(batch.faction_for("盗宝大师"), "werewolf")
        self.assertEqual(value["seats"][11]["faction"], "werewolf")

    def test_two_shots_in_one_slot_are_preserved_for_review_not_overwritten(self):
        extracted = {"seats": [{"seat": 1, "role": "猎人"}], "rounds": [{"number": 1, "night": [], "day": [
            {"slot": "hunter_shot", "action": "shoot", "actor": 1, "targets": [2], "result": None},
            {"slot": "hunter_shot", "action": "shoot", "actor": 1, "targets": [3], "result": None}]}]}
        value, issues, extra = batch.build_dossier(self.entry(), extracted)
        shot = next(e for e in value["rounds"][0]["day"] if e["slot"] == "hunter_shot")
        self.assertEqual(shot["action"], "unknown")
        self.assertEqual(len(extra), 2)
        self.assertTrue(any("多次或冲突" in s for s in issues))

    def test_explicit_mixed_blood_model_reaches_its_fixed_night_slot(self):
        text = "本局游戏预言家10号女巫2号猎人12号白神3号狼人1号4号7号9号平民6号8号11号混血儿5号榜样是7号狼人。首夜狼人击杀2号女巫，女巫毒杀1号狼人。"
        extracted = batch.extract_game_recap([{"start_ms": 0, "end_ms": 10000, "text": text}], "预女猎白混")
        value, _, _ = batch.build_dossier(self.entry(), extracted)
        model = next(e for e in value["rounds"][0]["night"] if e["slot"] == "mixed_blood_model")
        self.assertEqual((model["action"], model["actor"], model["targets"]), ("choose", 5, [7]))
        self.assertEqual(len(value["rounds"]), 1)
        from game_records import validate
        validate(value, check_files=False, allow_incomplete=True)

    def test_catalog_regular_episode_labels_keep_the_regular_phase(self):
        entries = batch.entries_from_catalog(include_excluded=True)
        regular = [e for e in entries if e["episode"] is not None]
        self.assertEqual(len(entries), 163)
        self.assertTrue(regular)
        self.assertTrue(all(e["phase"] == "regular" for e in regular))

    def test_special_supplement_requires_exact_source_and_never_creates_rounds(self):
        segments = [{"start_ms": 0, "end_ms": 1000, "text": "首夜混血儿5号选择7号为榜样。"}]
        entry = {"bvid": "BVtest", "output_dir": "game"}
        event = {"number": 1, "phase": "night", "slot": "mixed_blood_model", "action": "choose",
                 "actor": 5, "targets": [7], "result": None}
        source_hash = batch.hashlib.sha256((batch.recap_text_for(segments) + "\n").replace("\n", batch.os.linesep).encode()).hexdigest()
        annotation = {"items": {"BVtest": {"recap_sha256": source_hash,
                      "source_path": "game/复盘原文.txt", "events": [event], "issues": []}}}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "supplement.json"
            batch.atomic_json(path, annotation)
            with patch.object(batch, "SUPPLEMENT_FILE", path):
                result = batch.apply_recap_supplement(entry, segments, {"rounds": [{"number": 1, "night": [], "day": []}]})
                self.assertEqual(result["rounds"][0]["night"][0]["targets"], [7])
                missing = batch.apply_recap_supplement(entry, segments, {"rounds": []})
                self.assertEqual(missing["rounds"], [])
                changed = [{**segments[0], "text": "转写已修改"}]
                stale = batch.apply_recap_supplement(entry, changed, {"rounds": [{"number": 1, "night": [], "day": []}]})
                self.assertEqual(stale["rounds"][0]["night"], [])
                self.assertTrue(any("原文不一致" in issue for issue in stale["issues"]))

    def test_ghost_bride_explicit_third_party_keeps_original_cards(self):
        entry = {**self.entry(), "board": "ghost_bride"}
        value, _, _ = batch.build_dossier(entry, {"seats": [
            {"seat": 9, "role": "狼人", "faction": "third_party"},
            {"seat": 5, "role": "平民", "faction": "third_party"},
            {"seat": 10, "role": "鬼魂新娘", "faction": "third_party"}], "rounds": []})
        self.assertEqual((value["seats"][8]["role"], value["seats"][8]["faction"]), ("狼人", "third_party"))
        self.assertEqual((value["seats"][4]["role"], value["seats"][4]["faction"]), ("平民", "third_party"))
        from game_records import validate
        validate(value, check_files=False, allow_incomplete=True)

    def test_invalid_role_capacity_is_flagged_instead_of_choosing_a_seat(self):
        extracted = {"seats": [{"seat": 1, "role": "预言家"}, {"seat": 2, "role": "预言家"}], "rounds": []}
        value, issues, _ = batch.build_dossier(self.entry(), extracted)
        self.assertIsNone(value["seats"][0]["role"])
        self.assertIsNone(value["seats"][1]["role"])
        self.assertTrue(any("超过配置" in s for s in issues))

    def test_liveness_does_not_use_windows_kill_zero(self):
        # A real OS file lock is released on close; a stale filename is harmless.
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "batch.lock"
            with batch.batch_lock(path):
                self.assertTrue(path.exists())
            with batch.batch_lock(path):
                self.assertTrue(path.exists())

    def test_summary_distinguishes_imported_from_reviewed_and_pending(self):
        state = {"items": {"a": {"bvid": "a", "state": "imported"},
                            "b": {"bvid": "b", "state": "reviewed"},
                            "c": {"bvid": "c", "state": "failed"}}}
        report = batch.summary(state)
        self.assertEqual((report["imported"], report["reviewed"], report["needs_review"], report["pending"]), (2, 1, 1, 1))
        self.assertEqual(report["next_bvid"], "c")


if __name__ == "__main__":
    unittest.main()
