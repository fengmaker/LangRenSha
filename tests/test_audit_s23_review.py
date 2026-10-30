import hashlib
import json
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_s23_review import audio_asr_evidence_errors, resolve_evidence_path


class AuditS23EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bvid = 'BVtest123'
        self.audio = self.root / 'data/seasons/S23' / self.bvid / 'audio.m4a'
        self.transcript = (self.root / 'data/extractions/S23/audio_semantic_review'
                           / self.bvid / 'transcript.json')
        self.audio.parent.mkdir(parents=True)
        self.transcript.parent.mkdir(parents=True)
        self.audio.write_bytes(b'fixture audio bytes')
        self.audio_sha = hashlib.sha256(self.audio.read_bytes()).hexdigest()
        source = {
            'status': 'machine_generated_unverified',
            'source_audio': str(self.audio.resolve()),
            'source_audio_sha256': self.audio_sha,
            'start_ms': 3_740_000,
            'end_ms': 3_767_000,
            'text': '守夜守卫技能通过，接下来九尾狐标记四号',
            'raw_result': [{'key': 'clip', 'text': '守夜守卫技能通过，接下来九尾狐标记四号',
                            'text_tn': '守夜守卫技能通过，接下来九尾狐标记四号'}],
        }
        self.transcript.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')
        self.proof = {
            'kind': 'audio_asr',
            'source_path': self.transcript.relative_to(self.root).as_posix(),
            'source_sha256': hashlib.sha256(self.transcript.read_bytes()).hexdigest(),
            'source_audio_path': str(self.audio.resolve()),
            'source_audio_sha256': self.audio_sha,
            'start_ms': 3_740_000,
            'end_ms': 3_767_000,
            'quote': '守夜守卫技能通过',
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_asr_quote_in_bound_window_passes(self):
        self.assertEqual(audio_asr_evidence_errors(self.root, self.proof, self.transcript), [])

    def test_asr_wrong_quote_fails(self):
        proof = dict(self.proof, quote='技能没有通过')
        errors = audio_asr_evidence_errors(self.root, proof, self.transcript)
        self.assertIn('quote_mismatch', [code for code, _ in errors])

    def test_asr_wrong_time_fails_even_when_quote_matches(self):
        proof = dict(self.proof, end_ms=3_767_001)
        errors = audio_asr_evidence_errors(self.root, proof, self.transcript)
        self.assertIn('evidence_time_mismatch', [code for code, _ in errors])

    def test_asr_wrong_source_sha_fails(self):
        proof = dict(self.proof, source_sha256='0' * 64)
        errors = audio_asr_evidence_errors(self.root, proof, self.transcript)
        self.assertIn('evidence_sha256_mismatch', [code for code, _ in errors])

    def test_asr_wrong_audio_sha_fails(self):
        proof = dict(self.proof, source_audio_sha256='0' * 64)
        errors = audio_asr_evidence_errors(self.root, proof, self.transcript)
        self.assertIn('evidence_sha256_mismatch', [code for code, _ in errors])

    def test_old_s22_rules_path_resolves_to_the_existing_archive(self):
        root = Path(__file__).resolve().parents[1]
        resolved, error = resolve_evidence_path(
            root, 'docs/12_S22正式版型规则与录入流程.md')
        self.assertIsNone(error)
        self.assertEqual(resolved, root / 'docs/archive/S22/正式版型规则与录入流程.md')

    def test_unmapped_missing_path_stays_missing(self):
        resolved, error = resolve_evidence_path(self.root, 'docs/other-old-rules.md')
        self.assertIsNone(resolved)
        self.assertEqual(error, 'evidence_missing')

    def test_outside_project_path_stays_rejected(self):
        resolved, error = resolve_evidence_path(self.root, '../outside.md')
        self.assertIsNone(resolved)
        self.assertEqual(error, 'evidence_outside_project')


if __name__ == '__main__':
    unittest.main()
