"""Current game model integration tests in an isolated PostgreSQL schema."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

import psycopg
from psycopg import sql

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import database
from game_records import apply_derived_rules, import_game


class FixedGameDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema="jcms_fixed_test_"+uuid.uuid4().hex
        database.migrate(cls.schema)
        cls.value=json.loads((ROOT/"data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q/dossier.json").read_text(encoding="utf-8"))
        with database.connect(cls.schema) as conn:
            conn.execute("INSERT INTO seasons(code,name) VALUES('S22','synthetic test season')")
            for platform,key in {(f["platform"],f["external_key"]) for f in cls.value["files"]}:
                conn.execute("INSERT INTO sources(platform,external_key,title) VALUES(%s,%s,'synthetic test registry')",(platform,key))

    @classmethod
    def tearDownClass(cls):
        assert cls.schema.startswith("jcms_fixed_test_")
        with database.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def setUp(self):
        self.environment=patch.dict(os.environ,{"DATABASE_SCHEMA":self.schema})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.receipt=import_game(copy.deepcopy(self.value))

    def test_every_round_has_exactly_the_board_slots(self):
        with database.connect() as conn:
            rows=conn.execute("SELECT round_number,phase,count(*) AS n FROM game_event_records GROUP BY round_number,phase").fetchall()
            self.assertEqual(len(rows),6)
            self.assertTrue(all(r["n"]=={"night":8,"day":11}[r["phase"]] for r in rows))

    def test_commentator_and_player_can_be_the_same_person(self):
        value=copy.deepcopy(self.value)
        value["roster"][value["roster"].index("JY")]="桃子"
        value["seats"][6]["name"]="桃子"
        import_game(value)
        with database.connect() as conn:
            row=conn.execute("""SELECT s.person_id AS player,p.person_id AS commentator FROM game_seats s
                JOIN game_staff p ON p.game_id=s.game_id JOIN people n ON n.id=p.person_id
                WHERE s.seat_number=7 AND n.name='桃子' AND p.duty='commentator'""").fetchone()
            self.assertEqual(row["player"],row["commentator"])
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM people WHERE name='桃子'").fetchone()["n"],1)

    def test_repeat_import_does_not_duplicate_game_or_events(self):
        def count():
            with database.connect() as conn:
                return {t:conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(t))).fetchone()["n"]
                        for t in ["people","games","game_details","game_seats","game_staff","game_rounds","game_files","game_event_records","game_event_targets","game_event_effects"]}
        before=count()
        again=import_game(copy.deepcopy(self.value))
        self.assertEqual(before,count())
        self.assertEqual(again["game_id"],self.receipt["game_id"])

    def test_import_does_not_create_evidence_review_or_transcript_records(self):
        with database.connect() as conn:
            for table in ["game_revisions","extraction_runs","transcription_runs","transcript_segments","evidence_links","reviews"]:
                self.assertEqual(conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()["n"],0,table)
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM game_files").fetchone()["n"],7)

    def test_database_rejects_an_action_from_another_slot(self):
        with database.connect() as conn:
            with self.assertRaises(psycopg.Error):
                with conn.transaction():
                    conn.execute("UPDATE game_event_records SET action='self_destruct' WHERE phase='night' AND slot_code='guard'")

    def test_confirmed_names_random_point_and_hunter_states_are_stored(self):
        with database.connect() as conn:
            names=conn.execute("SELECT s.seat_number,p.name FROM game_seats s JOIN people p ON p.id=s.person_id ORDER BY s.seat_number").fetchall()
            self.assertEqual(len(names),12)
            self.assertEqual({r["seat_number"]:r["name"] for r in names if r["seat_number"] in {7,9,11,12}}, {7:"JY",9:"翼风",11:"申屠",12:"陈俊洁"})
            order=conn.execute("SELECT action,start_seat,random_point,speech_scope,direction FROM game_event_records WHERE round_number=1 AND slot_code='speech_order'").fetchone()
            self.assertEqual(dict(order),{"action":"order","start_seat":4,"random_point":3,"speech_scope":"sheriff","direction":"forward"})
            states=conn.execute("SELECT action FROM game_event_records WHERE slot_code='hunter_state' ORDER BY round_number").fetchall()
            self.assertEqual([r["action"] for r in states],["can_shoot"]*3)

    def test_poison_reflection_stores_original_target_and_witch_death_separately(self):
        value=copy.deepcopy(self.value)
        value["rounds"]=value["rounds"][:2]
        value["seats"][7].update(learning_target=5,learned_role="机械守卫")
        def event(n,phase,slot):
            return next(e for e in value["rounds"][n-1][phase] if e["slot"]==slot)
        event(1,"night","mechanical_action").update(targets=[5],result="机械守卫")
        event(2,"night","mechanical_action").update(action="guard",targets=[7])
        event(2,"night","witch_poison").update(action="poison",targets=[7])
        event(2,"day","night_deaths").update(targets=[1,10])
        apply_derived_rules(value)
        import_game(value)
        import_game(copy.deepcopy(value))
        with database.connect() as conn:
            effect=conn.execute("SELECT kind,intended_target,dead_seat,shield_actor FROM game_event_effects").fetchall()
            self.assertEqual([dict(e) for e in effect],[{"kind":"poison_reflected","intended_target":7,"dead_seat":10,"shield_actor":8}])
            state=conn.execute("SELECT action FROM game_event_records WHERE round_number=2 AND slot_code='hunter_state'").fetchone()
            self.assertEqual(state["action"],"can_shoot")
            with self.assertRaises(psycopg.Error):
                with conn.transaction():
                    conn.execute("UPDATE game_event_effects SET dead_seat=7 WHERE kind='poison_reflected'")
            for mutation in [
                "UPDATE game_event_effects SET intended_target=2 WHERE kind='poison_reflected'",
                "UPDATE game_event_effects SET shield_actor=5 WHERE kind='poison_reflected'",
                "UPDATE game_event_targets SET seat_number=2 WHERE event_id IN (SELECT id FROM game_event_records WHERE round_number=2 AND slot_code='mechanical_action')"
            ]:
                with self.assertRaises(psycopg.Error):
                    with conn.transaction():
                        conn.execute(mutation)
                        conn.execute("SET CONSTRAINTS ALL IMMEDIATE")


if __name__=="__main__":
    unittest.main()
