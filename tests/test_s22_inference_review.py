"""Content checks catch impossible histories without rejecting simultaneous skills."""
from pathlib import Path
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import batch_s22 as batch
from s22_inference_review import active_scope_entries, semantic_issues, changed_value, later_rule_alignment_valid


def event(slot, action, actor=None, targets=()):
    return dict(slot=slot, action=action, actor=actor, targets=list(targets))


class InferenceContentTests(unittest.TestCase):
    def test_later_sourced_revision_does_not_rewrite_or_bypass_historic_hashes(self):
        real_root = Path(__file__).resolve().parents[1]
        sample = real_root / "data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q/dossier.json"
        before = json.loads(sample.read_text(encoding="utf-8"))
        changes = [{"kind": "event", "number": 1, "phase": "night", "slot": "guard",
                    "fields": {"action": "pass", "targets": []}}]
        after = changed_value(before, changes)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before_path = root / "data/archive/S22_formal_rule_alignment/BVtest/before.json"
            after_path = root / "data/games/S22/test/dossier.json"
            source = root / "data/source.txt"
            for path, value in ((before_path, before), (after_path, after)):
                batch.atomic_json(path, value)
            source.write_text("明确的守卫空过记录", encoding="utf-8")
            old_hash, current_hash = batch.digest(before_path), batch.digest(after_path)
            report = {"items": [{"bvid": "BVtest", "state": "applied", "before_sha256": old_hash,
                "after_sha256": current_hash, "before_snapshot": before_path.relative_to(root).as_posix(),
                "file": after_path.relative_to(root).as_posix(), "changes": changes,
                "evidence": [{"path": "data/source.txt", "quote": "守卫空过", "source_sha256": batch.digest(source)}]}]}
            batch.atomic_json(root / "data/reports/S22_正式规则对齐记录.json", report)
            with patch.object(batch, "ROOT", root):
                self.assertTrue(later_rule_alignment_valid("BVtest", old_hash, current_hash, {}))
                self.assertFalse(later_rule_alignment_valid("BVtest", "wrong-before", current_hash, {}))
                source.write_text("source changed", encoding="utf-8")
                self.assertFalse(later_rule_alignment_valid("BVtest", old_hash, current_hash, {}))

    def test_historical_plan_skips_newly_excluded_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "config" / "S22_game_scope.json"
            policy.parent.mkdir()
            policy.write_text(json.dumps({"season": "S22", "excluded_bvids": ["BV1tj8p6REfY"]}),
                              encoding="utf-8")
            entries = [
                {"bvid": "BV1tj8p6REfY", "phase": "finals_week", "date": "2026-08-19"},
                {"bvid": "BV1jM8B6jE2i", "phase": "finals_week", "date": "2026-08-21"},
            ]
            self.assertEqual([entry["bvid"] for entry in active_scope_entries(entries, root=root)],
                             ["BV1jM8B6jE2i"])

    def test_current_night_victim_can_act_but_cannot_act_next_night(self):
        value = {"rounds": [
            {"number": 1, "night": [event("seer_check", "check", 2, [3])],
             "day": [event("night_deaths", "die", targets=[2])]},
        ]}
        self.assertEqual(semantic_issues(value), [])
        value["rounds"].append({"number": 2,
            "night": [event("seer_check", "check", 2, [3])], "day": []})
        self.assertIn("行动者前轮已出局", "；".join(semantic_issues(value)))

    def test_one_time_medicine_and_no_two_medicines_same_night(self):
        value = {"rounds": [
            {"number": 1, "night": [event("witch_save", "save", 2, [3]),
                event("witch_poison", "poison", 2, [4])], "day": []},
            {"number": 2, "night": [event("witch_poison", "poison", 2, [5])], "day": []},
        ]}
        issues = "；".join(semantic_issues(value))
        self.assertIn("同夜使用两药", issues)
        self.assertIn("一次性witch_poison重复", issues)

    def test_departed_target_and_repeated_night_death_are_rejected(self):
        value = {"rounds": [
            {"number": 1, "night": [], "day": [event("exile", "exile", targets=[3])]},
            {"number": 2, "night": [event("wolf_attack", "attack", targets=[3])],
             "day": [event("night_deaths", "die", targets=[3])]},
        ]}
        issues = "；".join(semantic_issues(value))
        self.assertIn("目标前轮已出局", issues)
        self.assertIn("夜死名单重复前轮死者", issues)

    def test_repeated_dance_and_consecutive_mask_targets_are_rejected(self):
        value = {"rounds": [
            {"number": 2, "night": [event("dancer_dance", "dance", 1, [1, 2, 3]),
                event("masquerade_mask", "give_mask", 4, [5])], "day": []},
            {"number": 3, "night": [event("dancer_dance", "dance", 1, [1, 6, 7]),
                event("masquerade_mask", "give_mask", 4, [5])], "day": []},
        ]}
        issues = "；".join(semantic_issues(value))
        self.assertIn("包含此前已共舞者", issues)
        self.assertIn("连续重复选择", issues)


if __name__ == "__main__":
    unittest.main()
