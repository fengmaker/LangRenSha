"""Explicit, opt-in loading of platform-scoped Netscape cookies."""

from __future__ import annotations

from copy import copy
import time
from http.cookiejar import MozillaCookieJar
from pathlib import Path


class AuthConfigurationError(ValueError):
    """A safe-to-display authentication configuration error."""


# Cookie domains are kept explicit so one platform's session cannot be sent to
# another platform's hosts. The browser login helper shares this allowlist.
PLATFORM_DOMAINS = {
    "bilibili": ("bilibili.com", "hdslb.com"),
    "douyin": ("douyin.com", "iesdouyin.com"),
    "weibo": ("weibo.com", "weibo.cn"),
}

PLATFORM_URLS = {
    "bilibili": "https://www.bilibili.com/",
    "douyin": "https://www.douyin.com/",
    "weibo": "https://weibo.com/",
}

# Browser exports request only cookies affecting these platform URLs. In an
# attached personal browser, never retrieve the whole browser's cookie jar.
PLATFORM_COOKIE_URLS = {
    "bilibili": ["https://www.bilibili.com/", "https://api.bilibili.com/"],
    "douyin": ["https://www.douyin.com/"],
    "weibo": ["https://weibo.com/", "https://m.weibo.cn/"],
}


def cookie_matches_platform(cookie_domain: str, platform: str) -> bool:
    """Return whether a cookie domain belongs to the named platform."""
    allowed_domains = PLATFORM_DOMAINS.get(platform)
    if not allowed_domains:
        return False
    domain = cookie_domain.strip().lower().lstrip(".").rstrip(".")
    return any(domain == allowed or domain.endswith("." + allowed)
               for allowed in allowed_domains)


def configure_session(session, auth_mode: str = "none", cookies_file=None,
                      platform: str = "bilibili") -> dict:
    """Configure a requests-like session using no auth or explicit cookies.

    Anonymous mode intentionally returns before inspecting ``cookies_file``.
    The result describes only the selected mode and whether cookies were
    loaded; it does not validate that a loaded session is signed in or
    authorized for any particular resource.
    """
    if auth_mode == "none":
        return {"auth_mode": "none", "cookies_loaded": False}
    if auth_mode != "cookies":
        raise AuthConfigurationError("认证模式必须是 none 或 cookies")
    if platform not in PLATFORM_DOMAINS:
        raise AuthConfigurationError("不支持的平台；当前支持 bilibili、douyin、weibo")
    if cookies_file is None:
        raise AuthConfigurationError("cookies 模式需要指定 Netscape 格式 Cookie 文件")

    jar = MozillaCookieJar(str(Path(cookies_file)))
    try:
        # Load expired entries too, then discard them ourselves so the same
        # explicit filtering applies on every Python version.
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as error:
        # Cookie parser exceptions can include file contents. Never forward them.
        raise AuthConfigurationError("无法读取 Netscape Cookie 文件") from None

    now = time.time()
    accepted = [cookie for cookie in jar
                if cookie_matches_platform(cookie.domain, platform)
                and (cookie.expires is None or cookie.expires > now)]
    if not accepted:
        raise AuthConfigurationError(
            "Cookie 文件为空，或没有当前平台的未过期 Cookie"
        )

    for cookie in accepted:
        session.cookies.set_cookie(copy(cookie))
    return {"auth_mode": "cookies", "cookies_loaded": True}
