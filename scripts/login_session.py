"""Export reusable platform cookies from an existing Chrome or isolated profile."""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from auth_support import PLATFORM_COOKIE_URLS, PLATFORM_URLS, cookie_matches_platform


class LoginSessionError(ValueError):
    pass


def local_cdp_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in {"http","https","ws","wss"} and
                 parsed.hostname in {"localhost","127.0.0.1","::1"} and
                 parsed.port is not None and 1 <= parsed.port <= 65535 and parsed.username is None and parsed.password is None and
                 not parsed.query and not parsed.fragment)
        if not valid:
            raise ValueError
    except (ValueError,TypeError):
        raise argparse.ArgumentTypeError("CDP 地址只接受有端口的本机 localhost/127.0.0.1/[::1] 地址") from None
    return value


def netscape_line(cookie: dict) -> str:
    domain = cookie["domain"]
    domain_flag = "TRUE" if domain.startswith(".") else "FALSE"
    if cookie.get("httpOnly"):
        domain = "#HttpOnly_" + domain
    expires = cookie.get("expires", -1)
    expires = str(int(expires)) if expires and expires > 0 else ""
    fields = [domain, domain_flag,
              cookie.get("path") or "/",
              "TRUE" if cookie.get("secure") else "FALSE", expires,
              cookie["name"], cookie["value"]]
    if any("\t" in field or "\r" in field or "\n" in field for field in fields):
        raise ValueError("cookie field cannot be represented in Netscape format")
    return "\t".join(fields)


def export_platform_cookies(context, platform: str, cookie_path: Path) -> int:
    now = time.time()
    cookies = [cookie for cookie in context.cookies(urls=PLATFORM_COOKIE_URLS[platform])
               if cookie_matches_platform(cookie.get("domain", ""), platform)
               and (cookie.get("expires", -1) <= 0 or cookie["expires"] > now)]
    if not cookies:
        raise LoginSessionError("没有找到未过期的该平台 Cookie；请先在所连接的 Chrome 中正常登录")
    if platform == "bilibili" and not any(cookie.get("name") == "SESSDATA" and cookie.get("value") for cookie in cookies):
        raise LoginSessionError("未找到 B 站 SESSDATA 登录 Cookie；请先在所连接的 Chrome 中登录 B 站，原 Cookie 文件保持不变")
    contents = "# Netscape HTTP Cookie File\n"
    contents += "# Treat this file as a password; it is stored only in .secrets.\n"
    contents += "\n".join(netscape_line(cookie) for cookie in cookies) + "\n"
    cookie_path.parent.mkdir(parents=True,exist_ok=True)
    temporary = cookie_path.with_name(cookie_path.name + "." + uuid.uuid4().hex + ".part")
    try:
        temporary.write_text(contents,encoding="utf-8",newline="")
        try:
            os.chmod(temporary,0o600)
        except OSError:
            pass
        temporary.replace(cookie_path)
    finally:
        temporary.unlink(missing_ok=True)
    return len(cookies)


def export_from_existing(playwright, endpoint: str, platform: str, cookie_path: Path, timeout_ms: int) -> int:
    """Attach only; never launch/navigate/close the user's browser or its pages."""
    browser = playwright.chromium.connect_over_cdp(endpoint,timeout=timeout_ms)
    contexts = browser.contexts
    if not contexts:
        raise LoginSessionError("已连接 Chrome，但没有可复用的现有浏览器上下文")
    return export_platform_cookies(contexts[0],platform,cookie_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=sorted(PLATFORM_URLS))
    parser.add_argument("--channel", choices=("msedge", "chrome"), default="chrome",
                        help="不指定 --cdp-url 时启动的浏览器；默认 chrome")
    parser.add_argument("--cdp-url",type=local_cdp_url,
                        help="连接已打开的本机 Chrome，不新建窗口；例如 ws://127.0.0.1:9222/devtools/browser")
    parser.add_argument("--timeout",type=int,default=30,help="CDP 连接超时秒数，默认 30")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 60:
        parser.error("--timeout 必须为 1 到 60 秒")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 Playwright；请先安装 playwright Python 包", file=sys.stderr)
        return 1

    root = Path(__file__).resolve().parents[1]
    secrets_dir = root / ".secrets"
    profile_dir = secrets_dir / f"browser-profile-{args.platform}-{args.channel}"
    cookie_path = secrets_dir / f"{args.platform}.cookies.txt"
    context = None
    try:
        secrets_dir.mkdir(parents=True, exist_ok=True)
        if not args.cdp_url:
            profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(secrets_dir, 0o700)
            if not args.cdp_url:
                os.chmod(profile_dir, 0o700)
        except OSError:
            pass

        with sync_playwright() as playwright:
            if args.cdp_url:
                print("连接已打开的 Chrome；若 Chrome 显示远程连接确认，请在浏览器中确认。",flush=True)
                count = export_from_existing(playwright,args.cdp_url,args.platform,cookie_path,args.timeout*1000)
                print(f"已保存 {count} 条该平台 Cookie：{cookie_path}")
                print("未新建窗口或标签页；断开连接后保留你的 Chrome。后续采集直接复用 Cookie 文件，无需再运行登录助手。")
                return 0
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir), channel=args.channel, headless=False
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(PLATFORM_URLS[args.platform], wait_until="domcontentloaded", timeout=60000)
            print(f"已打开 {args.platform} 登录页。请在浏览器中自行登录；完成后回到此终端按 Enter。")
            print("此助手使用独立浏览器配置，不读取或接管你现有的浏览器会话，也不会处理验证码。")
            input()

            count = export_platform_cookies(context,args.platform,cookie_path)
            print(f"已导出 {count} 条该平台 Cookie：{cookie_path}")
            print("导出只表示浏览器提供了 Cookie，不保证该会话仍有效或拥有目标内容权限。")
            print("后续直接运行带 --auth cookies 的采集命令即可，不需要每次重新打开登录窗口。")
            return 0
    except KeyboardInterrupt:
        print("已取消；没有导出 Cookie。", file=sys.stderr)
        return 130
    except LoginSessionError as error:
        print(str(error),file=sys.stderr)
        return 1
    except Exception as error:
        # Avoid surfacing browser/parser exception text that could contain secrets.
        print(f"登录助手失败（{type(error).__name__}）", file=sys.stderr)
        if args.cdp_url:
            print("请检查现有 Chrome 的远程调试是否开启、端口/地址是否一致，并完成 Chrome 的连接确认；不会自动启动新窗口。",file=sys.stderr)
        return 1
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
