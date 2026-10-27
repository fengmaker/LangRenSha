"""Reconcile announced voting outcomes with the independent referee recap."""
from collections import Counter, defaultdict
import re


def reconcile(facts, audit, dossier):
    """Change days only when a unique recap outcome identifies the same event."""
    changes = []
    exile_days, explosion_days = defaultdict(list), defaultdict(list)
    for r in dossier.get("rounds", []):
        for e in r.get("day", []):
            if e["slot"] == "exile_result" and e["action"] == "exile" and len(e["targets"]) == 1:
                exile_days[e["targets"][0]].append(r["number"])
            if e["action"] == "self_destruct" and e.get("actor"):
                explosion_days[e["actor"]].append(r["number"])
    for b in facts["ballots"]:
        if b["kind"] != "exile":
            continue
        days = exile_days.get(b.get("winner"), [])
        if len(days) == 1 and b["day"] != days[0]:
            changes.append({"target": b["id"], "field": "day", "before": b["day"], "after": days[0],
                            "reason": "投票结束播报的出局座位与法官复盘该日唯一放逐座位一致。"})
            b["day"] = days[0]
    # PK and a skill-triggered revote stay with the preceding vote of that day.
    for i, b in enumerate(facts["ballots"]):
        if b["stage"] not in {"pk", "revote"} or not i:
            continue
        prev = facts["ballots"][i-1]
        if prev["kind"] != b["kind"]:
            continue
        if b["stage"] == "pk" and (not prev["tied_candidates"] or prev["tied_candidates"] != b["candidates"]):
            continue
        anchored = [x for x in (prev, b) if len(exile_days.get(x.get("winner"), [])) == 1]
        if len(anchored) == 1:
            other = b if anchored[0] is prev else prev
            if other["day"] != anchored[0]["day"]:
                changes.append({"target": other["id"], "field": "day", "before": other["day"],
                                "after": anchored[0]["day"], "reason": "相邻PK或技能重投与同一日的已核放逐结果衔接。"})
                other["day"] = anchored[0]["day"]
    for x in facts["interruptions"]:
        days = explosion_days.get(x["actor"], [])
        if len(days) == 1 and x["day"] != days[0]:
            changes.append({"target": x["id"], "field": "day", "before": x["day"], "after": days[0],
                            "reason": "自爆座位与法官复盘的唯一自爆记录一致。"})
            x["day"] = days[0]
    count = Counter()
    for b in facts["ballots"]:
        count[b["day"], b["kind"]] += 1
        b["number"] = count[b["day"], b["kind"]]
        if b["number"] == 1 and b["stage"] == "unknown":
            b["stage"] = "initial"
    maximum = max([r["number"] for r in dossier.get("rounds", [])] +
                  [b["day"] or 0 for b in facts["ballots"]] + [d["day"] for d in facts["days"]] + [1])
    for day in range(1, maximum+1):
        d = next((d for d in facts["days"] if d["day"] == day), None)
        if d is None:
            d = {"day": day, "sheriff": "unknown"}
            facts["days"].append(d)
        exploded = bool(next((e for r in dossier.get("rounds", []) if r["number"] == day
                             for e in r.get("day", []) if e["action"] == "self_destruct"), None))
        exploded = exploded or any(x["day"] == day and x["ends_day"] for x in facts["interruptions"])
        d["exile"] = "recorded" if any(b["day"] == day and b["kind"] == "exile" for b in facts["ballots"]) else "interrupted_self_destruct" if exploded else "unknown"
    audit["day_crosscheck_changes"] = changes


def day_outcomes(facts, audit, dossier):
    """Keep day conclusions separate from whether individual votes were recovered."""
    rows = []
    by_day = {r["number"]: r for r in dossier.get("rounds", [])}
    for d in facts["days"]:
        day = d["day"]
        ballots = [b for b in facts["ballots"] if b["day"] == day and b["kind"] == "exile"]
        events = by_day.get(day, {}).get("day", [])
        explosion = next((e for e in events if e["action"] == "self_destruct"), None)
        explosion = explosion or next((x for x in facts["interruptions"] if x["day"] == day and x["ends_day"]), None)
        result = next((e for e in events if e["slot"] == "exile_result"), {})
        proof = [e for b in ballots for e in audit["evidence"].get(b["id"], [])]
        # Only a final judge announcement of a peaceful day or a recap's explicit
        # no-exile result establishes a tie day; never infer it from partial votes.
        final_text = proof[-1]["quote"] if proof else ""
        final_text = re.split(r"请(?:出|冲|举)(?:票|牌)|请投票", final_text)[-1]
        peaceful = bool(ballots and ((ballots[-1]["stage"] == "pk" and re.search(r"平安[日曰]", final_text)) or
                         (result.get("action") == "none" and "平票" in str(result.get("result", "")))))
        if peaceful:
            outcome, note = "peaceful_tie", "两轮投票均平票，平安日，无人被放逐。"
            if ballots[-1]["candidates"]:
                ballots[-1]["tied_candidates"] = list(ballots[-1]["candidates"])
        elif explosion and not ballots:
            outcome, note = "self_destruct", f"{explosion.get('actor') or '未知座位'}号狼人自爆，未进行放逐投票。"
        elif result.get("action") == "exile":
            outcome = "exiled"
            note = "、".join(str(n)+"号" for n in result["targets"]) + "被放逐。" + ("逐人票型待补录。" if not ballots else "")
        elif ballots:
            outcome, note = "recorded", "已记录放逐投票，结果待核。"
        else:
            outcome, note = "missing", "未见白天自爆记录，应有放逐投票环节；需交叉核对并补录票型或确认提前结束原因。"
        rows.append({"day": day, "outcome": outcome, "exile_note": note, "evidence": proof})
    return rows
