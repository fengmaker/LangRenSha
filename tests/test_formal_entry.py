"""Formal entries distinguish a known contradiction from missing source facts."""
import copy
import json
from collections import Counter
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from formal_entry import check, make_entry
from formal_rule_checks import issues, registry
from game_records import ReviewError, validate


class FormalEntryTests(unittest.TestCase):
    def entry(self, board="mixed_blood", rounds=1, number=None):
        number = number or (1 if board == "mixed_blood" else 3 if board == "mechanical_wolf_seer" else 2)
        return make_entry(board, "2026-08-21", number, rounds)

    @staticmethod
    def event(value, slot, number=1):
        return next(e for phase in ("night", "day") for e in value["rounds"][number-1][phase] if e["slot"] == slot)

    def codes(self, value):
        return {i["code"] for i in issues(value) if i["severity"] == "error"}

    def test_registry_matches_templates_and_separates_entertainment(self):
        rules = registry()
        self.assertEqual(sum(b["scored_count"] for b in rules["boards"].values()), 148)
        self.assertEqual(len(rules["boards"]), 7)
        for code, board in rules["boards"].items():
            template = json.loads((ROOT/f"config/board_templates/{code}.json").read_text(encoding="utf-8"))
            if not template.get("dynamic_roles"):
                self.assertEqual({r["physical_identity"]: r["count"] for r in board["role_composition"]}, template["role_counts"])
        with self.assertRaises(ReviewError):
            self.entry("ghost_bride")

    def test_blank_draft_passes_and_final_keeps_unknowns_unresolved(self):
        value = self.entry()
        self.assertTrue(check(value, check_files=False)["valid"])
        result = check(value, final=True, check_files=False)
        self.assertFalse(result["valid"])
        self.assertFalse(result["errors"])
        self.assertTrue(result["pending"])
        self.assertIsNone(value["seats"][0]["role"])

    def test_mixed_wolf_allegiance_does_not_grant_knife_or_change_seer_result(self):
        value = self.entry()
        value["seats"][0].update(role="混血儿", faction="werewolf")
        value["seats"][1].update(role="狼人", faction="werewolf")
        self.event(value, "mixed_blood_model").update(action="choose", actor=1, targets=[2])
        self.event(value, "wolf_attack").update(action="attack", actor=2, targets=[1])
        self.event(value, "seer_check").update(action="check", targets=[1], result="好人")
        self.assertTrue(check(value, check_files=False)["valid"])
        self.event(value, "wolf_attack")["actor"] = 1
        with self.assertRaisesRegex(ReviewError, "狼刀行动者"):
            check(value, check_files=False)
        self.event(value, "wolf_attack")["actor"] = 2
        self.event(value, "seer_check")["result"] = "狼人"
        self.assertIn("mixed_seer_good", self.codes(value))

    def test_mixed_model_and_victory_projection_must_agree(self):
        value = self.entry()
        value["seats"][0].update(role="混血儿", faction="werewolf")
        value["seats"][1].update(role="平民", faction="good")
        self.event(value, "mixed_blood_model").update(action="choose", actor=1, targets=[2])
        self.assertIn("model_faction", self.codes(value))

    def test_ordinary_potions_self_save_per_night_and_global_limits(self):
        value = self.entry(rounds=2)
        self.event(value, "witch_save").update(action="save", actor=1, targets=[1])
        self.event(value, "witch_poison").update(action="poison", actor=1, targets=[2])
        self.event(value, "witch_poison", 2).update(action="poison", actor=1, targets=[3])
        self.assertTrue({"witch_self_save", "witch_one_per_night", "potion_exhausted"} <= self.codes(value))

    def test_mechanical_guard_can_self_guard_but_cannot_repeat(self):
        value = self.entry("mechanical_wolf_seer", rounds=3)
        value["seats"][0].update(role="机械狼", faction="werewolf", learned_role="机械守卫")
        for n in (2, 3):
            self.event(value, "mechanical_action", n).update(action="guard", actor=1, targets=[1])
        self.assertIn("guard_consecutive", self.codes(value))
        self.event(value, "mechanical_action", 3)["targets"] = [2]
        self.assertFalse(self.codes(value))

    def test_mechanical_poison_is_one_per_game_and_self_explosion_forbidden(self):
        value = self.entry("mechanical_wolf_seer", rounds=3)
        value["seats"][0].update(role="机械狼", faction="werewolf", learned_role="机械女巫")
        for n in (2, 3):
            self.event(value, "mechanical_action", n).update(action="poison", actor=1, targets=[2])
        self.assertIn("mechanical_poison_exhausted", self.codes(value))
        self.event(value, "self_destruct").update(action="self_destruct", actor=1)
        with self.assertRaisesRegex(ReviewError, "不能自爆"):
            validate(value, check_files=False, allow_incomplete=True)

    def test_delayed_learning_preserves_unlearned_seer_feedback(self):
        value = self.entry("mechanical_wolf_seer", rounds=2)
        value["seats"][0].update(role="机械狼", faction="werewolf", learned_role="机械守卫", learning_target=5)
        value["seats"][4].update(role="守卫", faction="good")
        self.event(value, "mechanical_action").update(action="pass", actor=1)
        self.event(value, "seer_check").update(action="check", targets=[1], result="双爪狼")
        self.event(value, "mechanical_action", 2).update(action="learn", actor=1, targets=[5], result="机械守卫")
        self.event(value, "seer_check", 2).update(action="check", targets=[1], result="守卫")
        self.assertFalse(self.codes(value))
        self.assertTrue(check(value, check_files=False)["valid"])
        self.event(value, "seer_check")["result"] = "机械狼"
        self.assertIn("mechanical_seer_feedback", self.codes(value))
        self.assertEqual(value["seats"][0]["role"], "机械狼")

    def test_same_knife_guard_and_save_cannot_be_peaceful(self):
        for slot in ("guard", "mechanical_action"):
            with self.subTest(slot=slot):
                value = self.entry("mechanical_wolf_seer", rounds=2)
                self.event(value, slot, 2).update(action="guard", targets=[2])
                self.event(value, "wolf_attack", 2).update(action="attack", targets=[2])
                self.event(value, "witch_save", 2).update(action="save", targets=[2])
                self.event(value, "night_deaths", 2).update(action="peaceful")
                self.assertIn("guard_save_death", self.codes(value))
                self.event(value, "night_deaths", 2).update(action="die", targets=[2])
                self.assertNotIn("guard_save_death", self.codes(value))

    def test_puppet_first_night_once_and_circular_adjacency(self):
        value = self.entry("neighbor_puppet", rounds=2)
        for p in value["seats"]:
            p["role"] = "平民"
        value["seats"][11]["role"] = "狼人"
        self.event(value, "puppet_select").update(action="select", targets=[1])
        self.assertNotIn("puppet_adjacency", self.codes(value))
        self.event(value, "puppet_select")["targets"] = [5]
        self.assertIn("puppet_adjacency", self.codes(value))
        self.event(value, "puppet_select", 2).update(action="select", targets=[1])
        self.assertIn("first_night_puppet", self.codes(value))

    def test_trade_records_both_mixed_decisions_and_requires_pair_order(self):
        value = self.entry("all_in", rounds=2)
        self.event(value, "warden_trade_targets", 2).update(action="select_pair", targets=[3, 7])
        e = self.event(value, "trade_decisions", 2)
        for action in ("trade", "betray", "trade_betray", "betray_trade"):
            e.update(action=action, targets=[3, 7])
            self.assertTrue(check(value, check_files=False)["valid"])
        e["targets"] = [7, 3]
        self.assertIn("trade_participant_order", self.codes(value))

    def test_cross_night_dance_and_guile_reuse_are_detected(self):
        value = self.entry("masquerade", rounds=3)
        self.event(value, "dancer_dance", 2).update(action="dance", targets=[1, 2, 3])
        self.event(value, "dancer_dance", 3).update(action="dance", targets=[3, 4, 5])
        self.assertIn("once_per_participant", self.codes(value))
        value = self.entry("guile_realm", rounds=2)
        for n in (1, 2):
            self.event(value, "guile_exchange", n).update(action="pass")
        self.assertIn("guile_consecutive_pass", self.codes(value))

    def test_real_invalid_exchange_preserves_the_attempt_and_judge_ruling(self):
        value = self.entry("guile_realm", rounds=2)
        value["seats"][0].update(role="诡术师", faction="werewolf")
        self.event(value, "guile_exchange").update(action="exchange", actor=1, targets=[3, 7])
        e = self.event(value, "guile_exchange", 2)
        e.update(action="invalid_exchange", actor=1, targets=[5, 7], result="disqualified_repeat_target")
        self.assertTrue(check(value, check_files=False)["valid"])
        e["result"] = None
        with self.assertRaisesRegex(ReviewError, "判离裁定"):
            check(value, check_files=False)

    def test_strict_dynamic_treasure_uses_actual_twelve_cards(self):
        value = self.entry("treasure_master")
        roles = ["通灵师", "毒师", "猎人", "摄梦人", "蒙面人", "平民", "狼王", "狼人", "狼人", "狼人", "盗宝大师", "平民"]
        for p, role in zip(value["seats"], roles):
            p.update(role=role, faction="werewolf" if role in {"狼人", "狼王", "盗宝大师"} else "good", name=f"选手{p['seat']}")
        value.update(roster=[p["name"] for p in value["seats"]], commentators=["解说甲"], referee="法官甲")
        remainder = Counter({"通灵师": 1, "毒师": 1, "猎人": 1, "摄梦人": 1, "蒙面人": 1,
                             "平民": 5, "狼王": 1, "狼人": 3, "盗宝大师": 1}) - Counter(roles)
        self.assertEqual(remainder["狼人"] + remainder["狼王"], 0)
        self.assertEqual(validate(value, check_files=False)["code"], "treasure_master")
        value["seats"][10]["faction"] = "good"
        self.assertIn("treasure_alignment", self.codes(value))

    def test_treasure_master_takes_ordinary_knife_only_after_other_wolves_depart(self):
        value = self.entry("treasure_master", rounds=2)
        roles = ["盗宝大师", "狼人", "狼人", "狼人", "狼王", "通灵师", "毒师", "猎人", "摄梦人", "蒙面人", "平民", "平民"]
        for p, role in zip(value["seats"], roles):
            p.update(role=role, faction="werewolf" if role in {"狼人", "狼王", "盗宝大师"} else "good")
        knife = self.event(value, "wolf_attack", 2)
        knife.update(action="attack", actor=1, targets=[6])

        pending = next(i for i in issues(value) if i["code"] == "treasure_knife_timing_unknown")
        self.assertEqual(pending["severity"], "pending")
        prior_outcomes = {
            "night_deaths": "peaceful", "exile_result": "none", "self_destruct": "none",
            "hunter_shot": "unavailable", "wolf_king_shot": "unavailable",
            "masked_delayed_death": "not_triggered",
        }
        for slot, action in prior_outcomes.items():
            self.event(value, slot, 1).update(action=action, targets=[])
        self.assertIn("treasure_knife_timing", self.codes(value))

        first_day = value["rounds"][0]["day"]
        exile = next(e for e in first_day if e["slot"] == "exile_result")
        exile.update(action="exile", targets=[2, 3, 4])
        self.assertIn("treasure_knife_timing", self.codes(value), "仅狼人出局、狼王仍存活时不得接刀")
        exile["targets"] = [2, 3, 4, 5]
        self.assertNotIn("treasure_knife_timing", self.codes(value))
        self.event(value, "treasure_choice").update(action="choose", result="通灵师")
        self.assertIn("treasure_remaining_choice", self.codes(value))

    def test_strict_nonmechanical_accepts_actual_special_wolves_and_wolf_mixed(self):
        for code in ("mixed_blood", "guile_realm", "masquerade", "neighbor_puppet", "all_in"):
            with self.subTest(board=code):
                value = self.entry(code)
                board = json.loads((ROOT/f"config/board_templates/{code}.json").read_text(encoding="utf-8"))
                wolves = {"狼人", "诡术师", "假面", "狼王", "典狱长"}
                roles = [role for role, amount in board["role_counts"].items() for _ in range(amount)]
                for p, role in zip(value["seats"], roles):
                    p.update(role=role, faction="werewolf" if role in wolves or role == "混血儿" else "good", name=f"选手{p['seat']}")
                value.update(roster=[p["name"] for p in value["seats"]], commentators=["解说甲"], referee="法官甲")
                self.assertEqual(validate(value, check_files=False)["code"], code)

    def test_confirmed_guile_extra_is_scored_and_daily_pattern_is_checked(self):
        value = self.entry("guile_realm", number=4)
        value["date"] = "2026-06-26"
        self.assertTrue(check(value, check_files=False)["valid"])
        value["game_number"] = 1
        self.assertEqual(check(value, check_files=False)["errors"][0]["code"], "first_board")

    def test_formal_third_party_winner_is_rejected_by_normal_draft_import_validation(self):
        value = self.entry()
        value["winner"] = "third_party"
        with self.assertRaisesRegex(ReviewError, "正式局胜方"):
            validate(value, check_files=False, allow_incomplete=True)


if __name__ == "__main__":
    unittest.main()
