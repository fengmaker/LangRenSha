"""Unit tests for importing legacy and FunASR transcript timestamps."""

import importlib.util
import json
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
HAS_DRIVER = importlib.util.find_spec("psycopg") is not None
if HAS_DRIVER:
    import database


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self):
        self.run_id = "synthetic-transcription-run"
        self.run_exists = False
        self.run_parameters = None
        self.segments = []

    def execute(self, query, params=None):
        if "INSERT INTO transcription_runs" in query:
            self.run_parameters = params
            if self.run_exists:
                return FakeCursor(None)
            self.run_exists = True
            return FakeCursor({"id": self.run_id})
        if "SELECT id FROM transcription_runs" in query:
            return FakeCursor({"id": self.run_id})
        if "INSERT INTO transcript_segments" in query:
            self.segments.append(params)
            return FakeCursor(None)
        raise AssertionError(f"Unexpected query: {query}")


@unittest.skipUnless(HAS_DRIVER, "requires psycopg so scripts/database.py can be imported")
class TranscriptImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "transcript.json"

    def write_value(self, value):
        self.path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return self.path

    def import_with_fake(self, conn, value):
        self.write_value(value)
        with patch.object(database, "artifact", return_value="synthetic-artifact") as artifact_mock, \
                patch.object(database, "Jsonb", side_effect=lambda obj: obj):
            result = database.import_transcript(conn, "synthetic-source", self.path)
        return result, artifact_mock

    def test_legacy_seconds_are_preserved(self):
        conn = FakeConnection()
        result, _ = self.import_with_fake(conn, {
            "engine": "legacy-asr", "model": "legacy-model", "language": "zh",
            "segments": [{"start": 1.25, "end": 1.5, "text": "测试"}],
        })

        self.assertEqual(result, conn.run_id)
        self.assertEqual(conn.run_parameters[3:5], ("legacy-model", "zh"))
        row = conn.segments[0]
        self.assertEqual((row[2], row[3]), (Decimal("1.25"), Decimal("1.5")))
        self.assertEqual(row[4], "测试")

    def test_fun_asr_milliseconds_and_provenance_are_imported(self):
        conn = FakeConnection()
        audio_hash = "a" * 64
        config = {
            "models": {"asr": "example/asr-model", "vad": "example/vad-model"},
            "device": "cuda", "audio_sha256": audio_hash,
        }
        result, _ = self.import_with_fake(conn, {
            "engine": "FunASR", "source": {"audio_sha256": audio_hash}, "config": config,
            "segments": [{"start_ms": 450, "end_ms": 670, "text": "转写内容",
                          "speaker": "chunk_0001:speaker_0", "chunk_index": 1}],
        })

        self.assertEqual(result, conn.run_id)
        run = conn.run_parameters
        self.assertEqual(run[2:5], ("FunASR", "example/asr-model", None))
        self.assertEqual((conn.segments[0][2], conn.segments[0][3]),
                         (Decimal("0.45"), Decimal("0.67")))
        self.assertEqual(conn.segments[0][5]["speaker"], "chunk_0001:speaker_0")
        self.assertEqual(conn.segments[0][5]["chunk_index"], 1)
        self.assertEqual(run[5]["config"], config)
        self.assertEqual(run[5]["audio_sha256"], audio_hash)

    def test_invalid_segments_are_rejected_before_artifact_registration(self):
        invalid_segments = [
            {"start_ms": -1, "end_ms": 2, "text": "负时间"},
            {"start_ms": 3, "end_ms": 2, "text": "逆序"},
            {"start_ms": float("inf"), "end_ms": 4, "text": "无穷"},
            {"start": "0.1", "end": 0.2, "text": "字符串时间"},
            {"start_ms": 0, "end_ms": 1, "text": "   "},
        ]
        for segment in invalid_segments:
            with self.subTest(segment=segment):
                conn = FakeConnection()
                self.write_value({"segments": [segment]})
                with patch.object(database, "artifact") as artifact_mock, \
                        patch.object(database, "Jsonb", side_effect=lambda obj: obj):
                    with self.assertRaises(database.ReviewError):
                        database.import_transcript(conn, "synthetic-source", self.path)
                artifact_mock.assert_not_called()
                self.assertFalse(conn.run_exists)
                self.assertEqual(conn.segments, [])

    def test_repeated_import_does_not_duplicate_segments(self):
        conn = FakeConnection()
        value = {"engine": "FunASR", "segments": [
            {"start_ms": 10, "end_ms": 20, "text": "幂等"},
        ]}
        self.write_value(value)
        with patch.object(database, "artifact", return_value="synthetic-artifact"), \
                patch.object(database, "Jsonb", side_effect=lambda obj: obj):
            first = database.import_transcript(conn, "synthetic-source", self.path)
            second = database.import_transcript(conn, "synthetic-source", self.path)

        self.assertEqual(first, second)
        self.assertEqual(len(conn.segments), 1)


if __name__ == "__main__":
    unittest.main()
