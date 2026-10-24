import sys
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from cleanup_data import data_path
from collect_bilibili_audio import is_chinese_subtitle


class DataCleanupBoundaryTests(unittest.TestCase):
    def test_cleanup_cannot_target_audio_or_leave_data_folder(self):
        for value in ['README.md','data/../../outside.json','data/raw/bilibili/example/audio.m4a']:
            with self.subTest(path=value),self.assertRaises(ValueError):
                data_path(value)
        self.assertEqual(data_path('data/reports/example.json'),ROOT/'data/reports/example.json')

    def test_chinese_ai_and_human_tracks_are_kept_but_translations_are_not(self):
        for language in ['ai-zh','zh','zh-CN','zh-Hans','zh-Hant','zh_TW']:
            with self.subTest(language=language):
                self.assertTrue(is_chinese_subtitle(language))
        for language in ['ai-en','ai-ja','ai-ar','ai-pt','ai-es','en-US',None,'']:
            with self.subTest(language=language):
                self.assertFalse(is_chinese_subtitle(language))


if __name__=='__main__':
    unittest.main()
