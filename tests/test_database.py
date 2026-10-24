"""Integration checks in an isolated temporary PostgreSQL schema, never pilot facts."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
HAS_DRIVER = importlib.util.find_spec("psycopg") is not None
if HAS_DRIVER:
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb
    import database


@unittest.skipUnless(HAS_DRIVER and (ROOT / '.secrets/database.json').exists(), '需要项目 PostgreSQL 和 psycopg 驱动')
class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = 'jcms_test_' + uuid.uuid4().hex
        database.migrate(cls.schema)

    @classmethod
    def tearDownClass(cls):
        assert cls.schema.startswith('jcms_test_')
        with database.connect() as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(cls.schema)))

    def setUp(self):
        self.conn = database.connect(self.schema)
        c = self.conn
        tag = uuid.uuid4().hex
        self.source = c.execute("INSERT INTO sources(platform,external_key,title) VALUES('other',%s,'synthetic test only') RETURNING id", (tag,)).fetchone()['id']
        self.season = c.execute("INSERT INTO seasons(code,name) VALUES(%s,'synthetic test only') RETURNING id", (tag,)).fetchone()['id']
        self.board = c.execute("""INSERT INTO rule_versions(code,kind,verified,definition) VALUES(%s,'board',true,%s) RETURNING id""",
                               (tag,Jsonb({'participant_count':2,'role_counts':{'villager':1,'werewolf':1},'result_mode':'faction'}))).fetchone()['id']
        self.scoring = c.execute("INSERT INTO rule_versions(code,kind,verified,definition) VALUES(%s,'scoring',true,'{}') RETURNING id", (tag+'s',)).fetchone()['id']
        self.period = c.execute("INSERT INTO scoring_periods(season_id,phase,rule_version_id) VALUES(%s,'finals_week',%s) RETURNING id", (self.season,self.scoring)).fetchone()['id']
        self.slug = 'synthetic-' + tag
        self.game = c.execute("INSERT INTO games(slug,season_id,primary_source_id) VALUES(%s,%s,%s) RETURNING id", (self.slug,self.season,self.source)).fetchone()['id']
        self.revision = c.execute("""INSERT INTO game_revisions(game_id,revision_no,event_date,phase,game_number,board_name,
            board_rule_id,expected_seats,is_extra_game,scoring_eligible,scoring_period_id,scope_confirmed,match_status,winning_faction)
            VALUES(%s,1,'2000-01-01','finals_week',1,'synthetic',%s,2,false,true,%s,true,'completed','good') RETURNING id""",
            (self.game,self.board,self.period)).fetchone()['id']
        self.players = [c.execute("INSERT INTO players(display_name) VALUES(%s) RETURNING id", ('synthetic '+str(i),)).fetchone()['id'] for i in [1,2]]
        for i in [0,1]:
            c.execute("""INSERT INTO game_participants(revision_id,seat_number,player_id,nickname_as_broadcast,role_code,
                opening_faction,settlement_faction,personal_result) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.revision,i+1,self.players[i],'synthetic','villager' if i==0 else 'werewolf',
                 'good' if i==0 else 'werewolf','good' if i==0 else 'werewolf','win' if i==0 else 'loss'))
        for key in ['scope','roster','roles','results','rules','scoring']:
            c.execute("INSERT INTO evidence_links(revision_id,source_id,field_key,locator) VALUES(%s,%s,%s,'synthetic fixture, not real evidence')", (self.revision,self.source,key))

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def fail_statement(self, statement, params):
        with self.assertRaises(psycopg.Error):
            with self.conn.transaction():
                self.conn.execute(statement,params)

    def approve(self):
        self.conn.execute("UPDATE game_revisions SET review_state='submitted' WHERE id=%s", (self.revision,))
        self.conn.execute("INSERT INTO reviews(revision_id,reviewer,review_type,decision,comment) VALUES(%s,'synthetic tester','manual_single','approved','test only')", (self.revision,))
        self.conn.execute("UPDATE game_revisions SET review_state='approved' WHERE id=%s", (self.revision,))

    def test_drafts_do_not_enter_public_statistics(self):
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM published_games WHERE game_id=%s', (self.game,)).fetchone()['n'],0)
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM player_basic_stats WHERE player_id=%s', (self.players[0],)).fetchone()['n'],0)

    def test_cannot_publish_an_unreviewed_revision(self):
        self.fail_statement('UPDATE games SET published_revision_id=%s WHERE id=%s', (self.revision,self.game))

    def test_duplicate_seat_and_player_are_rejected(self):
        self.fail_statement('INSERT INTO game_participants(revision_id,seat_number) VALUES(%s,1)', (self.revision,))
        self.fail_statement('INSERT INTO game_participants(revision_id,seat_number,player_id) VALUES(%s,3,%s)', (self.revision,self.players[0]))

    def test_missing_roster_cannot_be_approved(self):
        self.conn.execute('UPDATE game_participants SET player_id=NULL WHERE revision_id=%s AND seat_number=1', (self.revision,))
        self.fail_statement("UPDATE game_revisions SET review_state='submitted' WHERE id=%s", (self.revision,))

    def test_contradictory_outcome_is_rejected(self):
        self.conn.execute("UPDATE game_participants SET personal_result='loss' WHERE revision_id=%s AND seat_number=1", (self.revision,))
        self.fail_statement("UPDATE game_revisions SET review_state='submitted' WHERE id=%s", (self.revision,))

    def test_role_quotas_are_checked(self):
        self.conn.execute("UPDATE game_participants SET role_code='villager' WHERE revision_id=%s", (self.revision,))
        self.fail_statement("UPDATE game_revisions SET review_state='submitted' WHERE id=%s", (self.revision,))

    def test_unverified_scoring_rule_does_not_authorize_scoring(self):
        rule = self.conn.execute("INSERT INTO rule_versions(code,kind,verified,definition) VALUES(%s,'scoring',false,'{}') RETURNING id", (str(uuid.uuid4()),)).fetchone()['id']
        self.conn.execute('UPDATE scoring_periods SET rule_version_id=%s WHERE id=%s', (rule,self.period))
        self.fail_statement("UPDATE game_revisions SET review_state='submitted' WHERE id=%s", (self.revision,))

    def test_a_review_record_is_required_for_approval(self):
        self.conn.execute("UPDATE game_revisions SET review_state='submitted' WHERE id=%s", (self.revision,))
        self.fail_statement("UPDATE game_revisions SET review_state='approved' WHERE id=%s", (self.revision,))

    def test_approved_facts_and_rules_are_immutable(self):
        self.approve()
        self.fail_statement("UPDATE game_participants SET personal_result='loss' WHERE revision_id=%s", (self.revision,))
        self.fail_statement("UPDATE game_revisions SET board_name='changed' WHERE id=%s", (self.revision,))
        self.fail_statement("UPDATE rule_versions SET verified=false WHERE id=%s", (self.board,))
        self.fail_statement("UPDATE scoring_periods SET rule_version_id=NULL WHERE id=%s", (self.period,))

    def test_cross_game_publication_is_rejected(self):
        self.approve()
        other = self.conn.execute("INSERT INTO games(slug,season_id) VALUES(%s,%s) RETURNING id", ('other-'+self.slug,self.season)).fetchone()['id']
        self.fail_statement('UPDATE games SET published_revision_id=%s WHERE id=%s', (self.revision,other))

    def test_artifact_and_evidence_source_must_agree(self):
        source = self.conn.execute("INSERT INTO sources(platform,external_key) VALUES('other',%s) RETURNING id", (str(uuid.uuid4()),)).fetchone()['id']
        artifact = self.conn.execute("INSERT INTO artifacts(source_id,kind,relative_path,sha256,byte_size) VALUES(%s,'frame','synthetic.jpg',%s,1) RETURNING id", (source,'0'*64)).fetchone()['id']
        self.fail_statement("INSERT INTO evidence_links(revision_id,source_id,artifact_id,field_key,locator) VALUES(%s,%s,%s,'roles','fixture')", (self.revision,self.source,artifact))

    def test_publish_is_idempotent_and_withdraw_updates_stats(self):
        self.approve()
        self.conn.commit()
        with patch.dict(os.environ, {'DATABASE_SCHEMA':self.schema}):
            self.assertTrue(database.publish(self.slug,'synthetic tester')['changed'])
            self.assertFalse(database.publish(self.slug,'synthetic tester')['changed'])
            count = self.conn.execute('SELECT count(*) AS n FROM publication_events WHERE game_id=%s', (self.game,)).fetchone()['n']
            self.assertEqual(count,1)
            row = self.conn.execute('SELECT * FROM player_basic_stats WHERE player_id=%s', (self.players[0],)).fetchone()
            self.assertEqual((row['wins'],row['losses'],row['decided_games'],row['win_rate']),(1,0,1,1))
            self.assertTrue(database.publish(self.slug,'synthetic tester',withdraw=True,reason='test')['changed'])
            self.assertIsNone(self.conn.execute('SELECT * FROM player_basic_stats WHERE player_id=%s', (self.players[0],)).fetchone())

    def test_published_identity_cannot_be_reassigned(self):
        self.approve()
        self.conn.execute('UPDATE games SET published_revision_id=%s WHERE id=%s', (self.revision,self.game))
        self.fail_statement('UPDATE games SET season_id=NULL WHERE id=%s', (self.game,))
        self.fail_statement('UPDATE games SET primary_source_id=NULL WHERE id=%s', (self.game,))

    def test_migration_is_repeatable_without_recreating_tables(self):
        self.assertEqual(database.migrate(self.schema),[])

    def test_child_edit_locks_the_revision_before_submission(self):
        self.conn.commit()
        self.conn.execute('UPDATE game_participants SET nickname_as_broadcast=nickname_as_broadcast WHERE revision_id=%s', (self.revision,))
        other = database.connect(self.schema)
        try:
            other.execute("SET LOCAL lock_timeout='300ms'")
            with self.assertRaises(psycopg.errors.LockNotAvailable):
                other.execute("UPDATE game_revisions SET review_state='submitted' WHERE id=%s", (self.revision,))
            other.rollback()
        finally:
            other.close()

    def test_correction_draft_keeps_old_publication_and_copies_evidence(self):
        self.approve()
        self.conn.commit()
        with patch.dict(os.environ, {'DATABASE_SCHEMA':self.schema}):
            database.publish(self.slug,'synthetic tester')
            created = database.new_draft(self.slug,'synthetic tester')
            self.assertEqual(created['revision_no'],2)
            self.assertFalse(created['published_pointer_changed'])
            current = self.conn.execute('SELECT published_revision_id FROM games WHERE id=%s', (self.game,)).fetchone()
            self.assertEqual(current['published_revision_id'],self.revision)
            self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM game_participants WHERE revision_id=%s', (created['revision_id'],)).fetchone()['n'],2)
            self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM evidence_links WHERE revision_id=%s', (created['revision_id'],)).fetchone()['n'],6)
            with self.assertRaises(database.ReviewError):
                database.new_draft(self.slug,'synthetic tester')

    def test_new_scoring_rule_preserves_frozen_period(self):
        self.approve()
        code = 'synthetic-rule-'+uuid.uuid4().hex
        self.conn.execute("INSERT INTO rule_versions(code,kind,season_id,verified,definition) VALUES(%s,'scoring',%s,true,'{}')", (code,self.season))
        season = self.conn.execute('SELECT code FROM seasons WHERE id=%s', (self.season,)).fetchone()['code']
        self.conn.commit()
        with patch.dict(os.environ, {'DATABASE_SCHEMA':self.schema}):
            bound = database.bind_period(season,'finals_week',code,'synthetic tester')
            self.assertNotEqual(bound['scoring_period_id'],str(self.period))
            self.assertFalse(database.bind_period(season,'finals_week',code,'synthetic tester')['changed'])
        self.assertEqual(self.conn.execute('SELECT rule_version_id FROM scoring_periods WHERE id=%s', (self.period,)).fetchone()['rule_version_id'],self.scoring)

    def test_rule_import_requires_explicit_human_completion(self):
        self.conn.commit()
        season = self.conn.execute('SELECT code FROM seasons WHERE id=%s', (self.season,)).fetchone()['code']
        value = {'code':'synthetic-import-'+uuid.uuid4().hex,'kind':'board','season_code':season,
                 'source_id':str(self.source),'definition':{'participant_count':2,'role_counts':{'werewolf':1,'villager':1},'result_mode':'faction'},
                 'verified':True,'review_complete':False,'reviewer':'','evidence_locator':''}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DATABASE_SCHEMA':self.schema}):
            path = Path(folder)/'rule.json'
            path.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaises(database.ReviewError):
                database.import_rule(path)
            value.update(review_complete=True,reviewer='synthetic tester',evidence_locator='synthetic fixture only')
            path.write_text(json.dumps(value),encoding='utf-8')
            self.assertTrue(database.import_rule(path)['verified'])
            self.assertFalse(database.import_rule(path)['changed'])
            value['definition']['participant_count'] = 3
            path.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaises(database.ReviewError):
                database.import_rule(path)

    def test_weibo_import_keeps_partial_sources_separate_from_game_facts(self):
        self.conn.commit()
        value = {'source':'https://m.weibo.cn','status':'partial','posts':[
            {'post_id':'synthetic-'+uuid.uuid4().hex,'post_url':'https://m.weibo.cn/detail/synthetic','author_uid':'7525583841',
             'text':'synthetic fixture, not an actual post','raw_file':'posts/synthetic.json','images':[]}]}
        with tempfile.TemporaryDirectory(dir=ROOT/'data') as folder, patch.dict(os.environ, {'DATABASE_SCHEMA':self.schema}):
            path = Path(folder)/'manifest.json'
            (Path(folder)/'posts').mkdir()
            (Path(folder)/'posts/synthetic.json').write_text('{}',encoding='utf-8')
            path.write_text(json.dumps(value),encoding='utf-8')
            first = database.import_weibo(path)
            second = database.import_weibo(path)
            self.assertEqual(first['source_ids'],second['source_ids'])
            self.assertFalse(first['game_facts_changed'])
            row = self.conn.execute('SELECT metadata FROM sources WHERE id=%s', (first['source_ids'][0],)).fetchone()
            self.assertFalse(row['metadata']['facts_verified'])
            value['posts'] = []
            value['status'] = 'login_required'
            path.write_text(json.dumps(value),encoding='utf-8')
            self.assertEqual(database.import_weibo(path)['imported_posts'],0)

    def test_refreshing_input_does_not_overwrite_archived_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'data') as folder:
            path = Path(folder)/'metadata.json'
            first_text = json.dumps({'synthetic':uuid.uuid4().hex,'version':1})
            path.write_text(first_text,encoding='utf-8')
            first_id = database.artifact(self.conn,self.source,path,'metadata')
            stored = self.conn.execute('SELECT relative_path FROM artifacts WHERE id=%s', (first_id,)).fetchone()['relative_path']
            path.write_text('{"version":2}',encoding='utf-8')
            second_id = database.artifact(self.conn,self.source,path,'metadata')
            self.assertNotEqual(first_id,second_id)
            self.assertEqual((ROOT/stored).read_text(encoding='utf-8'),first_text)

    def test_raw_registration_is_independent_and_idempotent(self):
        from raw_media_fixture import make_media
        self.conn.commit()
        counts = lambda: {table:self.conn.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier(table))).fetchone()['n']
                          for table in ['sources','artifacts','transcription_runs','extraction_runs','games','game_revisions','players','published_games']}
        before = counts()
        with tempfile.TemporaryDirectory(dir=ROOT/'data') as folder,patch.dict(os.environ,{'DATABASE_SCHEMA':self.schema}):
            path = make_media(Path(folder),cid=int(uuid.uuid4().hex[:12],16))
            first = database.import_media(path)
            after_first = counts()
            second = database.import_media(path)
            self.assertEqual(first['source_id'],second['source_id'])
            self.assertEqual(after_first,counts())
            self.assertEqual(after_first['sources'],before['sources']+1)
            self.assertEqual(after_first['artifacts'],before['artifacts']+3)
            for table in ['transcription_runs','extraction_runs','games','game_revisions','players','published_games']:
                self.assertEqual(after_first[table],before[table])
            self.assertFalse(first['transcription_started'])
            self.assertFalse(first['game_facts_changed'])

    def test_invalid_raw_media_does_not_register_a_source(self):
        from raw_media_fixture import make_media
        self.conn.commit()
        before = self.conn.execute('SELECT count(*) AS n FROM sources').fetchone()['n']
        with tempfile.TemporaryDirectory(dir=ROOT/'data') as folder,patch.dict(os.environ,{'DATABASE_SCHEMA':self.schema}):
            path = make_media(Path(folder))
            (Path(folder)/'audio.m4a').write_bytes(b'bad')
            with self.assertRaises(database.MediaValidationError):
                database.import_media(path)
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM sources').fetchone()['n'],before)


if __name__ == '__main__':
    unittest.main()
