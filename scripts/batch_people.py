"""Conservative local enrichment of batch S22 names and seat assignments."""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_REL = Path("data/weibo/2026-05-26_2026-10-20/比赛排班.csv")
PHOTO_NAMES_REL = Path("data/weibo/2026-05-26_2026-10-20/参赛名单/人名去重_照片映射.csv")
TOTAL_NAMES_REL = Path("data/weibo/2026-05-26_2026-10-20/参赛名单/京城大师赛_S22至今_参赛人名总表.csv")
JUNE_25_SAMPLE_REL = Path("data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q/dossier.json")

# These are editorially confirmed mappings for known schedule handles.
EXPLICIT_ALIASES = {
    "其人": "其人",
    "其人的心事": "其人",
    "陸慧霖_陆元箐小桃子": "桃子",
    "pointy豆儿啵": "豆儿啵",
    "萧亚辉": "辉少",
    "JY戴士": "JY",
}

_PROMPT_RE = re.compile(r"有请\s*(?:第\s*)?([一二三四五六七八九十两\d]{1,3})\s*号(?:\s*玩家)?")
_SELF_RE = re.compile(r"我\s*(?:是|叫|叫做)\s*([A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·_\-]{0,29})")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _key(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE)


def _split_names(value: str | None) -> list[str]:
    return [part.strip() for part in re.split(r"[、,，;；]+", value or "") if part.strip()]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _add_alias(aliases: dict[str, set[str]], alias: str | None, canonical: str | None) -> None:
    alias, canonical = (alias or "").strip(), (canonical or "").strip()
    key = _key(alias)
    if key and canonical:
        aliases.setdefault(key, set()).add(canonical)


def _name_aliases(root: Path, issues: list[str]) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    photo_path = root / PHOTO_NAMES_REL
    if photo_path.is_file():
        try:
            for row in _read_csv(photo_path):
                if row.get("赛季") != "S22" or row.get("纳入参赛名单") != "是":
                    continue
                canonical = row.get("去重后姓名", "").strip()
                for field in ("原图名字", "复核行名字", "去重后姓名"):
                    _add_alias(aliases, row.get(field), canonical)
        except (OSError, UnicodeError, csv.Error) as exc:
            issues.append(f"无法读取S22人名去重映射表：{type(exc).__name__}。")
    else:
        issues.append("缺少S22人名去重映射表；仅使用明确别名和清晰原名。")

    total_path = root / TOTAL_NAMES_REL
    if total_path.is_file():
        try:
            for row in _read_csv(total_path):
                if "S22" not in (row.get("参与赛季") or ""):
                    continue
                canonical = row.get("姓名", "").strip()
                _add_alias(aliases, canonical, canonical)
                for raw in re.split(r"[、,，;；|/]+", row.get("原图名字", "")):
                    _add_alias(aliases, raw, canonical)
        except (OSError, UnicodeError, csv.Error) as exc:
            issues.append(f"无法读取已复核参赛人名总表：{type(exc).__name__}。")

    for alias, canonical in EXPLICIT_ALIASES.items():
        _add_alias(aliases, alias, canonical)
    return aliases


def _resolve_name(raw: str, aliases: dict[str, set[str]], *, allow_clear_name: bool = False,
                  prefix_only: bool = False) -> tuple[str | None, str]:
    key = _key(raw)
    if not key:
        return None, "empty"
    exact = aliases.get(key, set())
    if len(exact) == 1:
        return next(iter(exact)), "mapped"
    if len(exact) > 1:
        return None, "ambiguous"

    # Handles commonly add a location, platform ID, or playful suffix to a
    # reviewed display name. Accept only the unique longest reviewed token.
    matches = [(len(alias), values) for alias, values in aliases.items()
               if len(alias) >= 2 and (key.startswith(alias) if prefix_only else alias in key)]
    if matches:
        longest = max(length for length, _ in matches)
        targets = set().union(*(values for length, values in matches if length == longest))
        if len(targets) == 1:
            return next(iter(targets)), "mapped"
        return None, "ambiguous"

    if allow_clear_name:
        # Keep a plainly written Chinese name, but do not mint a person from a
        # mixed-script handle. A CJK prefix before an ID separator is clear too.
        cjk = r"\u3400-\u9fff"
        prefix = re.split(r"[_|/·]", raw.strip(), maxsplit=1)[0].strip()
        if re.fullmatch(rf"[{cjk}]{{2,6}}", prefix):
            return prefix, "clear_unreviewed"
        if re.fullmatch(rf"[{cjk}]{{2,8}}", raw.strip()):
            return raw.strip(), "clear_unreviewed"
    return None, "unmapped"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _schedule_row(root: Path, date: str, issues: list[str]) -> tuple[dict[str, str] | None, list[dict[str, object]]]:
    path = root / SCHEDULE_REL
    if not path.is_file():
        issues.append("缺少本地比赛排班表；没有补入解说、法官或名单。")
        return None, []
    try:
        rows = _read_csv(path)
    except (OSError, UnicodeError, csv.Error) as exc:
        issues.append(f"无法读取本地比赛排班表：{type(exc).__name__}。")
        return None, []

    dated_rows = [(i + 2, row) for i, row in enumerate(rows) if row.get("比赛日期") == date]
    s22 = [(line, row) for line, row in dated_rows if row.get("赛季") == "S22"]
    candidates = [{"row": line, "season": row.get("赛季"), "date": row.get("比赛日期"),
                   "phase": row.get("阶段"), "episode": row.get("期数")} for line, row in dated_rows]
    if len(s22) != 1:
        if s22:
            issues.append(f"{date}有多条S22排班记录，无法唯一关联；未补入当日人员。")
        else:
            issues.append(f"{date}没有S22排班公告，未补入当日人员。")
        return None, candidates
    return {**s22[0][1], "_source_row": str(s22[0][0])}, candidates


def _rows_by_date(root: Path, date: str, issues: list[str]) -> tuple[dict[str, str] | None, list[dict[str, object]]]:
    if not _DATE_RE.fullmatch(date or ""):
        issues.append("批次日期缺失或格式不合法；无法安全关联当日排班。")
        return None, []
    return _schedule_row(root, date, issues)


def _convert_seat_number(raw: str) -> int | None:
    if raw.isdigit():
        number = int(raw)
        return number if 1 <= number <= 12 else None
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    if raw == "十":
        return 10
    if "十" in raw:
        left, _, right = raw.partition("十")
        number = (digits.get(left, 1) if left else 1) * 10 + (digits.get(right, 0) if right else 0)
    elif len(raw) == 2:
        number = digits.get(raw[0], 0) * 10 + digits.get(raw[1], 0)
    else:
        number = digits.get(raw, 0)
    return number if 1 <= number <= 12 else None


def _intro_files(root: Path, date: str) -> tuple[Path | None, list[Path]]:
    season_root = root / "data/seasons/S22"
    if not season_root.is_dir():
        return None, []
    files = sorted(p for p in season_root.rglob("*") if p.is_file()
             and date in p.name and re.search(r"第(?:0?1|一)局", p.name)
             and p.suffix.casefold() in {".txt", ".srt", ".vtt"})

    def pick_unique_source(candidates: list[Path]) -> tuple[Path | None, bool]:
        # A reading text and its SRT/VTT companion represent one transcript
        # source. Distinct transcript sources at the same priority stay
        # ambiguous; among formats for one source, prefer the readable text.
        sources: dict[tuple[Path, str], list[Path]] = {}
        for path in candidates:
            stem = re.sub(r"\.阅读$", "", path.stem)
            sources.setdefault((path.parent.resolve(), stem), []).append(path)
        if not sources:
            return None, False
        if len(sources) > 1:
            return None, True
        representations = next(iter(sources.values()))
        chosen = min(representations, key=lambda path: (
            0 if "阅读" in path.name else 1,
            0 if path.suffix.casefold() == ".txt" else 1,
            str(path),
        ))
        return chosen, False

    local_full, ambiguous = pick_unique_source([p for p in files if "本地全文" in p.name])
    if local_full is not None or ambiguous:
        return local_full, files

    platform_reading, ambiguous = pick_unique_source(
        [p for p in files if "平台" in p.name and "阅读" in p.name]
    )
    if platform_reading is not None or ambiguous:
        return platform_reading, files

    preferred = [p for p in files if "平台AI字幕" in p.name or "转写" in p.name]
    pool = preferred if preferred else files
    selected, _ = pick_unique_source(pool)
    return selected, files


def _timestamp_ms(prefix: str) -> int | None:
    match = re.search(r"(\d{2}):(\d{2}):(\d{2})(?:[.,](\d+))?", prefix)
    if not match:
        return None
    hour, minute, second = (int(match.group(i)) for i in (1, 2, 3))
    fraction = (match.group(4) or "")[:3].ljust(3, "0")
    return ((hour * 60 + minute) * 60 + second) * 1000 + int(fraction or "0")


def _transcript_segments(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    segments: list[dict[str, object]] = []
    srt_time: int | None = None
    for line_number, line in enumerate(text.splitlines(), 1):
        bracket = re.match(r"\s*\[([^\]]+)\]\s*(.*)", line)
        if bracket:
            content = bracket.group(2).strip()
            if content:
                segments.append({"line": line_number, "time_ms": _timestamp_ms(bracket.group(1)), "text": content})
            continue
        timing = re.match(r"\s*(\d{2}:\d{2}:\d{2}[,.]\d+)\s*-->", line)
        if timing:
            srt_time = _timestamp_ms(timing.group(1))
            continue
        content = line.strip()
        if content and not content.isdigit() and srt_time is not None:
            segments.append({"line": line_number, "time_ms": srt_time, "text": content})
            srt_time = None
        elif content and not content.isdigit() and not re.match(r"\d{2}:\d{2}:\d{2}", content):
            segments.append({"line": line_number, "time_ms": None, "text": content})
    return segments


def _intro_candidates(path: Path | None, aliases: dict[str, set[str]], roster: list[str]) -> list[dict[str, object]]:
    if path is None:
        return []
    segments = _transcript_segments(path)
    prompts: list[tuple[int, int, str]] = []
    for i, segment in enumerate(segments):
        match = _PROMPT_RE.search(str(segment["text"]))
        if match:
            seat = _convert_seat_number(match.group(1))
            if seat is not None:
                prompts.append((i, seat, match.group(0)))

    candidates: list[dict[str, object]] = []
    for prompt_index, (segment_index, seat, prompt_text) in enumerate(prompts):
        next_prompt_index = prompts[prompt_index + 1][0] if prompt_index + 1 < len(prompts) else len(segments)
        prompt_segment = segments[segment_index]
        prompt_time = prompt_segment.get("time_ms")
        for candidate_index in range(segment_index + 1, min(next_prompt_index, segment_index + 9)):
            segment = segments[candidate_index]
            candidate_time = segment.get("time_ms")
            if (prompt_time is not None and candidate_time is not None
                    and candidate_time - prompt_time > 20_000):
                break
            match = _SELF_RE.search(str(segment["text"]))
            if not match:
                continue
            raw_name = match.group(1).strip("_-")
            raw_name = re.sub(r"^(?:第)?[一二三四五六七八九十两\d]{1,3}号(?:玩家)?", "", raw_name)
            key = _key(raw_name)
            resolved, status = _resolve_name(raw_name, aliases, prefix_only=True)
            if resolved is None:
                # A name can still resolve against this date's roster when the
                # schedule supplied a clear but not previously catalogued name.
                roster_matches = [name for name in roster if _key(name) and key.startswith(_key(name))]
                if roster_matches:
                    longest = max(len(_key(name)) for name in roster_matches)
                    finalists = {name for name in roster_matches if len(_key(name)) == longest}
                    if len(finalists) == 1:
                        resolved, status = next(iter(finalists)), "roster_match"
                    else:
                        status = "ambiguous"
            if resolved not in roster:
                resolved = None
                if status not in {"ambiguous", "unmapped"}:
                    status = "not_in_roster"
            candidates.append({
                "seat": seat,
                "prompt_line": prompt_segment["line"],
                "prompt_time_ms": prompt_time,
                "prompt": prompt_text,
                "self_intro_line": segment["line"],
                "self_intro_time_ms": candidate_time,
                "self_intro": segment["text"],
                "claimed_name": raw_name,
                "resolved_name": resolved,
                "status": status,
            })
            break
    return candidates


def _sample_seats(root: Path, date: str, roster: list[str]) -> tuple[dict[int, str] | None, Path | None]:
    if date != "2026-06-25":
        return None, None
    path = root / JUNE_25_SAMPLE_REL
    if not path.is_file():
        return None, path
    try:
        sample = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, path
    mapped = {int(seat["seat"]): seat["name"] for seat in sample.get("seats", [])
              if isinstance(seat.get("seat"), int) and isinstance(seat.get("name"), str)}
    sample_roster = set(sample.get("roster", []))
    if len(mapped) == 12 and len(sample_roster) == 12 and sample_roster == set(roster):
        return mapped, path
    return None, path


def enrich_people(value: dict, entry: dict, root: Path | str = ROOT) -> tuple[dict, list[str], dict]:
    """Fill only names supported by the same-day schedule or local self-intros.

    The returned context is review metadata for the caller's separate progress
    files; it is deliberately not copied into the business dossier.
    """
    root = Path(root)
    issues: list[str] = []
    context: dict[str, object] = {
        "schedule_path": _relative(root / SCHEDULE_REL, root),
        "schedule_candidates": [],
        "intro_source_path": None,
        "intro_source_candidates": [],
        "intro_candidates": [],
        "seat_source": None,
        "seat_source_path": None,
    }
    if entry.get("season") not in (None, "S22"):
        issues.append("批次不是S22；未根据S22排班补入人员。")
        return value, issues, context

    date = str(entry.get("date") or "")
    aliases = _name_aliases(root, issues)
    schedule, schedule_candidates = _rows_by_date(root, date, issues)
    context["schedule_candidates"] = schedule_candidates
    if schedule is None:
        return value, issues, context
    context["schedule_row"] = int(schedule["_source_row"])

    raw_roster = _split_names(schedule.get("选手"))
    roster: list[str] = []
    for raw in raw_roster:
        canonical, status = _resolve_name(raw, aliases, allow_clear_name=True)
        if canonical is None:
            issues.append(f"排班选手“{raw}”无法唯一映射到规范姓名；未建新人物。")
            continue
        if status == "clear_unreviewed":
            issues.append(f"排班选手“{raw}”未在复核名册中唯一匹配，暂保留清楚原名“{canonical}”。")
        if canonical in roster:
            issues.append(f"排班名单多个原名映射到“{canonical}”；名单已去重。")
            continue
        roster.append(canonical)
    value["roster"] = roster

    def map_staff(field: str, label: str) -> list[str]:
        mapped: list[str] = []
        for raw in _split_names(schedule.get(field)):
            canonical, status = _resolve_name(raw, aliases, allow_clear_name=True)
            if canonical is None:
                issues.append(f"{label}“{raw}”无法唯一映射；暂不写入。")
                continue
            if status == "clear_unreviewed":
                issues.append(f"{label}“{raw}”未在复核名册中唯一匹配，暂保留清楚原名“{canonical}”。")
            if canonical not in mapped:
                mapped.append(canonical)
        return mapped

    value["commentators"] = map_staff("解说", "解说")
    referees = map_staff("法官", "法官")
    value["referee"] = referees[0] if len(referees) == 1 else None
    if len(referees) > 1:
        issues.append("当日法官映射出多个人名，未选择单一法官。")

    intro_path, intro_files = _intro_files(root, date)
    context["intro_source_candidates"] = [_relative(path, root) for path in intro_files]
    if intro_path is None:
        if intro_files:
            issues.append("当日首局转写有多个候选，无法唯一选定；未从转写归座。")
        else:
            issues.append("没有找到当日首局转写；未从转写归座。")
    else:
        context["intro_source_path"] = _relative(intro_path, root)
        try:
            intro_candidates = _intro_candidates(intro_path, aliases, roster)
        except OSError as exc:
            intro_candidates = []
            issues.append(f"无法读取当日首局转写：{type(exc).__name__}。")
        context["intro_candidates"] = intro_candidates

    seats = {int(seat["seat"]): seat for seat in value.get("seats", [])
             if isinstance(seat, dict) and isinstance(seat.get("seat"), int)}
    sample_mapping, sample_path = _sample_seats(root, date, roster)
    if sample_mapping is not None and sample_path is not None:
        context["seat_source"] = "confirmed_same_day_sample"
        context["seat_source_path"] = _relative(sample_path, root)
        issues.append("复用同日已确认座位样例；若本局阵容换人，需按新阵容更新座位映射。")
        for number, name in sample_mapping.items():
            seat = seats.get(number)
            if seat is None:
                continue
            if seat.get("name") is None or seat.get("name") == name:
                seat["name"] = name
            else:
                issues.append(f"{number}号已有姓名“{seat['name']}”，未覆盖同日样例姓名“{name}”。")
    else:
        if date == "2026-06-25" and sample_path is not None and sample_path.is_file():
            issues.append("同日已确认样例阵容与本日公告不完全一致，未复用座位；如属换人，需按本局重新核对。")
        candidates = context["intro_candidates"]
        by_name: dict[str, list[int]] = {}
        for candidate in candidates:
            name = candidate.get("resolved_name")
            if name:
                by_name.setdefault(str(name), []).append(int(candidate["seat"]))
        duplicates = {name for name, numbers in by_name.items() if len(set(numbers)) > 1}
        for name in duplicates:
            issues.append(f"首局自我介绍把“{name}”关联到多个座位；均未自动归座。")
        assigned = False
        for candidate in candidates:
            number, name = int(candidate["seat"]), candidate.get("resolved_name")
            if not name:
                if candidate.get("status") in {"ambiguous", "not_in_roster", "unmapped"}:
                    issues.append(f"{number}号自我介绍“{candidate.get('claimed_name')}”无法与当日名单唯一对应；未归座。")
                continue
            if name in duplicates:
                continue
            seat = seats.get(number)
            if seat is None:
                continue
            if seat.get("name") is None or seat.get("name") == name:
                seat["name"] = name
                assigned = True
            else:
                issues.append(f"首局转写的{number}号姓名“{name}”与已有姓名冲突；未覆盖。")
        if assigned:
            context["seat_source"] = "first_game_self_introduction"
            context["seat_source_path"] = _relative(intro_path, root) if intro_path else None
        elif intro_path is not None:
            issues.append("首局转写没有可与当日名单唯一匹配的自我介绍；未按照片顺序归座。")

    # User-confirmed rule: JY is seat 7, but only when the official roster
    # establishes that JY actually participated on this date.
    if "JY" in roster and 7 in seats:
        for number, seat in seats.items():
            if number != 7 and seat.get("name") == "JY":
                seat["name"] = None
                issues.append(f"首局候选把JY放在{number}号；按已确认规则只保留7号。")
        if seats[7].get("name") not in (None, "JY"):
            issues.append(f"7号首局自我介绍与已确认的JY7规则冲突；按用户确认规则填为JY。")
        seats[7]["name"] = "JY"
        if context.get("seat_source") is None:
            context["seat_source"] = "confirmed_jy_seat_rule"
            context["seat_source_path"] = context.get("schedule_path")

    # Context is intentionally separate from the dossier's business schema.
    return value, list(dict.fromkeys(issues)), context
