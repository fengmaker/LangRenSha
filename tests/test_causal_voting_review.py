"""Contextual decisions must remain source-bound and preserve residual doubts."""
from pathlib import Path
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import causal_voting_review as causal


class CausalReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'source.json').write_text('original source', encoding='utf8')
        self.entry = {'bvid': 'BVtest', 'source_path': 'source.json'}
        self.decision = {'question_id': 'vote-BVtest-ballot-1-stage_unknown', 'resolved': True,
                         'confidence': 'medium', 'conclusion': '技能重投', 'reason': '翻牌后明确重新投票。'}
        self.item = {'bvid': 'BVtest', 'source_sha256': hashlib.sha256(b'original source').hexdigest(),
                     'decisions': [self.decision], 'patches': []}
        self.report = self.root/'accepted.json'
        self.report.write_text(json.dumps({'items': [self.item]}), encoding='utf8')
        self.patches = [patch.object(causal, 'ROOT', self.root), patch.object(causal, 'REVIEW', self.report)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def save(self):
        self.report.write_text(json.dumps({'items': [self.item]}), encoding='utf8')

    def test_changed_source_rejects_contextual_correction(self):
        (self.root/'source.json').write_text('different source', encoding='utf8')
        with self.assertRaisesRegex(ValueError, '转写已变化'):
            causal.load(self.entry)

    def test_resolved_inference_does_not_clear_another_question(self):
        other = {'id': 'vote-BVtest-ballot-1-source_conflict-12345678', 'reason': 'ambiguous'}
        questions = [{'id': self.decision['question_id']}, other]
        remaining, decisions = causal.disposition(questions, {'causal_review': self.item})
        self.assertEqual(remaining, [other])
        self.assertEqual(len(decisions), 1)

    def test_user_confirmation_remains_bound_to_its_original_record(self):
        record = self.root / 'confirmation.txt'
        record.write_bytes(b'user confirmed the seven votes')
        self.item['user_confirmation'] = {'path': 'confirmation.txt', 'sha256': hashlib.sha256(record.read_bytes()).hexdigest()}
        self.save()
        self.assertEqual(causal.load(self.entry)['user_confirmation'], self.item['user_confirmation'])
        record.write_bytes(b'different confirmation')
        with self.assertRaisesRegex(ValueError, '人工确认记录已变化'):
            causal.load(self.entry)

    def test_unresolved_decision_keeps_a_specific_manual_reason(self):
        self.decision.update(resolved=False, confidence='low', residual_reason='两个号码均与后续过程相容，不能选定。')
        remaining, _ = causal.disposition([{'id': self.decision['question_id']}], {'causal_review': self.item})
        self.assertTrue(remaining[0]['manual_required'])
        self.assertEqual(remaining[0]['reason'], self.decision['residual_reason'])

    def test_low_confidence_cannot_silently_mark_a_question_resolved(self):
        self.decision['confidence'] = 'low'
        self.save()
        with self.assertRaisesRegex(ValueError, '置信度不合法'):
            causal.load(self.entry)

    def test_ballot_patch_replays_and_rejects_changed_baseline(self):
        self.item['patches'] = [{'kind': 'ballot', 'id': 'ballot-1', 'before': {'stage': 'unknown'},
                                 'after': {'stage': 'revote'}}]
        self.save()
        facts = {'registrations': [], 'interruptions': [], 'ballots': [{'id': 'ballot-1', 'stage': 'unknown'}]}
        audit = {'evidence': {'ballot-1': [{'start_ms': 1000}]}, 'issues': []}
        causal.apply(facts, audit, self.entry)
        self.assertEqual(facts['ballots'][0]['stage'], 'revote')
        causal.apply(facts, audit, self.entry)
        facts['ballots'][0]['stage'] = 'pk'
        with self.assertRaisesRegex(ValueError, '基线已变化'):
            causal.apply(facts, audit, self.entry)


if __name__ == '__main__':
    unittest.main()
