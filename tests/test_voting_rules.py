"""Confirmed election continuation and implicit abstention behavior."""
import copy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from voting_rules import apply_rules
from voting_records import validate


def action(slot, value, actor=None, targets=None):
    return {'slot':slot,'action':value,'actor':actor,'targets':targets or []}


def base(day=1, kind='sheriff', eligible=None):
    facts={'schema_version':1,'game_slug':'voting-rule-test',
           'registrations':[{'id':'registration-1','day':1,'on_police':[s for s in range(1,13) if s not in [2,5]],'off_police':[2,5]}],
           'ballots':[{'id':'ballot-1','day':day,'kind':kind,'number':1,'stage':'initial','status':'partial',
                       'candidates':[7,8],'eligible_voters':eligible,'votes':[{'voter':2,'target':7,'state':'cast'}],
                       'tied_candidates':[],'winner':None,'unrecorded_voters':None}],
           'interruptions':[],'days':[{'day':d,'sheriff':'unknown','exile':'unknown'} for d in range(1,4)]}
    dossier={'rounds':[{'number':d,'day':[action('night_deaths','peaceful'),action('exile_result','unknown'),action('self_destruct','unknown'),action('sheriff_result','unknown')], 'night':[]} for d in range(1,4)], 'seats':[]}
    return facts,{'evidence':{'ballot-1':[]},'issues':[]},dossier


def set_event(dossier, day, slot, value, actor=None, targets=None):
    r=dossier['rounds'][day-1]
    r['day']=[action(slot,value,actor,targets) if e['slot']==slot else e for e in r['day']]


class VotingRuleTests(unittest.TestCase):
    def test_missing_target_defaults_to_abstention_with_rule_basis(self):
        facts,audit,dossier=base()
        apply_rules(facts,audit,dossier)
        b=facts['ballots'][0]
        self.assertEqual(b['eligible_voters'],[2,5])
        self.assertEqual(b['votes'],[{'voter':2,'target':7,'state':'cast'},{'voter':5,'target':None,'state':'abstained'}])
        self.assertEqual(audit['rule_applications'][0]['voters'],[5])
        self.assertEqual(b['status'],'complete')
        validate(facts)
        before=copy.deepcopy((facts,audit))
        apply_rules(facts,audit,dossier)
        self.assertEqual((facts,audit),before)

    def test_day_two_continuation_keeps_original_off_police_voters(self):
        facts,audit,dossier=base(day=2)
        set_event(dossier,1,'self_destruct','self_destruct',actor=9)
        set_event(dossier,1,'sheriff_result','deferred')
        apply_rules(facts,audit,dossier)
        self.assertEqual(facts['days'][0]['sheriff'],'deferred')
        self.assertEqual(facts['ballots'][0]['eligible_voters'],[2,5])
        self.assertEqual(facts['days'][1]['sheriff'],'recorded')
        self.assertEqual(facts['days'][2]['sheriff'],'not_applicable')
        self.assertFalse(audit['rule_issues'])

    def test_second_day_self_destruct_loses_badge_and_never_delays_to_third(self):
        facts,audit,dossier=base(day=2)
        facts['ballots']=[]
        set_event(dossier,1,'self_destruct','self_destruct',actor=9)
        set_event(dossier,1,'sheriff_result','deferred')
        set_event(dossier,2,'self_destruct','self_destruct',actor=8)
        apply_rules(facts,audit,dossier)
        self.assertEqual([d['sheriff'] for d in facts['days']],['deferred','badge_lost','badge_lost'])
        self.assertEqual(facts['ballots'],[])

    def test_self_destruct_after_election_is_not_a_deferred_election(self):
        facts,audit,dossier=base()
        set_event(dossier,1,'self_destruct','self_destruct',actor=9)
        set_event(dossier,1,'sheriff_result','elected')
        apply_rules(facts,audit,dossier)
        self.assertEqual(facts['days'][1]['sheriff'],'not_applicable')
        self.assertEqual(audit['election_flow'],[])

    def test_day_two_without_first_day_interruption_is_flagged(self):
        facts,audit,dossier=base(day=2)
        apply_rules(facts,audit,dossier)
        self.assertIn('deferred_prerequisite',[i['code'] for i in audit['rule_issues']])

    def test_unknown_voter_roster_does_not_create_twelve_abstentions(self):
        facts,audit,dossier=base(day=3,kind='exile')
        facts['registrations']=[]
        apply_rules(facts,audit,dossier)
        self.assertIsNone(facts['ballots'][0]['eligible_voters'])
        self.assertEqual(len(facts['ballots'][0]['votes']),1)
        self.assertFalse(audit['rule_applications'])

    def test_known_departures_remove_ineligible_players_from_exile_votes(self):
        facts,audit,dossier=base(kind='exile')
        set_event(dossier,1,'night_deaths','die',targets=[4])
        apply_rules(facts,audit,dossier)
        b=facts['ballots'][0]
        self.assertNotIn(4,b['eligible_voters'])
        self.assertEqual(len(b['votes']),11)
        self.assertNotIn(4,[v['voter'] for v in b['votes']])

    def test_same_day_pk_and_next_day_continuation_remain_distinct(self):
        facts,audit,dossier=base()
        facts['ballots'][0]['stage']='pk'
        apply_rules(facts,audit,dossier)
        self.assertEqual(facts['ballots'][0]['eligible_voters'],[1,2,3,4,5,6,9,10,11,12])
        self.assertEqual(facts['days'][1]['sheriff'],'not_applicable')


if __name__=='__main__':unittest.main()
