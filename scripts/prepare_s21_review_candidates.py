"""Prepare non-authoritative S21 per-game machine candidate baselines.

Reads only the already selected local transcripts and candidate time indexes.
Writes only ``baseline.*`` files under S21 game_reviews plus the baseline
acceptance report. It does not write to the database or website.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from recap_parser import extract_recap

SCOPE_PATH = ROOT / "config/S21_game_scope.json"
RULE_EVIDENCE_PATH = ROOT / "data/reports/S21_范围与规则证据.json"
PLAN_PATH = ROOT / "data/indexes/S21_采集计划.json"
MEDIA_ROOT = ROOT / "data/extractions/S21/media_evidence"
OUTPUT_ROOT = ROOT / "data/extractions/S21/game_reviews"
REPORT_PATH = ROOT / "data/reports/S21_候选基线验收.json"

NUM = r"(?:12|11|10|[1-9]|十二|十一|十|一|二|两|三|四|五|六|七|八|九)"
SEAT = rf"{NUM}号(?:玩家)?"
GROUP = rf"{SEAT}(?:[、，,和与及\s]*{SEAT})*"
ANNOUNCED_CHOICE = re.compile(
    rf"(?<!给)(?P<voters>{GROUP})(?:选择)?(?:(?:投票给了?|投给了?)(?P<target>{NUM})号|(?P<abstain>弃票))"
)
SHOW_BALLOT = re.compile(r"(?:请(?:出|冲|举)(?:票|牌)|请投票|开始投票|321请出票|三二一请出票|出票)")
BALLOT_END = re.compile(r"投票结束|停止投票|天黑请闭眼|平票|评委PK|PK发言|票出局", re.I)

ROLE_NAMES = (
    "机械双刀狼", "机械通灵师", "机械女巫", "机械猎人", "机械守卫", "机械平民",
    "鬼魂新娘", "定序王子", "盗宝大师", "黑狼王", "机械狼", "摄梦人", "摄梦师",
    "典狱长", "混血儿", "魔术师", "诡术师", "鬼术师", "通灵师", "预言家",
    "白痴", "白神", "女巫", "猎人", "守卫", "骑士", "舞者", "武者",
    "假面", "狼人", "狼王", "平民", "毒师", "蒙面人",
)
ROLE_PATTERN = "|".join(map(re.escape, sorted(ROLE_NAMES, key=len, reverse=True)))
ROLE_NUMBER_PATTERNS = (
    re.compile(rf"(?P<role>{ROLE_PATTERN})(?:身份|牌)?(?:为|是)?[，,、；;：:]?(?P<seat>{NUM})号"),
    re.compile(rf"(?P<seat>{NUM})号[，,、；;：:]?(?:身份为|是|为)?(?P<role>{ROLE_PATTERN})"),
)

REGISTRATION_RE = re.compile(r"上警|警下|警长竞选|警长报名|报名竞选|参与竞选|竞选警长")
BALLOT_CONTEXT_RE = re.compile(r"投票|出票|归票|弃票|平票|PK|pk|票型|投给|投出|唱票|放逐|公投")
DEATH_PHASE_RE = re.compile(r"天黑|闭眼|天亮|昨夜|昨晚|死亡|死讯|出局|倒牌|淘汰|平安夜|自爆|交牌")
ROLE_CLAIM_RE = re.compile(r"(?:我是|我跳|我认|我底牌(?:是)?|我拿到)(?:一个)?(?:预言家|通灵师)|(?:预言家|通灵师)(?:牌)?(?:是)?我")
SPECIAL_CUE_RE = re.compile(r"唯邻是从|傀儡|榜样|诡术师|鬼术师|盗宝大师|假面|面具|共舞|舞池|毒药反弹|机械狼.{0,5}(?:学习|模仿|带刀|守护)|换牌|交换身份|特殊技能")
WINNER_CUE_RE = re.compile(r"好人阵营获胜|狼人阵营获胜|好人(?:阵营)?胜利|狼人(?:阵营)?胜利|第三方.{0,5}(?:胜利|获胜)|狼队获胜|屠神获胜|屠民获胜|游戏结束|交牌")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def seat_number(raw: str) -> int | None:
    if raw.isdigit():
        n = int(raw)
    else:
        n = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
             "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}.get(raw)
    return n if n is not None and 1 <= n <= 12 else None


def quote_ref(rows: list[dict[str, Any]], source_path: str, source_sha: str) -> dict[str, Any] | None:
    if not rows:
        return None
    ordered = sorted(rows, key=lambda r: (r["start_ms"], r["index"]))
    return {
        "source_path": source_path,
        "source_sha256": source_sha,
        "start_ms": ordered[0]["start_ms"],
        "end_ms": ordered[-1]["end_ms"],
        "segment_indices": [r["index"] for r in ordered],
        "source_segment_indices": [r["source_segment_index"] for r in ordered],
        "quote": "\n".join(r["text"] for r in ordered),
    }


def context_rows(rows: list[dict[str, Any]], index: int, radius: int = 3) -> list[dict[str, Any]]:
    return rows[max(0, index-radius):min(len(rows), index+radius+1)]


def context_windows(rows: list[dict[str, Any]], patterns: dict[str, re.Pattern[str]],
                    source_path: str, source_sha: str, radius: int = 3) -> list[dict[str, Any]]:
    hits = []
    for i, row in enumerate(rows):
        text = compact(row["text"])
        kinds = sorted(name for name, pattern in patterns.items() if pattern.search(text))
        if kinds:
            hits.append({"first": max(0, i-radius), "last": min(len(rows)-1, i+radius),
                         "cue_indices": [i], "cue_types": kinds})
    merged: list[dict[str, Any]] = []
    for hit in hits:
        if merged and hit["first"] <= merged[-1]["last"] + 1:
            merged[-1]["last"] = max(merged[-1]["last"], hit["last"])
            merged[-1]["cue_indices"].extend(hit["cue_indices"])
            merged[-1]["cue_types"] = sorted(set(merged[-1]["cue_types"] + hit["cue_types"]))
        else:
            merged.append(hit)
    result = []
    for i, item in enumerate(merged, 1):
        selected = rows[item["first"]:item["last"]+1]
        ref = quote_ref(selected, source_path, source_sha)
        result.append({"context_id": f"context-{i:03d}", "cue_types": item["cue_types"],
                       "cue_source_segment_indices": [rows[j]["source_segment_index"] for j in item["cue_indices"]],
                       "cue_times_ms": [rows[j]["start_ms"] for j in item["cue_indices"]],
                       **(ref or {}), "status": "text_context_candidate_not_verified"})
    return result


def role_mentions(rows: list[dict[str, Any]], recap_id: str, source_path: str,
                  source_sha: str) -> dict[int, dict[str, list[dict[str, Any]]]]:
    found: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        text = compact(row["text"])
        for pattern in ROLE_NUMBER_PATTERNS:
            for match in pattern.finditer(text):
                seat = seat_number(match.group("seat"))
                role = match.group("role")
                if seat is None:
                    continue
                ref = quote_ref([row], source_path, source_sha)
                if ref:
                    found[seat][role].append({"source_recap_candidate_id": recap_id,
                                              "evidence": ref,
                                              "status": "role_seat_text_pair_candidate"})
    return found


def extract_ballot_candidates(rows: list[dict[str, Any]], source_path: str,
                              source_sha: str) -> dict[str, Any]:
    prompts = [i for i, row in enumerate(rows) if SHOW_BALLOT.search(compact(row["text"]))]
    ballots = []
    for prompt_no, i in enumerate(prompts, 1):
        start_ms = rows[i]["start_ms"]
        stop_index = prompts[prompt_no] if prompt_no < len(prompts) else len(rows)
        scope = []
        for j in range(i, stop_index):
            if rows[j]["start_ms"] - start_ms > 90_000:
                break
            scope.append(rows[j])
            if j > i and BALLOT_END.search(compact(rows[j]["text"])):
                break
        if not scope:
            continue
        # Exact spoken vote forms only. No omitted voter, tie-break, or scoring
        # inference is made. Scanning short joined fragments catches split cues.
        vote_mentions = []
        seen_windows: set[tuple[int, int, int, int | None, str]] = set()
        for a in range(len(scope)):
            for width in (1, 2, 3):
                b = min(len(scope), a+width)
                text = compact("".join(r["text"] for r in scope[a:b]))
                text = re.sub(r"[，,、。；;：:]", "", text)
                for match in ANNOUNCED_CHOICE.finditer(text):
                    target = seat_number(match["target"]) if match["target"] else None
                    state = "abstained" if match["abstain"] else "cast"
                    voters = [seat_number(m.group(1)) for m in re.finditer(rf"({NUM})号(?:玩家)?", match["voters"])]
                    for voter in filter(None, voters):
                        key = (a, b, voter, target, state)
                        if key in seen_windows:
                            continue
                        seen_windows.add(key)
                        ref_rows = scope[a:b]
                        vote_mentions.append({"voter_seat_candidate": voter,
                                              "target_seat_candidate": target,
                                              "state_candidate": state,
                                              "time_ms": ref_rows[0]["start_ms"],
                                              "evidence": quote_ref(ref_rows, source_path, source_sha)})
        # If overlapping fragments produced the same declaration, keep the
        # shortest source window. Contradictions are retained and flagged.
        chosen: dict[tuple[int, int | None, str], dict[str, Any]] = {}
        for vote in vote_mentions:
            k = (vote["voter_seat_candidate"], vote["target_seat_candidate"], vote["state_candidate"])
            old = chosen.get(k)
            if old is None or len(vote["evidence"]["segment_indices"]) < len(old["evidence"]["segment_indices"]):
                chosen[k] = vote
        vote_mentions = sorted(chosen.values(), key=lambda v: (v["time_ms"], v["voter_seat_candidate"]))
        by_voter: dict[int, set[tuple[int | None, str]]] = defaultdict(set)
        for vote in vote_mentions:
            by_voter[vote["voter_seat_candidate"]].add((vote["target_seat_candidate"], vote["state_candidate"]))
        conflicts = sorted(seat for seat, choices in by_voter.items() if len(choices) > 1)
        text = compact("".join(r["text"] for r in scope))
        if re.search(r"警长|警徽", text):
            kind = "sheriff_vote_candidate"
        elif re.search(r"归票|放逐|公投|出局", text):
            kind = "exile_vote_candidate"
        else:
            kind = "unknown_vote_type_candidate"
        ballots.append({"ballot_id": f"ballot-candidate-{len(ballots)+1:02d}",
                        "time_ms": start_ms, "day_candidate": explicit_day_hint(rows, start_ms),
                        "type_candidate": kind, "stage_candidate": "unknown",
                        "prompt_source_segment_index": rows[i]["source_segment_index"],
                        "reported_vote_candidates": vote_mentions,
                        "reported_choice_count": len(vote_mentions),
                        "voters_with_conflicting_announcements": conflicts,
                        "text_context": quote_ref(scope, source_path, source_sha),
                        "status": "machine_candidate_unconfirmed",
                        "issues": (["同座位有不同报票说法；均保留待核"] if conflicts else []) +
                                  ["警长/放逐/PK阶段仅为字幕词语分类候选；没有使用S21未证实的票权或计分规则"]})
    usable = sum(bool(b["reported_vote_candidates"]) for b in ballots)
    return {"ballot_prompt_candidate_count": len(prompts),
            "usable_reported_vote_round_candidate_count": usable,
            "ballots": ballots,
            "status": "machine_candidate_unconfirmed",
            "policy": "只提取显式报票/弃票字句；不推断票权、缺票、有效票、计分或PK结算；不使用S22弃票规则。"}


def explicit_day_hint(rows: list[dict[str, Any]], start_ms: int) -> int | None:
    candidates = []
    for row in rows:
        if row["start_ms"] > start_ms or start_ms - row["start_ms"] > 60_000:
            continue
        m = re.search(r"第(十二|十一|十|[一二两三四五六七八九]|1[0-2]|[1-9])天", compact(row["text"]))
        if m:
            candidates.append(seat_number(m.group(1)))
    return candidates[-1] if candidates else None


def event_evidence_rows(rows: list[dict[str, Any]], event: dict[str, Any]) -> list[dict[str, Any]]:
    action = event.get("action", "")
    pattern = {
        "attack": r"击杀|袭击|狼刀|刀",
        "guard": r"守护|保护|守卫|盾",
        "save": r"女巫|解药|救",
        "poison": r"女巫|毒",
        "check": r"预言家|通灵师|查验|验证|验",
        "learn": r"机械狼|学习|模仿",
        "shoot": r"猎人|开枪|射杀|带走",
        "self_destruct": r"自爆",
        "exile": r"放逐|公投|出局|淘汰|抗推",
        "elected": r"警长|警徽|当选",
        "transfer": r"警徽|移交|转交",
        "destroy": r"警徽|撕掉|流失",
        "peaceful": r"平安夜|平安",
        "die": r"死亡|倒牌|身亡|死讯",
        "none": r"平安日|无人出局",
    }.get(action)
    targets = set(event.get("targets") or [])
    hits = []
    if pattern:
        for i, row in enumerate(rows):
            text = compact(row["text"])
            seats = {seat_number(m.group(1)) for m in re.finditer(rf"({NUM})号", text)}
            if re.search(pattern, text) and (not targets or not seats or targets & seats):
                hits.append(i)
    result = []
    seen = set()
    for i in hits[:8]:
        group = rows[max(0, i-1):min(len(rows), i+2)]
        key = tuple(r["index"] for r in group)
        if key not in seen:
            seen.add(key)
            result.append(group)
    return result


def candidate_recap(rows: list[dict[str, Any]], candidate: dict[str, Any],
                    board_name: str, source_path: str, source_sha: str) -> dict[str, Any]:
    start, end = candidate.get("start_ms"), candidate.get("end_ms")
    selected = [r for r in rows if start is not None and r["end_ms"] >= start
                and (end is None or r["start_ms"] <= end)]
    if not selected:
        allowed = {item.get("index") for item in candidate.get("evidence", []) if isinstance(item, dict)}
        selected = [r for r in rows if r["index"] in allowed]
    refs = quote_ref(selected, source_path, source_sha)
    parse_eligible = candidate.get("status") in {
        "candidate_needs_visual_check", "roster_dense_fallback_needs_visual_check"
    } and bool(selected)
    parsed = extract_recap(selected, board_name or "S21版型候选未知", seat_count=12) if parse_eligible else {
        "seats": [{"seat": seat, "role": None, "learning_target": None, "learned_role": None} for seat in range(1, 13)],
        "rounds": [], "winning_faction": None,
        "issues": ["复盘窗口只是弱定位候选，未对其中说话内容解析角色或行动。"],
    }
    return {"candidate_id": candidate.get("candidate_id"),
            "start_ms": start, "end_ms": end,
            "end_caption_end_ms": candidate.get("end_caption_end_ms"),
            "candidate_status": candidate.get("status"),
            "candidate_method": candidate.get("candidate_method", candidate.get("start_basis")),
            "explicit_recap_anchor_missing": candidate.get("explicit_recap_anchor_missing", False),
            "parse_status": "machine_candidate_unconfirmed" if parse_eligible else "localization_only_not_parsed",
            "support_counts": candidate.get("support_counts"),
            "source_excerpt": refs,
            "parsed_candidates": parsed,
            "issues": list(parsed.get("issues", [])) + ["复盘定位和解析均为字幕机器候选，需人工/AI语义与原音核对。"]}


def build_game(entry: dict[str, Any], plan_entry: dict[str, Any], limit_index: int) -> dict[str, Any]:
    bvid = entry["bvid"]
    folder = MEDIA_ROOT / bvid
    evidence_entry = read_json(folder / "entry.json")
    transcript = read_json(folder / "transcript.selected.json")
    recap_file = read_json(folder / "recap_candidates.json")
    source_path = evidence_entry["selected_source_path"]
    source_sha = evidence_entry["source_hashes"]["selected_source_sha256"]
    source_file = ROOT / source_path
    actual_sha = digest(source_file) if source_file.is_file() else None
    segments = transcript.get("segments", [])
    for i, row in enumerate(segments):
        row.setdefault("index", i)
    board = plan_entry.get("labels", {}).get("board_candidate")
    recap_candidates = recap_file.get("recap_location", {}).get("candidates", [])
    recaps = [candidate_recap(segments, candidate, board, source_path, source_sha)
              for candidate in recap_candidates]
    parseable = [c for c in recaps if c["parse_status"] == "machine_candidate_unconfirmed"]

    # Role mentions and parser output remain candidates. Conflicts are retained
    # as option sets; no faction is inferred from an S22 role table.
    role_options: dict[int, dict[str, list[dict[str, Any]]]] = {n: defaultdict(list) for n in range(1, 13)}
    for recap in parseable:
        source_rows = [r for r in segments if recap["start_ms"] is not None and r["end_ms"] >= recap["start_ms"]
                       and (recap["end_ms"] is None or r["start_ms"] <= recap["end_ms"])]
        mentions = role_mentions(source_rows, recap["candidate_id"], source_path, source_sha)
        for seat, roles in mentions.items():
            for role, refs in roles.items():
                role_options[seat][role].extend(refs)
        for source_seat in recap["parsed_candidates"].get("seats", []):
            role = source_seat.get("role")
            seat = source_seat.get("seat")
            if isinstance(seat, int) and role:
                role_options[seat][role].append({"source_recap_candidate_id": recap["candidate_id"],
                                                 "evidence": recap["source_excerpt"],
                                                 "status": "recap_parser_role_candidate"})

    seats = []
    role_counts = []
    for seat in range(1, 13):
        options = role_options[seat]
        names = sorted(options)
        chosen = names[0] if len(names) == 1 else None
        if chosen:
            role_counts.append(seat)
        seats.append({"seat": seat, "name": None, "role": None, "faction": None,
                      "role_candidate": chosen, "role_candidate_options": names,
                      "role_candidate_status": "single_machine_candidate_unconfirmed" if len(names) == 1 else
                                               "conflicting_machine_candidates" if len(names) > 1 else "unknown",
                      "evidence": [ref for name in names for ref in options[name]],
                      "learning_target_candidate": None, "learned_role_candidate": None})

    rounds = []
    event_refs: list[dict[str, Any]] = []
    for recap in parseable:
        for parsed_round in recap["parsed_candidates"].get("rounds", []):
            round_record = {"round_number_candidate": parsed_round.get("number"),
                            "source_recap_candidate_id": recap["candidate_id"],
                            "phase_event_candidates": []}
            recap_rows = [r for r in segments if r["end_ms"] >= recap["start_ms"]
                          and r["start_ms"] <= recap["end_ms"]]
            for phase in ("night", "day"):
                for event_no, event in enumerate(parsed_round.get(phase, []), 1):
                    matched = event_evidence_rows(recap_rows, event)
                    refs = [quote_ref(group, source_path, source_sha) for group in matched]
                    refs = [ref for ref in refs if ref]
                    if not refs and recap.get("source_excerpt"):
                        refs = [recap["source_excerpt"]]
                    event_record = {"phase_candidate": phase,
                                    "event_candidate_id": f"{recap['candidate_id']}-r{parsed_round.get('number')}-{phase}-{event_no}",
                                    "slot_candidate": event.get("slot"),
                                    "action_candidate": event.get("action"),
                                    "actor_seat_candidate": event.get("actor"),
                                    "target_seats_candidate": event.get("targets", []),
                                    "result_candidate": event.get("result"),
                                    "status": "machine_candidate_unconfirmed",
                                    "evidence": refs}
                    round_record["phase_event_candidates"].append(event_record)
                    event_refs.extend(refs)
            rounds.append(round_record)

    vote_data = extract_ballot_candidates(segments, source_path, source_sha)
    ctx = context_windows(segments, {
        "registration_or_police_election": REGISTRATION_RE,
        "ballot_or_vote_discussion": BALLOT_CONTEXT_RE,
        "death_night_or_day_result": DEATH_PHASE_RE,
    }, source_path, source_sha)
    role_claims = context_windows(segments, {"self_claim_prophet_or_medium": ROLE_CLAIM_RE}, source_path, source_sha)
    special_cues = context_windows(segments, {"special_role_or_mechanic_wording": SPECIAL_CUE_RE}, source_path, source_sha)
    winner_cues = context_windows(segments, {"winner_or_game_end_wording": WINNER_CUE_RE}, source_path, source_sha)
    speech = recap_file.get("last_game_day_speech_command")
    speech_context = []
    if speech:
        i = next((i for i, row in enumerate(segments) if row.get("source_segment_index") == speech.get("source_segment_index")), None)
        if i is not None:
            speech_context = [quote_ref(context_rows(segments, i, radius=4), source_path, source_sha)]
    for claim in role_claims:
        claim["speaker_attribution"] = {"value": None, "status": "unknown_in_selected_transcript",
                                        "note": "已保存的transcript.selected.json不包含说话人字段；不可据字幕窗口指派玩家座位。"}
        claim["seat_tokens_mentioned"] = sorted({seat_number(m.group(1)) for m in re.finditer(rf"({NUM})号", claim["quote"]) if seat_number(m.group(1))})

    policy = {
        "scope_path": "config/S21_game_scope.json",
        "rules_evidence_path": "data/reports/S21_范围与规则证据.json",
        "S21_formal_rules_path": "config/S21_formal_rules.json",
        "S21_formal_rules_file_exists": False,
        "S21_rule_card_files_identified": [],
        "S21_vote_sheriff_rules": "unknown_pending_S21_primary_evidence",
        "S21_night_wake_order": "unknown_pending_S21_primary_evidence",
        "S21_special_role_mechanics": "unknown_pending_S21_primary_evidence",
        "S22_templates_or_special_rules_applied": False,
        "note": "S21规则证据报告未确认版型全套身份、夜序、警徽/投票规则或特殊互动；版型标题仅候选；不从模板填槽、不套计分或弃票规则。",
    }
    winner_candidates = []
    for recap in parseable:
        value = recap["parsed_candidates"].get("winning_faction")
        if value:
            winner_candidates.append({"candidate": value, "source_recap_candidate_id": recap["candidate_id"],
                                     "status": "machine_candidate_unconfirmed",
                                     "evidence": recap["source_excerpt"]})

    dossier = {
        "schema_version": 1,
        "status": "machine_candidate_unconfirmed",
        "season": "S21",
        "slug": f"bili-{entry['bvid']}-p{entry.get('page', 1):02d}-cid{entry['cid']}",
        "bvid": entry["bvid"], "cid": entry["cid"], "page": entry.get("page", 1),
        "title": entry["title"], "date_candidate": entry.get("date_candidate"),
        "phase_candidate": entry.get("phase_candidate"),
        "game_number_candidate": plan_entry.get("labels", {}).get("game_number_candidate"),
        "board_candidate": board,
        "source": {"path": source_path, "sha256": source_sha, "origin": evidence_entry.get("selected_transcript_origin")},
        "rule_context": policy,
        "seat_count_note": "本基线按任务要求保留12个空座位容器；S21证据报告不证明每局均有12名玩家。空位不按版型补猜。",
        "seats": seats,
        "identity_candidate_completeness": {"candidate_role_seats": len(role_counts), "seat_slots": 12,
                                            "all_12_role_candidates_present": len(role_counts) == 12},
        "recap_candidates": recaps,
        "rounds": rounds,
        "winner_candidates": winner_candidates,
        "issues": sorted(set([issue for recap in recaps for issue in recap.get("issues", [])] +
                             (["缺少S21正式版型/警徽/投票/夜序规则证据，所有自动字段仅保留机器候选。"]))),
    }
    votes = {
        "schema_version": 1, "game_slug": dossier["slug"], "season": "S21",
        "status": "machine_candidate_unconfirmed",
        "source": dossier["source"], "rule_context": policy,
        "ballot_prompt_candidate_count": vote_data["ballot_prompt_candidate_count"],
        "usable_reported_vote_round_candidate_count": vote_data["usable_reported_vote_round_candidate_count"],
        "reported_registration_contexts": [w for w in ctx if "registration_or_police_election" in w["cue_types"]],
        "ballots": vote_data["ballots"],
        "issues": [vote_data["policy"], "未验证S21的票权、警徽竞选、PK、弃票或计分规则；没有推断缺票或合法性。"],
    }
    evidence = {
        "schema_version": 1, "status": "machine_evidence_unconfirmed",
        "bvid": entry["bvid"], "cid": entry["cid"], "page": entry.get("page", 1),
        "source": dossier["source"], "rule_context": policy,
        "recap_full_text_candidates": [{"candidate_id": c["candidate_id"], "status": c["candidate_status"],
                                         "parse_status": c["parse_status"], "text": c["source_excerpt"]}
                                        for c in recaps if c.get("source_excerpt")],
        "registration_ballot_death_context_windows": ctx,
        "ballot_round_candidates": vote_data["ballots"],
        "last_game_day_speech_command_candidate": speech,
        "last_game_day_speech_context": [r for r in speech_context if r],
        "player_prophet_medium_self_claim_candidates": role_claims,
        "speaker_attribution_note": "所选转写没有speaker字段；自称候选的说话人归属未知，不能定为悍跳。",
        "winner_announcement_context_candidates": winner_cues,
        "special_event_quote_candidates": special_cues,
        "round_event_evidence_refs": event_refs,
        "notes": ["每个文本引文都含source path、SHA256、时间范围、段索引与原文。",
                  "特殊事件 cue仅保留原句与时点，不按不存在的S21规则补充机制。",
                  "本文件不是人工语义确认结果；不入库、不发布。"],
    }

    out = OUTPUT_ROOT / entry["bvid"]
    out.mkdir(parents=True, exist_ok=True)
    dossier_path = out / "baseline.dossier.json"
    voting_path = out / "baseline.voting.json"
    evidence_path = out / "baseline.evidence.json"
    text_path = out / "baseline.evidence.txt"
    write_json(dossier_path, dossier)
    write_json(voting_path, votes)
    write_json(evidence_path, evidence)
    text_path.write_text(render_packet(dossier, votes, evidence), encoding="utf-8")

    all_refs = collect_refs([dossier, votes, evidence])
    valid_indices = {r.get("source_segment_index") for r in segments}
    selected_rows_by_index = {r["index"]: r for r in segments}
    invalid_quote_refs = []
    exact_quote_matches = 0
    for ref in all_refs:
        source_indices = ref.get("source_segment_indices") or []
        segment_indices = ref.get("segment_indices") or []
        if (not source_indices or any(i not in valid_indices for i in source_indices)
                or not segment_indices or any(i not in selected_rows_by_index for i in segment_indices)):
            invalid_quote_refs.append(ref)
            continue
        quoted_rows = [selected_rows_by_index[i] for i in segment_indices]
        actual_quote = "\n".join(r["text"] for r in quoted_rows)
        if (actual_quote != ref.get("quote") or quoted_rows[0]["start_ms"] != ref.get("start_ms")
                or quoted_rows[-1]["end_ms"] != ref.get("end_ms")):
            invalid_quote_refs.append(ref)
        else:
            exact_quote_matches += 1
    cited_source_matches = source_file.is_file() and actual_sha == source_sha
    return {
        "index": entry["index"], "bvid": entry["bvid"], "cid": entry["cid"],
        "phase_candidate": entry.get("phase_candidate"), "board_candidate": board,
        "source_path": source_path, "source_sha256": source_sha,
        "source_sha256_matches": cited_source_matches,
        "recap_status": recap_file.get("recap_location", {}).get("status"),
        "recap_candidate_count": len(recaps),
        "parseable_recap_candidate_count": len(parseable),
        "role_candidate_seats": len(role_counts),
        "all_12_role_candidates_present": len(role_counts) == 12,
        "round_candidate_count": len(rounds),
        "round_event_candidate_count": sum(len(r["phase_event_candidates"]) for r in rounds),
        "ballot_prompt_candidate_count": vote_data["ballot_prompt_candidate_count"],
        "usable_reported_vote_round_candidate_count": vote_data["usable_reported_vote_round_candidate_count"],
        "special_event_quote_candidate_count": len(special_cues),
        "player_role_claim_candidate_count": len(role_claims),
        "evidence_quote_ref_count": len(all_refs),
        "exact_evidence_quote_match_count": exact_quote_matches,
        "missing_evidence_quote_ref_count": len(invalid_quote_refs),
        "output_paths": {"dossier": str(dossier_path.relative_to(ROOT)).replace("\\", "/"),
                          "voting": str(voting_path.relative_to(ROOT)).replace("\\", "/"),
                          "evidence": str(evidence_path.relative_to(ROOT)).replace("\\", "/"),
                          "evidence_text": str(text_path.relative_to(ROOT)).replace("\\", "/")},
    }


def collect_refs(value: Any) -> list[dict[str, Any]]:
    refs = []
    if isinstance(value, dict):
        if {"source_path", "source_sha256", "source_segment_indices", "quote"} <= set(value):
            refs.append(value)
        for child in value.values():
            refs.extend(collect_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(collect_refs(child))
    return refs


def render_packet(dossier: dict[str, Any], votes: dict[str, Any], evidence: dict[str, Any]) -> str:
    lines = [f"S21候选基线 | {dossier['title']}", f"BVID/CID: {dossier['bvid']} / {dossier['cid']}",
             f"来源: {dossier['source']['path']} SHA256={dossier['source']['sha256']}",
             "状态：机器候选，未确认；不入库、不发布。S21投票、夜序和特殊规则尚无正式规则文件。", "",
             f"身份候选：{dossier['identity_candidate_completeness']['candidate_role_seats']}/12座有文本候选；没有角色事实或阵营推断。",
             f"复盘窗口：{len(dossier['recap_candidates'])} 个；轮次候选：{len(dossier['rounds'])}；票轮候选：{votes['usable_reported_vote_round_candidate_count']} 个。", ""]
    for recap in evidence["recap_full_text_candidates"]:
        lines += [f"【复盘全文候选 {recap['candidate_id']} | {recap['status']} | {recap['parse_status']}】"]
        ref = recap["text"]
        # Keep each original utterance and timestamp separately for easy review.
        lines.append(f"来源定位：{ref['start_ms']}..{ref['end_ms']}ms；source_segment_indices={ref['source_segment_indices']}")
        lines.append(ref["quote"])
        lines.append("")
    for title, key in (("【报名/投票/死亡/夜间上下文候选】", "registration_ballot_death_context_windows"),
                       ("【玩家本人预言家/通灵师自称候选】", "player_prophet_medium_self_claim_candidates"),
                       ("【胜负/结束播报候选】", "winner_announcement_context_candidates"),
                       ("【特殊事件原句候选】", "special_event_quote_candidates")):
        lines.append(title)
        candidates = evidence.get(key, [])
        if not candidates:
            lines.append("未检出文本窗口；不代表原视频没有此事件。")
        for item in candidates:
            quote = item.get("quote")
            if quote is None and isinstance(item.get("evidence"), dict):
                quote = item["evidence"].get("quote")
            if quote is None and isinstance(item.get("text_context"), dict):
                quote = item["text_context"].get("quote")
            if quote:
                lines.append(f"[{item.get('start_ms', item.get('time_ms', ''))}..{item.get('end_ms', '')}ms] {quote}")
        lines.append("")
    lines.append("【报票轮次候选】")
    if not votes["ballots"]:
        lines.append("未检出明确报票口令候选；不据此推断没有投票。")
    for ballot in votes["ballots"]:
        lines.append(f"{ballot['ballot_id']} @ {ballot['time_ms']}ms 类型候选={ballot['type_candidate']} 报票数={ballot['reported_choice_count']} 状态=未确认")
        if ballot.get("text_context"):
            lines.append(ballot["text_context"]["quote"])
    return "\n".join(lines).rstrip() + "\n"


def run(limit: int | None = None) -> dict[str, Any]:
    scope = read_json(SCOPE_PATH)
    plan = read_json(PLAN_PATH)
    report_rules = read_json(RULE_EVIDENCE_PATH)
    retained_phases = set(scope.get("retained_phases", ["regular", "finals_week"]))
    excluded = set(scope.get("excluded_bvids", []))
    plan_by_bvid = {item["bvid"]: item for item in plan["entries"]}
    evidence_report_by_bvid = {
        item["bvid"]: item for item in report_rules.get("media_title_candidates", [])
    }
    entries = [read_json(path) for path in sorted(MEDIA_ROOT.glob("*/entry.json"))]
    entries = [e for e in entries if e.get("phase_candidate") in retained_phases and e.get("bvid") not in excluded]
    entries.sort(key=lambda e: e["index"])
    if limit is not None:
        entries = entries[:limit]
    results = []
    for entry in entries:
        if entry["bvid"] not in plan_by_bvid:
            raise ValueError(f"BVID missing from collection plan: {entry['bvid']}")
        item = build_game(entry, plan_by_bvid[entry["bvid"]], entry["index"])
        media_rule = evidence_report_by_bvid.get(entry["bvid"], {})
        item["S21_board_rule_status"] = media_rule.get("rule_evidence_status", "not_applicable_or_missing_from_rule_evidence_index")
        results.append(item)
        print(f"#{entry['index']} {entry['bvid']}: roles {item['role_candidate_seats']}/12; ballots {item['usable_reported_vote_round_candidate_count']} candidate rounds", flush=True)

    board_counts = Counter(item.get("board_candidate") or "版型候选未知" for item in results)
    source_ok = sum(item["source_sha256_matches"] for item in results)
    evidence_ok = sum(item["missing_evidence_quote_ref_count"] == 0 for item in results)
    all_ref_count = sum(item["evidence_quote_ref_count"] for item in results)
    exact_ref_count = sum(item["exact_evidence_quote_match_count"] for item in results)
    invalid_ref_count = sum(item["missing_evidence_quote_ref_count"] for item in results)
    full_roles = sum(item["all_12_role_candidates_present"] for item in results)
    role_distribution = Counter(str(item["role_candidate_seats"]) for item in results)
    vote_round_total = sum(item["usable_reported_vote_round_candidate_count"] for item in results)
    report = {
        "schema_version": 1, "season": "S21",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "machine_candidates_only_not_confirmed",
        "scope": {"scope_path": "config/S21_game_scope.json", "scope_sha256": digest(SCOPE_PATH),
                  "retained_media_total": scope.get("current_pending_media_total"),
                  "retained_phase_counts": scope.get("current_pending_media_by_phase"),
                  "indexed_baseline_media_count": len(results), "excluded_media_count": scope.get("excluded_media_total"),
                  "excluded_bvids_applied": len(excluded)},
        "rule_adaptation": {
            "rules_evidence_path": "data/reports/S21_范围与规则证据.json",
            "rules_evidence_sha256": digest(RULE_EVIDENCE_PATH),
            "S21_formal_rules_path": "config/S21_formal_rules.json",
            "S21_formal_rules_exists": False,
            "S21_rule_card_files_identified": report_rules.get("rules_and_flow_evidence", {}).get("S21_rule_card_files_identified_in_data_raw_rules", []),
            "vote_and_sheriff_rules": "unknown_pending_S21_primary_evidence",
            "night_wake_order": "unknown_pending_S21_primary_evidence",
            "special_role_mechanics": "unknown_pending_S21_primary_evidence",
            "existing_board_templates": "S22 structural references only; not used as S21 rules",
            "specific_gaps": report_rules.get("rules_and_flow_evidence", {}).get("special_role_mechanics", {}),
        },
        "extractor_adaptation": {
            "recap": "scripts/recap_parser.py::extract_recap; output is kept as unconfirmed candidates and no board template is consulted",
            "voting": "standalone explicit-prompt/report-vote phrase scanner; voting_records.py could not be imported because its module-level database import requires missing psycopg; no database API was called",
            "vote_semantics": "lexical ballot-kind label only; no S21 legality, 12-seat eligibility, missing-vote, abstention, PK, or scoring rule applied",
            "self_claims": "self-claim windows only; speaker attribution unavailable in selected transcript and bluff status is not classified",
        },
        "coverage": {
            "indexed_count": len(results), "source_sha256_matches": source_ok,
            "entries_with_all_quote_refs_resolving": evidence_ok,
            "total_quote_refs_checked": all_ref_count,
            "quote_refs_matching_source_text_and_time_exactly": exact_ref_count,
            "quote_ref_mismatches_or_missing_locators": invalid_ref_count,
            "twelve_slot_role_candidate_completeness": {
                "games_with_all_12_candidate_role_seats": full_roles,
                "candidate_role_seat_count_distribution": dict(sorted(role_distribution.items(), key=lambda kv: int(kv[0]))),
                "role_candidates_are_not_confirmed_facts": True,
            },
            "usable_announced_vote_round_candidates": vote_round_total,
            "available_vote_round_definition": "explicit ballot prompt plus at least one exact report-vote or abstain phrase; no legality, voters-eligible, or scoring inferred",
            "special_board_gaps": {"board_candidate_media_counts": dict(sorted(board_counts.items())),
                                    "all_S21_board_rules_unverified": True,
                                    "retained_media_with_special_cue_quotes": sum(item["special_event_quote_candidate_count"] > 0 for item in results),
                                    "note": "原句与时点留在evidence中；没有S21正式规则/规则卡，不能解释特殊动作或套用S22规则。"},
            "database_writes": False, "website_publication": False,
        },
        "items": results,
    }
    if limit is None:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        write_json(REPORT_PATH, report)
    else:
        # Sample runs write per-game baseline files but never replace the 122-game acceptance report.
        report["report_written"] = False
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="process only the first N retained entries")
    args = parser.parse_args()
    report = run(args.limit)
    print(json.dumps({"coverage": report["coverage"], "scope": report["scope"],
                      "acceptance_report": str(REPORT_PATH.relative_to(ROOT)) if args.limit is None else None},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
