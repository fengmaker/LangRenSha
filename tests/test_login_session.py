import argparse
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from http.cookiejar import MozillaCookieJar

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
SPEC = importlib.util.spec_from_file_location('login_session_cdp_test',ROOT/'scripts/login_session.py')
login = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(login)


def cookie(domain='.bilibili.com',name='SESSDATA',expires=-1):
    return {'domain':domain,'name':name,'value':'synthetic-test-placeholder',
            'path':'/','secure':True,'httpOnly':True,'expires':expires}


class ExistingChromeExportTests(unittest.TestCase):
    def test_only_explicit_loopback_cdp_addresses_are_accepted(self):
        for value in ['ws://127.0.0.1:9222/devtools/browser','http://localhost:9222','ws://[::1]:9222/devtools/browser/test']:
            self.assertEqual(login.local_cdp_url(value),value)
        for value in ['https://example.test:9222','http://localhost','http://127.0.0.1:0',
                      'http://localhost:9222/?token=test','http://name:password@localhost:9222',
                      'file:///tmp/browser','http://localhost:99999']:
            with self.subTest(value=value),self.assertRaises(argparse.ArgumentTypeError):
                login.local_cdp_url(value)

    def test_export_reads_only_platform_urls_and_filters_domains_and_expiry(self):
        context = Mock()
        context.cookies.return_value = [cookie(),cookie(name='old',expires=time.time()-1),
                                        cookie('.example.test',name='unrelated')]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'bilibili.cookies.txt'
            count = login.export_platform_cookies(context,'bilibili',target)
            parsed = MozillaCookieJar(str(target))
            parsed.load(ignore_discard=True,ignore_expires=True)
            self.assertEqual(count,1)
            self.assertEqual([item.name for item in parsed],['SESSDATA'])
        context.cookies.assert_called_once_with(urls=['https://www.bilibili.com/','https://api.bilibili.com/'])

    def test_empty_or_logged_out_browser_keeps_existing_cookie_file(self):
        for cookies in [[],[cookie(name='buvid3')],[cookie(expires=time.time()-10)]]:
            with self.subTest(cookies_present=bool(cookies)),tempfile.TemporaryDirectory() as folder:
                target = Path(folder)/'bilibili.cookies.txt'
                target.write_text('previous-file-placeholder',encoding='utf-8')
                context = Mock()
                context.cookies.return_value = cookies
                with self.assertRaises(login.LoginSessionError):
                    login.export_platform_cookies(context,'bilibili',target)
                self.assertEqual(target.read_text(encoding='utf-8'),'previous-file-placeholder')

    def test_invalid_cookie_serialization_keeps_existing_file(self):
        context = Mock()
        context.cookies.return_value = [{**cookie(),'value':'unrepresentable\nplaceholder'}]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'bilibili.cookies.txt'
            target.write_text('previous-file-placeholder',encoding='utf-8')
            with self.assertRaises(ValueError):
                login.export_platform_cookies(context,'bilibili',target)
            self.assertEqual(target.read_text(encoding='utf-8'),'previous-file-placeholder')

    def test_connect_does_not_launch_navigate_or_close_existing_browser(self):
        context = Mock()
        browser = Mock(contexts=[context])
        playwright = Mock()
        playwright.chromium.connect_over_cdp.return_value = browser
        endpoint = 'ws://127.0.0.1:9222/devtools/browser'
        target = Path('synthetic-unused-target')
        with patch.object(login,'export_platform_cookies',return_value=1) as export:
            self.assertEqual(login.export_from_existing(playwright,endpoint,'bilibili',target,30000),1)
        playwright.chromium.connect_over_cdp.assert_called_once_with(endpoint,timeout=30000)
        export.assert_called_once_with(context,'bilibili',target)
        playwright.chromium.launch.assert_not_called()
        playwright.chromium.launch_persistent_context.assert_not_called()
        browser.new_context.assert_not_called()
        browser.close.assert_not_called()
        context.new_page.assert_not_called()
        context.close.assert_not_called()

    def test_failed_attach_does_not_launch_a_fallback_window(self):
        playwright = Mock()
        playwright.chromium.connect_over_cdp.side_effect = RuntimeError('synthetic connection failure')
        with self.assertRaises(RuntimeError):
            login.export_from_existing(playwright,'ws://127.0.0.1:9222/devtools/browser',
                                       'bilibili',Path('synthetic-unused-target'),1000)
        playwright.chromium.launch.assert_not_called()
        playwright.chromium.launch_persistent_context.assert_not_called()

    def test_missing_existing_context_does_not_create_a_new_context(self):
        browser = Mock(contexts=[])
        playwright = Mock()
        playwright.chromium.connect_over_cdp.return_value = browser
        with self.assertRaises(login.LoginSessionError):
            login.export_from_existing(playwright,'http://127.0.0.1:9222','bilibili',Path('synthetic-unused-target'),1000)
        browser.new_context.assert_not_called()


if __name__ == '__main__':
    unittest.main()
