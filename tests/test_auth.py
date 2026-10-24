import importlib.util
import tempfile
import time
import unittest
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "auth_support", ROOT / "scripts" / "auth_support.py"
)
auth = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auth)
COLLECTOR_SPEC = importlib.util.spec_from_file_location(
    "collector_auth_test", ROOT / "scripts" / "collect_bilibili_audio.py"
)
collector = importlib.util.module_from_spec(COLLECTOR_SPEC)
COLLECTOR_SPEC.loader.exec_module(collector)
LOGIN_SESSION_SPEC = importlib.util.spec_from_file_location(
    "login_session_test", ROOT / "scripts" / "login_session.py"
)
login_session = importlib.util.module_from_spec(LOGIN_SESSION_SPEC)
LOGIN_SESSION_SPEC.loader.exec_module(login_session)


def netscape_cookie(domain, name, value, expires, include_subdomains="TRUE"):
    return "\t".join((domain, include_subdomains, "/", "TRUE", str(expires), name, value))


class ExplicitCookieAuthenticationTests(unittest.TestCase):
    def test_collector_remains_constructible_without_arguments(self):
        instance = collector.Collector()
        self.assertEqual(instance.authentication,
                         {"auth_mode": "none", "cookies_loaded": False})

    def test_anonymous_mode_does_not_read_the_supplied_file(self):
        session = requests.Session()
        with mock.patch.object(MozillaCookieJar, "load", side_effect=AssertionError("read")) as load:
            result = auth.configure_session(session, cookies_file=object())
        self.assertEqual(result, {"auth_mode": "none", "cookies_loaded": False})
        self.assertEqual(list(session.cookies), [])
        load.assert_not_called()

    def test_cookie_mode_keeps_only_live_cookies_from_platform_domains(self):
        now = int(time.time())
        text = "# Netscape HTTP Cookie File\n" + "\n".join((
            netscape_cookie(".bilibili.com", "SESSDATA", "private-value", now + 3600),
            netscape_cookie("api.hdslb.com", "buvid3", "another-value", now + 3600, "FALSE"),
            netscape_cookie(".bilibili.com", "OLD", "expired-value", now - 60),
            netscape_cookie(".example.com", "OTHER", "other-value", now + 3600),
            netscape_cookie(".evilbilibili.com", "LOOKALIKE", "wrong-domain", now + 3600),
        )) + "\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = Path(temp_dir) / "cookies.txt"
            cookie_file.write_text(text, encoding="utf-8")
            session = requests.Session()
            result = auth.configure_session(session, "cookies", cookie_file, "bilibili")

        self.assertEqual(result, {"auth_mode": "cookies", "cookies_loaded": True})
        self.assertEqual({cookie.name for cookie in session.cookies}, {"SESSDATA", "buvid3"})

    def test_exported_httponly_domain_session_cookie_roundtrips(self):
        browser_cookie = {
            "domain": ".bilibili.com",
            "httpOnly": True,
            "secure": True,
            "path": "/",
            "expires": -1,
            "name": "SESSION_TEST",
            "value": "test-only-placeholder",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = Path(temp_dir) / "session.txt"
            cookie_file.write_text(
                "# Netscape HTTP Cookie File\n" + login_session.netscape_line(browser_cookie) + "\n",
                encoding="utf-8",
            )

            parsed_jar = MozillaCookieJar(str(cookie_file))
            parsed_jar.load(ignore_discard=True, ignore_expires=True)
            parsed = list(parsed_jar)
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0].domain, ".bilibili.com")
            self.assertTrue(parsed[0].domain_initial_dot)
            self.assertTrue(parsed[0].domain_specified)
            self.assertTrue(parsed[0].has_nonstandard_attr("HTTPOnly"))
            self.assertIsNone(parsed[0].expires)

            session = requests.Session()
            result = auth.configure_session(session, "cookies", cookie_file, "bilibili")
            loaded = list(session.cookies)

        self.assertEqual(result, {"auth_mode": "cookies", "cookies_loaded": True})
        self.assertEqual(len(loaded), 1)
        self.assertIsNone(loaded[0].expires)

    def test_empty_cookie_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = Path(temp_dir) / "empty.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with self.assertRaises(auth.AuthConfigurationError):
                auth.configure_session(requests.Session(), "cookies", cookie_file)

    def test_expired_only_cookie_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = Path(temp_dir) / "expired.txt"
            cookie_file.write_text(
                "# Netscape HTTP Cookie File\n" +
                netscape_cookie(".bilibili.com", "OLD", "expired-value", int(time.time()) - 10) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(auth.AuthConfigurationError):
                auth.configure_session(requests.Session(), "cookies", cookie_file)

    def test_platform_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = Path(temp_dir) / "weibo.txt"
            cookie_file.write_text(
                "# Netscape HTTP Cookie File\n" +
                netscape_cookie(".weibo.com", "SUB", "value", int(time.time()) + 3600) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(auth.AuthConfigurationError):
                auth.configure_session(requests.Session(), "cookies", cookie_file, "bilibili")

    def test_loaded_cookie_does_not_clear_a_login_required_subtitle_status(self):
        result = collector.subtitle_availability(
            {"need_login_subtitle": True, "subtitle": {"subtitles": []}},
            auth_mode="cookies", cookies_loaded=True,
        )
        self.assertEqual(result["status"], "login_required")
        self.assertEqual(result["access_note"], "cookies_loaded_but_login_still_required")
        self.assertEqual(result["checked_access"], "explicit_cookies")


if __name__ == "__main__":
    unittest.main()
