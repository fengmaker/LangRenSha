"""Regression checks for recap day alignment and peaceful tied days."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import batch_s22 as batch
import voting_records as voting
from review_s22_voting import apply_accepted
from voting_crosscheck import reconcile, day_outcomes


class VotingCrosscheckTests(unittest.TestCase):
    def load(self, bvid):
        entry = batch.load_state()["items"][bvid]
        dossier = batch.read_json(batch.ROOT / entry["output_dir"] / "dossier.json")
        facts, audit = voting.extract(batch.load_segments(batch.ROOT / entry["source_path"]), dossier, entry["source_path"])
        apply_accepted(facts, audit, entry)
        reconcile(facts, audit, dossier)
        return facts, audit, dossier

    def test_june_second_game_explosion_does_not_take_next_days_ballot(self):
        facts, audit, dossier = self.load("BV1CGVC6cE8T")
        self.assertEqual([(b["day"], b["winner"]) for b in facts["ballots"] if b["kind"] == "exile"], [(1, 4), (3, 12), (4, 9)])
        self.assertEqual(next(d["exile"] for d in facts["days"] if d["day"] == 2), "interrupted_self_destruct")
        voting.validate(facts)

    def test_double_tie_has_votes_but_no_exiled_player(self):
        facts, audit, dossier = self.load("BV1pGVC6cEbW")
        outcomes = day_outcomes(facts, audit, dossier)
        day = next(d for d in outcomes if d["day"] == 4)
        self.assertEqual(day["outcome"], "peaceful_tie")
        ballots = [b for b in facts["ballots"] if b["day"] == 4]
        self.assertEqual(len(ballots), 2)
        self.assertTrue(all(b["winner"] is None for b in ballots))
        self.assertEqual(ballots[-1]["tied_candidates"], [1, 11])

    def test_plain_ballot_title_does_not_imply_multiple_votes(self):
        b = {"day": 3, "kind": "exile", "stage": "initial", "number": 1}
        self.assertEqual(voting.ballot_stage_label(b, [b]), "")

    def test_unknown_result_never_infers_a_day_from_vote_majority(self):
        facts, audit, dossier = self.load("BV1CGVC6cE8T")
        ballot = facts["ballots"][2]
        ballot["day"], ballot["winner"] = None, None
        reconcile(facts, audit, dossier)
        self.assertIsNone(ballot["day"])
        self.assertIsNone(ballot["winner"])


if __name__ == "__main__":
    unittest.main()
