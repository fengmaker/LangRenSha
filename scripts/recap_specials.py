"""Conservative extraction of explicit special-board recap actions.

This module only consumes the already bounded referee recap passed by the
caller. It never creates rounds, infers deaths from action targets, or infers
missing roles. Ambiguous and hypothetical wording is left for human review.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

if __package__:
    from .recap_parser import _NUM, _number, _stage_spans, _compact
else:
    from recap_parser import _NUM, _number, _stage_spans, _compact


ROOT = Path(__file__).resolve().parents[1]

_BOARD_CODES = {
    "预女猎白混": "mixed_blood",
    "假面舞会": "masquerade",
    "诡术之境": "guile_realm",
    "盗宝大师": "treasure_master",
    "盗宝大师赛": "treasure_master",
}

_HYPOTHESIS = re.compile(r"如果|假如|倘若|可能|应该|我觉得|我猜|猜测|猜想")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；;])")
_SEAT_RE = re.compile(rf"(?P<n>{_NUM})号(?:玩家)?")
_DANCE_BREAK = re.compile(
    r"假面.{0,8}(?:验证|给|赐予|发给|扣面具)|"
    r"(?:狼人|狼队).{0,8}(?:击杀|击毙)|女巫.{0,8}(?:救|毒|解药)|"
    r"预言家.{0,8}(?:查验|验证)|(?:不在|在)舞池|"
    r"击杀|毒杀|查验|验证|扣面具|自爆"
)
_DANCE_ACTION_AFTER_SEAT = re.compile(
    r"^(?:(?:狼人|狼队).{0,4}(?:击杀|击毙)|(?:女巫|毒师).{0,4}(?:救|毒)|"
    r"(?:预言家|通灵师).{0,4}(?:验证|查验)|被狼刀|被击杀|"
    r"开枪|投票|自爆|出局|放逐|毒杀)"
)
_TREASURE_BREAK = re.compile(
    r"本夜|当夜|随后|然后|接下来|盗宝(?:大师)?(?:选择|选|拿)|"
    r"选择|选了|拿了|狼队.{0,2}击杀|狼人.{0,2}击杀|"
    r"女巫.{0,3}(?:救|毒)|预言家.{0,3}(?:验证|查验|验)|"
    r"魔术师.{0,3}交换|(?:诡术师|鬼术师).{0,3}交换"
)
_ROLE_NAMES = (
    "机械双刀狼", "机械通灵师", "鬼魂新娘", "定序王子", "盗宝大师",
    "机械狼", "黑狼王", "摄梦人", "典狱长", "混血儿", "魔术师",
    "诡术师", "通灵师", "预言家", "舞者", "假面", "白神", "白痴",
    "女巫", "猎人", "守卫", "骑士", "狼人", "狼王", "平民", "毒师", "蒙面人",
)
_ROLE_RE = re.compile("|".join(map(re.escape, sorted(_ROLE_NAMES, key=len, reverse=True))))
_ROLE_ALIASES = {"鬼术师": "诡术师"}


@lru_cache(maxsize=None)
def _template(code: str) -> dict[str, Any] | None:
    path = ROOT / "config" / "board_templates" / f"{code}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _board_code(board_name: str) -> str | None:
    compact = re.sub(r"\s+", "", board_name or "")
    return _BOARD_CODES.get(compact)


def _seat_value(raw: str | None) -> int | None:
    value = _number(raw or "")
    return value if value is not None and value <= 12 else None


def _unique_role_seat(seats: list[dict[str, Any]], role: str) -> int | None:
    found = [s.get("seat") for s in seats if s.get("role") == role]
    return found[0] if len(found) == 1 and isinstance(found[0], int) else None


def _explicit_actor(clause: str, role: str, seats: list[dict[str, Any]]) -> int | None:
    aliases = [role]
    if role == "诡术师":
        aliases.append("鬼术师")
    for alias in aliases:
        for pattern in (
            re.compile(rf"(?P<n>{_NUM})号(?:玩家)?{re.escape(alias)}"),
            re.compile(rf"{re.escape(alias)}(?:玩家)?(?P<n>{_NUM})号"),
        ):
            match = pattern.search(clause)
            if match:
                actor = _seat_value(match.group("n"))
                known_role = next((s.get("role") for s in seats if s.get("seat") == actor), None)
                return actor if known_role in (None, role) else None
    return _unique_role_seat(seats, role)


def _targets(text: str) -> list[int]:
    out: list[int] = []
    for match in _SEAT_RE.finditer(text):
        seat = _seat_value(match.group("n"))
        if seat is not None and seat not in out:
            out.append(seat)
    return out


def _slot_phase(code: str, slot: str) -> tuple[str, set[str]] | None:
    template = _template(code)
    if not template:
        return None
    for phase, key in (("night", "night_slots"), ("day", "day_slots")):
        for spec in template.get(key, []):
            if spec.get("code") == slot:
                return phase, set(spec.get("actions", []))
    return None


def _event(
    code: str,
    number: int,
    phase: str,
    slot: str,
    action: str,
    actor: int | None,
    targets: list[int] | None = None,
    result: str | None = None,
) -> dict[str, Any] | None:
    spec = _slot_phase(code, slot)
    if not spec or spec[0] != phase or action not in spec[1]:
        return None
    return {
        "number": number,
        "phase": phase,
        "slot": slot,
        "action": action,
        "actor": actor,
        "targets": targets or [],
        "result": result,
    }


def _dance_targets(text: str) -> list[int]:
    """Read a contiguous explicit three-seat dance list, stopping at actions."""
    targets: list[int] = []
    cursor = 0
    for match in _SEAT_RE.finditer(text):
        if _DANCE_BREAK.search(text[cursor:match.start()]):
            break
        seat = _seat_value(match.group("n"))
        if _DANCE_ACTION_AFTER_SEAT.search(text[match.end():match.end() + 16]):
            break
        cursor = match.end()
        if seat is not None and seat not in targets:
            targets.append(seat)
            if len(targets) == 3:
                break
    return targets


def _remainder_roles(text: str) -> list[str]:
    """Read the first explicit three-role remainder list before another action."""
    found: list[str] = []
    cursor = 0
    for match in _ROLE_RE.finditer(text):
        if _TREASURE_BREAK.search(text[cursor:match.start()]):
            break
        found.append(_ROLE_ALIASES.get(match.group(0), match.group(0)))
        cursor = match.end()
        if len(found) == 3:
            break
    return found


def _mixed_model(clause: str, seats: list[dict[str, Any]]) -> tuple[int | None, int] | None:
    selected = re.search(
        rf"(?:(?P<a>{_NUM})号)?混血儿(?:{_NUM}号)?(?:选择了?|选了)(?P<t>{_NUM})号"
        rf"[^。！？；;]{{0,8}}(?:为|作)榜样",
        clause,
    )
    explicit = re.search(
        rf"(?:(?:混血儿(?:是|为)?)(?P<a>{_NUM})号[^。！？；;]{{0,8}}榜样|"
        rf"(?P<a2>{_NUM})号混血儿[^。！？；;]{{0,8}}榜样|"
        rf"(?P<a3>{_NUM})号[^。！？；;]{{0,6}}榜样)"
        rf"[^。！？；;]{{0,8}}?(?:是|为|选择|选了)?[^。！？；;]{{0,3}}(?P<t>{_NUM})号",
        clause,
    )
    short = re.search(rf"(?P<a>{_NUM})号榜样(?:是|为|选择)?(?P<t>{_NUM})号", clause)
    match = explicit or short or selected
    if not match:
        return None
    raw_actor = (
        match.groupdict().get("a") or match.groupdict().get("a2")
        or match.groupdict().get("a3")
    )
    actor = _seat_value(raw_actor) if raw_actor else _unique_role_seat(seats, "混血儿")
    if raw_actor:
        known_role = next((s.get("role") for s in seats if s.get("seat") == actor), None)
        if known_role not in (None, "混血儿"):
            actor = None
    target = _seat_value(match.group("t"))
    return (actor, target) if target is not None else None


def extract_specials(
    segments: list[dict[str, Any]], board_name: str, base_result: dict[str, Any]
) -> dict[str, Any]:
    """Return explicit special-board events restricted to parsed rounds.

    Sentence punctuation is retained by ``_compact`` and each stage span is
    split at sentence boundaries before matching. A hypothesis marker anywhere
    in that sentence blocks extraction from it.
    """
    code = _board_code(board_name)
    if code is None:
        return {"events": [], "issues": []}

    issues: list[str] = []
    events: list[dict[str, Any]] = []
    seats = [s for s in (base_result or {}).get("seats", []) if isinstance(s, dict)]
    rounds = (base_result or {}).get("rounds", [])
    existing: dict[int, dict[str, Any]] = {
        r["number"]: r for r in rounds
        if isinstance(r, dict) and isinstance(r.get("number"), int)
    }
    text = _compact(segments or [])
    candidates: list[tuple[int, str, str]] = []

    def add_candidate(number: int, phase: str, slot: str, action: str,
                      actor: int | None, targets: list[int] | None = None,
                      result: str | None = None) -> None:
        value = _event(code, number, phase, slot, action, actor, targets, result)
        if value is None:
            issues.append(f"版型模板没有匹配的特殊事件槽或动作：{slot}/{action}")
            return
        if number not in existing:
            issues.append(f"识别到 {slot}，但复盘解析结果中没有第{number}轮；未新增事件")
            return
        candidates.append((number, phase, value))

    # Stage recognition is delegated to the common recap parser. Matching is
    # still done sentence-by-sentence so a role/action cannot borrow a target
    # or a hypothesis from an adjacent sentence.
    spans = _stage_spans(text)
    if code == "mixed_blood":
        # The model choice is often stated as referee metadata before the
        # first explicit “首夜”/“入夜” cue. Its fixed template slot is a
        # first-night action, so this prelude may only map to an already
        # present round 1; no other round is inferred.
        prelude_end = spans[0][0] if spans else len(text)
        for clause in (piece for piece in _SENTENCE_SPLIT.split(text[:prelude_end]) if piece):
            if _HYPOTHESIS.search(clause):
                if "榜样" in clause:
                    issues.append("混血儿榜样句包含假设或推测措辞，未提取")
                continue
            model = _mixed_model(clause, seats)
            if model:
                actor, target = model
                add_candidate(1, "night", "mixed_blood_model", "choose", actor, [target])

    for _offset, phase, number, content in spans:
        if phase not in {"night", "day"}:
            continue
        clauses = [piece for piece in _SENTENCE_SPLIT.split(content) if piece]
        for clause in clauses:
            if _HYPOTHESIS.search(clause):
                if any(token in clause for token in ("榜样", "共舞", "验证", "面具", "交换", "翻牌", "余牌", "盗宝")):
                    issues.append("特殊动作所在句包含假设或推测措辞，未提取")
                continue

            if code == "mixed_blood" and phase == "night" and number == 1:
                model = _mixed_model(clause, seats)
                if model:
                    actor, target = model
                    add_candidate(number, phase, "mixed_blood_model", "choose", actor, [target])

            elif code == "masquerade" and phase == "night":
                actor = _explicit_actor(clause, "假面", seats)
                verify = re.search(
                    rf"假面(?:{_NUM}号)?[^。！？；;]{{0,6}}验证(?:了|一下)?(?P<t>(?:{_NUM}号(?:玩家)?[、，,和及与]?)+)",
                    clause,
                )
                if verify and not re.search(r"(?:没有|未|并未)验证", clause):
                    targets = _targets(verify.group("t"))
                    result = "不在舞池" if "不在舞池" in clause else ("在舞池" if "在舞池" in clause else None)
                    if targets:
                        add_candidate(number, phase, "masquerade_verify", "verify", actor, targets, result)

                mask = re.search(
                    rf"假面(?:{_NUM}号)?[^。！？；;]{{0,8}}(?:给|赐予|发给|扣给)(?:面具)?(?P<t>{_NUM}号(?:玩家)?)"
                    rf"|假面(?:{_NUM}号)?[^。！？；;]{{0,8}}(?:给|赐予|发给)(?P<t2>{_NUM}号(?:玩家)?)[^。！？；;]{{0,6}}(?:扣面具|面具)"
                    rf"|假面(?:{_NUM}号)?[^。！？；;]{{0,8}}扣面具(?:给|于)(?P<t3>{_NUM}号(?:玩家)?)"
                    rf"|假面(?:{_NUM}号)?[^。！？；;]{{0,32}}?(?:给|赐予|发给)(?P<t4>{_NUM}号(?:玩家)?)[^。！？；;]{{0,8}}扣(?:了)?面具"
                    rf"|假面(?:{_NUM}号)?[^。！？；;]{{0,10}}扣(?:了)?(?P<t5>{_NUM}号)(?:的)?面具",
                    clause,
                )
                if mask:
                    raw = (
                        mask.groupdict().get("t") or mask.groupdict().get("t2")
                        or mask.groupdict().get("t3") or mask.groupdict().get("t4")
                        or mask.groupdict().get("t5")
                    )
                    target = _targets(raw or "")
                    if target and not re.search(r"(?:没有|未|并未)(?:给|赐予|发给|扣)", clause):
                        add_candidate(number, phase, "masquerade_mask", "give_mask", actor, target)

                dance = re.search(
                    rf"舞者(?:{_NUM}号)?(?:选择了?|选了|邀请|带|与|和)(?P<body>[^。！？；;]{{1,60}}?)(?:共舞|跳舞)"
                    r"|舞者共舞(?:的)?对象(?:为|是)(?P<body2>[^。！？；;]{1,60})",
                    clause,
                )
                if dance:
                    body = dance.group("body") or dance.group("body2") or ""
                    targets = _dance_targets(body)
                    if len(targets) == 3:
                        add_candidate(number, phase, "dancer_dance", "dance",
                                      _explicit_actor(clause, "舞者", seats), targets)
                    else:
                        issues.append("舞者共舞名单未明确给出三个不同座位，未提取")

            elif code == "guile_realm" and phase == "night":
                for role, aliases, slot in (
                    ("魔术师", ("魔术师",), "magician_exchange"),
                    ("诡术师", ("诡术师", "鬼术师"), "guile_exchange"),
                ):
                    matched: re.Match[str] | None = None
                    for alias in aliases:
                        matched = re.search(
                            rf"{re.escape(alias)}(?:{_NUM}号)?[^。！？；;]{{0,6}}交换(?:了|选择)?"
                            rf"(?P<body>[^。！？；;]{{0,50}})", clause
                        )
                        if matched:
                            break
                    if not matched:
                        continue
                    body = matched.group("body")
                    next_action = re.search(r"(?:魔术师|诡术师|鬼术师)[^。！？；;]{0,6}交换", body)
                    if next_action:
                        body = body[:next_action.start()]
                    # The special exchange always names a pair. Later actions
                    # in a punctuation-free ASR span may add more seat numbers.
                    targets = _targets(body)[:2]
                    if len(targets) == 2:
                        add_candidate(number, phase, slot, "exchange",
                                      _explicit_actor(clause, role, seats), targets)
                    else:
                        issues.append(f"{role}交换句没有明确给出恰好两个座位，未提取")

            elif code == "guile_realm" and phase == "day":
                prince = re.search(
                    r"定序王子(?:\d{1,2}号)?[^。！？；;]{0,18}翻牌[^。！？；;]{0,12}"
                    r"(?:发动|启用|使用|后)[^。！？；;]{0,18}(?:重新投票|再次投票|重投)",
                    clause,
                )
                if prince:
                    actor = _explicit_actor(clause, "定序王子", seats)
                    add_candidate(number, phase, "sequential_prince_skill", "reveal", actor)
                    issues.append("已明确提及定序王子发动后重投，但未给出逐人票型；待人工核对")

            elif code == "treasure_master" and phase == "night":
                actor = _explicit_actor(clause, "盗宝大师", seats)
                remainder = re.search(r"余牌(?:分别)?(?:是|为|有|分别为)(?P<body>[^。！？；;]{1,80})", clause)
                if remainder:
                    roles = _remainder_roles(remainder.group("body"))
                    if len(roles) == 3:
                        add_candidate(number, phase, "treasure_remainder", "view", actor,
                                      result="余牌：" + "、".join(roles))
                    else:
                        issues.append("盗宝余牌句未能明确提取三张角色牌，未提取")

                choice = re.search(
                    rf"(?:盗宝大师(?:{_NUM}号)?|本夜盗宝)(?:(?:选择了?|选了|选取|拿取|拿了)(?:切换为|转为)?|切换为|转为)"
                    rf"(?P<role>{_ROLE_RE.pattern})(?:牌|身份牌|技能)?",
                    clause,
                )
                if choice:
                    chosen = _ROLE_ALIASES.get(choice.group("role"), choice.group("role"))
                    add_candidate(number, phase, "treasure_choice", "choose", actor, result=chosen)

    for number, phase, value in candidates:
        # Preserve repeated explicit mentions; callers may need to review them
        # as separate events rather than losing one through slot-based merging.
        events.append(value)

    return {"events": events, "issues": list(dict.fromkeys(issues))}
