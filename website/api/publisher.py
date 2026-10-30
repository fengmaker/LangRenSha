"""Build and atomically publish immutable public game snapshots."""

from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from scripts.game_time import display_time_text, phase_label
from website.api.game_presentation import (
    build_game_presentation, terminal_from_events, terminal_day_events,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_ROOT = Path(os.environ.get("MASTERS_SOURCE_ROOT", PACKAGE_ROOT))
PERSON_NAMESPACE = uuid.UUID("5a1e9a41-663d-4dcc-9ce6-f5e75e9efb18")
PUBLICATION_FORMAT_VERSION = 12
STATISTICS_VERSION = 2
BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")
EVENT_FIELDS = (
    "slot", "action", "actor", "targets", "result", "start_seat", "direction",
    "random_point", "speech_scope", "availability", "votes", "effects",
    "invalidated", "blocked_by_game_end",
)
EFFECT_FIELDS = ("kind", "intended_target", "dead_seat", "shield_actor")
VOTE_FIELDS = ("round", "voter", "target", "abstained")
REGISTRATION_FIELDS = ("id", "day", "on_police", "off_police")
BALLOT_FIELDS = (
    "id", "day", "kind", "number", "stage", "status", "candidates", "eligible_voters",
    "votes", "tied_candidates", "winner", "unrecorded_voters",
)
INTERRUPTION_FIELDS = ("id", "day", "actor", "reason", "ends_day")
DAY_FIELDS = ("day", "sheriff", "exile")
ENDGAME_FIELDS = ("kind", "day", "actor", "declared_targets", "result", "note")
ACTION_LABELS = {
    "guard": "执行守护", "attack": "执行击杀", "save": "使用解药", "poison": "使用毒药",
    "check": "执行查验", "learn": "学习身份", "can_shoot": "可以开枪", "cannot_shoot": "不能开枪",
    "carrying": "已带刀", "not_carrying": "未带刀", "shoot": "开枪", "self_destruct": "自爆",
    "die": "出局", "die_after_speech": "发言后出局", "suicide": "自杀出局", "disqualify": "DQ出局", "peaceful": "平安夜",
    "register": "登记上警", "elected": "当选警长", "deferred": "竞选延期", "continued": "继续竞选",
    "transfer": "移交警徽", "hold": "持有警徽", "order": "安排发言顺序", "exile": "被放逐",
    "vote": "投票", "not_held": "未举行投票", "none": "没有结果", "pass": "选择不行动",
    "unknown": "记录未知", "unavailable": "行动不可用", "not_eligible": "无投票资格",
    "forbidden": "该行动被禁止", "invalid_exchange": "交换无效", "trade": "选择交易",
    "betray": "选择背叛", "trade_betray": "分别选择交易和背叛", "betray_trade": "分别选择背叛和交易",
    "transform": "变换身份", "mask": "使用面具", "dance": "参与共舞", "win": "胜出",
}
S23_ACTION_LABELS = {
    "verify": "查验身份", "give_mask": "给予面具", "minority_dies": "少数方出局",
    "invalidated_by_dq": "最后一狼被DQ，狼刀失效", "mark": "标记", "hunt": "狩猎",
    "choose": "选择", "wolf": "狼人阵营", "good": "好人阵营", "clear_mark": "清除标记",
    "destroy": "销毁", "reveal": "翻牌", "speak": "发言", "clear": "清除",
    "kill": "猎杀", "attempt": "尝试发动", "surrender": "交牌", "no_death": "无人出局",
    "exchange": "交换", "dream": "摄梦", "swap": "交换",
}


class PublishError(ValueError):
    """A source snapshot cannot be safely published."""


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise PublishError("源 JSON 顶层必须是对象")
    return value, digest_bytes(raw)


def _logical_rules(root: Path, season: str) -> tuple[dict[str, str], dict[str, dict]]:
    from scripts.board_config import load_template
    from scripts.rule_config import load_formal_rules, load_scope

    config_dir = root / "config"
    scope_path = config_dir / "seasons.json"
    formal_path = config_dir / "game_rules.json"
    board_dir = config_dir / "board_templates"
    if not scope_path.is_file() or not formal_path.is_file() or not board_dir.is_dir():
        raise PublishError("缺少正式范围、正式规则或版型模板配置")
    _, scope_digest = _read_json(scope_path)
    _, formal_digest = _read_json(formal_path)
    scope = load_scope(season, root)
    formal = load_formal_rules(season, root)
    if scope.get("season") != season or formal.get("season") != season:
        raise PublishError("赛季范围配置不匹配")
    hashes = {
        f"config/{scope_path.name}": scope_digest,
        f"config/{formal_path.name}": formal_digest,
    }
    boards: dict[str, dict] = {}
    for path in sorted(board_dir.glob("*.json")):
        data, data_digest = _read_json(path)
        code = data.get("code")
        public_board = {"code": code, "name": data["name"]}
        for code in [code, *data.get("storage_variants", {})]:
            if not isinstance(code, str) or code in boards:
                raise PublishError("版型模板缺少唯一代码")
            boards[code] = load_template(code, root)
            boards[code]["_public_board"] = public_board
        hashes[f"config/board_templates/{path.name}"] = data_digest
    if not boards:
        raise PublishError("版型模板为空")
    return hashes, {"scope": scope, "formal": formal, "boards": boards}


def _bvid(dossier: dict) -> str:
    slug = dossier.get("slug")
    match = BVID_RE.search(slug) if isinstance(slug, str) else None
    if not match:
        raise PublishError("对局缺少可识别的视频编号")
    return match.group(0)


def _included(dossier: dict, scope: dict) -> bool:
    bvid = _bvid(dossier)
    return not (
        dossier.get("board") in scope.get("excluded_board_codes", [])
        or dossier.get("phase") in scope.get("excluded_phases", [])
        or dossier.get("date") in scope.get("excluded_dates", [])
        or bvid in scope.get("excluded_bvids", [])
        or (scope.get("retained_phases") and dossier.get("phase") not in scope["retained_phases"])
    )


def _pick(source: dict, fields: tuple[str, ...]) -> dict:
    return {key: source[key] for key in fields if key in source}


def _clean_ballot(ballot: dict, rule_defaults: set[tuple[str, int]]) -> dict:
    result = _pick(ballot, BALLOT_FIELDS)
    votes = []
    ballot_id = ballot.get("id")
    for vote in ballot.get("votes", []):
        cleaned = _pick(vote, ("voter", "target", "state"))
        if vote.get("state") == "abstained":
            source_basis = vote.get("basis")
            source_default = (
                isinstance(source_basis, str)
                and source_basis.strip() == (
                    "本轮票权由已核死亡及存活唯一确定；未播报投向按既有用户口径默认弃票"
                )
            )
            cleaned["basis"] = (
                "rule_default" if source_default or (ballot_id, vote.get("voter")) in rule_defaults
                else "abstained"
            )
        else:
            cleaned["basis"] = "recorded"
        votes.append(cleaned)
    result["votes"] = votes
    return result


def _rounds(dossier: dict, board: dict) -> list[dict]:
    labels = {
        phase: {slot["code"]: slot["label"] for slot in board.get(f"{phase}_slots", [])}
        for phase in ("night", "day")
    }
    result = []
    for round_ in dossier.get("rounds", []):
        number = round_.get("number")
        row = {"number": number}
        for phase in ("night", "day"):
            events = []
            for event in round_.get(phase, []):
                slot = event.get("slot")
                if slot not in labels[phase] and slot != "disqualification":
                    raise PublishError("事件槽位不在当前版型中")
                output = _pick(event, EVENT_FIELDS)
                if dossier.get("season") == "S23" and isinstance(output.get("result"), str):
                    output["result"] = re.sub(
                        r"逐人票型另见voting\.(?:reviewed|candidate)\.json",
                        "逐人票型见本页投票记录", output["result"],
                    )
                output["votes"] = [_pick(vote, VOTE_FIELDS) for vote in event.get("votes", [])]
                output["effects"] = [_pick(effect, EFFECT_FIELDS) for effect in event.get("effects", [])]
                output["slot_label"] = (
                    "DQ出局" if slot == "disqualification" else labels[phase][slot]
                )
                period = phase_label(number, phase)
                action = event.get("action")
                action_label = ACTION_LABELS.get(action, '记录动作 ' + str(action))
                if dossier.get("season") == "S23":
                    action_label = S23_ACTION_LABELS.get(action, action_label)
                description = f"{period}，{labels[phase][slot]}：{action_label}"
                actor = event.get("actor")
                if actor is not None:
                    description += f"；行动者 {actor} 号"
                targets = event.get("targets") or []
                if targets:
                    description += "；目标 " + "、".join(f"{target} 号" for target in targets)
                output["description"] = description
                events.append(output)
            row[phase] = events
        result.append(row)
    return result


def _terminal_from_dossier(dossier: dict) -> dict | None:
    try:
        return terminal_from_events(dossier)
    except ValueError as exc:
        raise PublishError(str(exc)) from exc


def _public_supplemental_events(supplemental: dict) -> list[dict]:
    """Expose only the confirmed DQ and surrender actions needed by the timeline."""
    public = []
    for row in supplemental.get("events", []):
        if not isinstance(row, dict) or type(row.get("round")) is not int:
            continue
        phase, source = row.get("phase"), row.get("event")
        if phase not in {"night", "day"} or not isinstance(source, dict):
            continue
        action = source.get("action")
        if action not in {"disqualify", "surrender"}:
            continue
        event = _pick(source, EVENT_FIELDS)
        event["supplemental"] = True
        if action == "disqualify":
            event["slot"] = "disqualification"
            targets = event.get("targets") or []
            seats = "、".join(f"{seat}号" for seat in targets)
            subject = seats or (f"{event['actor']}号" if type(event.get("actor")) is int else "玩家")
            event["result"] = "DQ裁定；与普通死亡结算分开记录。"
            event["description"] = f"{subject}被DQ出局；此裁定与普通死亡结算分开记录。"
            event["slot_label"] = "DQ出局"
        else:
            slot = event.get("slot")
            if slot is None:
                continue
            actor = event.get("actor")
            subject = f"{actor}号狼人" if type(actor) is int else "狼人"
            event["result"] = "交牌，对局结束。"
            event["description"] = f"{subject}选择交牌，对局结束。"
            event["slot_label"] = "狼人交牌"
        public.append({"round": row["round"], "phase": phase, "event": event})
    return public


def _display_inference_notes(presentation: dict) -> dict:
    for round_ in presentation.get("rounds", []):
        for phase in ("night", "day"):
            for event in round_.get(phase, []):
                if isinstance(event.get("inference_note"), str):
                    event["inference_note"] = display_time_text(event["inference_note"])
    terminal = presentation.get("terminal") or {}
    for event in terminal.get("events", []):
        if isinstance(event.get("inference_note"), str):
            event["inference_note"] = display_time_text(event["inference_note"])
    return presentation


def _public_endgame(endgame: dict) -> dict:
    phases = []
    for item in endgame.get("phases", []):
        public = _pick(item, ENDGAME_FIELDS)
        if isinstance(public.get("note"), str):
            public["note"] = display_time_text(public["note"])
        phases.append(public)
    return {"phases": phases}


def _public_rules_state(report: dict) -> dict:
    """Project only safe, stable rule-state fields into the public snapshot."""
    def token(value: object) -> str:
        return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]*", value) else "unknown"

    def rows(field: str) -> list:
        value = report.get(field)
        return value if isinstance(value, list) else []

    living = []
    for row in rows("rounds"):
        if not isinstance(row, dict) or type(row.get("day")) is not int:
            continue
        item = {"day": row["day"]}
        for field in ("dead_before_night", "night_deaths", "living_before_vote",
                      "living_after_day", "known_departed_after_day"):
            seats = row.get(field)
            if seats is None and field == "living_after_day":
                item[field] = None
            elif isinstance(seats, list) and all(type(seat) is int for seat in seats):
                item[field] = seats
        if type(row.get("night_deaths_complete")) is bool:
            item["night_deaths_complete"] = row["night_deaths_complete"]
        living.append(item)

    slots = []
    for row in rows("slot_states"):
        if not isinstance(row, dict) or type(row.get("round")) is not int:
            continue
        slot = token(row.get("slot"))
        if row.get("phase") not in {"night", "day"} or slot == "unknown":
            continue
        item = {"round": row["round"], "phase": row["phase"], "slot": slot,
                "status": token(row.get("status")), "reason": token(row.get("reason"))}
        targets = row.get("legal_targets")
        if targets is None or (isinstance(targets, list) and all(type(seat) is int for seat in targets)):
            item["legal_targets"] = targets
        if type(row.get("review_required")) is bool:
            item["review_required"] = row["review_required"]
        consequences = row.get("consequences")
        if isinstance(consequences, list):
            item["consequences"] = [
                {"type": token(value.get("type")), "seat": value["seat"], "rule": token(value.get("rule"))}
                for value in consequences
                if isinstance(value, dict) and type(value.get("seat")) is int
            ]
        slots.append(item)

    codes = sorted({token(row.get("code")) for row in rows("issues")
                    if isinstance(row, dict) and token(row.get("code")) != "unknown"})
    return {"living": living, "slots": slots, "issues": codes}


def _bluff_evidence_source_bindings(root: Path, dossier: dict, folder: Path) -> dict[str, str]:
    """Freeze hashes for text sources used by bluff evidence without exposing paths."""
    from website.api.bluffs import evidence_source_ref

    allowed_roles = {"subtitle", "transcript", "recap"}
    bindings = {}
    candidates = {
        row.get("path") for row in dossier.get("files", [])
        if isinstance(row, dict) and row.get("role") in allowed_roles
        and isinstance(row.get("path"), str)
    }
    # These existing per-game text evidence files are not always listed in
    # dossier.files. Keep the allowlist narrow so candidate/import artifacts
    # beside the official records do not enter the release source hash.
    local_evidence_names = {"复盘原文.txt", "复核记录.json", "定位上下文.txt"}
    candidates.update(
        source.relative_to(root).as_posix()
        for source in folder.iterdir()
        if source.is_file() and source.name in local_evidence_names
    )
    for relative in candidates:
        source = (root / relative).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            continue
        try:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
        except OSError:
            continue
        bindings[evidence_source_ref(relative)] = digest
    return bindings


def _append_supplemental_events(rounds: list[dict], context: dict) -> None:
    for item in context.get("supplemental_events", []):
        if not isinstance(item, dict):
            continue
        number, phase, event = item.get("round"), item.get("phase"), item.get("event")
        if type(number) is not int or phase not in {"night", "day"} or not isinstance(event, dict):
            continue
        round_ = next((row for row in rounds if row["number"] == number), None)
        if round_ is None:
            continue
        output = _pick(event, EVENT_FIELDS)
        output["slot_label"] = event.get("slot_label") or output.get("slot")
        output["description"] = event.get("description") or "对局补充记录。"
        round_[phase].append(output)


def _clip_voting(voting: dict, round_number: int, phase: str) -> dict:
    """Remove vote records for a phase that the terminal boundary excludes."""
    last_day = round_number - 1 if phase == "night" else round_number

    def is_excluded_day(row: dict) -> bool:
        day = row.get("day")
        return type(day) is int and day > last_day

    future_ballots = [row for row in voting.get("ballots", []) if is_excluded_day(row)]
    if future_ballots:
        raise PublishError("终局边界之后仍有已记录投票，需先核对终局与票轮档案")
    future_registrations = [row for row in voting.get("registrations", [])
                            if is_excluded_day(row)
                            and (row.get("on_police") is not None or row.get("off_police") is not None)]
    if future_registrations:
        raise PublishError("终局边界之后仍有已记录竞选报名，需先核对终局与报名档案")
    future_interruptions = [row for row in voting.get("interruptions", []) if is_excluded_day(row)]
    if future_interruptions:
        raise PublishError("终局边界之后仍有已记录流程中断，需先核对终局与投票档案")
    future_days = [row for row in voting.get("days", []) if is_excluded_day(row)]
    non_placeholder_days = [
        row for row in future_days
        if any(row.get(kind) not in (None, "unknown", "not_applicable")
               for kind in ("sheriff", "exile"))
    ]
    if non_placeholder_days:
        raise PublishError("终局边界之后仍有已确认白天阶段，需先核对终局与日阶段档案")

    result = dict(voting)
    result["days"] = [row for row in voting.get("days", []) if not is_excluded_day(row)]
    result["ballots"] = [row for row in voting.get("ballots", []) if not is_excluded_day(row)]
    result["registrations"] = [row for row in voting.get("registrations", [])
                                if not is_excluded_day(row)]
    result["interruptions"] = [row for row in voting.get("interruptions", [])
                                if not is_excluded_day(row)]
    return result


def _public_game(dossier: dict, voting: dict, endgame: dict, audit: dict | None,
                 board: dict, person_ids: dict[str, str], *,
                 source_voting: dict | None = None, derivations: dict | None = None) -> dict:
    bvid = _bvid(dossier)
    seats = []
    for seat in dossier.get("seats", []):
        name = seat.get("name")
        if not isinstance(name, str) or not name.strip():
            raise PublishError("座位姓名为空")
        seats.append({
            "seat": seat["seat"], "person_id": person_ids[name], "name": name,
            "role": seat["role"], "faction": seat["faction"],
            "learning_target": seat.get("learning_target"), "learned_role": seat.get("learned_role"),
        })
    default_rules: set[tuple[str, int]] = set()
    applications = []
    source_records = None
    if audit is not None:
        audited_voting = source_voting if source_voting is not None else voting
        if audit.get("facts") != audited_voting:
            if derivations is None:
                raise PublishError("投票旁证与当前投票档案不一致")
            from scripts.game_derivations import restore_source_records

            source_records = restore_source_records(dossier, voting, derivations)
            if audit.get("facts") != source_records["voting"]:
                raise PublishError("投票旁证与规则推导的原始投票档案不一致")
        for item in audit.get("rule_applications", []):
            if not isinstance(item, dict) or not isinstance(item.get("target"), str):
                raise PublishError("默认弃票旁证格式不合法")
            voters = item.get("voters", [])
            if not isinstance(voters, list) or any(type(voter) is not int for voter in voters):
                raise PublishError("默认弃票旁证缺少有效座位")
            rule, target, day = item.get("rule"), item["target"], item.get("day")
            if not isinstance(rule, str) or type(day) is not int:
                raise PublishError("默认弃票旁证字段不完整")
            applications.append({"rule": rule, "target": target, "day": day, "voters": voters})
            default_rules.update((target, voter) for voter in voters)
    public_voting = {
        "registrations": [_pick(row, REGISTRATION_FIELDS) for row in voting.get("registrations", [])],
        "ballots": [_clean_ballot(row, default_rules) for row in voting.get("ballots", [])],
        "interruptions": [_pick(row, INTERRUPTION_FIELDS) for row in voting.get("interruptions", [])],
        "days": [_pick(row, DAY_FIELDS) for row in voting.get("days", [])],
        "rule_applications": applications,
        "notes": (["未明确投向的票权位按已确认规则标注为默认弃票。"] if applications else
                  ["原文弃票与规则默认弃票按逐票旁证区分。"]),
    }
    if not voting.get("ballots"):
        public_voting["notes"].append("当前档案没有投票记录；这不表示该局投票数为零。")
    if audit is None:
        public_voting["notes"].append("默认弃票旁证缺失，未把弃票标记为规则默认。")

    context = dossier.get("_publication_context", {})
    public_rounds = _rounds(dossier, board)
    _append_supplemental_events(public_rounds, context)
    terminal = context.get("terminal_observation")
    terminal_observation = None
    terminal_events = []
    if isinstance(terminal, dict):
        number, phase = terminal.get("round"), terminal.get("phase")
        if type(number) is not int or phase not in {"night", "day"}:
            raise PublishError("终局观察缺少有效日夜边界")
        terminal_observation = {"round": number, "phase": phase}
        public_rounds = [row for row in public_rounds if row["number"] <= number]
        if phase == "night":
            terminal_round = next((row for row in public_rounds if row["number"] == number), None)
            if terminal_round is None:
                raise PublishError("终局轮次不在正式档案范围内")
            terminal_events = terminal_day_events(terminal_round['day'])
            terminal_round["day"] = []
        public_voting = _clip_voting(public_voting, number, phase)

    winner = dossier.get("winner")
    if winner not in {"good", "werewolf", "draw", None}:
        raise PublishError("胜方字段不在允许的公开值内")
    details = {
        "id": dossier["slug"], "season": dossier["season"], "date": dossier["date"],
        "phase": dossier["phase"], "game_number": dossier.get("game_number"),
        "board": dict(board["_public_board"]), "winner": winner,
        "players": [{"id": s["person_id"], "name": s["name"], "seat": s["seat"],
                     "role": s["role"], "faction": s["faction"]} for s in seats],
        "ballot_count": len(public_voting["ballots"]), "round_count": len(public_rounds),
        "release_id": None,
        "commentators": list(dossier.get("commentators", [])), "referee": dossier.get("referee"),
        "seats": seats, "rounds": public_rounds, "voting": public_voting,
        "endgame": _public_endgame(endgame),
        "source": {"url": f"https://www.bilibili.com/video/{bvid}/", "bvid": bvid},
        "data_notes": [],
    }
    evidence_sources = context.get("bluff_evidence_sources")
    if isinstance(evidence_sources, dict) and all(
        isinstance(key, str) and re.fullmatch(r"[a-f0-9]{64}", key)
        and isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
        for key, value in evidence_sources.items()
    ):
        details["bluff_evidence_sources"] = dict(evidence_sources)
    if terminal_observation is not None:
        details["terminal_observation"] = terminal_observation
        details["terminal_events"] = terminal_events
    if not public_voting["ballots"]:
        details["data_notes"].append("没有可发布的投票记录；投票数未按零票推断。")
    if winner is None:
        details["data_notes"].append("整局胜方待核。")
    if any(seat["role"] is None for seat in seats):
        details["data_notes"].append("部分座位身份待核，保留未知值。")
    if any(seat["faction"] is None for seat in seats):
        details["data_notes"].append("部分座位阵营待核，保留未知值。")
    if any(event["action"] == "unknown" for r in details["rounds"] for phase in ("night", "day") for event in r[phase]):
        details["data_notes"].append("部分行动仍为未知，保留来源状态。")
    for note in context.get("public_notes", []):
        if not isinstance(note, str) or re.search(r"source_path|[A-Za-z]:[\\/]|data[\\/]", note):
            raise PublishError("公开补充说明含有无效文字或本地路径")
        details["data_notes"].append(note)
    if derivations is not None:
        details["rules_state"] = _public_rules_state(derivations)
    if dossier["season"] == "S21":
        details["data_notes"].append("本季按保留媒体逐条展示，正式计分总局数尚未确认。")
        details["data_notes"].append("版型槽位仅用于归档，未确认的阵营、规则与叫醒顺序保留未知。")
    if dossier["season"] == "S23":
        details["data_notes"].append("夜间槽位排列用于归档，不表示已确认各技能的精确发动顺序。")
        if dossier["board"] == "masquerade":
            details["data_notes"].append("假面验证、给予面具和舞者共舞从第一天夜晚开始，首夜不可发动。")
        if any(event.get("invalidated") or event.get("action") == "invalidated_by_dq"
               for r in details["rounds"] for event in r["night"]):
            details["data_notes"].append("最后一狼8号在夜间被DQ出局，狼刀被判失效，因此为平安夜；DQ出局单独记录。")
        if (any(event.get("blocked_by_game_end") for r in details["rounds"]
                for phase in ("night", "day") for event in r[phase])
                or any(event.get("blocked_by_game_end") for event in details.get("terminal_events", []))):
            details["data_notes"].append("猎人作为最后一张神牌出局时对局立即结束，没有后续开枪环节。")
    if terminal_observation is not None:
        number, phase = terminal_observation["round"], terminal_observation["phase"]
        if phase == "night":
            details["data_notes"].append(
                f"档案确认本局在{phase_label(number, phase)}结束，未进入{phase_label(number, 'day')}。"
            )
        else:
            details["data_notes"].append(f"档案确认本局在{phase_label(number, phase)}结束。")
    details["presentation"] = _display_inference_notes(build_game_presentation(details))
    if derivations is not None:
        from website.api.bluffs import source_fingerprint

        if source_records is None:
            from scripts.game_derivations import restore_source_records

            source_records = restore_source_records(dossier, voting, derivations)
        source_view = _public_game(
            source_records["dossier"], source_records["voting"], endgame, audit, board, person_ids,
            source_voting=source_records["voting"],
        )
        details["bluff_source_binding"] = {
            "derived_fingerprint": source_fingerprint(details),
            "source_fingerprint": source_fingerprint(source_view),
        }
    return details


def load_publication(root: Path, season: str, sample: str | None = None) -> tuple[list[dict], str, str]:
    root = root.resolve()
    rules_hashes, rules = _logical_rules(root, season)
    scope = rules["scope"]
    rules_hash = digest_bytes(canonical_json(rules_hashes))
    season_dir = root / "data" / "games" / season
    if not season_dir.is_dir():
        raise PublishError("找不到指定赛季的游戏数据")
    entries = []
    for dossier_path in sorted(season_dir.glob("*/dossier.json")):
        try:
            dossier, dossier_digest = _read_json(dossier_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise PublishError("对局档案无法读取") from exc
        if dossier.get("season") != season or not _included(dossier, scope):
            continue
        if sample and _bvid(dossier) != sample:
            continue
        folder = dossier_path.parent
        paths = {key: folder / f"{key}.json" for key in ("voting", "endgame")}
        if any(not path.is_file() for path in paths.values()):
            raise PublishError("正式对局缺少投票或终局档案")
        voting, voting_digest = _read_json(paths["voting"])
        source_voting = voting
        endgame, endgame_digest = _read_json(paths["endgame"])
        slug = dossier.get("slug")
        if voting.get("game_slug") != slug or endgame.get("game_slug") != slug:
            raise PublishError("对局、投票和终局档案关联不一致")
        audit_path = root / "data" / "extractions" / season / "voting" / f"{_bvid(dossier)}.json"
        audit = None
        audit_digest = None
        if audit_path.is_file():
            audit, audit_digest = _read_json(audit_path)
        board_code = rules["formal"].get("board_code_map", {}).get(dossier.get("board"), dossier.get("board"))
        board = rules["boards"].get(board_code)
        if not board:
            raise PublishError("正式对局使用了未知版型")
        file_hashes = {"dossier": dossier_digest, "voting": voting_digest, "endgame": endgame_digest}
        if audit_digest is not None:
            file_hashes["voting_audit"] = audit_digest
        # Formal sidecars are part of the immutable source fingerprint. Only
        # explicitly allowlisted public notes and a phase boundary cross into
        # the public snapshot; source paths and audit text stay private.
        context = {}
        supplemental = {}
        supplemental_input = None
        for name in ("supplemental", "vote_control", "formal_context"):
            sidecar_path = folder / f"{name}.json"
            if sidecar_path.is_file():
                sidecar, sidecar_hash = _read_json(sidecar_path)
                if sidecar.get("game_slug") != slug:
                    raise PublishError("正式补充档案的对局关联不一致")
                file_hashes[name] = sidecar_hash
                if name == "formal_context":
                    context = sidecar
                elif name == "supplemental":
                    supplemental = sidecar
                    supplemental_input = sidecar
        derivation_path = folder / "rule_derivations.json"
        derivations = None
        if derivation_path.is_file():
            derivations, derivation_digest = _read_json(derivation_path)
            file_hashes["rule_derivations"] = derivation_digest
            try:
                from scripts.game_derivations import apply_precomputed, fingerprint

                input_hashes = derivations.get("input_hashes")
                if not isinstance(input_hashes, dict):
                    raise ValueError("规则推导缺少来源指纹")
                if ("terminal_observation" in input_hashes and input_hashes["terminal_observation"]
                        != fingerprint(context.get("terminal_observation"))):
                    raise ValueError("终局边界已变化，规则推导已过期，请重新生成")
                if (input_hashes.get("supplemental") != fingerprint(supplemental_input)
                        or input_hashes.get("endgame") != fingerprint(endgame)):
                    raise ValueError("补充或终局档案已变化，规则推导已过期，请重新生成")
                if "speech_evidence" in input_hashes:
                    speech = derivations.get("sheriff_speech_evidence") or {}
                    binding = speech.get("source_binding") or {}
                    source_binding = (supplemental_input or {}).get("source_binding") or {}
                    source = root / binding.get("path", "")
                    if (fingerprint(speech) != input_hashes["speech_evidence"]
                            or binding.get("path") != source_binding.get("selected_transcript_path")
                            or binding.get("sha256") != source_binding.get("selected_transcript_sha256")
                            or not source.is_file()
                            or hashlib.sha256(source.read_bytes()).hexdigest() != binding.get("sha256")):
                        raise ValueError("警上发言旁证的字幕来源已变化，请重新生成规则推导")
                normalized = apply_precomputed(dossier, source_voting, derivations)
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise PublishError(str(exc)) from exc
            dossier, voting = normalized["dossier"], normalized["voting"]
            report_terminal = derivations.get("terminal")
            if report_terminal is not None:
                if (not isinstance(report_terminal, dict)
                        or type(report_terminal.get("round")) is not int
                        or report_terminal.get("phase") not in {"night", "day"}):
                    raise PublishError("规则推导终局缺少有效日夜边界")
                terminal_boundary = {"round": report_terminal["round"],
                                     "phase": report_terminal["phase"]}
                existing_terminal = context.get("terminal_observation")
                if existing_terminal is not None:
                    if (not isinstance(existing_terminal, dict)
                            or type(existing_terminal.get("round")) is not int
                            or existing_terminal.get("phase") not in {"night", "day"}):
                        raise PublishError("正式终局观察缺少有效日夜边界")
                    if (existing_terminal["round"], existing_terminal["phase"]
                            ) != (terminal_boundary["round"], terminal_boundary["phase"]):
                        raise PublishError("规则推导与正式终局边界不一致")
                context["terminal_observation"] = terminal_boundary
        if not context.get("terminal_observation") and audit is not None:
            audited_terminal = (audit.get("game_flow") or {}).get("terminal")
            if (isinstance(audited_terminal, dict)
                    and audit.get("dossier_sha256") == dossier_digest):
                round_number, phase = audited_terminal.get("round"), audited_terminal.get("phase")
                if type(round_number) is int and phase in {"night", "day"}:
                    context["terminal_observation"] = {"round": round_number, "phase": phase}
        if not context.get("terminal_observation"):
            context["terminal_observation"] = _terminal_from_dossier(dossier)
        context["supplemental_events"] = _public_supplemental_events(supplemental)
        evidence_sources = _bluff_evidence_source_bindings(root, dossier, folder)
        if evidence_sources:
            context["bluff_evidence_sources"] = evidence_sources
            file_hashes["bluff_evidence_sources"] = digest_bytes(canonical_json(evidence_sources))
        dossier = {**dossier, "_publication_context": context}
        entries.append({
            "dossier": dossier, "voting": voting, "endgame": endgame, "audit": audit,
            "source_voting": source_voting, "derivations": derivations,
            "board": board, "folder": folder, "bvid": _bvid(dossier), "source_hashes": file_hashes,
        })
    if sample and not entries:
        raise PublishError("指定样例不在已确认正式范围内或不存在")
    if not sample:
        expected = rules["formal"].get("scope", {}).get("scored_total", scope.get("expected_games"))
        if type(expected) is int:
            from scripts.incremental_scope import approved_incremental_count
            try:
                expected += approved_incremental_count(root, season)
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise PublishError(f"新增对局人工确认范围无效：{error}") from error
        if type(expected) is int and len(entries) != expected:
            raise PublishError("正式范围数量与已确认统计口径不一致")
    hashes = []
    for item in entries:
        hashes.append({"game_id": item["dossier"]["slug"], "files": item["source_hashes"]})
    source_hash = digest_bytes(canonical_json(hashes))
    return entries, source_hash, rules_hash


def publication_seasons(season: str | list[str] | tuple[str, ...]) -> list[str]:
    seasons = [season] if isinstance(season, str) else list(season)
    if not seasons or len(set(seasons)) != len(seasons) or any(
        not isinstance(s, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", s) for s in seasons
    ):
        raise PublishError("发布赛季必须非空、唯一且格式合法")
    return sorted(seasons)


def load_release(root: Path, season: str | list[str] | tuple[str, ...], sample: str | None = None
                 ) -> tuple[list[dict], str, str]:
    seasons = publication_seasons(season)
    if len(seasons) == 1:
        return load_publication(root, seasons[0], sample)
    if sample:
        raise PublishError("多赛季发布不能指定单局样例")
    entries, sources, rules = [], {}, {}
    for selected in seasons:
        batch, source_hash, rules_hash = load_publication(root, selected)
        entries.extend(batch)
        sources[selected], rules[selected] = source_hash, rules_hash
    if len({entry["dossier"]["slug"] for entry in entries}) != len(entries):
        raise PublishError("多赛季发布含有重复对局 ID")
    return entries, digest_bytes(canonical_json(sources)), digest_bytes(canonical_json(rules))


def _connect(schema: str = "masters_web"):
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        conn = psycopg.connect(database_url, row_factory=dict_row)
        conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        conn.commit()
        return conn
    # Existing local installs keep their credentials in scripts/database.py;
    # this import is publisher-only and never required by the API runtime.
    import sys
    scripts = str(PACKAGE_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import database
    conn = database.connect(schema)
    conn.commit()
    return conn


def _schema_sql() -> str:
    return (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")


def _person_ids(conn, names: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    # A local jcms.people table is an optional identity source. The public
    # schema deliberately has no FK or dependency on the source database.
    conn.execute("SAVEPOINT person_lookup")
    try:
        cols = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = ANY(%s)",
            ("jcms", "people", ["id", "name"]),
        ).fetchall()
        if {row["column_name"] for row in cols} == {"id", "name"}:
            rows = conn.execute(
                "SELECT name, id::text AS id FROM jcms.people WHERE name = ANY(%s)", (list(names),)
            ).fetchall()
            result.update({row["name"]: row["id"] for row in rows})
        conn.execute("RELEASE SAVEPOINT person_lookup")
    except psycopg.Error:
        # No jcms schema or permissions: use deterministic public UUIDs.
        conn.execute("ROLLBACK TO SAVEPOINT person_lookup")
    for name in names:
        result.setdefault(name, str(uuid.uuid5(PERSON_NAMESPACE, name.strip().casefold())))
    return result


def _create_schema(conn) -> None:
    conn.execute("SAVEPOINT publish_schema")
    try:
        conn.execute(_schema_sql(), prepare=False)
        conn.execute("RELEASE SAVEPOINT publish_schema")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT publish_schema")
        raise


def _release_id(season: str, source_hash: str, rules_hash: str) -> str:
    return (f"{season}-{source_hash[:16]}-{rules_hash[:8]}-"
            f"p{PUBLICATION_FORMAT_VERSION}-s{STATISTICS_VERSION}")


def publish(root: Path = DEFAULT_SOURCE_ROOT, season: str | list[str] = "S22", sample: str | None = None,
            *, activate: bool = True) -> dict:
    seasons = publication_seasons(season)
    season_label = "_".join(seasons)
    entries, source_hash, rules_hash = load_release(root, seasons, sample)
    release_id = _release_id(season_label, source_hash, rules_hash)
    conn = _connect("masters_web")
    try:
        with conn.transaction():
            _create_schema(conn)
            names = {seat["name"] for item in entries for seat in item["dossier"].get("seats", [])}
            person_ids = _person_ids(conn, names)
            existing = conn.execute("SELECT game_count FROM releases WHERE id = %s", (release_id,)).fetchone()
            if existing:
                if existing["game_count"] != len(entries):
                    raise PublishError("同一发布批次的局数发生冲突")
            else:
                manifest_games = []
                docs = []
                player_rows: dict[str, dict] = {}
                for item in entries:
                    dossier = item["dossier"]
                    doc = _public_game(dossier, item["voting"], item["endgame"], item["audit"],
                                       item["board"], person_ids,
                                       source_voting=item.get("source_voting"),
                                       derivations=item.get("derivations"))
                    doc["release_id"] = release_id
                    docs.append((item, doc))
                    manifest_games.append({"id": dossier["slug"], "files": item["source_hashes"]})
                    for seat in doc["seats"]:
                        player = player_rows.setdefault(seat["person_id"], {
                            "id": seat["person_id"], "name": seat["name"], "appearances": 0,
                            "roles": Counter(),
                        })
                        player["appearances"] += 1
                        player["roles"][seat["role"] or "身份未知"] += 1
                manifest = {"season": season_label, "seasons": seasons, "publication_format_version": PUBLICATION_FORMAT_VERSION,
                            "statistics_version": STATISTICS_VERSION, "games": manifest_games,
                            "rules": {s: sorted(_logical_rules(Path(root), s)[0].items()) for s in seasons}}
                conn.execute(
                    "INSERT INTO releases(id, season, game_count, source_hash, rules_hash, manifest) "
                    "VALUES(%s, %s, %s, %s, %s, %s)",
                    (release_id, season_label, len(entries), source_hash, rules_hash, Jsonb(manifest)),
                )
                for player in player_rows.values():
                    roles = [{"role": role, "count": count} for role, count in sorted(player["roles"].items())]
                    conn.execute(
                        "INSERT INTO players(release_id, id, name, appearances, roles) VALUES(%s,%s,%s,%s,%s)",
                        (release_id, player["id"], player["name"], player["appearances"], Jsonb(roles)),
                    )
                for item, doc in docs:
                    dossier = item["dossier"]
                    search_text = " ".join([
                        dossier["slug"], item["bvid"], dossier["date"], item["board"]["name"],
                        " ".join(s["name"] for s in doc["seats"]),
                    ])
                    vote_count = sum(len(ballot["votes"]) for ballot in doc["voting"]["ballots"])
                    conn.execute(
                        "INSERT INTO games(release_id,id,season,event_date,phase,game_number,board_code,board_name,"
                        "winner,bvid,search_text,ballot_count,vote_count,round_count,snapshot) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                         (release_id, doc["id"], doc["season"], date.fromisoformat(doc["date"]), doc["phase"], doc["game_number"],
                         doc["board"]["code"], doc["board"]["name"], doc["winner"], item["bvid"], search_text,
                         doc["ballot_count"], vote_count, doc["round_count"], Jsonb(doc)),
                    )
                    for seat in doc["seats"]:
                        conn.execute(
                            "INSERT INTO game_players(release_id,game_id,person_id,name,seat,role,faction) "
                            "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                            (release_id, doc["id"], seat["person_id"], seat["name"], seat["seat"],
                             seat["role"], seat["faction"]),
                        )
            if activate:
                conn.execute(
                    "INSERT INTO active_release(singleton, release_id) VALUES(true,%s) "
                    "ON CONFLICT(singleton) DO UPDATE SET release_id=EXCLUDED.release_id",
                    (release_id,),
                )
        return {"id": release_id, "seasons": seasons, "game_count": len(entries), "source_hash": source_hash,
                "rules_hash": rules_hash, "activated": activate, "idempotent": bool(existing)}
    finally:
        conn.close()


def activate(release_id: str) -> dict:
    conn = _connect("masters_web")
    try:
        with conn.transaction():
            _create_schema(conn)
            row = conn.execute("SELECT game_count FROM releases WHERE id = %s", (release_id,)).fetchone()
            if not row:
                raise PublishError("发布批次不存在")
            conn.execute(
                "INSERT INTO active_release(singleton, release_id) VALUES(true,%s) "
                "ON CONFLICT(singleton) DO UPDATE SET release_id=EXCLUDED.release_id", (release_id,)
            )
        return {"id": release_id, "game_count": row["game_count"], "activated": True}
    finally:
        conn.close()


def list_games(root: Path = DEFAULT_SOURCE_ROOT, season: str | list[str] = "S22") -> list[dict]:
    entries, _, _ = load_release(root, season)
    return [{"id": item["dossier"]["slug"], "date": item["dossier"]["date"],
             "game_number": item["dossier"].get("game_number"), "board": item["board"]["name"],
             "bvid": item["bvid"]} for item in entries]
