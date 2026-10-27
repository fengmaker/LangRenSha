"""Review conclusions must never hide an unrelated unresolved question."""
from copy import deepcopy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from s23_daily_audit import apply_events, apply_findings, recap_rows


class DailyAuditTests(unittest.TestCase):
    def test_resolves_one_question_and_preserves_the_other_for_user(self):
        finding = {'round': 1, 'phase': 'night', 'field': 'wolf_attack',
                   'title': '狼刀未知', 'status': 'unresolved', 'evidence': []}
        game = {'review': {'phase_findings': [dict(finding, id='a'), dict(finding, id='b')],
                           'human_questions': [], 'open_ai_followups': ['旧收尾事项']}}
        apply_findings(game, {'finding_resolutions': [{'id': 'a', 'status': 'inferred',
                                                     'conclusion': '首夜规则禁刀'}]})
        self.assertEqual(game['review']['phase_review_counts']['unresolved'], 1)
        self.assertEqual([q['id'] for q in game['review']['human_questions']], ['b'])
        self.assertEqual(game['review']['historical_ai_followups'], ['旧收尾事项'])

    def test_event_patch_preserves_before_and_does_not_touch_original_audit(self):
        event = {'slot': 'wolf_attack', 'actor': None, 'targets': [], 'action': 'unknown'}
        audit = {'event_patches': [{'round': 1, 'phase': 'night', 'slot': 'wolf_attack',
                                    'changes': {'action': 'forbidden'}}]}
        original = deepcopy(audit)
        game = {'dossier': {'rounds': [{'number': 1, 'night': [event], 'day': []}]}, 'review': {}}
        apply_events(game, audit)
        self.assertEqual(event['action'], 'forbidden')
        self.assertEqual(game['review']['daily_audit_changes'][0]['before']['action'], 'unknown')
        self.assertEqual(audit, original)

    def test_display_window_does_not_remove_the_full_source_rows(self):
        rows = [{'start_ms': 0, 'end_ms': 1000, 'text': '赛前'},
                {'start_ms': 5000, 'end_ms': 6000, 'text': '复盘'},
                {'start_ms': 9000, 'end_ms': 10000, 'text': '下一局'}]
        shown = recap_rows(rows, {'recap_window': {'start_ms': 5000, 'end_ms': 6000}})
        self.assertEqual([r['text'] for r in shown], ['复盘'])
        self.assertEqual(len(rows), 3)

    def test_unpublished_fact_remains_distinct_from_confirmed_fact(self):
        game = {'review': {'phase_findings': [{'id': 'a', 'round': 3, 'phase': 'night',
                            'title': '终局查验未知', 'field': 'seer_check', 'status': 'unresolved'}],
                           'human_questions': []}}
        apply_findings(game, {'finding_resolutions': [{'id': 'a', 'status': 'not_observed',
                              'conclusion': '录制未公布，继续保留未知'}]})
        self.assertEqual(game['review']['phase_review_counts']['not_observed'], 1)
        self.assertEqual(game['review']['phase_review_counts']['confirmed'], 0)
        self.assertEqual(game['review']['human_questions'], [])

    def test_question_and_timeline_alias_share_one_response_field(self):
        q = {'id': 'q1', 'round': 1, 'phase': 'day', 'question': '统计口径？', 'reason': ''}
        game = {'review': {'phase_findings': [{'id': 'question-q1', 'question_id': 'q1',
                            'round': 1, 'phase': 'day', 'field': 'counting',
                            'title': '统计口径？', 'status': 'unresolved'}], 'human_questions': [q]}}
        apply_findings(game, {'human_questions': [dict(q, id='question-q1')]})
        self.assertEqual([x['id'] for x in game['review']['human_questions']], ['q1'])

    def test_explicit_night_ending_hides_the_following_day(self):
        game = {'review': {'phase_findings': [], 'human_questions': []},
                'flow': {'terminal': None, 'display_phases': [
                    {'round': 3, 'phase': 'day'}, {'round': 4, 'phase': 'night'},
                    {'round': 4, 'phase': 'day'}]}}
        apply_findings(game, {'terminal_observation': {'round': 4, 'phase': 'night',
                                                      'reason': '法官明确宣布游戏结束'}})
        self.assertEqual(game['flow']['display_phases'][-1], {'round': 4, 'phase': 'night'})
        self.assertIsNone(game['flow']['theoretical_terminal'])
        self.assertEqual(game['flow']['terminal']['basis'], 'explicit_source_announcement')


if __name__ == '__main__':
    unittest.main()
