"""Voting extraction checks focus on lost/ambiguous ballots and round boundaries."""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import database
import voting_records as voting


def transcript(*lines):
    return [{"start_ms": t * 1000, "end_ms": t * 1000 + 900, "text": text} for t, text in lines]


def sample(lines):
    return voting.extract(transcript(*lines), {"slug": "voting-test", "rounds": [{"number": 1}]}, "data/test.json")


class VotingExtractionTests(unittest.TestCase):
    def test_target_is_not_reused_as_abstaining_voter(self):
        self.assertEqual(voting.choices("五号投给十一号七号弃票"), [
            {"voter": 5, "target": 11, "state": "cast"}, {"voter": 7, "target": None, "state": "abstained"}])
        self.assertEqual(voting.choices("十九号投给八号"), [])
        self.assertEqual(voting.choices("我觉得一号投给八号就能赢"), [])
        self.assertEqual(voting.choices("八号投给十号十九号，投给八号十号投给九号十二号投给八号"), [
            {"voter":8,"target":10,"state":"cast"}, {"voter":10,"target":9,"state":"cast"},
            {"voter":12,"target":8,"state":"cast"}])

    def test_long_segment_pk_and_cross_segment_votes_stay_separate(self):
        facts, audit = sample([
            (1, "321天亮了"), (2, "本游戏除一号十一号外其他玩家上警上警玩家请亮红灯"),
            (10, "警下玩家做好投票准备请从七号八号当中选出本局警长"),
            (11, "请出票一号投票给八号十一号投票给七号七号八号各一票平票PK八号玩家请发言"),
            (100, "PK发言结束请从七号八号当中选出本局警长"),
            (101, "321请出票"), (102, "一号投给"), (103, "八号二号投给七号投票结束"),
        ])
        self.assertEqual(len(facts["ballots"]), 2)
        first, second = facts["ballots"]
        self.assertEqual(first["tied_candidates"], [7, 8])
        self.assertEqual((second["kind"], second["number"], second["stage"]), ("sheriff", 2, "pk"))
        self.assertEqual([(v["voter"], v["target"]) for v in second["votes"]], [(1, 8), (2, 7)])
        self.assertIn("请出票", audit["evidence"][first["id"]][0]["quote"])

    def test_missing_choice_is_unknown_and_conflicting_choice_is_removed(self):
        facts, audit = sample([
            (1, "321天亮了"), (2, "本局游戏除一号二号三号外其他玩家上警上警玩家请亮红灯"),
            (10, "警上玩家七号八号请警下玩家做好投票准备"),
            (11, "321请出票"), (12, "一号投给七号"), (13, "二号投给二号弃票投票结束"),
        ])
        ballot = facts["ballots"][0]
        self.assertEqual(ballot["unrecorded_voters"], [2, 3])
        self.assertEqual(ballot["status"], "partial")
        self.assertEqual(len(ballot["votes"]), 1)
        self.assertTrue(audit["issues"])
        voting.validate(facts)

    def test_nightfall_without_dawn_still_separates_next_day(self):
        facts, audit = sample([
            (1, "321天亮了"), (2, "本游戏除一号外其他玩家上警上警玩家请亮红灯"),
            (10, "九号玩家选择自爆"), (11, "平安夜天黑请闭眼哦"),
            (200, "八号玩家选择自爆本局游戏警徽流失"), (201, "各位玩家天黑请闭眼"),
            (400, "警长请归票放逐投票准备321请出票"), (401, "一号投给十二号投票结束"),
        ])
        self.assertEqual([x["day"] for x in facts["interruptions"]], [1, 2])
        self.assertEqual(facts["ballots"][0]["day"], 3)
        self.assertEqual(len(audit["inferred_day_anchors_ms"]), 2)

    def test_abstention_validation_does_not_accept_unknown_target(self):
        facts, _ = sample([(1, "321请出票"), (2, "一号投给八号投票结束")])
        value = copy.deepcopy(facts)
        value["ballots"][0]["votes"][0]["target"] = None
        with self.assertRaises(database.ReviewError):
            voting.validate(value)

    def test_corrected_candidate_announcement_and_pk_pool_override_first_list(self):
        facts, _ = sample([
            (1,"321天亮了"),(2,"本游戏除九号十号外其他玩家上警上警玩家请亮红灯"),
            (10,"警上玩家四号等一下警上玩家四号五号八号请警下玩家投票准备"),
            (11,"在四号五号八号玩家中选出本局警长321请出票"),
            (12,"九号投给四号十号投给八号投票结束"),(13,"四号八号各一票平票PK"),
            (100,"请除四号八号外其他玩家戴盔在四号八号玩家中选出本局警长"),
            (101,"321请出票"),(102,"一号投给四号二号投给八号投票结束"),
        ])
        self.assertEqual(facts["ballots"][0]["candidates"],[4,5,8])
        self.assertEqual(facts["ballots"][1]["stage"],"pk")
        self.assertEqual(facts["ballots"][1]["candidates"],[4,8])

    def test_player_pk_hypothesis_does_not_turn_first_vote_into_revote(self):
        facts, _ = sample([
            (1,"321天亮了"),(2,"本游戏除九号十号外其他玩家上警上警玩家请亮红灯"),
            (10,"如果他起来跟我PK投完我不结束我也没意义"),
            (11,"所有玩家发言结束警长请归票四号321请出票"),
            (12,"一号投给四号四号投给八号投票结束四号玩家出局"),
        ])
        self.assertEqual(facts["ballots"][0]["stage"],"initial")
        self.assertEqual(len(facts["ballots"][0]["votes"]),2)

    def test_missing_pk_first_round_does_not_discard_votes(self):
        facts, _ = sample([
            (1,"321天亮了"),(2,"本游戏除九号十号外其他玩家上警上警玩家请亮红灯"),
            (10,"PK环节发言结束请除六号八号玩家外其余玩家带盔"),
            (11,"321请出票"),(12,"一号投给六号二号投给八号投票结束六号当选警长"),
        ])
        self.assertEqual(facts["ballots"][0]["stage"],"pk")
        self.assertEqual(len(facts["ballots"][0]["votes"]),2)

    def test_real_self_destruct_sequences_keep_two_days(self):
        import batch_s22 as batch
        for bvid, actors in (("BV1CSuN62Eey", [9,8]), ("BV1nBj664EFS", [8,4])):
            entry = batch.load_state()["items"][bvid]
            dossier = batch.read_json(batch.ROOT / entry["output_dir"] / "dossier.json")
            segments = batch.load_segments(batch.ROOT / entry["source_path"])
            facts, _ = voting.extract(segments, dossier, entry["source_path"])
            self.assertEqual([(x["actor"],x["day"]) for x in facts["interruptions"]], list(zip(actors,[1,2])))

    def test_player_recollection_does_not_add_an_extra_day(self):
        import batch_s22 as batch
        entry=batch.load_state()['items']['BV1BPNB6QE1s']
        dossier=batch.read_json(batch.ROOT/entry['output_dir']/'dossier.json')
        facts,_=voting.extract(batch.load_segments(batch.ROOT/entry['source_path']),dossier,entry['source_path'])
        self.assertEqual([b['day'] for b in facts['ballots']],[1,1,2,3])


@unittest.skipUnless((ROOT / ".secrets/database.json").is_file() or os.environ.get("DATABASE_URL"), "需要本地 PostgreSQL 配置")
class VotingDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "jcms_voting_test_" + uuid.uuid4().hex
        database.migrate(cls.schema)

    @classmethod
    def tearDownClass(cls):
        from psycopg import sql
        assert cls.schema.startswith("jcms_voting_test_")
        with database.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def test_reimport_is_idempotent_and_invalid_record_preserves_previous_votes(self):
        facts, _ = sample([
            (1, "321请出票"), (2, "一号投给八号十一号弃票投票结束"),
        ])
        facts["game_slug"] = "vote-" + uuid.uuid4().hex
        with patch.dict(os.environ, {"DATABASE_SCHEMA": self.schema}):
            with database.connect() as conn:
                conn.execute("INSERT INTO games(slug) VALUES(%s)", (facts["game_slug"],))
            voting.import_voting(facts)
            voting.import_voting(facts)
            broken = copy.deepcopy(facts)
            broken["ballots"][0]["votes"][0]["voter"] = 19
            with self.assertRaises(database.ReviewError):
                voting.import_voting(broken)
            with database.connect() as conn:
                self.assertEqual(conn.execute("SELECT count(*) n FROM game_ballots").fetchone()["n"], 1)
                self.assertEqual(conn.execute("SELECT count(*) n FROM game_ballot_choices").fetchone()["n"], 2)
                conn.execute("DELETE FROM games WHERE slug=%s", (facts["game_slug"],))
                self.assertEqual(conn.execute("SELECT count(*) n FROM game_ballot_choices").fetchone()["n"], 0)


if __name__ == "__main__":
    unittest.main()
