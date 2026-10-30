import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from game_records import ReviewError, apply_derived_rules, describe, phase_label, template, validate


DOSSIER = ROOT / "data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q/dossier.json"


class FixedGameEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = json.loads(DOSSIER.read_text(encoding="utf-8"))

    def valid_sample(self):
        return copy.deepcopy(self.sample)

    def test_real_dossier_has_eight_night_and_eleven_day_slots_every_round(self):
        value = self.valid_sample()
        board = validate(value, check_files=False)

        self.assertEqual(len(board["night_slots"]), 8)
        self.assertEqual(len(board["day_slots"]), 11)
        for round_ in value["rounds"]:
            with self.subTest(round=round_["number"]):
                self.assertEqual(len(round_["night"]), 8)
                self.assertEqual(len(round_["day"]), 11)

    def test_each_phase_rejects_a_missing_duplicate_or_misordered_slot(self):
        for phase in ("night", "day"):
            for defect in ("missing", "duplicate", "misordered"):
                with self.subTest(phase=phase, defect=defect):
                    value = self.valid_sample()
                    events = value["rounds"][0][phase]
                    if defect == "missing":
                        events.pop()
                    elif defect == "duplicate":
                        events[-1]["slot"] = events[0]["slot"]
                    else:
                        events[0], events[1] = events[1], events[0]
                    with self.assertRaises(ReviewError):
                        validate(value, check_files=False)

    def test_actor_must_have_the_role_assigned_to_the_slot(self):
        value = self.valid_sample()
        guard = value["rounds"][0]["night"][0]
        guard["actor"] = 10  # Seat 10 is the witch, not the guard.

        with self.assertRaises(ReviewError):
            validate(value, check_files=False)

    def test_actor_target_and_speech_start_numbers_must_be_real_seats(self):
        mutations = (
            ("actor", lambda value: value["rounds"][0]["night"][0].update(actor=13)),
            ("target", lambda value: value["rounds"][0]["night"][0].update(targets=[13])),
            ("speech start", lambda value: value["rounds"][2]["day"][6].update(start_seat=13)),
        )
        for label, mutate in mutations:
            with self.subTest(number=label):
                value = self.valid_sample()
                mutate(value)
                with self.assertRaises(ReviewError):
                    validate(value, check_files=False)

    def test_names_are_consistent_between_roster_and_seated_players(self):
        value = self.valid_sample()
        validate(value, check_files=False)

        seated_names = [seat["name"] for seat in value["seats"] if seat["name"] is not None]
        self.assertEqual(len(seated_names), len(set(seated_names)))
        self.assertTrue(set(seated_names).issubset(value["roster"]))
        self.assertEqual(value["commentators"], ["其人", "桃子"])
        self.assertEqual(value["referee"], "豆儿啵")

    def test_evidence_version_and_review_metadata_are_rejected_even_when_nested(self):
        forbidden_fields = (
            "evidence",
            "evidence_ids",
            "review",
            "review_state",
            "verification_status",
            "schema_version",
            "transcription_runs",
            "speech_turns",
        )
        for field in forbidden_fields:
            with self.subTest(field=field):
                value = self.valid_sample()
                value["rounds"][0]["night"][0][field] = "must not be imported"
                with self.assertRaises(ReviewError):
                    validate(value, check_files=False)

    def test_unknown_stays_distinct_from_pass_and_an_actual_abstention(self):
        value = self.valid_sample()
        # The dossier records a save here; use a synthetic unknown event to
        # exercise the description distinction without changing that record.
        unknown = copy.deepcopy(value["rounds"][0]["night"][2])
        unknown.update(action="unknown", targets=[])
        self.assertEqual(unknown["action"], "unknown")
        unknown_text = describe(value, 1, "night", unknown)
        self.assertEqual(unknown_text, "首夜10号女巫解药未知")
        self.assertNotIn("未使用", unknown_text)

        passed = copy.deepcopy(value["rounds"][1]["night"][0])
        passed.update(action="pass", targets=[])
        pass_text = describe(value, 2, "night", passed)
        self.assertEqual(pass_text, "第一天夜晚5号守卫未守护")
        self.assertNotEqual(unknown_text, pass_text)

        abstained = value["rounds"][1]["day"][7]
        abstained.update(
            action="vote",
            votes=[{"round": 2, "voter": 2, "target": None, "abstained": True}],
        )
        validate(value, check_files=False)
        self.assertEqual(describe(value, 2, "day", abstained), "第二天白天2号平民弃票")
        self.assertNotIn("未知", describe(value, 2, "day", abstained))

    def test_phase_labels_use_day_relative_night_names(self):
        self.assertEqual(phase_label(1, "night"), "首夜")
        self.assertEqual(phase_label(2, "night"), "第一天夜晚")
        self.assertEqual(phase_label(4, "night"), "第三天夜晚")
        self.assertEqual(phase_label(4, "day"), "第四天白天")

    def test_descriptions_are_fixed_and_put_the_actual_role_after_each_seat_number(self):
        value = self.valid_sample()
        expected = (
            (1, "night", 0, "首夜5号守卫守护12号狼人"),
            (1, "night", 1, "首夜狼队击杀8号机械狼"),
            (1, "night", 6, "首夜8号机械狼模仿12号狼人"),
            (1, "day", 9, "第一天白天12号狼人自爆"),
            (3, "day", 4, "第三天白天7号猎人开枪带走8号机械狼"),
        )
        for round_number, phase, event_index, expected_text in expected:
            with self.subTest(round=round_number, phase=phase, event=event_index):
                event = value["rounds"][round_number - 1][phase][event_index]
                self.assertEqual(describe(value, round_number, phase, event), expected_text)

    def test_third_day_speech_order_records_only_the_eleven_seat_start(self):
        value = self.valid_sample()
        event = value["rounds"][2]["day"][6]

        self.assertEqual(describe(value, 3, "day", event), "第三天白天随机点数11，从11号平民开始顺序发言")
        self.assertNotIn("从3号", describe(value, 3, "day", event))

    def test_any_positive_number_of_rounds_repeats_the_same_fixed_slots(self):
        board = template("mechanical_wolf_seer")
        for round_count in (1, 5, 8):
            with self.subTest(round_count=round_count):
                value = self.valid_sample()
                first_round = value["rounds"][0]
                value["rounds"] = [
                    {"number": number, "night": copy.deepcopy(first_round["night"]),
                     "day": copy.deepcopy(first_round["day"])}
                    for number in range(1, round_count + 1)
                ]
                for round_ in value["rounds"][1:]:
                    event=next(e for e in round_["night"] if e["slot"]=="mechanical_action")
                    event.update(action="unavailable",targets=[],result=None)
                    guard=next(e for e in round_["night"] if e["slot"]=="guard")
                    guard.update(action="pass",targets=[])
                    # Repeated rounds reuse event slots, not the sample's one
                    # global antidote.
                    save=next(e for e in round_["night"] if e["slot"]=="witch_save")
                    save.update(action="pass",targets=[])
                apply_derived_rules(value)
                validate(value, check_files=False)
                self.assertEqual(
                    [event["slot"] for event in value["rounds"][-1]["night"]],
                    [slot["code"] for slot in board["night_slots"]],
                )
                self.assertEqual(
                    [event["slot"] for event in value["rounds"][-1]["day"]],
                    [slot["code"] for slot in board["day_slots"]],
                )


if __name__ == "__main__":
    unittest.main()
