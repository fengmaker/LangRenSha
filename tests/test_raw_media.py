import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from collect_bilibili_audio import Collector, CollectionError
import media_ingest
from raw_media_fixture import make_media, make_subtitle_media


class RawMediaBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT/'data')
        self.path = make_media(Path(self.folder.name))

    def tearDown(self):
        self.folder.cleanup()

    def change(self,filename,mutate):
        path = self.path.parent/filename
        value = json.loads(path.read_text(encoding='utf-8'))
        mutate(value)
        path.write_text(json.dumps(value),encoding='utf-8')

    def test_valid_audio_does_not_require_subtitles_or_asr(self):
        value = media_ingest.validate_media(self.path)['summary']
        self.assertEqual(value['status'],'raw_media_ready')
        self.assertTrue(value['audio_available'])
        self.assertFalse(value['subtitle_available'])
        self.assertEqual(value['subtitle_status'],'login_required')
        self.assertTrue(value['probe']['first_frame_decoded'])
        self.assertFalse(value['game_facts_verified'])

    def test_valid_subtitle_only_source_is_accepted_without_audio_probe(self):
        path = make_subtitle_media(Path(self.folder.name))
        with patch.object(media_ingest, 'probe_audio', side_effect=AssertionError('subtitle mode probed audio')):
            checked = media_ingest.validate_media(path)
        self.assertEqual(checked['summary']['status'], 'raw_subtitles_ready')
        self.assertFalse(checked['summary']['audio_available'])
        self.assertTrue(checked['summary']['subtitle_available'])
        self.assertIsNone(checked['audio_path'])
        self.assertEqual(len(checked['subtitles']), 1)

    def test_subtitle_only_requires_readable_valid_chinese_track(self):
        corruptions = {
            'missing': lambda path: path.unlink(),
            'invalid_json': lambda path: path.write_text('{', encoding='utf-8'),
            'invalid_cues': lambda path: path.write_text('{"body":[]}', encoding='utf-8'),
        }
        for name, corrupt in corruptions.items():
            with self.subTest(name=name):
                manifest = make_subtitle_media(Path(self.folder.name))
                corrupt(manifest.parent / 'subtitle.01.raw.json')
                with self.assertRaises(media_ingest.MediaValidationError):
                    media_ingest.validate_media(manifest)

    def test_subtitle_only_rejects_non_chinese_track(self):
        path = make_subtitle_media(Path(self.folder.name), language='ai-en')
        with self.assertRaisesRegex(media_ingest.MediaValidationError, '中文字幕'):
            media_ingest.validate_media(path)

    def test_subtitle_only_rejects_track_from_another_platform(self):
        path = make_subtitle_media(Path(self.folder.name), platform='weibo')
        with self.assertRaisesRegex(media_ingest.MediaValidationError, '来源'):
            media_ingest.validate_media(path)

    def test_bad_declared_audio_does_not_fall_back_to_valid_subtitles(self):
        subtitle_file = self.path.parent / 'subtitle.01.raw.json'
        subtitle_file.write_text(json.dumps({'body': [{'from': 0, 'to': 1, 'content': '中文'}]},
                                             ensure_ascii=False), encoding='utf-8')
        self.change('manifest.json', lambda value: value.update(subtitles={
            'status': 'visible_tracks',
            'tracks': [{'id': 1, 'platform': 'bilibili', 'language': 'ai-zh',
                        'file': subtitle_file.name, 'provenance': 'platform_visible_subtitle'}],
            'requests': [{'id': 1, 'language': 'ai-zh', 'status': 'downloaded', 'file': subtitle_file.name}],
        }))
        self.change('manifest.json', lambda value: value['audio'].update(sha256='0' * 64))
        with self.assertRaisesRegex(media_ingest.MediaValidationError, 'SHA-256'):
            media_ingest.validate_media(self.path)

    def test_unreferenced_audio_file_does_not_block_or_enter_subtitle_registration(self):
        path = make_subtitle_media(Path(self.folder.name))
        (path.parent / 'audio.m4a').write_bytes(b'bad audio')
        with patch.object(media_ingest, 'probe_audio') as probe:
            checked = media_ingest.validate_media(path)
        probe.assert_not_called()
        self.assertIsNone(checked['audio_path'])
        self.assertTrue(checked['summary']['subtitle_available'])

    def test_nonofficial_owner_is_rejected_before_media_probe(self):
        self.change('metadata.raw.json',lambda v:v['data']['owner'].update(mid=999))
        with patch.object(media_ingest,'probe_audio') as probe:
            with self.assertRaises(media_ingest.MediaValidationError):
                media_ingest.validate_media(self.path)
            probe.assert_not_called()

    def test_wrong_cid_is_rejected(self):
        self.change('metadata.raw.json',lambda v:v['data']['pages'][0].update(cid=999))
        with self.assertRaises(media_ingest.MediaValidationError):
            media_ingest.validate_media(self.path)

    def test_metadata_from_another_video_is_rejected(self):
        self.change('metadata.raw.json',lambda v:v['data'].update(bvid='BV1z6tG6rEfw'))
        with self.assertRaisesRegex(media_ingest.MediaValidationError, 'BVID'):
            media_ingest.validate_media(self.path)

    def test_existing_file_must_match_requested_bv_and_page(self):
        for bvid,page in [('BV1z6tG6rEfw',1),('BV1tj8p6REqy',2)]:
            with self.subTest(bvid=bvid,page=page),self.assertRaises(media_ingest.MediaValidationError):
                media_ingest.validate_media(self.path,bvid,page)

    def test_changed_bytes_are_rejected_even_if_size_is_unchanged(self):
        audio = self.path.parent/'audio.m4a'
        contents = bytearray(audio.read_bytes())
        contents[-1] = 1
        audio.write_bytes(contents)
        with self.assertRaisesRegex(media_ingest.MediaValidationError,'SHA-256'):
            media_ingest.validate_media(self.path)

    def test_truncated_file_is_not_complete(self):
        audio = self.path.parent/'audio.m4a'
        audio.write_bytes(audio.read_bytes()[:-20])
        with self.assertRaisesRegex(media_ingest.MediaValidationError,'大小'):
            media_ingest.validate_media(self.path)

    def test_part_file_is_not_complete(self):
        (self.path.parent/'audio.m4a').rename(self.path.parent/'audio.part')
        self.change('manifest.json',lambda v:v['audio'].update(file='audio.part'))
        with self.assertRaises(media_ingest.MediaValidationError):
            media_ingest.validate_media(self.path)

    def test_path_escape_is_rejected(self):
        self.change('manifest.json',lambda v:v['audio'].update(file='../audio.m4a'))
        with self.assertRaises(media_ingest.MediaValidationError):
            media_ingest.validate_media(self.path)

    def test_html_with_valid_hash_is_not_audio(self):
        audio = self.path.parent/'audio.m4a'
        content = b'<html>login required</html>'
        audio.write_bytes(content)
        self.change('manifest.json',lambda v:v['audio'].update(bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
        with self.assertRaisesRegex(media_ingest.MediaValidationError,'容器'):
            media_ingest.validate_media(self.path)

    def test_duration_disagreement_is_not_complete(self):
        self.change('manifest.json',lambda v:v.update(duration_seconds=100))
        self.change('metadata.raw.json',lambda v:v['data']['pages'][0].update(duration=100))
        with self.assertRaisesRegex(media_ingest.MediaValidationError,'时长'):
            media_ingest.validate_media(self.path)

    def test_video_track_is_rejected(self):
        audio = Mock(type='audio',codec_context=Mock(name='aac'))
        video = Mock(type='video',codec_context=Mock(name='h264'))
        container = Mock(streams=[audio,video])
        manager = Mock()
        manager.__enter__ = Mock(return_value=container)
        manager.__exit__ = Mock(return_value=False)
        with patch('av.open',return_value=manager),self.assertRaisesRegex(media_ingest.MediaValidationError,'视频轨'):
            media_ingest.probe_audio(self.path.parent/'audio.m4a',1)
        container.decode.assert_not_called()

    def test_collector_stops_before_download_when_owner_is_wrong(self):
        collector = Collector()
        raw = {'data':{'owner':{'mid':999},'pages':[{'page':1,'cid':123,'duration':1}]}}
        with patch.object(collector,'api',return_value=raw) as api,patch.object(collector,'download') as download:
            with self.assertRaisesRegex(CollectionError,'UID'):
                collector.collect('BV1tj8p6REqy',1,self.path.parent,True,128000,200*1024*1024,expected_owner='19106800')
            self.assertEqual(api.call_count,1)
            download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
