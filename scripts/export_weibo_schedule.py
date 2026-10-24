"""Export an offline, reviewable schedule index from a collected Weibo manifest."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date
from html import escape
from pathlib import Path
from urllib.parse import quote


TARGET_UID = "7525583841"
OUT_OF_SCOPE_RE = re.compile(r"京城龙门赛")
TARGET_EVENT_RE = re.compile(r"京城大师赛|昆仑归墟")
SCHEDULE_POST_RE = re.compile(r"阵容(?:公布)?|排班|赛程|表演赛")
RELATED_NOTICE_RE = re.compile(r"公告|停播|整顿|暂停|恢复|调整|赛事|京城大师赛|昆仑归墟")
COMMERCIAL_RE = re.compile(r"京师甄选|带货|商品|优惠|下单|商城")
SIX_CITY_LEAGUE_RE = re.compile(r"六城联赛")
COLLABORATION_ACTIVITY_RE = re.compile(r"京师天狼|网杀季|整活表演赛|独家联动直播")
QUALIFIER_ACTIVITY_RE = re.compile(r"小师赛|公开赛|突围(?:赛|类|名额|资格|晋级)?|资格赛")
SHOWMATCH_RE = re.compile(r"表演赛")
FINALS_PHASE_RE = re.compile(r"总决赛|(?:决赛|收官之战)\s*(?:周|阵容|排班|赛程|公布)")
DATE_RE = re.compile(r"(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|号)?")
INHERITED_DAY_RE = re.compile(
    r"\s*(、|,|，|/|&|及|至|到|~|～|—|–|-)\s*(?!\d{1,2}\s*月)(\d{1,2})\s*(?:日|号)?"
)
MENTION_RE = re.compile(r"@([A-Za-z0-9_\-\u4e00-\u9fff]+)")
ROLE_RE = re.compile(r"(解说(?:员)?|法官|板子|板型|选手|阵容(?:公布)?)\s*[：:]")
TIME_RE = re.compile(
    r"(?:今晚|今夜|今天|明晚|明天晚上|明天)?\s*"
    r"(?:上午|中午|下午|晚上|晚间)?\s*"
    r"\d{1,2}(?:\s*[:：]\s*\d{2}|\s*点(?:半|\s*\d{1,2}\s*分?)?|\s*时(?:\s*\d{1,2}\s*分?)?)"
)
TRUNCATION_RE = re.compile(r"(?:……|…|\.\.\.|展开(?:全文)?|全文)\s*$")
TEXT_CSV_FIELDS = [
    "post_id", "author_uid", "author_name", "is_target_account", "is_repost", "candidate_category",
    "reposted_author_uid", "published_date", "published_at_utc8", "post_url", "text", "image_refs",
    "image_source_urls", "raw_file_ref", "full_text_file_ref", "detail_file_ref", "full_text_status", "source_manifest", "schedule_candidate",
    "candidate_reason", "season", "episode", "phase", "game_dates", "players", "commentators",
    "judges", "board", "start_time", "role_date_association", "review_flags",
]
CANDIDATE_CSV_FIELDS = [
    "post_id", "published_date", "published_at_utc8", "post_url", "candidate_category", "season", "episode", "phase", "game_dates",
    "schedule_match_keys", "players", "player_count", "commentators", "judges",
    "board", "start_time", "role_date_association", "is_repost", "review_status", "review_flags", "text",
    "image_refs", "raw_file_ref", "full_text_file_ref", "detail_file_ref", "full_text_status", "source_manifest", "candidate_reason",
]


def chinese_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if not value or any(char not in digits and char not in "十百" for char in value):
        return None
    total = 0
    section = 0
    number = 0
    for char in value:
        if char in digits:
            number = digits[char]
        elif char == "十":
            section += (number or 1) * 10
            number = 0
        elif char == "百":
            section += (number or 1) * 100
            number = 0
    total = section + number
    return total or None


def _published_date(post: dict) -> date | None:
    raw = post.get("published_date")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _resolve_month_day(month: int, day: int, published: date | None, explicit_year: int | None) -> date | None:
    years = [explicit_year] if explicit_year else (
        list(range(published.year - 4, published.year + 5)) if published else []
    )
    possible: list[date] = []
    for year in years:
        try:
            possible.append(date(year, month, day))
        except ValueError:
            continue
    if not possible:
        return None
    if explicit_year or not published:
        return possible[0]
    return min(possible, key=lambda item: (abs((item - published).days), item))


def extract_dates(text: str, published: date | None) -> tuple[list[dict], bool]:
    """Extract explicit month/day mentions; infer a year only from publication date."""
    found: list[dict] = []
    seen: set[tuple[int | None, int, int]] = set()

    def add(year: int | None, month: int, day: int) -> None:
        key = (year, month, day)
        if key in seen:
            return
        seen.add(key)
        resolved = _resolve_month_day(month, day, published, year)
        found.append({
            "month": month,
            "day": day,
            "explicit_year": year,
            "iso_date": resolved.isoformat() if resolved else None,
        })

    range_unresolved = False
    for match in DATE_RE.finditer(text):
        year_text, month_text, day_text = match.groups()
        year = int(year_text) if year_text else None
        month, day = int(month_text), int(day_text)
        # Invalid calendar dates remain visible as review flags through the missing resolution.
        add(year, month, day)
        cursor = match.end()
        while True:
            inherited = INHERITED_DAY_RE.match(text, cursor)
            if not inherited:
                break
            next_day = int(inherited.group(2))
            separator = inherited.group(1)
            if separator in {"至", "到", "~", "～", "—", "–", "-"}:
                previous_day = int(found[-1]["day"])
                if previous_day < next_day <= 31:
                    for value in range(previous_day + 1, next_day + 1):
                        add(year, month, value)
                else:
                    range_unresolved = True
                    add(year, month, next_day)
            else:
                add(year, month, next_day)
            cursor = inherited.end()
    # A range that crosses into a separately written month/year needs review; do not imply
    # that endpoints alone are the complete set of days.
    for match in re.finditer(r"(?:至|到|~|～|—|–|-)\s*\d{1,2}\s*月", text):
        range_unresolved = True
    return found, range_unresolved


def _role_sections(text: str) -> list[tuple[str, int, int]]:
    matches = list(ROLE_RE.finditer(text))
    return [(match.group(1), match.end(), matches[index + 1].start() if index + 1 < len(matches) else len(text))
            for index, match in enumerate(matches)]


def _role_value(text: str, names: tuple[str, ...], sections: list[tuple[str, int, int]]) -> str:
    for name, start, end in sections:
        if name in names:
            value = text[start:end]
            # Time and live-stream details often follow the board in the same clause.
            if name in {"板子", "板型"}:
                value = re.split(
                    r"(?:今晚|今夜|今天|明晚|明天|时间|开赛|直播|转播|看顶尖玩家|精彩不容错过)"
                    r"|\[(?:打call|doge|允悲|赞|笑而不语)\]|\r?\n",
                    value, maxsplit=1,
                )[0]
            return value.strip(" \t\r\n，,；;。:")
    return ""


def _names(value: str, *, player_list: bool = False) -> list[str]:
    if player_list:
        value = re.sub(
            r"^\s*(?:(?:周|星期)[一二三四五六日天]\s*)?"
            r"[（(]?\s*\d{1,2}\s*月\s*\d{1,2}\s*(?:日|号)?\s*[）)]?\s*[:：]?\s*",
            "", value,
        )
    # Keep untagged names between/after @mentions (some real rosters omit @ on the last name).
    parts = MENTION_RE.split(value)
    names: list[str] = []
    stopwords = {"等", "选手", "阵容", "名单", "以及", "还有", "出战", "周一", "周二", "周三",
                 "周四", "周五", "周六", "周日", "星期一", "星期二", "星期三", "星期四",
                 "星期五", "星期六", "星期日"}
    for index, part in enumerate(parts):
        tokens = [part] if index % 2 else re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]+", part)
        for token in tokens:
            token = token.strip()
            if token and token not in stopwords and not token.isdigit():
                names.append(token)
    return list(dict.fromkeys(names))


def _is_truncated(text: str) -> bool:
    return bool(TRUNCATION_RE.search(text))


def _season_number(text: str) -> int | None:
    match = re.search(r"第\s*([0-9零〇一二两三四五六七八九十百]+)\s*季", text)
    if match:
        return chinese_number(match.group(1))
    match = re.search(r"(?<![A-Za-z0-9])S\s*(\d{1,2})(?!\d)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _episode_number(text: str) -> int | None:
    match = re.search(r"第\s*([0-9零〇一二两三四五六七八九十百]+)\s*期", text)
    return chinese_number(match.group(1)) if match else None


def _schedule_phase(text: str, schedule_post: bool, season: int | None, episode: int | None,
                    other_activity: bool) -> str:
    if other_activity:
        return "其他活动/资格赛待核"
    if not schedule_post:
        return ""
    if SHOWMATCH_RE.search(text):
        return "表演赛"
    if FINALS_PHASE_RE.search(text):
        return "决赛周"
    if season is not None and episode is not None:
        return "正赛"
    return "阶段待核"


def _relative_ref(manifest_dir: Path, output_dir: Path, relative: object) -> str:
    if not isinstance(relative, str) or not relative.strip():
        return ""
    source_path = manifest_dir / Path(relative)
    try:
        return Path(os.path.relpath(source_path, output_dir)).as_posix()
    except ValueError:
        return source_path.as_posix()


def _image_data(post: dict, manifest_dir: Path, output_dir: Path) -> tuple[list[dict], list[str], list[str]]:
    images = post.get("images") if isinstance(post.get("images"), list) else []
    records: list[dict] = []
    refs: list[str] = []
    source_urls: list[str] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        local_ref = _relative_ref(manifest_dir, output_dir, image.get("file"))
        source_url = image.get("source_url") if isinstance(image.get("source_url"), str) else ""
        if local_ref:
            refs.append(local_ref)
        if source_url:
            source_urls.append(source_url)
        records.append({
            "status": image.get("status") or "unknown",
            "file": image.get("file"),
            "relative_ref": local_ref or None,
            "source_url": source_url or None,
        })
    return records, refs, source_urls


def analyze_post(post: dict, manifest_dir: Path, output_dir: Path, source_manifest: str) -> dict:
    text = post.get("text") if isinstance(post.get("text"), str) else ""
    author_uid = str(post.get("author_uid") or "")
    is_target = author_uid == TARGET_UID
    is_repost = bool(post.get("is_repost"))
    # Mobile plain text starts with the supertopic link label on unrelated posts too.
    event_text = re.sub(r"^\s*京城大师赛\s+", "", text, count=1)
    target_event_text = re.sub(r"通往[【〖《「\s]*京城大师赛[】〗》」\s]*的席位", "", event_text)
    mentions_target_event = bool(TARGET_EVENT_RE.search(target_event_text))
    mentions_other_event = bool(OUT_OF_SCOPE_RE.search(event_text))
    out_of_scope = mentions_other_event and not mentions_target_event
    explicit_master_header = bool(re.search(r"第\s*[0-9零〇一二两三四五六七八九十百]+\s*季\s*《京城大师赛》", text))
    mixed_event = mentions_target_event and mentions_other_event and not explicit_master_header
    commercial = bool(COMMERCIAL_RE.search(text))
    season_seen = _season_number(text)
    episode_seen = _episode_number(text)
    explicit_stage = bool(SHOWMATCH_RE.search(text) or FINALS_PHASE_RE.search(text))
    schedule_signal = bool(SCHEDULE_POST_RE.search(text))
    # Remove @handles before looking for qualifier markers: some player names
    # contain strings such as "东北小师赛". A clear 六城联赛 label is enough
    # to identify a separate activity; generic qualifier terms need the absence
    # of an explicit season/episode or a named master showmatch/finals stage.
    qualifier_text = MENTION_RE.sub(" ", target_event_text)
    six_city_league = bool(SIX_CITY_LEAGUE_RE.search(qualifier_text))
    collaboration_activity = bool(COLLABORATION_ACTIVITY_RE.search(qualifier_text))
    qualifier_marker = bool(QUALIFIER_ACTIVITY_RE.search(qualifier_text))
    explicit_master_schedule = (
        (season_seen is not None and episode_seen is not None)
        or (mentions_target_event and schedule_signal and explicit_stage)
        or (season_seen is not None and schedule_signal and explicit_stage)
    )
    other_activity = collaboration_activity or six_city_league or (qualifier_marker and not explicit_master_schedule)
    schedule_post = (schedule_signal and not out_of_scope and not mixed_event and not commercial
                     and not other_activity)
    related_notice = bool(RELATED_NOTICE_RE.search(text))
    published = _published_date(post)
    image_records, image_refs, image_urls = _image_data(post, manifest_dir, output_dir)
    candidate = bool(is_target and not out_of_scope and not commercial and not other_activity and (
        is_repost or not text.strip() or schedule_post or related_notice
    ))
    if not is_target:
        candidate_category = "非目标作者"
    elif commercial:
        candidate_category = "商业内容排除"
    elif out_of_scope:
        candidate_category = "其他赛事排除"
    elif other_activity:
        candidate_category = "其他活动/资格赛待核"
    elif is_repost:
        candidate_category = "转载待核"
    elif not text.strip():
        candidate_category = "图片或空文待核"
    elif schedule_post:
        candidate_category = "排班候选"
    elif candidate:
        candidate_category = "赛事公告待核"
    else:
        candidate_category = "非候选"

    if commercial:
        candidate_reason = "正文属于带货或商品推广内容，排除出赛事排班候选"
    elif out_of_scope:
        candidate_reason = "正文提及其他比赛“京城龙门赛”，排除出京城大师赛排班候选"
    elif other_activity:
        activity = ("联动网杀/整活表演活动" if collaboration_activity else
                    "六城联赛" if six_city_league else "小师赛、公开赛或突围/资格赛")
        candidate_reason = (f"正文出现{activity}活动标记，且没有足够证据将栏目归为大师赛排班；"
                            "保留原帖与证据，暂不解析选手和角色")
    elif not is_target:
        candidate_reason = "作者 UID 非目标账号"
    elif is_repost:
        candidate_reason = "目标账号转载：只保留外层正文，赛事信息待核"
    elif not text.strip():
        candidate_reason = "正文为空或仅含配图，图片内容及赛事归属待核"
    elif schedule_post:
        candidate_reason = "正文含阵容公布、排班或赛程线索"
    elif candidate:
        candidate_reason = "正文含其他官方公告线索，未识别为排班内容，待核"
    else:
        candidate_reason = "正文未发现明确排班线索"

    season = episode = None
    phase = _schedule_phase(text, schedule_post, season_seen, episode_seen, other_activity)
    dates: list[dict] = []
    range_unresolved = False
    players: list[str] = []
    commentators: list[str] = []
    judges: list[str] = []
    board = start_time = ""
    if schedule_post and not is_repost and is_target:
        season, episode = season_seen, episode_seen
        dates, range_unresolved = extract_dates(text, published)
        sections = _role_sections(text)
        players_section = _role_value(text, ("选手", "阵容", "阵容公布"), sections)
        commentators_section = _role_value(text, ("解说", "解说员"), sections)
        judges_section = _role_value(text, ("法官",), sections)
        board = _role_value(text, ("板子", "板型"), sections)
        players = _names(players_section, player_list=True)
        commentators = _names(commentators_section)
        judges = _names(judges_section)
        time_match = TIME_RE.search(text)
        start_time = re.sub(r"\s+", "", time_match.group(0)) if time_match else ""

    flags: list[str] = []
    if candidate:
        if is_repost:
            flags.append("转载外层只作待核，不解析转发来源")
        elif not schedule_post:
            if not text.strip() and image_records:
                flags.append("仅有配图，图片内容及赛事归属待人工核对")
            else:
                flags.append("相关赛事公告保留待核，排班字段未提取")
        else:
            if season is None:
                flags.append("未识别到赛季")
            if episode is None and phase not in {"表演赛", "决赛周"}:
                flags.append("未识别到期数")
            if not dates:
                flags.append("未识别到比赛日期")
            elif any(not item["iso_date"] for item in dates):
                flags.append("比赛日期缺少可用年份或日期格式异常，待核")
            if range_unresolved:
                flags.append("比赛日期范围未能完整展开，待核且不生成匹配键")
            if len(dates) > 1:
                flags.append("多日期正文中的选手及角色字段与日期关联未核，不生成匹配键")
            if not players:
                flags.append("未识别到选手名单")
            elif len(players) != 12:
                flags.append(f"识别到{len(players)}名选手，不是常见12人排班，待核")
            if not commentators:
                flags.append("未识别到解说")
            if not judges:
                flags.append("未识别到法官")
            if not board:
                flags.append("未识别到板子")
            if not start_time:
                flags.append("未识别到开赛时间")
        if post.get("full_text_status") != "expanded" and _is_truncated(text):
            flags.append("正文疑似截断，待核全文")
    raw_file = _relative_ref(manifest_dir, output_dir, post.get("raw_file"))
    match_dates = [item["iso_date"] for item in dates if item["iso_date"]]
    multi_date = len(dates) > 1
    role_date_association = (
        "转载外层待核" if is_repost else
        "非排班公告" if not schedule_post else
        "待核：同帖包含多个日期，角色字段与各日期的对应关系未确认" if multi_date else "单日期"
    )
    match_keys = (
        [f"S{season}-E{episode}-{match_dates[0]}"]
        if phase == "正赛" and season and episode and len(match_dates) == 1 and not range_unresolved and not multi_date
        else []
    )
    return {
        "post_id": post.get("post_id") or "",
        "author_uid": author_uid,
        "author_name": post.get("author_name") or "",
        "is_target_account": is_target,
        "is_repost": is_repost,
        "reposted_author_uid": post.get("reposted_author_uid") or "",
        "published_date": post.get("published_date") or "",
        "published_at_utc8": post.get("published_at_utc8") or "",
        "post_url": post.get("post_url") or "",
        "text": text,
        "images": image_records,
        "image_refs": image_refs,
        "image_source_urls": image_urls,
        "raw_file_ref": raw_file,
        "full_text_file_ref": _relative_ref(manifest_dir, output_dir, post.get("full_text_file")),
        "detail_file_ref": _relative_ref(manifest_dir, output_dir, post.get("detail_file")),
        "full_text_status": post.get("full_text_status") or "not_needed_or_not_checked",
        "source_raw_file": post.get("raw_file") or "",
        "source_manifest": source_manifest,
        "schedule_candidate": candidate,
        "candidate_category": candidate_category,
        "candidate_reason": candidate_reason,
        "season": season,
        "episode": episode,
        "phase": phase,
        "date_candidates": dates,
        "game_dates": match_dates,
        "schedule_match_keys": match_keys,
        "players": players,
        "player_count": len(players),
        "commentators": commentators,
        "judges": judges,
        "board": board,
        "start_time": start_time,
        "role_date_association": role_date_association,
        "review_flags": flags,
        "review_status": "待核" if flags else ("候选，字段较完整" if candidate else "非排班候选"),
    }


def _csv_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "是" if value else "否"
    return "" if value is None else str(value)


def _all_csv_row(post: dict) -> dict:
    row = dict(post)
    row.update({
        "image_refs": post["image_refs"],
        "image_source_urls": post["image_source_urls"],
        "game_dates": post["game_dates"],
        "players": post["players"],
        "commentators": post["commentators"],
        "judges": post["judges"],
        "review_flags": post["review_flags"],
    })
    return {key: _csv_value(row.get(key)) for key in TEXT_CSV_FIELDS}


def _candidate_csv_row(post: dict) -> dict:
    row = {key: post.get(key) for key in CANDIDATE_CSV_FIELDS}
    for key in ("game_dates", "schedule_match_keys", "players", "commentators", "judges", "review_flags", "image_refs"):
        row[key] = post.get(key)
    return {key: _csv_value(row.get(key)) for key in CANDIDATE_CSV_FIELDS}


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _markdown_link(label: str, target: str) -> str:
    if not target:
        return ""
    return f"[{label}](<{quote(target.replace('\\', '/'), safe='/.:_-')}>)"


def _render_markdown(manifest: dict, posts: list[dict]) -> str:
    candidate_count = sum(bool(item["schedule_candidate"]) for item in posts)
    schedule_count = sum(item["candidate_category"] == "排班候选" for item in posts)
    lines = ["# 微博整理", "", "## 采集记录", "",
             f"- Manifest：`{manifest.get('_source_manifest', '')}`",
             f"- 状态：`{manifest.get('status') or '未知'}`",
             f"- 终止原因：`{manifest.get('termination_reason') or '未记录'}`",
             f"- 覆盖说明：{manifest.get('coverage_note') or 'manifest 未提供 coverage_note。'}", "",
             f"共整理 {len(posts)} 条微博，其中候选 {candidate_count} 条，排班候选 {schedule_count} 条。", ""]
    for post in posts:
        post_id = str(post["post_id"] or "无 ID")
        heading = _markdown_link(post_id, post["post_url"]) or post_id
        lines.extend([f"## {heading}", "",
                      f"- 作者：{post['author_name']}（UID `{post['author_uid']}`）",
                      f"- 发布时间：{post['published_date'] or '未知'}；转载：{'是' if post['is_repost'] else '否'}",
                      f"- 候选类别：{post['candidate_category']}；{post['candidate_reason']}"])
        if post["candidate_category"] == "排班候选":
            lines.append(
                f"- 提取字段：阶段 {post['phase'] or '待核'}，赛季 {post['season'] or '待核'}，"
                f"期数 {post['episode'] or '待核'}，"
                f"比赛日期 {', '.join(post['game_dates']) or '待核'}，选手 {', '.join(post['players']) or '待核'}，"
                f"解说 {', '.join(post['commentators']) or '待核'}，法官 {', '.join(post['judges']) or '待核'}，"
                f"板子 {post['board'] or '待核'}，时间 {post['start_time'] or '待核'}"
            )
            lines.append(f"- 日期与角色关联：{post['role_date_association']}")
        if post["schedule_candidate"] and post["review_flags"]:
            lines.append(f"- 待核原因：{'；'.join(post['review_flags'])}")
        if post["raw_file_ref"]:
            lines.append(f"- 原始帖子：{_markdown_link(post['source_raw_file'], post['raw_file_ref'])}")
        if post["full_text_file_ref"]:
            lines.append(f"- 完整正文响应：{_markdown_link('长文原件', post['full_text_file_ref'])}")
        if post["detail_file_ref"]:
            lines.append(f"- 完整图片详情：{_markdown_link('详情原件', post['detail_file_ref'])}")
        for index, image in enumerate(post["images"], 1):
            if image["relative_ref"]:
                lines.append(f"- 图片 {index}：{_markdown_link(image['file'], image['relative_ref'])}")
            elif image["source_url"]:
                lines.append(f"- 图片 {index}：未下载（来源 `{image['source_url']}`）")
            else:
                lines.append(f"- 图片 {index}：未记录本地引用")
        lines.extend(["", "正文：", "", "<pre>", escape(post["text"]), "</pre>", ""])
    return "\n".join(lines)


def export(manifest_path: Path, output_dir: Path) -> dict:
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest 顶层必须是 JSON 对象")
    source_posts = manifest.get("posts")
    if not isinstance(source_posts, list):
        raise ValueError("manifest 缺少 posts 列表")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_manifest = manifest_path.as_posix()
    rows = [analyze_post(item, manifest_path.parent, output_dir.resolve(), source_manifest)
            for item in source_posts if isinstance(item, dict)]
    candidates = [item for item in rows if item["schedule_candidate"]]
    schedules = [item for item in candidates if item["candidate_category"] == "排班候选"]
    _write_csv(output_dir / "全部微博.csv", TEXT_CSV_FIELDS, [_all_csv_row(item) for item in rows])
    _write_csv(output_dir / "排班候选.csv", CANDIDATE_CSV_FIELDS,
               [_candidate_csv_row(item) for item in candidates])
    readable_schedule = [{
        "阶段": item["phase"],
        "比赛日期": "；".join(item["game_dates"]),
        "赛季": f"S{item['season']}" if item["season"] else "",
        "期数": item["episode"] or "",
        "选手": "、".join(item["players"]),
        "选手人数": item["player_count"],
        "解说": "、".join(item["commentators"]),
        "法官": "、".join(item["judges"]),
        "板子": item["board"],
        "开播时间": item["start_time"],
        "待核事项": "；".join(item["review_flags"]),
        "发帖日期": item["published_date"],
        "发帖时间": item["published_at_utc8"],
        "原帖链接": item["post_url"],
        "正文原件": item["full_text_file_ref"] or item["raw_file_ref"],
        "图片": "；".join(item["image_refs"]),
    } for item in schedules]
    schedule_fields = ["阶段", "比赛日期", "赛季", "期数", "选手", "选手人数", "解说", "法官", "板子",
                       "开播时间", "待核事项", "发帖日期", "发帖时间", "原帖链接", "正文原件", "图片"]
    _write_csv(output_dir / "比赛排班.csv", schedule_fields, readable_schedule)
    (output_dir / "排班候选.json").write_text(
        json.dumps({
            "source_manifest": source_manifest,
            "collection_status": manifest.get("status"),
            "termination_reason": manifest.get("termination_reason"),
            "coverage_note": manifest.get("coverage_note"),
            "candidate_count": len(candidates),
            "candidates": candidates,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_for_md = dict(manifest)
    manifest_for_md["_source_manifest"] = source_manifest
    (output_dir / "微博整理.md").write_text(_render_markdown(manifest_for_md, rows), encoding="utf-8")
    return {"post_count": len(rows), "candidate_count": len(candidates), "schedule_count": len(schedules),
            "output_dir": str(output_dir.resolve())}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="采集目录中的 manifest.json")
    parser.add_argument("--output", required=True, type=Path, help="导出目录")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = export(args.manifest, args.output)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
