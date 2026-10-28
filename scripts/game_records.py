"""Current game records: shared people and fixed per-board event slots."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
import json
from pathlib import Path

from psycopg.types.json import Jsonb

from database import ROOT, ReviewError, artifact, connect

ALIASES = {
    "其人": ["其人的心事"],
    "桃子": ["陸慧霖_陆元箐小桃子"],
    "豆儿啵": ["pointy豆儿啵"],
    "辉少": [],
}

WOLF_ROLES = frozenset({"狼人", "机械狼", "狼王", "黑狼王", "诡术师", "假面", "典狱长", "白狼王", "九尾狐", "狼术师"})
ROLE_FACTIONS = {
    **{role: "werewolf" for role in WOLF_ROLES},
    "盗宝大师": "werewolf",
    "九尾狐": "werewolf",
    "狼术师": "werewolf",
    "鬼魂新娘": "third_party",
    **{role: "good" for role in {
        "预言家", "通灵师", "女巫", "猎人", "守卫", "骑士", "摄梦人", "平民",
        "魔术师", "定序王子", "舞者", "白痴", "白神", "混血儿", "毒师", "蒙面人", "白泽",
    }},
}


def data_file(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to((ROOT / "data").resolve()) or not path.is_file():
        raise ReviewError(f"源文件必须位于data目录：{relative}")
    return path


def primary_source_file(files):
    for role in ("audio", "subtitle", "transcript"):
        for file in files:
            if file.get("role") == role:
                return file
    raise ReviewError("入库需要本局的音频、字幕或转写来源关联")


def template(code):
    if not code.replace("_", "").isalnum():
        raise ReviewError("版型代码不合法")
    return json.loads((ROOT / "config/board_templates" / (code+".json")).read_text(encoding="utf-8"))


def empty_event(slot, actor=None):
    return {"slot": slot, "action": "unknown", "actor": actor, "targets": [],
            "result": None, "start_seat": None, "direction": None, "votes": [],
            "random_point": None, "speech_scope": None, "availability": None, "effects": []}


def game_rules():
    return json.loads((ROOT/"config/game_rules.json").read_text(encoding="utf-8"))


def mechanical_player(value):
    return next(p for p in value["seats"] if p["role"]=="机械狼")


def learning_round(value):
    return next((r["number"] for r in value["rounds"]
                 if any(e["slot"]=="mechanical_action" and e["action"]=="learn" for e in r["night"])),None)


def poison_effects(value, round_number):
    """Resolve poison only; wolf attacks and other death causes remain separate."""
    round_=next(r for r in value["rounds"] if r["number"]==round_number)
    mech=mechanical_player(value)
    mechanical=next(e for e in round_["night"] if e["slot"]=="mechanical_action")
    learned=learning_round(value)
    shield_active=(mech["learned_role"]=="机械守卫" and learned is not None and
                   round_number>=learned+game_rules()["mechanical_unlock"]["night_round_offset"])
    resolved={}
    for event in round_["night"]:
        if event["action"]!="poison":
            continue
        if not event["targets"]:
            continue  # The validator reports the missing target.
        intended=event["targets"][0]
        shield=shield_active and event["slot"]=="witch_poison"
        reflected=shield and mechanical["action"]=="guard" and intended in mechanical["targets"]
        uncertain=shield and mechanical["action"]=="unknown"
        kind="poison_unresolved" if uncertain else "poison_reflected" if reflected else "poison_death"
        resolved[event["slot"]]=[{"kind":kind,"intended_target":intended,
            "dead_seat":None if uncertain else event["actor"] if reflected else intended,
            "shield_actor":mech["seat"] if reflected else None}]
    return resolved


def derived_effects(value, round_number):
    resolved=poison_effects(value,round_number)
    night=next(r["night"] for r in value["rounds"] if r["number"]==round_number)
    action=next(e for e in night if e["slot"]=="mechanical_action")
    form=template(value["board"])["mechanical_forms"].get(mechanical_player(value)["learned_role"],{})
    if action["action"]=="attack" and form.get("skill_knife_ignores_guard_shield"):
        guard=next(e for e in night if e["slot"]=="guard")
        resolved[action["slot"]]=[{"kind":"shield_bypassed","intended_target":target,
            "dead_seat":None,"shield_actor":guard["actor"]} for target in action["targets"]
            if guard["action"]=="guard" and target in guard["targets"]]
    return resolved


def prior_departures(value, round_number):
    departed=set()
    for round_ in value["rounds"]:
        if round_["number"]>=round_number:
            break
        for event in round_["day"]:
            if event["action"] in {"die","shoot","exile"}:
                departed.update(event["targets"])
            if (event["action"]=="self_destruct" or (event["slot"]=="hunter_shot" and event["action"]=="shoot")) and event["actor"] is not None:
                departed.add(event["actor"])
        for effects in poison_effects(value,round_["number"]).values():
            departed.update(e["dead_seat"] for e in effects if e["dead_seat"] is not None)
    return departed


def prior_survival_unknown(value, round_number):
    # An incomplete death/shot/exile record cannot prove that a seat survived.
    uncertain_slots={"night_deaths","hunter_shot","exile_result","self_destruct"}
    if mechanical_player(value)["learned_role"] in {None,"机械猎人"}:
        uncertain_slots.add("mechanical_day_skill")
    return any(e["slot"] in uncertain_slots and e["action"]=="unknown"
               for r in value["rounds"] if r["number"]<round_number for e in r["day"])


def inferred_takeover_state(value, round_number):
    departed=prior_departures(value,round_number)
    if mechanical_player(value)["seat"] in departed:
        return "dead"
    if prior_survival_unknown(value,round_number):
        return "unknown"
    return "wolves_alive" if any(p["role"]=="狼人" and p["seat"] not in departed for p in value["seats"]) else "available"


def takeover_state(value, round_number):
    night=next(r["night"] for r in value["rounds"] if r["number"]==round_number)
    confirmation=next(e for e in night if e["slot"]=="mechanical_knife_status")
    return {"carrying":"available","not_carrying":"wolves_alive","unavailable":"dead"}.get(
        confirmation["action"],inferred_takeover_state(value,round_number))


def poisoned_state(value, round_number, seat):
    round_=next(r for r in value["rounds"] if r["number"]==round_number)
    resolved=poison_effects(value,round_number)
    uncertain=False
    mech=mechanical_player(value)
    for source in game_rules()["hunter_poison_sources"]:
        event=next(e for e in round_["night"] if e["slot"]==source["slot"])
        if source.get("learned_role") and mech["learned_role"] is not None and mech["learned_role"]!=source["learned_role"]:
            continue
        for effect in resolved.get(event["slot"],[]):
            if effect["dead_seat"]==seat:
                return "poisoned"
            if effect["kind"]=="poison_unresolved" and seat in {event["actor"],effect["intended_target"]}:
                uncertain=True
        if event["action"]=="unknown":
            uncertain=True
    return "unknown" if uncertain else "clear"


def mechanical_skill_state(value, round_number, phase):
    mech=mechanical_player(value)
    if mech["seat"] in prior_departures(value,round_number):
        return "dead"
    if prior_survival_unknown(value,round_number) and takeover_state(value,round_number) not in {"available","wolves_alive"}:
        return "unknown"
    learned=learning_round(value)
    if learned is None:
        actions=[e["action"] for r in value["rounds"] if r["number"]<=round_number
                 for e in r["night"] if e["slot"]=="mechanical_action"]
        return "locked" if mech["learned_role"] is None and actions and all(a in {"pass","unavailable"} for a in actions) else "unknown"
    if phase=="night" and round_number==learned:
        return "learning"
    offset=game_rules()["mechanical_unlock"][phase+"_round_offset"]
    if round_number<learned+offset:
        return "locked"
    form=template(value["board"])["mechanical_forms"].get(mech["learned_role"])
    if form is None:
        return "unknown"
    if form["phase"] is None:
        return "no_skill"
    if form["phase"]!=phase:
        return "wrong_phase"
    if form.get("requires_ordinary_wolves_eliminated"):
        state=takeover_state(value,round_number)
        if state!="available":
            return state
    if mech["learned_role"]=="机械猎人":
        state=poisoned_state(value,round_number,mech["seat"])
        if state!="clear":
            return state
    return "available"


def resolve_speech_start(random_point, direction, eligible, seat_count):
    if direction not in {"forward","reverse"} or not 1<=random_point<=seat_count:
        raise ReviewError("随机点数或发言方向不合法")
    eligible=set(eligible)
    if not eligible or not eligible<=set(range(1,seat_count+1)):
        raise ReviewError("没有可用的发言座位")
    step=1 if direction=="forward" else -1
    for offset in range(seat_count):
        seat=(random_point-1+step*offset)%seat_count+1
        if seat in eligible:
            return seat
    raise ReviewError("没有可用的发言座位")


def speech_start_for_event(value, round_number, event):
    current=next(r for r in value["rounds"] if r["number"]==round_number)
    eligible={p["seat"] for p in value["seats"]}-prior_departures(value,round_number)
    for day_event in current["day"]:
        if day_event["action"] in {"die","shoot"}:
            eligible.difference_update(day_event["targets"])
    if event["speech_scope"]=="sheriff":
        candidates=None
        for round_ in value["rounds"]:
            if round_["number"]>round_number:
                break
            registration=next(e for e in round_["day"] if e["slot"]=="sheriff_candidates")
            if registration["action"]=="register":
                candidates=set(registration["targets"])
        if candidates is None:
            raise ReviewError("警上发言缺少上警名单")
        eligible.intersection_update(candidates)
    elif event["speech_scope"]!="day":
        raise ReviewError("发言顺序缺少警上或白天范围")
    return resolve_speech_start(event["random_point"],event["direction"],eligible,len(value["seats"]))


def hunter_skill_state(value, round_number):
    hunter=next(p["seat"] for p in value["seats"] if p["role"]=="猎人")
    if hunter in prior_departures(value,round_number):
        return "unavailable"
    if prior_survival_unknown(value,round_number):
        return "unknown"
    return {"poisoned":"cannot_shoot","clear":"can_shoot","unknown":"unknown"}[poisoned_state(value,round_number,hunter)]


def apply_derived_rules(value):
    for round_ in value["rounds"]:
        confirmation=next(e for e in round_["night"] if e["slot"]=="mechanical_knife_status")
        inferred=inferred_takeover_state(value,round_["number"])
        confirmation["action"]={"available":"carrying","wolves_alive":"not_carrying","dead":"unavailable","unknown":"unknown"}[inferred]
        resolved=derived_effects(value,round_["number"])
        for phase in ["night","day"]:
            for event in round_[phase]:
                event["effects"]=resolved.get(event["slot"],[]) if phase=="night" else []
                event["availability"]=(mechanical_skill_state(value,round_["number"],phase)
                    if event["slot"] in {"mechanical_action","mechanical_day_skill"} else None)
        hunter=next(e for e in round_["night"] if e["slot"]=="hunter_state")
        hunter["action"]=hunter_skill_state(value,round_["number"])
        order=next(e for e in round_["day"] if e["slot"]=="speech_order")
        if order["action"]=="order" and order["random_point"] is not None:
            order["start_seat"]=speech_start_for_event(value,round_["number"],order)
    return value


def validate_batch(value, check_files=True, *, check_rules=True, allow_legacy_treasure_faction=False):
    """Validate a batch review record using only the facts already known."""
    forbidden = {"evidence", "evidence_ids", "review", "review_state", "verification_status", "schema_version", "transcription_runs", "speech_turns"}
    def walk(node):
        if isinstance(node, dict):
            if forbidden & node.keys():
                raise ReviewError("当前对局格式不包含证据、转写版本或审核字段")
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(value)

    board = template(value["board"])
    seats = value["seats"]
    count = board["seat_count"]
    if (not isinstance(seats, list) or len(seats) != count or
            any(not isinstance(p, dict) or not {"seat", "role", "faction", "name"} <= p.keys() or type(p.get("seat")) is not int for p in seats) or
            sorted(p["seat"] for p in seats) != list(range(1, count+1))):
        raise ReviewError("座位必须完整且不重复")
    by_seat = {p["seat"]: p for p in seats}

    configured_counts = board.get("role_counts")
    if configured_counts is None or configured_counts == "dynamic" or board.get("dynamic_roles") is True:
        role_counts = None
    elif isinstance(configured_counts, dict) and all(
            isinstance(role, str) and role and type(amount) is int and amount >= 0
            for role, amount in configured_counts.items()):
        role_counts = configured_counts
    else:
        raise ReviewError("版型角色数量配置不合法")

    known_role_counts = Counter()
    known_names = []
    for p in seats:
        role, faction, name = p.get("role"), p.get("faction"), p.get("name")
        if role is not None:
            if not isinstance(role, str) or not role.strip():
                raise ReviewError("已知身份不能为空")
            if role_counts is not None and role not in role_counts:
                raise ReviewError("身份不属于版型")
            known_role_counts[role] += 1
            expected_faction = None if role == "混血儿" else ROLE_FACTIONS.get(role)
            explicit_ghost_third_party = board["code"] == "ghost_bride" and faction == "third_party"
            legacy_treasure_good = (allow_legacy_treasure_faction and board["code"] == "treasure_master"
                                    and role == "盗宝大师" and faction == "good")
            if (expected_faction is not None and faction is not None and faction != expected_faction
                    and not explicit_ghost_third_party and not legacy_treasure_good):
                raise ReviewError("身份与阵营不一致")
        if faction is not None and faction not in {"good", "werewolf", "third_party"}:
            raise ReviewError("阵营不合法")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise ReviewError("已知座位姓名不能为空")
            known_names.append(name)
        target = p.get("learning_target")
        learned_role = p.get("learned_role")
        if target is not None and (type(target) is not int or target not in by_seat or target == p["seat"]):
            raise ReviewError("学习目标越界或指向自身")
        if role is not None and role != "机械狼" and (target is not None or learned_role is not None):
            raise ReviewError("只有机械狼可以登记学习结果")
        if role == "机械狼" and learned_role is not None:
            forms = board.get("mechanical_forms", {})
            if not isinstance(learned_role, str) or learned_role not in forms:
                raise ReviewError("机械狼学习形态不属于版型")
        if role == "机械狼" and target is not None and learned_role is not None:
            form = board.get("mechanical_forms", {}).get(learned_role)
            target_role = by_seat[target].get("role")
            if target_role is not None and form.get("learned_from") != target_role:
                raise ReviewError("机械狼学习形态与学习目标身份不一致")
    if role_counts is not None and any(known_role_counts[role] > maximum for role, maximum in role_counts.items()):
        raise ReviewError("已知身份数量超过版型配置")
    if len(known_names) != len(set(known_names)):
        raise ReviewError("座位姓名重复")

    roster = value["roster"]
    if not isinstance(roster, list) or any(not isinstance(name, str) or not name.strip() for name in roster):
        raise ReviewError("排班姓名不合法")
    if len(roster) != len(set(roster)):
        raise ReviewError("排班姓名重复")
    for name, seat_number in game_rules()["fixed_seats"].items():
        if name in roster and by_seat[seat_number].get("name") is not None and by_seat[seat_number]["name"] != name:
            raise ReviewError(f"{name}在场时必须使用{seat_number}号座位")
        if name in known_names and by_seat[next(p["seat"] for p in seats if p.get("name") == name)]["seat"] != seat_number:
            raise ReviewError(f"{name}在场时必须使用{seat_number}号座位")

    if type(value.get("game_number")) is not int and value.get("game_number") is not None:
        raise ReviewError("场次编号必须为正整数或未知")
    if value.get("game_number") is not None and value["game_number"] < 1:
        raise ReviewError("场次编号必须为正整数或未知")
    winner = value.get("winner")
    if winner is not None and (not isinstance(winner, str) or winner not in {"good", "werewolf", "third_party", "draw"}):
        raise ReviewError("胜方阵营不合法")

    numbers = [r.get("number") for r in value["rounds"]]
    if any(type(n) is not int for n in numbers) or numbers != list(range(1, len(numbers)+1)):
        raise ReviewError("轮次必须从1连续编号")
    valid_seats = set(by_seat)
    valid_effects = {"poison_death", "poison_reflected", "poison_unresolved", "shield_bypassed"}
    # Target counts are slot-specific: the same verb may denote a seat target
    # in one slot and a selected role/result in another (for example, treasure
    # choice). Unknown/pass/unavailable and all other non-target outcomes keep
    # an empty targets list.
    fixed_target_counts = {
        ("guard", "guard"): 1,
        ("wolf_attack", "attack"): 1,
        ("witch_save", "save"): 1,
        ("witch_poison", "poison"): 1,
        ("seer_check", "check"): 1,
        ("mechanical_action", "learn"): 1,
        ("mechanical_action", "attack"): 1,
        ("mechanical_action", "guard"): 1,
        ("mechanical_action", "poison"): 1,
        ("mechanical_action", "check"): 1,
        ("mechanical_day_skill", "shoot"): 1,
        ("hunter_shot", "shoot"): 1,
        ("wolf_king_shot", "shoot"): 1,
        ("dreamer_action", "dream"): 1,
        ("treasure_card_skill", "attack"): 1,
        ("treasure_card_skill", "guard"): 1,
        ("treasure_card_skill", "poison"): 1,
        ("treasure_card_skill", "check"): 1,
        ("treasure_card_skill", "dream"): 1,
        ("treasure_card_skill", "shoot"): 1,
        ("treasure_extra_attack", "attack"): 1,
        ("sheriff_result", "elected"): 1,
        ("second_exile_result", "exile"): 1,
        ("exile_result", "exile"): 1,
        ("badge", "transfer"): 1,
        ("badge", "hold"): 1,
        ("mixed_blood_model", "choose"): 1,
        ("ghost_bride_select_groom", "choose"): 1,
        ("couple_select_witness", "choose"): 1,
        ("magician_exchange", "exchange"): 2,
        ("guile_exchange", "exchange"): 2,
        ("guile_exchange", "invalid_exchange"): 2,
        ("masquerade_verify", "verify"): 1,
        ("masquerade_mask", "give_mask"): 1,
        ("dancer_dance", "dance"): 3,
        ("dance_resolution", "minority_dies"): 1,
        ("masked_delayed_death", "die_after_speech"): 1,
        ("puppet_select", "select"): 1,
        ("bullet_chat_hunter", "select"): 1,
        ("wolf_arrest", "arrest"): 1,
        ("knight_duel", "duel"): 1,
        ("warden_trade_targets", "select_pair"): 2,
        ("trade_resolution", "betrayal_death"): 1,
        ("trade_resolution", "mutual_targets"): 2,
        ("trade_resolution", "warden_self_trade"): 1,
        ("trade_resolution", "immune"): 2,
        ("trade_decisions", "trade"): 2,
        ("trade_decisions", "betray"): 2,
        ("trade_decisions", "trade_betray"): 2,
        ("trade_decisions", "betray_trade"): 2,
        ("ghost_bride_attack_executor", "single_wolf_attack"): 1,
        ("ghost_bride_attack_executor", "couple_attack"): 1,
        ("ghost_bride_attack_executor", "witness_attack"): 1,
        ("lover_death_chain", "suicide"): 1,
        # This action selects a card role; its value belongs in result, never
        # in seat targets.
        ("treasure_choice", "choose"): 0,
        # S23-only actions in season-namespaced templates.
        ("nine_tail_mark", "mark"): 1,
        ("nine_tail_vote_mark", "mark"): 1,
        ("nine_tail_kill", "kill"): 1,
        ("nine_tail_skill", "attempt"): 2,
        ("whiteze_clear", "clear"): 1,
        ("whiteze_clear_mark", "clear"): 1,
        ("whiteze_clear_mark", "clear_mark"): 1,
        ("magic_duel_magician_swap", "swap"): 2,
        ("magic_duel_wolf_sorcerer_swap", "swap"): 2,
        ("sorcerer_exchange", "exchange"): 2,
        ("wolf_shot", "shoot"): 2,
    }
    minimum_target_counts = {
        ("sheriff_candidates", "register"): 1,
        ("night_deaths", "die"): 1,
        ("nine_tail_hunt", "hunt"): 1,
    }
    for round_ in value["rounds"]:
        for phase in ["night", "day"]:
            slots = board[phase+"_slots"]
            events = round_[phase]
            event_codes = [e.get("slot") for e in events]
            slot_codes = [s["code"] for s in slots]
            ended_inside_phase = (
                value.get("season") == "S23" and board.get("code") == "s23_qingqiu_night" and
                phase == "day" and bool(events) and event_codes[-1] == "game_end" and
                events[-1].get("action") != "unknown" and event_codes == slot_codes[:len(event_codes)]
            )
            if event_codes != slot_codes and not ended_inside_phase:
                raise ReviewError("每轮事件槽位和排列必须与版型模板完全相同")
            for event, slot in zip(events, slots):
                if set(event) != {"slot", "action", "actor", "targets", "result", "start_seat", "direction", "votes", "random_point", "speech_scope", "availability", "effects"}:
                    raise ReviewError("事件必须使用固定字段，不能附加自由描述")
                if event["action"] not in slot["actions"]:
                    raise ReviewError("事件动作不属于槽位")
                actor = event["actor"]
                if actor is not None:
                    if type(actor) is not int or actor not in by_seat:
                        raise ReviewError("行动座位越界")
                    actor_role = by_seat[actor].get("role")
                    expected_role = slot["actor_role"]
                    if actor_role is not None:
                        if expected_role and expected_role != "狼队" and expected_role != actor_role and not (slot["code"] == "self_destruct" and actor_role in WOLF_ROLES):
                            raise ReviewError("行动者身份与版型槽位不符")
                        treasure_wolf = (value["board"] in {"treasure_master", "s23_treasure_master"} and actor_role == "盗宝大师"
                                         and by_seat[actor].get("faction") == "werewolf")
                        if expected_role == "狼队" and actor_role not in WOLF_ROLES and not treasure_wolf:
                            raise ReviewError("狼刀行动者必须属于狼队")
                        if slot["code"] == "self_destruct" and event["action"] == "self_destruct" and actor_role not in WOLF_ROLES:
                            raise ReviewError("自爆者必须为狼人身份")
                        if slot["code"] == "self_destruct" and event["action"] == "self_destruct" and actor_role == "机械狼":
                            raise ReviewError("机械狼不能自爆")
                targets = event["targets"]
                if not isinstance(targets, list) or any(type(t) is not int or t not in by_seat for t in targets) or len(targets) != len(set(targets)):
                    raise ReviewError("目标座位重复或越界")
                if event["start_seat"] is not None and (type(event["start_seat"]) is not int or event["start_seat"] not in valid_seats):
                    raise ReviewError("发言起始座位越界")
                if event["direction"] is not None and event["direction"] not in {"forward", "reverse"}:
                    raise ReviewError("发言方向不合法")
                if event["action"] == "order" and (event["start_seat"] is None or event["direction"] not in {"forward", "reverse"}):
                    raise ReviewError("发言顺序缺少起点或方向")
                if event["slot"] == "speech_order":
                    if event["action"] == "order" and event["speech_scope"] not in {"sheriff", "day"}:
                        raise ReviewError("发言顺序缺少警上或白天范围")
                    if event["random_point"] is not None:
                        if type(event["random_point"]) is not int or event["random_point"] not in valid_seats or event["action"] != "order":
                            raise ReviewError("随机点数不合法")
                    if event["action"] != "order" and any(event[k] is not None for k in ["start_seat", "direction", "random_point", "speech_scope"]):
                        raise ReviewError("没有发言环节时不能填写顺序")
                elif event["random_point"] is not None or event["speech_scope"] is not None:
                    raise ReviewError("随机点数和发言范围只属于发言顺序槽位")

                if event["availability"] is not None:
                    allowed_availability = {"learning", "locked", "available", "wrong_phase", "no_skill", "dead", "poisoned", "wolves_alive", "unknown"}
                    s23_availability = {"spent", "no_living_wolves", "unavailable"}
                    s23_record = value.get("season") == "S23" and board.get("code", "").startswith("s23_")
                    allowed = allowed_availability | (s23_availability if s23_record else set())
                    scoped_slot = event["slot"] in {"mechanical_action", "mechanical_day_skill"}
                    if event["availability"] not in allowed or (not scoped_slot and not s23_record):
                        raise ReviewError("事件发动条件不属于该赛季与槽位的正式编码")
                if not isinstance(event["effects"], list):
                    raise ReviewError("技能结算格式不合法")
                for effect in event["effects"]:
                    if (not isinstance(effect, dict) or set(effect) != {"kind", "intended_target", "dead_seat", "shield_actor"} or
                            not isinstance(effect["kind"], str) or effect["kind"] not in valid_effects or
                            type(effect["intended_target"]) is not int or effect["intended_target"] not in targets or
                            (effect["dead_seat"] is not None and (type(effect["dead_seat"]) is not int or effect["dead_seat"] not in valid_seats)) or
                            (effect["shield_actor"] is not None and (type(effect["shield_actor"]) is not int or effect["shield_actor"] not in valid_seats))):
                        raise ReviewError("技能结算与已记录目标不一致")
                    dead, shield = effect['dead_seat'], effect['shield_actor']
                    effect_valid = {
                        'poison_death': event['action'] == 'poison' and dead is not None and dead == effect['intended_target'] and shield is None,
                        'poison_reflected': event['action'] == 'poison' and dead is not None and dead == event['actor'] and shield is not None,
                        'poison_unresolved': event['action'] == 'poison' and dead is None and shield is None,
                        'shield_bypassed': event['action'] == 'attack' and dead is None and shield is not None,
                    }
                    if not effect_valid[effect['kind']]:
                        raise ReviewError("技能结算类型与死亡者或护盾不一致")

                target_key = (event["slot"], event["action"])
                if event["action"] == "invalid_exchange" and (event["result"] != "disqualified_repeat_target" or actor is None):
                    raise ReviewError("违规换位须保留行动者，并明确记录重复选人的判离裁定")
                if target_key in fixed_target_counts:
                    expected_count = fixed_target_counts[target_key]
                    if (value.get("season") == "S23" and board.get("code", "").startswith("s23_")
                            and target_key == ("badge", "hold")):
                        # S23 marks the holder in actor and uses an empty target;
                        # keep the S22 transfer/hold contract untouched.
                        expected_count = 0
                    if len(targets) != expected_count:
                        if expected_count == 0:
                            raise ReviewError("该动作不应填写座位目标")
                        raise ReviewError(f"{event['slot']}/{event['action']}必须有且仅有{expected_count}个目标座位；当前{len(targets)}个")
                elif target_key in minimum_target_counts:
                    if len(targets) < minimum_target_counts[target_key]:
                        raise ReviewError("该槽位动作缺少操作目标")
                elif targets:
                    raise ReviewError("未发生或未知的动作不能填写操作目标")
                if event["slot"] == "treasure_choice" and event["action"] == "choose":
                    role_pool = board.get("role_pool")
                    if not isinstance(role_pool, dict) or not isinstance(event["result"], str) or event["result"] not in role_pool:
                        raise ReviewError("盗宝大师选择的角色不属于版型候选牌")
                if event["action"] == "vote" and not event["votes"]:
                    raise ReviewError("已发生的投票需要逐人票型")
                if not isinstance(event["votes"], list):
                    raise ReviewError("票型格式不合法")
                seen = set()
                for vote in event["votes"]:
                    if (not isinstance(vote, dict) or set(vote) != {"round", "voter", "target", "abstained"} or
                            type(vote["round"]) is not int or type(vote["voter"]) is not int or
                            vote["voter"] not in by_seat or vote["round"] < 1):
                        raise ReviewError("票型重复或投票者越界")
                    key = (vote["round"], vote["voter"])
                    if key in seen:
                        raise ReviewError("票型重复或投票者越界")
                    seen.add(key)
                    if vote["abstained"] != (vote["target"] is None):
                        raise ReviewError("弃票与未知不能混用")
                    if vote["target"] is not None and (type(vote["target"]) is not int or vote["target"] not in by_seat):
                        raise ReviewError("投票目标越界")

    commentators = value["commentators"]
    if not isinstance(commentators, list) or any(not isinstance(name, str) or not name.strip() for name in commentators) or len(set(commentators)) != len(commentators):
        raise ReviewError("解说名单重复或姓名不合法")
    referee = value["referee"]
    if referee is not None and (not isinstance(referee, str) or not referee.strip()):
        raise ReviewError("法官姓名不合法")
    if len({f["role"] for f in value["files"]}) != len(value["files"]):
        raise ReviewError("每类源文件只登记一个当前文件")
    if check_files:
        for file in value["files"]:
            data_file(file["path"])
    if check_rules:
        from formal_rule_checks import issues
        errors = [i for i in issues(value) if i["severity"] == "error"]
        if errors:
            raise ReviewError(errors[0]["message"])
    return board


def validate(value, check_files=True, *, allow_incomplete=False):
    if allow_incomplete:
        return validate_batch(value, check_files)
    # All boards share the structural contract. The original strict validator
    # below also resolves mechanical timing/effects and is specific to that board.
    board = validate_batch(value, check_files)
    if board["code"] != "mechanical_wolf_seer":
        return validate_complete_board(value, board)
    forbidden = {"evidence", "evidence_ids", "review", "review_state", "verification_status", "schema_version", "transcription_runs", "speech_turns"}
    def walk(node):
        if isinstance(node, dict):
            if forbidden & node.keys():
                raise ReviewError("当前对局格式不包含证据、转写版本或审核字段")
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(value)
    board = template(value["board"])
    seats = value["seats"]
    count = board["seat_count"]
    if sorted(p["seat"] for p in seats) != list(range(1, count+1)):
        raise ReviewError("座位必须完整且不重复")
    if dict(Counter(p["role"] for p in seats)) != board["role_counts"]:
        raise ReviewError("身份数量与版型不一致")
    roster = value["roster"]
    names = [p["name"] for p in seats if p["name"] is not None]
    if len(roster) != count or len(set(roster)) != count or len(names) != len(set(names)) or not set(names) <= set(roster):
        raise ReviewError("排班姓名或座位姓名不合法")
    by_seat = {p["seat"]: p for p in seats}
    for name,seat_number in game_rules()["fixed_seats"].items():
        if name in roster and by_seat.get(seat_number,{}).get("name")!=name:
            raise ReviewError(f"{name}在场时必须使用{seat_number}号座位")
    for p in seats:
        if p["faction"] != ("werewolf" if p["role"] in {"狼人", "机械狼"} else "good"):
            raise ReviewError("身份与阵营不一致")
        if p.get("learning_target") is not None and p["learning_target"] not in by_seat:
            raise ReviewError("学习目标越界")
        if p["role"]!="机械狼" and (p.get("learning_target") is not None or p.get("learned_role") is not None):
            raise ReviewError("只有机械狼可以登记学习结果")
        if p["role"]=="机械狼":
            target=p.get("learning_target")
            form=board["mechanical_forms"].get(p.get("learned_role"))
            if (target is None)!=(p.get("learned_role") is None):
                raise ReviewError("学习目标和学习形态必须同时填写")
            if target is not None and (target==p["seat"] or form is None or form["learned_from"]!=by_seat[target]["role"]):
                raise ReviewError("机械狼学习形态与学习目标身份不一致")
    numbers = [r["number"] for r in value["rounds"]]
    if numbers != list(range(1,len(numbers)+1)) or not numbers:
        raise ReviewError("轮次必须从1连续编号")
    for round_ in value["rounds"]:
        for phase in ["night", "day"]:
            slots = board[phase+"_slots"]
            events = round_[phase]
            if [e["slot"] for e in events] != [s["code"] for s in slots]:
                raise ReviewError("每轮事件槽位和排列必须与版型模板完全相同")
            for event, slot in zip(events,slots):
                if set(event)!={"slot","action","actor","targets","result","start_seat","direction","votes","random_point","speech_scope","availability","effects"}:
                    raise ReviewError("事件必须使用固定字段，不能附加自由描述")
                if event["action"] not in slot["actions"]:
                    raise ReviewError("事件动作不属于槽位")
                actor = event["actor"]
                if actor is not None:
                    if actor not in by_seat:
                        raise ReviewError("行动座位越界")
                    expected_role = slot["actor_role"]
                    if expected_role and expected_role != "狼队" and by_seat[actor]["role"] != expected_role and not (slot["code"]=="self_destruct" and by_seat[actor]["role"]=="机械狼"):
                        raise ReviewError("行动者身份与版型槽位不符")
                    if expected_role=="狼队" and by_seat[actor]["role"] not in {"狼人","机械狼"}:
                        raise ReviewError("狼刀行动者必须属于狼队")
                    if slot["code"]=="wolf_attack" and event["action"] in {"attack","pass"} and by_seat[actor]["role"]=="机械狼" and takeover_state(value,round_["number"])!="available":
                        raise ReviewError("其他狼人未全出局或存活信息未知，无法确认机械狼带刀")
                elif (phase=="night" and slot["actor_role"] not in {None,"狼队"}) or slot["code"]=="mechanical_day_skill":
                    raise ReviewError("夜间角色槽位必须指定行动者")
                if len(event["targets"]) != len(set(event["targets"])) or any(t not in by_seat for t in event["targets"]):
                    raise ReviewError("目标座位重复或越界")
                if event["start_seat"] is not None and event["start_seat"] not in by_seat:
                    raise ReviewError("发言起始座位越界")
                if event["action"] == "order" and (event["start_seat"] is None or event["direction"] not in {"forward", "reverse"}):
                    raise ReviewError("发言顺序缺少起点或方向")
                if event["slot"]=="speech_order":
                    if event["action"]=="order" and event["speech_scope"] not in {"sheriff","day"}:
                        raise ReviewError("发言顺序缺少警上或白天范围")
                    if event["random_point"] is not None:
                        point=event["random_point"]
                        if type(point) is not int or point not in by_seat or event["action"]!="order":
                            raise ReviewError("随机点数不合法")
                        if event["start_seat"]!=speech_start_for_event(value,round_["number"],event):
                            raise ReviewError("发言起点未按随机点数跳过未参加发言的座位")
                    if event["action"]!="order" and any(event[k] is not None for k in ["start_seat","direction","random_point","speech_scope"]):
                        raise ReviewError("没有发言环节时不能填写顺序")
                elif event["random_point"] is not None or event["speech_scope"] is not None:
                    raise ReviewError("随机点数和发言范围只属于发言顺序槽位")
                if event["slot"]=="mechanical_knife_status":
                    inferred=inferred_takeover_state(value,round_["number"])
                    expected={"available":"carrying","wolves_alive":"not_carrying","dead":"unavailable","unknown":"unknown"}[inferred]
                    if event["action"]!=expected:
                        raise ReviewError("夜间带刀确认与上帝视角的狼人出局情况不一致")
                if event["effects"]!=(derived_effects(value,round_["number"]).get(event["slot"],[]) if phase=="night" else []):
                    raise ReviewError("技能结算与规则不一致：毒药反弹时女巫死亡，机械双刀技能刀无视守卫的盾")
                if event["slot"] in {"mechanical_action","mechanical_day_skill"}:
                    state=mechanical_skill_state(value,round_["number"],phase)
                    if event["availability"]!=state:
                        raise ReviewError("机械技能状态与学习时点、形态或其他狼人存活情况不一致")
                    if event["action"]=="learn":
                        mech=mechanical_player(value)
                        if state!="learning" or event["targets"]!=[mech["learning_target"]] or event["result"]!=mech["learned_role"]:
                            raise ReviewError("机械狼学习事件与学习结果不一致")
                    elif state=="available":
                        allowed=board["mechanical_forms"][mechanical_player(value)["learned_role"]]["actions"]
                        if event["action"] not in allowed+["pass","unknown"]:
                            raise ReviewError("机械技能已解锁，不能记为不适用或使用其他形态技能")
                    elif state=="locked" and (learning_round(value) is None or round_["number"]<learning_round(value)):
                        if event["action"] not in {"pass","unavailable","unknown"}:
                            raise ReviewError("机械狼尚未学习，不能发动模仿技能")
                    elif event["action"]!=("unknown" if state=="unknown" else "unavailable"):
                        raise ReviewError("机械技能尚未解锁、时段不符、已中毒或其他狼人未全出局，不能发动")
                elif event["availability"] is not None:
                    raise ReviewError("只有机械狼技能槽位保存发动条件")
                if event["slot"]=="hunter_state" and event["action"]!=hunter_skill_state(value,round_["number"]):
                    raise ReviewError("猎人技能状态与女巫或机械女巫用毒情况不一致")
                if event["slot"]=="hunter_shot" and event["action"]=="shoot" and hunter_skill_state(value,round_["number"])!="can_shoot":
                    raise ReviewError("猎人中毒或已出局，不能开枪")
                target_actions = {"guard","attack","save","poison","check","learn","shoot","register","die","exile","elected","transfer","hold"}
                if event["action"] not in target_actions and event["targets"]:
                    raise ReviewError("未发生或未知的动作不能填写操作目标")
                if event["action"] in target_actions and not event["targets"]:
                    raise ReviewError("事件缺少操作目标")
                if event["action"] in {"guard","save","poison","check","learn","shoot","elected","transfer","hold"} and len(event["targets"]) != 1:
                    raise ReviewError("该动作必须有且仅有一个目标")
                if event["action"]=="attack" and len(event["targets"])!=1:
                    raise ReviewError("普通狼刀与机械双刀技能刀各自记录一个目标")
                if event["action"] in {"guard","save","poison","check","learn","shoot","self_destruct"} and actor is None:
                    raise ReviewError("事件缺少行动者")
                if event["action"] == "self_destruct" and by_seat[actor]["role"] not in {"狼人","机械狼"}:
                    raise ReviewError("自爆者必须为狼人身份")
                if event["action"] == "vote" and not event["votes"]:
                    raise ReviewError("已发生的投票需要逐人票型")
                seen = set()
                for vote in event["votes"]:
                    key = (vote["round"],vote["voter"])
                    if key in seen or vote["voter"] not in by_seat or vote["round"] < 1:
                        raise ReviewError("票型重复或投票者越界")
                    seen.add(key)
                    if vote["abstained"] != (vote["target"] is None):
                        raise ReviewError("弃票与未知不能混用")
                    if vote["target"] is not None and vote["target"] not in by_seat:
                        raise ReviewError("投票目标越界")
        deaths=next(e for e in round_["day"] if e["slot"]=="night_deaths")
        poisoned={e["dead_seat"] for effects in poison_effects(value,round_["number"]).values() for e in effects if e["dead_seat"] is not None}
        if (deaths["action"]=="peaceful" and poisoned) or (deaths["action"]=="die" and not poisoned<=set(deaths["targets"])):
            raise ReviewError("夜间出局名单漏记实际中毒者；毒药反弹应记录女巫死亡")
    learns=[e for r in value["rounds"] for e in r["night"] if e["slot"]=="mechanical_action" and e["action"]=="learn"]
    if len(learns)>1 or (mechanical_player(value)["learned_role"] is not None and len(learns)!=1):
        raise ReviewError("一局机械狼只能学习一次，已知学习结果必须有学习事件")
    if not value["commentators"] or len(set(value["commentators"])) != len(value["commentators"]):
        raise ReviewError("解说名单为空或重复")
    if not isinstance(value["referee"],str) or not value["referee"].strip():
        raise ReviewError("缺少法官姓名")
    if len({f["role"] for f in value["files"]}) != len(value["files"]):
        raise ReviewError("每类源文件只登记一个当前文件")
    if check_files:
        for file in value["files"]:
            data_file(file["path"])
    from formal_rule_checks import issues
    errors = [i for i in issues(value) if i["severity"] == "error"]
    if errors:
        raise ReviewError(errors[0]["message"])
    return board


def validate_complete_board(value, board):
    """Complete metadata for every board, with dynamic roles kept dynamic."""
    seats = value["seats"]
    if any(p["role"] is None or p["faction"] is None or p["name"] is None for p in seats):
        raise ReviewError("完整录入需要全部座位的姓名、底牌和胜利阵营")
    if not board.get("dynamic_roles") and dict(Counter(p["role"] for p in seats)) != board["role_counts"]:
        raise ReviewError("身份数量与版型不一致")
    if board.get("dynamic_roles"):
        pool = board.get("role_pool", {})
        if any(role not in pool or amount > pool[role] for role, amount in Counter(p["role"] for p in seats).items()):
            raise ReviewError("实际发牌不属于候选牌池或超过候选牌数量")
    if len(value["roster"]) != board["seat_count"] or set(value["roster"]) != {p["name"] for p in seats}:
        raise ReviewError("排班姓名必须与全部在场座位一致")
    if not value["rounds"] or value.get("game_number") is None:
        raise ReviewError("完整录入需要局次和实际游戏轮次")
    if not value["commentators"] or not value["referee"]:
        raise ReviewError("完整录入需要解说和法官姓名")
    from formal_rule_checks import issues
    errors = [i for i in issues(value) if i["severity"] == "error"]
    if errors:
        raise ReviewError(errors[0]["message"])
    return board


def chinese(number):
    return {1:"一",2:"二",3:"三",4:"四",5:"五",6:"六",7:"七",8:"八",9:"九",10:"十"}.get(number,str(number))


def describe(value, round_number, phase, event):
    seats = {p["seat"]:p for p in value["seats"]}
    def person(seat):
        return f"{seat}号{seats[seat]['role']}" if seat is not None else ""
    prefix = "第"+chinese(round_number)+( "夜" if phase=="night" else "天白天")
    actor = person(event["actor"])
    if event["slot"] in {"mechanical_action","mechanical_day_skill"} and event["action"]!="learn" and event["actor"] is not None:
        actor=f"{event['actor']}号{seats[event['actor']]['learned_role'] or '机械狼'}"
    target = "、".join(person(t) for t in event["targets"])
    slot, action = event["slot"], event["action"]
    if slot=="guile_exchange" and action=="invalid_exchange":
        return prefix+actor+"尝试交换"+target+"，因重复选人被判离出局"
    if slot=="trade_decisions" and action in {"trade","betray","trade_betray","betray_trade"}:
        choices={"trade":("交易","交易"),"betray":("背叛","背叛"),"trade_betray":("交易","背叛"),"betray_trade":("背叛","交易")}[action]
        return prefix+"，".join(person(seat)+"选择"+choice for seat,choice in zip(event["targets"],choices))
    if action=="unknown":
        label = {"guard":"守护","wolf_attack":"击杀目标","witch_save":"解药","witch_poison":"毒药","hunter_state":"技能状态","mechanical_knife_status":"带刀状态","mechanical_action":"行动","mechanical_day_skill":"开枪情况","seer_check":"查验"}.get(slot)
        if label:
            text = ("狼队" if slot=="wolf_attack" else actor)+label+"未知"
        else:
            label = next(s["label"] for s in template(value["board"])[phase+"_slots"] if s["code"]==slot)
            text = label+"未知"
    elif action=="guard": text = actor+"自守" if event["actor"]==event["targets"][0] else actor+"守护"+target
    elif action=="attack":
        text = ("狼队" if slot=="wolf_attack" else actor+"技能刀")+"击杀"+target
        for effect in event["effects"]:
            if effect["kind"]=="shield_bypassed":
                text+="，无视"+person(effect["shield_actor"])+"的盾"
    elif action=="invalidated_by_dq": text = actor+"因DQ离场，狼刀判失效"
    elif action=="save": text = actor+"解救"+target
    elif action=="poison":
        effects=event["effects"]
        if effects and effects[0]["kind"]=="poison_reflected":
            shield=effects[0]["shield_actor"]
            text=actor+"对"+target+"用毒，毒药被"+f"{shield}号机械守卫"+"的盾反弹，"+actor+"死亡"
        elif effects and effects[0]["kind"]=="poison_unresolved":
            text=actor+"对"+target+"用毒，结算未知"
        else: text = actor+"毒杀"+target
    elif action=="check": text = actor+"查验"+target
    elif action=="learn": text = actor+"模仿"+target
    elif action=="can_shoot": text = actor+"可以开枪"
    elif action=="cannot_shoot": text = actor+"不能开枪"
    elif action=="carrying": text = actor+"已带刀"
    elif action=="not_carrying": text = actor+"未带刀"
    elif action=="shoot": text = actor+"开枪带走"+target
    elif action=="self_destruct": text = actor+"自爆"
    elif action=="die": text = target+"出局"
    elif action=="peaceful": text = "平安夜"
    elif action=="register": text = target+"上警"
    elif action=="elected": text = target+"当选警长"
    elif action=="deferred": text = "警长竞选延期"
    elif action=="continued": text = "延续警长竞选"
    elif action=="transfer": text = "警徽移交"+target
    elif action=="hold": text = target+"持有警徽"
    elif action=="order":
        text = (f"随机点数{event['random_point']}，" if event["random_point"] is not None else "")+"从"+person(event["start_seat"])+"开始"+("顺序" if event["direction"]=="forward" else "逆序")+"发言"
    elif action=="exile": text = target+"被放逐"
    elif action=="vote":
        text = "；".join(person(v["voter"])+("弃票" if v["abstained"] else "投票给"+person(v["target"])) for v in event["votes"])
    elif action=="pass":
        text = actor+{"guard":"未守护","wolf_attack":"空刀","witch_save":"未使用解药","witch_poison":"未使用毒药","hunter_shot":"未开枪","seer_check":"未查验","mechanical_action":"未行动","mechanical_day_skill":"未开枪"}.get(slot,"未行动")
        if slot=="wolf_attack": text="狼队空刀"
    elif action=="not_held": text = {"sheriff_vote":"未进行警长投票","exile_vote":"未进行放逐投票","speech_order":"未进入白天发言"}[slot]
    elif action=="none": text = {"sheriff_result":"无警长","badge":"无警徽","exile_result":"无人被放逐","self_destruct":"无狼人自爆"}[slot]
    elif action=="unavailable":
        text = {"sheriff_candidates":"无警长竞选","sheriff_vote":"无警长投票","sheriff_result":"无警长竞选","hunter_shot":actor+"未开枪","mechanical_action":actor+"未行动"}.get(slot,actor+"已出局")
        if slot in {"mechanical_action","mechanical_day_skill"}:
            text=actor+{"locked":"技能未解锁","wrong_phase":"无白天技能" if phase=="day" else "无夜间技能","no_skill":"无技能","dead":"已出局","poisoned":"中毒，不能开枪","wolves_alive":"尚未带刀，不能发动技能刀"}.get(event["availability"],"未行动")
    else: raise ReviewError("未定义事件描述模板")
    return prefix+text


def ensure_person(conn, name):
    if not isinstance(name, str) or not name.strip():
        raise ReviewError("人物姓名不能为空")
    person = conn.execute("INSERT INTO people(name) VALUES(%s) ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id", (name,)).fetchone()
    for alias in [name]+ALIASES.get(name,[]):
        existing = conn.execute("SELECT person_id FROM person_aliases WHERE alias=%s", (alias,)).fetchone()
        if existing and existing["person_id"]!=person["id"]:
            raise ReviewError("人物别名已属于其他人")
        conn.execute("INSERT INTO person_aliases(alias,person_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (alias,person["id"]))
    return person["id"]


def import_game(value, *, allow_incomplete=False, conn=None):
    from game_scope import exclusion_reason
    excluded = exclusion_reason(value)
    if excluded:
        raise ReviewError("该局已移出对局范围，禁止重新入库：" + excluded)
    board = validate(value, allow_incomplete=allow_incomplete)
    primary_file = primary_source_file(value["files"])
    transaction = connect() if conn is None else nullcontext(conn)
    with transaction as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("game-record-"+value["slug"],))
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("board-template-"+board["code"],))
        conn.execute("""INSERT INTO board_templates(code,name,seat_count,role_counts,wake_order) VALUES(%s,%s,%s,%s,%s)
            ON CONFLICT(code) DO UPDATE SET name=EXCLUDED.name,seat_count=EXCLUDED.seat_count,role_counts=EXCLUDED.role_counts,wake_order=EXCLUDED.wake_order""",
            (board["code"],board["name"],board["seat_count"],Jsonb(board.get("role_counts") or {}),board["wake_order"]))
        for phase in ["night","day"]:
            # Move existing positions clear before applying an expanded template.
            conn.execute("""UPDATE board_event_slots SET position=position+
                (SELECT COALESCE(max(position),0)+%s FROM board_event_slots WHERE board_code=%s AND phase=%s)
                WHERE board_code=%s AND phase=%s""",(len(board[phase+"_slots"])+1,board["code"],phase,board["code"],phase))
            for position,slot in enumerate(board[phase+"_slots"],1):
                conn.execute("""INSERT INTO board_event_slots(board_code,phase,code,position,label,actor_role,allowed_actions)
                    VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(board_code,phase,code) DO UPDATE SET
                    position=EXCLUDED.position,label=EXCLUDED.label,actor_role=EXCLUDED.actor_role,allowed_actions=EXCLUDED.allowed_actions""",
                    (board["code"],phase,slot["code"],position,slot["label"],slot["actor_role"],slot["actions"]))
        season = conn.execute("SELECT id FROM seasons WHERE code=%s", (value["season"],)).fetchone()
        if not season: raise ReviewError("赛季尚未登记")
        file_records=[]
        for file in value["files"]:
            source = conn.execute("SELECT id FROM sources WHERE platform=%s AND external_key=%s", (file["platform"],file["external_key"])).fetchone()
            if not source: raise ReviewError("先登记源资料，再导入游戏内容")
            file_records.append((file,source["id"],artifact(conn,source["id"],data_file(file["path"]),file["kind"])))
        source_id=next(s for f,s,_ in file_records if f["role"]==primary_file["role"])
        game=conn.execute("""INSERT INTO games(slug,season_id,primary_source_id) VALUES(%s,%s,%s)
            ON CONFLICT(slug) DO NOTHING RETURNING id""", (value["slug"],season["id"],source_id)).fetchone()
        if not game:
            game=conn.execute("SELECT id,season_id,primary_source_id FROM games WHERE slug=%s", (value["slug"],)).fetchone()
            if game["season_id"]!=season["id"] or game["primary_source_id"]!=source_id:
                raise ReviewError("同名对局已关联其他赛季或源文件")
        game_id=game["id"]
        # Replace only the current structured record of this game, in one transaction.
        conn.execute("DELETE FROM game_event_effects WHERE game_id=%s", (game_id,))
        conn.execute("DELETE FROM game_event_votes WHERE game_id=%s", (game_id,))
        conn.execute("DELETE FROM game_event_targets WHERE game_id=%s", (game_id,))
        conn.execute("DELETE FROM game_event_records WHERE game_id=%s", (game_id,))
        conn.execute("DELETE FROM game_rounds WHERE game_id=%s", (game_id,))
        conn.execute("DELETE FROM game_staff WHERE game_id=%s", (game_id,))
        conn.execute("DELETE FROM game_seats WHERE game_id=%s", (game_id,))
        conn.execute("DELETE FROM game_files WHERE game_id=%s", (game_id,))
        conn.execute("""INSERT INTO game_details(game_id,board_code,event_date,phase,episode,day_in_episode,game_number,winning_faction)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(game_id) DO UPDATE SET board_code=EXCLUDED.board_code,
            event_date=EXCLUDED.event_date,phase=EXCLUDED.phase,episode=EXCLUDED.episode,day_in_episode=EXCLUDED.day_in_episode,
            game_number=EXCLUDED.game_number,winning_faction=EXCLUDED.winning_faction""",
            (game_id,value["board"],value["date"],value["phase"],value.get("episode"),value.get("day_in_episode"),value.get("game_number"),value.get("winner")))
        names = value["roster"] + value["commentators"] + [seat["name"] for seat in value["seats"] if seat["name"] is not None] + [value["referee"],"豆儿啵","辉少"]
        identities={name:ensure_person(conn,name) for name in dict.fromkeys(name for name in names if name is not None)}
        for duty,names in [("commentator",value["commentators"]),("referee",[value["referee"]] if value["referee"] is not None else [])]:
            for position,name in enumerate(names,1):
                conn.execute("INSERT INTO game_staff(game_id,person_id,duty,position) VALUES(%s,%s,%s,%s)", (game_id,identities[name],duty,position))
        for seat in value["seats"]:
            conn.execute("""INSERT INTO game_seats(game_id,seat_number,person_id,role,faction,learning_target_seat,learned_role)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""", (game_id,seat["seat"],identities.get(seat["name"]),seat["role"],seat["faction"],seat.get("learning_target"),seat.get("learned_role")))
        for file,_,file_id in file_records:
            conn.execute("INSERT INTO game_files(game_id,file_role,artifact_id) VALUES(%s,%s,%s)", (game_id,file["role"],file_id))
        for round_ in value["rounds"]:
            number=round_["number"]
            conn.execute("INSERT INTO game_rounds(game_id,round_number) VALUES(%s,%s)", (game_id,number))
            for phase in ["night","day"]:
                for event in round_[phase]:
                    row=conn.execute("""INSERT INTO game_event_records(game_id,round_number,board_code,phase,slot_code,action,actor_seat,result_code,start_seat,direction,random_point,speech_scope,availability)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (game_id,number,value["board"],phase,event["slot"],event["action"],event["actor"],event["result"],event["start_seat"],event["direction"],event["random_point"],event["speech_scope"],event["availability"])).fetchone()
                    for position,effect in enumerate(event["effects"],1):
                        conn.execute("""INSERT INTO game_event_effects(event_id,game_id,position,kind,intended_target,dead_seat,shield_actor)
                            VALUES(%s,%s,%s,%s,%s,%s,%s)""",(row["id"],game_id,position,effect["kind"],effect["intended_target"],effect["dead_seat"],effect["shield_actor"]))
                    for position,target in enumerate(event["targets"],1):
                        conn.execute("INSERT INTO game_event_targets(event_id,game_id,position,seat_number) VALUES(%s,%s,%s,%s)", (row["id"],game_id,position,target))
                    for vote in event["votes"]:
                        conn.execute("INSERT INTO game_event_votes(event_id,game_id,ballot_round,voter_seat,target_seat,abstained) VALUES(%s,%s,%s,%s,%s,%s)", (row["id"],game_id,vote["round"],vote["voter"],vote["target"],vote["abstained"]))
        event_count = sum(len(round_[phase]) for round_ in value["rounds"] for phase in ("night", "day"))
        return {"game_id":str(game_id),"slug":value["slug"],"people":len(identities),"seats":len(value["seats"]),
                "rounds":len(value["rounds"]),"night_slots":len(board["night_slots"]),"day_slots":len(board["day_slots"]),
                "event_records":event_count,"source_files":len(value["files"])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file",type=Path)
    parser.add_argument("--check-only",action="store_true")
    parser.add_argument("--receipt",type=Path)
    args=parser.parse_args()
    value=json.loads(args.file.read_text(encoding="utf-8"))
    if args.check_only:
        validate(value)
        result={"valid":True,"slug":value["slug"]}
    else: result=import_game(value)
    if args.receipt:
        args.receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
