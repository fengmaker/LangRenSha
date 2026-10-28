"""Adapt approved S21 identity and day/night reviews into incomplete formal records."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = str(ROOT / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import database
import endgame_records
import game_records
import s21_phase_review as phase_review
import voting_records
from psycopg.types.json import Jsonb

INDEX = Path("data/reports/S21_文字与截图时点索引.json")
SCOPE = Path("config/S21_game_scope.json")
PHASE_AUDIT = Path("data/extractions/S21/phase_primary_audit.json")
OUTPUT = Path("data/games/S21")
PHASE_DIR = Path("data/extractions/S21/phase_specs")
REVIEW_DIR = Path("data/extractions/S21/game_reviews")
BOARD_TITLES = {
    "预女猎白混": "s21_seer_witch_hunter_white_mixed",
    "机械狼通灵师": "s21_mechanical_wolf_seer",
    "诡术之境": "s21_guile_realm",
    "盗宝大师": "s21_treasure_master",
    "假面舞会": "s21_masquerade",
    "唯邻是从": "s21_neighbor_puppet",
    "孤注一掷": "s21_all_in",
    "狼王守卫": "s21_wolf_king_guard",
}
BOARD_ALIASES = {"机械狼通灵师修改": "机械狼通灵师"}
UNKNOWN_ROLES = {"", "未知", "unknown", "?"}


class ReviewError(database.ReviewError):
    pass


def read_json(root: Path, relative: str | Path):
    return json.loads((root / relative).read_text(encoding="utf-8"))


def digest(root: Path, relative: str | Path) -> str:
    with (root / relative).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def checked_data_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    data_root = (root / "data").resolve()
    if not path.is_relative_to(data_root) or not path.is_file():
        raise ReviewError(f"正式档案来源文件缺失或不在data目录：{relative}")
    return path


def chinese_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        return (digits.get(left, 1) if left else 1) * 10 + digits.get(right, 0)
    return digits.get(value)


def board_for_title(title: str) -> str:
    matches = [label for label in BOARD_TITLES if label in title]
    matches.extend(alias for alias in BOARD_ALIASES if alias in title)
    matches = sorted(set(matches), key=len, reverse=True)
    if not matches:
        raise ReviewError(f"S21标题中没有已核对版型：{title}")
    canonical = BOARD_ALIASES.get(matches[0], matches[0])
    return BOARD_TITLES[canonical]


def title_number(title: str, pattern: str) -> int | None:
    match = re.search(pattern, title)
    return chinese_number(match.group(1)) if match else None


def event_winner(events: list[dict]) -> tuple[str | None, list[dict]]:
    direct = [event for event in events if event["action"] == "game_end"
              and event["state"] == "performed"
              and event["status"] in {"text_explicit", "visual_explicit", "unique_deduction"}]
    values = {normalize_winner(event.get("result")) for event in direct}
    values.discard(None)
    if len(values) == 1 and all(normalize_winner(event.get("result")) in values for event in direct):
        return next(iter(values)), []
    if len(values) > 1 or direct:
        return None, [{"event_id": event["event_id"], "reason": "explicit end result is missing or conflicting; winner kept unknown"}
                      for event in direct]
    return None, []


def normalize_winner(value: str | None) -> str | None:
    if value in {"good", "werewolf", "third_party", "draw"}:
        return value
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", "", value)
    if re.search(r"(?:不是|并非)(?:好人|狼人|狼队|狼阵营)", text):
        return None
    good = bool(re.search(r"好人(?:阵营)?(?:获胜|胜利)", text))
    wolf = bool(re.search(
        r"(?:狼人(?:阵营)?|狼队|狼阵营)(?:屠神|屠民|屠城|绑票|拍刀(?:成功(?:并)?)?)?(?:获胜|胜利)", text))
    if good == wolf:
        return None
    return "good" if good else "werewolf"


def approved_identity_and_phase(entry: dict, *, root: Path = ROOT,
                                approvals: dict | None = None) -> tuple[dict, dict, dict]:
    """Rebuild from the source-bound spec and require the existing reviewed files to match."""
    bvid = entry["bvid"]
    identity_path = REVIEW_DIR / bvid / "identity.reviewed.json"
    phase_path = REVIEW_DIR / bvid / "phase.reviewed.json"
    spec_path = PHASE_DIR / f"{bvid}.json"
    if not (root / identity_path).is_file() or not (root / phase_path).is_file() or not (root / spec_path).is_file():
        raise ReviewError(f"{bvid}: 核实身份、phase记录或审定spec缺失")
    identity = read_json(root, identity_path)
    if (identity.get("season") != "S21" or
            any(identity.get(key) != entry.get(key) for key in ("bvid", "cid", "page"))):
        raise ReviewError(f"{bvid}: identity.reviewed BV/CID/P不匹配")
    if identity.get("review", {}).get("status") != "ai_visual_checked":
        raise ReviewError(f"{bvid}: identity.reviewed不是已核视觉身份记录")
    if sorted(seat.get("seat") for seat in identity.get("seats", [])) != list(range(1, 13)):
        raise ReviewError(f"{bvid}: 已核身份没有完整12席")
    identity_review = identity["review"]
    for path_key, hash_key in (("visual_review_path", "visual_review_sha256"),
                               ("primary_corrections_path", "primary_corrections_sha256")):
        relative = identity_review.get(path_key)
        expected = identity_review.get(hash_key)
        if relative and expected and digest(root, relative) != expected:
            raise ReviewError(f"{bvid}: identity.reviewed来源已变化：{relative}")
    for relative, expected in identity_review.get("name_map_paths", {}).items():
        if digest(root, relative) != expected:
            raise ReviewError(f"{bvid}: identity.reviewed姓名映射来源已变化：{relative}")

    approvals = approvals if approvals is not None else read_json(root, PHASE_AUDIT)["items"]
    approval = approvals.get(bvid)
    if approval is None:
        raise ReviewError(f"{bvid}: 缺少primary phase approval")
    if digest(root, spec_path) != approval.get("spec_sha256"):
        raise ReviewError(f"{bvid}: primary phase approval已过期")

    # phase_review.build performs the existing literal-source and identity binding checks.
    old_root = phase_review.ROOT
    phase_review.ROOT = root
    try:
        reviewed = phase_review.build(read_json(root, spec_path))
    finally:
        phase_review.ROOT = old_root
    reviewed["primary_audit"] = approval
    saved = read_json(root, phase_path)
    if saved != reviewed:
        raise ReviewError(f"{bvid}: phase.reviewed与当前approved spec/identity/transcript不一致")
    return identity, reviewed, {"identity": identity_path.as_posix(), "phase": phase_path.as_posix(),
                                "spec": spec_path.as_posix(), "approval": approval}


def source_files(entry: dict, reviewed: dict, *, root: Path = ROOT) -> list[dict]:
    bvid, cid, page = entry["bvid"], entry["cid"], entry["page"]
    key = f"{bvid}:{cid}"
    related = entry.get("related_sources", {})
    # The exact reviewed transcript source is sufficient for this adapter; audio remains untouched.
    hashes = entry.get("source_hashes", {})
    origin = entry.get("selected_transcript_origin")
    selected_original = reviewed["source"]["original_path"]
    if origin == "platform_original_chinese_subtitle":
        expected = related.get("platform_raw_chinese_subtitle_path")
        if not expected or selected_original != expected or entry.get("selected_source_path") != expected:
            raise ReviewError(f"{bvid}: 原字幕与phase来源的BV/CID/P绑定不一致")
        if hashes.get("selected_source_sha256") != reviewed["source"].get("original_sha256"):
            raise ReviewError(f"{bvid}: 原字幕SHA与phase来源不一致")
        role, relative, kind = "subtitle", expected, "subtitle"
    elif origin == "local_light_review":
        raw_asr = related.get("original_transcript_path")
        if not raw_asr:
            raise ReviewError(f"{bvid}: 本地ASR没有原始转写文件")
        if reviewed["source"].get("original_path") != entry.get("selected_source_path"):
            raise ReviewError(f"{bvid}: 轻校对ASR路径与phase来源不一致")
        if reviewed["source"]["original_sha256"] != hashes.get("selected_source_sha256"):
            raise ReviewError(f"{bvid}: 轻校对ASR来源SHA不匹配")
        corrections = related.get("light_review_corrections_path")
        if not corrections or digest(root, corrections) != hashes.get("light_review_corrections_sha256"):
            raise ReviewError(f"{bvid}: ASR轻校对修订来源SHA不匹配")
        checked_data_file(root, raw_asr)
        raw_value = read_json(root, raw_asr)
        raw_source = raw_value.get("source", {})
        if any(raw_source.get(field) != entry.get(field) for field in ("bvid", "cid", "page")):
            raise ReviewError(f"{bvid}: 原始ASR不属于当前BV/CID/P")
        if (hashes.get("original_transcript_sha256") != digest(root, raw_asr)
                or raw_source.get("audio_sha256") != hashes.get("audio_sha256")):
            raise ReviewError(f"{bvid}: 原始ASR或音频来源SHA不匹配")
        # The reviewed light-copy remains in supplemental provenance; the formal file points to its same-media ASR input.
        role, relative, kind = "transcript", raw_asr, "asr"
    else:
        raise ReviewError(f"{bvid}: 未识别的S21转写来源类型：{origin}")
    checked_data_file(root, relative)
    return [{"role": role, "path": Path(relative).as_posix(), "kind": kind,
             "platform": "bilibili", "external_key": key}]


def role_faction(board: str, role: str | None, rules: dict) -> str | None:
    """Use only S21-specific faction evidence; other boards retain unknown factions."""
    if board != "s21_guile_realm" or role is None:
        return None
    board_evidence = rules["boards"].get("诡术之境", {})
    if board_evidence.get("formal_status") != "S21-specific official image verified":
        return None
    for faction_name, roles in board_evidence.get("factions", {}).items():
        for configured in roles:
            if configured.split("×", 1)[0] == role:
                return "werewolf" if faction_name == "狼人阵营" else "good"
    return None


def _event_targets(event: dict, *, actual_first: bool = False) -> list:
    primary = event.get("targets") or []
    actual = event.get("actual_targets")
    if actual_first and actual is not None:
        return actual
    return primary


def _one_target(event: dict, values: list | None = None) -> list | None:
    values = _event_targets(event) if values is None else values
    return values if len(values) == 1 else None


def map_phase_event(source: dict) -> tuple[str, int, dict] | tuple[None, None, str]:
    """Map one explicit source event only when the fixed slot can retain it exactly."""
    phase, number, action = source.get("phase"), source.get("round"), source.get("action")
    if phase not in {"night", "day"} or type(number) is not int:
        return None, None, "no formal night/day round slot; retained in supplemental"
    if source.get("state") not in {"performed", "pass", "forbidden", "not_applicable"}:
        return None, None, "source action state is unknown; retained in supplemental"
    if source.get("status") not in {"text_explicit", "visual_explicit", "unique_deduction"}:
        return None, None, "source status is unknown; retained in supplemental"
    actor = source.get("actor")
    targets = _event_targets(source)
    result = None
    slot, formal_action = None, None

    if source["state"] == "pass":
        pass_slots = {
            ("night", "wolf_attack"): "wolf_attack", ("night", "guard"): "guard",
            ("night", "save"): "witch_save", ("night", "poison"): "witch_poison",
            ("night", "investigate"): "seer_check", ("night", "learn"): "mechanical_action",
            ("night", "dream"): "dreamer_action", ("night", "dance"): "dancer_dance",
            ("night", "choose_model"): "mixed_blood_model",
            ("day", "self_destruct"): "self_destruct",
        }
        slot = pass_slots.get((phase, action))
        if phase == "day" and action == "shoot":
            slot = {"猎人": "hunter_shot", "狼王": "wolf_king_shot", "机械狼": "mechanical_day_skill"}.get(source.get("actor_physical_role"))
        formal_action = "pass" if slot else None
    elif source["state"] in {"forbidden", "not_applicable"}:
        unavailable_slots = {
            ("night", "wolf_attack"): "wolf_attack", ("night", "guard"): "guard",
            ("night", "save"): "witch_save", ("night", "poison"): "witch_poison",
            ("night", "investigate"): "seer_check", ("night", "learn"): "mechanical_action",
        }
        slot = unavailable_slots.get((phase, action))
        if phase == "day" and action == "shoot":
            slot = {"猎人": "hunter_shot", "狼王": "wolf_king_shot", "机械狼": "mechanical_day_skill"}.get(source.get("actor_physical_role"))
        formal_action = "unavailable" if slot else None
    elif phase == "night":
        if action == "night_deaths":
            slot = "night_deaths"
            if source.get("result") == "peaceful" or (
                    isinstance(source.get("result"), str) and
                    re.search(r"平安夜|无(?:人)?(?:夜间)?死亡|无夜死", source["result"])):
                formal_action, targets, actor = "peaceful", [], None
            elif targets:
                formal_action, actor = "die", None
            else:
                return None, None, "no explicit death target/result for the formal slot"
            phase = "day"
        elif action == "wolf_attack": slot, formal_action = "wolf_attack", "attack"
        elif action == "guard": slot, formal_action = "guard", "guard"
        elif action == "save": slot, formal_action = "witch_save", "save"
        elif action == "poison": slot, formal_action = "witch_poison", "poison"
        elif action == "investigate":
            slot, formal_action, result = "seer_check", "check", source.get("result")
        elif action == "learn": slot, formal_action = "mechanical_action", "learn"
        elif action == "dream": slot, formal_action = "dreamer_action", "dream"
        elif action == "dance": slot, formal_action = "dancer_dance", "dance"
        elif action == "choose_model": slot, formal_action = "mixed_blood_model", "choose"
        elif action == "exchange":
            role = source.get("actor_physical_role")
            if role == "魔术师": slot, formal_action = "magician_exchange", "exchange"
            elif role == "诡术师": slot, formal_action = "guile_exchange", "exchange"
        elif action == "extra_attack": slot, formal_action = "treasure_extra_attack", "attack"
        elif action == "puppet": slot, formal_action = "puppet_select", "select"
        elif action == "wear_mask": slot, formal_action = "masquerade_mask", "give_mask"
        elif action == "steal_card":
            slot, formal_action = "s21_treasure_action", "choose"
            result = source.get("details", {}).get("selected_identity")
            targets = []
    elif phase == "day":
        if action in {"sheriff_signup", "sheriff_candidates"}:
            slot, formal_action = "sheriff_candidates", "register"
        elif action == "sheriff_elected":
            slot, formal_action = "sheriff_result", "elected"
            target = _one_target(source)
            if target is None and type(actor) is int:
                target = [actor]
            targets, actor = target, None
        elif action == "sheriff_deferred": slot, formal_action = "sheriff_result", "deferred"
        elif action in {"night_deaths", "death_announcement"}:
            slot = "night_deaths"
            if source.get("result") == "peaceful" or (
                    isinstance(source.get("result"), str) and
                    re.search(r"平安夜|无(?:人)?(?:夜间)?死亡|无夜死", source["result"])):
                formal_action, targets, actor = "peaceful", [], None
            elif targets:
                formal_action, actor = "die", None
            else:
                return None, None, "no explicit death target/result for the formal slot"
        elif action == "badge_transfer": slot, formal_action = "badge", "transfer"
        elif action in {"badge_lost", "badge_destroyed"}: slot, formal_action = "badge", "none"
        elif action == "exile":
            slot, formal_action = "exile_result", "exile"
            actual = source.get("details", {}).get("actual_exile_target")
            if type(actual) is int:
                targets = [actual]
            else:
                targets = _event_targets(source, actual_first=True)
        elif action == "no_exile": slot, formal_action = "exile_result", "none"
        elif action == "self_destruct": slot, formal_action = "self_destruct", "self_destruct"
        elif action == "shoot":
            slot = {"猎人": "hunter_shot", "狼王": "wolf_king_shot", "机械狼": "mechanical_day_skill"}.get(source.get("actor_physical_role"))
            formal_action = "shoot" if slot else None
        elif action == "reveal":
            role = source.get("actor_physical_role")
            slot, formal_action = ("white_god_reveal", "reveal") if role == "白神" else ("s21_reveal", "reveal")
    if slot is None or formal_action is None:
        return None, None, "no season-neutral formal slot; retained in supplemental"

    if source["state"] in {"forbidden", "not_applicable"}:
        targets = []
    if formal_action == "peaceful":
        targets = []
    elif slot == "night_deaths" and formal_action == "die":
        targets = sorted(targets)
    if formal_action in {"attack", "guard", "save", "poison", "check", "learn", "dream", "choose", "select", "give_mask", "shoot", "transfer", "elected", "exile", "dance", "exchange"}:
        required = {"dance": 3, "exchange": 2}.get(formal_action, 1)
        if formal_action == "choose" and slot == "s21_treasure_action":
            required = 0
        if len(targets) != required:
            return None, None, f"target count does not fit {slot}/{formal_action}; retained in supplemental"
    if source["state"] in {"pass", "forbidden", "not_applicable"}:
        targets = []
    if slot == "self_destruct" and source.get("actor_physical_role") is not None:
        role = source["actor_physical_role"]
        if role == "机械狼" or role not in game_records.WOLF_ROLES:
            return None, None, "shared formal validator cannot represent self-destruct for this verified role"
    mapped = game_records.empty_event(slot)
    mapped.update(action=formal_action, actor=actor, targets=list(targets or []), result=result)
    return phase, number, mapped


def _explicit_targets(value, key: str) -> list[int] | None:
    raw = value.get(key)
    if isinstance(raw, int) and not isinstance(raw, bool):
        raw = [raw]
    if not isinstance(raw, list) or any(type(seat) is not int or not 1 <= seat <= 12 for seat in raw):
        return None
    if len(raw) != len(set(raw)):
        return None
    return sorted(raw)


def voting_facts(slug: str, reviewed: dict) -> tuple[dict, list[dict]]:
    ballots, issues = [], []
    counters = Counter()
    days: dict[int, dict] = {}

    def day_status(day: int):
        return days.setdefault(day, {"day": day, "sheriff": "unknown", "exile": "unknown"})

    for original in reviewed.get("ballots", []):
        kind = original["type"]
        day = original.get("day")
        if type(day) is int:
            d = day_status(day)
            d["sheriff" if kind == "sheriff" else "exile"] = "recorded"
        counters[day, kind] += 1
        eligible = original.get("eligible_voters")
        candidates = original.get("candidate_seats")
        votes = []
        for row in original.get("votes", []):
            voter, target, state = row["voter"], row["target"], row["state"]
            # The shared schema has no separate default-abstention code; the original state remains in supplemental.
            normalized_state = {"cast": "cast", "abstained": "abstained",
                                "default_abstention": "abstained"}[state]
            votes.append({"voter": voter, "target": target, "state": normalized_state})
        unrecorded = sorted(set(eligible) - {vote["voter"] for vote in votes}) if eligible is not None else None
        complete = (original.get("completeness") == "complete_for_proven_eligible_set"
                    and eligible is not None and not unrecorded)
        stage = original.get("stage", "unknown")
        stage = "revote" if stage in {"revote", "prince_revote", "prince_repeat"} else stage
        if stage not in {"initial", "pk", "revote", "unknown"}:
            stage = "unknown"
        outcome = original.get("outcome", {})
        winner_values = []
        for key in (("elected", "winner") if kind == "sheriff" else ("exiled", "winner")):
            if key in outcome:
                value = _explicit_targets({"x": outcome[key]}, "x")
                if value is not None and len(value) == 1:
                    winner_values.extend(value)
                else:
                    issues.append({"ballot_id": original["ballot_id"], "reason": f"{key} result is not a single directly recorded seat"})
        winner_values = sorted(set(winner_values))
        winner = winner_values[0] if len(winner_values) == 1 else None
        tie = None
        for key in ("tied_candidates", "tie_candidates", "tie"):
            if key in outcome:
                tie = _explicit_targets({"x": outcome[key]}, "x")
                if tie is None:
                    issues.append({"ballot_id": original["ballot_id"], "reason": f"{key} could not be represented as a seat list"})
                break
        if tie is None:
            tie = []
        if winner_values and len(winner_values) > 1:
            issues.append({"ballot_id": original["ballot_id"], "reason": "conflicting explicit winner fields; winner left unknown"})
            winner = None
        ballots.append({
            "id": original["ballot_id"], "day": day, "kind": kind,
            "number": counters[day, kind], "stage": stage,
            "status": "complete" if complete else "partial", "candidates": candidates,
            "eligible_voters": eligible, "tied_candidates": tie,
            "winner": winner, "unrecorded_voters": unrecorded, "votes": votes,
        })

    registrations = []
    for event in reviewed.get("events", []):
        if event["state"] != "performed" or event["action"] not in {"sheriff_signup", "sheriff_candidates"}:
            continue
        details = event.get("details", {})
        on_police = _explicit_targets({"x": event.get("targets") or []}, "x")
        off_police = _explicit_targets({"x": details.get("off_sheriff_seats")}, "x") if "off_sheriff_seats" in details else None
        complete_claim = details.get("initial_signup_complete") is True
        if on_police is None:
            issues.append({"event_id": event["event_id"], "reason": "registration has an invalid candidate set"})
            continue
        if off_police is None and complete_claim:
            off_police = sorted(set(range(1, 13)) - set(on_police))
        if (off_police is None or set(on_police) & set(off_police)
                or set(on_police + off_police) != set(range(1, 13))):
            issues.append({"event_id": event["event_id"], "reason": "registration does not prove a complete on/off-sheriff partition"})
            continue
        registrations.append({"id": event["event_id"], "day": event.get("round"),
                              "on_police": on_police, "off_police": off_police})
        if type(event.get("round")) is int:
            day_status(event["round"])

    for event in reviewed.get("events", []):
        if (event["phase"] != "day" or event["state"] != "performed" or
                event["action"] not in {"sheriff_deferred", "badge_lost", "no_exile", "self_destruct"}):
            continue
        day = event.get("round")
        if type(day) is not int:
            continue
        d = day_status(day)
        if event["action"] == "sheriff_deferred" and d["sheriff"] == "unknown":
            d["sheriff"] = "deferred"
        elif event["action"] == "badge_lost" and d["sheriff"] == "unknown":
            d["sheriff"] = "badge_lost"
        elif event["action"] == "no_exile" and d["exile"] == "unknown":
            d["exile"] = "none"
        elif event["action"] == "self_destruct" and event.get("details", {}).get("ends_day") is True and d["exile"] == "unknown":
            d["exile"] = "interrupted_self_destruct"

    facts = {"schema_version": 1, "game_slug": slug, "registrations": registrations,
             "ballots": ballots, "interruptions": [], "days": [days[d] for d in sorted(days)]}
    return facts, issues


def endgame_sidecar(slug: str, reviewed: dict) -> tuple[dict, list[dict]]:
    phases, issues = [], []
    for event in reviewed.get("events", []):
        if event.get("action") != "endgame_attack":
            continue
        if event.get("status") not in {"text_explicit", "visual_explicit", "unique_deduction"} or event.get("state") != "performed":
            issues.append({"event_id": event["event_id"], "reason": "endgame action is not directly explicit"})
            continue
        details = event.get("details", {})
        targets = _explicit_targets({"x": details.get("declared_targets")}, "x") if "declared_targets" in details else None
        event_targets = _explicit_targets({"x": event.get("targets") or []}, "x")
        if targets is None:
            targets = event_targets or []
        elif event_targets and event_targets != targets:
            issues.append({"event_id": event["event_id"], "reason": "phase targets conflict with declared_targets; target set left empty"})
            targets = []
        actor = event.get("actor")
        if details.get("actor_identity_unresolved") is True:
            actor = None
        result = event.get("result")
        result = result if result in {"werewolf_win", "good_win", "unknown"} else "unknown"
        day = event.get("round")
        if type(day) is not int:
            day = details.get("day") if type(details.get("day")) is int else None
        evidence = []
        for ref in event.get("evidence", []):
            evidence.append({"path": ref["original_source_path"], "start_ms": ref["start_ms"],
                             "end_ms": ref["end_ms"], "quote": ref["quote"]})
        phases.append({"kind": "wolf_rush", "day": day, "actor": actor,
                       "declared_targets": targets, "result": result,
                       "note": event.get("note") or "S21 primary-reviewed endgame attack; unspecified settlement remains unknown.",
                       "evidence": evidence})
    sidecar = {"schema_version": 1, "game_slug": slug, "phases": phases,
               "source_sha256": reviewed["source"]["original_sha256"]}
    endgame_records.validate(sidecar)
    return sidecar, issues


def build_records(entry: dict, identity: dict, reviewed: dict, binding: dict, *, root: Path = ROOT) -> dict:
    bvid, cid, page = entry["bvid"], entry["cid"], entry["page"]
    board = board_for_title(entry["title"])
    rules = read_json(root, Path("config/S21_formal_rules.json"))
    date_match = re.match(r"^(20\d{2})(\d{2})(\d{2})", entry["title"])
    date = "-".join(date_match.groups()) if date_match else None
    if date and entry.get("date_candidate") and date != entry["date_candidate"]:
        date = None
    game_number = title_number(entry["title"], r"第\s*([0-9]+|[一二两三四五六七八九十]+)\s*局")
    episode = title_number(entry["title"], r"第\s*([0-9]+|[一二两三四五六七八九十]+)\s*期")
    day_in_episode = title_number(entry["title"], r"Day[-\s]*(\d+)")
    slug = f"bili-{bvid}-p{page:02d}-cid{cid}"
    files = source_files(entry, reviewed, root=root)
    seats = []
    for source_seat in sorted(identity["seats"], key=lambda item: item["seat"]):
        role = source_seat.get("role")
        if role in UNKNOWN_ROLES:
            role = None
        name = source_seat.get("name")
        if name in UNKNOWN_ROLES:
            name = None
        seats.append({"seat": source_seat["seat"], "name": name, "role": role,
                      "faction": role_faction(board, role, rules),
                      "learning_target": None, "learned_role": None})
    roster = list(dict.fromkeys(seat["name"] for seat in seats if seat["name"] is not None))

    rounds_by_number = {}
    for event in reviewed.get("events", []):
        number = event.get("round")
        if event.get("phase") in {"night", "day"} and type(number) is int:
            rounds_by_number.setdefault(number, {})
    max_round = max(rounds_by_number, default=0)
    template = game_records.template(board)
    rounds = [{"number": number,
               "night": [game_records.empty_event(slot["code"]) for slot in template["night_slots"]],
               "day": [game_records.empty_event(slot["code"]) for slot in template["day_slots"]]}
              for number in range(1, max_round + 1)]
    placements = {}
    unmapped = []
    for event in reviewed.get("events", []):
        mapped_phase, number, mapped = map_phase_event(event)
        if mapped_phase is None:
            if event.get("phase") in {"night", "day"}:
                unmapped.append({"event_id": event["event_id"], "phase": event["phase"],
                                 "round": event.get("round"), "action": event["action"],
                                 "reason": mapped})
            continue
        placements.setdefault((mapped_phase, number, mapped["slot"]), []).append((event, mapped))
    for key, rows in placements.items():
        mapped_phase, number, slot = key
        if len(rows) > 1 and len({json.dumps(mapped, ensure_ascii=False, sort_keys=True) for _, mapped in rows}) == 1:
            event, mapped = rows[0]
            phase_events = rounds[number - 1][mapped_phase]
            slot_position = next(i for i, existing in enumerate(phase_events) if existing["slot"] == slot)
            phase_events[slot_position] = mapped
            for duplicate, _ in rows[1:]:
                unmapped.append({"event_id": duplicate["event_id"], "phase": duplicate["phase"],
                                 "round": number, "action": duplicate["action"],
                                 "reason": f"same formal fact as {event['event_id']}; full source detail retained in supplemental"})
            continue
        if len(rows) != 1:
            for event, _ in rows:
                unmapped.append({"event_id": event["event_id"], "phase": event["phase"],
                                 "round": number, "action": event["action"],
                                 "reason": f"{len(rows)} reviewed events compete for {mapped_phase}/{slot}; all retained outside the formal slot"})
            continue
        event, mapped = rows[0]
        phase_events = rounds[number - 1][mapped_phase]
        slot_position = next(i for i, existing in enumerate(phase_events) if existing["slot"] == slot)
        phase_events[slot_position] = mapped

    winner, winner_issues = event_winner(reviewed.get("events", []))
    unmapped.extend({"event_id": item.get("event_id"), "phase": "endgame", "action": "game_end",
                     "reason": item["reason"]} for item in winner_issues)
    dossier = {"slug": slug, "season": "S21", "date": date,
               "phase": entry.get("phase_candidate") if entry.get("phase_candidate") in {"regular", "finals_week"} else None,
               "episode": episode, "day_in_episode": day_in_episode, "game_number": game_number,
               "board": board, "winner": winner, "roster": roster, "commentators": [], "referee": None,
               "seats": seats, "rounds": rounds, "files": files}
    voting, voting_issues = voting_facts(slug, reviewed)
    unmapped.extend({"phase": "ballot", **item} for item in voting_issues)
    endgame, endgame_issues = endgame_sidecar(slug, reviewed)
    unmapped.extend({"phase": "endgame", **item} for item in endgame_issues)
    supplemental = {
        "schema_version": 1, "season": "S21", "bvid": bvid, "cid": cid, "page": page,
        "source_title": entry["title"], "source_phase_candidate": entry.get("phase_candidate"),
        "formal_game_count_note": "A dossier is one source-bound media record. The 122-item S21 media scope is not a confirmed formal game count.",
        "rule_status": "Only S21-specific evidence is used. Board slots are archive fields; unknown rule and wake-order details remain unknown.",
        "source_binding": {
            "identity_reviewed_path": binding["identity"],
            "identity_reviewed_sha256": digest(root, binding["identity"]),
            "phase_reviewed_path": binding["phase"],
            "phase_reviewed_sha256": digest(root, binding["phase"]),
            "phase_spec_path": binding["spec"],
            "phase_spec_sha256": digest(root, binding["spec"]),
            "selected_transcript_path": reviewed["source"]["selected_path"],
            "selected_transcript_sha256": reviewed["source"]["selected_sha256"],
            "original_transcript_path": reviewed["source"]["original_path"],
            "original_transcript_sha256": reviewed["source"]["original_sha256"],
            "phase_approval": binding["approval"],
        },
        "formal_slot_coverage": {
            "mapped_events": sum(event["action"] != "unknown" for round_ in rounds for phase_name in ("night", "day") for event in round_[phase_name]),
            "reviewed_phase_events": len(reviewed.get("events", [])),
            "unmapped_events": len(unmapped),
            "placeholder_rounds": [number for number in range(1, max_round + 1) if number not in rounds_by_number],
        },
        "unmapped": unmapped,
        "phase_reviewed": reviewed,
        "note": "正式轮次只映射能被固定slot表达且由直接文字/画面确认的事件；原phase全部细节、唯一推断、未知项与slot冲突均留在phase_reviewed及unmapped。投票只写voting.json，不复制到game_rounds。",
    }
    game_records.validate(dossier, check_files=False, allow_incomplete=True)
    voting_records.validate(voting)
    endgame_records.validate(endgame)
    folder_name = f"{date or 'date-unknown'}_{f'g{game_number:02d}' if game_number else 'gunknown'}_{bvid}"
    folder = OUTPUT / folder_name
    return {"entry": entry, "slug": slug, "dossier": dossier, "voting": voting,
            "endgame": endgame, "supplemental": supplemental,
            "folder": folder.as_posix(), "unmapped_count": len(unmapped)}


def selected_entries(*, root: Path = ROOT, bvids: list[str] | None = None) -> list[dict]:
    index = read_json(root, INDEX)
    scope = read_json(root, SCOPE)
    all_entries = index["entries"]
    by_id = {entry["bvid"]: entry for entry in all_entries}
    excluded = set(scope.get("excluded_bvids", []))
    selected = list(dict.fromkeys(bvids or []))
    if selected:
        unknown = [bvid for bvid in selected if bvid not in by_id]
        if unknown:
            raise ReviewError(f"S21媒体索引不存在这些BVID：{', '.join(unknown)}")
        if excluded.intersection(selected):
            raise ReviewError(f"用户已排除的媒体不能生成正式对局：{', '.join(sorted(excluded.intersection(selected)))}")
        entries = [by_id[bvid] for bvid in selected]
    else:
        entries = all_entries
    for entry in entries:
        if entry["bvid"] in excluded or entry.get("phase_candidate") not in {"regular", "finals_week"}:
            raise ReviewError(f"{entry['bvid']}: 媒体不在S21正赛/决赛周正式导入范围")
    return entries


def build_selected(*, root: Path = ROOT, bvids: list[str] | None = None) -> list[dict]:
    entries = selected_entries(root=root, bvids=bvids)
    approvals = read_json(root, PHASE_AUDIT)["items"]
    results = []
    for entry in entries:
        identity, reviewed, binding = approved_identity_and_phase(entry, root=root, approvals=approvals)
        results.append(build_records(entry, identity, reviewed, binding, root=root))
    return results


def write_prepared(items: list[dict], *, root: Path = ROOT) -> None:
    for item in items:
        folder = root / item["folder"]
        for filename, key in (("dossier.json", "dossier"), ("voting.json", "voting"),
                              ("endgame.json", "endgame"), ("supplemental.json", "supplemental")):
            save_json(folder / filename, item[key])


def load_prepared(items: list[dict], *, root: Path = ROOT) -> list[dict]:
    for item in items:
        folder = root / item["folder"]
        for filename, key in (("dossier.json", "dossier"), ("voting.json", "voting"),
                              ("endgame.json", "endgame"), ("supplemental.json", "supplemental")):
            path = folder / filename
            if not path.is_file():
                raise ReviewError(f"{item['entry']['bvid']}: --import-db需要先执行--prepare；缺少{path.relative_to(root).as_posix()}")
            if read_json(root, path.relative_to(root)) != item[key]:
                raise ReviewError(f"{item['entry']['bvid']}: 已准备的{filename}与当前approved输入不一致，请先重新prepare")
    return items


def ensure_source(conn, entry: dict) -> None:
    external_key = f"{entry['bvid']}:{entry['cid']}"
    source = conn.execute("SELECT id,metadata FROM sources WHERE platform='bilibili' AND external_key=%s",
                          (external_key,)).fetchone()
    metadata = {key: entry[key] for key in ("bvid", "cid", "page")}
    if source:
        if any(source["metadata"].get(key) not in (None, value) for key, value in metadata.items()):
            raise ReviewError(f"{entry['bvid']}: 已登记source的BV/CID/P不一致")
        return
    conn.execute("INSERT INTO sources(platform,external_key,url,title,metadata) VALUES(%s,%s,%s,%s,%s)",
                 ("bilibili", external_key,
                  f"https://www.bilibili.com/video/{entry['bvid']}/?p={entry['page']}",
                  entry["title"], Jsonb(metadata)))


def ensure_season(conn) -> None:
    season = read_json(ROOT, "config/seasons.json")["seasons"]["S21"]
    conn.execute("INSERT INTO seasons(code,name,metadata) VALUES(%s,%s,%s) ON CONFLICT(code) DO NOTHING",
                 ("S21", season["name"], Jsonb({"origin": "s21_formal_import",
                                                  "collection_id": season["collection_id"]})))


def import_batch(items: list[dict]) -> dict:
    counts = Counter()
    with database.connect() as conn:
        ensure_season(conn)
        for item in items:
            ensure_source(conn, item["entry"])
            game_receipt = game_records.import_game(item["dossier"], allow_incomplete=True, conn=conn)
            vote_receipt = voting_records.import_voting(item["voting"], conn=conn)
            endgame_receipt = endgame_records.import_endgame(item["endgame"], conn=conn)
            game = conn.execute("SELECT id FROM games WHERE slug=%s", (item["slug"],)).fetchone()
            if game is None:
                raise ReviewError(f"{item['slug']}: formal game import did not read back")
            reviewed = item["supplemental"]["source_binding"]["phase_reviewed_path"]
            source_hash = item["supplemental"]["source_binding"]["phase_reviewed_sha256"]
            for key, annotation_type, payload in (
                ("s21_phase_review", "supplemental_observations", item["supplemental"]),
                ("s21_endgame", "endgame", item["endgame"]),
            ):
                conn.execute("""INSERT INTO game_formal_annotations
                    (game_id,annotation_key,annotation_type,source_path,source_sha256,payload)
                    VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(game_id,annotation_key) DO UPDATE SET
                    annotation_type=EXCLUDED.annotation_type,source_path=EXCLUDED.source_path,
                    source_sha256=EXCLUDED.source_sha256,payload=EXCLUDED.payload,recorded_at=now()""",
                    (game["id"], key, annotation_type, reviewed, source_hash, Jsonb(payload)))
            counts["games"] += 1
            counts["ballots"] += vote_receipt["ballots"]
            counts["choices"] += vote_receipt["choices"]
            counts["endgame_phases"] += endgame_receipt["phases"]
            counts["formal_rounds"] += game_receipt["rounds"]
    return {"database_write": True, **dict(counts)}


def summary(items: list[dict]) -> dict:
    board_counts = Counter(item["dossier"]["board"] for item in items)
    return {
        "season": "S21", "media_reviewed": len(items),
        "formal_dossiers": len(items), "formal_game_count": None,
        "formal_game_count_note": "media_reviewed is a media count, not a confirmed formal game count",
        "board_counts": dict(sorted(board_counts.items())),
        "known_names": sum(seat["name"] is not None for item in items for seat in item["dossier"]["seats"]),
        "known_roles": sum(seat["role"] is not None for item in items for seat in item["dossier"]["seats"]),
        "known_factions": sum(seat["faction"] is not None for item in items for seat in item["dossier"]["seats"]),
        "formal_rounds": sum(len(item["dossier"]["rounds"]) for item in items),
        "mapped_events": sum(item["supplemental"]["formal_slot_coverage"]["mapped_events"] for item in items),
        "unmapped_events": sum(item["unmapped_count"] for item in items),
        "ballots": sum(len(item["voting"]["ballots"]) for item in items),
        "explicit_phase_gaps": sum(len(item["supplemental"]["phase_reviewed"]["coverage"]["gaps"]) for item in items),
        "unknown_winners": sum(item["dossier"]["winner"] is None for item in items),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="默认：只在内存校验，不写文件或数据库")
    mode.add_argument("--prepare", action="store_true", help="写入data/games/S21正式候选文件，不写数据库")
    mode.add_argument("--import-db", action="store_true", help="导入已prepare的候选；dossier、票型、端局和旁证同事务")
    parser.add_argument("--bvid", action="append", help="只处理指定BVID，可重复传入")
    args = parser.parse_args(argv)
    items = build_selected(bvids=args.bvid)
    result = summary(items)
    if args.prepare:
        write_prepared(items)
        result["prepared_paths"] = [item["folder"] for item in items]
        result["database_write"] = False
    elif args.import_db:
        load_prepared(items)
        database.migrate()
        result["database"] = import_batch(items)
    else:
        result["database_write"] = False
        result["file_write"] = False
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
