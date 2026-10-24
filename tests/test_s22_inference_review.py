"""Content checks catch impossible histories without rejecting simultaneous skills."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from s22_inference_review import semantic_issues


def event(slot, action, actor=None, targets=()):
    return dict(slot=slot, action=action, actor=actor, targets=list(targets))


class InferenceContentTests(unittest.TestCase):
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
