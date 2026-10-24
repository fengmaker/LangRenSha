"""Frame-seat acceptance preserves exact provenance across sourced dossier edits."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_s22_frame_seats as audit


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class FrameSeatAuditLineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output_dir = "data/games/S22/2026-06-11_g01_BVtest"
        self.frame_dossier = {
            "slug": "bili-BVtest-p01-g01", "board": "mixed_blood", "winner": "good",
            "roster": ["Scheduled Name"],
            "seats": [{"seat": 1, "name": "Frame Name", "role": "预言家", "faction": "good"}],
        }
        self.receipt_bytes = json_bytes(self.frame_dossier)
        self.receipt_hash = hashlib.sha256(self.receipt_bytes).hexdigest()
        self.current_path = self.root / self.output_dir / "dossier.json"
        self.current_path.parent.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def make_backup_report(self, *, member_bytes=None):
        backup_path = self.root / "data/backups/inference.zip"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(self.output_dir + "/dossier.json",
                             self.receipt_bytes if member_bytes is None else member_bytes)
        return {"state": "complete", "backup": {"files": "data/backups/inference.zip"}}

    def test_resolves_frame_stage_only_from_exact_receipt_snapshot(self):
        report = self.make_backup_report()
        snapshot = audit.resolve_frame_stage_snapshot(
            "BVtest", self.output_dir, self.receipt_hash, report, {}, root=self.root)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.dossier, self.frame_dossier)
        self.assertEqual(snapshot.sha256, self.receipt_hash)
        self.assertEqual(snapshot.source, "inference_backup")

        wrong_bytes = json_bytes({**self.frame_dossier, "winner": "werewolf"})
        wrong_report = self.make_backup_report(member_bytes=wrong_bytes)
        self.assertIsNone(audit.resolve_frame_stage_snapshot(
            "BVtest", self.output_dir, self.receipt_hash, wrong_report, {}, root=self.root))

    def test_can_resolve_matching_rule_alignment_before_snapshot(self):
        snapshot_path = self.root / audit.RULE_ALIGNMENT_ARCHIVE.relative_to(audit.ROOT) / "BVtest" / "before.json"
        snapshot_path.parent.mkdir(parents=True)
        snapshot_path.write_bytes(self.receipt_bytes)
        report = {"items": [{
            "bvid": "BVtest", "state": "applied", "file": self.output_dir + "/dossier.json",
            "before_sha256": self.receipt_hash,
            "before_snapshot": snapshot_path.relative_to(self.root).as_posix(),
        }]}
        snapshot = audit.resolve_frame_stage_snapshot(
            "BVtest", self.output_dir, self.receipt_hash, {}, report, root=self.root)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.source, "rule_alignment_before_snapshot")

    def test_inference_changes_must_replay_to_current_hash(self):
        current = {**self.frame_dossier, "winner": "werewolf"}
        self.current_path.write_bytes(json_bytes(current))
        current_hash = hashlib.sha256(self.current_path.read_bytes()).hexdigest()
        inference = {"state": "complete", "items": [{
            "bvid": "BVtest", "output_dir": self.output_dir,
            "dossier_sha256": self.receipt_hash, "after_sha256": current_hash,
            "changes": [{"kind": "winner", "value": "werewolf"}],
        }]}
        snapshot = audit.FrameStageSnapshot(self.frame_dossier, self.receipt_hash, "inference_backup")
        with patch.object(audit, "replay_inference_changes", return_value=current):
            valid, reason = audit.verify_frame_stage_lineage(
                "BVtest", self.output_dir, self.receipt_hash, snapshot,
                self.current_path, current_hash, current, inference, {}, {}, root=self.root)
        self.assertTrue(valid)
        self.assertEqual(reason, "inference_replay")

        unregistered = {**current, "winner": "unknown"}
        self.current_path.write_bytes(json_bytes(unregistered))
        unregistered_hash = hashlib.sha256(self.current_path.read_bytes()).hexdigest()
        with patch.object(audit, "replay_inference_changes", return_value=current), \
                patch.object(audit, "later_rule_alignment_is_valid", return_value=False):
            valid, reason = audit.verify_frame_stage_lineage(
                "BVtest", self.output_dir, self.receipt_hash, snapshot,
                self.current_path, unregistered_hash, unregistered, inference, {}, {}, root=self.root)
        self.assertFalse(valid)
        self.assertIsNone(reason)

    def test_inference_then_rule_alignment_requires_matching_before_snapshot(self):
        after_inference = {**self.frame_dossier, "winner": "werewolf"}
        current = {**after_inference, "commentators": ["verified correction"]}
        self.current_path.write_bytes(json_bytes(current))
        current_hash = hashlib.sha256(self.current_path.read_bytes()).hexdigest()
        after_bytes = json_bytes(after_inference)
        after_hash = hashlib.sha256(after_bytes).hexdigest()
        before_path = (self.root / audit.RULE_ALIGNMENT_ARCHIVE.relative_to(audit.ROOT)
                       / "BVtest" / "before-inference-aligned.json")
        before_path.parent.mkdir(parents=True)
        before_path.write_bytes(after_bytes)
        alignment = {"items": [{
            "bvid": "BVtest", "state": "applied", "file": self.output_dir + "/dossier.json",
            "before_sha256": after_hash, "after_sha256": current_hash,
            "before_snapshot": before_path.relative_to(self.root).as_posix(),
        }]}
        inference = {"state": "complete", "items": [{
            "bvid": "BVtest", "output_dir": self.output_dir,
            "dossier_sha256": self.receipt_hash, "after_sha256": after_hash,
            "changes": [{"kind": "winner", "value": "werewolf"}],
        }]}
        snapshot = audit.FrameStageSnapshot(self.frame_dossier, self.receipt_hash, "inference_backup")
        with patch.object(audit, "replay_inference_changes", return_value=after_inference), \
                patch.object(audit, "later_rule_alignment_is_valid", return_value=True) as alignment_check:
            valid, reason = audit.verify_frame_stage_lineage(
                "BVtest", self.output_dir, self.receipt_hash, snapshot,
                self.current_path, current_hash, current, inference, alignment, {}, root=self.root)
        self.assertTrue(valid)
        self.assertEqual(reason, "inference_then_rule_alignment")
        alignment_check.assert_called_once_with("BVtest", after_hash, current_hash, {})

        before_path.write_bytes(json_bytes({**after_inference, "winner": "good"}))
        with patch.object(audit, "replay_inference_changes", return_value=after_inference), \
                patch.object(audit, "later_rule_alignment_is_valid",
                             side_effect=lambda _bvid, before_hash, observed_current_hash, _cache:
                             before_hash == after_hash and observed_current_hash == current_hash):
            valid, reason = audit.verify_frame_stage_lineage(
                "BVtest", self.output_dir, self.receipt_hash, snapshot,
                self.current_path, current_hash, current, inference, alignment, {}, root=self.root)
        self.assertFalse(valid)
        self.assertIsNone(reason)

    def test_direct_rule_alignment_chain_is_checked_by_inference_helper(self):
        current = {**self.frame_dossier, "winner": "werewolf"}
        self.current_path.write_bytes(json_bytes(current))
        current_hash = hashlib.sha256(self.current_path.read_bytes()).hexdigest()
        snapshot = audit.FrameStageSnapshot(self.frame_dossier, self.receipt_hash, "rule_alignment_before_snapshot")
        with patch.object(audit, "later_rule_alignment_is_valid", return_value=True) as alignment_check:
            valid, reason = audit.verify_frame_stage_lineage(
                "BVtest", self.output_dir, self.receipt_hash, snapshot,
                self.current_path, current_hash, current, {}, {}, {}, root=self.root)
        self.assertTrue(valid)
        self.assertEqual(reason, "rule_alignment_from_frame_stage")
        alignment_check.assert_called_once_with("BVtest", self.receipt_hash, current_hash, {})

    def test_preimport_projection_uses_historical_nonname_fields(self):
        archived = {**self.frame_dossier, "roster": ["Scheduled Name"],
                    "seats": [{**self.frame_dossier["seats"][0], "name": None}]}
        after_ai_and_rules = {**self.frame_dossier, "winner": "werewolf",
                              "roster": ["Frame Name"]}
        self.assertEqual(audit.preimport_projection_diff(self.frame_dossier, archived), [])
        self.assertIn("winner", audit.preimport_projection_diff(after_ai_and_rules, archived))


if __name__ == "__main__":
    unittest.main()
