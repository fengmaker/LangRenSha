"""Confirmed mechanical form, timing, takeover and poison-resolution cases."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from game_records import (ReviewError, apply_derived_rules, describe, hunter_skill_state,
                          mechanical_skill_state, poison_effects, prior_departures, validate)


class MechanicalGameRulesTests(unittest.TestCase):
    def setUp(self):
        self.value=json.loads((ROOT/"data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q/dossier.json").read_text(encoding="utf-8"))

    def event(self,number,phase,slot):
        return next(e for e in self.value["rounds"][number-1][phase] if e["slot"]==slot)

    def form(self,target,role,rounds=2):
        self.value["rounds"]=self.value["rounds"][:rounds]
        self.value["seats"][7].update(learning_target=target,learned_role=role)
        self.event(1,"night","mechanical_action").update(targets=[target],result=role)
        for round_ in self.value["rounds"]:
            n=round_["number"]
            for phase,slot in [("night","mechanical_action"),("day","mechanical_day_skill")]:
                e=self.event(n,phase,slot)
                if e["action"]=="learn":
                    continue
                state=mechanical_skill_state(self.value,n,phase)
                e.update(action="pass" if state=="available" else "unavailable",targets=[],result=None)
        apply_derived_rules(self.value)

    def test_sample_double_knife_waits_for_remaining_ordinary_wolves(self):
        for n in [1,2,3]:
            self.assertEqual(self.event(n,"night","mechanical_knife_status")["action"],"not_carrying")
        for n in [2,3]:
            e=self.event(n,"night","mechanical_action")
            self.assertEqual((e["action"],e["availability"]),("unavailable","wolves_alive"))
            self.assertIn("尚未带刀，不能发动技能刀",describe(self.value,n,"night",e))
        validate(self.value,check_files=False)

    def test_hunter_unlocks_on_first_day_but_has_no_night_skill(self):
        self.form(7,"机械猎人")
        self.assertEqual(mechanical_skill_state(self.value,1,"night"),"learning")
        self.assertEqual(mechanical_skill_state(self.value,1,"day"),"available")
        self.assertEqual(mechanical_skill_state(self.value,2,"night"),"wrong_phase")
        self.event(1,"day","mechanical_day_skill").update(action="shoot",targets=[2])
        apply_derived_rules(self.value)
        with self.assertRaisesRegex(ReviewError,"出局触发"):
            validate(self.value,check_files=False)
        self.event(1,"day","exile_result").update(action="exile",targets=[8])
        # Day 2 events are not needed to test the departure-triggered shot.
        self.value["rounds"]=self.value["rounds"][:1]
        apply_derived_rules(self.value)
        validate(self.value,check_files=False)
        self.assertIn(8,prior_departures(self.value,2))

    def test_night_forms_unlock_second_night_even_with_small_wolves_alive(self):
        for target,role,action in [(1,"机械通灵师","check"),(5,"机械守卫","guard"),(10,"机械女巫","poison")]:
            with self.subTest(form=role):
                self.setUp()
                self.form(target,role)
                self.assertEqual(mechanical_skill_state(self.value,1,"day"),"wrong_phase")
                self.assertEqual(mechanical_skill_state(self.value,2,"night"),"available")
                e=self.event(2,"night","mechanical_action")
                e.update(action=action,targets=[2])
                if action=="poison":
                    self.event(2,"day","night_deaths").update(action="die",targets=[1,2])
                apply_derived_rules(self.value)
                validate(self.value,check_files=False)

    def test_no_skill_on_learning_night_or_in_wrong_phase(self):
        self.form(5,"机械守卫")
        self.event(1,"night","mechanical_action").update(action="guard",targets=[7],result=None)
        apply_derived_rules(self.value)
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)
        self.setUp()
        self.form(7,"机械猎人")
        self.event(2,"night","mechanical_action").update(action="attack",targets=[2])
        apply_derived_rules(self.value)
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)

    def prepare_reflection(self,shield_target=7,shield_action="guard"):
        self.form(5,"机械守卫")
        self.event(2,"night","mechanical_action").update(action=shield_action,targets=[shield_target] if shield_action=="guard" else [])
        self.event(2,"night","witch_poison").update(action="poison",targets=[7])
        self.event(2,"day","night_deaths").update(action="die",targets=[1,10] if shield_target==7 and shield_action=="guard" else [1,7])
        apply_derived_rules(self.value)

    def test_shield_reflection_kills_witch_and_preserves_hunter_skill(self):
        self.prepare_reflection()
        effect=poison_effects(self.value,2)["witch_poison"][0]
        self.assertEqual(effect,{"kind":"poison_reflected","intended_target":7,"dead_seat":10,"shield_actor":8})
        self.assertEqual(hunter_skill_state(self.value,2),"can_shoot")
        self.assertIn(10,prior_departures(self.value,3))
        self.assertNotIn(7,prior_departures(self.value,3))
        self.assertEqual(describe(self.value,2,"night",self.event(2,"night","witch_poison")),
            "第二夜10号女巫对7号猎人用毒，毒药被8号机械守卫的盾反弹，10号女巫死亡")
        validate(self.value,check_files=False)

    def test_reflection_cannot_be_recorded_as_original_target_death(self):
        self.prepare_reflection()
        self.event(2,"day","night_deaths")["targets"]=[1,7]
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)

    def test_shield_on_other_target_does_not_reflect_poison(self):
        self.prepare_reflection(shield_target=2)
        self.assertEqual(hunter_skill_state(self.value,2),"cannot_shoot")
        self.assertEqual(poison_effects(self.value,2)["witch_poison"][0]["dead_seat"],7)
        validate(self.value,check_files=False)

    def test_unknown_mechanical_shield_keeps_poison_outcome_unknown(self):
        self.prepare_reflection(shield_action="unknown")
        self.assertEqual(hunter_skill_state(self.value,2),"unknown")
        self.assertEqual(poison_effects(self.value,2)["witch_poison"][0]["kind"],"poison_unresolved")
        validate(self.value,check_files=False)

    def test_ordinary_guard_does_not_reflect_poison(self):
        self.value["rounds"]=self.value["rounds"][:1]
        self.event(1,"night","guard")["targets"]=[7]
        # The source dossier used the antidote this night. Free it in this
        # synthetic poison scenario so the ordinary witch uses one potion.
        self.event(1,"night","witch_save").update(action="pass",targets=[])
        self.event(1,"night","witch_poison").update(action="poison",targets=[7])
        self.event(1,"day","night_deaths").update(action="die",targets=[7])
        apply_derived_rules(self.value)
        self.assertEqual(hunter_skill_state(self.value,1),"cannot_shoot")
        validate(self.value,check_files=False)

    def test_mechanical_forms_cannot_use_each_others_skill_or_coexist(self):
        self.form(10,"机械女巫")
        self.event(2,"night","mechanical_action").update(action="guard",targets=[7])
        apply_derived_rules(self.value)
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)
        self.setUp()
        self.form(5,"机械女巫")
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)

    def test_mechanical_hunter_poison_disables_day_shot(self):
        self.form(7,"机械猎人",rounds=1)
        # Keep the test night legal: the witch cannot save and poison together.
        self.event(1,"night","witch_save").update(action="pass",targets=[])
        self.event(1,"night","witch_poison").update(action="poison",targets=[8])
        self.event(1,"day","night_deaths").update(action="die",targets=[8])
        self.event(1,"day","mechanical_day_skill").update(action="unavailable")
        apply_derived_rules(self.value)
        self.assertEqual(mechanical_skill_state(self.value,1,"day"),"poisoned")
        validate(self.value,check_files=False)
        self.event(1,"day","mechanical_day_skill").update(action="shoot",targets=[2])
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)

    def test_double_knife_skill_bypasses_guard_after_takeover(self):
        # Kill the last ordinary wolf on day 2; mechanic takes over on night 3.
        self.event(2,"night","witch_poison").update(action="poison",targets=[3])
        self.event(2,"day","night_deaths").update(targets=[1,3])
        self.event(3,"night","guard")["targets"]=[2]
        self.event(3,"night","wolf_attack").update(actor=8,targets=[9])
        self.event(3,"night","mechanical_action").update(action="attack",targets=[2])
        self.event(3,"day","hunter_shot").update(action="unavailable",targets=[])
        self.event(3,"day","night_deaths").update(targets=[2,9])
        self.event(3,"day","self_destruct").update(action="none",actor=None)
        apply_derived_rules(self.value)
        self.assertEqual(mechanical_skill_state(self.value,3,"night"),"available")
        self.assertEqual(self.event(3,"night","mechanical_knife_status")["action"],"carrying")
        self.assertEqual(self.event(3,"night","mechanical_action")["effects"],
            [{"kind":"shield_bypassed","intended_target":2,"dead_seat":None,"shield_actor":5}])
        self.assertEqual(self.event(3,"night","wolf_attack")["effects"],[])
        validate(self.value,check_files=False)

    def test_double_knife_cannot_take_over_or_use_skill_before_last_wolf_leaves(self):
        for slot in ["mechanical_action","wolf_attack"]:
            with self.subTest(slot=slot):
                self.setUp()
                self.event(2,"night",slot).update(action="attack",actor=8,targets=[2])
                apply_derived_rules(self.value)
                with self.assertRaises(ReviewError):
                    validate(self.value,check_files=False)

    def test_cannot_relearn_a_second_form(self):
        self.event(2,"night","mechanical_action").update(action="learn",targets=[12],result="机械双刀狼")
        apply_derived_rules(self.value)
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)

    def test_learning_may_be_delayed_and_unlock_is_relative_to_learning(self):
        self.form(5,"机械守卫")
        self.event(1,"night","mechanical_action").update(action="pass",targets=[],result=None)
        self.event(2,"night","mechanical_action").update(action="learn",targets=[5],result="机械守卫")
        self.event(1,"day","mechanical_day_skill").update(action="unavailable")
        apply_derived_rules(self.value)
        self.assertEqual(mechanical_skill_state(self.value,1,"night"),"locked")
        self.assertEqual(mechanical_skill_state(self.value,2,"night"),"learning")
        validate(self.value,check_files=False)

    def test_night_knife_confirmation_must_match_known_departures(self):
        self.event(2,"night","mechanical_knife_status")["action"]="carrying"
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)

    def test_unknown_prior_deaths_do_not_assert_small_wolves_alive_or_takeover(self):
        self.event(2,"day","night_deaths").update(action="unknown",targets=[])
        self.event(3,"day","hunter_shot").update(action="unknown",targets=[])
        self.event(3,"night","mechanical_action").update(action="unknown")
        self.event(3,"day","mechanical_day_skill").update(action="unknown")
        apply_derived_rules(self.value)
        self.assertEqual(mechanical_skill_state(self.value,3,"night"),"unknown")
        self.assertEqual(hunter_skill_state(self.value,3),"unknown")
        validate(self.value,check_files=False)
        self.event(3,"night","mechanical_action").update(action="attack",targets=[2])
        apply_derived_rules(self.value)
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)


if __name__=="__main__":
    unittest.main()
