"""Known-rule checks for scored S22 boards; never infer an unobserved result."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from rule_config import load_formal_rules

ROOT = Path(__file__).resolve().parents[1]
DEPARTURE_OUTCOME_SLOTS = frozenset({
    "night_deaths", "exile_result", "hunter_shot", "wolf_king_shot",
    "self_destruct", "masked_delayed_death",
})


def registry():
    return load_formal_rules("S22", ROOT)


def has_unresolved_departures(round_):
    """Whether this day leaves a possible departure outcome unknown or unrecorded."""
    events = {e["slot"]: e for e in round_["day"]}
    return any(slot not in events or events[slot]["action"] == "unknown"
               for slot in DEPARTURE_OUTCOME_SLOTS)


def issues(value):
    """Return contradictions and unresolved prerequisites separately from evidence."""
    rules = registry()
    if value.get("season") != "S22" or value.get("board") not in rules["boards"]:
        return []
    board = value["board"]
    seats = {p["seat"]: p for p in value["seats"]}
    found = []

    def add(code, message, number=None, slot=None, severity="error"):
        found.append({"code": code, "severity": severity, "round": number,
                      "slot": slot, "message": message})

    def event(round_, slot):
        return next((e for phase in ("night", "day") for e in round_[phase]
                     if e["slot"] == slot), None)

    def known_action(e, action):
        return e is not None and e["action"] == action

    if value.get("winner") not in {None, "good", "werewolf"}:
        add("formal_winner", "S22正式局胜方为好人或狼人；个人胜利阵营不能作为第三方胜方")

    def departures(round_):
        # Only explicit departures; a shot alone does not prove its actor died.
        result = set()
        for e in round_["day"]:
            if e["action"] in {"die", "exile", "shoot", "die_after_speech", "suicide"}:
                result.update(e["targets"])
            if e["action"] == "self_destruct" and e["actor"] is not None:
                result.add(e["actor"])
        for e in round_["night"]:
            if e["slot"] == "guile_exchange" and e["action"] == "invalid_exchange" and e["result"] == "disqualified_repeat_target":
                result.add(e["actor"])
        return result

    rounds = value["rounds"]
    totals = Counter()
    previous = {}
    used = {"dancer_dance": set(), "warden_trade_targets": set(), "guile_exchange": set()}
    uncertain_guile_usage = set()
    mixed = next((p for p in seats.values() if p["role"] == "混血儿"), None)
    treasure = next((p for p in seats.values() if p["role"] == "盗宝大师"), None)
    mech = next((p for p in seats.values() if p["role"] == "机械狼"), None)
    model_factions = set()
    treasure_remainder = None
    uncertain_departure_history = False
    if board == "treasure_master" and all(p["role"] for p in seats.values()):
        pool = Counter({r["physical_identity"]: r["count"] for r in rules["boards"][board]["role_pool"]})
        dealt = Counter(p["role"] for p in seats.values())
        if dealt["盗宝大师"] != 1:
            add("treasure_presence", "盗宝大师版型必须有一名实际在场的盗宝大师")
        if not dealt - pool:
            treasure_remainder = pool - dealt
    for p in seats.values():
        if p["role"] == "混血儿" and p["faction"] not in {None, "good", "werewolf"}:
            add("personal_faction", "混血儿的个人胜利阵营只可为好人或狼人")
        if board == "treasure_master" and p["role"] == "盗宝大师" and p["faction"] not in {None, "werewolf"}:
            add("treasure_alignment", "盗宝大师始终属于狼人阵营，不随余牌或技能牌改变")
    departed = set()
    learned_at = next((r["number"] for r in rounds for e in r["night"]
                       if e["slot"] == "mechanical_action" and e["action"] == "learn"), None)
    for r in rounds:
        number = r["number"]
        current_departures = departures(r)
        save, poison = event(r, "witch_save"), event(r, "witch_poison")
        if known_action(save, "save") and known_action(poison, "poison"):
            add("witch_one_per_night", "普通女巫每夜最多使用一瓶药", number, "witch_save")
        for e, action in ((save, "save"), (poison, "poison")):
            if known_action(e, action):
                totals[e["slot"]] += 1
                limit = rules["shared_rules"]["ordinary_witch"]["antidote_count" if action == "save" else "poison_count"]
                if totals[e["slot"]] > limit:
                    add("potion_exhausted", "每种普通药全局只有一瓶（盗宝版毒师也只有一瓶毒）", number, e["slot"])
                if action == "save" and e["actor"] in e["targets"]:
                    add("witch_self_save", "普通女巫不能自救", number, e["slot"])

        for e in r["night"] + r["day"]:
            role = seats.get(e["actor"], {}).get("role")
            if e["slot"] == "self_destruct" and e["action"] == "self_destruct" and role == "机械狼":
                add("mechanical_self_destruct", "机械狼不能自爆", number, e["slot"])
            if e["slot"] == "wolf_attack" and e["action"] == "attack" and role == "混血儿":
                add("mixed_no_knife", "混血儿可以被狼刀杀死，但不能继承或执行狼刀", number, e["slot"])
            if e["slot"] in {"hunter_shot", "mechanical_day_skill", "wolf_king_shot"} and e["action"] == "shoot":
                if e["actor"] is not None and e["actor"] not in current_departures:
                    death = event(r, "night_deaths")
                    exile = event(r, "exile_result")
                    unknown = any(x and x["action"] == "unknown" for x in (death, exile))
                    add("shot_requires_departure", "死亡技能必须有本轮独立的出局触发记录", number, e["slot"],
                        "pending" if unknown else "error")
                if e["actor"] in departed:
                    add("departed_shooter", "此前已出局的玩家不能再次发动死亡技能", number, e["slot"])

        for slot in ("guard", "mechanical_action"):
            e = event(r, slot)
            if known_action(e, "guard"):
                if previous.get(slot) == (number - 1, tuple(e["targets"])):
                    add("guard_consecutive", "守卫可以自守，但不能连续两夜守护同一人", number, slot)
                previous[slot] = (number, tuple(e["targets"]))

        # Milk death is a confirmed mechanical-board interaction, not a full
        # simulator for exchange, dream, dance or trade target mapping.
        if board == "mechanical_wolf_seer":
            knife = event(r, "wolf_attack")
            if known_action(knife, "attack") and known_action(save, "save"):
                shields = [event(r, "guard"), event(r, "mechanical_action")]
                if knife["targets"] == save["targets"] and any(
                        known_action(s, "guard") and s["targets"] == knife["targets"] for s in shields):
                    deaths = event(r, "night_deaths")
                    if deaths["action"] != "unknown" and not set(knife["targets"]) <= set(deaths["targets"]):
                        add("guard_save_death", "守护与解药同保当夜刀口时目标死亡；机械盾暂按同一约定", number, "night_deaths")
            action = event(r, "mechanical_action")
            knife_status = event(r, "mechanical_knife_status")
            if knife_status["action"] in {"not_carrying", "unavailable"}:
                is_mechanical_knife = (known_action(knife, "attack") and mech and knife["actor"] == mech["seat"])
                if is_mechanical_knife or known_action(action, "attack"):
                    add("mechanical_takeover", "机械狼尚未接刀或已出局，不能执行普通狼刀或双刀技能刀", number, "mechanical_knife_status")
            check = event(r, "seer_check")
            if known_action(check, "check") and mech and mech["seat"] in check["targets"]:
                history = [event(prior, "mechanical_action") for prior in rounds if prior["number"] <= number]
                learning = next((e for e in history if e["action"] == "learn"), None)
                expected = None
                if learning:
                    expected = seats[learning["targets"][0]]["role"]
                elif all(e["action"] in {"pass", "unavailable"} for e in history):
                    expected = "双爪狼"
                feedback_roles = {"狼人", "通灵师", "女巫", "猎人", "守卫", "平民", "机械狼", "双爪狼"}
                if expected and check["result"] in feedback_roles and check["result"] != expected:
                    add("mechanical_seer_feedback", f"通灵师本夜查验机械狼应反馈{expected}；底牌仍为机械狼", number, "seer_check")
            if known_action(action, "learn"):
                totals["learn"] += 1
                if totals["learn"] > 1:
                    add("learning_once", "机械狼可以推迟学习，但全局只能学习一次", number, "mechanical_action")
                if mech:
                    if mech.get("learning_target") is not None and action["targets"] != [mech["learning_target"]]:
                        add("learning_target", "学习事件与登记的学习目标不一致", number, "mechanical_action")
                    canonical_forms = {"机械双刀狼", "机械通灵师", "机械女巫", "机械猎人", "机械守卫", "机械平民"}
                    if mech.get("learned_role") and action["result"] in canonical_forms and action["result"] != mech["learned_role"]:
                        add("learning_form", "学习事件与登记的学习形态不一致", number, "mechanical_action")
            if known_action(action, "poison"):
                totals["mechanical_poison"] += 1
                if totals["mechanical_poison"] > rules["shared_rules"]["mechanical_wolf"]["mechanical_witch"]["poison_count"]:
                    add("mechanical_poison_exhausted", "机械女巫全局只有一瓶毒", number, "mechanical_action")
            if action["action"] in {"attack", "guard", "poison", "check"}:
                if learned_at is not None and number <= learned_at:
                    add("mechanical_unlock", "学习当夜及之前不能发动模仿技能，夜间技能从学习后的下一夜解锁", number, "mechanical_action")
                elif learned_at is None:
                    add("unknown_learning_time", "发动模仿技能前需核实学习时点", number, "mechanical_action", "pending")
                forms = {"attack": "机械双刀狼", "guard": "机械守卫", "poison": "机械女巫", "check": "机械通灵师"}
                if mech and mech.get("learned_role") and mech["learned_role"] != forms[action["action"]]:
                    add("mechanical_form", "机械行动与学习形态不一致", number, "mechanical_action")
            day_skill = event(r, "mechanical_day_skill")
            if known_action(day_skill, "shoot") and mech:
                if mech.get("learned_role") not in {None, "机械猎人"}:
                    add("mechanical_hunter_form", "只有机械猎人形态可发动白天开枪", number, "mechanical_day_skill")
                if learned_at is not None and number < learned_at:
                    add("mechanical_hunter_unlock", "机械猎人须先学习，再在紧接白天或以后出局时触发", number, "mechanical_day_skill")

        if board == "mixed_blood":
            model = event(r, "mixed_blood_model")
            if known_action(model, "choose"):
                totals["model"] += 1
                if number != 1 or totals["model"] > 1:
                    add("first_night_model", "混血儿只在首夜选择一次榜样", number, "mixed_blood_model")
                if mixed and mixed["seat"] in model["targets"]:
                    add("model_self", "混血儿不能选择自身作为榜样", number, "mixed_blood_model")
                target = seats[model["targets"][0]]
                if mixed and mixed["faction"] and target["faction"] and mixed["faction"] != target["faction"]:
                    add("model_faction", "混血儿个人胜利阵营应跟随榜样", number, "mixed_blood_model")
            for slot in ("mixed_blood_alignment", "mixed_blood_victory"):
                e = event(r, slot)
                if e["action"] in {"good", "wolf"}:
                    faction = {"good": "good", "wolf": "werewolf"}[e["action"]]
                    model_factions.add(faction)
                    if mixed and mixed["faction"] and faction != mixed["faction"]:
                        add("mixed_alignment", "混血儿阵营投影与座位的个人胜利阵营不一致", number, slot)
            check = event(r, "seer_check")
            if known_action(check, "check") and mixed and mixed["seat"] in check["targets"]:
                if check["result"] not in {None, "good", "好人", "金水"}:
                    add("mixed_seer_good", "预言家查验混血儿始终反馈好人", number, "seer_check")
            white = event(r, "white_god_reveal")
            exile = event(r, "exile_result")
            if known_action(white, "reveal") and white["actor"] is not None:
                if exile["action"] != "unknown" and not (exile["action"] == "exile" and white["actor"] in exile["targets"]):
                    add("white_exile", "白神被放逐后翻牌并直接出局，需有对应放逐结果", number, "white_god_reveal")

        for slot in ("masquerade_verify", "masquerade_mask", "treasure_choice"):
            e = event(r, slot)
            if e and e["action"] in {"verify", "give_mask", "choose"}:
                selected = e["result"] if slot == "treasure_choice" else tuple(e["targets"])
                if previous.get(slot) == (number - 1, selected):
                    add("consecutive_target", "该技能不能连续两夜选择同一目标或牌", number, slot)
                previous[slot] = (number, selected)
        for slot, action in (("dancer_dance", "dance"), ("warden_trade_targets", "select_pair"), ("guile_exchange", "exchange")):
            e = event(r, slot)
            if not e:
                continue
            if slot == "guile_exchange" and e["action"] == "invalid_exchange":
                if not used[slot] & set(e["targets"]):
                    add("unproven_repeat_ruling", "重复选人的判离裁定缺少此前选人记录", number, slot, "pending")
                previous[slot] = (number, e["action"])
                continue
            if e["action"] == action:
                if slot in {"dancer_dance", "warden_trade_targets"} and number == 1:
                    add("second_night_skill", "共舞和交易从第二夜起开放", number, slot)
                if used[slot] & set(e["targets"]) or (slot == "guile_exchange" and uncertain_guile_usage & set(e["targets"])):
                    # Same-pair cancellation may have unresolved consumption.
                    magician = event(r, "magician_exchange")
                    cancellation = slot == "guile_exchange" and magician and magician["action"] == "exchange" and set(magician["targets"]) == set(e["targets"])
                    add("once_per_participant", "该技能每名玩家全局只能参加一次；抵消耗次边界另核", number, slot,
                        "pending" if cancellation or (slot == "guile_exchange" and uncertain_guile_usage & set(e["targets"])) else "error")
                magician = event(r, "magician_exchange")
                if slot == "guile_exchange" and magician and magician["action"] == "exchange" and set(magician["targets"]) == set(e["targets"]):
                    uncertain_guile_usage.update(e["targets"])
                else:
                    used[slot].update(e["targets"])
            if slot == "guile_exchange" and e["action"] == "pass" and previous.get(slot) == (number - 1, "pass"):
                add("guile_consecutive_pass", "诡术师不能连续两夜空过", number, slot)
            previous[slot] = (number, e["action"])
        prince = event(r, "sequential_prince_skill")
        if prince and prince["action"] == "reveal":
            totals["prince"] += 1
            if totals["prince"] > 1:
                add("prince_once", "定序王子翻牌技能全局最多一次", number, prince["slot"])
        if board == "all_in":
            pair = event(r, "warden_trade_targets")
            choice = event(r, "trade_decisions")
            if choice["action"] in {"trade", "betray", "trade_betray", "betray_trade"}:
                if pair["action"] == "select_pair" and choice["targets"] != pair["targets"]:
                    add("trade_participant_order", "交易选择的两个目标必须按交易双方顺序记录", number, "trade_decisions")
        if board == "treasure_master":
            knife = event(r, "wolf_attack")
            if number == 1 and knife["action"] in {"attack", "pass"}:
                add("treasure_first_night_forbidden", "盗宝大师首夜规则禁刀，不能记狼刀或主动空刀", number, "wolf_attack")
            takeover = rules["boards"][board]["board_rules"]["ordinary_wolf_knife_takeover"]
            if (number > 1 and treasure and knife["actor"] == treasure["seat"]
                    and knife["action"] in {"attack", "pass"}):
                initial_wolves_not_departed = any(
                    p["role"] in takeover["after_all_identity_roles_departed"] and p["seat"] not in departed
                    for p in seats.values()
                )
                unknown_roles = any(p["role"] is None for p in seats.values())
                if initial_wolves_not_departed:
                    if unknown_roles or uncertain_departure_history:
                        add("treasure_knife_timing_unknown", "身份或此前出局记录不完整，暂不能确认盗宝大师接刀时点",
                            number, "wolf_attack", "pending")
                    else:
                        add("treasure_knife_timing", "除盗宝大师外的初始狼队成员（狼人、狼王）尚未全部出局，不能接替普通狼刀",
                            number, "wolf_attack")
                elif unknown_roles:
                    add("treasure_knife_timing_unknown", "仍有身份未知，暂不能确认其他初始狼队成员均已出局后的接刀时点",
                        number, "wolf_attack", "pending")
            choice = event(r, "treasure_choice")
            if known_action(choice, "choose") and treasure_remainder is not None and not treasure_remainder[choice["result"]]:
                add("treasure_remaining_choice", "盗宝大师每夜只能选择三张实际余牌中的牌", number, "treasure_choice")
        if board == "neighbor_puppet":
            puppet = event(r, "puppet_select")
            if known_action(puppet, "select"):
                totals["puppet"] += 1
                if number != 1 or totals["puppet"] > 1:
                    add("first_night_puppet", "傀儡只在首夜选择一次", number, "puppet_select")
                target = puppet["targets"][0]
                adjacent = {(target - 2) % len(seats) + 1, target % len(seats) + 1}
                neighboring_roles = {seats[s]["role"] for s in adjacent}
                if None not in neighboring_roles and not neighboring_roles & {"狼人", "狼王"}:
                    add("puppet_adjacency", "傀儡必须与至少一名狼人座位相邻，1号和12号相邻", number, "puppet_select")
        if board == "treasure_master" and has_unresolved_departures(r):
            uncertain_departure_history = True
        departed.update(current_departures)
    if len(model_factions) > 1:
        add("mixed_alignment_changed", "混血儿胜利阵营不能在局中改变")
    return found


def final_gaps(value):
    """A final entry must explicitly resolve unknowns, not substitute defaults."""
    gaps = []
    for key in ("date", "game_number", "winner", "referee"):
        if value.get(key) is None:
            gaps.append(key)
    if not value.get("rounds"):
        gaps.append("rounds")
    for p in value["seats"]:
        for key in ("name", "role", "faction"):
            if p.get(key) is None:
                gaps.append(f"seat[{p['seat']}].{key}")
    for r in value["rounds"]:
        for phase in ("night", "day"):
            for e in r[phase]:
                if e["action"] == "unknown":
                    gaps.append(f"round[{r['number']}].{phase}.{e['slot']}")
    return gaps
