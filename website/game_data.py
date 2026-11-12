"""Project a newly reviewed candidate into the final game format.

Historical games load directly from game.json; this module only handles the
current incremental batch before its temporary evidence is removed.
"""
from __future__ import annotations
import re
from scripts.game_time import display_time_text, phase_label
from scripts.role_constraints import puppet_target
from scripts.game_inference import build_game_presentation, terminal_from_events, terminal_day_events

class PublishError(ValueError):
    pass

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


def _bvid(dossier: dict) -> str:
    slug = dossier.get("slug")
    match = BVID_RE.search(slug) if isinstance(slug, str) else None
    if not match:
        raise PublishError("对局缺少可识别的视频编号")
    return match.group(0)


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
    """Expose confirmed actions retained outside the formal event slots."""
    public = []
    rows = list(supplemental.get("events", []))
    for source in (supplemental.get("phase_reviewed") or {}).get("events", []):
        if (source.get("action") == "trade" and source.get("state") == "performed"
                and source.get("status") == "text_explicit"):
            rows.append({"round": source.get("round"), "phase": source.get("phase"),
                         "event": {"slot": "warden_trade_targets", "action": "select_pair",
                                   "actor": source.get("actor"), "targets": source.get("targets", []),
                                   "result": source.get("result")}})
            continue
        if source.get("action") not in {"concede", "surrender"} or source.get("state") != "performed":
            continue
        phase = "day" if source.get("phase") == "endgame" else source.get("phase")
        rows.append({"round": source.get("round"), "phase": phase,
                     "event": {"slot": "werewolf_surrender", "action": "surrender", "actor": source.get("actor")}})
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get("round")) is not int:
            continue
        phase, source = row.get("phase"), row.get("event")
        if phase not in {"night", "day"} or not isinstance(source, dict):
            continue
        action = source.get("action")
        revenge = source.get("slot") == "wolf_girl_revenge" and action == "die"
        if action not in {"disqualify", "surrender", "select_pair"} and not revenge:
            continue
        # This guard ruling is already displayed on the attempted guard. The
        # seat still requires pursuit and must not become an ordinary death.
        if (source.get("slot") == "guard_disqualification" and action == "disqualify"
                and "追刀追投" in str(source.get("result") or "")):
            continue
        event = _pick(source, EVENT_FIELDS)
        event["supplemental"] = True
        if revenge:
            event["slot_label"] = "狼女孩报复连带"
        elif action == "disqualify":
            event["slot"] = "disqualification"
            targets = event.get("targets") or []
            seats = "、".join(f"{seat}号" for seat in targets)
            subject = seats or (f"{event['actor']}号" if type(event.get("actor")) is int else "玩家")
            event["result"] = "DQ裁定；与普通死亡结算分开记录。"
            event["description"] = f"{subject}被DQ出局；此裁定与普通死亡结算分开记录。"
            event["slot_label"] = "DQ出局"
        elif action == "surrender":
            slot = event.get("slot")
            if slot is None:
                continue
            actor = event.get("actor")
            subject = f"{actor}号狼人" if type(actor) is int else "狼人"
            event["result"] = "交牌，对局结束。"
            event["description"] = f"{subject}选择交牌，对局结束。"
            event["slot_label"] = "狼人交牌"
        else:
            event["slot_label"] = "典狱长选择交易对象"
        identity = (row["round"], phase, action, event.get("actor"), tuple(event.get("targets", [])))
        if identity not in seen:
            public.append({"round": row["round"], "phase": phase, "event": event})
            seen.add(identity)
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
        if public.get('note') == 'S21 primary-reviewed endgame attack; unspecified settlement remains unknown.':
            public.pop('note')
        if isinstance(public.get("note"), str):
            public["note"] = display_time_text(public["note"])
        phases.append(public)
    return {"phases": phases, "review_status": endgame.get("review_status", "recorded")}


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
    puppet = puppet_target(dossier)
    seats = []
    for seat in dossier.get("seats", []):
        name = seat.get("name")
        if not isinstance(name, str) or not name.strip():
            raise PublishError("座位姓名为空")
        seats.append({
            "seat": seat["seat"], "person_id": person_ids[name], "name": name,
            "role": seat["role"], "faction": 'werewolf' if seat['seat'] == puppet else seat["faction"],
            "is_puppet": seat['seat'] == puppet,
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
    return details
