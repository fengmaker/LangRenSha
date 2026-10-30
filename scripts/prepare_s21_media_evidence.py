"""Build S21 transcript and visual-review time indexes from saved local sources.

This script does not download media, run ASR, or assert game facts. All detected
recaps and spoken cues are text-based candidates that still need visual review.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "data/indexes/S21_采集计划.json"
CAPTIONS = ROOT / "data/seasons/S21/S21_中文优先复核目录.csv"
LIGHT_REVIEW = ROOT / "data/seasons/S21/S21_全文转写与轻校对目录.csv"
OUT = ROOT / "data/extractions/S21/media_evidence"
REPORT_JSON = ROOT / "data/reports/S21/S21_文字与截图时点索引.json"
REPORT_CSV = ROOT / "data/exports/S21_文字与截图时点索引.csv"

ROLE_RE = re.compile(r"机械双刀狼|机械通灵师|机械女巫|机械猎人|机械守卫|机械平民|机械狼|预言家|通灵师|女巫|猎人|守卫|白痴|白神|骑士|摄梦人|摄梦师|混血儿|狼人|狼王|平民|毒师|盗宝大师|假面|舞者|魔术师|诡术师|典狱长")
SEAT_RE = re.compile(r"(?<!\d)(?:1[0-2]|[1-9])\s*号")
SEAT_WORD_RE = re.compile(r"(?<![一二三四五六七八九十百])(?:十一|十二|一|二|两|三|四|五|六|七|八|九|十)\s*号")
RECAP_WORD_RE = re.compile(r"复盘|回顾本局|复盘本局")
RECAP_INTRO_RE = re.compile(
    r"(?:本局|这局|本场|本游戏|这一局).{0,12}(?:游戏)?(?:复盘|回顾)|"
    r"(?:复盘|回顾).{0,14}(?:本局|这局|本场|本游戏|这一局)|"
    r"(?:给|为).{0,18}(?:弹幕|大家|各位|观众).{0,12}(?:做|来|讲|进行).{0,14}(?:本局|这局|本游戏|复盘)|"
    r"(?:做|来|进行).{0,12}(?:本局|这局|本游戏|这一局).{0,10}(?:的)?复盘"
)
RECAP_HEADING_RE = re.compile(r"(?:本局|这局|本场|本游戏).{0,8}(?:版型|身份配置|身份名单|角色配置|角色名单)|(?:本局)?版型(?:为|是)")
FUTURE_RECAP_RE = re.compile(r"(?:稍后|待会儿?|一会儿?|之后|结束后|下播前).{0,18}(?:复盘|回顾)|(?:复盘|回顾).{0,12}(?:稍后|待会儿?|一会儿?|之后)")
RECAP_EXPLICIT_RE = re.compile(r"复盘|回顾")
RECAP_TRANSITION_RE = re.compile(r"复盘(?:就到这里|结束|完了|完毕)|以上就是.{0,10}(?:复盘|回顾)|下一局|下一把|下一场|准备开局|进入下一局|再来一局|下一个游戏")
VOTE_START_RE = re.compile(r"(?:现在|开始|请|进行|大家|各位|所有人|全体|时间到).{0,8}(?:开始)?投票|请.{0,8}投票|开始投票|投票开始|请投出")
VOTE_END_RE = re.compile(r"投票结束|停止投票|公布(?:投票)?结果|宣布(?:投票)?结果|投票结果|放逐票(?:型|结果)|归票结束")
VOTE_CAST_RE = re.compile(r"(?:我|那我|我这边)?投(?:给|向|票给)?\s*(?:1[0-2]|[1-9]|十一|十二|一|二|两|三|四|五|六|七|八|九|十)\s*号|(?:投给|票给)\s*(?:1[0-2]|[1-9]|十一|十二|一|二|两|三|四|五|六|七|八|九|十)\s*号")
DEATH_RE = re.compile(r"(?:昨夜|昨晚|昨天晚上).{0,20}(?:死亡|出局|倒牌|被刀|离场|不在|平安|没有死)|(?:1[0-2]|[1-9]|十一|十二|一|二|两|三|四|五|六|七|八|九|十)\s*号.{0,8}(?:死亡|出局|倒牌|被放逐|被淘汰|离场)|(?:宣布|公布|播报).{0,12}(?:死亡|出局|倒牌|死讯)")
NIGHT_ENTRY_RE = re.compile(r"天黑(?:了)?请闭眼|天黑了|请所有(?:玩家|人)闭眼|请大家闭眼|所有玩家请闭眼|入夜|进入夜晚|夜晚开始|开始夜间行动|开始夜晚|首夜|第一夜|第(?:[一二三四五六七八九十0-9]+)夜")
NEXT_GAME_RE = re.compile(r"下一局|下一把|下一场|准备开局|进入下一局|再来一局|下一个游戏")
ROLE_CONFIG_RE = re.compile(r"版型|身份配置|身份名单|角色配置|角色名单|神职阵营|平民阵营|狼人阵营|好人阵营")
GAME_START_RE = re.compile(r"看牌|看身份|发身份|五秒后进入天黑|进入天黑|开始游戏|游戏开始|天黑请闭眼")
GAME_END_RE = re.compile(r"好人阵营获胜|狼人阵营获胜|好人(?:阵营)?胜利|狼人(?:阵营)?胜利|游戏结束|狼队获胜|屠神获胜|屠民获胜")


def read_csv(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["BVID"]: row for row in csv.DictReader(handle)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    source_rows = value.get("segments", value.get("body", []))
    result: list[dict[str, Any]] = []
    for i, row in enumerate(source_rows):
        if not isinstance(row, dict):
            continue
        if "start_ms" in row:
            start = int(round(float(row["start_ms"])))
            end = int(round(float(row.get("end_ms", row["start_ms"]))))
            text = row.get("text", "")
        elif "start" in row:
            start = int(round(float(row["start"]) * 1000))
            end = int(round(float(row.get("end", row["start"])) * 1000))
            text = row.get("text", "")
        else:
            start = int(round(float(row.get("from", 0)) * 1000))
            end = int(round(float(row.get("to", row.get("from", 0))) * 1000))
            text = row.get("content", "")
        if not isinstance(text, str) or not text.strip():
            continue
        result.append({"index": len(result), "source_segment_index": i,
                       "start_ms": max(0, start), "end_ms": max(max(0, start), end), "text": text})
    return result


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def context_text(rows: list[dict[str, Any]], index: int, before_ms: int = 8000,
                 after_ms: int = 6000) -> str:
    center = rows[index]["start_ms"]
    return compact("".join(row["text"] for row in rows
                            if center - before_ms <= row["start_ms"] <= center + after_ms))


def _seat_matches(text: str) -> set[str]:
    values = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
              "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}
    result = {str(int(m.group(1))) for m in re.finditer(r"(?<!\d)(1[0-2]|[1-9])\s*号", text)}
    result.update(str(values[m.group(1)]) for m in re.finditer(
        r"(?<![一二三四五六七八九十百])(十一|十二|一|二|两|三|四|五|六|七|八|九|十)\s*号", text))
    return result


def dense_winner_recap_fallbacks(rows: list[dict[str, Any]], duration_ms: int) -> list[dict[str, Any]]:
    """Find late roster narration immediately followed by a winner/result cue."""
    late_cues = [r for r in rows if r["start_ms"] >= duration_ms * 0.55
                 and GAME_END_RE.search(compact(r["text"]))]
    clusters: list[list[dict[str, Any]]] = []
    for cue in late_cues:
        if clusters and cue["start_ms"] - clusters[-1][-1]["start_ms"] <= 45_000:
            clusters[-1].append(cue)
        else:
            clusters.append([cue])
    candidates = []
    for n, cluster in enumerate(clusters, 1):
        end_row = cluster[-1]
        window_start = max(0, end_row["start_ms"] - 45_000)
        region = [r for r in rows if window_start <= r["start_ms"] <= end_row["start_ms"]]
        role_rows = [r for r in region if ROLE_RE.search(compact(r["text"]))]
        role_set = set().union(*(set(ROLE_RE.findall(compact(r["text"]))) for r in region)) if region else set()
        seat_set = set().union(*(_seat_matches(r["text"]) for r in region)) if region else set()
        headings = [r for r in region if re.search(
            r"(?:本局|本游戏|本场).{0,5}(?:预言家|通灵师|版型|配置)|版型|身份配置|身份名单|角色配置|角色名单", compact(r["text"]))]
        strong_roster = len(seat_set) >= 8 and len(role_set) >= 4 and len(role_rows) >= 6
        headed_roster = bool(headings) and len(seat_set) >= 6 and len(role_set) >= 3 and len(role_rows) >= 4
        if not (strong_roster or headed_roster):
            continue
        first_row = headings[0] if headings else next((r for r in region if ROLE_RE.search(compact(r["text"])) or _seat_matches(r["text"])), end_row)
        start_ms = max(0, first_row["start_ms"] - 2000)
        # The winner caption onset is a useful temporal end candidate; retain its
        # full subtitle span separately so a reviewer can move to the spoken end.
        end_ms = end_row["start_ms"]
        evidence = [r for r in rows if start_ms <= r["start_ms"] <= end_ms]
        screenshot_candidates = [{"offset_after_estimated_recap_end_ms": offset, "time_ms": end_ms + offset,
                                  "within_media_duration": end_ms + offset < duration_ms,
                                  "status": "suggested_time_only_not_captured" if end_ms + offset < duration_ms else "out_of_bounds"}
                                 for offset in (0, 3000)]
        candidates.append({"candidate_id": f"recap-dense-{n:02d}", "start_ms": start_ms, "end_ms": end_ms,
                           "end_caption_end_ms": end_row["end_ms"],
                           "end_source_segment_index": end_row["source_segment_index"],
                           "anchor_ms": first_row["start_ms"],
                           "start_basis": "late_identity_heading_or_dense_role_seat_run",
                           "end_basis": "late_winner_caption_after_role_seat_run_approximate",
                           "status": "roster_dense_fallback_needs_visual_check",
                           "candidate_method": "postgame_dense_identity_and_winner_sequence_within_45s",
                           "explicit_recap_word": False,
                           "explicit_recap_anchor_missing": True,
                           "structured_identity_or_faction_cue": bool(headings),
                           "late_program_candidate": True,
                           "support_counts": {"role_terms": len(role_set), "role_segments": len(role_rows),
                                              "seat_tokens": len(seat_set), "faction_segments": sum(bool(re.search(r"神职阵营|平民阵营|狼人阵营|好人阵营", compact(r["text"]))) for r in region)},
                           "evidence": evidence[:160], "screenshot_candidates": screenshot_candidates,
                           "note": "45秒内出现密集身份/座位播报并接近胜方字幕；缺少复盘前导词，仍需核对是否为法官连续复盘。"})
    return candidates


def find_recap_candidates(rows: list[dict[str, Any]], duration_ms: int) -> dict[str, Any]:
    if not rows:
        return {"status": "no_transcript_segments", "candidates": []}
    anchors: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        ctx = context_text(rows, i)
        explicit_match = RECAP_INTRO_RE.search(ctx)
        heading_match = RECAP_HEADING_RE.search(ctx)
        explicit = bool(explicit_match) and not FUTURE_RECAP_RE.search(ctx)
        structured = bool(heading_match)
        if not (explicit or structured):
            continue
        # Recap introductions for later games are often previews, not the current
        # game's referee review. Keep only late anchors, and exclude next-game setup.
        late = row["start_ms"] >= duration_ms * 0.55
        if not late:
            continue
        around = [r for r in rows if abs(r["start_ms"] - row["start_ms"]) <= 60_000]
        if not explicit and any(GAME_START_RE.search(compact(r["text"])) for r in around):
            continue
        start = max(0, row["start_ms"] - 6000)
        anchors.append({"segment_index": row["index"], "anchor_ms": row["start_ms"],
                        "source_segment_index": row["source_segment_index"], "start_ms": start,
                        "matched_context": ctx[:220], "explicit_recap_word": explicit,
                        "structured_heading": structured, "late_program_candidate": late})
    # Cluster the introduction and identity/faction rows belonging to one review.
    clusters: list[list[dict[str, Any]]] = []
    for anchor in anchors:
        if clusters and anchor["anchor_ms"] - clusters[-1][-1]["anchor_ms"] <= 150_000:
            clusters[-1].append(anchor)
        else:
            clusters.append([anchor])
    # If no explicit lead-in was captioned, a dense roster ending at a late winner
    # announcement can still localize the referee's review.
    if not clusters:
        fallback = dense_winner_recap_fallbacks(rows, duration_ms)
        if fallback:
            for candidate in fallback:
                candidate["screenshot_candidates"] = []
                if candidate.get("end_ms") is not None:
                    for offset in (0, 3000):
                        t = candidate["end_ms"] + offset
                        candidate["screenshot_candidates"].append({"offset_after_estimated_recap_end_ms": offset,
                            "time_ms": t, "within_media_duration": t < duration_ms,
                            "status": "suggested_time_only_not_captured" if t < duration_ms else "out_of_bounds"})
            return {"status": "transcript_anchor_missing_fallback_found", "candidates": fallback}
        weak = [r for r in rows if RECAP_WORD_RE.search(r["text"])]
        if weak:
            row = weak[-1]
            return {"status": "weak_keyword_needs_localization", "candidates": [{
                "candidate_id": "recap-01", "start_ms": max(0, row["start_ms"]-5000), "end_ms": None,
                "start_basis": "latest_recap_keyword_only", "end_basis": "unresolved",
                "status": "weak_keyword_needs_localization", "evidence": [row],
                "screenshot_candidates": [], "note": "仅发现复盘词语，不能据此确认法官复盘。"}]}
        return {"status": "not_located", "candidates": []}

    candidates: list[dict[str, Any]] = []
    for n, cluster in enumerate(clusters, 1):
        # An explicit recap-intro is preferred; otherwise use the first structural anchor.
        chosen = next((a for a in cluster if a["explicit_recap_word"]), cluster[0])
        start_ms = min(a["start_ms"] for a in cluster if a["anchor_ms"] <= chosen["anchor_ms"] + 15_000) if cluster else chosen["start_ms"]
        anchor_ms = chosen["anchor_ms"]
        limit = min(duration_ms, anchor_ms + 240_000)
        later_anchor = next((c[0]["anchor_ms"] for c in clusters[n:] if c[0]["anchor_ms"] > anchor_ms + 150_000), None)
        if later_anchor:
            limit = min(limit, later_anchor)
        region = [r for r in rows if anchor_ms <= r["start_ms"] <= limit]
        role_rows = [r for r in region if ROLE_RE.search(compact(r["text"]))]
        seat_set = set().union(*(_seat_matches(r["text"]) for r in region)) if region else set()
        role_set = set().union(*(set(ROLE_RE.findall(compact(r["text"]))) for r in region)) if region else set()
        faction_rows = [r for r in region if re.search(r"神职阵营|平民阵营|狼人阵营|好人阵营", compact(r["text"]))]
        explicit = any(a["explicit_recap_word"] for a in cluster)
        structured = any(a["structured_heading"] or ROLE_CONFIG_RE.search(a["matched_context"]) for a in cluster)
        has_intro = any(RECAP_EXPLICIT_RE.search(a["matched_context"]) for a in cluster)
        strong = (explicit and len(role_set) >= 2 and (len(seat_set) >= 2 or faction_rows)) or (structured and len(role_set) >= 3 and (len(seat_set) >= 2 or faction_rows))

        transition = next((r for r in region if r["start_ms"] > anchor_ms + 10_000 and RECAP_TRANSITION_RE.search(compact(r["text"]))), None)
        relevant = [r for r in region if ROLE_RE.search(compact(r["text"])) or _seat_matches(r["text"])
                    or re.search(r"阵营|首夜|第[一二三四五六七八九十0-9]+天|第[一二三四五六七八九十0-9]+夜|昨夜|昨晚|拍刀|屠神|屠民|获胜|胜利|交牌|游戏结束", compact(r["text"]))]
        if transition:
            end_ms, end_basis = transition["end_ms"], "explicit_recap_or_next_game_transition"
        elif relevant:
            end_row = relevant[-1]
            end_ms, end_basis = end_row["end_ms"], "last_role_or_phase_result_cue_within_4min_approximate"
        else:
            end_ms, end_basis = None, "unresolved"
        start_row = min((r for r in rows if r["start_ms"] >= start_ms), key=lambda r: r["start_ms"], default=rows[0])
        evidence = [r for r in rows if start_ms <= r["start_ms"] <= (end_ms if end_ms else min(limit, anchor_ms + 35_000))]
        evidence = evidence[:160]
        if not evidence:
            evidence = [start_row]
        status = "candidate_needs_visual_check" if strong else "weak_candidate_needs_localization"
        screenshot_candidates = []
        if end_ms is not None:
            for offset in (0, 3000):
                t = end_ms + offset
                screenshot_candidates.append({"offset_after_estimated_recap_end_ms": offset,
                                              "time_ms": t, "within_media_duration": t < duration_ms,
                                              "status": "suggested_time_only_not_captured" if t < duration_ms else "out_of_bounds"})
        candidates.append({"candidate_id": f"recap-{n:02d}", "start_ms": start_ms, "end_ms": end_ms,
                           "start_basis": "judge_recap_or_identity_configuration_text_candidate",
                           "end_basis": end_basis, "status": status, "anchor_ms": anchor_ms,
                           "explicit_recap_word": explicit, "structured_identity_or_faction_cue": structured,
                           "late_program_candidate": chosen["late_program_candidate"],
                           "support_counts": {"role_terms": len(role_set), "role_segments": len(role_rows),
                                              "seat_tokens": len(seat_set), "faction_segments": len(faction_rows)},
                           "evidence": evidence, "screenshot_candidates": screenshot_candidates,
                           "note": "纯文本定位候选；起止边界和结算页画面均未目视核实。"})
    if not any(c["status"] == "candidate_needs_visual_check" for c in candidates):
        fallback = dense_winner_recap_fallbacks(rows, duration_ms)
        for candidate in fallback:
            overlapping = next((c for c in candidates if abs(c.get("start_ms", 0) - candidate["start_ms"]) <= 90_000), None)
            if overlapping:
                overlapping.update(candidate)
                overlapping["candidate_id"] = overlapping.get("candidate_id") or candidate["candidate_id"]
            else:
                if candidate.get("end_ms") is not None:
                    candidate["screenshot_candidates"] = [{"offset_after_estimated_recap_end_ms": offset,
                        "time_ms": candidate["end_ms"] + offset,
                        "within_media_duration": candidate["end_ms"] + offset < duration_ms,
                        "status": "suggested_time_only_not_captured" if candidate["end_ms"] + offset < duration_ms else "out_of_bounds"}
                        for offset in (0, 3000)]
                candidates.append(candidate)
    fallback_only = bool(candidates) and all(c.get("explicit_recap_anchor_missing") for c in candidates)
    status = ("transcript_anchor_missing_fallback_found" if fallback_only else
              "multiple_candidates_needs_review" if len(candidates) > 1 else candidates[0]["status"])
    return {"status": status, "candidates": candidates}


def _speech_commands(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patterns = [
        re.compile(r"(?P<seat>(?:1[0-2]|[1-9]|十一|十二|一|二|两|三|四|五|六|七|八|九|十)号)(?:玩家|选手|位|麦)?[^。！？]{0,12}请(?:你|您)?发言"),
        re.compile(r"请(?:你|您)?(?P<seat>(?:1[0-2]|[1-9]|十一|十二|一|二|两|三|四|五|六|七|八|九|十)号)(?:玩家|选手|位|麦)?(?:来|现在|继续|可以开始)?(?:进行)?发言"),
        re.compile(r"(?:有请|下面请)(?P<seat>(?:1[0-2]|[1-9]|十一|十二|一|二|两|三|四|五|六|七|八|九|十)号)(?:玩家|选手|位)?(?:进行)?发言"),
        re.compile(r"(?P<seat>(?:1[0-2]|[1-9]|十一|十二|一|二|两|三|四|五|六|七|八|九|十)号)(?:玩家|选手|位)?(?:开始|继续|可以)?发言"),
    ]
    result = []
    for row in rows:
        text = compact(row["text"])
        found = next((m for pattern in patterns if (m := pattern.search(text))), None)
        if not found or re.search(r"复盘|采访|遗言|回放|解说", text):
            continue
        result.append({"time_ms": row["start_ms"], "end_ms": row["end_ms"], "seat_text": found.group("seat"),
                       "text": row["text"], "source_segment_index": row["source_segment_index"],
                       "status": "explicit_speech_command_candidate_needs_visual_check"})
    return result


def find_time_cues(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        text = compact(row["text"])
        kinds = []
        if VOTE_START_RE.search(text): kinds.append("vote_call_candidate")
        if VOTE_END_RE.search(text): kinds.append("vote_result_or_close_candidate")
        if VOTE_CAST_RE.search(text): kinds.append("vote_cast_words_candidate")
        if DEATH_RE.search(text): kinds.append("death_or_night_result_candidate")
        if NIGHT_ENTRY_RE.search(text): kinds.append("night_entry_or_night_command_candidate")
        for kind in kinds:
            result.append({"type": kind, "start_ms": row["start_ms"], "end_ms": row["end_ms"],
                           "text": row["text"], "source_segment_index": row["source_segment_index"],
                           "status": "text_cue_candidate_not_verified_as_game_event"})
    return result


def build_frame_candidates(rows: list[dict[str, Any]], recap: dict[str, Any],
                           duration_ms: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def add(kind: str, time_ms: int, reason: str, source_indices: list[int]) -> None:
        result.append({"kind": kind, "time_ms": int(time_ms), "reason": reason,
                       "source_segment_indices": sorted(set(source_indices)),
                       "within_media_duration": 0 <= int(time_ms) < duration_ms,
                       "status": "suggested_time_only_not_captured" if 0 <= int(time_ms) < duration_ms else "out_of_bounds"})

    for candidate in recap.get("candidates", []):
        start_ms, end_ms = candidate.get("start_ms"), candidate.get("end_ms")
        if start_ms is None:
            continue
        start_row = min(rows, key=lambda r: abs(r["start_ms"] - start_ms), default=None)
        start_indices = [start_row["source_segment_index"]] if start_row else []
        add("settlement_recap_start_minus_5s", start_ms - 5000,
            "法官复盘候选起点前5秒，检查可能在复盘前切出的结算页", start_indices)
        if end_ms is not None:
            span = end_ms - start_ms
            for ratio in (0.70, 0.80, 0.90):
                t = start_ms + int(round(span * ratio))
                nearest = min(rows, key=lambda r: abs(r["start_ms"] - t), default=None)
                indices = [nearest["source_segment_index"]] if nearest else []
                add(f"settlement_during_recap_{int(ratio*100)}pct", t,
                    f"复盘候选时长约{int(ratio*100)}%处，采样是否已显示结算页", indices)
            end_row = next((r for r in rows if r["source_segment_index"] == candidate.get("end_source_segment_index")), None)
            if end_row is None:
                end_row = min(rows, key=lambda r: abs(r["end_ms"] - end_ms), default=None)
            end_indices = [end_row["source_segment_index"]] if end_row else []
            for offset in (-5000, -3000, -1000, 0, 3000):
                kind = (f"settlement_recap_end_minus_{abs(offset)//1000}s" if offset < 0
                        else f"settlement_recap_end_plus_{offset//1000}s")
                add(kind, end_ms + offset,
                    (f"复盘结束时间候选前{abs(offset)//1000}秒，检查可能提前显示的结算页" if offset < 0
                     else f"复盘结束时间候选后{offset//1000}秒，检查结算页；仅时间建议"), end_indices)
        end_limit = end_ms if end_ms is not None else start_ms
        result_cues = [r for r in rows if 0 <= end_limit - r["start_ms"] <= 600_000
                       and r["start_ms"] < end_limit + 1 and GAME_END_RE.search(compact(r["text"]))]
        for cue in result_cues[-3:]:
            cue_idx = cue["source_segment_index"]
            for delta in (-3000, -1000, 0, 3000):
                t = cue["start_ms"] + delta
                kind = "settlement_near_game_end_cue" if delta == 0 else f"settlement_near_game_end_cue_{delta:+d}ms"
                add(kind, t, "胜负/游戏结束原字幕前后附近候选，需查看该时点画面", [cue_idx])
    if not result:
        # No recap anchor may mean that the original subtitle track omitted the
        # judge review. Retain late game-end text times for targeted sampling.
        late_floor = int(duration_ms * 0.55)
        end_cues = [r for r in rows if r["start_ms"] >= late_floor and GAME_END_RE.search(compact(r["text"]))]
        for cue in end_cues[-3:]:
            cue_idx = cue["source_segment_index"]
            for delta in (-3000, -1000, 0, 3000):
                t = cue["start_ms"] + delta
                kind = "settlement_near_game_end_cue" if delta == 0 else f"settlement_near_game_end_cue_{delta:+d}ms"
                add(kind, t, "没有明确复盘锚点；取片尾胜负字幕前后作为结算页定位候选", [cue_idx])
    merged: dict[tuple[str, int], dict[str, Any]] = {}
    for row in result:
        key = (row["kind"], row["time_ms"])
        if key not in merged:
            merged[key] = row
        else:
            old = merged[key]
            old["source_segment_indices"] = sorted(set(old["source_segment_indices"] + row["source_segment_indices"]))
    return sorted(merged.values(), key=lambda row: (row["time_ms"], row["kind"]))


def prepare(limit: int | None = None) -> dict[str, Any]:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    scoped_entries = [entry for entry in plan["entries"]
                      if entry.get("labels", {}).get("phase_candidate") in {"regular", "finals_week"}]
    if limit is not None:
        scoped_entries = scoped_entries[:limit]
    captions = read_csv(CAPTIONS)
    local_rows = read_csv(LIGHT_REVIEW)
    items = []
    csv_rows = []
    for entry in scoped_entries:
        bvid = entry["bvid"]
        caption = captions.get(bvid)
        local = local_rows.get(bvid)
        if caption is None:
            raise ValueError(f"Missing caption directory row for {bvid}")
        selected_rel = (local or {}).get("轻校对JSON") or caption.get("中文字幕原件")
        origin = "local_light_review" if (local or {}).get("轻校对JSON") else "platform_original_chinese_subtitle"
        if not selected_rel:
            selected_rel = caption.get("本地轻校对JSON") or caption.get("本地全文JSON")
            origin = "local_transcript_fallback_unexpected"
        if not selected_rel or not (ROOT / selected_rel).is_file():
            raise FileNotFoundError(f"Selected source missing for {bvid}: {selected_rel!r}")
        selected_path = ROOT / selected_rel
        segments = normalize(selected_path)
        duration_ms = int(round(float(entry.get("duration_seconds") or 0) * 1000))
        if origin == "local_light_review":
            related = {"original_transcript_path": (local or {}).get("模型原稿JSON"),
                       "light_review_corrections_path": (local or {}).get("逐条修改记录"),
                       "audio_path": (local or {}).get("音频文件")}
        else:
            related = {"platform_raw_chinese_subtitle_path": caption.get("中文字幕原件"),
                       "platform_chinese_srt_path": caption.get("中文字幕SRT"),
                       "audio_path": caption.get("音频文件")}
        source_hashes = {"selected_source_sha256": sha256(selected_path)}
        for key, rel in related.items():
            if rel and (ROOT / rel).is_file():
                source_hashes[key.replace("_path", "_sha256")] = sha256(ROOT / rel)
        record = {"index": entry["index"], "bvid": bvid, "cid": entry["cid"], "page": entry.get("page"),
                  "title": entry["title"], "duration_ms": duration_ms,
                  "phase_candidate": entry.get("labels", {}).get("phase_candidate"),
                  "date_candidate": entry.get("labels", {}).get("event_date_candidate"),
                  "selected_transcript_origin": origin, "selected_source_path": selected_rel,
                  "related_sources": related, "source_hashes": source_hashes,
                  "selected_segment_count": len(segments), "transcript_selected_path": f"data/extractions/S21/media_evidence/{bvid}/transcript.selected.json"}
        recap = find_recap_candidates(segments, duration_ms)
        commands = _speech_commands(segments)
        # The recap comes after regular speech. Use the most recent explicit command before its earliest candidate.
        first_recap = min((c["start_ms"] for c in recap["candidates"] if c.get("start_ms") is not None), default=duration_ms)
        prior_commands = [c for c in commands if c["time_ms"] < first_recap]
        last_speech = prior_commands[-1] if prior_commands else None
        cues = find_time_cues(segments)
        frame_candidates = build_frame_candidates(segments, recap, duration_ms)
        folder = OUT / bvid
        folder.mkdir(parents=True, exist_ok=True)
        selected = {"schema_version": 1, "bvid": bvid, "source_path": selected_rel,
                    "source_sha256": source_hashes["selected_source_sha256"], "origin": origin,
                    "related_sources": related,
                    "source_sha256_by_related_source": {k: v for k, v in source_hashes.items() if k != "selected_source_sha256"},
                    "timestamp_unit": "milliseconds", "text_preservation": "source text copied verbatim; no normalization applied",
                    "segments": segments}
        (folder / "transcript.selected.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        recap_out = {"schema_version": 1, "bvid": bvid, "source_path": selected_rel,
                     "source_sha256": source_hashes["selected_source_sha256"], "duration_ms": duration_ms,
                     "recap_location": recap,
                     "last_game_day_speech_command": last_speech,
                     "speech_command_candidates_before_recap": commands,
                     "time_cue_candidates": cues,
                     "frame_candidates": frame_candidates,
                     "visual_review_verified": False,
                     "fact_extraction_performed": False}
        (folder / "recap_candidates.json").write_text(json.dumps(recap_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        record["recap_status"] = recap["status"]
        record["recap_candidates"] = [{k: c.get(k) for k in ("candidate_id", "start_ms", "end_ms", "status", "end_basis", "screenshot_candidates", "support_counts")} for c in recap["candidates"]]
        record["last_game_day_speech_command"] = last_speech
        record["speech_command_candidate_count"] = len(commands)
        record["time_cue_counts"] = dict(Counter(c["type"] for c in cues))
        record["frame_candidates"] = frame_candidates
        record["recap_candidates_path"] = f"data/extractions/S21/media_evidence/{bvid}/recap_candidates.json"
        record["entry_path"] = f"data/extractions/S21/media_evidence/{bvid}/entry.json"
        (folder / "entry.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        items.append(record)

        if not recap["candidates"]:
            csv_rows.append({"index": entry["index"], "bvid": bvid, "title": entry["title"],
                             "timeline_type": "recap_not_found", "start_ms": "", "end_ms": "",
                             "status": recap["status"], "text": "", "source_path": selected_rel,
                             "record_path": record["recap_candidates_path"]})
        for candidate in recap["candidates"]:
            quote = " | ".join(r["text"] for r in candidate.get("evidence", [])[:12])
            csv_rows.append({"index": entry["index"], "bvid": bvid, "title": entry["title"],
                             "timeline_type": candidate["candidate_id"], "start_ms": candidate.get("start_ms"),
                             "end_ms": candidate.get("end_ms"), "status": candidate["status"],
                             "text": quote, "source_path": selected_rel,
                             "record_path": record["recap_candidates_path"]})
            for shot in candidate.get("screenshot_candidates", []):
                csv_rows.append({"index": entry["index"], "bvid": bvid, "title": entry["title"],
                                 "timeline_type": f"{candidate['candidate_id']}_settlement_shot_{shot['offset_after_estimated_recap_end_ms']}ms",
                                 "start_ms": shot["time_ms"], "end_ms": shot["time_ms"], "status": shot["status"],
                                 "text": "结算页截图建议时间，仅候选未截图", "source_path": selected_rel,
                                 "record_path": record["recap_candidates_path"]})
        if last_speech:
            csv_rows.append({"index": entry["index"], "bvid": bvid, "title": entry["title"],
                             "timeline_type": "last_game_day_speech_command_candidate", "start_ms": last_speech["time_ms"],
                             "end_ms": last_speech["end_ms"], "status": last_speech["status"], "text": last_speech["text"],
                             "source_path": selected_rel, "record_path": record["recap_candidates_path"]})
        else:
            csv_rows.append({"index": entry["index"], "bvid": bvid, "title": entry["title"],
                             "timeline_type": "last_game_day_speech_command_not_found", "start_ms": "", "end_ms": "",
                             "status": "not_found_in_selected_text", "text": "", "source_path": selected_rel,
                             "record_path": record["recap_candidates_path"]})
        for cue in cues:
            csv_rows.append({"index": entry["index"], "bvid": bvid, "title": entry["title"],
                             "timeline_type": cue["type"], "start_ms": cue["start_ms"], "end_ms": cue["end_ms"],
                             "status": cue["status"], "text": cue["text"], "source_path": selected_rel,
                             "record_path": record["recap_candidates_path"]})
        for frame in frame_candidates:
            csv_rows.append({"index": entry["index"], "bvid": bvid, "title": entry["title"],
                             "timeline_type": f"frame_candidate:{frame['kind']}", "start_ms": frame["time_ms"],
                             "end_ms": frame["time_ms"], "status": frame["status"], "text": frame["reason"],
                             "source_path": selected_rel, "record_path": record["entry_path"]})

    statuses = Counter(item["recap_status"] for item in items)
    in_scope_total = sum(e.get("labels", {}).get("phase_candidate") in {"regular", "finals_week"} for e in plan["entries"])
    summary = {"collection_media_count": len(plan["entries"]), "planned_media_count": in_scope_total,
               "indexed_media_count": len(items), "indexed_this_run_count": len(items),
               "excluded_by_user_count": len(plan["entries"]) - in_scope_total,
               "source_origin_counts": dict(Counter(i["selected_transcript_origin"] for i in items)),
               "recap_status_counts": dict(statuses),
               "recap_candidate_count": sum(len(i["recap_candidates"]) for i in items),
               "recap_candidate_missing_count": sum(not i["recap_candidates"] for i in items),
               "settlement_screenshot_suggestions": "near game-end text cue, recap end -1/3/5s, recap 70/80/90 percent, and recap estimated end +0/3s; time-only proposals, none captured",
               "speech_command_missing_count": sum(i["last_game_day_speech_command"] is None for i in items),
               "visual_review_verified": False, "game_facts_written": False}
    report = {"schema_version": 1, "season": "S21", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "method": "user-scoped regular/finals_week media; saved Chinese subtitle originals or light-reviewed local full transcripts; all time locations are candidates",
              "summary": summary, "entries": items}
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["index", "bvid", "title", "timeline_type", "start_ms", "end_ms", "status", "text", "source_path", "record_path"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(csv_rows)
    return {"summary": summary, "json": str(REPORT_JSON.relative_to(ROOT)),
            "csv": str(REPORT_CSV.relative_to(ROOT))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="index only the first N collection entries")
    args = parser.parse_args()
    print(json.dumps(prepare(args.limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
