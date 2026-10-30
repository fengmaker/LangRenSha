"""User-excluded games cannot re-enter through batch or direct imports."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import json
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import batch_s22 as batch
import game_scope
import game_records
import prune_s22_excluded as prune
from export_s22_offline_review import attach_original_questions, embedded_rule_documents


class GameScopeTests(unittest.TestCase):
    def test_s21_direct_import_scope_excludes_only_its_own_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "config/seasons.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"seasons": {"S21": {"scope": {
                "excluded_phases": ["showmatch", "special"], "excluded_bvids": ["BVexcluded"]}}}}), encoding="utf-8")
            for entry in ({"season": "S21", "phase": "special"},
                          {"season": "S21", "slug": "s21-BVexcluded-p01"}):
                self.assertTrue(game_scope.exclusion_reason(entry, root=root))
            self.assertIsNone(game_scope.exclusion_reason({"season": "S21", "phase": "regular"}, root=root))
            self.assertIsNone(game_scope.exclusion_reason({"season": "S22", "bvid": "BVexcluded"}, root=root))

    def test_phase_date_and_bvid_apply_only_to_s22(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / game_scope.POLICY_REL
            path.parent.mkdir()
            path.write_text(json.dumps({"seasons": {"S22": {"scope": {"excluded_phases": ["showmatch"],
                "excluded_dates": ["2026-07-03"], "excluded_bvids": ["BVexcluded"]}}}}), encoding="utf-8")
            for entry in [{"phase": "showmatch"}, {"date": "2026-07-03"}, {"bvid": "BVexcluded"},
                          {"slug": "bili-BVexcluded-p01-g01"}]:
                self.assertTrue(game_scope.exclusion_reason(entry, root=root))
            self.assertIsNone(game_scope.exclusion_reason({"season": "S23", "phase": "showmatch"}, root=root))
            self.assertIsNone(game_scope.exclusion_reason({"phase": "finals_week", "date": "2026-08-21"}, root=root))

    def test_current_catalog_does_not_restore_removed_games(self):
        full = batch.entries_from_catalog(include_excluded=True)
        active = batch.entries_from_catalog()
        self.assertEqual(len(full), 163)
        self.assertEqual(len(active), 148)
        self.assertEqual(len(full) - len(active), 15)
        self.assertFalse(any(game_scope.exclusion_reason(entry) for entry in active))
        self.assertIn("BV1yt7v6QE3Q", {entry["bvid"] for entry in active})
        all_bvids = {entry["bvid"] for entry in full}
        active_bvids = {entry["bvid"] for entry in active}
        self.assertIn("BV1tj8p6REfY", all_bvids)
        self.assertNotIn("BV1tj8p6REfY", active_bvids)
        self.assertTrue(any(entry["date"] == "2026-08-19" and entry["bvid"] != "BV1tj8p6REfY"
                            for entry in active))
        self.assertIn("BV1cJ7L64EBW", active_bvids)  # Scored June 26, game 4, Guile Realm.

    def test_incremental_prune_does_not_reuse_old_completed_scope(self):
        previous = {"state": "complete", "items": [{"bvid": f"old-{n}"} for n in range(14)]}
        current = {f"old-{n}" for n in range(14)} | {"BV1tj8p6REfY"}
        self.assertFalse(prune.completed_scope_matches(previous, current))
        previous["items"].append({"bvid": "BV1tj8p6REfY"})
        self.assertTrue(prune.completed_scope_matches(previous, current))

    def test_entertainment_board_classification_does_not_depend_on_bvid_or_frequency(self):
        self.assertTrue(game_scope.exclusion_reason({"phase": "finals_week", "board": "ghost_bride", "bvid": "BVnew"}))
        self.assertTrue(game_scope.exclusion_reason({"board_name": "狼王守卫", "bvid": "BVanother"}))
        self.assertIsNone(game_scope.exclusion_reason({"board": "all_in", "phase": "finals_week"}))

    def test_expanded_prune_scope_requires_a_new_database_backup(self):
        previous = {"state": "complete", "backup": "data/backups/old.dump",
                    "database_before": {"games": 163}, "completed_at": "old-run"}
        report = {"backup": previous["backup"], "database_before": previous["database_before"],
                  "backup_history": []}
        fresh = prune.require_fresh_backup(report, previous)
        self.assertNotIn("backup", fresh)
        self.assertNotIn("database_before", fresh)
        self.assertEqual(fresh["backup_history"], [{"path": "data/backups/old.dump",
            "database_before": {"games": 163}, "created_at": "old-run"}])

    def test_safe_move_archives_under_verified_windows_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "data" / "games" / "S22"
            archive_root = root / "data" / "archive" / "S22_excluded_games" / "run"
            source = source_root / "2026-08-19_g04_BV1tj8p6REfY"
            destination = archive_root / "games" / source.name
            source.mkdir(parents=True)
            (source / "dossier.json").write_text("preserved", encoding="utf-8")
            self.assertTrue(prune.safe_move(source, destination, source_root, archive_root))
            self.assertFalse(source.exists())
            self.assertEqual((destination / "dossier.json").read_text(encoding="utf-8"), "preserved")
            self.assertFalse(prune.safe_move(source, destination, source_root, archive_root))

    def test_offline_rules_embed_both_documents_with_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs/archive/S22"
            docs.mkdir(parents=True)
            contents = {
                "版型规则与夜间顺序.md": "旧规则正文",
                "正式版型规则与录入流程.md": "正式版规则正文",
            }
            for name, content in contents.items():
                (docs / name).write_text(content, encoding="utf-8")
            rules, hashes = embedded_rule_documents(root)
            self.assertIn(contents["版型规则与夜间顺序.md"], rules)
            self.assertIn(contents["正式版型规则与录入流程.md"], rules)
            self.assertIn("历史证据资料，规则更新以S22正式规则册为准。", rules)
            self.assertIn("S22正式录入口径。", rules)
            self.assertEqual(set(hashes), {
                "docs/archive/S22/版型规则与夜间顺序.md",
                "docs/archive/S22/正式版型规则与录入流程.md",
            })
            self.assertEqual(hashes["docs/archive/S22/版型规则与夜间顺序.md"],
                             hashlib.sha256(contents["版型规则与夜间顺序.md"].encode()).hexdigest())

    def test_offline_decision_counts_follow_active_decisions(self):
        decisions, original, additional = attach_original_questions(
            [{"id": "q1"}, {"id": "q2"}, {"id": "new1"}],
            {"q1": {"id": "q1"}, "q2": {"id": "q2"}},
        )
        self.assertEqual((original, additional), (2, 1))
        self.assertEqual(sum(d["original_question"] is not None for d in decisions), original)

    def test_loaded_old_progress_filters_excluded_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / game_scope.POLICY_REL
            policy.parent.mkdir()
            policy.write_text(json.dumps({"seasons": {"S22": {"scope": {
                "excluded_bvids": ["BVexcluded"]}}}}), encoding="utf-8")
            state_path = root / "state.json"
            state_path.write_text(json.dumps({"season": "S22", "items": {
                "BVexcluded": {"phase": "regular"}, "BVkeep": {"phase": "regular"}}}), encoding="utf-8")
            with patch.object(batch, "ROOT", root), patch.object(batch, "STATE_FILE", state_path):
                self.assertEqual(set(batch.load_state()["items"]), {"BVkeep"})

    def test_direct_import_blocks_before_validation_or_database_write(self):
        with patch.object(game_records, "connect") as connect, patch.object(game_records, "validate") as validate:
            with self.assertRaisesRegex(game_records.ReviewError, "禁止重新入库"):
                game_records.import_game({"season": "S22", "phase": "showmatch"})
            connect.assert_not_called()
            validate.assert_not_called()
