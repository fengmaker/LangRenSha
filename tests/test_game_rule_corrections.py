"""Regression cases for the user's confirmed speech, hunter and seating rules."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from game_records import ReviewError, apply_derived_rules, describe, hunter_skill_state, resolve_speech_start, validate


class ConfirmedGameRulesTests(unittest.TestCase):
    def setUp(self):
        self.value=json.loads((ROOT/"data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q/dossier.json").read_text(encoding="utf-8"))

    def event(self,number,phase,slot):
        return next(e for e in self.value["rounds"][number-1][phase] if e["slot"]==slot)

    def test_first_day_random_point_skips_seat_three_off_sheriff_election(self):
        event=self.event(1,"day","speech_order")
        self.assertEqual(event["action"],"order")
        self.assertEqual(event["random_point"],3)
        self.assertEqual(event["start_seat"],4)
        self.assertEqual(event["direction"],"forward")
        self.assertEqual(describe(self.value,1,"day",event),"第一天白天随机点数3，从4号平民开始顺序发言")

    def test_unpoisoned_hunter_can_shoot_all_three_nights(self):
        for number in [1,2,3]:
            with self.subTest(night=number):
                self.assertEqual(self.event(number,"night","hunter_state")["action"],"can_shoot")

    def test_user_confirmed_seat_names(self):
        names={p["seat"]:p["name"] for p in self.value["seats"]}
        self.assertEqual({s:names[s] for s in [7,9,11,12]},{7:"JY",9:"翼风",11:"申屠",12:"陈俊洁"})
        self.assertTrue(all(names.values()))

    def test_second_day_has_no_speech(self):
        self.assertEqual(self.event(2,"day","speech_order")["action"],"not_held")

    def test_random_point_honors_direction_and_wraps_to_eligible_seat(self):
        self.assertEqual(resolve_speech_start(3,"forward",[1,4,5],12),4)
        self.assertEqual(resolve_speech_start(3,"reverse",[1,4,5],12),1)
        self.assertEqual(resolve_speech_start(12,"forward",[1,4],12),1)
        self.assertEqual(resolve_speech_start(1,"reverse",[4,12],12),12)

    def test_rejects_starting_at_a_seat_not_on_sheriff_election(self):
        self.event(1,"day","speech_order")["start_seat"]=3
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)

    def test_jy_must_be_seat_seven_whenever_present(self):
        self.value["seats"][6]["name"],self.value["seats"][8]["name"]=self.value["seats"][8]["name"],self.value["seats"][6]["name"]
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)

    def prepare_poison(self,mechanical=False):
        number=2 if mechanical else 1
        self.value["rounds"]=self.value["rounds"][:number]
        poison=self.event(number,"night","mechanical_action" if mechanical else "witch_poison")
        poison.update(action="poison",targets=[7],result=None)
        if mechanical:
            self.value["seats"][7].update(learning_target=10,learned_role="机械女巫")
            self.event(1,"night","mechanical_action").update(targets=[10],result="机械女巫")
        self.event(number,"day","night_deaths").update(action="die",targets=[7])
        apply_derived_rules(self.value)

    def test_witch_poison_disables_hunter_shot(self):
        self.prepare_poison()
        self.assertEqual(hunter_skill_state(self.value,1),"cannot_shoot")
        validate(self.value,check_files=False)
        self.event(1,"day","hunter_shot").update(action="shoot",targets=[8])
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)

    def test_mechanical_witch_poison_after_hunter_eye_step_still_disables_shot(self):
        self.prepare_poison(mechanical=True)
        self.assertEqual(hunter_skill_state(self.value,2),"cannot_shoot")
        self.assertEqual(self.event(2,"night","hunter_state")["action"],"cannot_shoot")
        validate(self.value,check_files=False)

    def test_a_wolf_attack_on_hunter_does_not_disable_shot(self):
        self.event(1,"night","wolf_attack")["targets"]=[7]
        self.assertEqual(hunter_skill_state(self.value,1),"can_shoot")

    def test_stale_unknown_hunter_state_is_rejected_when_poison_is_known(self):
        self.event(1,"night","hunter_state")["action"]="unknown"
        with self.assertRaises(ReviewError):
            validate(self.value,check_files=False)


if __name__=="__main__":
    unittest.main()
