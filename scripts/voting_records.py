"""Extract announced ballots from full transcripts; keep evidence outside game facts."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import html
import json
from pathlib import Path
import re
import sys

import batch_s22 as batch
from database import ReviewError, connect, migrate

NUM = r"(?<![\d一二两三四五六七八九十])(?:12|11|10|[1-9]|十二|十一|十|[一二两三四五六七八九])"
SEAT = rf"{NUM}号(?:玩家)?"
GROUP = rf"{SEAT}(?:[、，,和与及\s]*{SEAT})*"
CHOICE = re.compile(rf"(?P<voters>{GROUP})(?:选择)?(?:投票给了?|投给了?)(?P<target>{NUM})号")
ABSTAIN = re.compile(rf"(?P<voters>{GROUP})(?:选择)?弃票")
ANNOUNCED_CHOICE = re.compile(rf"(?<!给)(?P<voters>{GROUP})(?:选择)?(?:(?:投票给了?|投给了?)(?P<target>{NUM})号|(?P<abstain>弃票))")
REPORT = batch.REPORT_DIR / "S22_投票补录进度.json"
EXTRACTIONS = batch.ROOT / "data/extractions/S22/voting"


def number(text):
    if text.isdigit():
        return int(text)
    return {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}[text]


def seats(text):
    return [number(m.group(1)) for m in re.finditer(rf"({NUM})号", text)]


def normalized(text):
    return re.sub(r"\s+", "", text).replace("自曝", "自爆").replace("ＰＫ", "PK")


def choices(text, *, announced=False):
    """Only declarative, seat-prefixed announcements; never repair ASR numbers."""
    text = normalized(text)
    text = re.sub(r"[，,、。；;：:]", "", text)
    if not announced and re.search(r"如果|假如|可能|应该|我觉得|我认为|你觉得|昨天|刚才|为什么|要是|不要", text):
        return []
    if not announced and not re.match(rf"^{NUM}号", text):
        return []
    found = []
    # One non-overlapping scan matters: in "5号投给11号7号弃票",
    # 11 is the first vote's target, never an additional abstaining voter.
    for match in ANNOUNCED_CHOICE.finditer(text):
        for voter in seats(match["voters"]):
            found.append({"voter": voter, "target": number(match["target"]) if match["target"] else None,
                          "state": "cast" if match["target"] else "abstained"})
    return sorted(found, key=lambda v: v["voter"])


def evidence(rows, source):
    return {"path": source, "start_ms": rows[0]["start_ms"], "end_ms": rows[-1]["end_ms"],
            "quote": "\n".join(r["text"] for r in rows)}


def extract(segments, dossier, source_path):
    texts = [normalized(s["text"]) for s in segments]
    proof, problems, registrations, ballots, interruptions = {}, [], [], [], []
    dawns = []
    for i, (s, text) in enumerate(zip(segments, texts)):
        following = "".join(texts[i+1:i+10])
        if ("天亮了" in text and len(text) < 55
                and not re.search(r"因为|觉得|如果|等到|昨天|明天|今天|等会|就天亮了|然后.*天亮了", text)
                and re.search(r"昨夜|昨晚|上警|退水|警上|警下|死亡|倒牌|平安夜", following)
                and (not dawns or s["start_ms"] - dawns[-1] > 90_000)):
            dawns.append(s["start_ms"])

    # The first complete registration is an independent day-one anchor when
    # the opening dawn command is missing from a subtitle track.
    registration_candidates = []
    for i, text in enumerate(texts):
        window = "".join(texts[i:i+3])
        if len(window) > 240:
            continue
        match = re.search(rf"(?:本(?:局|期)?游戏|本局|第[一二三四]局游戏)(?:除|除了)(?P<off>{GROUP})(?:在)?外[，,]*(?:其他|其余|区|曲|请大家)(?:玩?家)?(?:均|军|俊)?上警", window)
        if match:
            off = sorted(set(seats(match["off"])))
            registration_candidates.append((i, off, sorted(set(range(1, 13)) - set(off)), 3))
            continue
        match = re.search(rf"(?:本游戏|本局)(?P<on>{GROUP})(?:上警|参与警长竞选)", window)
        if match:
            on = sorted(set(seats(match["on"])))
            registration_candidates.append((i, sorted(set(range(1, 13)) - set(on)), on, 3))
            continue
        match = re.search(rf"^(?P<off>{GROUP})(?:在)?警下[，,]*(?:其余|其他)(?:玩?家)?上警", window)
        if match:
            off = sorted(set(seats(match["off"])))
            registration_candidates.append((i, off, sorted(set(range(1, 13)) - set(off)), 3))
            continue
        match = re.search(rf"共有[\d一二三四五六七八九十]+名玩家在警下(?P<off>{GROUP})", window)
        if match:
            off = sorted(set(seats(match["off"])))
            # A declared count prevents a clipped list from becoming a false
            # complete police registration.
            count_text = re.search(r"共有([\d一二三四五六七八九十]+)名", match[0]).group(1)
            if number(count_text) == len(off):
                registration_candidates.append((i, off, sorted(set(range(1, 13)) - set(off)), 3))
            continue
        if re.search(r"本(?:局)?游戏全员上警", window):
            registration_candidates.append((i, [], list(range(1,13)), 3))

    opening = next((s["start_ms"] for i,s in enumerate(segments)
                    if re.search(r"(?:上警|上镜|上景)玩家.*(?:亮|红灯)|(?:其他|其余)玩家.*上警", "".join(texts[i:i+3]))), None)
    initial = segments[registration_candidates[0][0]]["start_ms"] if registration_candidates else opening
    if initial is not None and (not dawns or initial < dawns[0] - 90_000):
        dawns.insert(0, initial)

    # Some subtitle tracks omit the wake-up command completely. A real
    # nightfall followed by a judge ballot/self-destruct command proves a new
    # day without using the recap's (often incomplete) round count.
    inferred_dawns = []
    night_pending = False
    opening_ms = dawns[0] if dawns else None
    for i, (s, text) in enumerate(zip(segments, texts)):
        if opening_ms is None or s["start_ms"] < opening_ms:
            continue
        if s["start_ms"] in dawns:
            night_pending = False
        dusk = re.fullmatch(r"(?:好|各位玩家|各位|所有玩家|请所有玩家|是否发动技能|受发动技能|平安夜|[1-5一二三四五，,。]*)*天黑请闭眼[哦啊，,。！!]*", text)
        if dusk and not re.search(r"(?:交友|郊游)请睁眼", "".join(texts[i+1:i+4])):
            night_pending = True
            continue
        command_text = re.sub(r"^(?:54321|5432|543|五四三二一|五四三二|五四三|五是三|321|三二一)[，,。]*", "", text)
        wake = re.match(rf"^{NUM}号(?:玩家)?(?:选择|决定)自爆", command_text)
        wake = wake or re.search(r"请(?:出|冲|举)(?:票|牌)", text)
        if night_pending and wake:
            if not any(abs(d-s["start_ms"]) < 90_000 for d in dawns):
                dawns.append(s["start_ms"])
                inferred_dawns.append(s["start_ms"])
            night_pending = False
    dawns.sort()

    def day_at(ms):
        return sum(t <= ms for t in dawns) or None

    # Repeated announcements in a minute are corrections; use the final one,
    # retaining all original utterances in the extraction evidence.
    grouped = []
    for row in registration_candidates:
        if grouped and segments[row[0]]["start_ms"] - segments[grouped[-1][-1][0]]["start_ms"] < 60_000:
            grouped[-1].append(row)
        else:
            grouped.append([row])
    for group in grouped:
        i, off, on, count = group[-1]
        key = f"registration-{len(registrations)+1}"
        registrations.append({"id": key, "day": day_at(segments[i]["start_ms"]), "on_police": on, "off_police": off})
        first = group[0][0]
        proof[key] = [evidence(segments[first:i+count], source_path)]

    # A ballot starts only at a judge-style show-ballots command and must have
    # a nearby continuous run of seat-prefixed announcements.
    last_end, last_ballot_end = -1, -1
    pending_starts = []
    show_command = re.compile(r"请(?:出|冲|举)(?:票|牌)|请投票")
    for i, text in enumerate(texts):
        if show_command.search(text) or re.fullmatch(r"[123一二三，,。！!]*(?:出票|请投票)[，,。！!]*", text):
            pending_starts.append(i)
    for i in pending_starts:
        if i <= last_end:
            continue
        start = segments[i]["start_ms"]
        rows, per_voter, conflicts, j = [], {}, set(), i
        vote_parts = []
        first_choice, last_choice = None, None
        while j < len(segments) and segments[j]["start_ms"] - start <= 85_000:
            if j > i and j in pending_starts:
                break
            if last_choice is not None and segments[j]["start_ms"] - last_choice > 12_000:
                break
            content = texts[j]
            if j == i:
                command = show_command.search(content)
                content = content[command.end():] if command else ""
            # A long ASR sentence can contain the end of voting and the first
            # PK speech. Only scan the part before the judge's end marker.
            content = re.split(r"投票结束|平票|评委PK|平安日|天黑请闭眼|请发言|请发表遗言", content, maxsplit=1, flags=re.I)[0]
            vote_parts.append(content)
            announced = choices("".join(vote_parts))
            if announced:
                first_choice = first_choice if first_choice is not None else segments[j]["start_ms"]
                if first_choice - start > 15_000:
                    break
                last_choice = segments[j]["end_ms"]
                rows.append(segments[j])
                for choice in announced:
                    old = per_voter.get(choice["voter"])
                    if old is not None and old != choice:
                        conflicts.add(choice["voter"])
                    per_voter[choice["voter"]] = choice
            if rows and ("投票结束" in texts[j] or re.search(r"平票|评委PK|平安日|票出局|天黑请闭眼", texts[j], re.I)):
                break
            j += 1
        if not rows:
            continue
        # The preamble is deliberately short: a player's earlier comments
        # about police votes cannot decide the current ballot type.
        before = [s for s in segments[max(0, i-18):i+1] if start - s["start_ms"] <= 45_000]
        preamble = "".join(normalized(s["text"]) for s in before)
        after = [s for s in segments[min(j, len(segments)-1):min(j+8, len(segments))]
                 if s["start_ms"] - (last_choice or start) <= 20_000]
        suffix = "".join(normalized(s["text"]) for s in after)
        # Include the final vote line when it already contains the tie/result.
        suffix = "".join(normalized(s["text"]) for s in rows[-2:]) + suffix
        day = day_at(start)
        if re.search(r"警下(?:的)?玩家.*投票准备|选出.*(?:警长|进长)|警长竞选|警长投票", preamble + suffix):
            kind = "sheriff"
        elif re.search(r"归票|放逐|票出局|平安日", preamble + suffix):
            kind = "exile"
        else:
            kind = "unknown"
        previous = ballots[-1] if ballots else None
        pool_matches = list(re.finditer(rf"(?:请从|在|从)(?P<c>{GROUP})(?:玩家)?(?:当中|中)选出", preamble))
        explicit_pool = sorted(set(seats(pool_matches[-1]["c"]))) if pool_matches else None
        pk_announcement = bool(re.search(r"pk(?:环节)?(?:发言|班)?结束", preamble, re.I))
        pk = bool(previous and previous["day"] == day and previous["tied_candidates"]
                  and (re.search(r"pk|平票|当中选出", preamble, re.I) or explicit_pool == previous["tied_candidates"])
                  and not any(last_ballot_end < d <= start for d in dawns))
        pk = pk or pk_announcement
        if kind == "unknown" and pk and previous:
            kind = previous["kind"]
        elif kind != "unknown" and pk and previous and previous["kind"] == "unknown":
            previous["kind"] = kind
        candidates = None
        candidate_announcements = list(re.finditer(rf"(?:警|井)上(?:的)?玩家(?:有|为)?(?P<c>{GROUP})", preamble))
        if kind == "sheriff" and candidate_announcements:
            candidates = sorted(set(seats(candidate_announcements[-1]["c"])))
        if explicit_pool is not None:
            candidates = explicit_pool
        if pk and candidates is None and previous and previous["tied_candidates"]:
            candidates = previous["tied_candidates"]
        tied = []
        match = re.search(rf"(?P<c>{GROUP})(?:各|均)?[^号。]{{0,10}}(?:平票|凭票|评委PK)", suffix, re.I)
        if match:
            tied = sorted(set(seats(match["c"])))
            if len(tied) < 2:
                tied = []
        if not tied and candidates is not None and len(candidates) == 2 and re.search(r"(?:平票|凭票|评委)[,.，。]*pk", suffix, re.I):
            tied = list(candidates)
        winner = None
        match = re.search(rf"({NUM})号(?:玩家)?(?:[一二三四五六七八九十\d.点票]+)?(?:出局|当选警长|当选为警长|成为警长)", suffix)
        if match:
            winner = number(match.group(1))
        for voter in conflicts:
            per_voter.pop(voter, None)
        eligible = None
        registration = next((r for r in reversed(registrations) if r["day"] is not None and r["day"] <= (day or 0)), None)
        if kind == "sheriff" and registration and not pk:
            eligible = registration["off_police"]
        if eligible is not None:
            for voter in set(per_voter) - set(eligible):
                problems.append(f"{start}ms警徽票出现警下名单之外的{voter}号，整轮票权待核")
                eligible = None
                break
        # An immediately repeated seat with both a target and "abstain" is
        # ambiguous ASR, not two independently trustworthy announcements.
        ballot_text = "".join(vote_parts)
        for m in re.finditer(rf"({NUM})号(?:选择)?(?:投票给|投给)({NUM})号弃票", re.sub(r"[，,、。]", "", ballot_text)):
            conflicts.add(number(m.group(1)))
        for voter in conflicts:
            per_voter.pop(voter, None)
        if candidates is not None:
            unexpected = [v for v,c in per_voter.items() if c["state"] == "cast" and c["target"] not in candidates]
            for voter in unexpected:
                per_voter.pop(voter)
                conflicts.add(voter)
            if unexpected:
                problems.append(f"{start}ms投向候选名单之外的票{unexpected}未作合法票入库，待核对原文")
        if eligible is None and len(per_voter) == 12 and not conflicts:
            eligible = list(range(1,13))
        # Every unannounced seat remains unknown; it is never an abstention.
        known = sorted(per_voter.values(), key=lambda v: v["voter"])
        missing = sorted(set(eligible) - set(per_voter)) if eligible is not None else None
        if conflicts:
            problems.append(f"{start}ms重复且冲突的投票座位{sorted(conflicts)}，冲突票未入库")
        ordinal = 1 + sum(b["day"] == day and b["kind"] == kind for b in ballots)
        key = f"ballot-{len(ballots)+1}"
        revote = bool(re.search(r"定序王子|重新投票|再次投票|重投", preamble)) and not pk
        ballot = {"id": key, "day": day, "kind": kind, "number": ordinal,
                  "stage": "pk" if pk else "revote" if revote else "initial" if ordinal == 1 else "unknown",
                  "status": "complete" if eligible is not None and not missing and not conflicts else "partial",
                  "candidates": candidates, "eligible_voters": eligible, "votes": known,
                  "tied_candidates": tied, "winner": winner, "unrecorded_voters": missing}
        ballots.append(ballot)
        proof[key] = [evidence(before + segments[i+1:min(j+8, len(segments))], source_path)]
        last_end = j-1 if j > i and j in pending_starts else j
        last_ballot_end = last_choice or start

    # An opening election or initial registration establishes day one even
    # if its dawn command is absent. Do not guess subsequent missing dawns.
    first_sheriff = next((b for b in ballots if b["kind"] == "sheriff"), None)
    if first_sheriff and first_sheriff["day"] is None:
        opening_ms = proof[first_sheriff["id"]][0]["start_ms"]
        dawns.insert(0, opening_ms)
        for b in ballots:
            ms = proof[b["id"]][0]["start_ms"]
            b["day"] = day_at(ms)
    # Normalize numbers again after a PK bridge resolved the preceding kind.
    ordinals = Counter()
    for b in ballots:
        ordinals[b["day"],b["kind"]] += 1
        b["number"] = ordinals[b["day"],b["kind"]]
    for i, text in enumerate(texts):
        command_text = re.sub(r"^(?:54321|5432|543|五四三二一|五四三二|五四三|五是三|321|三二一)[，,。]*", "", text)
        match = re.match(rf"^({NUM})号(?:玩家)?(?:选择|决定)自爆", command_text)
        if not match:
            continue
        after = [s for s in segments[i:i+100] if s["start_ms"] - segments[i]["start_ms"] <= 180_000]
        key = f"interruption-{len(interruptions)+1}"
        interruptions.append({"id": key, "day": day_at(segments[i]["start_ms"]),
                              "actor": number(match.group(1)), "reason": "self_destruct",
                              "ends_day": any("天黑请闭眼" in s["text"] for s in after)})
        proof[key] = [evidence(after, source_path)]

    # Coverage lists every known day even when no usable votes were announced.
    days = []
    maximum = max(len(dawns), len(dossier["rounds"]))
    for day in range(1, maximum+1):
        found = [b for b in ballots if b["day"] == day]
        ended = any(x["day"] == day and x["ends_day"] for x in interruptions)
        days.append({"day": day, "sheriff": "recorded" if any(b["kind"] == "sheriff" for b in found) else "unknown",
                     "exile": "recorded" if any(b["kind"] == "exile" for b in found) else "interrupted_self_destruct" if ended else "unknown"})
    facts = {"schema_version": 1, "game_slug": dossier["slug"], "registrations": registrations,
             "ballots": ballots, "interruptions": interruptions, "days": days}
    return facts, {"evidence": proof, "day_anchors_ms": dawns, "inferred_day_anchors_ms": inferred_dawns, "issues": problems,
                   "note": "全文机器转写提取，尚未人工回听。complete仅表示已知票权名单中无缺票；不代表人工确认。数字不自动纠错，不凭票数反推结果。"}


def validate(facts):
    if facts.get("schema_version") != 1 or not facts.get("game_slug"):
        raise ReviewError("投票档案版本或对局关联不合法")
    def seat_list(value):
        return isinstance(value, list) and len(value) == len(set(value)) and all(type(n) is int and 1 <= n <= 12 for n in value)
    seen = set()
    for r in facts["registrations"]:
        if not seat_list(r["on_police"]) or not seat_list(r["off_police"]) or set(r["on_police"]) & set(r["off_police"]) or set(r["on_police"] + r["off_police"]) != set(range(1,13)):
            raise ReviewError("上警与警下名单必须形成完整且不重复的座位划分")
    for b in facts["ballots"]:
        if b["id"] in seen or b["day"] is not None and (type(b["day"]) is not int or b["day"] < 1):
            raise ReviewError("投票轮次重复或日序不合法")
        seen.add(b["id"])
        if b["kind"] not in {"sheriff", "exile", "unknown"} or b["stage"] not in {"initial", "pk", "revote", "unknown"}:
            raise ReviewError("投票种类或阶段不合法")
        if type(b["number"]) is not int or b["number"] < 1:
            raise ReviewError("投票轮号不合法")
        for field in ("candidates", "eligible_voters", "unrecorded_voters", "tied_candidates"):
            if b[field] is not None and not seat_list(b[field]):
                raise ReviewError("投票座位名单不合法")
        voters = []
        for v in b["votes"]:
            if v["state"] not in {"cast", "abstained"} or (v["target"] is None) != (v["state"] == "abstained") or not seat_list([v["voter"]]) or v["target"] is not None and not seat_list([v["target"]]):
                raise ReviewError("未知票不能记为弃票，投票座位须合法")
            voters.append(v["voter"])
        if not seat_list(voters):
            raise ReviewError("同轮投票者重复")
        if b["eligible_voters"] is not None:
            if not set(voters) <= set(b["eligible_voters"]) or b["unrecorded_voters"] != sorted(set(b["eligible_voters"]) - set(voters)):
                raise ReviewError("缺票名单或票权不一致")
        if b["status"] not in {"partial", "complete"} or b["status"] == "complete" and (b["eligible_voters"] is None or b["unrecorded_voters"]):
            raise ReviewError("票权未知或缺票不能标为完整")


def import_voting(facts):
    """Replace only this game's voting supplement, atomically and idempotently."""
    validate(facts)
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("game-record-" + facts["game_slug"],))
        game = conn.execute("SELECT id FROM games WHERE slug=%s", (facts["game_slug"],)).fetchone()
        if game is None:
            raise ReviewError("投票档案对应的对局尚未入库")
        game_id = game["id"]
        conn.execute("DELETE FROM game_sheriff_registrations WHERE game_id=%s", (game_id,))
        conn.execute("DELETE FROM game_ballots WHERE game_id=%s", (game_id,))
        conn.execute("DELETE FROM game_voting_days WHERE game_id=%s", (game_id,))
        for r in facts["registrations"]:
            for registered, ns in ((True, r["on_police"]), (False, r["off_police"])):
                for n in ns:
                    conn.execute("INSERT INTO game_sheriff_registrations(game_id,registration_key,day_number,seat_number,registered) VALUES(%s,%s,%s,%s,%s)",
                                 (game_id, r["id"], r["day"], n, registered))
        for b in facts["ballots"]:
            row = conn.execute("""INSERT INTO game_ballots(game_id,ballot_key,day_number,kind,ballot_number,stage,status,candidates,eligible_voters,tied_candidates,winner_seat)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (game_id,b["id"],b["day"],b["kind"],b["number"],b["stage"],b["status"],b["candidates"],b["eligible_voters"],b["tied_candidates"],b["winner"])).fetchone()
            for v in b["votes"]:
                conn.execute("INSERT INTO game_ballot_choices(ballot_id,voter_seat,target_seat,state) VALUES(%s,%s,%s,%s)",
                             (row["id"],v["voter"],v["target"],v["state"]))
        for d in facts["days"]:
            conn.execute("INSERT INTO game_voting_days(game_id,day_number,sheriff_status,exile_status) VALUES(%s,%s,%s,%s) ON CONFLICT(game_id,day_number) DO UPDATE SET sheriff_status=EXCLUDED.sheriff_status,exile_status=EXCLUDED.exile_status",
                         (game_id,d["day"],d["sheriff"],d["exile"]))
        return {"ballots": len(facts["ballots"]), "choices": sum(len(b["votes"]) for b in facts["ballots"])}


def run(write_database=False):
    state = batch.load_state()
    if write_database:
        migrate()
    items, csv_rows = [], []
    for bvid, entry in state["items"].items():
        folder = batch.ROOT / entry["output_dir"]
        dossier_path = folder / "dossier.json"
        dossier = batch.read_json(dossier_path)
        source = batch.ROOT / entry["source_path"]
        facts, audit = extract(batch.load_segments(source), dossier, entry["source_path"])
        from review_s22_voting import apply_accepted
        apply_accepted(facts, audit, entry)
        validate(facts)
        audit.update(bvid=bvid, source_sha256=batch.digest(source), dossier_sha256=batch.digest(dossier_path),
                     generated_at=batch.now(), facts=facts)
        EXTRACTIONS.mkdir(parents=True, exist_ok=True)
        batch.atomic_json(EXTRACTIONS / (bvid + ".json"), audit)
        batch.atomic_json(folder / "voting.json", facts)
        receipt = import_voting(facts) if write_database else None
        item = {"bvid": bvid, "date": entry["date"], "game_number": entry["game_number"],
                "file": batch.relative(folder / "voting.json"), "registrations": len(facts["registrations"]),
                "ballots": len(facts["ballots"]), "votes": sum(len(b["votes"]) for b in facts["ballots"]),
                "pk_ballots": sum(b["stage"] == "pk" for b in facts["ballots"]),
                "unknown_day_ballots": sum(b["day"] is None for b in facts["ballots"]),
                "unknown_kind_ballots": sum(b["kind"] == "unknown" for b in facts["ballots"]),
                "complete_ballots": sum(b["status"] == "complete" for b in facts["ballots"]),
                "issues": audit["issues"], "database": receipt}
        items.append(item)
        for b in facts["ballots"]:
            for v in b["votes"]:
                ev = audit["evidence"][b["id"]][0]
                csv_rows.append([entry["date"], entry["game_number"], bvid, b["day"], b["kind"], b["number"], b["stage"],
                                 v["voter"], v["target"], v["state"], ev["start_ms"], entry["source_path"]])
    counts = {key: sum(i[key] for i in items) for key in ("registrations", "ballots", "votes", "pk_ballots", "unknown_day_ballots", "unknown_kind_ballots", "complete_ballots")}
    report = {"generated_at": batch.now(), "games": len(items), "database_written": write_database,
              **counts, "games_with_votes": sum(i["votes"] > 0 for i in items),
              "games_without_registration": sum(i["registrations"] == 0 for i in items),
              "games_without_votes": sum(i["votes"] == 0 for i in items), "items": items}
    batch.atomic_json(REPORT, report)
    export = batch.ROOT / "data/exports/S22_逐人投票.csv"
    with export.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["日期", "局次", "BVID", "游戏日", "投票类型", "本日轮号", "阶段", "投票人", "投给", "票状态", "原文起点毫秒", "转写来源"])
        writer.writerows(csv_rows)
    summary = {k: v for k,v in report.items() if k != "items"}
    page = ["<!doctype html><meta charset='utf-8'><title>S22 投票补录</title><style>body{font:16px/1.7 system-ui;margin:30px;color:#19364a}table{border-collapse:collapse}td,th{padding:7px;border:1px solid #ddd}</style>",
            "<h1>S22 投票补录</h1><p>来自整局机器转写，尚未人工回听。未知票不等于弃票；日序、类别或票权不明时保留待核。PK 前后分别记录。</p>",
            "<p>" + html.escape(json.dumps(summary,ensure_ascii=False)) + "</p>", "<a href='S22_逐人投票.csv'>逐人投票 CSV</a><table><tr><th>日期 / 局次</th><th>BV</th><th>上警名单组</th><th>投票轮</th><th>逐人票</th><th>PK轮</th><th>档案</th></tr>"]
    for i in items:
        folder = batch.ROOT / state["items"][i["bvid"]]["output_dir"]
        target = folder / "投票记录.html"
        facts = batch.read_json(folder / "voting.json")
        detail = render_html(facts, batch.read_json(EXTRACTIONS / (i["bvid"] + ".json")))
        target.write_text(detail, encoding="utf-8")
        url = "../../" + batch.relative(target)
        page.append(f"<tr><td>{i['date']} / {i['game_number']}</td><td>{i['bvid']}</td><td>{i['registrations']}</td><td>{i['ballots']}</td><td>{i['votes']}</td><td>{i['pk_ballots']}</td><td><a href='{html.escape(url)}'>查看逐日票型</a></td></tr>")
    page.append("</table>")
    (export.parent / "S22_投票补录.html").write_text("".join(page),encoding="utf-8")
    from review_s22_voting import build as build_review
    build_review()
    return summary


def render_html(facts, audit):
    out = ["<!doctype html><meta charset='utf-8'><title>逐日投票记录</title><style>body{font:16px/1.7 system-ui;margin:30px;max-width:1100px;color:#19364a}pre{white-space:pre-wrap}section{border:1px solid #ccc;padding:15px;margin:12px 0}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:6px}</style>",
           "<h1>逐日投票记录</h1><p>机器转写待核。未播报的票保持未知；缺少完整票权名单时不宣称票型完整。</p>"]
    def ev(key):
        return "".join(f"<details><summary>原文 {e['start_ms']/1000:.2f}–{e['end_ms']/1000:.2f} 秒</summary><pre>{html.escape(e['quote'])}</pre></details>" for e in audit["evidence"].get(key,[]))
    for r in facts["registrations"]:
        out.append(f"<section>第{r['day'] or '待核'}天：上警 {r['on_police']}；警下 {r['off_police']}{ev(r['id'])}</section>")
    for b in facts["ballots"]:
        label = {"sheriff":"警徽票","exile":"放逐票","unknown":"类别待核"}[b["kind"]]
        stage = {"initial":"首轮","pk":"平票 PK 后","revote":"技能重投","unknown":"阶段待核"}[b["stage"]]
        out.append(f"<section><h2>第{b['day'] or '待核'}天 · {label} · 第{b['number']}轮 · {stage}</h2><p>候选人：{b['candidates']}；票权名单：{b['eligible_voters']}；缺票：{b['unrecorded_voters']}；平票：{b['tied_candidates']}；公布结果：{b['winner']}</p><table><tr><th>投票人</th><th>投给</th></tr>")
        for v in b["votes"]:
            out.append(f"<tr><td>{v['voter']}号</td><td>{'明确弃票' if v['state']=='abstained' else str(v['target'])+'号'}</td></tr>")
        out.append("</table>" + ev(b["id"]) + "</section>")
    out.append("<h2>每日覆盖</h2><pre>" + html.escape(json.dumps(facts["days"],ensure_ascii=False,indent=2)) + "</pre>")
    return "".join(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-db", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.import_db), ensure_ascii=False, indent=2))
