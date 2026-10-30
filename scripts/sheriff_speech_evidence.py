"""Extract first-day sheriff signup evidence from procedural transcript cues.

This is deliberately a small, evidence-preserving parser. It does not infer a
signup from player speech content or from how often a seat is mentioned.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


_NUMBER = r"(?:12|11|10|[1-9]|十二|十一|十|九|八|七|六|五|四|三|二|一)"
_DIGITS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}

_REGISTRATION_RE = re.compile(
    r"(?:想要|想|愿意|要)?(?:上警|竞选警长)(?:的)?(?:玩家)?请亮红灯"
)
_ORDER_RE = re.compile(
    rf"(?:随机点数[一二三四五六七八九十百0-9]+)?(?:由|从)(?:第)?(?P<seat>{_NUMBER})号"
    r"(?:玩家)?(?:开始|起)(?:正式)?(?:(?P<direction>顺|逆)序)?(?:竞选)?发言"
)
_CALL_RE = re.compile(
    rf"(?:第)?(?P<seat>{_NUMBER})号(?:玩家)?(?:的)?请"
    r"(?:发表(?:竞选)?发言|发言)(?!准备)"
)
_EXCLUSION_CUE_RE = re.compile(
    r"除(?P<seats>.*?)(?:外|以外)(?:其他|其余)(?:玩家)?上警"
)
_CLOSURE_PATTERNS = (
    ("police_speeches_finished", re.compile(r"(?:警上|竞选)所有(?:玩家)?发言结束")),
    ("withdrawal_or_self_destruct_phase", re.compile(r"退水(?:自爆)?环节")),
    ("off_police_vote", re.compile(r"^(?:现在|接下来|请)?(?:进入|开始)?警下(?:玩家)?(?:进行)?投票环节$")),
)
_PK_RE = re.compile(r"(?:开始|进入|进行|开启)(?:警上)?pk(?:发言|投票|环节)|pk(?:发言|投票)环节")
_SELF_DESTRUCT_RE = re.compile(
    rf"^(?:白天)?(?:(?:第)?[一二三四五六七八九十0-9]+天)?"
    rf"(?:(?:{_NUMBER})号(?:玩家|狼人)?(?:身份)?(?:选择|宣布)?自爆"
    rf"|自(?:爆|曝)(?:{_NUMBER})号(?:玩家|狼人)?自(?:爆|曝))"
)


def _seat_number(raw: str) -> int | None:
    if raw in _DIGITS:
        return _DIGITS[raw]
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def _number_value(match: re.Match[str]) -> int | None:
    return _seat_number(match.group("seat"))


def _segment_records(segments: Any) -> list[dict[str, Any]]:
    if isinstance(segments, dict):
        segments = segments.get("segments")
    if not isinstance(segments, list):
        raise ValueError("segments must be a list or a transcript object with a segments list")

    records: list[dict[str, Any]] = []
    for position, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ValueError(f"segment {position} is not an object")
        records.append(
            {
                "position": position,
                "index": segment.get("index", position),
                "start_ms": segment.get("start_ms"),
                "end_ms": segment.get("end_ms"),
                "text": str(segment.get("text", "")),
            }
        )
    return records


def _windows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join only tightly adjacent ASR fragments so a split call can match."""
    groups: list[list[dict[str, Any]]] = []
    for record in records:
        if not groups:
            groups.append([record])
            continue
        previous = groups[-1][-1]
        start = record["start_ms"]
        previous_end = previous["end_ms"]
        duration_ok = False
        gap_ok = False
        if start is not None and previous_end is not None:
            try:
                gap_ok = float(start) - float(previous_end) <= 650
                first_start = groups[-1][0]["start_ms"]
                duration_ok = (
                    first_start is not None
                    and float(record["end_ms"]) - float(first_start) <= 4500
                )
            except (TypeError, ValueError):
                pass
        if gap_ok and duration_ok:
            groups[-1].append(record)
        else:
            groups.append([record])

    windows: list[dict[str, Any]] = []
    for group in groups:
        normalized = "".join(_normalize(record["text"]) for record in group)
        windows.append(
            {
                "records": group,
                "text": normalized,
                "first_position": group[0]["position"],
                "last_position": group[-1]["position"],
            }
        )
    return windows


def _refs(window: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "index": record["index"],
            "start_ms": record["start_ms"],
            "end_ms": record["end_ms"],
            "quote": record["text"],
        }
        for record in window["records"]
    ]


def _event(kind: str, match: re.Match[str], window: dict[str, Any], **extra: Any) -> dict[str, Any]:
    refs = _refs(window)
    starts = [ref["start_ms"] for ref in refs if ref["start_ms"] is not None]
    ends = [ref["end_ms"] for ref in refs if ref["end_ms"] is not None]
    return {
        "kind": kind,
        "position": window["first_position"],
        "match_position": match.start(),
        "start_ms": min(starts) if starts else None,
        "end_ms": max(ends) if ends else None,
        "quote": "\n".join(ref["quote"] for ref in refs),
        "segment_refs": refs,
        **extra,
    }


def _events(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for window in windows:
        for match in _REGISTRATION_RE.finditer(window["text"]):
            if re.search(r"复盘|赛后|回放", window["text"]):
                continue
            events.append(_event("registration", match, window))
        for match in _ORDER_RE.finditer(window["text"]):
            direction = match.group("direction")
            events.append(
                _event(
                    "order_start",
                    match,
                    window,
                    anchor_seat=_number_value(match),
                    direction=("forward" if direction == "顺" else "reverse" if direction == "逆" else None),
                )
            )
        for match in _EXCLUSION_CUE_RE.finditer(window["text"]):
            excluded = [
                _seat_number(raw)
                for raw in re.findall(rf"(?:第)?({_NUMBER})号?", match.group("seats"))
            ]
            events.append(
                _event(
                    "seat_exclusion",
                    match,
                    window,
                    seats=[seat for seat in excluded if seat is not None],
                )
            )
        for match in _CALL_RE.finditer(window["text"]):
            events.append(_event("speaker_call", match, window, seat=_number_value(match)))
        for closure_kind, pattern in _CLOSURE_PATTERNS:
            for match in pattern.finditer(window["text"]):
                events.append(_event("closure", match, window, closure_kind=closure_kind))
        for match in _PK_RE.finditer(window["text"]):
            events.append(_event("pk_interrupt", match, window))
        # Self-destruction may be a separate subtitle fragment inside a joined
        # ASR window, so match it against each original segment boundary.
        for record in window["records"]:
            segment_window = {
                "records": [record],
                "first_position": record["position"],
                "last_position": record["position"],
            }
            for match in _SELF_DESTRUCT_RE.finditer(_normalize(record["text"])):
                events.append(_event("self_destruct_interrupt", match, segment_window))

    # Direct exclusion lists can be split across adjacent ASR segments even
    # when the spoken clause is short. Join just neighboring window edges for
    # this procedural cue; do not broaden speech-call matching across turns.
    records = [record for window in windows for record in window["records"]]
    window_by_position = {
        record["position"]: window
        for window in windows
        for record in window["records"]
    }
    for previous, current in zip(records, records[1:]):
        if window_by_position[previous["position"]] is window_by_position[current["position"]]:
            continue
        try:
            gap = float(current["start_ms"]) - float(previous["end_ms"])
            duration = float(current["end_ms"]) - float(previous["start_ms"])
        except (TypeError, ValueError):
            continue
        if gap > 650 or duration > 8000:
            continue
        pair_window = {
            "records": [previous, current],
            "text": _normalize(previous["text"]) + _normalize(current["text"]),
            "first_position": previous["position"],
            "last_position": current["position"],
        }
        for match in _EXCLUSION_CUE_RE.finditer(pair_window["text"]):
            excluded = [
                _seat_number(raw)
                for raw in re.findall(rf"(?:第)?({_NUMBER})号?", match.group("seats"))
            ]
            events.append(
                _event(
                    "seat_exclusion",
                    match,
                    pair_window,
                    seats=[seat for seat in excluded if seat is not None],
                )
            )

    unique_events: dict[tuple[Any, ...], dict[str, Any]] = {}
    for event in events:
        key = (
            event["kind"],
            tuple(ref.get("index") for ref in event["segment_refs"]),
            event["match_position"],
            event.get("seat"),
            tuple(event.get("seats", [])),
        )
        unique_events[key] = event
    return sorted(unique_events.values(), key=lambda item: (item["position"], item["match_position"]))


def _merge_refs(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: dict[tuple[Any, Any, Any, Any], dict[str, Any]] = {}
    for event in events:
        for ref in event.get("segment_refs", []):
            key = (ref.get("index"), ref.get("start_ms"), ref.get("end_ms"), ref.get("quote"))
            refs[key] = ref
    return sorted(
        refs.values(),
        key=lambda ref: (
            ref["start_ms"] is None,
            ref["start_ms"] if ref["start_ms"] is not None else 0,
            str(ref["index"]),
        ),
    )


def _timeline_gaps(records: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    interval = records[start : end + 1]
    for record in interval:
        if record["start_ms"] is None or record["end_ms"] is None:
            gaps.append(
                {
                    "code": "missing_timestamp",
                    "message": "all segments in a complete signup window need start_ms and end_ms",
                    "segment_refs": [
                        {"index": record["index"], "start_ms": record["start_ms"], "end_ms": record["end_ms"], "quote": record["text"]}
                    ],
                }
            )
        else:
            try:
                if float(record["end_ms"]) < float(record["start_ms"]):
                    raise ValueError
            except (TypeError, ValueError):
                gaps.append(
                    {
                        "code": "invalid_timestamp",
                        "message": "segment timestamps are not numeric or have a negative duration",
                        "segment_refs": [
                            {"index": record["index"], "start_ms": record["start_ms"], "end_ms": record["end_ms"], "quote": record["text"]}
                        ],
                    }
                )
    for previous, current in zip(interval, interval[1:]):
        try:
            previous_index = int(previous["index"])
            current_index = int(current["index"])
        except (TypeError, ValueError):
            previous_index = current_index = None
        if previous_index is not None and current_index != previous_index + 1:
            gaps.append(
                {
                    "code": "transcript_segment_gap",
                    "message": "segment indices are not contiguous across the signup window",
                    "segment_refs": [
                        {"index": previous["index"], "start_ms": previous["start_ms"], "end_ms": previous["end_ms"], "quote": previous["text"]},
                        {"index": current["index"], "start_ms": current["start_ms"], "end_ms": current["end_ms"], "quote": current["text"]},
                    ],
                }
            )
        if previous["start_ms"] is None or previous["end_ms"] is None or current["start_ms"] is None or current["end_ms"] is None:
            continue
        try:
            delta = float(current["start_ms"]) - float(previous["end_ms"])
        except (TypeError, ValueError):
            delta = 0
            gaps.append(
                {
                    "code": "invalid_timestamp",
                    "message": "segment timestamps are not numeric",
                    "segment_refs": [
                        {"index": current["index"], "start_ms": current["start_ms"], "end_ms": current["end_ms"], "quote": current["text"]}
                    ],
                }
            )
        if delta > 30000:
            gaps.append(
                {
                    "code": "possible_clip_gap",
                    "message": "a timestamp gap over 30 seconds prevents a complete-roster claim",
                    "segment_refs": [
                        {"index": previous["index"], "start_ms": previous["start_ms"], "end_ms": previous["end_ms"], "quote": previous["text"]},
                        {"index": current["index"], "start_ms": current["start_ms"], "end_ms": current["end_ms"], "quote": current["text"]},
                    ],
                }
            )
    return gaps


def _seat_chain_valid(seats: list[int], anchor: int, direction: str | None, seat_count: int) -> bool:
    if not seats or anchor < 1 or anchor > seat_count or len(set(seats)) != len(seats):
        return False

    def increasing(which: str) -> bool:
        ranks = [
            (seat - anchor) % seat_count
            if which == "forward"
            else (anchor - seat) % seat_count
            for seat in seats
        ]
        return all(left < right for left, right in zip(ranks, ranks[1:]))

    if direction is not None:
        return increasing(direction)
    return increasing("forward") or increasing("reverse")


def analyze_sheriff_speeches(segments: Any, *, seat_count: int = 12) -> dict[str, Any]:
    """Extract first-day sheriff signup calls and their completeness evidence.

    A seat gets supporting evidence only from a judge-style call in a signup
    round. A procedural start/closure does not prove ASR captured every call.
    Speech chains remain supporting evidence and never establish off-police seats.
    """
    if not isinstance(seat_count, int) or seat_count < 1:
        raise ValueError("seat_count must be a positive integer")
    records = _segment_records(segments)
    events = _events(_windows(records))
    registrations = [event for event in events if event["kind"] == "registration"]
    if not registrations:
        return {
            "rounds": [],
            "evidence": [],
            "gaps": [
                {
                    "code": "initial_registration_not_found",
                    "message": "no explicit initial sheriff signup prompt was found",
                    "segment_refs": [],
                }
            ],
        }

    registration = registrations[0]
    after_registration = [event for event in events if (event["position"], event["match_position"]) > (registration["position"], registration["match_position"])]
    order_events = [event for event in after_registration if event["kind"] == "order_start"]
    first_order = order_events[0] if order_events else None
    round_gaps: list[dict[str, Any]] = []

    if first_order is None:
        round_events = [registration]
        close = next((event for event in after_registration if event["kind"] == "closure"), None)
        round_gaps.append(
            {
                "code": "speech_order_not_found",
                "message": "the registration prompt was not followed by an explicit start-order command",
                "segment_refs": [],
            }
        )
    else:
        after_order = [event for event in events if (event["position"], event["match_position"]) > (first_order["position"], first_order["match_position"])]
        round_events = [registration, first_order]
        round_events.extend(
            event
            for event in events
            if event["kind"] == "seat_exclusion"
            and (
                registration["position"] <= event["position"] <= first_order["position"]
                or (
                    event.get("start_ms") is not None
                    and registration.get("start_ms") is not None
                    and 0 <= float(registration["start_ms"]) - float(event["start_ms"]) <= 5000
                )
            )
        )
        close = None
        for event in after_order:
            if event["kind"] in ("pk_interrupt", "self_destruct_interrupt"):
                round_events.append(event)
                round_gaps.append(
                    {
                        "code": "signup_interrupted",
                        "message": "a PK round or self-destruction interrupted the first signup speech chain",
                        "segment_refs": event["segment_refs"],
                    }
                )
                break
            if event["kind"] == "closure":
                close = event
                round_events.append(event)
                break
            if event["kind"] == "speaker_call":
                round_events.append(event)
            elif event["kind"] == "order_start":
                round_events.append(event)
            elif event["kind"] == "seat_exclusion":
                round_events.append(event)

    calls = [event for event in round_events if event["kind"] == "speaker_call"]
    interruptions = [event for event in round_events if event["kind"] in ("pk_interrupt", "self_destruct_interrupt")]
    if close is None:
        round_gaps.append(
            {
                "code": "signup_closure_not_found",
                "message": "the first signup speech chain has no explicit closure cue",
                "segment_refs": [],
            }
        )
    if not calls:
        round_gaps.append(
            {
                "code": "speaker_calls_not_found",
                "message": "no explicit numbered sheriff-speech call followed the start-order cue",
                "segment_refs": [],
            }
        )
    if first_order is None:
        speakers: list[int] = []
        chain_valid = False
    else:
        speakers = []
        for call in calls:
            seat = call.get("seat")
            if seat is None or seat < 1 or seat > seat_count:
                round_gaps.append(
                    {
                        "code": "speaker_seat_out_of_range",
                        "message": f"called seat must be in 1..{seat_count}",
                        "segment_refs": call["segment_refs"],
                    }
                )
                continue
            speakers.append(seat)
        unique_speakers = list(dict.fromkeys(speakers))
        if len(unique_speakers) != len(speakers):
            duplicates = sorted({seat for seat in speakers if speakers.count(seat) > 1})
            round_gaps.append(
                {
                    "code": "duplicate_speaker_call",
                    "message": "a seat was explicitly called more than once before signup closure",
                    "seats": duplicates,
                    "segment_refs": _merge_refs([call for call in calls if call.get("seat") in duplicates]),
                }
            )
        anchor = first_order.get("anchor_seat")
        if anchor is None or anchor < 1 or anchor > seat_count:
            chain_valid = False
            round_gaps.append(
                {
                    "code": "order_anchor_out_of_range",
                    "message": f"the announced first seat must be in 1..{seat_count}",
                    "segment_refs": first_order["segment_refs"],
                }
            )
        else:
            chain_valid = _seat_chain_valid(speakers, anchor, first_order.get("direction"), seat_count)
            if speakers and not chain_valid:
                round_gaps.append(
                    {
                        "code": "seat_chain_conflict",
                        "message": "the called seats do not form a unique chain in the announced direction",
                        "seats": speakers,
                        "segment_refs": _merge_refs(calls),
                    }
                )
        speakers = unique_speakers

        excluded_events = [event for event in round_events if event["kind"] == "seat_exclusion"]
        excluded_seats = sorted({seat for event in excluded_events for seat in event["seats"]})
        conflicting_seats = sorted(set(speakers) & set(excluded_seats))
        if conflicting_seats:
            round_gaps.append(
                {
                    "code": "speaker_number_conflict",
                    "message": "a called seat conflicts with an explicit signup exclusion in the same procedure",
                    "seats": conflicting_seats,
                    "segment_refs": _merge_refs([*excluded_events, *calls]),
                }
            )

        later_orders = [event for event in round_events if event["kind"] == "order_start" and event is not first_order]
        if any(
            (event.get("anchor_seat"), event.get("direction"))
            != (first_order.get("anchor_seat"), first_order.get("direction"))
            for event in later_orders
        ):
            round_gaps.append(
                {
                    "code": "conflicting_order_commands",
                    "message": "the signup window contains conflicting start-order commands",
                    "segment_refs": _merge_refs([first_order, *later_orders]),
                }
            )

    if close is not None:
        timeline_end = close["position"]
    elif interruptions:
        timeline_end = interruptions[0]["position"]
    elif round_events:
        timeline_end = max(event["position"] for event in round_events)
    else:
        timeline_end = registration["position"]
    timeline_start = registration["position"]
    timeline_gaps = _timeline_gaps(records, timeline_start, timeline_end)
    round_gaps.extend(timeline_gaps)

    complete = (
        first_order is not None
        and close is not None
        and not interruptions
        and bool(speakers)
        and chain_valid
        and not round_gaps
    )
    end_event = close or (interruptions[0] if interruptions else None)
    round_result = {
        "round_id": "sheriff_signup_day1",
        "day": 1,
        "kind": "initial_sheriff_signup",
        "registration": registration,
        "order_start": first_order,
        "closure": close,
        "interrupted_by": interruptions[0] if interruptions else None,
        "start_ms": registration["start_ms"],
        "end_ms": end_event["end_ms"] if end_event else None,
        "on_police": speakers,
        "off_police": None,
        "speakers": speakers,
        "count": len(speakers),
        "complete": False,
        "procedural_complete": complete,
    }

    evidence: list[dict[str, Any]] = []
    for seat in speakers:
        for call in [event for event in calls if event.get("seat") == seat]:
            evidence.append(
                {
                    "round_id": round_result["round_id"],
                    "claim": "on_police",
                    "seat": seat,
                    "strength": "supporting",
                    "quote": call["quote"],
                    "segment_refs": call["segment_refs"],
                }
            )

    return {
        "rounds": [round_result],
        "evidence": evidence,
        "gaps": [dict(gap, round_id=round_result["round_id"]) for gap in round_gaps],
    }


def load_bound_sheriff_speeches(
    supplemental: dict[str, Any] | None, *, root: str | Path, voting: dict | None = None
) -> dict[str, Any] | None:
    """Use known signup, then a judge list, then the fallback speech chain."""
    if any(r.get("day") == 1 for r in (voting or {}).get("registrations", [])):
        return None
    binding = supplemental.get("source_binding") if isinstance(supplemental, dict) else None
    if binding is None:
        return None
    if not isinstance(binding, dict):
        raise ValueError("source_binding must be an object")
    relative_path = binding.get("selected_transcript_path")
    expected_sha256 = binding.get("selected_transcript_sha256")
    if relative_path is None and expected_sha256 is None:
        return None
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("source_binding.selected_transcript_path is missing")
    if not isinstance(expected_sha256, str) or not expected_sha256.strip():
        raise ValueError("source_binding.selected_transcript_sha256 is missing")

    path = Path(relative_path)
    if not path.is_absolute():
        path = Path(root) / path
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"bound selected transcript cannot be read: {relative_path}") from exc
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256.lower() != expected_sha256.lower():
        raise ValueError(f"bound selected transcript SHA256 changed: {relative_path}")
    try:
        transcript = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"bound selected transcript is not valid UTF-8 JSON: {relative_path}") from exc
    if not isinstance(transcript, dict) or not isinstance(transcript.get("segments"), list):
        raise ValueError(f"bound selected transcript has no segments list: {relative_path}")

    try:
        from .voting_records import find_registration_candidates
    except ImportError:
        from voting_records import find_registration_candidates
    segments = transcript["segments"]
    candidates = find_registration_candidates(segments)
    if candidates:
        # Judge corrections within the initial announcement minute supersede
        # the preceding list. Never mix in the later deferred election.
        initial = [candidates[0]]
        for row in candidates[1:]:
            if segments[row[0]]["start_ms"] - segments[initial[-1][0]]["start_ms"] >= 60_000:
                break
            initial.append(row)
        i, off, on, count = initial[-1]
        refs = [{"index": s.get("index", n), "start_ms": s["start_ms"], "end_ms": s["end_ms"], "quote": s["text"]}
                for n, s in enumerate(segments[initial[0][0]:i + count], initial[0][0])]
        result = {"method": "judge_signup_list", "registration": {"day": 1, "on_police": on, "off_police": off},
                  "rounds": [], "evidence": [{"claim": "initial_registration", "strength": "direct",
                                               "segment_refs": refs}], "gaps": []}
    else:
        result = analyze_sheriff_speeches(segments)
        result["method"] = "initial_speech_round_fallback"
    result["source_binding"] = {"path": relative_path, "sha256": actual_sha256}
    return result
