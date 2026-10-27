"""Survivors and terminal nights must drive voting coverage."""
from pathlib import Path
import copy
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import batch_s22 as batch
from voting_rules import apply_rules, ballot_living_seats
from game_flow import replay, collect_death_announcements


class GameFlowTests(unittest.TestCase):
    def load_june_three(self):
        entry = batch.load_state()["items"]["BV1hb7R6XEtD"]
        folder = batch.ROOT / entry["output_dir"]
        return (batch.read_json(folder / "voting.json"),
                batch.read_json(batch.ROOT / "data/extractions/S22/voting/BV1hb7R6XEtD.json"),
                batch.read_json(folder / "dossier.json"))

    def test_june_three_survivors_determine_both_exile_rosters(self):
        facts, audit, dossier = self.load_june_three()
        apply_rules(facts, audit, dossier)
        self.assertEqual(ballot_living_seats(dossier, 3), [1, 2, 3, 4, 5, 9, 10, 12])
        self.assertEqual(ballot_living_seats(dossier, 4), [2, 3, 4, 5, 9])
        self.assertTrue(all(b["status"] == "complete" for b in facts["ballots"]))

    def test_june_three_terminal_night_does_not_create_day_five(self):
        facts, audit, dossier = self.load_june_three()
        apply_rules(facts, audit, dossier)
        self.assertEqual([d["day"] for d in facts["days"]], [1, 2, 3, 4])
        self.assertEqual(audit["game_flow"]["terminal"], {
            "round": 5, "phase": "night", "after_day": 4,
            "winner": "werewolf", "eliminated_side": "civilian"})

    def test_exiled_hunter_shoots_after_current_ballot(self):
        _, _, dossier = self.load_june_three()
        dossier = copy.deepcopy(dossier)
        r = dossier["rounds"][2]
        for e in r["day"]:
            if e["slot"] == "exile_result":
                e.update(action="exile", targets=[3])
            if e["slot"] == "hunter_shot":
                e.update(action="shoot", actor=3, targets=[5])
        self.assertIn(5, ballot_living_seats(dossier, 3) or [])
        self.assertNotIn(5, ballot_living_seats(dossier, 4) or [])

    def test_terminal_night_does_not_hide_a_conflicting_actual_ballot(self):
        facts, _, dossier = self.load_june_three()
        facts["ballots"].append({**facts["ballots"][-1], "id": "contradiction", "day": 5})
        flow = replay(dossier, facts)
        self.assertIsNone(flow["terminal"])
        self.assertEqual(flow["issues"][0]["code"], "terminal_conflict")

    def test_pk_excludes_only_candidates_from_actual_survivors(self):
        facts, audit, dossier = self.load_june_three()
        b = facts["ballots"][1]
        b.update(stage="pk", candidates=[2, 5], votes=[{"voter": 3, "target": 2, "state": "cast"}], eligible_voters=None)
        apply_rules(facts, audit, dossier)
        self.assertEqual(b["eligible_voters"], [3, 4, 9])
        self.assertEqual(len(b["votes"]), 3)
        self.assertEqual(audit["eligibility_derivations"][-1]["living_count"], 5)

    def test_guarded_attack_is_not_promoted_to_a_death(self):
        _, _, dossier = self.load_june_three()
        dossier["board"] = "mechanical_wolf_seer"
        self.assertIsNone(replay(dossier)["rounds"][0]["night_deaths"])

    def test_judge_report_requires_a_unique_day_and_keeps_its_source(self):
        rows = [{"start_ms": 1000, "end_ms": 2000, "text": "昨夜8号玩家倒牌，没有遗言，是否发动技能"}]
        facts = {"ballots": [{"id": "b", "day": 3}], "interruptions": []}
        audit = {"source_path": "data/test.json", "evidence": {"b": [{"start_ms": 3000}]}}
        dossier = {"rounds": [{"number": 3, "day": [{"slot": "night_deaths", "action": "unknown"}], "night": []}]}
        reports = collect_death_announcements(rows, dossier, facts, audit)
        self.assertEqual([(r["day"], r["targets"]) for r in reports], [(3, [8])])
        self.assertEqual(reports[0]["evidence"][0]["path"], "data/test.json")
        facts["ballots"].append({"id": "c", "day": 4})
        audit["evidence"]["c"] = [{"start_ms": 4000}]
        self.assertEqual(collect_death_announcements(rows, dossier, facts, audit), [])

    def test_same_night_both_victory_conditions_settle_for_wolves(self):
        entry = batch.load_state()['items']['BV1sYEo6QEyS']
        dossier = batch.read_json(batch.ROOT/entry['output_dir']/'dossier.json')
        for e in dossier['rounds'][1]['day']:
            if e['slot'] == 'night_deaths':
                e.update(action='die', targets=[3])
        terminal = replay(dossier)['terminal']
        self.assertIsNotNone(terminal)
        self.assertEqual((terminal['round'], terminal['phase'], terminal['winner']), (3, 'night', 'werewolf'))

    def test_after_speech_death_is_a_daytime_terminal(self):
        _, _, dossier = self.load_june_three()
        final = dossier['rounds'][-1]
        for e in final['day']:
            if e['slot'] == 'night_deaths':
                e.update(action='peaceful', targets=[])
        final['day'].append({'slot':'masked_delayed_death','action':'die_after_speech','actor':9,'targets':[9]})
        terminal = replay(dossier)['terminal']
        self.assertEqual((terminal['round'],terminal['phase'],terminal['after_day']),(5,'day',5))


if __name__ == "__main__":
    unittest.main()
