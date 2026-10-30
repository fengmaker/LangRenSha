import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from cleanup_data import (REPORT, current_media_references, data_path, require_idle_seasons,
                          scan_evidence_references)
from collect_bilibili_audio import is_chinese_subtitle


class DataCleanupBoundaryTests(unittest.TestCase):
    def test_cleanup_receipts_are_written_to_maintenance_reports(self):
        self.assertEqual(REPORT.parent, ROOT/'data/reports/maintenance')

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

    def test_current_subtitle_exports_and_manifest_raw_tracks_are_protected_for_all_registered_seasons(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path = root/'config/seasons.json'
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(json.dumps({'seasons': {'S22': {}, 'S23': {}}}), encoding='utf-8')
            for season in ('S22', 'S23'):
                bvid = f'BVTEST{season}'
                folder = root/'data/raw/bilibili'/bvid/'p01'
                folder.mkdir(parents=True)
                manifest_path = folder/'manifest.json'
                source_raw = folder/f'subtitle.{season}.raw.json'
                source_raw.write_text('{}', encoding='utf-8')
                manifest_path.write_text(json.dumps({'subtitles': {'tracks': [
                    {'file': source_raw.name, 'language': 'ai-zh'}]}}), encoding='utf-8')
                base = f'data/seasons/{season}'
                exports = {
                    'audio': f'{base}/{bvid}.音频.m4a',
                    'description': f'{base}/{bvid}.说明.json',
                    'source_manifest': manifest_path.relative_to(root).as_posix(),
                    'subtitles': [{
                        'language': 'ai-zh',
                        'raw': f'{base}/{bvid}.字幕_当前.原始.json',
                        'srt': f'{base}/{bvid}.字幕_当前.srt',
                        'readable': f'{base}/{bvid}.字幕_当前.阅读.txt',
                    }],
                }
                progress_path = root/'data/reports'/season/f'{season}_采集进度.json'
                progress_path.parent.mkdir(parents=True, exist_ok=True)
                progress_path.write_text(json.dumps({'items': {f'{bvid}:123': {
                    'bvid': bvid, 'status': 'complete', 'exports': exports}},
                    'current_run': {'state': 'finished'}}), encoding='utf-8')

            references = current_media_references(root)
            for season in ('S22', 'S23'):
                bvid = f'BVTEST{season}'
                self.assertIn(root/f'data/seasons/{season}/{bvid}.字幕_当前.原始.json',
                              references['active_exports'])
                self.assertIn(root/f'data/raw/bilibili/{bvid}/p01/subtitle.{season}.raw.json',
                              references['active_raw'])
                self.assertIn(root/f'data/raw/bilibili/{bvid}/p01/manifest.json', references['manifests'])
                self.assertEqual(references['season_counts'][season]['manifest_raw_subtitle_files'], 1)

    def test_missing_progress_is_allowed_and_running_progress_blocks_apply_guard(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'config').mkdir()
            (root/'config/seasons.json').write_text(
                json.dumps({'seasons': {'S22': {}, 'S23': {}}}), encoding='utf-8')
            progress = root/'data/reports/S22/S22_采集进度.json'
            progress.parent.mkdir(parents=True)
            progress.write_text(json.dumps({'items': {}, 'current_run': {'state': 'running'}}),
                                encoding='utf-8')

            references = current_media_references(root)
            self.assertEqual(references['running_seasons'], ['S22'])
            require_idle_seasons([])
            with self.assertRaisesRegex(ValueError, 'S22'):
                require_idle_seasons(references['running_seasons'])

    def test_reference_scan_protects_current_paths_and_hashes_but_skips_reports(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            referenced = root/'data/transcripts/S22/current.json'
            referenced.parent.mkdir(parents=True)
            referenced.write_text(json.dumps({'text': 'current evidence'}), encoding='utf-8')
            digest = hashlib.sha256(referenced.read_bytes()).hexdigest()
            game = root/'data/games/S22/game.json'
            game.parent.mkdir(parents=True)
            game.write_text(json.dumps({'transcript_file': referenced.relative_to(root).as_posix(),
                                        'transcript_sha256': digest}), encoding='utf-8')
            transcript_path = root/'data/transcripts/S22/transcript.json'
            transcript_path.write_text(json.dumps({'source': {'audio_sha256': 'ab' * 32,
                                                               'manifest_file': 'data/raw/bilibili/BVTEST/p01/manifest.json'},
                                                    'segments': [{'text': 'transcript content'}]}),
                                       encoding='utf-8')
            report_target = root/'data/raw/bilibili/old/subtitle.unused.raw.json'
            report_target.parent.mkdir(parents=True)
            report_target.write_text('report inventory only', encoding='utf-8')
            report = root/'data/reports/data_cleanup_old.json'
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({'path': report_target.relative_to(root).as_posix(),
                                          'sha256': hashlib.sha256(report_target.read_bytes()).hexdigest()}),
                              encoding='utf-8')
            maintenance = root/'data/reports/maintenance/maintenance_baseline.json'
            maintenance.parent.mkdir(parents=True, exist_ok=True)
            maintenance.write_text(json.dumps({'path': report_target.relative_to(root).as_posix()}),
                                   encoding='utf-8')

            paths, hashes = scan_evidence_references(root)
            self.assertIn(referenced, paths)
            self.assertIn(digest, hashes)
            self.assertIn('ab' * 32, hashes)
            self.assertIn(root/'data/raw/bilibili/BVTEST/p01/manifest.json', paths)
            self.assertNotIn(report_target, paths)
            self.assertNotIn(hashlib.sha256(report_target.read_bytes()).hexdigest(), hashes)


if __name__=='__main__':
    unittest.main()
