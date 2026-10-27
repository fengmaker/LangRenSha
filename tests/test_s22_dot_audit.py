import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import batch_s22
import s22_dot_audit


class S22DotAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patchset = s22_dot_audit.load_patchset()

    def test_reviewed_patchset_covers_each_candidate_and_preserves_the_single_hold(self):
        findings = self.patchset["findings"]
        self.assertEqual(len(findings), 101)
        self.assertEqual(sum(f["disposition"] == "applied" for f in findings), 100)
        held = [f["finding_id"] for f in findings if f["disposition"] == "held"]
        self.assertEqual(held, ["S22-A-027-02"])
        self.assertTrue(all(f.get("sources") for f in findings))

    def test_event_resolution_uses_round_number_instead_of_array_position(self):
        dossier = {"slug": "round-number-test", "rounds": [
            {"number": 2, "night": [{"slot": "seer_check", "result": "round-two"}]},
            {"number": 1, "night": [{"slot": "seer_check", "result": "round-one"}]},
        ]}
        event = s22_dot_audit._event(dossier, {"round": 1, "phase": "night", "slot": "seer_check"})
        self.assertEqual(event["result"], "round-one")

    def test_published_source_files_and_dependency_projections_are_current(self):
        result = s22_dot_audit.check_current_files()
        self.assertEqual(result["patches_pending"], 0, result["mismatches"])
        self.assertEqual(result["source_check"]["source_files_hash_matched"],
                         result["source_check"]["unique_source_files"])
        self.assertEqual(result["dependency_checks"]["dossier_hash_mismatches"], 0)
        self.assertEqual(result["dependency_checks"]["facts_mismatches"], 0)
        self.assertEqual(result["dependency_checks"]["flow_mismatches"], 0)
        self.assertEqual(result["dependency_checks"]["outcome_mismatches"], 0)
        self.assertEqual(result["dependency_checks"]["endgame_mismatches"], 0)

    def test_generated_dossier_and_voting_hooks_are_idempotent_on_patched_outputs(self):
        state = batch_s22.load_state()
        bvid = "BV18W8B6KE7C"
        entry = state["items"][bvid]
        folder = ROOT / entry["output_dir"]
        dossier = batch_s22.read_json(folder / "dossier.json")
        self.assertEqual(s22_dot_audit.apply_generated_dossier(copy.deepcopy(dossier), entry), [])
        voting = batch_s22.read_json(folder / "voting.json")
        audit = batch_s22.read_json(ROOT / "data/extractions/S22/voting" / f"{bvid}.json")
        self.assertEqual(s22_dot_audit.apply_generated_voting(copy.deepcopy(voting), copy.deepcopy(audit), entry), [])

    def test_unresolved_candidate_keeps_unknown_but_records_nano_support(self):
        item = next(f for f in self.patchset["findings"] if f["finding_id"] == "S22-A-027-02")
        self.assertEqual(item["disposition"], "held")
        self.assertEqual(item["patch"]["dossier"], [])
        self.assertEqual(item["candidate_value"]["targets"], [5])
        self.assertEqual(item["supplemental_sources"][0]["classification"],
                         "independent local ASR; machine_generated_unverified; not human audition")


if __name__ == "__main__":
    unittest.main()
