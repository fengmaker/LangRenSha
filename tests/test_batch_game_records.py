"""Batch review records may retain unknown game facts without inventing values."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from game_records import ReviewError, ensure_person, import_game, validate


class BatchGameRecordTests(unittest.TestCase):
    def setUp(self):
        self.value = json.loads(
            (ROOT / "data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q/dossier.json").read_text(encoding="utf-8")
        )

    def incomplete(self):
        value = copy.deepcopy(self.value)
        mechanic = next(p for p in value["seats"] if p["role"] == "机械狼")
        mechanic.update(role=None, faction=None, learning_target=None, learned_role=None)
        unnamed = value["seats"][0]
        old_name = unnamed["name"]
        unnamed.update(name=None, role=None, faction=None)
        value["roster"].remove(old_name)
        value["commentators"] = []
        value["referee"] = None
        value["game_number"] = None
        value["winner"] = "third_party"
        value["season"] = "S21"  # Generic archival storage, outside S22 formal policy.
        return value

    def template_record(self, board_code):
        value = copy.deepcopy(self.value)
        value["board"] = board_code
        value["roster"] = []
        value["commentators"] = []
        value["referee"] = None
        value["game_number"] = None
        value["winner"] = None
        for seat in value["seats"]:
            seat.update(name=None, role=None, faction=None, learning_target=None, learned_role=None)

        def blank_event(slot):
            return {
                "slot": slot,
                "action": "unknown",
                "actor": None,
                "targets": [],
                "result": None,
                "start_seat": None,
                "direction": None,
                "votes": [],
                "random_point": None,
                "speech_scope": None,
                "availability": None,
                "effects": [],
            }

        board = json.loads((ROOT / f"config/board_templates/{board_code}.json").read_text(encoding="utf-8"))
        value["rounds"] = [{
            "number": 1,
            "night": [blank_event(slot["code"]) for slot in board["night_slots"]],
            "day": [blank_event(slot["code"]) for slot in board["day_slots"]],
        }]
        if board_code in {"masquerade", "all_in", "treasure_master"}:
            second = copy.deepcopy(value["rounds"][0])
            second["number"] = 2
            value["rounds"].append(second)
        return value

    @staticmethod
    def event(value, slot):
        return next(
            event
            for round_ in reversed(value["rounds"])
            for phase in ("night", "day")
            for event in round_[phase]
            if event["slot"] == slot
        )

    def test_batch_accepts_unknown_seat_data_and_optional_game_metadata(self):
        value = self.incomplete()
        board = validate(value, check_files=False, allow_incomplete=True)
        self.assertEqual(board["seat_count"], 12)

    def test_batch_accepts_no_rounds_without_creating_a_placeholder_round(self):
        value = self.incomplete()
        value["rounds"] = []
        self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["seat_count"], 12)

    def test_default_validation_keeps_the_confirmed_record_requirements(self):
        self.assertEqual(validate(copy.deepcopy(self.value), check_files=False)["code"], self.value["board"])
        value = self.incomplete()
        with self.assertRaises(ReviewError):
            validate(value, check_files=False)
        with self.assertRaises(ReviewError):
            validate(value, check_files=False, allow_incomplete=False)

    def test_batch_caps_known_roles_at_static_template_counts(self):
        value = copy.deepcopy(self.value)
        value["seats"][0].update(role="平民", faction="good")
        with self.assertRaisesRegex(ReviewError, "超过版型"):
            validate(value, check_files=False, allow_incomplete=True)

    def test_batch_keeps_known_actor_role_validation(self):
        value = copy.deepcopy(self.value)
        wolf = next(p["seat"] for p in value["seats"] if p["role"] == "狼人")
        villager = next(p["seat"] for p in value["seats"] if p["role"] == "平民")
        attack = next(e for e in value["rounds"][0]["night"] if e["slot"] == "wolf_attack")
        attack["actor"] = villager
        self.assertNotEqual(attack["actor"], wolf)
        with self.assertRaisesRegex(ReviewError, "狼刀行动者必须属于狼队"):
            validate(value, check_files=False, allow_incomplete=True)

    def test_batch_allows_an_unknown_actor_to_remain_null(self):
        value = copy.deepcopy(self.value)
        guard = next(e for e in value["rounds"][0]["night"] if e["slot"] == "guard")
        guard["actor"] = None
        self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["seat_count"], 12)

    def test_batch_keeps_target_duplicate_validation(self):
        value = copy.deepcopy(self.value)
        guard = next(e for e in value["rounds"][0]["night"] if e["slot"] == "guard")
        guard["targets"] = [2, 2]
        with self.assertRaisesRegex(ReviewError, "目标座位重复或越界"):
            validate(value, check_files=False, allow_incomplete=True)

    def test_batch_accepts_new_template_actions_with_slot_specific_target_counts(self):
        cases = [
            ("mixed_blood", {"mixed_blood_model": ("choose", [5])}),
            ("guile_realm", {
                "magician_exchange": ("exchange", [2, 9]),
                "guile_exchange": ("exchange", [1, 8]),
            }),
            ("masquerade", {
                "masquerade_verify": ("verify", [6]),
                "masquerade_mask": ("give_mask", [3]),
                "dancer_dance": ("dance", [2, 5, 11]),
            }),
            ("all_in", {"warden_trade_targets": ("select_pair", [3, 7])}),
            ("ghost_bride", {
                "ghost_bride_select_groom": ("choose", [4]),
                "couple_select_witness": ("choose", [10]),
            }),
        ]
        for board_code, actions in cases:
            with self.subTest(board=board_code):
                value = self.template_record(board_code)
                for slot, (action, targets) in actions.items():
                    event = self.event(value, slot)
                    event.update(action=action, targets=targets)
                self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["code"], board_code)

    def test_masquerade_minority_resolution_preserves_the_departing_seat(self):
        value = self.template_record("masquerade")
        self.event(value, "dancer_dance").update(action="dance", targets=[1, 7, 12])
        self.event(value, "dance_resolution").update(action="minority_dies", targets=[7])
        self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["code"], "masquerade")

    def test_masquerade_resolution_rejects_multiple_minority_departures(self):
        value = self.template_record("masquerade")
        self.event(value, "dance_resolution").update(action="minority_dies", targets=[1, 7])
        with self.assertRaises(ReviewError):
            validate(value, check_files=False, allow_incomplete=True)

    def test_masked_delayed_death_preserves_the_departing_seat(self):
        value = self.template_record("treasure_master")
        self.event(value, "masked_delayed_death").update(action="die_after_speech", actor=3, targets=[3])
        self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["code"], "treasure_master")

    def test_wolf_aligned_treasure_master_can_execute_the_ordinary_wolf_attack(self):
        value = self.template_record("treasure_master")
        value["seats"][0].update(role="盗宝大师", faction="werewolf")
        self.event(value, "wolf_attack").update(action="attack", actor=1, targets=[4])
        self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["code"], "treasure_master")
        value["seats"][0]["faction"] = "good"
        with self.assertRaisesRegex(ReviewError, "狼刀行动者必须属于狼队"):
            validate(value, check_files=False, allow_incomplete=True)

    def test_number_swap_cannot_be_encoded_as_direct_poison_death(self):
        value = self.template_record("guile_realm")
        self.event(value, "witch_poison").update(action="poison", targets=[1], effects=[{
            "kind": "poison_death", "intended_target": 1, "dead_seat": 8, "shield_actor": None,
        }])
        with self.assertRaisesRegex(ReviewError, "技能结算类型"):
            validate(value, check_files=False, allow_incomplete=True)

    def test_batch_trade_resolution_targets_follow_the_outcome(self):
        value = self.template_record("all_in")
        for action, targets in (
            ("betrayal_death", [5]),
            ("mutual_targets", [2, 9]),
            ("warden_self_trade", [7]),
        ):
            with self.subTest(action=action):
                event = self.event(value, "trade_resolution")
                event.update(action=action, targets=targets)
                self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["code"], "all_in")

        self.event(value, "trade_resolution").update(action="betrayal_death", targets=[1, 2])
        with self.assertRaises(ReviewError):
            validate(value, check_files=False, allow_incomplete=True)

    def test_batch_enforces_each_new_action_target_cardinality(self):
        cases = [
            ("guile_realm", "magician_exchange", "exchange", [2]),
            ("guile_realm", "guile_exchange", "exchange", [2, 8, 10]),
            ("masquerade", "masquerade_verify", "verify", [2, 3]),
            ("masquerade", "masquerade_mask", "give_mask", []),
            ("masquerade", "dancer_dance", "dance", [1, 5]),
            ("masquerade", "dancer_dance", "dance", [1, 4, 7, 9]),
            ("mixed_blood", "mixed_blood_model", "choose", []),
        ]
        for board_code, slot, action, targets in cases:
            with self.subTest(board=board_code, slot=slot, targets=targets):
                value = self.template_record(board_code)
                self.event(value, slot).update(action=action, targets=targets)
                with self.assertRaises(ReviewError):
                    validate(value, check_files=False, allow_incomplete=True)

    def test_batch_rejects_targets_for_unknown_pass_and_unavailable_actions(self):
        for action in ("unknown", "pass", "unavailable"):
            with self.subTest(action=action):
                value = self.template_record("guile_realm")
                self.event(value, "magician_exchange").update(action=action, targets=[2, 8])
                with self.assertRaisesRegex(ReviewError, "不能填写操作目标"):
                    validate(value, check_files=False, allow_incomplete=True)

    def test_treasure_choice_uses_a_valid_role_result_and_no_seat_target(self):
        value = self.template_record("treasure_master")
        self.event(value, "treasure_choice").update(action="choose", result="通灵师")
        self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["code"], "treasure_master")

        for result, targets in (("未知角色", []), ("通灵师", [5])):
            with self.subTest(result=result, targets=targets):
                invalid = self.template_record("treasure_master")
                self.event(invalid, "treasure_choice").update(action="choose", result=result, targets=targets)
                with self.assertRaises(ReviewError):
                    validate(invalid, check_files=False, allow_incomplete=True)

    def test_vote_actions_still_require_per_person_ballots(self):
        value = self.template_record("all_in")
        vote = self.event(value, "exile_vote")
        vote.update(action="vote", votes=[{"round": 1, "voter": 2, "target": 7, "abstained": False}])
        self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["code"], "all_in")

        vote["votes"] = []
        with self.assertRaisesRegex(ReviewError, "需要逐人票型"):
            validate(value, check_files=False, allow_incomplete=True)

    def test_dynamic_role_template_does_not_apply_static_role_caps(self):
        value = copy.deepcopy(self.value)
        actor_seats = {
            event["actor"]
            for round_ in value["rounds"]
            for phase in ("night", "day")
            for event in round_[phase]
            if event["actor"] is not None
        }
        candidate = next(p for p in value["seats"] if p["seat"] not in actor_seats)
        candidate.update(role="盗宝人", faction="third_party")
        board = json.loads((ROOT / "config/board_templates/mechanical_wolf_seer.json").read_text(encoding="utf-8"))
        board.update(role_counts={}, dynamic_roles=True)
        with patch("game_records.template", return_value=board):
            self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["seat_count"], 12)

    def test_special_wolf_and_third_party_factions_are_not_guessed_as_good(self):
        value = copy.deepcopy(self.value)
        actor_seats = {
            event["actor"]
            for round_ in value["rounds"]
            for phase in ("night", "day")
            for event in round_[phase]
            if event["actor"] is not None
        }
        candidate = next(p for p in value["seats"] if p["seat"] not in actor_seats)
        board = json.loads((ROOT / "config/board_templates/mechanical_wolf_seer.json").read_text(encoding="utf-8"))
        board.update(role_counts={}, dynamic_roles=True)
        with self.subTest(role="狼王"):
            candidate.update(role="狼王", faction="good")
            with patch("game_records.template", return_value=board):
                with self.assertRaisesRegex(ReviewError, "身份与阵营不一致"):
                    validate(value, check_files=False, allow_incomplete=True)
        with self.subTest(role="鬼魂新娘"):
            candidate.update(role="鬼魂新娘", faction="good")
            with patch("game_records.template", return_value=board):
                with self.assertRaisesRegex(ReviewError, "身份与阵营不一致"):
                    validate(value, check_files=False, allow_incomplete=True)

    def test_special_wolf_is_a_valid_wolf_team_actor(self):
        value = copy.deepcopy(self.value)
        actor_seats = {
            event["actor"]
            for round_ in value["rounds"]
            for phase in ("night", "day")
            for event in round_[phase]
            if event["actor"] is not None
        }
        candidate = next(p for p in value["seats"] if p["seat"] not in actor_seats)
        candidate.update(role="狼王", faction="werewolf")
        attack = next(e for e in value["rounds"][0]["night"] if e["slot"] == "wolf_attack")
        attack["actor"] = candidate["seat"]
        board = json.loads((ROOT / "config/board_templates/mechanical_wolf_seer.json").read_text(encoding="utf-8"))
        board.update(role_counts={}, dynamic_roles=True)
        with patch("game_records.template", return_value=board):
            self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["seat_count"], 12)

    def test_batch_allows_one_sided_mechanical_learning_information(self):
        for known_field in ("learned_role", "learning_target"):
            with self.subTest(known_field=known_field):
                value = copy.deepcopy(self.value)
                mechanic = next(p for p in value["seats"] if p["role"] == "机械狼")
                if known_field == "learned_role":
                    mechanic.update(learning_target=None, learned_role="机械女巫")
                else:
                    target = next(p["seat"] for p in value["seats"] if p["seat"] != mechanic["seat"])
                    mechanic.update(learning_target=target, learned_role=None)
                learn = next(
                    e for round_ in value["rounds"] for e in round_["night"]
                    if e["slot"] == "mechanical_action" and e["action"] == "learn"
                )
                learn.update(action="unknown", targets=[], result=None)
                self.assertEqual(validate(value, check_files=False, allow_incomplete=True)["seat_count"], 12)

    def test_batch_checks_a_fully_known_mechanical_target_and_form(self):
        value = copy.deepcopy(self.value)
        mechanic = next(p for p in value["seats"] if p["role"] == "机械狼")
        target = next(p for p in value["seats"] if p["role"] == "女巫")
        mechanic.update(learning_target=target["seat"], learned_role="机械通灵师")
        with self.assertRaisesRegex(ReviewError, "学习形态与学习目标身份不一致"):
            validate(value, check_files=False, allow_incomplete=True)
        mechanic.update(learning_target=99, learned_role=None)
        with self.assertRaisesRegex(ReviewError, "学习目标越界"):
            validate(value, check_files=False, allow_incomplete=True)

    def test_strict_mode_still_requires_complete_mechanical_learning_pair(self):
        value = copy.deepcopy(self.value)
        mechanic = next(p for p in value["seats"] if p["role"] == "机械狼")
        mechanic.update(learning_target=None, learned_role="机械女巫")
        with self.assertRaises(ReviewError):
            validate(value, check_files=False)

    def test_ensure_person_refuses_unknown_names_before_writing(self):
        class Connection:
            def execute(self, *args, **kwargs):
                raise AssertionError("must not write a null person")

        with self.assertRaises(ReviewError):
            ensure_person(Connection(), None)

    def test_batch_import_skips_unknown_referee_and_keeps_unknowns_null(self):
        class Result:
            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        class Connection:
            def __init__(self):
                self.queries = []
                self.next_person = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, params=()):
                statement = " ".join(query.split())
                self.queries.append((statement, params))
                if statement.startswith("SELECT id FROM seasons"):
                    return Result({"id": "season-id"})
                if statement.startswith("SELECT id FROM sources"):
                    return Result({"id": "source-id"})
                if statement.startswith("INSERT INTO games"):
                    return Result({"id": "game-id"})
                if statement.startswith("INSERT INTO people"):
                    self.next_person += 1
                    return Result({"id": f"person-{self.next_person}"})
                if statement.startswith("INSERT INTO game_event_records"):
                    return Result({"id": "event-id"})
                return Result()

        conn = Connection()
        value = self.incomplete()
        value["rounds"] = []
        with patch("game_records.connect", return_value=conn), \
             patch("game_records.artifact", return_value="artifact-id"), \
             patch("game_records.data_file", return_value=Path("synthetic")):
            import_game(value, allow_incomplete=True)

        people = [params for query, params in conn.queries if query.startswith("INSERT INTO people")]
        staff = [params for query, params in conn.queries if query.startswith("INSERT INTO game_staff")]
        seats = [params for query, params in conn.queries if query.startswith("INSERT INTO game_seats")]
        details = [params for query, params in conn.queries if query.startswith("INSERT INTO game_details")]
        forbidden = ("game_revisions", "evidence_links", "reviews", "transcription_runs")
        self.assertTrue(people)
        self.assertTrue(all(params[0] is not None for params in people))
        self.assertEqual(staff, [])
        self.assertTrue(any(params[3] is None and params[4] is None for params in seats))
        self.assertEqual(details[0][-2:], (None, "third_party"))
        self.assertFalse(any(any(table in query for table in forbidden) for query, _ in conn.queries))


if __name__ == "__main__":
    unittest.main()
