"""Audit current voting facts and build a dated, evidence-linked review queue."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

import batch_s22 as batch

REPORT = batch.REPORT_DIR / "S22_投票逐局核对.json"
CORRECTIONS = batch.ROOT / "data/extractions/S22/voting_review/accepted.json"
VIDEO_REVIEW = batch.ROOT / "data/extractions/S22/voting_review/video_checks.json"
UNRESOLVED = batch.ROOT / "data/extractions/S22/voting_review/unresolved.json"


def value_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def rebuild_days(facts):
    maximum = max([d["day"] for d in facts["days"]] + [x["day"] or 0 for x in facts["ballots"]] + [1])
    for day in range(1, maximum + 1):
        entry = next((d for d in facts["days"] if d["day"] == day), None)
        if entry is None:
            entry = {"day": day}
            facts["days"].append(entry)
        entry["sheriff"] = "recorded" if any(b["day"] == day and b["kind"] == "sheriff" for b in facts["ballots"]) else "unknown"
        entry["exile"] = "recorded" if any(b["day"] == day and b["kind"] == "exile" for b in facts["ballots"]) else "interrupted_self_destruct" if any(x["day"] == day and x["ends_day"] for x in facts["interruptions"]) else "unknown"
    ordinals = Counter()
    for b in facts["ballots"]:
        ordinals[b["day"], b["kind"]] += 1
        b["number"] = ordinals[b["day"], b["kind"]]
        voters = {v["voter"] for v in b["votes"]}
        if b["kind"] == "sheriff" and b["stage"] == "initial" and b["eligible_voters"] is None:
            registration = next((r for r in reversed(facts["registrations"]) if r["day"] == b["day"]), None)
            if registration and voters <= set(registration["off_police"]):
                b["eligible_voters"] = list(registration["off_police"])
        if b["stage"] == "pk" and b["candidates"] and b["eligible_voters"] is None:
            everyone_else = set(range(1,13)) - set(b["candidates"])
            if voters == everyone_else:
                b["eligible_voters"] = sorted(everyone_else)
        b["unrecorded_voters"] = sorted(set(b["eligible_voters"]) - voters) if b["eligible_voters"] is not None else None
        b["status"] = "complete" if b["eligible_voters"] is not None and not b["unrecorded_voters"] else "partial"


def apply_accepted(facts, audit, entry):
    """Source-bound reviewed changes survive regeneration; a changed baseline fails closed."""
    if not CORRECTIONS.is_file():
        return
    corrections = batch.read_json(CORRECTIONS)
    changes = []
    for change in corrections.get("items", []):
        if change["bvid"] != entry["bvid"]:
            continue
        if change["source_sha256"] != batch.digest(batch.ROOT / entry["source_path"]):
            raise ValueError("投票核对依据的转写已变化：" + entry["bvid"])
        if change["target"] == "registration":
            r = change["after"]
            if not any(x["on_police"] == r["on_police"] and x["off_police"] == r["off_police"] and x["day"] == r["day"] for x in facts["registrations"]):
                r = {**r, "id": f"registration-review-{change['id']}"}
                facts["registrations"].append(r)
                audit["evidence"][r["id"]] = change["evidence"]
        else:
            ballot = next(b for b in facts["ballots"] if b["id"] == change["target"])
            if change.get("ballot_start_ms") is not None:
                start = audit["evidence"][ballot["id"]][0]["start_ms"]
                if abs(start - change["ballot_start_ms"]) > 1000:
                    raise ValueError("投票轮定位已变化，请重新核对更正对象：" + change["id"])
            old_voters = {v["voter"] for v in ballot["votes"]}
            for field, after in change["after"].items():
                before = change["before"][field]
                if ballot[field] != before and ballot[field] != after:
                    raise ValueError("投票核对更正与当前提取冲突：" + change["id"] + "." + field)
                ballot[field] = after
            audit["evidence"][ballot["id"]] += change["evidence"]
            if change.get("method") == "transcript_judge_correction" and "votes" in change["after"]:
                added = {v["voter"] for v in ballot["votes"]} - old_voters
                resolved = []
                for issue in audit["issues"]:
                    seats = re.search(r"\[([\d, ]+)\]", issue)
                    timestamp = re.match(r"(\d+)ms", issue)
                    belongs = timestamp and any(e["start_ms"] <= int(timestamp.group(1)) <= e["end_ms"] for e in audit["evidence"][ballot["id"]])
                    if belongs and seats and set(int(n) for n in seats.group(1).split(',')) <= added:
                        resolved.append(issue)
                audit.setdefault("resolved_issues", []).extend(resolved)
                audit["issues"] = [i for i in audit["issues"] if i not in resolved]
        changes.append(change)
    if changes:
        rebuild_days(facts)
        audit["review_changes"] = changes


def audit_game(entry, facts, audit, dossier, video_checks=None, unresolved_checks=None):
    questions = []
    departure_gaps = {}
    evidence = audit["evidence"]
    def add(code, day, title, reason, target=None, severity="pending", ev=None):
        key = target or ("day-" + str(day))
        question = {"id": f"vote-{entry['bvid']}-{key}-{code}", "code": code, "day": day,
                    "target": target, "title": title, "reason": reason, "severity": severity,
                    "evidence": ev if ev is not None else evidence.get(target, [])}
        questions.append(question)

    if not facts["registrations"]:
        add("registration_missing", 1, "首日警下名单待核", "尚未取得完整初始报名名单；退水后的候选人不能用来推导初始警下名单。")
    for b in facts["ballots"]:
        day, key = b["day"], b["id"]
        if day is None:
            add("day_unknown", None, "投票属于第几天待核", "已有逐人票，但日界证据不足，不能按投票顺序直接编号游戏日。", key, "question")
        if b["kind"] == "unknown":
            add("kind_unknown", day, "警徽票或放逐票待核", "尚未找到足够的法官阶段口令，需要看前后文或原视频。", key, "question")
        if b["stage"] == "unknown":
            add("stage_unknown", day, "本次投票衔接待核", "现有证据还不足以确定是否有平票前投票或技能重投；需要核对前后投票及发言衔接。", key, "question")
        if b["unrecorded_voters"]:
            add("votes_missing", day, "票权或默认弃票处理待核", "仍未处理的有票权座位：" + "、".join(str(n) + "号" for n in b["unrecorded_voters"]) + "；按用户确认口径，没有明确投向应记默认弃票。", key)
        elif b["eligible_voters"] is None and not any(i.get("target") == key and i["code"] == "living_voter_conflict" for i in audit.get("rule_issues", [])):
            row = next((r for r in (audit.get("game_flow") or {}).get("rounds", []) if r["day"] == day), {})
            gaps = row.get("roster_gaps", []) if b["kind"] == "exile" else []
            if gaps:
                gap = gaps[0]
                gap_key = (gap["round"], gap["slot"])
                if gap_key not in departure_gaps:
                    label = {"night_deaths": "前夜死亡播报", "exile_result": "放逐或白天结束结果",
                             "hunter_shot": "猎人死亡技能结果", "mechanical_day_skill": "机械猎人死亡技能结果",
                             "wolf_king_shot": "狼王死亡技能结果", "round": "阶段记录"}[gap["slot"]]
                    add("departure-" + gap["slot"], gap["round"], f"第{gap['round']}天{label}待补充",
                        "需补充这项原文出局信息，之后自动重算存活与票权，无需人工计算票数。受影响投票：", severity="pending")
                    departure_gaps[gap_key] = questions[-1]
                q = departure_gaps[gap_key]
                q["reason"] += f"第{day}天（{key}）；"
            else:
                add("eligibility_unknown", day, "本轮票权名单待补充", f"已提取{len(b['votes'])}条票，但完整票权名单未知；需补齐警下等票权依据，随后自动计算。", key)
        if b["stage"] == "pk":
            prior = [p for p in facts["ballots"] if p["day"] == day and p["kind"] == b["kind"] and p["number"] < b["number"]]
            if not prior:
                add("pk_first_missing", day, "平票前的票型未记录", "原文明确为PK后投票，现档案尚缺平票前的票型。", key, "question")
        if b["day"] is not None and b["day"] > len(dossier["rounds"]) and dossier["rounds"]:
            add("round_disagreement", day, "游戏日与原档案轮数不一致", "全文日界与原复盘档案的轮数需要交叉核对，不能仅取较大的数字。", key, "question")
        # A seat that was definitely eliminated on a prior day cannot cast
        # a later ballot. This is a contradiction check, not survivor inference.
        departed = set()
        for r in dossier["rounds"]:
            if day is None or r["number"] >= day:
                continue
            for event in r["day"]:
                if event["action"] in {"die", "shoot", "exile"}:
                    departed.update(event["targets"])
                if event["action"] == "self_destruct" and event["actor"] is not None:
                    departed.add(event["actor"])
        impossible = sorted(departed & {v["voter"] for v in b["votes"]})
        if impossible:
            add("departed_voter", day, "票型与先前出局信息冲突", "此前档案已记录出局、此轮却出现投票的座位：" + str(impossible) + "。需核对日序、座号或原出局记录。", key, "question")

    for text in audit.get("issues", []):
        stamp = re.match(r"(\d+)ms", text)
        ms = int(stamp.group(1)) if stamp else None
        candidates = [(abs(evidence[b["id"]][0]["start_ms"] - ms), b) for b in facts["ballots"]] if ms is not None else []
        b = min(candidates, key=lambda x:x[0])[1] if candidates else None
        add("source_conflict-" + hashlib.sha256(text.encode()).hexdigest()[:8], b["day"] if b else None,
            "播票原文存在冲突", text, b["id"] if b else None, "question")
    for issue in audit.get("rule_issues", []):
        existing = next((q for q in questions if issue.get("target") and q["target"] == issue["target"] and q["code"].startswith("source_conflict")), None)
        if existing:
            existing["reason"] += "\n规则核对：" + issue["reason"]
        else:
            add("rule-" + issue["code"], issue.get("day"), "投票与已确认规则需要核对", issue["reason"], issue.get("target"), "question")
    for d in facts["days"]:
        known_not_held = any(r["number"] == d["day"] and any(e["slot"] == "exile_vote" and e["action"] == "not_held" for e in r["day"]) for r in dossier["rounds"])
        exploded = any(r["number"] == d["day"] and any(e["action"] == "self_destruct" for e in r["day"]) for r in dossier["rounds"])
        if exploded and d["exile"] == "recorded":
            add("self_destruct_with_exile", d["day"], "自爆日出现放逐票，需核对日序", "复盘记录该日狼人自爆，票型却归于同一天；需确认投票日期或自爆发生顺序。", severity="question")
        if d["exile"] == "unknown" and not known_not_held:
            add("exile_unrecorded", d["day"], "本日放逐投票待补录", "未见该日白天狼人自爆记录，应有放逐投票环节；目前缺少可用票型，需结合复盘与出局记录确认漏票、日序或提前结束原因。")
        elif d["exile"] == "unknown" and known_not_held and not exploded:
            add("not_held_without_self_destruct", d["day"], "未投票原因需要交叉复核", "原档案记为未举行投票，但未见白天自爆记录；需核对提前结束原因，不能据缺少票型认定没有投票。", severity="question")
    for check in (unresolved_checks or {}).get(entry["bvid"], []):
        b = next((b for b in facts["ballots"] if b["id"] == check["ballot_id"]), None)
        if b is None:
            continue
        existing = next((q for q in questions if q["target"] == b["id"] and (("stage" in check["field"] and q["code"] == "stage_unknown") or ("departed" in check["field"] and q["code"] == "departed_voter"))), None)
        if existing:
            existing["reason"] += "\n逐段核对：" + check["reason"]
        if "day" in check["field"]:
            add("day_disputed", b["day"], "当前游戏日仍需核对", check["reason"], b["id"], "question", check.get("evidence") or evidence.get(b["id"], []))
    # Review questions are evidence-backed flags, separate from fact completeness.
    videos = [dict(x) for x in (video_checks or {}).get(entry["bvid"], [])]
    for check in videos:
        if check.get("resolved"):
            continue
        resolved = next((d for d in audit.get("causal_review", {}).get("decisions", [])
                         if d["resolved"] and f"-{check['ballot_id']}-source_conflict-" in d["question_id"]), None)
        if resolved:
            check.update(resolved_by_causal=True, resolution=resolved["conclusion"] + "：" + resolved["reason"])
            continue
        b = next((b for b in facts["ballots"] if b["id"] == check["ballot_id"]), None)
        defaults = [s for a in audit.get("rule_applications", []) if a["target"] == check["ballot_id"] for s in a["voters"]]
        if b and defaults and not any(q["target"] == b["id"] and q["code"].startswith("source_conflict") for q in questions):
            check["resolved_by_rule"] = True
            check["resolution"] = "画面原先不足以确定的未报投向，现按用户确认口径记默认弃票：" + "、".join(map(str,defaults)) + "号。"
            continue
        existing = next((q for q in questions if q["target"] == check["ballot_id"] and q["severity"] == "question"), None)
        if existing:
            existing["reason"] += "\n原视频核对：" + check["finding"]
            existing["evidence"] = existing["evidence"] + check["evidence"]
            continue
        add("video_uncertain-" + check["id"], b["day"] if b else None, "已看原视频，仍需回听或更清晰画面",
            check["finding"], check["ballot_id"], "question", check["evidence"])
    from causal_voting_review import disposition
    questions, causal_decisions = disposition(questions, audit)
    days = []
    for day in sorted({d["day"] for d in facts["days"]} | {q["day"] for q in questions}, key=lambda n:(n is None,n or 0)):
        qs = [q for q in questions if q["day"] == day]
        known_not_held = any(r["number"] == day and any(e["slot"] == "exile_vote" and e["action"] == "not_held" for e in r["day"]) for r in dossier["rounds"])
        days.append({"day": day, "question_count": sum(q["severity"] == "question" for q in qs),
                     "pending_count": sum(q["severity"] == "pending" for q in qs), "question_ids": [q["id"] for q in qs],
                     "exile_note": next((x["exile_note"] for x in audit.get("day_outcomes", []) if x["day"] == day), None)})
    return {"bvid": entry["bvid"], "date": entry["date"], "game_number": entry["game_number"],
            "checked_by": "Codex", "method": "已做逐轮结构、来源及转写证据检查；逐项更正和原视频核对另列",
            "human_reviewed": False, "facts_sha256": value_hash(facts),
            "causal_decisions": causal_decisions,
            "question_count": sum(q["severity"] == "question" for q in questions),
            "pending_count": sum(q["severity"] == "pending" for q in questions),
            "questions": questions, "days": days, "video_checks": videos,
            "rule_applications": audit.get("rule_applications", []), "election_flow": audit.get("election_flow", []),
            "game_flow": audit.get("game_flow"), "eligibility_derivations": audit.get("eligibility_derivations", []),
            "day_crosscheck_changes": audit.get("day_crosscheck_changes", []), "day_outcomes": audit.get("day_outcomes", []),
            "accepted_changes": audit.get("review_changes", [])}


def build():
    from voting_records import validate
    state = batch.load_state()
    videos = batch.read_json(VIDEO_REVIEW).get("items", []) if VIDEO_REVIEW.is_file() else []
    video_map = defaultdict(list)
    for item in videos:
        video_map[item["bvid"]].append(item)
    unresolved_map = defaultdict(list)
    for item in batch.read_json(UNRESOLVED).get("items", []) if UNRESOLVED.is_file() else []:
        source = state["items"][item["bvid"]]["source_path"]
        if item["source_sha256"] != batch.digest(batch.ROOT / source):
            raise ValueError("待核记录的转写来源已变化：" + item["bvid"])
        unresolved_map[item["bvid"]].append(item)
    items = []
    for bvid, entry in state["items"].items():
        folder = batch.ROOT / entry["output_dir"]
        facts = batch.read_json(folder / "voting.json")
        audit = batch.read_json(batch.ROOT / "data/extractions/S22/voting" / (bvid + ".json"))
        validate(facts)
        assert audit["facts"] == facts
        assert audit["source_sha256"] == batch.digest(batch.ROOT / entry["source_path"])
        item = audit_game(entry, facts, audit, batch.read_json(folder / "dossier.json"), video_map, unresolved_map)
        segments = batch.load_segments(batch.ROOT / entry["source_path"])
        for q in item["questions"]:
            if q["evidence"]:
                continue
            day = q["day"]
            anchors = audit.get("day_anchors_ms", [])
            anchor = anchors[day-1] if day is not None and day <= len(anchors) else None
            if anchor is not None:
                rows = [s for s in segments if anchor-5000 <= s["start_ms"] <= anchor+20000]
                if rows:
                    q["evidence"] = [{"path": entry["source_path"],"start_ms": rows[0]["start_ms"],"end_ms":rows[-1]["end_ms"],
                                      "quote":"\n".join(s["text"] for s in rows),"note":"本日开局定位，非缺失投票的直接证据"}]
            if not q["evidence"] and day is not None:
                chinese = {1:"一",2:"二",3:"三",4:"四",5:"五",6:"六",7:"七",8:"八",9:"九",10:"十"}.get(day, str(day))
                matches = [n for n,s in enumerate(segments) if re.search(rf"第(?:{day}|{chinese})天", s["text"])]
                if matches:
                    n = matches[-1]
                    rows = segments[max(0,n-1):n+4]
                    q["evidence"] = [{"path": entry["source_path"],"start_ms":rows[0]["start_ms"],"end_ms":rows[-1]["end_ms"],
                                      "quote":"\n".join(s["text"] for s in rows),"note":"提及本日的原文定位，非缺失投票的直接证据"}]
        item["voting_sha256"] = batch.digest(folder / "voting.json")
        item["source_sha256"] = audit["source_sha256"]
        items.append(item)
        batch.atomic_json(folder / "voting_review.json", item)
    dates = []
    for date in sorted({i["date"] for i in items}):
        same = [i for i in items if i["date"] == date]
        dates.append({"date": date, "games": len(same), "question_count": sum(i["question_count"] for i in same),
                      "pending_count": sum(i["pending_count"] for i in same),
                      "games_with_questions": sum(i["question_count"] > 0 for i in same),
                      "games_with_pending": sum(i["pending_count"] > 0 for i in same),
                      "game_days": [{"bvid": i["bvid"], "game_number": i["game_number"], **d} for i in same for d in i["days"] if d["question_ids"]]})
    report = {"generated_at": batch.now(), "games": len(items), "dates": dates,
              "question_count": sum(i["question_count"] for i in items), "pending_count": sum(i["pending_count"] for i in items),
              "video_games": len(video_map), "video_frames": len({ev.get("frame_path") for x in videos for ev in x["evidence"] if ev.get("frame_path")}),
              "accepted_changes": sum(len(i["accepted_changes"]) for i in items), "items": items}
    batch.atomic_json(REPORT, report)
    with (batch.ROOT / "data/exports/S22_投票待复核清单.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["比赛日期", "局次", "BVID", "游戏日", "分类", "问题", "说明", "原视频时间秒", "原视频", "疑点ID"])
        for item in items:
            for q in item["questions"]:
                ms = next((e["start_ms"] for e in q["evidence"] if e.get("start_ms") is not None), None)
                sec = ms // 1000 if ms is not None else None
                writer.writerow([item["date"],item["game_number"],item["bvid"],q["day"],"有疑问" if q["severity"] == "question" else "待复核",q["title"],q["reason"],sec,
                                 f"https://www.bilibili.com/video/{item['bvid']}/" + (f"?t={sec}" if sec is not None else ""),q["id"]])
    return {k:v for k,v in report.items() if k not in {"items","dates"}}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(build(),ensure_ascii=False,indent=2))
