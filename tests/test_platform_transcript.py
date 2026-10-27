import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import register_season_transcripts as register
from season_naming import digest


class PlatformTranscriptTests(unittest.TestCase):
    def test_empty_platform_cue_preserves_raw_and_records_omission(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root/'data/raw/subtitle.json'
            raw.parent.mkdir(parents=True)
            raw.write_text(json.dumps({'body': [
                {'from': 1.25, 'to': 2.5, 'content': '七号玩家请发言'},
                {'from': 3.0, 'to': 4.0, 'content': '  '},
            ]}, ensure_ascii=False), encoding='utf-8')
            raw_hash = digest(raw)
            row = {'BVID': 'BVexample001', '中文字幕原件': 'data/raw/subtitle.json'}
            manifest = {'bvid': row['BVID'], 'cid': 123, 'page': 1, 'audio': {'sha256': 'a'*64}}
            with patch.object(register, 'ROOT', root):
                output = register.platform_transcript(row, manifest, 'S23')
                first_hash = digest(output)
                value = json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(value['segments'], [{'start': 1.25, 'end': 2.5, 'text': '七号玩家请发言'}])
                self.assertEqual(value['normalization']['empty_cues_omitted'], [{'index': 1, 'from': 3.0, 'to': 4.0}])
                self.assertEqual(value['source']['subtitle_sha256'], raw_hash)
                self.assertEqual(digest(raw), raw_hash)
                register.platform_transcript(row, manifest, 'S23')
                self.assertEqual(digest(output), first_hash)


if __name__ == '__main__':
    unittest.main()
