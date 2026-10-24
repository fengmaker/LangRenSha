"""Stable, human-readable names for archived Weibo post artifacts.

This module is intentionally pure: it only derives names and relative paths
from the supplied post dictionary and never reads or writes archive data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import re
from typing import Any


BEIJING = timezone(timedelta(hours=8))
UNKNOWN_PARTITION = "未知时间"
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_CHINESE_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
    "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_ID_KEYS = ("idstr", "id", "mid")
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SPACE_RUN = re.compile(r"\s+")
_RESERVED_WINDOWS_NAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)


class _TextExtractor(HTMLParser):
    """Collect visible text while keeping block boundaries readable."""

    _BLOCK_TAGS = {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._hidden_depth += 1
        elif not self._hidden_depth and tag.lower() in self._BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1
        elif not self._hidden_depth and lowered in self._BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def _visible_text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
        text = " ".join(parser.parts)
    except Exception:
        # Malformed markup is still useful as a readable title after removing
        # obvious tags; parsing errors must not turn an otherwise valid post
        # into an unusable filename.
        text = re.sub(r"<[^>]*>", " ", value)
    return _SPACE_RUN.sub(" ", text).strip()


def _post_text(raw: dict[str, Any]) -> str:
    """Choose the best available post title/body without requiring a schema."""
    for key in ("title", "text", "text_raw", "longTextContent", "long_text"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return _visible_text(value)
    data = raw.get("data")
    if isinstance(data, dict):
        for key in ("title", "longTextContent", "text"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return _visible_text(value)
    return ""


def _remove_topic_prefix(value: str) -> str:
    """Remove the account's repeated 京城大师赛 supertopic prefix."""
    text = value.strip()
    topic = r"(?:#\s*京城大师赛(?:\s*超话)?\s*#|京城大师赛(?:\s*超话)?)"
    while True:
        shortened = re.sub(r"^\s*" + topic + r"\s*", "", text, count=1)
        if shortened == text:
            break
        text = shortened.lstrip("#＃、，,:：;；|｜-—_ ")
    return text.strip()


def _parse_chinese_integer(value: str) -> int | None:
    """Parse digits and common Chinese integers through 999."""
    if value.isdigit():
        return int(value)
    if not value:
        return None
    if all(char in _CHINESE_DIGITS for char in value):
        return int("".join(str(_CHINESE_DIGITS[char]) for char in value))

    total = 0
    section = 0
    digit = 0
    units = {"十": 10, "百": 100}
    for char in value:
        if char in _CHINESE_DIGITS:
            digit = _CHINESE_DIGITS[char]
        elif char in units:
            unit = units[char]
            section += (digit or (1 if unit == 10 else 0)) * unit
            digit = 0
        else:
            return None
    result = total + section + digit
    return result if result > 0 else None


def _season_and_issue(text: str) -> str:
    """Return explicit season/issue labels; never infer a season from dates."""
    season: int | None = None
    for match in re.finditer(r"(?<![A-Za-z0-9])S\s*(\d{1,2})(?!\d)", text, re.IGNORECASE):
        candidate = int(match.group(1))
        if 1 <= candidate <= 99:
            season = candidate
            break
    if season is None:
        for match in re.finditer(r"第\s*([0-9]{1,2}|[零〇一二两三四五六七八九十百]+)\s*季", text):
            candidate = _parse_chinese_integer(match.group(1))
            if candidate is not None and 1 <= candidate <= 99:
                season = candidate
                break

    issue: int | None = None
    for match in re.finditer(r"第\s*([0-9]{1,3}|[零〇一二两三四五六七八九十百]+)\s*期", text):
        candidate = _parse_chinese_integer(match.group(1))
        if candidate is not None and 1 <= candidate <= 999:
            issue = candidate
            break

    season_part = f"S{season:02d}" if season is not None else None
    issue_part = f"第{issue:02d}期" if issue is not None else None
    if season_part and issue_part:
        return f"{season_part}_{issue_part}"
    if season_part:
        return f"{season_part}_期数待核"
    if issue_part:
        return f"赛季待核_{issue_part}"
    return "赛季期数待核"


def _parse_created_at(value: Any) -> datetime | None:
    """Parse supported timestamps and return the instant in Beijing time."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()

    # ISO date-times, including a trailing Z. A date with no clock is not
    # treated as midnight because that would invent a publication time.
    if re.search(r"\d{2}:\d{2}", text):
        candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=BEIJING)
            return parsed.astimezone(BEIJING)
        except ValueError:
            pass

    # Weibo's standard created_at form, parsed without locale-sensitive
    # strptime month names: Thu Sep 25 15:33:00 +0800 2025.
    match = re.search(
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Za-z]{3})\s+(\d{1,2})\s+"
        r"(\d{2}):(\d{2}):(\d{2})\s+([+-]\d{2}:?\d{2})\s+(\d{4})",
        text,
    )
    if not match:
        return None
    month = _MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    offset_text = match.group(6).replace(":", "")
    sign = 1 if offset_text[0] == "+" else -1
    try:
        offset = sign * (int(offset_text[1:3]) * 60 + int(offset_text[3:5]))
        parsed = datetime(
            int(match.group(7)), month, int(match.group(2)),
            int(match.group(3)), int(match.group(4)), int(match.group(5)),
            tzinfo=timezone(timedelta(minutes=offset)),
        )
        return parsed.astimezone(BEIJING)
    except (ValueError, OverflowError):
        return None


def _post_id(raw: dict[str, Any]) -> str:
    for key in _ID_KEYS:
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            digits = str(value)
            break
        if isinstance(value, str) and value.isdigit():
            digits = value
            break
    else:
        return "未知ID"
    # Real numeric Weibo IDs fit comfortably within this bound. Rejecting an
    # implausibly long value keeps caller-controlled data from creating an
    # overlong or unusable Windows path.
    if len(digits) > 32:
        raise ValueError("微博数字 ID 长度异常")
    return digits


def _has_images(raw: dict[str, Any]) -> bool:
    for key in ("pics", "pic_ids", "images"):
        value = raw.get(key)
        if isinstance(value, (list, tuple)) and value:
            return True
    return False


def _content_label(raw: dict[str, Any], text: str) -> str:
    # Specific notices are more useful than an event-name match. Posts may
    # mention 京城龙门赛 while announcing a suspension or leave for the
    # account's wider event program.
    if "请假" in text:
        return "请假公告_涉及龙门赛" if "龙门赛" in text else "请假公告"
    if any(word in text for word in ("停播整顿", "停播整改", "停播整治")):
        return "停播整顿公告_涉及龙门赛" if "龙门赛" in text else "停播整顿公告"
    if "停播" in text or "休播" in text:
        if "休播" in text and "停播" not in text:
            return "休播公告_涉及龙门赛" if "龙门赛" in text else "休播公告"
        return "停播公告_涉及龙门赛" if "龙门赛" in text else "停播公告"

    # The commerce account's posts tend to have long promotional copy and
    # decorative emoji/hashtags. Keep their stable business category instead
    # of copying that copy into the filename.
    if "京师甄选" in text:
        if any(word in text for word in ("带货", "直播", "商品", "优惠", "下单", "购物", "上新", "秒杀")):
            return "京师甄选_带货安排"
        return "京师甄选公告"
    if "带货" in text:
        return "带货安排"

    if "龙门赛" in text:
        if "积分" in text:
            return "龙门赛积分"
        if any(word in text for word in ("阵容", "名单", "选手阵容")):
            return "龙门赛阵容"
        if any(word in text for word in ("赛果", "战报", "胜负", "获胜", "冠军", "比赛结果")):
            return "龙门赛赛果"
        if any(word in text for word in ("公告", "通知", "报名", "招募", "安排", "开赛")):
            return "龙门赛公告"
        return "龙门赛"

    if "积分" in text:
        return "积分说明"
    if any(word in text for word in ("阵容", "名单", "选手阵容")):
        return "阵容公告"
    if "大师赛" in text:
        return "大师赛公告"
    if _has_images(raw) and ("公告" in text or not text):
        return "图片公告"
    if _has_images(raw) and not text:
        return "图片"
    if "公告" in text:
        return "公告"
    return text or "微博"


def _safe_fragment(value: str, limit: int) -> str:
    text = _INVALID_FILENAME_CHARS.sub("_", value)
    text = _SPACE_RUN.sub("_", text)
    text = re.sub(r"_+", "_", text).strip(" ._")
    text = text[:limit].rstrip(" ._")
    return text or "内容待核"


def _timestamp_parts(raw: dict[str, Any]) -> tuple[str, str]:
    published = _parse_created_at(raw.get("created_at"))
    if published is None:
        return f"{UNKNOWN_PARTITION}_{UNKNOWN_PARTITION}", UNKNOWN_PARTITION
    return published.strftime("%Y-%m-%d_%H-%M-%S"), published.strftime("%Y-%m")


def post_stem(raw: dict[str, Any]) -> str:
    """Create a stable, Windows-safe stem from an unmodified Weibo post.

    Timestamps are converted to UTC+8 before formatting. If ``created_at`` is
    missing or invalid, the stem explicitly says ``未知时间``. Only explicit
    ``S22``/``第22季`` and ``第1期`` markers produce season or issue labels.
    """
    if not isinstance(raw, dict):
        raise TypeError("raw 必须是 dict")
    timestamp, _ = _timestamp_parts(raw)
    text = _remove_topic_prefix(_post_text(raw))
    season_issue = _season_and_issue(text)
    content = _content_label(raw, text)
    post_id = _post_id(raw)

    prefix = f"{timestamp}_{season_issue}_"
    suffix = f"__WB{post_id}"
    available = 99 - len(prefix) - len(suffix)
    if available < 1:
        raise ValueError("微博 ID 与可读时间信息过长，无法生成 100 字符内文件名")
    label = _safe_fragment(content, min(28, available))
    stem = prefix + label + suffix
    # Defensive final check for unusual Unicode or caller-supplied IDs.
    if len(stem) > 100:
        raise ValueError("微博文件名超过 100 字符")
    if stem.endswith((" ", ".")) or _RESERVED_WINDOWS_NAME.fullmatch(stem):
        stem = "_" + stem.rstrip(" .")
    return stem


def artifact_paths(raw: dict[str, Any]) -> dict[str, str | None]:
    """Return deterministic relative paths for each possible post artifact.

    ``full_text_file`` is always returned as the canonical destination for a
    full-text response; callers should write it only when one was collected.
    ``image_base`` omits the image ordinal and extension, so callers can append
    ``_图01.jpg`` (or another ordinal/extension) to it.
    """
    stem = post_stem(raw)
    _, month = _timestamp_parts(raw)
    published_at = _parse_created_at(raw.get("created_at"))
    return {
        "stem": stem,
        "raw_file": f"posts/{month}/{stem}.帖子原始.json",
        "full_text_file": f"long_text/{month}/{stem}.长文原始.json",
        "detail_file": f"details/{month}/{stem}.详情原始.json",
        "image_base": f"images/{month}/{stem}",
        "published_at_utc8": published_at.isoformat(timespec="seconds") if published_at else None,
    }

