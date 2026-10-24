import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = script('collect_bilibili_audio')
transcriber = script('transcribe_audio')


class AcquisitionBoundaryTests(unittest.TestCase):
    def test_muxed_fallback_cannot_download_video_when_audio_is_missing(self):
        play = {'dash': {'video': [{'baseUrl': 'https://example.test/video'}]},
                'durl': [{'url': 'https://example.test/muxed'}]}
        with self.assertRaises(collector.CollectionError):
            collector.select_audio(play, 128000)

    def test_audio_label_cannot_select_a_video_mime_type(self):
        play = {'dash': {'audio': [{'baseUrl': 'https://example.test/video',
                                   'mimeType': 'video/mp4', 'bandwidth': 64000}]}}
        with self.assertRaises(collector.CollectionError):
            collector.select_audio(play, 128000)

    def test_bitrate_limit_prevents_unbounded_track_selection(self):
        items = [{'baseUrl': 'https://example.test/audio', 'mimeType': 'audio/mp4',
                  'bandwidth': bitrate} for bitrate in [67175, 81764, 105755, 192000]]
        self.assertEqual(collector.select_audio({'dash': {'audio': items}}, 128000)['bandwidth'], 105755)
        with self.assertRaises(collector.CollectionError):
            collector.select_audio({'dash': {'audio': items}}, 32000)

    def test_bvid_is_identical_between_shared_url_and_bare_id(self):
        self.assertEqual(collector.parse_bvid('https://www.bilibili.com/video/BV1tj8p6REqy/?p=1'),
                         collector.parse_bvid('BV1tj8p6REqy'))
        with self.assertRaises(collector.CollectionError):
            collector.parse_bvid('BV1tj8p6REqyOTHER')

    def test_clips_cannot_silently_extend_past_actual_audio(self):
        with self.assertRaises(ValueError):
            transcriber.parse_clips('3755:3936', 3935.53)
        self.assertEqual(transcriber.parse_clips('0:120,3755:3935', 3935.53),
                         [(0, 120), (3755, 3935)])

    def test_media_times_preserve_hour_boundary(self):
        self.assertEqual(transcriber.clock(3600.125), '01:00:00,125')

    def test_login_gated_empty_subtitles_are_not_reported_as_absent(self):
        result = collector.subtitle_availability({'need_login_subtitle': True,
                                                   'subtitle': {'subtitles': []}})
        self.assertEqual(result['status'], 'login_required')
        self.assertTrue(result['need_login_subtitle'])

    def test_visible_subtitles_remain_usable_when_login_hint_is_also_present(self):
        result = collector.subtitle_availability({'need_login_subtitle': True,
                                                   'subtitle': {'subtitles': [{'lan': 'ai-zh'}]}})
        self.assertEqual(result['status'], 'visible_tracks')
        self.assertEqual(result['count'], 1)

    def test_missing_login_indicator_is_not_assumed_to_mean_login_unnecessary(self):
        result = collector.subtitle_availability({'subtitle': {'subtitles': []}})
        self.assertIsNone(result['need_login_subtitle'])
        self.assertEqual(result['status'], 'none_visible')

    def test_subtitle_index_must_belong_to_requested_media(self):
        self.assertTrue(collector.subtitle_source_matches({'bvid':'BV1tj8p6REqy','cid':123,'aid':456},'BV1tj8p6REqy',123,456))
        self.assertFalse(collector.subtitle_source_matches({'bvid':'BV1z6tG6rEfw','cid':123,'aid':456},'BV1tj8p6REqy',123,456))
        self.assertFalse(collector.subtitle_source_matches({'cid':789},'BV1tj8p6REqy',123,456))

    def test_current_subtitle_endpoint_and_chinese_selection(self):
        instance=collector.Collector(quiet=True)
        view={'data':{'aid':456,'bvid':'BV1tj8p6REqy','owner':{'mid':19106800},
                      'pages':[{'page':1,'cid':123,'duration':60}],'title':'synthetic fixture'}}
        player={'data':{'aid':456,'cid':123,'bvid':'BV1tj8p6REqy','need_login_subtitle':False,
                        'subtitle':{'subtitles':[
                            {'id':1,'lan':'ai-zh','subtitle_url':'https://aisubtitle.hdslb.com/synthetic-zh.json'},
                            {'id':2,'lan':'ai-en','subtitle_url':'https://aisubtitle.hdslb.com/synthetic-en.json'}]}}}
        reply=Mock(status_code=200)
        reply.json.return_value={'type':'AIsubtitle','body':[{'from':1,'to':2,'content':'synthetic'}]}
        with tempfile.TemporaryDirectory() as folder,patch.object(instance,'api',side_effect=[view,player]) as api,patch.object(instance.session,'get',return_value=reply) as get:
            manifest=instance.collect('BV1tj8p6REqy',1,Path(folder),False,128000,200*1024**2,expected_owner='19106800')
            self.assertEqual(api.call_args_list[1].args,('/x/player/wbi/v2',{'aid':456,'cid':123}))
            self.assertEqual(get.call_count,1)
            self.assertEqual([track['language'] for track in manifest['subtitles']['tracks']],['ai-zh'])
            self.assertEqual(manifest['subtitles']['requests'][1]['status'],'not_selected_language')

    def test_wrong_media_subtitle_index_is_never_downloaded(self):
        instance=collector.Collector(quiet=True)
        view={'data':{'aid':456,'bvid':'BV1tj8p6REqy','owner':{'mid':19106800},
                      'pages':[{'page':1,'cid':123,'duration':60}],'title':'synthetic fixture'}}
        player={'data':{'aid':456,'cid':999,'bvid':'BV1tj8p6REqy','subtitle':{'subtitles':[]}}}
        with tempfile.TemporaryDirectory() as folder,patch.object(instance,'api',side_effect=[view,player]),patch.object(instance.session,'get') as get:
            manifest=instance.collect('BV1tj8p6REqy',1,Path(folder),False,128000,200*1024**2,expected_owner='19106800')
            self.assertEqual(manifest['subtitles']['status'],'unavailable_in_this_request')
            get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
