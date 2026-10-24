import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from season_naming import naming,export_source,validate_cues
from raw_media_fixture import make_media


class SeasonArchiveTests(unittest.TestCase):
    def label(self,title):
        return naming(title,'BV1tj8p6REqy',41072527914,1,'2026-05-26')

    def test_showmatch_regular_and_finals_week_are_distinct(self):
        show=self.label('20260526 表演赛 Day-1 第一局-预女猎白混')
        regular=self.label('20260602 正赛 第一期 Day-1 第一局-预女猎白混')
        finals=self.label('20260819 决赛 Day-2 第四局-鬼魂新娘')
        self.assertEqual((show['week_number'],regular['week_number'],finals['week_number']),(1,2,13))
        self.assertEqual(regular['issue_candidate'],1)
        self.assertIn('决赛周',finals['stem'])
        self.assertIn('第04局',finals['stem'])
        self.assertFalse(finals['game_facts_verified'])

    def test_bad_year_is_retained_and_cannot_shift_week(self):
        value=self.label('20250723 正赛 第八期 Day-3 第一局-预女猎白混')
        self.assertEqual(value['event_date_candidate'],'2025-07-23')
        self.assertTrue(value['date_conflict'])
        self.assertEqual(value['week_number'],9)
        self.assertIn('日期存疑',value['stem'])

    def test_missing_game_number_is_not_guessed(self):
        value=self.label('20260612 正赛 第二期 Day-4 唯邻是从')
        self.assertIsNone(value['game_number_candidate'])
        self.assertIn('局次待核',value['stem'])
        self.assertIn('唯邻是从',value['stem'])

    def test_special_is_not_forced_to_regular(self):
        value=self.label('20260703 特辑 第一局-预女猎白')
        self.assertEqual(value['phase_candidate'],'special')
        self.assertEqual(value['week_number'],6)
        self.assertIn('特辑待核',value['stem'])

    def test_identifiers_disambiguate_same_date_and_game(self):
        title='20260819 决赛 Day-2 第一局-预女猎白混'
        first=self.label(title)
        second=naming(title,'BV1tj8p6RE2h',123,1,'2026-05-26')
        self.assertNotEqual(first['stem'],second['stem'])
        self.assertIn('CID41072527914',first['stem'])

    def test_invalid_cue_timestamps_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_cues({'body':[{'from':3,'to':1,'content':'synthetic'}]})

    def test_caption_time_coverage_does_not_double_count_overlaps(self):
        from audit_season import coverage
        result=coverage([{'from':0,'to':20,'content':'synthetic'},
                         {'from':10,'to':30,'content':'synthetic'},
                         {'from':40,'to':50,'content':'synthetic'}],100)
        self.assertEqual(result['covered_seconds'],40)
        self.assertEqual(result['covered_ratio'],0.4)

    def test_short_intro_caption_is_flagged_without_claiming_accuracy(self):
        from audit_season import coverage
        result=coverage([{'from':1,'to':30,'content':'synthetic introduction'}],5000)
        self.assertEqual(result['screening_status'],'needs_review')
        self.assertFalse(result['accuracy_verified'])
        self.assertGreater(len(result['warnings']),0)

    def test_existing_chinese_capture_survives_empty_or_short_refresh(self):
        import reconcile_season_subtitles as reconciliation
        from season_naming import digest
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=ROOT/'data') as folder:
            base=Path(folder)
            archive=base/'data/archive'
            archive.mkdir(parents=True)
            candidates=[]
            for name,language,end in [('short','ai-zh',20),('full','ai-zh',5000),('foreign','ai-en',6000)]:
                path=archive/f'{name}.json'
                path.write_text(json.dumps({'body':[{'from':0,'to':end,'content':'synthetic'}]}),encoding='utf-8')
                candidates.append({'relative_path':path.relative_to(base).as_posix(),
                                   'sha256':digest(path),'metadata':{'language':language}})
            with patch.object(reconciliation,'ROOT',base):
                self.assertEqual(reconciliation.choose_best(candidates,6000)['relative_path'],'data/archive/full.json')
                self.assertIsNone(reconciliation.choose_best([],6000))
                candidates[0]['sha256']='0'*64
                with self.assertRaisesRegex(ValueError,'哈希'):
                    reconciliation.choose_best(candidates,6000)

    def test_export_keeps_raw_subtitle_bytes_and_uses_hardlinked_audio(self):
        import season_naming
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=ROOT/'data') as folder:
            base=Path(folder)
            manifest_path=make_media(base/'raw')
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest.update(url='https://www.bilibili.com/video/BV1tj8p6REqy/',title='20260819 决赛 Day-2 第一局-预女猎白混')
            raw=b'{"type":"AIsubtitle","lang":"zh","body":[{"from":1.25,"to":2.5,"content":"synthetic speech"}]}'
            (manifest_path.parent/'subtitle.json').write_bytes(raw)
            manifest['subtitles']={'status':'visible_tracks','tracks':[{'file':'subtitle.json','language':'ai-zh'}]}
            manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
            # Export root is isolated from the actual season archive.
            with patch.object(season_naming,'ROOT',base):
                result=export_source(manifest_path,self.label(manifest['title']))
                again=export_source(manifest_path,self.label(manifest['title']))
            audio=base/result['audio']
            self.assertTrue(os.path.samefile(audio,manifest_path.parent/'audio.m4a'))
            track=result['subtitles'][0]
            self.assertEqual((base/track['raw']).read_bytes(),raw)
            self.assertIn('00:00:01,250 --> 00:00:02,500',(base/track['srt']).read_text(encoding='utf-8'))
            self.assertIn('synthetic speech',(base/track['readable']).read_text(encoding='utf-8'))
            self.assertEqual(result,again)
            self.assertLess(len(str(audio)),240)
            changed={'type':'AIsubtitle','lang':'zh','body':[{'from':1.25,'to':2.5,'content':'refreshed synthetic speech'}]}
            (manifest_path.parent/'subtitle.json').write_text(json.dumps(changed),encoding='utf-8')
            with patch.object(season_naming,'ROOT',base):
                refreshed=export_source(manifest_path,self.label(manifest['title']))
            self.assertNotEqual(refreshed['subtitles'][0]['raw'],track['raw'])
            self.assertEqual((base/track['raw']).read_bytes(),raw)


if __name__=='__main__':
    unittest.main()
