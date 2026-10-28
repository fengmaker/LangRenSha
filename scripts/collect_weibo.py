"""Collect a bounded sample of publicly visible Weibo posts.

The mobile web endpoints used here are undocumented and may change or require
normal login. The collector never retries a login wall, captcha, or rate limit.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "raw" / "weibo"
MOBILE_ROOT = "https://m.weibo.cn"
MAX_PAGES_HARD_LIMIT = 50
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGES_PER_POST = 36
_BEIJING = timezone(timedelta(hours=8))


class CollectionError(RuntimeError):
    def __init__(self, message: str, state: str = "blocked", reason: str = "request_failed"):
        super().__init__(message)
        self.state = state
        self.reason = reason


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_post_id(value: str) -> str:
    """Accept a Weibo post ID or a supported public post URL."""
    candidate = value.strip()
    if candidate.startswith(("http://", "https://")):
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").lower()
        if host not in {"weibo.com", "www.weibo.com", "m.weibo.cn"}:
            raise CollectionError("--post 只接受微博公开帖子链接或帖子 ID", reason="invalid_post")
        parts = [part for part in parsed.path.split("/") if part]
        candidate = parts[-1] if parts else ""
    if not re.fullmatch(r"[A-Za-z0-9]{6,32}", candidate):
        raise CollectionError("无法从 --post 解析微博帖子 ID", reason="invalid_post")
    return candidate


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期格式应为 YYYY-MM-DD") from exc


def post_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.astimezone(_BEIJING).date() if parsed.utcoffset() is not None else parsed.date()
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.astimezone(_BEIJING).date() if parsed.utcoffset() is not None else parsed.date()
    except ValueError:
        return None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.parts.append("\n")


def plain_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    parser = _TextExtractor()
    parser.feed(html.unescape(value))
    return re.sub(r"[ \t\r\f\v]+", " ", " ".join(parser.parts)).strip()


def parse_detail_html(source: str) -> dict | None:
    """Extract the mblog object embedded in Weibo's rendered detail page."""
    match = re.search(r"\$render_data\s*=\s*(\[.*?\])\s*\[0\]", source, re.DOTALL)
    if not match:
        return None
    try:
        rendered = json.loads(match.group(1))
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(rendered, list) or not rendered or not isinstance(rendered[0], dict):
        return None
    first = rendered[0]
    status = first.get("status")
    if isinstance(status, dict):
        return status
    if isinstance(first.get("mblog"), dict):
        return first["mblog"]
    return None


def timeline_statuses(data: dict) -> list[dict]:
    """Return only ordinary post cards; ignore ads, profile cards, and other cards."""
    cards = data.get("cards")
    if not isinstance(cards, list):
        return []
    result: list[dict] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        card_type = card.get("card_type")
        if card_type == 9 and isinstance(card.get("mblog"), dict):
            result.append(card["mblog"])
        elif card_type == 11 and isinstance(card.get("card_group"), list):
            for nested in card["card_group"]:
                if (isinstance(nested, dict) and nested.get("card_type") == 9
                        and isinstance(nested.get("mblog"), dict)):
                    result.append(nested["mblog"])
    return result


def _image_url(picture: object) -> str | None:
    if not isinstance(picture, dict):
        return None
    for key in ("original", "large", "bmiddle"):
        item = picture.get(key)
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            url = item["url"]
            break
    else:
        url = picture.get("url") if isinstance(picture.get("url"), str) else None
    if not url:
        return None
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "sinaimg.cn" or host.endswith(".sinaimg.cn")):
        return None
    return url


def image_urls(mblog: dict) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    pictures = mblog.get("pics") or []
    infos = mblog.get("pic_infos")
    if isinstance(infos, dict) and isinstance(mblog.get("pic_ids"), list):
        pictures = [infos.get(str(picture_id)) for picture_id in mblog["pic_ids"]]
    for picture in pictures:
        candidate = _image_url(picture)
        if candidate and candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    return found


def _safe_source_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def normalize_post(mblog: dict, expected_uid: str | None = None) -> dict:
    user = mblog.get("user") if isinstance(mblog.get("user"), dict) else {}
    uid_value = user.get("idstr", user.get("id"))
    uid = str(uid_value) if uid_value is not None else ""
    post_id = str(mblog.get("idstr", mblog.get("id", "")))
    created = mblog.get("created_at")
    pub_date = post_date(created)
    repost = mblog.get("retweeted_status")
    repost_user = repost.get("user") if isinstance(repost, dict) else {}
    repost_uid = ""
    if isinstance(repost_user, dict):
        value = repost_user.get("idstr", repost_user.get("id"))
        repost_uid = str(value) if value is not None else ""
    return {
        "post_id": post_id,
        "post_url": f"{MOBILE_ROOT}/detail/{post_id}" if post_id else None,
        "author_uid": uid,
        "author_name": user.get("screen_name"),
        "created_at_source": created,
        "published_date": pub_date.isoformat() if pub_date else None,
        "text": plain_text(mblog.get("text")),
        "is_repost": isinstance(repost, dict),
        "reposted_author_uid": repost_uid or None,
        "expected_author_uid": expected_uid,
        "raw_file": f"posts/{post_id}.json" if post_id else None,
        "images": [{"source_url": _safe_source_url(url), "status": "not_downloaded"}
                   for url in image_urls(mblog)],
    }


def keyword_matches(text: str, keywords: list[str]) -> list[str]:
    folded = text.casefold()
    return [word for word in keywords if word.casefold() in folded]


def _failure_from_response(response: requests.Response, body: str) -> CollectionError:
    status_code = response.status_code
    lower = body[:6000].lower()
    response_url = urlsplit(getattr(response, "url", ""))
    location = response.headers.get("Location", "") if hasattr(response, "headers") else ""
    redirect_url = urlsplit(urljoin(getattr(response, "url", ""), location)) if location else None
    redirect_host = redirect_url.netloc.lower() if redirect_url else ""
    redirect_path = redirect_url.path.lower() if redirect_url else ""
    if ("passport.weibo.com" in response_url.netloc.lower()
            or "passport.weibo.com" in redirect_host
            or "login" in redirect_path
            or any(
                marker in lower for marker in ("passport/login", "账号登录", "请先登录", "未登录", "login required"))):
        return CollectionError("微博返回登录页或登录要求", "login_required", "login_required")
    if any(marker in lower for marker in ("captcha", "verify", "验证码", "访问频繁", "操作频繁", "risk control")):
        return CollectionError("微博返回验证或访问限制页面", "blocked", "rate_or_verification_wall")
    if status_code in (401, 407):
        return CollectionError(f"微博返回 HTTP {status_code}", "login_required", "login_required")
    if status_code in (403, 429, 451, 432):
        return CollectionError(f"微博返回 HTTP {status_code}", "blocked", "http_access_limited")
    if status_code != 200:
        return CollectionError(f"微博返回 HTTP {status_code}", "blocked", "http_error")
    return CollectionError("微博响应无法解析为可见帖子数据", "partial", "unrecognized_response")


def configure_auth(session: requests.Session, auth_mode: str, cookies_file: str | None) -> None:
    if auth_mode == "none" and cookies_file:
        raise CollectionError("指定 --cookies-file 时必须同时使用 --auth cookies", reason="invalid_auth_args")
    from auth_support import AuthConfigurationError, configure_session
    try:
        configure_session(session, auth_mode=auth_mode, cookies_file=cookies_file, platform="weibo")
    except AuthConfigurationError as exc:
        # Authentication helper exceptions may contain a path or credential; expose only the type.
        raise CollectionError(f"认证配置失败（{type(exc).__name__}）", reason="auth_configuration_failed") from None


class WeiboCollector:
    def __init__(self, session: requests.Session | None = None, sleep=time.sleep, request_interval: float = 1.0):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
            "Referer": "https://weibo.com/",
            "Accept": "text/html,application/json,application/xhtml+xml,*/*",
        })
        self.sleep = sleep
        self.last_request = 0.0
        self.request_interval = max(1.0, request_interval)

    def _get(self, url: str, params: dict | None = None, *, stream: bool = False) -> requests.Response:
        delay = self.request_interval - (time.monotonic() - self.last_request)
        if delay > 0:
            self.sleep(delay)
        self.last_request = time.monotonic()
        try:
            response = self.session.get(url, params=params, timeout=25,
                                        allow_redirects=False, stream=stream)
        except requests.RequestException as exc:
            raise CollectionError(f"网络请求失败（{type(exc).__name__}）", "blocked", "network_error") from None
        return response

    def get_post(self, post_id: str) -> dict:
        response = self._get(f"{MOBILE_ROOT}/detail/{post_id}")
        source = response.text if isinstance(response.text, str) else ""
        if response.status_code != 200 or not parse_detail_html(source):
            raise _failure_from_response(response, source)
        post = parse_detail_html(source)
        if not post:
            raise CollectionError("帖子详情页未包含可解析的公开正文", "partial", "detail_not_found")
        return post

    def get_timeline_page(self, uid: str, since_id: str) -> dict:
        response = self._get(f"{MOBILE_ROOT}/api/container/getIndex",
                             {"jumpfrom": "weibocom", "type": "uid", "value": uid,
                              "containerid": f"107603{uid}", "since_id": since_id})
        body = response.text if isinstance(response.text, str) else ""
        if response.status_code != 200:
            raise _failure_from_response(response, body)
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            raise _failure_from_response(response, body) from None
        if not isinstance(payload, dict):
            raise CollectionError("微博列表响应结构异常", "partial", "unrecognized_response")
        if payload.get("ok") != 1:
            message = str(payload.get("msg", ""))
            if any(term in message.casefold() for term in ("login", "登录", "未登录", "passport")):
                raise CollectionError("微博列表接口要求登录", "login_required", "login_required")
            raise CollectionError("微博列表接口拒绝请求", "blocked", "api_rejected")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
            raise CollectionError("微博响应没有可确认的列表页数据", "partial", "missing_cards")
        return data

    def get_long_text(self, post_id: str) -> dict:
        response = self._get(f"{MOBILE_ROOT}/statuses/extend", {"id": post_id})
        body = response.text if isinstance(response.text, str) else ""
        if response.status_code != 200:
            raise _failure_from_response(response, body)
        try:
            payload = response.json()
        except ValueError:
            raise _failure_from_response(response, body) from None
        data = payload.get("data") if isinstance(payload, dict) else None
        if (not isinstance(payload, dict) or payload.get("ok") != 1
                or not isinstance(data, dict) or not isinstance(data.get("longTextContent"), str)
                or not data["longTextContent"].strip()):
            raise _failure_from_response(response, body)
        return payload

    def get_post_data(self, post_id: str) -> dict:
        response = self._get("https://weibo.com/ajax/statuses/show", {"id": post_id})
        body = response.text if isinstance(response.text, str) else ""
        if response.status_code != 200:
            raise _failure_from_response(response, body)
        try:
            payload = response.json()
        except ValueError:
            raise _failure_from_response(response, body) from None
        if (not isinstance(payload, dict) or str(payload.get("idstr") or payload.get("id")) != post_id):
            raise _failure_from_response(response, body)
        return payload

    def download_image(self, url: str, target: Path) -> dict:
        response: requests.Response | None = None
        temporary = target.with_suffix(target.suffix + ".part")
        try:
            response = self._get(url, stream=True)
            if response.status_code != 200:
                return {"status": "download_failed", "reason": f"http_{response.status_code}"}
            content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0]
            if not content_type.startswith("image/"):
                return {"status": "download_failed", "reason": "not_an_image"}
            declared_size = None
            raw_length = response.headers.get("Content-Length")
            if raw_length is not None:
                try:
                    declared_size = int(raw_length)
                except (TypeError, ValueError):
                    declared_size = None
            if declared_size is not None and declared_size > MAX_IMAGE_BYTES:
                return {"status": "skipped", "reason": "size_limit", "max_bytes": MAX_IMAGE_BYTES,
                        "declared_bytes": declared_size}
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            written = 0
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    next_size = written + len(chunk)
                    if next_size > MAX_IMAGE_BYTES:
                        return {"status": "skipped", "reason": "size_limit",
                                "max_bytes": MAX_IMAGE_BYTES, "observed_bytes": next_size}
                    stream.write(chunk)
                    digest.update(chunk)
                    written = next_size
            if declared_size is not None and written != declared_size:
                return {"status": "download_failed", "reason": "content_length_mismatch"}
            if written == 0:
                return {"status": "download_failed", "reason": "empty_body"}
            temporary.replace(target)
            return {"status": "downloaded", "file": str(target.relative_to(self.output_dir)),
                    "size_bytes": written, "content_type": content_type, "sha256": digest.hexdigest()}
        except requests.RequestException as exc:
            return {"status": "download_failed", "reason": type(exc).__name__}
        except OSError as exc:
            return {"status": "download_failed", "reason": type(exc).__name__}
        finally:
            if response is not None:
                response.close()
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def save_post(self, raw: dict, normalized: dict, run_dir: Path, download_images: bool,
                  image_source: dict | None = None) -> dict:
        post_id = normalized["post_id"]
        raw_path = run_dir / normalized["raw_file"]
        if not raw_path.is_file() or json.loads(raw_path.read_text(encoding="utf-8")) != raw:
            save_json(raw_path, raw)
        urls = image_urls(image_source if image_source is not None else raw)
        for index, url in enumerate(urls):
            entry = normalized["images"][index]
            if not download_images:
                continue
            if entry.get("status") == "downloaded" and entry.get("file"):
                existing = (run_dir / entry["file"]).resolve()
                if not existing.is_relative_to(run_dir.resolve()):
                    raise CollectionError("图片路径超出采集目录", reason="invalid_manifest")
                if existing.is_file() and existing.stat().st_size == entry.get("size_bytes"):
                    with existing.open("rb") as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() == entry.get("sha256"):
                            continue
            if index >= MAX_IMAGES_PER_POST:
                entry.update({"status": "skipped", "reason": "image_count_limit"})
                continue
            path = urlsplit(url).path
            suffix = Path(path).suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                suffix = ".img"
            self.output_dir = run_dir
            entry["source_url"] = _safe_source_url(url)
            image_base = normalized.get("image_base")
            target = (run_dir / f"{image_base}_图{index + 1:02}{suffix}" if image_base else
                      run_dir / "images" / f"{post_id}_{index + 1}{suffix}")
            entry.update(self.download_image(url, target))
        return normalized

    def collect_exact(self, post_id: str, run_dir: Path, download_images: bool = False) -> dict:
        manifest = new_manifest("post", {"post_id": post_id})
        try:
            raw = self.get_post(post_id)
            normalized = normalize_post(raw)
            normalized = self.save_post(raw, normalized, run_dir, download_images)
            manifest["status"] = "collected" if normalized["post_id"] else "partial"
            manifest["posts"] = [normalized]
            manifest["counts"] = {"posts_saved": len(manifest["posts"])}
        except CollectionError as exc:
            manifest["status"] = exc.state
            manifest["termination_reason"] = exc.reason
            manifest["warnings"].append(str(exc))
        save_json(run_dir / "manifest.json", manifest)
        return manifest

    def collect_author(self, uid: str, since: date, until: date, keywords: list[str],
                       max_pages: int, run_dir: Path, download_images: bool = False) -> dict:
        manifest = new_manifest("author", {"uid": uid, "since": since.isoformat(),
                                            "until": until.isoformat(), "keywords": keywords,
                                            "max_pages": max_pages})
        pages: list[dict] = []
        posts: list[dict] = []
        seen_ids: set[str] = set()
        end_reason = "max_pages_reached"
        failure: CollectionError | None = None
        since_id = ""
        for page_number in range(1, max_pages + 1):
            try:
                data = self.get_timeline_page(uid, since_id)
            except CollectionError as exc:
                failure = exc
                end_reason = exc.reason
                break
            statuses = timeline_statuses(data)
            page_record = {"page": page_number, "cards_seen": len(data.get("cards", [])),
                           "status_cards": len(statuses), "target_author_posts": 0,
                           "in_date_window": 0, "keyword_candidates": 0,
                           "skipped_non_target": 0, "skipped_unparseable_date": 0,
                           "skipped_duplicate": 0}
            for raw in statuses:
                normalized = normalize_post(raw, expected_uid=uid)
                if normalized["author_uid"] != uid:
                    page_record["skipped_non_target"] += 1
                    continue
                page_record["target_author_posts"] += 1
                post_id = normalized["post_id"]
                if not post_id or post_id in seen_ids:
                    page_record["skipped_duplicate"] += 1
                    continue
                seen_ids.add(post_id)
                published = post_date(raw.get("created_at"))
                if published is None:
                    page_record["skipped_unparseable_date"] += 1
                    continue
                if not since <= published <= until:
                    continue
                page_record["in_date_window"] += 1
                matched = keyword_matches(normalized["text"], keywords)
                normalized["matched_keywords"] = matched
                normalized["keyword_candidate"] = bool(matched) if keywords else True
                if keywords and not matched:
                    continue
                page_record["keyword_candidates"] += 1
                posts.append(self.save_post(raw, normalized, run_dir, download_images))
            pages.append(page_record)
            # Never infer end-of-history from post dates: pinned posts may be out of order.
            has_more = data.get("has_more")
            if has_more is None:
                has_more = (data.get("cardlistInfo") or {}).get("has_more")
            if has_more is False or has_more == 0:
                end_reason = "api_end_marker"
                break
            if not statuses:
                end_reason = "empty_page_without_end_marker"
                break
            # A repeated full page is an API pagination boundary, not evidence of no older posts.
            current_signature = tuple(str(item.get("idstr", item.get("id", ""))) for item in statuses)
            if len(pages) > 1 and current_signature and current_signature == pages[-2].get("_signature"):
                end_reason = "repeated_page_boundary"
                pages[-1]["pagination_boundary"] = end_reason
                break
            pages[-1]["_signature"] = current_signature
            next_since_id = (data.get("cardlistInfo") or {}).get("since_id")
            next_since_id = str(next_since_id) if next_since_id is not None else ""
            if not next_since_id or next_since_id == "0" or next_since_id == since_id:
                end_reason = "cursor_missing_or_repeated"
                break
            since_id = next_since_id
        for page in pages:
            page.pop("_signature", None)
        if failure:
            manifest["status"] = failure.state if not pages else "partial"
            manifest["warnings"].append(str(failure))
        else:
            manifest["status"] = "partial"
        manifest["termination_reason"] = end_reason
        manifest["pages"] = pages
        manifest["posts"] = posts
        manifest["counts"] = {
            "pages_fetched": len(pages),
            "target_posts_seen": sum(page["target_author_posts"] for page in pages),
            "date_window_posts_seen": sum(page["in_date_window"] for page in pages),
            "keyword_candidates_saved": len(posts),
            "non_target_posts_skipped": sum(page["skipped_non_target"] for page in pages),
            "unparseable_dates_skipped": sum(page["skipped_unparseable_date"] for page in pages),
        }
        manifest["coverage_note"] = (
            "只代表本次可见分页样本；置顶/乱序、缺页、删除、搜索不可见或分页限制均可能造成遗漏。"
            "即使接口报告末页，也不能据此声称找全历史。"
        )
        save_json(run_dir / "manifest.json", manifest)
        return manifest


def new_manifest(mode: str, request_info: dict) -> dict:
    return {
        "schema_version": 1,
        "mode": mode,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "https://m.weibo.cn",
        "auth_mode": None,
        "request": request_info,
        "status": "partial",
        "termination_reason": None,
        "warnings": [],
        "counts": {},
        "pages": [],
        "posts": [],
    }


def expand_manifest(manifest_path: Path, collector: WeiboCollector) -> dict:
    """Supplement saved list posts with full text; keep both original responses."""
    run_dir = manifest_path.resolve().parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source") != MOBILE_ROOT or not isinstance(manifest.get("posts"), list):
        raise CollectionError("不是本项目的微博采集清单", reason="invalid_manifest")
    stats = {"status": "completed", "long_posts": 0, "expanded_posts": 0,
             "cached_responses": 0, "fetched_responses": 0, "termination_reason": None}
    eligible: list[dict] = []
    for post in manifest["posts"]:
        raw_file = (run_dir / post["raw_file"]).resolve()
        if not raw_file.is_relative_to(run_dir):
            raise CollectionError("原始帖子路径超出采集目录", reason="invalid_manifest")
        raw = json.loads(raw_file.read_text(encoding="utf-8"))
        if raw.get("isLongText"):
            eligible.append(post)
            post["full_text_status"] = "pending"
    stats["long_posts"] = len(eligible)
    manifest["long_text_expansion"] = stats
    save_json(manifest_path, manifest)
    for post in eligible:
        post_id = parse_post_id(str(post["post_id"]))
        relative = post.get("full_text_file") or f"long_text/{post_id}.json"
        cache = run_dir / relative
        if not cache.resolve().is_relative_to(run_dir):
            raise CollectionError("长文路径超出采集目录", reason="invalid_manifest")
        try:
            if cache.is_file():
                payload = json.loads(cache.read_text(encoding="utf-8"))
                stats["cached_responses"] += 1
            else:
                payload = collector.get_long_text(post_id)
                save_json(cache, payload)
                stats["fetched_responses"] += 1
            data = payload.get("data") if isinstance(payload, dict) else None
            text = data.get("longTextContent") if isinstance(data, dict) else None
            if (not isinstance(payload, dict) or payload.get("ok") != 1
                    or not isinstance(text, str) or not text.strip()):
                raise CollectionError("长文缓存没有完整正文", "partial", "invalid_long_text_cache")
            post["text"] = plain_text(text)
            post["full_text_file"] = relative
            post["full_text_status"] = "expanded"
            request = manifest.get("request", {})
            if "keywords" in request:
                keywords = request["keywords"]
                post["matched_keywords"] = keyword_matches(post["text"], keywords)
                post["keyword_candidate"] = bool(post["matched_keywords"]) if keywords else True
            stats["expanded_posts"] += 1
        except CollectionError as error:
            stats.update(status="partial", termination_reason=error.reason)
            post["full_text_status"] = error.state
            warning = f"长文补取停止：{error}"
            if warning not in manifest["warnings"]:
                manifest["warnings"].append(warning)
            save_json(manifest_path, manifest)
            break
        save_json(manifest_path, manifest)
    return manifest


def make_run_dir(output: Path, mode: str, slug: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_slug = re.sub(r"[^A-Za-z0-9_-]", "_", slug)[:32] or "weibo"
    base = output / f"{stamp}_{mode}_{safe_slug}"
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = Path(f"{base}_{suffix}")
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按微博帖子 ID 或有限作者分页采集公开可见内容")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--post", help="微博帖子 ID 或帖子 URL")
    modes.add_argument("--uid", help="微博作者 UID（需要同时传 --since 和 --until）")
    modes.add_argument("--expand-manifest", type=Path, help="为已有采集清单补取长文，复用已保存的长文响应")
    parser.add_argument("--since", type=parse_date, help="作者模式起始日期，含当天（YYYY-MM-DD）")
    parser.add_argument("--until", type=parse_date, help="作者模式结束日期，含当天（YYYY-MM-DD）")
    parser.add_argument("--keyword", default="", help="逗号分隔的候选关键词；命中任一词即保留")
    parser.add_argument("--max-pages", type=int, default=3, help=f"最多读取页数（默认 3，上限 {MAX_PAGES_HARD_LIMIT}）")
    parser.add_argument("--auth", choices=("none", "cookies"), default="none", help="认证方式，默认 none")
    parser.add_argument("--cookies-file", help="显式 Cookie 文件路径；仅在 --auth cookies 时读取")
    parser.add_argument("--download-images", action="store_true", help="下载图片（不下载视频或评论）")
    parser.add_argument("--expand-long-text", action="store_true", help="采集后为保存的帖子补取完整长文")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="结果根目录")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.post and not args.uid and not args.expand_manifest:
        parser.error("必须提供 --post、--uid 或 --expand-manifest")
    if args.post and (args.since or args.until or args.keyword):
        parser.error("--post 模式不接受 --since、--until 或 --keyword")
    if args.uid:
        if args.since is None or args.until is None:
            parser.error("作者模式必须同时提供 --since 和 --until")
        if args.since > args.until:
            parser.error("--since 不能晚于 --until")
        if not re.fullmatch(r"\d{1,20}", args.uid):
            parser.error("--uid 必须是数字 UID")
        if not 1 <= args.max_pages <= MAX_PAGES_HARD_LIMIT:
            parser.error(f"--max-pages 必须在 1 到 {MAX_PAGES_HARD_LIMIT} 之间")
    if args.auth == "cookies" and not args.cookies_file:
        parser.error("--auth cookies 必须同时提供 --cookies-file PATH")
    try:
        post_id = parse_post_id(args.post) if args.post else None
        session = requests.Session()
        configure_auth(session, args.auth, args.cookies_file)
    except CollectionError as exc:
        print(f"status={exc.state} reason={exc.reason}: {exc}", file=sys.stderr)
        return 2
    collector = WeiboCollector(session=session)
    if args.expand_manifest:
        try:
            result = expand_manifest(args.expand_manifest, collector)
        except (CollectionError, OSError, ValueError, KeyError) as error:
            print(f"长文补取失败（{type(error).__name__}）", file=sys.stderr)
            return 2
        stats = result["long_text_expansion"]
        print(f"long_text_status={stats['status']} expanded={stats['expanded_posts']}/{stats['long_posts']} "
              f"manifest={args.expand_manifest}")
        return 0 if stats["status"] == "completed" else 2
    mode = "post" if post_id else "author"
    run_dir = make_run_dir(args.output, mode, post_id or args.uid)
    if post_id:
        result = collector.collect_exact(post_id, run_dir, args.download_images)
    else:
        keywords = [word.strip() for word in args.keyword.split(",") if word.strip()]
        result = collector.collect_author(args.uid, args.since, args.until, keywords,
                                          args.max_pages, run_dir, args.download_images)
    result["auth_mode"] = args.auth
    result["output_dir"] = str(run_dir)
    save_json(run_dir / "manifest.json", result)
    if args.expand_long_text and result.get("posts"):
        result = expand_manifest(run_dir / "manifest.json", collector)
    counts = result.get("counts") or {}
    print(f"status={result['status']} pages={counts.get('pages_fetched', 0)} "
          f"posts={counts.get('posts_saved', counts.get('keyword_candidates_saved', 0))} "
          f"manifest={run_dir / 'manifest.json'}")
    return 0 if result["status"] in {"collected", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
