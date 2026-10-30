#!/usr/bin/env python3
"""Build a conservative, subtitle-guided plan for local recap transcription.

This script only reads the season index, collection progress report and local
subtitle files. It never downloads media or invokes speech recognition.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "data/indexes/S22_采集计划.json"
DEFAULT_PROGRESS = ROOT / "data/reports/S22/S22_采集进度.json"
MAX_CANDIDATE_MS = 180_000
LOCALIZE_MS = 300_000
BUFFER_BEFORE_MS = 3_000
BUFFER_AFTER_MS = 5_000

ROLE_RE = re.compile(r"机械狼|预言家|女巫|猎人|守卫|白痴|骑士|通灵师|摄梦人|丘比特|狼王|狼人|白狼王|石像鬼|禁言长老|觉醒愚者|大法师|平民|民牌")
SEAT_RE = re.compile(r"(?:第)?\s*(?:1[0-2]|[1-9])\s*(?:号|号位|号玩家|号选手|号麦|号座)")
RECAP_RE = re.compile(r"复盘|复盘一下|复盘本局|回顾本局")
FUTURE_RE = re.compile(r"(?:等会儿?|待会儿?|一会儿?|稍后|之后|结束(?:以后|后)|游戏完(?:了)?后|打完(?:了)?后|下播前).{0,14}(?:复盘|回顾)|(?:复盘|回顾).{0,8}(?:等会儿?|待会儿?|稍后|之后)")
EXPLICIT_RECAP_RE = re.compile(
    r"(?:给|为|替|跟|和|来|做|进行|看|聊|讲|一起|马上)?"
    r".{0,18}(?:本局|本游戏|这局|这一局|这把|弹幕|大家|各位|观众|本盘|本轮)"
    r".{0,12}(?:复盘|回顾)|(?:复盘|回顾).{0,12}(?:本局|本游戏|这局|这一局|这把|本盘|本轮)"
)

ACTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("first_night", re.compile(r"首夜|第一夜|天黑请闭眼|夜间行动|晚上行动|夜里行动")),
    ("guard_action", re.compile(r"守卫.{0,10}(?:守护|守谁|盾|保护|空守)|(?:守护|保护).{0,8}守卫|守了.{0,6}(?:谁|几号|自己)")),
    ("wolf_kill", re.compile(r"(?:狼队|狼人|狼刀|狼坑|狼).{0,12}(?:刀|击杀|杀掉|杀了|出刀|目标)|(?:刀口|击杀目标|狼队击杀)")),
    ("medium_check", re.compile(r"通灵师.{0,12}(?:验证|查验|验人|验了|查谁)|(?:验证|查验|验人).{0,8}通灵师")),
    ("night_result", re.compile(r"昨晚.{0,8}(?:死|刀|平安|没死)|平安夜|天亮了|昨夜")),
    ("witch_action", re.compile(r"女巫.{0,10}(?:救|毒|用药|解药|毒药)|(?:救人|毒人).{0,8}女巫")),
)
END_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("recap_end", re.compile(r"(?:本局|这局|这把)?复盘(?:就到这里|结束|完毕|完了)|以上就是.{0,8}(?:复盘|回顾)")),
    ("next_game", re.compile(r"下一局|下一把|准备开局|准备下一局|开始下一场|再来一局|再开一把|换一局|进入下一局")),
    ("production_switch", re.compile(r"切到.{0,6}(?:解说|鲜花|镜头)|看一下(?:解说|鲜花|镜头)|下面看(?:解说|鲜花|镜头)|导播.{0,8}(?:切|镜头)|解说席|鲜花席")),
    ("faction_result", re.compile(r"好人(?:阵营)?(?:胜利|获胜)|狼人(?:阵营)?(?:胜利|获胜)|狼队胜利|游戏结束")),
)
CHINESE_NUMERALS = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6",
                    "七": "7", "八": "8", "九": "9", "十": "10", "十一": "11", "十二": "12"}
CHINESE_SEAT_RE = re.compile(r"(?<![一二三四五六七八九十百])(?:十一|十二|一|二|三|四|五|六|七|八|九|十)(?=\s*(?:号|[/、，]))")


def _feature_text(text: str) -> str:
    # Normalize spoken Chinese seat numbers only for detection. Evidence keeps
    # the platform subtitle content verbatim.
    text = CHINESE_SEAT_RE.sub(lambda m: CHINESE_NUMERALS[m.group(0)], text)
    return re.sub(r"\s+", "", text)


def _ms(value: Any) -> int:
    try:
        return max(0, int(round(float(value) * 1000)))
    except (TypeError, ValueError):
        return 0


def _segments(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, list):
        return []
    result = []
    for row in body:
        if not isinstance(row, dict):
            continue
        start = _ms(row.get("from"))
        end = max(start, _ms(row.get("to")))
        content = str(row.get("content") or "").strip()
        if content:
            result.append({"start_ms": start, "end_ms": end, "text": content})
    return sorted(result, key=lambda x: (x["start_ms"], x["end_ms"]))


def _bounds(times: list[int], start_ms: int, end_ms: int) -> tuple[int, int]:
    return bisect_left(times, start_ms), bisect_right(times, end_ms)


def _context(segments: list[dict[str, Any]], times: list[int], center_ms: int, radius_ms: int = 14_000) -> str:
    left, right = _bounds(times, center_ms - radius_ms, center_ms + radius_ms)
    return "".join(_feature_text(s["text"]) for s in segments[left:right])


def _seat_numbers(text: str) -> set[int]:
    text = _feature_text(text)
    seats = {int(m.group(1)) for m in re.finditer(r"(?<!\d)(1[0-2]|[1-9])\s*号", text)}
    # Captions sometimes flatten a roster into forms such as 狼人3/6/12、机械狼8.
    role = r"(?:机械狼|预言家|女巫|猎人|守卫|白痴|骑士|通灵师|摄梦人|丘比特|狼王|狼人|白狼王|石像鬼|禁言长老|觉醒愚者|大法师|平民|民牌)"
    for match in re.finditer(role + r"\s*((?:1[0-2]|[1-9])(?:\s*[/、,，和及]\s*(?:1[0-2]|[1-9]))*)", text):
        seats.update(int(n) for n in re.findall(r"1[0-2]|[1-9]", match.group(1)))
    return seats


def _quote(segments: list[dict[str, Any]], times: list[int], center_ms: int, radius_ms: int = 8_000) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    left, right = _bounds(times, center_ms - radius_ms, center_ms + radius_ms)
    for s in segments[left:right]:
        if s["text"] not in seen:
            seen.add(s["text"])
            out.append({"time_ms": s["start_ms"], "text": s["text"][:72]})
            if len(out) >= 6:
                break
    return out


def _signal_evidence(segments: list[dict[str, Any]], times: list[int], anchor_ms: int,
                     feature_end_ms: int, end_ms: int | None, basis: str) -> list[dict[str, Any]]:
    left, right = _bounds(times, max(0, anchor_ms - 12_000), feature_end_ms)
    local = segments[left:right]
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()

    def add_text(time_ms: int, text: str) -> None:
        key = (time_ms, text)
        if key not in seen and len(result) < 8:
            seen.add(key)
            result.append({"time_ms": time_ms, "text": text[:96]})

    def add(row: dict[str, Any]) -> None:
        add_text(row["start_ms"], row["text"])

    recap = next((s for s in local if RECAP_RE.search(s["text"])), None)
    if recap:
        add(recap)
    role_rows = [s for s in local if ROLE_RE.search(_feature_text(s["text"])) or SEAT_RE.search(_feature_text(s["text"]))]
    for row in role_rows[:4]:
        add(row)
    matched_cues: set[str] = set()
    for i, row in enumerate(local):
        phrase = "".join(_feature_text(s["text"]) for s in local[i:min(i + 4, len(local))])
        for cue, pattern in ACTION_PATTERNS:
            if cue not in matched_cues and pattern.search(phrase):
                add_text(row["start_ms"], "".join(s["text"] for s in local[i:min(i + 4, len(local))]))
                matched_cues.add(cue)
        if len(matched_cues) >= 3:
            break
    if end_ms is not None:
        end_left, end_right = _bounds(times, end_ms - 12_000, end_ms + 5_000)
        end_rows = segments[end_left:end_right]
        for row in end_rows:
            if any(pattern.search(_feature_text(row["text"])) for _, pattern in END_PATTERNS):
                add(row)
                break
    return result


def _features(segments: list[dict[str, Any]], times: list[int], start_ms: int, end_ms: int) -> tuple[int, list[str], set[str]]:
    left, right = _bounds(times, start_ms, end_ms)
    text = _feature_text("".join(s["text"] for s in segments[left:right]))
    all_roles = set(ROLE_RE.findall(text))
    seats = _seat_numbers(text)
    # Count a continuous roster by distinct seats; captions frequently split or
    # reorder role and seat tokens across consecutive subtitle segments.
    role_lines = len(seats) if all_roles else 0
    cues = sorted({name for name, pattern in ACTION_PATTERNS if pattern.search(text)})
    return role_lines, cues, all_roles


def _dense_roster_span(segments: list[dict[str, Any]], times: list[int], search_start_ms: int,
                       search_end_ms: int, *, min_seats: int = 6, min_roles: int = 3,
                       span_ms: int = 20_000) -> tuple[int, int] | None:
    left, right = _bounds(times, search_start_ms, search_end_ms)
    role_indices = [i for i in range(left, right)
                    if ROLE_RE.search(_feature_text(segments[i]["text"]))
                    or SEAT_RE.search(_feature_text(segments[i]["text"]))]
    for index in role_indices:
        start = times[index]
        end = min(search_end_ms, start + span_ms)
        local_left, local_right = _bounds(times, start, end)
        text = _feature_text("".join(s["text"] for s in segments[local_left:local_right]))
        if len(_seat_numbers(text)) >= min_seats and len(set(ROLE_RE.findall(text))) >= min_roles:
            # Keep the whole concentrated identity run, even if captions split
            # seats and roles. The later action scan establishes the end floor.
            return start, max(s["end_ms"] for s in segments[local_left:local_right]
                              if ROLE_RE.search(_feature_text(s["text"]))
                              or SEAT_RE.search(_feature_text(s["text"])))
    return None


def _first_action_end(segments: list[dict[str, Any]], times: list[int], roster_start_ms: int,
                      roster_end_ms: int, search_end_ms: int) -> int | None:
    left, right = _bounds(times, roster_start_ms, search_end_ms)
    rows = segments[left:right]
    # Scan short caption runs so an action phrase split between captions remains
    # recognizable. Starting at the roster span prevents a previous game's
    # winner announcement from ending the recap window.
    for i, row in enumerate(rows):
        phrase_rows = [row]
        for later in rows[i + 1:i + 4]:
            if later["start_ms"] - phrase_rows[-1]["end_ms"] > 4_000:
                break
            phrase_rows.append(later)
        phrase = _feature_text("".join(s["text"] for s in phrase_rows))
        if any(pattern.search(phrase) for _, pattern in ACTION_PATTERNS):
            return max(roster_end_ms, max(s["end_ms"] for s in phrase_rows))
    return None


def _explicit_anchors(segments: list[dict[str, Any]], times: list[int]) -> list[int]:
    anchors = []
    for s in segments:
        if not RECAP_RE.search(s["text"]):
            continue
        context = _context(segments, times, s["start_ms"], 12_000)
        if FUTURE_RE.search(context):
            continue
        if EXPLICIT_RECAP_RE.search(context):
            anchors.append(s["start_ms"])
    return anchors


def _candidate_anchors(segments: list[dict[str, Any]], times: list[int]) -> list[tuple[int, str]]:
    explicit = _explicit_anchors(segments, times)
    found = [(t, "explicit_recap_intro") for t in explicit]
    # Programs without a formal recap introduction can be localized from a
    # genuinely concentrated, complete roster followed by night actions.
    role_indices = [i for i, s in enumerate(segments) if ROLE_RE.search(s["text"]) or SEAT_RE.search(s["text"])]
    last_roster_anchor = -100_000
    for index in role_indices:
        anchor = segments[index]["start_ms"]
        span = _dense_roster_span(segments, times, anchor, anchor + 20_000,
                                  min_seats=8, min_roles=4, span_ms=20_000)
        if not span:
            continue
        roster_start, _ = span
        title_left, title_right = _bounds(times, max(0, roster_start - 5_000), roster_start + 1_000)
        title_pattern = re.compile(r"版型|身份名单|角色名单|角色配置")
        title_rows = [s for s in segments[title_left:title_right] if title_pattern.search(_feature_text(s["text"]))]
        if title_rows:
            roster_start = title_rows[0]["start_ms"]
        local_context = _context(segments, times, roster_start + 10_000, 15_000)
        formal_roster = bool(re.search(r"本局版型|本局游戏|本场版型|版型|(?:好人|狼人|神人|平民)阵营", local_context))
        prior_context = _context(segments, times, roster_start - 60_000, 60_000)
        formal_finish = any(name == "faction_result" and pattern.search(prior_context)
                            for name, pattern in END_PATTERNS)
        _, cues, _ = _features(segments, times, roster_start, roster_start + 90_000)
        if (formal_roster or formal_finish) and len(cues) >= 2 and roster_start - last_roster_anchor > MAX_CANDIDATE_MS:
            found.append((roster_start, "complete_roster_plus_night_actions"))
            last_roster_anchor = roster_start
    found.sort()
    # Merge nearby anchors into one event. Keep the strongest basis and earliest
    # start; this prevents dense caption fragments from duplicating a window.
    merged: list[tuple[int, str]] = []
    for anchor, basis in found:
        if merged and anchor - merged[-1][0] <= 75_000:
            old_t, old_basis = merged[-1]
            if basis == "explicit_recap_intro" and old_basis != "explicit_recap_intro":
                merged[-1] = (min(old_t, anchor), basis)
        else:
            merged.append((anchor, basis))
    return merged


def _end_candidate(segments: list[dict[str, Any]], times: list[int], start_ms: int, duration_ms: int,
                   end_search_floor_ms: int | None, after_ms: int = BUFFER_AFTER_MS) -> tuple[int | None, str | None]:
    if end_search_floor_ms is None:
        return None, None
    floor = max(start_ms, end_search_floor_ms)
    ceiling = min(duration_ms, start_ms + MAX_CANDIDATE_MS)
    left, right = _bounds(times, floor, ceiling)
    for s in segments[left:right]:
        for name, pattern in END_PATTERNS:
            if pattern.search(s["text"]):
                # A result line can occur early in recap commentary. Require a
                # minimum lead-in and leave a short tail to catch the handoff.
                return min(duration_ms, s["end_ms"] + after_ms), name
    return None, None


def analyze_subtitle(segments: list[dict[str, Any]], duration_ms: int, *,
                     subtitle_present: bool = True, subtitle_truncated: bool = False,
                     before_ms: int = BUFFER_BEFORE_MS, after_ms: int = BUFFER_AFTER_MS) -> tuple[str, list[dict[str, Any]]]:
    """Return status and windows for already-normalized subtitle segments."""
    if not subtitle_present or not segments:
        start = max(0, duration_ms - LOCALIZE_MS)
        return "tail_probe", [_window(start, duration_ms, ["missing_subtitle_tail_probe"], 0, [], [], exact=False)]

    times = [s["start_ms"] for s in segments]
    candidates: list[dict[str, Any]] = []
    for anchor, basis in _candidate_anchors(segments, times):
        feature_end = min(duration_ms, anchor + 90_000)
        roster = _dense_roster_span(segments, times, anchor, feature_end,
                                    min_seats=6, min_roles=3, span_ms=20_000)
        if roster:
            roster_start, roster_end = roster
            roles, _, unique_roles = _features(segments, times, roster_start, roster_end)
            # Action narration can share the final roster caption, so inspect
            # the whole post-anchor passage while requiring the end marker to
            # wait until _first_action_end below.
            _, cues, _ = _features(segments, times, roster_start, feature_end)
            action_floor = _first_action_end(segments, times, roster_start, roster_end,
                                             min(duration_ms, anchor + MAX_CANDIDATE_MS))
        else:
            roles, cues, unique_roles = _features(segments, times, max(0, anchor - 8_000), feature_end)
            action_floor = None
        explicit = basis == "explicit_recap_intro"
        strong = (roster is not None and roles >= 6 and len(unique_roles) >= 3
                  and len(cues) >= 2 and action_floor is not None)
        if not explicit and not (roles >= 8 and len(unique_roles) >= 4 and len(cues) >= 2):
            continue
        start = max(0, anchor - before_ms)
        end_mark, end_basis = _end_candidate(segments, times, anchor, duration_ms,
                                             action_floor, after_ms)
        confidence = "candidate" if strong else "needs_localization"
        cap_end = min(duration_ms, start + MAX_CANDIDATE_MS)
        if confidence == "needs_localization":
            end = min(duration_ms, start + LOCALIZE_MS)
            window_basis = [basis, "weak_evidence_localization"]
        elif end_mark is not None:
            end = min(end_mark, cap_end)
            window_basis = [basis, "post_recap_transition:" + str(end_basis)]
        else:
            end = cap_end
            window_basis = [basis, "capped_at_3_minutes_no_transition_caption"]
        if end <= start:
            continue
        evidence = _signal_evidence(segments, times, anchor, feature_end, end_mark, basis)
        if end_basis:
            evidence += [e for e in _quote(segments, times, end_mark or anchor, 3_000) if e not in evidence]
        window = _window(start, end, window_basis, roles, cues, evidence, exact=False)
        window["unique_role_terms"] = sorted(unique_roles)
        window["status"] = confidence
        candidates.append(window)

    # Deduplicate overlapping windows without expanding the merged interval.
    candidates.sort(key=lambda w: w["start_ms"])
    deduped: list[dict[str, Any]] = []
    for window in candidates:
        overlaps = [i for i, old in enumerate(deduped)
                    if window["start_ms"] < old["end_ms"] and old["start_ms"] < window["end_ms"]
                    and abs(window["start_ms"] - old["start_ms"]) <= 75_000]
        if overlaps:
            i = overlaps[0]
            old = deduped[i]
            limit = MAX_CANDIDATE_MS if "candidate" in (old["status"], window["status"]) else LOCALIZE_MS
            start = min(old["start_ms"], window["start_ms"])
            end = min(max(old["end_ms"], window["end_ms"]), start + limit)
            old["start_ms"] = start
            old["end_ms"] = end
            old["basis"] = list(dict.fromkeys(old["basis"] + window["basis"]))
            old["action_cues"] = sorted(set(old["action_cues"]) | set(window["action_cues"]))
            old["role_line_count"] = max(old["role_line_count"], window["role_line_count"])
            old["evidence"] = (old["evidence"] + [e for e in window["evidence"] if e not in old["evidence"]])[:8]
            old["unique_role_terms"] = sorted(set(old.get("unique_role_terms", [])) | set(window.get("unique_role_terms", [])))
            if window["status"] == "candidate":
                old["status"] = "candidate"
        else:
            deduped.append(window)

    if deduped:
        strong_count = sum(w["status"] == "candidate" for w in deduped)
        if strong_count > 1:
            return "review", deduped
        if strong_count == 1:
            return "candidate", deduped
        return "needs_localization", deduped

    if subtitle_truncated:
        start = max(0, duration_ms - LOCALIZE_MS)
        return "tail_probe", [_window(start, duration_ms, ["truncated_subtitle_tail_probe"], 0, [], [], exact=False)]

    # A complete transcript with only vague recap mentions gets a bounded
    # localization window around the best mention, never an asserted detection.
    weak = [s for s in segments if RECAP_RE.search(s["text"]) and not FUTURE_RE.search(_context(segments, times, s["start_ms"], 8_000))]
    if weak:
        anchor = weak[-1]["start_ms"]
        start = max(0, anchor - before_ms)
        end = min(duration_ms, start + LOCALIZE_MS)
        return "needs_localization", [_window(start, end, ["recap_keyword_weak_or_context_incomplete"], 0, [], _quote(segments, times, anchor), exact=False)]
    return "needs_localization", []


def _window(start: int, end: int, basis: list[str], role_count: int, cues: list[str], evidence: list[dict[str, Any]], *, exact: bool) -> dict[str, Any]:
    return {
        "start_ms": int(start), "end_ms": int(end), "basis": basis,
        "role_line_count": int(role_count), "action_cues": list(cues),
        "evidence": evidence, "exact_boundary_verified": bool(exact),
        "expansion_strategy": ["5min", "10min", "20min", "manual_localization_no_full_audio_transcription"],
    }


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coverage_truncated(preferred: dict[str, Any], segments: list[dict[str, Any]], duration_ms: int) -> bool:
    coverage = preferred.get("coverage") if isinstance(preferred.get("coverage"), dict) else {}
    ratio = coverage.get("covered_ratio")
    if isinstance(ratio, (int, float)) and ratio < 0.72:
        return True
    last_s = coverage.get("last_seconds")
    if isinstance(last_s, (int, float)) and duration_ms and last_s * 1000 < duration_ms - 120_000:
        return True
    if segments and duration_ms and segments[-1]["end_ms"] < duration_ms - 120_000:
        return True
    return False


def build_plan(plan: dict[str, Any], progress: dict[str, Any], root: Path = ROOT,
               bvid: str | None = None) -> dict[str, Any]:
    items = progress.get("items", {})
    results = []
    for entry in plan.get("entries", []):
        if bvid and entry.get("bvid") != bvid:
            continue
        bvid_value, cid = entry.get("bvid"), entry.get("cid")
        record = items.get(f"{bvid_value}:{cid}", {}) if isinstance(items, dict) else {}
        preferred = record.get("preferred_chinese") if isinstance(record.get("preferred_chinese"), dict) else {}
        exports = record.get("exports") if isinstance(record.get("exports"), dict) else {}
        duration_ms = int(round(float(entry.get("duration_seconds") or 0) * 1000))
        audio_file = exports.get("audio")
        subtitle_file = preferred.get("raw")
        subtitle_path = root / subtitle_file if subtitle_file else None
        present = bool(subtitle_path and subtitle_path.is_file())
        raw_sub = {}
        if present and subtitle_path:
            try:
                raw_sub = json.loads(subtitle_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                present = False
        segments = _segments(raw_sub.get("body"))
        truncated = _coverage_truncated(preferred, segments, duration_ms)
        status, windows = analyze_subtitle(segments, duration_ms, subtitle_present=present,
                                          subtitle_truncated=truncated)
        results.append({
            "bvid": bvid_value, "cid": cid, "title": entry.get("title"),
            "audio_file": audio_file, "audio_duration_ms": duration_ms,
            "subtitle_file": subtitle_file,
            "subtitle_sha256": _sha256(subtitle_path) if present and subtitle_path else preferred.get("sha256"),
            "subtitle_present": present, "subtitle_truncated": truncated,
            "status": status, "windows": windows,
        })
    summary = _summarize(results)
    return {"schema_version": 1, "season": plan.get("season"), "items": results, "summary": summary}


def _summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(item["status"] for item in items)
    audio_total = sum(item["audio_duration_ms"] for item in items)
    all_windows = [(item, w) for item in items for w in item["windows"]]
    candidate_windows = [(item, w) for item, w in all_windows if w.get("status", item["status"]) == "candidate"]
    weak_windows = [(item, w) for item, w in all_windows if w.get("status", item["status"]) == "needs_localization"]
    candidate_ms = sum(w["end_ms"] - w["start_ms"] for _, w in candidate_windows)
    weak_ms = sum(w["end_ms"] - w["start_ms"] for _, w in weak_windows)
    tail_ms = sum(w["end_ms"] - w["start_ms"] for item in items for w in item["windows"] if item["status"] == "tail_probe")
    planned_ms = 0
    for item in items:
        merged: list[list[int]] = []
        for window in sorted(item["windows"], key=lambda w: w["start_ms"]):
            if merged and window["start_ms"] <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], window["end_ms"])
            else:
                merged.append([window["start_ms"], window["end_ms"]])
        planned_ms += sum(end - start for start, end in merged)
    longest = max(all_windows, key=lambda pair: pair[1]["end_ms"] - pair[1]["start_ms"], default=None)
    cannot_locate = [item["bvid"] for item in items if item["status"] == "needs_localization" and not item["windows"]]
    return {
        "item_count": len(items), "window_count": len(all_windows),
        "total_audio_duration_ms": audio_total,
        "candidate_window_count": len(candidate_windows), "candidate_window_duration_ms": candidate_ms,
        "weak_window_count": len(weak_windows), "weak_window_duration_ms": weak_ms,
        "tail_probe_duration_ms": tail_ms, "total_planned_duration_ms": planned_ms,
        "longest_window": ({"bvid": longest[0]["bvid"], "start_ms": longest[1]["start_ms"],
                            "end_ms": longest[1]["end_ms"],
                            "duration_ms": longest[1]["end_ms"] - longest[1]["start_ms"]} if longest else None),
        "not_locatable_count": len(cannot_locate), "not_locatable_bvids": cannot_locate,
        "status_counts": dict(sorted(statuses.items())),
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", default=str(DEFAULT_PLAN), help="collection index JSON")
    parser.add_argument("--progress", default=str(DEFAULT_PROGRESS), help="collection progress JSON")
    parser.add_argument("--out", required=True, help="output JSON plan")
    parser.add_argument("--bvid", help="plan one Bilibili video")
    args = parser.parse_args(argv)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    progress = json.loads(Path(args.progress).read_text(encoding="utf-8"))
    result = build_plan(plan, progress, ROOT, args.bvid)
    output = Path(args.out)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(output), **result["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
