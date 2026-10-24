"""Conservative, deterministic parsing of an already located referee recap.

This parser deliberately extracts only statements that have a clear textual
shape. It never fills remaining seats from a board template and never treats a
night action target as a confirmed death. The input should already be bounded
to the referee recap; commentary and player claims in a full broadcast are not
safe input for this module.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


_NUM = r"(?:12|1[0-2]|[1-9]|十二|十一|十|[一二两三四五六七八九])"
_SEAT = re.compile(rf"(?P<number>{_NUM})号(?:玩家)?")
_DIGITS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12,
}

# Long names appear first so that e.g. 机械狼 is never read as 狼人.
_ROLE_ALIASES = {
    "机械双刀狼": "机械双刀狼",
    "机械通灵师": "机械通灵师",
    "机械女巫": "机械女巫",
    "机械猎人": "机械猎人",
    "机械守卫": "机械守卫",
    "机械平民": "机械平民",
    "鬼魂新娘": "鬼魂新娘",
    "定序王子": "定序王子",
    "盗宝大师": "盗宝大师",
    "蒙面人": "蒙面人",
    "毒师": "毒师",
    "机械狼": "机械狼",
    "黑狼王": "黑狼王",
    "摄梦人": "摄梦人",
    "射梦人": "摄梦人",
    "圣梦人": "摄梦人",
    "典狱长": "典狱长",
    "混血儿": "混血儿",
    "魔术师": "魔术师",
    "鬼术师": "诡术师",
    "鬼书师": "诡术师",
    "诡术师": "诡术师",
    "通灵师": "通灵师",
    "预言家": "预言家",
    "白痴": "白痴",
    "白神": "白神",
    "女巫": "女巫",
    "猎人": "猎人",
    "守卫": "守卫",
    "骑士": "骑士",
    "舞者": "舞者",
    "武者": "舞者",
    "假面牌": "假面",
    "假面": "假面",
    "狼王": "狼王",
    "狼人": "狼人",
    "平民": "平民",
}
_MECHANICAL_FORMS = ("机械双刀狼", "机械通灵师", "机械女巫", "机械猎人", "机械守卫", "机械平民")
_MECHANICAL_FORM_BY_ROLE = {
    "狼人": "机械双刀狼",
    "通灵师": "机械通灵师",
    "女巫": "机械女巫",
    "猎人": "机械猎人",
    "守卫": "机械守卫",
    "平民": "机械平民",
}
_MECHANICAL_SOURCE_ROLE = {form: role for role, form in _MECHANICAL_FORM_BY_ROLE.items()}
_ROLE_PATTERN = "|".join(sorted(map(re.escape, _ROLE_ALIASES), key=len, reverse=True))
_ROLE_RE = re.compile(_ROLE_PATTERN)
# “品名” occurs as a high-confidence ASR spelling for 平民 in one roster.
# Keep this alias local to roster parsing; it must not affect action extraction.
_ROSTER_ROLE_ALIASES = {**_ROLE_ALIASES, "品名": "平民"}
_ROSTER_ROLE_PATTERN = "|".join(sorted(map(re.escape, _ROSTER_ROLE_ALIASES), key=len, reverse=True))
_ROSTER_ROLE_SEPARATOR = r"[，,、；;：:]?"


def _number(value: str) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        result = int(value) if value.isdigit() else _DIGITS.get(value)
    except (TypeError, ValueError):
        return None
    return result if result is not None and result > 0 else None


def _mechanical_form(role: str | None) -> str | None:
    """Normalize a learned-from role or an already modeled form safely."""
    if role in _MECHANICAL_FORMS:
        return role
    return _MECHANICAL_FORM_BY_ROLE.get(role)


def _learned_mechanical_form(
    target: int | None,
    role_label: str | None,
    declared_form: str | None,
    roles: dict[int, str | None],
    issues: list[str],
) -> str | None:
    """Use explicit form language, checking it against known target identity."""
    source_role = _ROLE_ALIASES.get(role_label) if role_label else None
    form = declared_form or _mechanical_form(source_role)
    if source_role in _MECHANICAL_SOURCE_ROLE:
        source_role = _MECHANICAL_SOURCE_ROLE[source_role]
    expected_source = _MECHANICAL_SOURCE_ROLE.get(form) if form else None
    target_role = roles.get(target) if target is not None else None
    if source_role and target_role and source_role != target_role:
        issues.append(f"机械狼学习目标{target}号的播报身份与终局身份名单冲突，学习形态保留为未知")
        return None
    if expected_source and target_role and expected_source != target_role:
        issues.append(f"机械狼学习目标{target}号与已声明形态{form}不一致，学习形态保留为未知")
        return None
    if expected_source and source_role and expected_source != source_role:
        issues.append(f"机械狼学习播报身份与已声明形态{form}不一致，学习形态保留为未知")
        return None
    return form


def _compact(segments: Iterable[dict[str, Any]]) -> str:
    """Join ASR fragments while retaining punctuation as weak boundaries."""
    pieces: list[str] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            continue
        text = segment.get("text")
        if isinstance(text, str) and text:
            pieces.append(text)
    return re.sub(r"\s+", "", "".join(pieces))


_STAGE_RE = re.compile(
    rf"(?P<cue>首夜|(?:首页|守夜)(?=[^。！？；;，,]{{0,12}}(?:守护|保护|狼刀|狼人.{{0,2}}击杀|狼队.{{0,2}}击杀|机械狼.{{0,4}}(?:模仿|学习)|女巫.{{0,5}}(?:救|毒)|通灵师.{{0,5}}(?:验证|查验|验)|(?:鬼术师|鬼书师|诡术师).{{0,2}}(?:交换|更换|互换)|混血儿?.{{0,2}}(?:选择|选取)|混圈儿?.{{0,2}}(?:选择|选取)|舞者.{{0,2}}共舞))|"
    rf"第{_NUM}夜|第{_NUM}天(?:的)?(?:白天|白日)|"
    rf"第{_NUM}天(?:的)?(?:夜里|夜间|晚上)|第{_NUM}天|入夜|天亮(?:了)?|"
    rf"天黑(?:了)?请闭眼)"
)


def _stage_number(cue: str, current: int | None, previous_phase: str | None) -> tuple[int | None, str | None]:
    if cue == "首夜" or cue.startswith(("首页", "守夜")):
        return 1, "night"
    if cue.startswith("入夜") or cue.startswith("天黑"):
        if current is None:
            return 1, "night"
        return (current + 1 if previous_phase == "day" else current + 1), "night"
    if cue.startswith("天亮"):
        if current is None:
            return None, "day"
        return current if previous_phase == "night" else current + 1, "day"
    match = re.match(rf"第({_NUM})(?:天|夜)", cue)
    if not match:
        return None, None
    value = _number(match.group(1))
    phase = "night" if "夜" in cue or "夜里" in cue or "夜间" in cue or "晚上" in cue else "day"
    return value, phase


def _stage_spans(text: str) -> list[tuple[int, str, int, str]]:
    """Return (start, phase, round, content) spans, honoring explicit cues."""
    raw_cues = list(_STAGE_RE.finditer(text))
    # “首页” and “守夜” are narrow ASR aliases for the first night, accepted
    # only when immediately followed by a recognizable action and before any
    # other stage cue.
    cues = []
    for match in raw_cues:
        cue = match.group("cue")
        if cue.startswith(("首页", "守夜")) and cues:
            continue
        cues.append(match)
    spans: list[tuple[int, str, int, str]] = []
    current: int | None = None
    phase: str | None = None
    for index, match in enumerate(cues):
        cue = match.group("cue")
        number, next_phase = _stage_number(cue, current, phase)
        if number is None or next_phase is None:
            continue
        end = cues[index + 1].start() if index + 1 < len(cues) else len(text)
        spans.append((match.start(), next_phase, number, text[match.end():end]))
        current, phase = number, next_phase
    return spans


def _strong_roster_syntax(region: str) -> bool:
    """Require a dense role list and both continuous faction seat lists."""
    associations: set[tuple[int, str]] = set()
    for match in re.finditer(
        rf"(?P<role>{_ROSTER_ROLE_PATTERN})(?:身份|牌)?(?:为|是)?{_ROSTER_ROLE_SEPARATOR}(?P<number>{_NUM})号",
        region,
    ):
        number = _number(match.group("number"))
        if number is not None:
            associations.add((number, _ROSTER_ROLE_ALIASES[match.group("role")]))
    for match in re.finditer(
        rf"(?P<number>{_NUM})号{_ROSTER_ROLE_SEPARATOR}(?:身份为|是|为)?(?P<role>{_ROSTER_ROLE_PATTERN})",
        region,
    ):
        number = _number(match.group("number"))
        if number is not None:
            associations.add((number, _ROSTER_ROLE_ALIASES[match.group("role")]))

    faction_sizes: dict[str, int] = {}
    for role, pattern_role in (("狼人", "狼人"), ("平民", "(?:平民|品名)")):
        pattern = re.compile(rf"(?:{pattern_role})(?:阵营)?(?P<seats>(?:[，,、；;：:]?{_NUM}号)+)")
        faction_sizes[role] = max(
            (len(list(_SEAT.finditer(match.group("seats")))) for match in pattern.finditer(region)),
            default=0,
        )
    return (
        len(associations) >= 4
        and len({role for _seat, role in associations}) >= 3
        and faction_sizes["狼人"] >= 2
        and faction_sizes["平民"] >= 2
    )


def _roster_region(text: str, spans: list[tuple[int, str, int, str]]) -> str:
    """Find a strong final-roster span before the first night without trusting claims."""
    first_night = next(
        (offset for offset, phase, number, _content in spans if phase == "night" and number == 1),
        None,
    )
    has_first_night = first_night is not None
    end = first_night if first_night is not None else len(text)
    pre_night = text[:end]

    intro_pattern = re.compile(
        r"本局(?:版型|板型|板子|版本|配置|游戏|版新)|本期(?:版型|版本)|本就游戏|"
        r"本游戏(?:版型|身份|配置)?|本周游戏|版型|版行为|神(?:职|人)?阵营"
    )
    association_pattern = re.compile(
        rf"(?:{_ROSTER_ROLE_PATTERN})(?:身份|牌)?(?:为|是)?{_ROSTER_ROLE_SEPARATOR}{_NUM}号|"
        rf"{_NUM}号{_ROSTER_ROLE_SEPARATOR}(?:身份为|是|为)?(?:{_ROSTER_ROLE_PATTERN})"
    )

    # A last explicit recap marker narrows the search away from any earlier
    # player chatter that might also mention role-seat pairs.
    recap_starts = [m.end() for m in re.finditer(r"复盘", pre_night)]
    candidate_starts: list[int] = []
    if recap_starts:
        candidate_starts.append(recap_starts[-1])

    # Prefer an intro that actually encloses a dense roster. Some ASR drafts
    # repeat “本局游戏/本局狼人混” after the roster as a separate metadata
    # sentence, so later anchors are accepted only if their own suffix is strong.
    candidate_starts.extend(m.start() for m in intro_pattern.finditer(pre_night))
    candidate_starts.extend(m.start() for m in association_pattern.finditer(pre_night))
    for start in sorted(set(candidate_starts)):
        region = text[start:end]
        if _strong_roster_syntax(region):
            # The no-intro fallback is intentionally enabled only when a first
            # night establishes the roster boundary. Explicit intro candidates
            # still retain the older bounded fallback below without that cue.
            if has_first_night:
                return region

    direct = re.search(
        r"本局(?:版型|板型|板子|版本|配置|游戏|版新)|本期(?:版型|版本)|本就游戏|"
        r"本游戏(?:版型|身份|配置)?",
        pre_night,
    )
    if has_first_night and direct:
        # An explicit “this game's roster/configuration” introduction is itself
        # a strong boundary even when the roster lists only special roles and
        # does not contain civilian/wolf faction runs.
        return text[direct.start():end]

    # Preserve direct-anchor support for recaps with no usable night cue, while
    # never using a generic word or a faction phrase alone as proof of roster.
    if not has_first_night:
        if direct:
            return text[direct.start():min(len(text), direct.start() + 1600)]
    return ""


def _parse_roster(region: str, seat_count: int, issues: list[str]) -> dict[int, str | None]:
    candidates: dict[int, set[str]] = {seat: set() for seat in range(1, seat_count + 1)}
    if not region:
        issues.append("未定位到明确的终局身份名单；玩家自称与行动中的目标身份不会用于填充名单")
        return {seat: None for seat in range(1, seat_count + 1)}

    def assign(seat_text: str, role_text: str) -> None:
        seat = _number(seat_text)
        role = _ROSTER_ROLE_ALIASES.get(role_text)
        if seat is None or role is None:
            return
        if seat > seat_count:
            issues.append(f"身份名单座位超出 seat_count：{seat}号")
            return
        candidates[seat].add(role)

    # Detect a continuous seat-first list only when its first token after the
    # 神职阵营 heading is a numbered role. All other mixed/role-first lists use
    # the explicit role-before-number reading to avoid shifting seats.
    number_role_pattern = re.compile(
        rf"(?P<number>{_NUM})号{_ROSTER_ROLE_SEPARATOR}(?:身份为|是|为)?(?P<role>{_ROSTER_ROLE_PATTERN})"
    )
    heading = re.search(r"神(?:职|人)?阵营", region)
    seat_first_start: int | None = None
    seat_first_end: int | None = None
    if heading:
        rest = region[heading.end():]
        stop = re.search(r"(?:狼人阵营|平民阵营|好人阵营|机械狼|首夜|入夜)", rest)
        roster_block = rest[:stop.start()] if stop else rest
        if number_role_pattern.match(roster_block):
            seat_first_start = heading.end()
            seat_first_end = heading.end() + len(roster_block)
    paired_number_ranges: list[tuple[int, int]] = []
    for match in re.finditer(
        rf"(?P<role>{_ROSTER_ROLE_PATTERN})(?:身份|牌)?(?:为|是)?{_ROSTER_ROLE_SEPARATOR}(?P<number>{_NUM})号",
        region,
    ):
        if seat_first_start is not None and seat_first_end is not None and seat_first_start <= match.start("number") < seat_first_end:
            continue
        assign(match.group("number"), match.group("role"))
        paired_number_ranges.append(match.span("number"))
    faction_run_seats: set[int] = set()
    for role, pattern_role in (("狼人", "狼人"), ("平民", "(?:平民|品名)")):
        role_seats = re.compile(rf"{pattern_role}(?:阵营)?(?P<seats>(?:[，,、；;：:]?{_NUM}号)+)")
        for group in role_seats.finditer(region):
            for number in _SEAT.finditer(group.group("seats")):
                seat = _number(number.group("number"))
                if seat is not None:
                    faction_run_seats.add(seat)
    # In a continuous list like “通灵师一号女巫十号”, the one号 is already
    # paired with 通灵师; do not attach the same number again to the next role.
    for match in number_role_pattern.finditer(region):
        number_range = match.span("number")
        boundary = number_range[0] == 0 or region[number_range[0] - 1] in "，,、；;。"
        in_seat_first_roster = (
            seat_first_start is not None
            and seat_first_end is not None
            and seat_first_start <= match.start() < seat_first_end
        )
        starts_faction_seat_run = (
            _ROSTER_ROLE_ALIASES.get(match.group("role")) in {"狼人", "平民"}
            and re.match(rf"(?:[，,、；;：:]?){_NUM}号", region[match.end():]) is not None
        )
        overlaps_role_first = any(number_range[0] < end and start < number_range[1] for start, end in paired_number_ranges)
        if (
            (boundary or in_seat_first_roster or starts_faction_seat_run)
            and not overlaps_role_first
            and _number(match.group("number")) not in faction_run_seats
        ):
            assign(match.group("number"), match.group("role"))

    # Some official recaps omit “阵营” and speak a role followed by a run of
    # seats, e.g. “狼人一号四号七号九号，平民六号八号十一号”. Only expand
    # these two common faction labels; never sweep numbers after arbitrary roles.
    for role, pattern_role in (("狼人", "狼人"), ("平民", "(?:平民|品名)")):
        role_seats = re.compile(rf"{pattern_role}(?:阵营)?(?P<seats>(?:[，,、；;：:]?{_NUM}号)+)")
        for group in role_seats.finditer(region):
            for number in _SEAT.finditer(group.group("seats")):
                assign(number.group("number"), role)

    roles: dict[int, str | None] = {}
    conflicts: list[int] = []
    for seat, values in candidates.items():
        roles[seat] = next(iter(values)) if len(values) == 1 else None
        if len(values) > 1:
            conflicts.append(seat)
    if conflicts:
        issues.append("终局身份名单座位身份冲突，已保留为未知：" + "、".join(f"{s}号" for s in conflicts))
    missing = [seat for seat, role in roles.items() if role is None]
    if missing:
        issues.append("身份名单未明确揭晓：" + "、".join(f"{s}号" for s in missing) + "；未按版型人数补齐")
    return roles


def _unique_role_seat(roles: dict[int, str | None], role: str) -> int | None:
    matches = [seat for seat, value in roles.items() if value == role]
    return matches[0] if len(matches) == 1 else None


def _seat_value(value: str, seat_count: int) -> int | None:
    seat = _number(value)
    return seat if seat is not None and seat <= seat_count else None


def _event(slot: str, action: str, actor: int | None = None, targets: list[int] | None = None, result: str | None = None) -> dict[str, Any]:
    return {"slot": slot, "action": action, "actor": actor, "targets": targets or [], "result": result}


def _events_in_span(
    span: str,
    phase: str,
    round_number: int,
    roles: dict[int, str | None],
    seat_count: int,
    issues: list[str],
    learned_form: str | None,
) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[int, str, dict[str, Any]]] = []

    def add(event_phase: str, value: dict[str, Any], offset: int = 0) -> None:
        found.append((offset, event_phase, value))

    def actor(role: str, label: str | None = None) -> int | None:
        result = _unique_role_seat(roles, role)
        if result is None:
            issues.append(f"第{round_number}{'夜' if phase == 'night' else '天'}{label or role}行动者座位不唯一或未揭晓")
        return result

    def seer_actor() -> int | None:
        matches = [seat for seat, role in roles.items() if role in {"通灵师", "预言家"}]
        if len(matches) != 1:
            issues.append(f"第{round_number}{'夜' if phase == 'night' else '天'}查验行动者座位不唯一或未揭晓")
            return None
        return matches[0]

    seat_pat = rf"({_NUM})号(?:玩家)?"

    # Night action targets remain separate from explicit night-death reports.
    for match in re.finditer(rf"(?:狼人|狼队|狼刀)(?:选择)?(?:击杀|袭击|选择击杀|刀|袭击目标)(?:了)?{seat_pat}", span):
        target = _seat_value(match.group(1), seat_count)
        if target is not None:
            add("night", _event("wolf_attack", "attack", targets=[target]), match.start())

    for match in re.finditer(
        rf"(?:守卫|首尾|首位)(?:选择)?(?:(?:守护|保护|守了)(?:了|到)?(?P<target>自己|自身|自守|{_NUM}号(?:玩家)?)|(?P<self>自守))",
        span,
    ):
        raw = match.group("target") or match.group("self")
        guard = actor("守卫")
        target_match = _SEAT.fullmatch(raw) if raw not in {"自己", "自身", "自守"} else None
        target = guard if raw in {"自己", "自身", "自守"} else (
            _seat_value(target_match.group("number"), seat_count) if target_match else None
        )
        if target is not None:
            add("night", _event("guard", "guard", actor=guard, targets=[target]), match.start())
        else:
            issues.append(f"第{round_number}夜守卫守护目标不清楚")

    for match in re.finditer(rf"女巫(?:使用解药)?(?:要|选择)?(?:救起|救下|救活|解救|救)(?:了)?{seat_pat}", span):
        target = _seat_value(match.group(1), seat_count)
        if target is not None:
            add("night", _event("witch_save", "save", actor=actor("女巫"), targets=[target]), match.start())
    for match in re.finditer(rf"女巫(?:使用毒药)?(?:选择)?(?:毒杀|毒死|毒了|毒)(?:了)?{seat_pat}", span):
        target = _seat_value(match.group(1), seat_count)
        if target is not None:
            outcome = "毒药反弹" if re.search(r"毒药.{0,10}反弹|反弹.{0,10}毒药", span) else None
            add("night", _event("witch_poison", "poison", actor=actor("女巫"), targets=[target], result=outcome), match.start())

    # Explicit no-use statements mean pass only for that named potion; they do
    # not establish that the potion was consumed or is no longer available.
    save_pass = re.search(r"女巫.{0,8}(?:解药|药).{0,4}(?:空过|未使用|没有使用|没用)", span)
    if save_pass:
        add("night", _event("witch_save", "pass", actor=_unique_role_seat(roles, "女巫"), result="明确记录本夜未使用解药"), save_pass.start())
    poison_pass = re.search(r"女巫.{0,8}毒药.{0,4}(?:空过|未使用|没有使用|没用)", span)
    if poison_pass:
        add("night", _event("witch_poison", "pass", actor=_unique_role_seat(roles, "女巫"), result="明确记录本夜未使用毒药"), poison_pass.start())
    if re.search(r"女巫(?:当夜)?(?:技能)?空过", span) and not re.search(r"(?:解药|毒药).{0,4}(?:空过|未使用)", span):
        issues.append(f"第{round_number}夜只说女巫空过，未说明哪瓶药；不推断药品状态")

    for match in re.finditer(
        rf"(?:通灵师|预言家|冤家)(?:夜间)?(?:验证|查验|验)(?:了)?{seat_pat}(?:玩家)?(?:的身份)?(?:为|是)?(?P<result>{_ROLE_PATTERN}|好人|坏人)?(?:身份)?",
        span,
    ):
        target = _seat_value(match.group(1), seat_count)
        if target is not None:
            result_label = match.group("result")
            result = _ROLE_ALIASES.get(result_label, result_label) if result_label else None
            add("night", _event("seer_check", "check", actor=seer_actor(), targets=[target], result=result), match.start())

    # Mechanic learning is kept distinct from the modeled seat's original role.
    learn_pattern = re.compile(
        rf"机械狼(?:(?:为|是)?(?P<mech>{_NUM})号)?(?:选择)?(?:模仿|学习)(?:了)?(?P<target>{_NUM})号(?P<role>{_ROLE_PATTERN})?"
    )
    for match in learn_pattern.finditer(span):
        mech_seat = _seat_value(match.group("mech"), seat_count) if match.group("mech") else _unique_role_seat(roles, "机械狼")
        target = _seat_value(match.group("target"), seat_count)
        learned_role = _learned_mechanical_form(target, match.group("role"), learned_form, roles, issues)
        add("night", _event("mechanical_action", "learn", actor=mech_seat, targets=[target] if target is not None else [], result=learned_role), match.start())

    for match in re.finditer(r"机械狼(?:已经|当前)?(?:接过|获得|带上|带刀)(?:了)?刀|机械狼带刀", span):
        add("night", _event("mechanical_knife_status", "carrying", actor=_unique_role_seat(roles, "机械狼")), match.start())
    for match in re.finditer(r"机械狼(?:没有|未|尚未)带刀|机械狼不带刀", span):
        add("night", _event("mechanical_knife_status", "not_carrying", actor=_unique_role_seat(roles, "机械狼")), match.start())

    # Additional learned guard action; it remains its own template-mappable slot.
    for match in re.finditer(
        rf"机械狼(?:(?:为|是)?(?P<mech>{_NUM})号)?(?:技能)?守护(?:了)?(?P<target>{_NUM})号(?:玩家)?",
        span,
    ):
        mech = _seat_value(match.group("mech"), seat_count) if match.group("mech") else _unique_role_seat(roles, "机械狼")
        target = _seat_value(match.group("target"), seat_count)
        if target is not None:
            add("night", _event("mechanical_action", "guard", actor=mech, targets=[target]), match.start())

    for match in re.finditer(rf"猎人(?:(?:玩家)?(?:可以|能够|能)开枪|可以发动技能)", span):
        add("night", _event("hunter_state", "can_shoot", actor=_unique_role_seat(roles, "猎人")), match.start())
    for match in re.finditer(r"猎人(?:玩家)?(?:不能|无法|不可)开枪|猎人(?:被毒|中毒)(?:后)?不能开枪", span):
        add("night", _event("hunter_state", "cannot_shoot", actor=_unique_role_seat(roles, "猎人")), match.start())

    # Day events are recognized anywhere after a stage cue because some referee
    # transcripts narrate a dawn death or hunter shot before saying “白天”.
    hunter_shot_patterns = (
        re.compile(rf"猎人(?:出局后?|玩家)?(?:选择)?(?:开枪|发动技能)(?:带走|射杀|打死)(?:最后一张(?:神职)?牌)?(?:了)?(?P<target>{_NUM})号(?:玩家)?"),
        re.compile(rf"(?P<actor>{_NUM})号(?:机械)?猎人(?:玩家)?(?:被(?:(?:公投|投票|抗推)?出局)|出局)?(?:选择)?(?:开枪|发动技能)(?:带走|射杀|打死)(?:最后一张(?:神职)?牌)?(?:了)?(?P<target>{_NUM})号(?:玩家)?"),
    )
    for pattern in hunter_shot_patterns:
        for match in pattern.finditer(span):
            target = _seat_value(match.group("target"), seat_count)
            if target is not None:
                shot_actor = _seat_value(match.group("actor"), seat_count) if "actor" in match.groupdict() and match.group("actor") else _unique_role_seat(roles, "猎人")
                add("day", _event("hunter_shot", "shoot", actor=shot_actor, targets=[target]), match.start())
    for match in re.finditer(rf"(?P<actor>{_NUM})号(?:狼人|狼王|机械狼|玩家)?(?:选择|决定)?自爆", span):
        seat = _seat_value(match.group("actor"), seat_count)
        if seat is not None:
            add("day", _event("self_destruct", "self_destruct", actor=seat), match.start())
    exile_patterns = (
        re.compile(rf"(?P<target>{_NUM})号(?:(?:悍跳)?(?:{_ROLE_PATTERN})|悍跳狼)?(?:玩家)?(?:被)?(?:公投|投票|抗推|放逐)(?:出局|淘汰|离场)?"),
        re.compile(rf"(?:将|把)(?P<target>{_NUM})号(?:(?:悍跳)?(?:{_ROLE_PATTERN})|悍跳狼)?(?:玩家)?(?:进行)?(?:公投|投票|抗推|放逐)(?:出局|淘汰|离场)?"),
    )
    exile_matches: dict[int, int] = {}
    for pattern in exile_patterns:
        for match in pattern.finditer(span):
            target = _seat_value(match.group("target"), seat_count)
            if target is not None:
                exile_matches.setdefault(target, match.start())
    for target, offset in sorted(exile_matches.items(), key=lambda item: item[1]):
        add("day", _event("exile_result", "exile", targets=[target]), offset)
    sheriff_patterns = (
        re.compile(rf"(?P<target>{_NUM})号(?:(?:悍跳)?(?:{_ROLE_PATTERN})|悍跳狼)?(?:玩家)?(?:成功)?(?:获得|拿到|当选)(?:了)?(?:警徽|警长)"),
        re.compile(rf"警长(?:由|是|为)?(?P<target>{_NUM})号(?:玩家)?"),
    )
    sheriff_matches: dict[int, int] = {}
    for pattern in sheriff_patterns:
        for match in pattern.finditer(span):
            target = _seat_value(match.group("target"), seat_count)
            if target is not None:
                sheriff_matches.setdefault(target, match.start())
    for target, offset in sorted(sheriff_matches.items(), key=lambda item: item[1]):
        add("day", _event("sheriff_result", "elected", targets=[target]), offset)
    for match in re.finditer(rf"警徽(?:移交|交给|转交)(?:了)?(?:至|给)?(?P<target>{_NUM})号(?:玩家)?", span):
        target = _seat_value(match.group("target"), seat_count)
        if target is not None:
            add("day", _event("badge", "transfer", targets=[target]), match.start())
    badge_destroy = re.search(r"警徽(?:流失|撕毁|撕掉)|撕掉警徽", span)
    if badge_destroy:
        add("day", _event("badge", "destroy"), badge_destroy.start())
    no_sheriff = re.search(r"无警长|没有警长", span)
    if no_sheriff:
        add("day", _event("sheriff_result", "none"), no_sheriff.start())

    # A night death is emitted only from an explicit result phrase. Attack and
    # poison targets above are never promoted into this slot by inference.
    peaceful = re.search(r"(?:形成|迎来)?平安夜|平安夜", span)
    if peaceful:
        add("day", _event("night_deaths", "peaceful"), peaceful.start())
    explicit_deaths: set[int] = set()
    death_offset = len(span)
    for match in re.finditer(rf"{seat_pat}(?:和|与|、|及)?{seat_pat}(?:玩家)?(?:双死|双亡|一起死亡|均死亡)", span):
        first = _seat_value(match.group(1), seat_count)
        second = _seat_value(match.group(2), seat_count)
        if first is not None and second is not None:
            explicit_deaths.update((first, second))
            death_offset = min(death_offset, match.start())
    for match in re.finditer(rf"{seat_pat}(?:玩家)?(?:单死|死亡|身亡|倒牌)", span):
        seat = _seat_value(match.group(1), seat_count)
        if seat is not None and not re.search(rf"{re.escape(match.group(0))}.{{0,5}}(?:没死|未死|没有死亡)", span):
            explicit_deaths.add(seat)
            death_offset = min(death_offset, match.start())
    # Poison reflection is an explicit death only when the text says the witch
    # died. The intended poison target is intentionally not added.
    if re.search(r"毒药.{0,12}反弹.{0,12}女巫(?:死亡|身亡|被毒死)|女巫.{0,8}毒药反弹.{0,8}(?:死亡|身亡)", span):
        witch_seat = _unique_role_seat(roles, "女巫")
        if witch_seat is not None:
            explicit_deaths.add(witch_seat)
            death_offset = min(death_offset, re.search(r"毒药.{0,12}反弹|女巫.{0,8}毒药反弹", span).start())
    if explicit_deaths:
        add("day", _event("night_deaths", "die", targets=sorted(explicit_deaths)), death_offset)

    return [(event_phase, value) for _offset, event_phase, value in sorted(found, key=lambda item: item[0])]


def _winning_faction(text: str, issues: list[str]) -> str | None:
    # The final result is ordinarily spoken immediately after “游戏结束”.
    # Prefer that terminal clause; a hypothetical earlier claim is not enough.
    end = text.rfind("游戏结束")
    candidate_text = text[end:] if end >= 0 else text[-500:]
    if re.search(r"如果|假如|可能|本来", candidate_text):
        # Keep a clear explicit terminal result despite nearby commentary only
        # when a game-over cue anchors it.
        if end < 0:
            return None
    pattern = re.compile(
        r"(好人|狼人|狼队|第三方)(?:阵营)?(?:正义|屠神|屠民)?"
        r"(?:获得|取得|获得了)?(?:获胜|胜利)"
    )
    matches = [m.group(1) for m in pattern.finditer(candidate_text)]
    normalized = {"狼人" if value == "狼队" else value for value in matches}
    if len(normalized) == 1:
        value = next(iter(normalized))
        return {"好人": "good", "狼人": "werewolf", "第三方": "third_party"}[value]
    if len(normalized) > 1:
        issues.append("终局胜负播报互相冲突，胜利阵营保留为未知")
    return None


def extract_recap(segments: list[dict[str, Any]], board_name: str, seat_count: int = 12) -> dict[str, Any]:
    """Extract conservative identity, round-event and winner candidates.

    Args:
        segments: ASR or corrected text segments with start_ms/end_ms/text.
        board_name: Display name of the game board; used by callers for context.
        seat_count: Number of seats in the game.

    The function is pure and safe to call repeatedly. It accepts fragments
    split across arbitrary segment boundaries, but assumes its input is already
    the referee's final recap rather than a whole broadcast.
    """
    if not isinstance(seat_count, int) or seat_count < 1:
        raise ValueError("seat_count must be a positive integer")
    if not isinstance(board_name, str):
        raise TypeError("board_name must be a string")
    text = _compact(segments or [])
    issues: list[str] = []
    spans = _stage_spans(text)
    roster_region = _roster_region(text, spans)
    role_by_seat = _parse_roster(roster_region, seat_count, issues)

    seats: list[dict[str, Any]] = [
        {"seat": seat, "role": role_by_seat[seat], "learning_target": None, "learned_role": None}
        for seat in range(1, seat_count + 1)
    ]
    seat_by_number = {seat["seat"]: seat for seat in seats}

    # Record learning metadata only from explicit “mechanical wolf learns or
    # models N号[role]” wording. Never replace the original role.
    learn_meta = re.compile(
        rf"机械狼(?:(?:为|是)?(?P<mech>{_NUM})号)?(?:选择)?(?:模仿|学习)(?:了)?(?P<target>{_NUM})号(?P<role>{_ROLE_PATTERN})?"
    )
    learn_form_only = re.compile(
        rf"机械狼(?:(?:为|是)?(?P<mech>{_NUM})号)?(?:选择)?(?:模仿|学习)(?:了)?"
        rf"(?:成为|变成|获得)?(?P<role>机械双刀狼|机械通灵师|机械(?:女巫|猎人|守卫|平民))(?:形态|技能)?"
    )
    mech_seat = _unique_role_seat(role_by_seat, "机械狼")
    form_declaration = re.compile(
        r"(?:本局|本酒席|本场|本游戏)(?:游戏|对局|身份|形态)?(?:的)?(?:机械狼)?(?:形态)?(?:是|为)"
        r"(?P<form>机械双刀狼|机械通灵师|机械女巫|机械猎人|机械守卫|机械平民)(?:形态)?"
    )
    explicit_forms = list(dict.fromkeys(match.group("form") for match in form_declaration.finditer(text)))
    learned_form = explicit_forms[0] if len(explicit_forms) == 1 else None
    if len(explicit_forms) > 1:
        issues.append("终局身份名单中的机械狼形态互相冲突，学习形态保留为未知")
    learn_values: dict[int, set[tuple[int | None, str | None]]] = {}
    for match in learn_meta.finditer(text):
        actor_seat = _seat_value(match.group("mech"), seat_count) if match.group("mech") else mech_seat
        target = _seat_value(match.group("target"), seat_count)
        if actor_seat is None or actor_seat not in seat_by_number:
            issues.append("机械狼学习记录无法唯一对应到初始机械狼座位")
            continue
        learned = _learned_mechanical_form(target, match.group("role"), learned_form, role_by_seat, issues)
        learn_values.setdefault(actor_seat, set()).add((target, learned))
    for match in learn_form_only.finditer(text):
        actor_seat = _seat_value(match.group("mech"), seat_count) if match.group("mech") else mech_seat
        if actor_seat is None or actor_seat not in seat_by_number:
            issues.append("机械狼学习形态无法唯一对应到初始机械狼座位")
            continue
        learned = _mechanical_form(_ROLE_ALIASES.get(match.group("role")))
        if learned_form and learned and learned_form != learned:
            issues.append(f"机械狼学习形态{learned}与本局已声明形态{learned_form}冲突，相关字段保留为未知")
            learned = None
        learn_values.setdefault(actor_seat, set()).add((None, learned))
    if not learn_values and learned_form and mech_seat is not None:
        # Some final-referee recaps identify the mechanical wolf's form but omit
        # its modeled seat. Preserve the confirmed form as a one-sided result.
        learn_values.setdefault(mech_seat, set()).add((None, learned_form))
    for actor_seat, values in learn_values.items():
        if len(values) == 1:
            target, learned = next(iter(values))
            seat_by_number[actor_seat]["learning_target"] = target
            seat_by_number[actor_seat]["learned_role"] = learned
        else:
            issues.append(f"{actor_seat}号机械狼学习目标或形态冲突，相关字段保留为未知")

    round_map: dict[int, dict[str, Any]] = {}
    for _offset, phase, number, content in spans:
        round_record = round_map.setdefault(number, {"number": number, "night": [], "day": []})
        for event_phase, event in _events_in_span(content, phase, number, role_by_seat, seat_count, issues, learned_form):
            round_map[number][event_phase].append(event)
    rounds = [round_map[number] for number in sorted(round_map)]
    if not rounds and text:
        issues.append("未从片段中找到明确的首夜、入夜或第N天轮次标记；没有猜测事件轮次")

    # De-duplicate identical warnings while preserving their first occurrence.
    issues = list(dict.fromkeys(issues))
    return {
        "seats": seats,
        "rounds": rounds,
        "winning_faction": _winning_faction(text, issues),
        "issues": issues,
    }

