import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from capture_season_speech_frames import choose_speech


class SpeechSelectionTests(unittest.TestCase):
    def test_latest_numbered_handoff_over_late_commentary(self):
        cues = [{'from': 20, 'to': 22, 'content': '天亮了'},
                {'from': 30, 'to': 32, 'content': '过了9号玩家请发言'},
                {'from': 70, 'to': 72, 'content': '4号玩家请发言'},
                {'from': 90, 'to': 92, 'content': '我觉得他的发言很好'}]
        selected = choose_speech(cues, 100)
        self.assertEqual(selected['seconds'], 80)
        self.assertEqual(selected['preceding_dawn_cue'], cues[0])
        self.assertFalse(selected['last_game_day_verified'])

    def test_recap_and_last_seconds_are_not_speech_candidates(self):
        cues = [{'from': 30, 'to': 32, 'content': '复盘请4号玩家请发言'},
                {'from': 98, 'to': 99, 'content': '4号玩家请发言'}]
        self.assertIsNone(choose_speech(cues, 100))


if __name__ == '__main__':
    unittest.main()
