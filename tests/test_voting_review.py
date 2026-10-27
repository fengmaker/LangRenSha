"""Review metadata must flag uncertainty without inventing votes or verification."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / 'scripts'))
import review_s22_voting as review


def facts():
    return {"schema_version":1,"game_slug":"review-test","registrations":[],"interruptions":[],
            "days":[{"day":1,"sheriff":"unknown","exile":"recorded"}],
            "ballots":[{"id":"ballot-1","day":1,"kind":"exile","number":1,"stage":"initial","status":"partial",
                        "candidates":None,"eligible_voters":None,"tied_candidates":[],"winner":4,
                        "votes":[{"voter":1,"target":4,"state":"cast"}],"unrecorded_voters":None}]}


class VotingReviewTests(unittest.TestCase):
    def test_shared_death_gap_requests_source_once_instead_of_vote_arithmetic(self):
        value = facts()
        value['ballots'].append({**copy.deepcopy(value['ballots'][0]), 'id': 'ballot-2', 'day': 2})
        audit = {'issues': [], 'evidence': {'ballot-1': [], 'ballot-2': []},
                 'game_flow': {'rounds': [{'day': d, 'roster_gaps': [{'round': 1, 'slot': 'night_deaths'}]}
                                          for d in (1, 2)]}}
        result = review.audit_game({'bvid': 'BVtest', 'date': '2026-06-02', 'game_number': 1},
                                   value, audit, {'rounds': []})
        gaps = [q for q in result['questions'] if q['code'] == 'departure-night_deaths']
        self.assertEqual(len(gaps), 1)
        self.assertIn('ballot-1', gaps[0]['reason'])
        self.assertIn('ballot-2', gaps[0]['reason'])
        self.assertNotIn('eligibility_unknown', {q['code'] for q in result['questions']})

    def test_uncertainty_counts_match_questions_and_do_not_claim_human_review(self):
        value=facts();value['ballots'][0].update(day=None,kind='unknown')
        entry={'bvid':'BVtest','date':'2026-06-02','game_number':1}
        audit={'issues':[],'evidence':{'ballot-1':[{'path':'data/test.json','start_ms':1000,'end_ms':2000,'quote':'原文'}]}}
        result=review.audit_game(entry,value,audit,{'rounds':[]})
        self.assertFalse(result['human_reviewed'])
        self.assertEqual(result['question_count'],2)
        self.assertEqual(sum(x['question_count'] for x in result['days']),2)
        self.assertEqual({q['code'] for q in result['questions']},{'registration_missing','day_unknown','kind_unknown','eligibility_unknown'})

    def test_registration_does_not_assign_initial_police_voters_to_pk(self):
        value=facts()
        value['registrations']=[{'day':1,'on_police':list(range(2,13)),'off_police':[1]}]
        b=value['ballots'][0];b.update(kind='sheriff',stage='pk',candidates=[4,6])
        review.rebuild_days(value)
        self.assertIsNone(b['eligible_voters'])
        self.assertEqual(b['status'],'partial')
        b['stage']='initial'
        review.rebuild_days(value)
        self.assertEqual(b['eligible_voters'],[1])

    def test_review_correction_is_source_bound_and_rejects_stale_baseline(self):
        change={'id':'correction-1','bvid':'BVtest','source_sha256':'original','target':'ballot-1',
                'before':{'day':1},'after':{'day':3},'evidence':[]}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'accepted.json';path.write_text(json.dumps({'items':[change]}),encoding='utf-8')
            with patch.object(review,'CORRECTIONS',path),patch.object(review.batch,'digest',return_value='changed'):
                with self.assertRaisesRegex(ValueError,'转写已变化'):
                    review.apply_accepted(facts(),{'evidence':{'ballot-1':[]}}, {'bvid':'BVtest','source_path':'data/test.json'})
            with patch.object(review,'CORRECTIONS',path),patch.object(review.batch,'digest',return_value='original'):
                value=facts();value['ballots'][0]['day']=2
                with self.assertRaisesRegex(ValueError,'当前提取冲突'):
                    review.apply_accepted(value,{'evidence':{'ballot-1':[]}}, {'bvid':'BVtest','source_path':'data/test.json'})
                value=facts();audit={'evidence':{'ballot-1':[]},'issues':[]}
                review.apply_accepted(value,audit,{'bvid':'BVtest','source_path':'data/test.json'})
                self.assertEqual(value['ballots'][0]['day'],3)
                self.assertEqual(value['days'][-1]['day'],3)
                self.assertEqual(audit['review_changes'][0]['id'],'correction-1')


if __name__=='__main__':
    unittest.main()
