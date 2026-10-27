"""User-confirmed vote-control boundaries, independent of source extraction."""
import sys
from pathlib import Path
import unittest
from copy import deepcopy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from s23_phase_review import vote_totals, enrich


class VoteControlTests(unittest.TestCase):
    def seats(self,wolves=5,good=5):
        return ([{'seat':n,'role':'混血儿' if n==1 else '狼人','faction':'werewolf'} for n in range(1,wolves+1)]
                +[{'seat':n,'role':'平民','faction':'good'} for n in range(wolves+1,wolves+good+1)])

    def tally(self,w=5,g=5,holder=None,known=True):
        s=self.seats(w,g)
        return vote_totals(s,[x['seat'] for x in s],holder,known)

    def test_equal_heads_without_badge_controls_vote(self):
        row=self.tally()
        self.assertEqual((row['werewolf_votes'],row['good_votes'],row['controls_vote']),(5,5,True))

    def test_wolf_badge_and_wolf_mix_are_counted(self):
        row=self.tally(holder=2)
        self.assertEqual((row['werewolf_votes'],row['good_votes'],row['controls_vote']),(5.5,5,True))
        self.assertIn(1,row['werewolf_seats'])

    def test_equal_heads_with_good_badge_does_not_control(self):
        row=self.tally(holder=6)
        self.assertEqual((row['werewolf_votes'],row['good_votes'],row['controls_vote']),(5,5.5,False))

    def test_more_wolves_outvote_good_even_with_good_badge(self):
        self.assertTrue(self.tally(w=6,g=5,holder=7)['controls_vote'])

    def test_unknown_badge_at_parity_is_not_treated_as_no_badge(self):
        row=self.tally(known=False)
        self.assertIsNone(row['controls_vote'])
        self.assertIsNone(row['good_votes'])

    def test_unknown_victory_faction_keeps_vote_total_uncertain(self):
        s=self.seats();s[0]['faction']=None
        self.assertIsNone(vote_totals(s,list(range(1,11)))['controls_vote'])

    def test_badge_transfer_after_exile_does_not_change_the_vote_before_exile(self):
        def ev(slot,action,actor=None,targets=None):
            return {'slot':slot,'action':action,'actor':actor,'targets':targets or []}
        rounds=[{'number':1,'night':[],'day':[ev('sheriff_result','elected',targets=[6]),
                  ev('exile_result','exile',targets=[6]),ev('badge','transfer',6,[2])]},
                {'number':2,'night':[],'day':[ev('exile_result','exile',targets=[7])]}]
        ballots=[{'id':f'b{n}','day':n,'kind':'exile','stage':'initial','status':'complete',
                  'eligible_voters':living,'votes':[],'winner':target}
                 for n,living,target in [(1,list(range(1,11)),6),(2,[1,2,3,4,5,7,8,9,10],7)]]
        game={'entry':{'source_sha256':'test','source_path':'data/test.json'},
              'dossier':{'board':'mixed_blood','winner':'werewolf','seats':self.seats(),'rounds':rounds},
              'voting':{'registrations':[{'day':1}],'days':[{'day':1,'sheriff':'recorded'},{'day':2,'sheriff':'not_applicable'}],
                        'ballots':ballots},'review':{'phase_findings':[],'human_questions':[]},
              'presentation':{'rounds':rounds},'flow':{'terminal':None,'rounds':[
                  {'day':1,'night_deaths':[],'living_before_vote':list(range(1,11)),
                   'living_after_day':[1,2,3,4,5,7,8,9,10]},
                  {'day':2,'night_deaths':[],'living_before_vote':[1,2,3,4,5,7,8,9,10]}]}}
        enrich(game)
        first,second=game['vote_control']['phases']
        self.assertEqual((first['badge_holder'],first['werewolf_votes'],first['good_votes']),(6,5,5.5))
        self.assertEqual((second['badge_holder'],second['werewolf_votes'],second['good_votes']),(2,5.5,4))
        self.assertTrue(second['controls_vote'])
        self.assertIsNone(game['flow']['terminal'])
        self.assertEqual(len(game['voting']['ballots']),2)
        # An exiled sheriff tearing the badge also happens after this vote.
        rounds[0]['day'][-1]=ev('badge','destroy',6)
        game['review']['phase_findings']=[{'id':'announced-death','round':1,'phase':'night',
             'field':'rounds[1].day.night_deaths','status':'confirmed','title':'夜死公布'}]
        enrich(game)
        first,second=game['vote_control']['phases']
        self.assertEqual((first['badge_holder'],first['good_votes']),(6,5.5))
        self.assertEqual((second['badge_holder'],second['werewolf_votes'],second['good_votes']),(None,5,4))
        announcement=next(f for f in game['review']['phase_findings'] if f['id']=='announced-death')
        self.assertEqual((announcement['phase'],announcement['phase_label']),('day','第1天白天'))


class PhaseInferenceTests(unittest.TestCase):
    def game(self):
        def ev(slot,action,actor=None,targets=None):
            return {'slot':slot,'action':action,'actor':actor,'targets':targets or []}
        rounds=[{'number':1,'night':[ev('wolf_attack','attack',targets=[2]),
                  ev('witch_save','unknown',1),ev('witch_poison','unknown',1)],
                  'day':[ev('night_deaths','peaceful')]},
                {'number':2,'night':[ev('wolf_attack','attack',targets=[3]),
                  ev('witch_save','unknown',1)],'day':[ev('night_deaths','die',targets=[3])]}]
        return {'entry':{'source_sha256':'test','source_path':'data/test.json'},
                'dossier':{'board':'mixed_blood','winner':'good','seats':[
                    {'seat':n,'role':'女巫' if n==1 else '平民','faction':'good'} for n in range(1,13)],'rounds':rounds},
                'voting':{'registrations':[{'day':1}],'days':[],'ballots':[]},
                'review':{'phase_findings':[],'human_questions':[]},
                'presentation':{'rounds':deepcopy(rounds)},'flow':{'rounds':[
                    {'day':1,'night_deaths':[],'living_after_day':list(range(1,13))},
                    {'day':2,'night_deaths':[3]}]}}

    def test_surviving_knife_target_proves_antidote_and_later_spent_state(self):
        game=enrich(self.game())
        first,second=game['presentation']['rounds']
        save=next(e for e in first['night'] if e['slot']=='witch_save')
        self.assertEqual((save['action'],save['targets']),('save',[2]))
        self.assertTrue(save['inferred'])
        self.assertEqual(next(e for e in first['night'] if e['slot']=='witch_poison')['action'],'unavailable')
        self.assertEqual(next(e for e in second['night'] if e['slot']=='witch_save')['action'],'unavailable')
        self.assertEqual(game['dossier']['rounds'][0]['night'][1]['action'],'unknown')

    def test_exchange_board_or_unknown_death_does_not_prove_antidote(self):
        for change in ['exchange','unknown_death']:
            game=self.game()
            if change=='exchange':game['dossier']['board']='masquerade'
            else:game['dossier']['rounds'][0]['day'][0]['action']='unknown'
            enrich(game)
            save=next(e for e in game['presentation']['rounds'][0]['night'] if e['slot']=='witch_save')
            self.assertEqual(save['action'],'unknown')


if __name__=='__main__':unittest.main()
