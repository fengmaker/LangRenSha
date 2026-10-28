"""Collect Bilibili metadata, visible subtitles, and an optional separate audio track.

Authentication defaults to anonymous; Netscape cookies are loaded only when
explicitly selected. Never falls back to a video or muxed stream. Requires
requests. Outputs remain under the explicitly selected output folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

# The script is also loaded from its file path by the repository's tests.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from auth_support import AuthConfigurationError, configure_session


class CollectionError(RuntimeError):
    pass


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_bvid(value: str) -> str:
    found = re.search(r"BV[0-9A-Za-z]{10}(?![0-9A-Za-z])", value)
    if not found:
        raise CollectionError("需要完整的 BVID 或包含 BVID 的视频链接")
    return found.group(0)


def select_audio(play_info: dict, max_bitrate: int) -> dict:
    """Choose an actual DASH audio/mp4 track; reject video/muxed fallback."""
    candidates = []
    for item in (play_info.get("dash") or {}).get("audio") or []:
        mime = item.get("mimeType") or item.get("mime_type") or ""
        url = item.get("baseUrl") or item.get("base_url")
        if mime == "audio/mp4" and url and int(item.get("bandwidth") or 0) > 0:
            candidates.append(item)
    if not candidates:
        raise CollectionError("未提供独立 audio/mp4 音轨；停止，不回退下载视频")
    within_limit = [x for x in candidates if int(x["bandwidth"]) <= max_bitrate]
    if not within_limit:
        raise CollectionError("独立音轨码率均超过上限；请明确提高 --max-bitrate")
    return max(within_limit, key=lambda x: int(x["bandwidth"]))


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def subtitle_availability(player_data: dict, auth_mode: str = "none",
                          cookies_loaded: bool = False) -> dict:
    tracks = (player_data.get("subtitle") or {}).get("subtitles") or []
    needs_login = player_data.get("need_login_subtitle")
    status = "visible_tracks" if tracks else "login_required" if needs_login is True else "none_visible"
    cookies_used = auth_mode == "cookies" and cookies_loaded
    result = {"status": status, "count": len(tracks), "need_login_subtitle": needs_login,
              "checked_access": "explicit_cookies" if cookies_used else "public_without_cookies",
              "tracks": []}
    if needs_login is True and cookies_used:
        result["access_note"] = "cookies_loaded_but_login_still_required"
    return result


def subtitle_source_matches(player_data: dict, bvid: str, cid: int, aid: int | None) -> bool:
    return all(player_data.get(key) is None or str(player_data[key]) == str(expected)
               for key,expected in [("bvid",bvid),("cid",cid),("aid",aid)] if expected is not None)


def is_chinese_subtitle(language: str | None) -> bool:
    code = str(language or "").lower().replace("_", "-")
    return code in {"zh", "ai-zh"} or code.startswith(("zh-", "ai-zh-"))


def validate_cues(document: dict) -> list[dict]:
    cues = document.get("body")
    if not isinstance(cues, list) or not cues:
        raise ValueError("平台字幕缺少有效 body")
    for item in cues:
        if (not isinstance(item, dict) or not isinstance(item.get("content"), str) or
                type(item.get("from")) not in {int, float} or type(item.get("to")) not in {int, float} or
                not 0 <= item["from"] <= item["to"]):
            raise ValueError("字幕段落缺少合法时间戳或文字")
    return cues


class Collector:
    def __init__(self, auth_mode: str = "none", cookies_file: Path | None = None, quiet: bool = False) -> None:
        self.quiet = quiet
        self.session = requests.Session()
        self.authentication = configure_session(
            self.session, auth_mode=auth_mode, cookies_file=cookies_file, platform="bilibili"
        )
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com/",
        })
        self.last_request = 0.0

    def api(self, path: str, params: dict) -> dict:
        delay = 1.0 - (time.monotonic() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        self.last_request = time.monotonic()
        response = self.session.get("https://api.bilibili.com" + path, params=params, timeout=25)
        if response.status_code != 200:
            raise CollectionError(f"接口返回 HTTP {response.status_code}，停止，不自动绕过访问限制")
        data = response.json()
        if data.get("code") != 0:
            raise CollectionError(f"接口业务状态 {data.get('code')}，停止；可能需要正常登录或稍后重试")
        return data

    def download(self, url: str, target: Path, max_bytes: int) -> dict:
        parsed = urlsplit(url)
        if parsed.scheme != "https":
            raise CollectionError("只接受 HTTPS 媒体地址")
        # Signed media addresses are transient and are never printed or persisted.
        temporary = target.with_suffix(target.suffix + ".part")
        size = 0
        started = time.monotonic()
        last_progress = started
        with self.session.get(url, stream=True, timeout=(15, 35)) as response:
            if response.status_code != 200:
                raise CollectionError(f"音轨返回 HTTP {response.status_code}，停止")
            expected = int(response.headers.get("Content-Length") or 0)
            if expected > max_bytes:
                raise CollectionError("音轨大小超过设定上限，未下载")
            with temporary.open("wb") as output:
                for block in response.iter_content(chunk_size=128 * 1024):
                    if not block:
                        continue
                    size += len(block)
                    if size > max_bytes or time.monotonic() - started > 600:
                        raise CollectionError("音轨超过大小/时间上限；保留 .part，不视为完成")
                    output.write(block)
                    if not self.quiet and time.monotonic() - last_progress >= 15:
                        print(f"已接收独立音轨 {size / 1024 / 1024:.1f} MiB", flush=True)
                        last_progress = time.monotonic()
        if size == 0 or (expected and size != expected):
            raise CollectionError("音轨长度不完整；保留 .part，不视为完成")
        temporary.replace(target)
        return {"file": target.name, "bytes": size, "sha256": sha256_file(target)}

    def collect(self, bvid: str, page_number: int, out: Path, audio: bool,
                max_bitrate: int, max_bytes: int, expected_owner: str | None = None,
                *, subtitles_first: bool = False) -> dict:
        folder = out / bvid / f"p{page_number:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        manifest_path = folder / "manifest.json"
        previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        raw = self.api("/x/web-interface/view", {"bvid": bvid})
        save_json(folder / "metadata.raw.json", raw)
        view = raw["data"]
        owner_mid = str((view.get("owner") or {}).get("mid", ""))
        if expected_owner is not None and owner_mid != str(expected_owner):
            raise CollectionError("投稿者 UID 与指定官方账号不一致，未下载音轨")
        if view["bvid"] != bvid:
            raise CollectionError("元数据的 BVID 与请求的视频不一致")
        page = next((p for p in view.get("pages", []) if p.get("page") == page_number), None)
        if page is None:
            raise CollectionError(f"没有第 {page_number} 个分 P")
        cid = page["cid"]
        manifest = {
            "schema_version": 1,
            "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            "bvid": bvid, "aid": view.get("aid"), "cid": cid, "page": page_number,
            "url": f"https://www.bilibili.com/video/{bvid}/?p={page_number}",
            "title": view.get("title"), "part": page.get("part"),
            "duration_seconds": page.get("duration"),
            "owner": {"mid": (view.get("owner") or {}).get("mid"),
                      "name": (view.get("owner") or {}).get("name")},
            "published_timestamp": view.get("pubdate"),
            "game_facts_reviewed": False,
            "authentication": dict(self.authentication),
            "access_mode": "public_without_cookies" if self.authentication["auth_mode"] == "none"
            else "explicit_cookies",
            "source_check": {"expected_owner_mid": str(expected_owner) if expected_owner else None,
                             "actual_owner_mid": owner_mid,
                             "owner_matches": owner_mid == str(expected_owner) if expected_owner else None},
        }
        # Keep a successful audio acquisition record across metadata refreshes.
        if previous.get("cid") == cid and previous.get("audio"):
            manifest["audio"] = previous["audio"]
        save_json(manifest_path, manifest)
        try:
            # Same current subtitle endpoint used by yt-dlp's Bilibili extractor.
            # Legacy /x/player/v2 was observed returning empty/short/stale tracks.
            endpoint = "/x/player/wbi/v2"
            captions = self.api(endpoint, {"aid": view.get("aid"), "cid": cid})
            player_data = captions["data"]
            if not subtitle_source_matches(player_data,bvid,cid,view.get("aid")):
                raise CollectionError("字幕索引的 BV/CID/AID 与目标媒体不一致")
            tracks = (player_data.get("subtitle") or {}).get("subtitles") or []
            manifest["subtitles"] = subtitle_availability(
                player_data, self.authentication["auth_mode"], self.authentication["cookies_loaded"]
            )
            manifest["subtitles"]["index_endpoint"] = endpoint
            manifest["subtitles"]["requests"] = []
            for index, track in enumerate(tracks, start=1):
                request_record = {"id":track.get("id"),"language":track.get("lan"),"status":"not_attempted"}
                manifest["subtitles"]["requests"].append(request_record)
                if not is_chinese_subtitle(track.get("lan")):
                    request_record["status"] = "not_selected_language"
                    continue
                url = track.get("subtitle_url")
                if not url:
                    request_record["status"] = "no_download_url"
                    continue
                if url.startswith("//"):
                    url = "https:" + url
                host = urlsplit(url).hostname or ""
                if urlsplit(url).scheme == "http" and (host.endswith(".hdslb.com") or host.endswith(".bilibili.com")):
                    url = "https:"+url.split(":",1)[1]
                if urlsplit(url).scheme != "https" or not (host.endswith(".hdslb.com") or host.endswith(".bilibili.com")):
                    request_record["status"] = "unsupported_source_url"
                    continue
                response = self.session.get(url, timeout=25)
                if response.status_code != 200:
                    request_record.update(status="http_error",http_status=response.status_code)
                    continue
                filename = f"subtitle.{index:02d}.raw.json"
                document = response.json()
                validate_cues(document)
                save_json(folder / filename, document)
                request_record.update(status="downloaded",http_status=200,file=filename)
                manifest["subtitles"]["tracks"].append({"id": track.get("id"),
                                                       "platform": "bilibili",
                                                       "language": track.get("lan"),
                                                       "language_description": track.get("lan_doc"),
                                                       "type": track.get("type"),
                                                       "is_lock": track.get("is_lock"),
                                                       "ai_type": track.get("ai_type"),
                                                       "ai_status": track.get("ai_status"),
                                                       "file": filename,
                                                       "provenance": "platform_visible_subtitle"})
        except (CollectionError, requests.RequestException, ValueError):
            manifest["subtitles"] = {"status": "unavailable_in_this_request"}
            save_json(manifest_path, manifest)
            if subtitles_first:
                raise
        save_json(manifest_path, manifest)
        if subtitles_first:
            subtitles = manifest["subtitles"]
            if any(is_chinese_subtitle(item["language"]) and item["status"] != "downloaded"
                   for item in subtitles["requests"]):
                raise CollectionError("中文轨存在但未成功下载；停止，不按无字幕下载音频")
            if subtitles["tracks"]:
                audio = False
            elif subtitles["need_login_subtitle"] is True:
                raise CollectionError("字幕需要有效登录；停止，不按无字幕下载音频")
        if audio:
            cached = manifest.get("audio") or {}
            cached_path = folder / "audio.m4a"
            if (cached.get("sha256") and cached_path.exists()
                    and sha256_file(cached_path) == cached["sha256"]):
                if not self.quiet:
                    print("音轨已存在且哈希一致，跳过下载", flush=True)
            else:
                play = self.api("/x/player/playurl", {"bvid": bvid, "cid": cid,
                                                       "fnval": 16, "fnver": 0, "fourk": 0})["data"]
                chosen = select_audio(play, max_bitrate)
                manifest["available_audio_formats"] = [
                    {"id": x.get("id"), "bitrate": x.get("bandwidth"),
                     "mime_type": x.get("mimeType") or x.get("mime_type"), "codecs": x.get("codecs")}
                    for x in (play.get("dash") or {}).get("audio") or []
                ]
                save_json(manifest_path, manifest)
                url = chosen.get("baseUrl") or chosen.get("base_url")
                acquisition = self.download(url, cached_path, max_bytes)
                manifest["audio"] = {**acquisition, "format_id": chosen.get("id"),
                                     "bitrate": chosen.get("bandwidth"),
                                     "codecs": chosen.get("codecs"), "video_downloaded": False}
        save_json(manifest_path, manifest)
        if not self.quiet:
            print(json.dumps({"bvid": bvid, "title": manifest["title"], "cid": cid,
                          "duration_seconds": manifest["duration_seconds"],
                          "subtitle_status": manifest["subtitles"]["status"],
                              "audio": manifest.get("audio"), "output": str(folder)}, ensure_ascii=False), flush=True)
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos", nargs="+", help="BVID 或视频 URL")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--out", type=Path, default=Path("data/raw/bilibili"))
    media = parser.add_mutually_exclusive_group()
    media.add_argument("--audio", action="store_true", help="显式下载独立音轨；默认仅索引和可见字幕")
    media.add_argument("--subtitles-first", action="store_true",
                       help="先取中文字幕；查询成功且没有可访问中文轨时才下载独立音频")
    parser.add_argument("--auth", choices=("none", "cookies"), default="none",
                        help="认证模式；默认 none，不读取任何 Cookie")
    parser.add_argument("--cookies-file", type=Path,
                        help="--auth cookies 时显式提供 Netscape 格式 Cookie 文件")
    parser.add_argument("--max-bitrate", type=int, default=128000)
    parser.add_argument("--max-mib", type=int, default=200)
    parser.add_argument("--expected-owner", help="若指定，投稿者 UID 不符即停止，不下载音轨")
    args = parser.parse_args()
    if args.page < 1 or args.max_bitrate < 1 or args.max_mib < 1:
        parser.error("页码、码率和大小上限必须为正数")
    try:
        collector = Collector(args.auth, args.cookies_file)
    except AuthConfigurationError as error:
        parser.error(str(error))
    failed = False
    for value in args.videos:
        try:
            collector.collect(parse_bvid(value), args.page, args.out.resolve(), args.audio or args.subtitles_first,
                              args.max_bitrate, args.max_mib * 1024 * 1024, args.expected_owner,
                              subtitles_first=args.subtitles_first)
        except (CollectionError, requests.RequestException, ValueError, OSError) as error:
            # Network exception strings can contain signed URLs. Print only type.
            message = str(error) if isinstance(error, CollectionError) else type(error).__name__
            print(f"采集停止：{message}", file=sys.stderr)
            failed = True
            break  # Do not continue a batch after a platform/access/network error.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
