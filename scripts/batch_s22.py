"""Recap-first S22 imports, separate review files, and resumable checkpoints."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SEASON_DIR = ROOT / "data/games/S22"
REPORT_DIR = ROOT / "data/reports"
STATE_FILE = REPORT_DIR / "S22_对局批处理进度.json"
JOURNAL_FILE = REPORT_DIR / "S22_对局批处理日志.jsonl"
LOCK_FILE = REPORT_DIR / "S22_对局批处理.lock"
CATALOG = ROOT / "data/seasons/S22/S22_音频与字幕总目录.csv"
REVIEW_CATALOG = ROOT / "data/seasons/S22/S22_中文优先复核目录.csv"
SUPPLEMENT_FILE = ROOT / "data/extractions/S22/复盘特殊动作补录.json"
SCHEDULE = ROOT / "data/weibo/2026-05-26_2026-10-20/比赛排班.csv"
COMPLETE = {"imported", "preserved", "reviewed"}
WOLF_ROLES = {"狼人", "机械狼", "狼王", "黑狼王", "诡术师", "假面", "典狱长"}
SLOT_ALIASES = {
    "mixer_model": "mixed_blood_model", "mixed_blood_target": "mixed_blood_model",
    "mask_check": "masquerade_verify", "mask_assign": "masquerade_mask",
    "illusion_swap": "guile_exchange", "magician_swap": "magician_exchange",
    "jailer_trade": "warden_trade_targets", "puppet_assign": "puppet_select",
}


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                # Windows readers can briefly deny rename while refreshing.
                # Keep the previous checkpoint intact and retry the same temp.
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative(path):
    return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


@contextmanager
def batch_lock(path=LOCK_FILE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("已有S22批处理进程正在运行，不重复启动。") from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def load_segments(path):
    value = read_json(path)
    rows = value.get("segments", value.get("body", [])) if isinstance(value, dict) else value
    segments = []
    for row in rows:
        if "start_ms" in row:
            start, end = int(row["start_ms"]), int(row.get("end_ms", row["start_ms"]))
            text = str(row.get("text", ""))
        else:
            start, end = round(float(row.get("from", 0)) * 1000), round(float(row.get("to", 0)) * 1000)
            text = str(row.get("content", ""))
        if text.strip() and start >= 0 and end >= start:
            segments.append({"start_ms": start, "end_ms": end, "text": text.strip()})
    return sorted(segments, key=lambda s: (s["start_ms"], s["end_ms"]))


def choose_transcript(row, review_row, root=ROOT):
    # The 25 completed full ASR files take priority over missing/truncated subtitles.
    for field, origin in [("本地全文JSON", "本地全文转写"), ("中文字幕原件", "平台中文字幕")]:
        candidate = review_row.get(field)
        if candidate and (root / candidate).is_file():
            return root / candidate, origin
    candidate = row.get("字幕原件")
    if candidate and (root / candidate).is_file():
        return root / candidate, "平台中文字幕"
    return None, "没有可读取转写"


def locate_recap(segments, duration_ms):
    from plan_recap_windows import analyze_subtitle
    status, windows = analyze_subtitle(segments, duration_ms, subtitle_present=bool(segments))
    strong = [w for w in windows if w.get("status") == "candidate"]
    if not strong:
        if not windows and segments:
            windows = [{"start_ms": max(0, duration_ms - 300_000), "end_ms": duration_ms,
                        "basis": ["tail_probe_no_formal_recap_detected"], "exact_boundary_verified": False}]
        return {"status": "localization_required", "windows": windows, "segments": [],
                "issues": ["尚未定位到同时含身份与行动的集中复盘，未从玩家自称或解说猜测提取。"]}
    # Earlier files can contain a preceding game's discussion. Prefer the last
    # concentrated roster, and preserve every competing window for human review.
    selected = max(strong, key=lambda w: w["start_ms"])
    selected_segments = [s for s in segments if s["end_ms"] >= selected["start_ms"] and s["start_ms"] <= selected["end_ms"]]
    issues = ["复盘由现有转写自动定位，数字与否定词尚未人工回听。"]
    if len(strong) > 1:
        issues.append("存在多个集中复盘候选，当前选择最后一段；请核对是否属于本局。")
    return {"status": "localized_candidate", "windows": windows, "selected": selected,
            "segments": selected_segments, "issues": issues}


def entries_from_catalog(*, include_excluded=False):
    from board_catalog import BOARD_CODES, canonical_board_name
    reviews = {r["BVID"]: r for r in read_csv(REVIEW_CATALOG)}
    entries = []
    for row in read_csv(CATALOG):
        bvid = row["BVID"]
        if not re.fullmatch(r"BV[0-9A-Za-z]+", bvid):
            raise ValueError("目录中的BVID格式不合法")
        name = canonical_board_name(row["配置候选"])
        number = int(row["局次候选"]) if row["局次候选"].isdigit() else None
        date = row["标题日期候选"]
        folder = f"{date}_g{number:02d}_{bvid}" if number else f"{date}_局次待核_{bvid}"
        source, origin = choose_transcript(row, reviews.get(bvid, {}))
        entries.append({"index": int(row["目录序号"]), "bvid": bvid, "cid": int(row["CID"]),
                        "page": int(row["分P"]), "date": date, "game_number": number,
                        "title": row["原始标题"], "board_name": name or row["配置候选"],
                        "board": BOARD_CODES.get(name), "output_dir": relative(SEASON_DIR / folder),
                        "audio_path": row["音频文件"], "source_path": relative(source) if source else None,
                        "transcript_origin": origin, "catalog_issues": row.get("待核事项", ""),
                        "phase": "regular" if row["阶段候选"].startswith("正赛") else {"表演赛": "showmatch", "决赛周": "finals_week", "特辑待核": "special"}.get(row["阶段候选"], "unknown"),
                        "episode": int(row["正赛期次候选"]) if row["正赛期次候选"].isdigit() else None})
    if len({(e["bvid"], e["cid"], e["page"]) for e in entries}) != len(entries):
        raise ValueError("目录有重复媒体，停止批处理。")
    if include_excluded:
        return entries
    from game_scope import exclusion_reason
    return [entry for entry in entries if not exclusion_reason(entry, root=ROOT)]


def load_state():
    if STATE_FILE.exists():
        state = read_json(STATE_FILE)
        if state.get("season") != "S22" or not isinstance(state.get("items"), dict):
            raise ValueError("批处理进度文件结构异常，保留原文件并停止。")
        from game_scope import exclusion_reason
        state["items"] = {bvid: entry for bvid, entry in state["items"].items()
                          if not exclusion_reason({**entry, "bvid": bvid}, root=ROOT)}
        return state
    return {"season": "S22", "created_at": now(), "items": {}, "last_processed": None}


def summary(state):
    entries = list(state["items"].values())
    counts = Counter(e.get("state", "pending") for e in entries)
    imported = counts["imported"] + counts["reviewed"]
    pending = [e for e in entries if e.get("state") not in COMPLETE]
    return {"total": len(entries), "imported": imported, "preserved": counts["preserved"],
            "reviewed": counts["reviewed"], "needs_review": counts["imported"], "pending": len(pending),
            "failed": counts["failed"], "known_roles": sum(e.get("known_roles", 0) for e in entries),
            "known_events": sum(e.get("known_events", 0) for e in entries),
            "last_processed": state.get("last_processed"), "next_bvid": pending[0]["bvid"] if pending else None,
            "next_review_bvid": next((e["bvid"] for e in entries if e.get("state") == "imported"), None)}


def checkpoint(state, event=None, *, render=True):
    state["updated_at"] = now()
    state["summary"] = summary(state)
    atomic_json(STATE_FILE, state)
    if event:
        with JOURNAL_FILE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": now(), **event}, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    if render:
        from batch_review import render_overview
        render_overview(SEASON_DIR, list(state["items"].values()), state["summary"])


def initialize(state):
    from game_scope import exclusion_reason
    state["items"] = {bvid: entry for bvid, entry in state.get("items", {}).items()
                      if not exclusion_reason({**entry, "bvid": bvid}, root=ROOT)}
    for incoming in entries_from_catalog():
        old = state["items"].get(incoming["bvid"], {})
        # Refresh source metadata without losing the completed transaction or
        # ownership hashes; a changed input is reprocessed by input_digest.
        state["items"][incoming["bvid"]] = {**old, **incoming}
        state["items"][incoming["bvid"]].setdefault("state", "pending")
    return state


def input_digest(entry):
    parts = [entry["bvid"], str(entry["cid"])]
    parts.append(json.dumps({key: entry.get(key) for key in (
        "title", "date", "game_number", "phase", "episode", "board", "page", "cid",
        "source_path", "audio_path", "transcript_origin", "catalog_issues")}, ensure_ascii=False, sort_keys=True))
    if entry["source_path"]:
        parts.append(digest(ROOT / entry["source_path"]))
    for path in [Path(__file__), ROOT / "scripts/recap_parser.py", ROOT / "scripts/recap_specials.py", ROOT / "scripts/batch_people.py", ROOT / "scripts/batch_review.py", ROOT / "scripts/board_catalog.py", ROOT / "scripts/game_records.py", ROOT / "config/board_templates" / (entry["board"] + ".json")]:
        parts.append(digest(path))
    from batch_people import SCHEDULE_REL, PHOTO_NAMES_REL, TOTAL_NAMES_REL, JUNE_25_SAMPLE_REL
    for relative_path in (SCHEDULE_REL, PHOTO_NAMES_REL, TOTAL_NAMES_REL, JUNE_25_SAMPLE_REL):
        path = ROOT / relative_path
        parts.append(digest(path) if path.is_file() else "missing:" + str(relative_path))
    parts.append(digest(SUPPLEMENT_FILE) if SUPPLEMENT_FILE.is_file() else "no-special-supplement")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def protect_existing(entry, old):
    dossier = ROOT / entry["output_dir"] / "dossier.json"
    if not dossier.exists():
        return False
    generated_hash = old.get("generated_dossier_sha256")
    return generated_hash is None or digest(dossier) != generated_hash


def faction_for(role):
    if role == "盗宝大师":
        return "werewolf"
    if role is None or role in {"傀儡", "混血儿"}:
        return None
    return "werewolf" if role in WOLF_ROLES else "third_party" if role == "鬼魂新娘" else "good"


def build_dossier(entry, extracted):
    from game_records import empty_event, template
    board = template(entry["board"])
    issues = list(extracted.get("issues", []))
    seats = []
    extracted_seats = {p["seat"]: p for p in extracted.get("seats", [])}
    for n in range(1, board["seat_count"] + 1):
        source = extracted_seats.get(n, {})
        role = source.get("role")
        if role == "白痴" and "白神" in board["role_counts"]:
            role = "白神"
        if role == "白神" and "白痴" in board["role_counts"]:
            role = "白痴"
        if role and not board.get("dynamic_roles") and role not in board["role_counts"]:
            issues.append(f"{n}号转写身份“{role}”不属于本版配置，身份暂空，保留复盘原文待核。")
            role = None
        faction = "third_party" if entry["board"] == "ghost_bride" and source.get("faction") == "third_party" else faction_for(role)
        seats.append({"seat": n, "name": None, "role": role, "faction": faction,
                      "learning_target": source.get("learning_target") if role == "机械狼" else None,
                      "learned_role": source.get("learned_role") if role == "机械狼" else None})
    if not board.get("dynamic_roles"):
        counts = Counter(s["role"] for s in seats if s["role"])
        for role, count in counts.items():
            if count > board["role_counts"].get(role, 0):
                issues.append(f"转写中{role}共{count}个，超过配置；冲突座位的该身份均暂空，不能靠数量猜哪一个正确。")
                for seat in seats:
                    if seat["role"] == role:
                        seat.update(role=None, faction=None, learning_target=None, learned_role=None)
    rounds, unmapped = [], []
    role_seats = {}
    for seat in seats:
        if seat["role"]:
            role_seats.setdefault(seat["role"], []).append(seat["seat"])
    for source_round in extracted.get("rounds", []):
        number = source_round["number"]
        if number != len(rounds) + 1:
            issues.append("复盘轮次不连续，未擅自填补缺少的游戏轮次。")
            break
        round_ = {"number": number}
        for phase in ("night", "day"):
            slots = board[phase + "_slots"]
            events = []
            for slot in slots:
                actors = role_seats.get(slot["actor_role"], [])
                events.append(empty_event(slot["code"], actors[0] if len(actors) == 1 else None))
            candidates = {}
            for event in source_round.get(phase, []):
                code = SLOT_ALIASES.get(event.get("slot"), event.get("slot"))
                candidates.setdefault(code, []).append({**event, "slot": code})
            for code, proposals in candidates.items():
                slot = next((s for s in slots if s["code"] == code), None)
                current = next((e for e in events if e["slot"] == code), None)
                if slot is None:
                    unmapped.extend({"round": number, "phase": phase, **p} for p in proposals)
                    continue
                # Repeat mentions of the same action are harmless; different
                # actions in one fixed slot remain visible, never overwritten.
                unique = {json.dumps({k: p.get(k) for k in ("action", "actor", "targets", "result")}, ensure_ascii=False, sort_keys=True): p for p in proposals}
                if len(unique) > 1:
                    issues.append(f"第{number}轮{slot['label']}存在多次或冲突记录，业务槽位保留未知，全部原记录列入复核。")
                    unmapped.extend({"round": number, "phase": phase, **p} for p in unique.values())
                    continue
                proposal = next(iter(unique.values()))
                action = proposal.get("action", "unknown")
                if action not in slot["actions"]:
                    unmapped.append({"round": number, "phase": phase, **proposal})
                    continue
                actor = proposal.get("actor") or current["actor"]
                actor_role = seats[actor-1]["role"] if isinstance(actor, int) and 1 <= actor <= len(seats) else None
                expected = slot["actor_role"]
                allowed_wolf_boom = code == "self_destruct" and actor_role in WOLF_ROLES - {"机械狼"}
                if actor_role and ((expected and expected != "狼队" and actor_role != expected and not allowed_wolf_boom)
                                   or (expected == "狼队" and actor_role not in WOLF_ROLES)
                                   or (code == "self_destruct" and action == "self_destruct" and actor_role == "机械狼")):
                    issues.append(f"第{number}轮{slot['label']}行动人与身份表不一致，操作暂留复核。")
                    unmapped.append({"round": number, "phase": phase, **proposal})
                    continue
                current.update(action=action, actor=actor, targets=proposal.get("targets", []), result=proposal.get("result"))
            round_[phase] = events
        rounds.append(round_)
    day_match = re.search(r"Day[-\s]*(\d+)", entry["title"], re.I)
    raw = Path("data/raw/bilibili") / entry["bvid"] / f"p{entry['page']:02d}"
    key = f"{entry['bvid']}:{entry['cid']}"
    files = []
    for role, path, kind in [("audio", entry["audio_path"], "audio"),
                              ("manifest", (raw / "manifest.json").as_posix(), "manifest"),
                              ("metadata", (raw / "metadata.raw.json").as_posix(), "metadata")]:
        if (ROOT / path).is_file():
            files.append({"role": role, "path": path, "kind": kind, "platform": "bilibili", "external_key": key})
    if entry["source_path"]:
        is_asr = entry["transcript_origin"] == "本地全文转写"
        files.append({"role": "transcript" if is_asr else "subtitle", "path": entry["source_path"],
                      "kind": "asr" if is_asr else "subtitle", "platform": "bilibili", "external_key": key})
    number_slug = f"g{entry['game_number']:02d}" if entry["game_number"] else "gunknown"
    value = {"slug": f"bili-{entry['bvid']}-p{entry['page']:02d}-{number_slug}", "season": "S22",
             "date": entry["date"], "phase": entry["phase"], "episode": entry["episode"],
             "day_in_episode": int(day_match[1]) if day_match else None, "game_number": entry["game_number"],
             "board": board["code"], "winner": extracted.get("winning_faction"),
             "roster": [], "commentators": [], "referee": None, "seats": seats, "rounds": rounds, "files": files}
    if not rounds:
        issues.append("未提取到明确轮次，当前只入基本资料与可确定身份，没有伪造第一夜。")
    return value, issues, unmapped


def coverage(value):
    events = [e for r in value["rounds"] for phase in ("night", "day") for e in r[phase]]
    return {"known_roles": sum(p.get("role") is not None for p in value["seats"]),
            "named_seats": sum(p.get("name") is not None for p in value["seats"]),
            "rounds": len(value["rounds"]), "known_events": sum(e["action"] != "unknown" for e in events),
            "total_events": len(events)}


def backup_database(state):
    from database import configuration, connect
    from local_postgres import BIN
    if state.get("backup") and (ROOT / state["backup"]).is_file():
        return
    config = configuration()
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
    target = ROOT / "data/backups" / f"S22批处理前_{stamp}.dump"
    target.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    args = [str(BIN / "pg_dump.exe"), "--format=custom", "--file", str(target)]
    if os.environ.get("DATABASE_URL"):
        # A URL can contain credentials: keep it in the child environment.
        environment["PGDATABASE"] = os.environ["DATABASE_URL"]
    else:
        for key, option in [("host", "--host"), ("port", "--port"), ("user", "--username"), ("dbname", "--dbname")]:
            args.extend([option, str(config[key])])
        environment["PGPASSWORD"] = config["password"]
    result = subprocess.run(args, env=environment, capture_output=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode or not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("批处理前数据库备份失败，停止写入；请检查本地PostgreSQL。")
    with connect() as conn:
        state["database_before"] = dict(conn.execute("SELECT (SELECT count(*) FROM game_details) AS games, (SELECT count(*) FROM game_event_records) AS events").fetchone())
    state["backup"] = relative(target)
    checkpoint(state, {"stage": "database_backup", "path": state["backup"]})


def database_has(entry):
    from database import connect
    receipt = entry.get("db_receipt")
    if not receipt:
        return False
    with connect() as conn:
        row = conn.execute("SELECT g.id, (SELECT count(*) FROM game_event_records e WHERE e.game_id=g.id) AS events FROM games g JOIN game_details d ON d.game_id=g.id WHERE g.slug=%s", (receipt["slug"],)).fetchone()
    return bool(row and str(row["id"]) == receipt["game_id"] and row["events"] == receipt["event_records"])


def database_snapshot():
    from database import connect
    with connect() as conn:
        counts = dict(conn.execute("""SELECT count(*) AS games,
            (SELECT count(*) FROM game_event_records e JOIN games g2 ON e.game_id=g2.id
             JOIN seasons s2 ON s2.id=g2.season_id WHERE s2.code='S22') AS events
            FROM game_details d JOIN games g ON g.id=d.game_id
            JOIN seasons s ON s.id=g.season_id WHERE s.code='S22'""").fetchone())
        counts["known_roles"] = conn.execute("""SELECT count(*) AS n FROM game_seats p
            JOIN games g ON p.game_id=g.id JOIN seasons s ON s.id=g.season_id
            WHERE s.code='S22' AND p.role IS NOT NULL""").fetchone()["n"]
    return counts


def recap_text_for(segments):
    return "\n".join(f"[{s['start_ms']/1000:.3f}–{s['end_ms']/1000:.3f}] {s['text']}" for s in segments)


def apply_recap_supplement(entry, segments, result):
    """Apply AI-read special actions only when their exact source still matches."""
    if not SUPPLEMENT_FILE.is_file() or not segments:
        return result
    supplement = read_json(SUPPLEMENT_FILE).get("items", {}).get(entry["bvid"])
    if not supplement:
        return result
    expected_path = entry["output_dir"] + "/复盘原文.txt"
    exported_text = (recap_text_for(segments) + "\n").replace("\n", os.linesep)
    recap_hash = hashlib.sha256(exported_text.encode("utf-8")).hexdigest()
    if supplement.get("recap_sha256") != recap_hash or supplement.get("source_path") != expected_path:
        result.setdefault("issues", []).append("特殊动作补录与当前复盘原文不一致，未采用旧补录；请重新核对。")
        return result
    rounds = {r["number"]: r for r in result.get("rounds", [])}
    applied = 0
    for event in supplement.get("events", []):
        number, phase = event.get("number"), event.get("phase")
        if number not in rounds or phase not in {"night", "day"}:
            result.setdefault("issues", []).append("特殊动作补录没有对应的已识别轮次，未创建轮次。")
            continue
        if set(event) != {"number", "phase", "slot", "action", "actor", "targets", "result"}:
            raise ValueError("特殊动作补录字段不合法")
        rounds[number].setdefault(phase, []).append({k: v for k, v in event.items() if k not in {"number", "phase"}})
        applied += 1
    result.setdefault("issues", []).extend(supplement.get("issues", []))
    if applied:
        result["issues"].append(f"另采用复盘特殊动作补录中的{applied}条AI逐句整理记录，尚待人工回听；来源：data/extractions/S22/复盘特殊动作补录.json。")
    if supplement.get("factions"):
        if entry.get("board") != "ghost_bride":
            raise ValueError("当前补录仅允许鬼魂新娘明确播报的第三方阵营")
        seats = {s["seat"]: s for s in result.get("seats", [])}
        for declaration in supplement["factions"]:
            if set(declaration) != {"seat", "faction"} or declaration["faction"] != "third_party" or declaration["seat"] not in seats:
                raise ValueError("第三方阵营补录不合法")
            seats[declaration["seat"]]["faction"] = "third_party"
    return result


def extract_game_recap(segments, board_name, entry=None):
    """Combine explicit common and board-specific actions in existing rounds."""
    from recap_parser import extract_recap
    from recap_specials import extract_specials
    result = extract_recap(segments, board_name)
    special = extract_specials(segments, board_name, result)
    rounds = {r["number"]: r for r in result.get("rounds", [])}
    for event in special["events"]:
        number, phase = event["number"], event["phase"]
        if number not in rounds or phase not in {"night", "day"}:
            result.setdefault("issues", []).append("特殊动作缺少对应轮次，保留待核。")
            continue
        rounds[number].setdefault(phase, []).append({k: v for k, v in event.items() if k not in {"number", "phase"}})
    result.setdefault("issues", []).extend(special["issues"])
    if entry:
        apply_recap_supplement(entry, segments, result)
    return result


def process_entry(entry, state, *, dry_run=False):
    from game_records import import_game, validate
    from batch_review import render_game
    out = ROOT / entry["output_dir"]
    old = dict(entry)
    out.mkdir(parents=True, exist_ok=True)
    if protect_existing(entry, old):
        value = read_json(out / "dossier.json")
        entry.update(coverage(value), state="preserved", auto_protected=True, updated_at=now())
        entry["issues"] = ["已有示例或人工修改，自动批处理保留该档案。可用import-edits显式重新入库。"]
        receipt_path = out / "database_receipt.json"
        if receipt_path.exists():
            entry["db_receipt"] = read_json(receipt_path)
        checkpoint(state, {"bvid": entry["bvid"], "stage": "preserved_existing"})
        return
    signature = input_digest(entry)
    if entry.get("state") in {"imported", "reviewed"} and entry.get("input_sha256") == signature and not dry_run and database_has(entry):
        if not (out / "复核.html").exists() and (out / "复核记录.json").exists():
            render_game(out, read_json(out / "dossier.json"), read_json(out / "复核记录.json"))
        return
    entry.update(state="processing", stage="locating_recap", updated_at=now())
    checkpoint(state, {"bvid": entry["bvid"], "stage": "locating_recap"})
    segments = load_segments(ROOT / entry["source_path"]) if entry["source_path"] else []
    location = locate_recap(segments, max((s["end_ms"] for s in segments), default=0))
    entry["recap_status"] = location["status"]
    atomic_json(out / "复盘定位.json", {k: v for k, v in location.items() if k != "segments"})
    recap_segments = location["segments"]
    recap_text = recap_text_for(recap_segments)
    (out / "复盘原文.txt").write_text(recap_text + "\n" if recap_text else "尚未自动定位集中复盘；请查看复盘定位.json与定位上下文.txt，不把上下文当作法官复盘。\n", encoding="utf-8")
    if not recap_segments and location["windows"]:
        window = location["windows"][-1]
        context = [s for s in segments if s["end_ms"] >= window["start_ms"] and s["start_ms"] <= window["end_ms"]]
        (out / "定位上下文.txt").write_text("以下只供定位回听，未作为身份或游戏事实提取依据。\n" + "\n".join(f"[{s['start_ms']/1000:.3f}] {s['text']}" for s in context) + "\n", encoding="utf-8")
    extracted = extract_game_recap(recap_segments, entry["board_name"], entry) if recap_segments else {"seats": [], "rounds": [], "winning_faction": None, "issues": []}
    value, issues, unmapped = build_dossier(entry, extracted)
    from batch_people import enrich_people
    value, people_issues, people_context = enrich_people(value, entry)
    issues.extend(people_issues)
    issues = location["issues"] + issues
    if entry.get("catalog_issues"):
        issues.append("来源目录待核：" + entry["catalog_issues"])
    validate(value, allow_incomplete=True)
    review = {"bvid": entry["bvid"], "title": entry["title"], "board_name": entry["board_name"],
              "audio_path": entry["audio_path"], "source_path": entry["source_path"],
              "recap_segments": recap_segments, "recap_start_ms": recap_segments[0]["start_ms"] if recap_segments else None,
              "recap_end_ms": recap_segments[-1]["end_ms"] if recap_segments else None,
              "recap_status": location["status"], "issues": issues, "unmapped_events": unmapped,
              "state": "prepared" if dry_run else "awaiting_import", "db_receipt": None,
              "people_sources": people_context}
    atomic_json(out / "dossier.json", value)
    entry.update(coverage(value), input_sha256=signature, generated_dossier_sha256=digest(out / "dossier.json"),
                 state="prepared", stage="validated", issues=issues, updated_at=now())
    atomic_json(out / "复核记录.json", review)
    checkpoint(state, {"bvid": entry["bvid"], "stage": "validated"})
    if not dry_run:
        receipt = import_game(value, allow_incomplete=True)
        atomic_json(out / "database_receipt.json", receipt)
        review.update(db_receipt=receipt, state="imported")
        atomic_json(out / "复核记录.json", review)
        entry.update(state="imported", stage="committed", db_receipt=receipt, imported_dossier_sha256=digest(out / "dossier.json"), updated_at=now())
        entry.pop("error", None)
        state["last_processed"] = f"原目录#{entry['index']} {entry['date']} {entry['bvid']} {entry['board_name']}"
        checkpoint(state, {"bvid": entry["bvid"], "stage": "committed", "game_id": receipt["game_id"]})
    render_game(out, value, review)
    checkpoint(state)


def render_failure(entry):
    """Export a failed item's source context without manufacturing a dossier."""
    from batch_review import render_game
    out = ROOT / entry["output_dir"]
    out.mkdir(parents=True, exist_ok=True)
    location_file = out / "复盘定位.json"
    location = read_json(location_file) if location_file.exists() else {}
    selected = location.get("selected")
    segments = []
    if selected and entry.get("source_path"):
        segments = [s for s in load_segments(ROOT / entry["source_path"])
                    if s["end_ms"] >= selected["start_ms"] and s["start_ms"] <= selected["end_ms"]]
    dossier_file = out / "dossier.json"
    value = read_json(dossier_file) if dossier_file.exists() else build_dossier(entry, {"seats": [], "rounds": []})[0]
    review = {"bvid": entry["bvid"], "title": entry["title"], "board_name": entry["board_name"],
              "audio_path": entry["audio_path"], "source_path": entry.get("source_path"),
              "recap_segments": segments, "recap_start_ms": segments[0]["start_ms"] if segments else None,
              "recap_end_ms": segments[-1]["end_ms"] if segments else None,
              "recap_status": location.get("status", "localization_required"),
              "issues": entry.get("issues", []) + [entry.get("error", "此条尚未完成入库")],
              "unmapped_events": [], "state": "failed", "db_receipt": entry.get("db_receipt")}
    atomic_json(out / "复核记录.json", review)
    render_game(out, value, review)


def print_status(state):
    report = summary(state)
    report["progress_file"] = relative(STATE_FILE)
    report["review_page"] = "data/games/S22/批量复核.html"
    try:
        report["database_actual"] = database_snapshot()
    except Exception:
        report["database_actual"] = "当前无法连接数据库，磁盘进度仍保留。"
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "run", "status", "import-edits", "mark-reviewed"])
    parser.add_argument("--bvid")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)
    if args.bvid and not re.fullmatch(r"BV[0-9A-Za-z]+", args.bvid):
        parser.error("BVID格式不合法")
    if args.limit is not None and args.limit <= 0:
        parser.error("limit必须大于0")
    if args.action == "status":
        state = load_state()
        print_status(state)
        return 0
    with batch_lock():
        state = initialize(load_state())
        checkpoint(state)
        if args.action == "plan":
            print_status(state)
            return 0
        if args.action in {"import-edits", "mark-reviewed"}:
            if not args.bvid or args.bvid not in state["items"]:
                parser.error("此动作必须指定目录中的--bvid")
            entry = state["items"][args.bvid]
            out = ROOT / entry["output_dir"]
            if args.action == "import-edits":
                from game_records import import_game
                value = read_json(out / "dossier.json")
                previous_slug = entry.get("db_receipt", {}).get("slug")
                if value.get("season") != "S22" or (previous_slug and value.get("slug") != previous_slug):
                    raise ValueError("人工修正不得改变赛季或已登记的对局标识；仅修改本局内容。")
                receipt = import_game(value, allow_incomplete=True)
                atomic_json(out / "database_receipt.json", receipt)
                entry.update(coverage(value), state="imported", db_receipt=receipt, auto_protected=True,
                             imported_dossier_sha256=digest(out / "dossier.json"), updated_at=now())
                # No generated hash: future automatic runs protect manual edits.
                entry.pop("generated_dossier_sha256", None)
                entry["issues"] = ["用户编辑的dossier已重新入库，尚未标记人工复核完成。"]
            else:
                if entry.get("state") not in COMPLETE or not database_has(entry):
                    raise ValueError("只有已入库并核对到数据库记录的对局才能标记已复核。")
                if digest(out / "dossier.json") != entry.get("imported_dossier_sha256"):
                    raise ValueError("档案存在未入库的修改或没有当前文件收据，请先执行import-edits。")
                value = read_json(out / "dossier.json")
                entry.update(state="reviewed", auto_protected=True, reviewed_at=now(), review_note=args.note)
            from batch_review import render_game
            review_path = out / "复核记录.json"
            review = read_json(review_path) if review_path.exists() else {"bvid": entry["bvid"],
                "title": entry["title"], "board_name": entry["board_name"], "recap_segments": [],
                "audio_path": entry["audio_path"], "source_path": entry.get("source_path")}
            review.update(state=entry["state"], issues=entry.get("issues", []), db_receipt=entry.get("db_receipt"),
                          review_note=args.note, updated_at=now())
            atomic_json(review_path, review)
            render_game(out, value, review)
            checkpoint(state, {"bvid": args.bvid, "stage": args.action, "note": args.note})
            print_status(state)
            return 0
        if not args.prepare_only:
            from database import migrate
            backup_database(state)
            applied = migrate()
            if applied:
                checkpoint(state, {"stage": "database_migrations", "applied": applied})
        processed = 0
        for entry in state["items"].values():
            if args.bvid and entry["bvid"] != args.bvid:
                continue
            if entry.get("state") in {"preserved", "reviewed"} or entry.get("auto_protected"):
                continue
            if not entry.get("board"):
                entry.update(state="failed", issues=["版型尚未识别，保留原目录项，未套用其他版型。"])
                checkpoint(state)
                continue
            try:
                before = entry.get("updated_at")
                process_entry(entry, state, dry_run=args.prepare_only)
                if entry.get("updated_at") != before:
                    processed += 1
                    print(f"[原目录#{entry['index']}] {entry['bvid']} {entry['state']} 身份{entry.get('known_roles',0)}/12 事件{entry.get('known_events',0)}/{entry.get('total_events',0)}", flush=True)
            except Exception as exc:
                entry.update(state="failed", stage="failed", error=f"{type(exc).__name__}: {exc}", updated_at=now())
                entry.setdefault("issues", []).append(entry["error"])
                checkpoint(state, {"bvid": entry["bvid"], "stage": "failed", "error": entry["error"]})
                try:
                    render_failure(entry)
                except Exception as page_error:
                    entry["issues"].append("复核页生成失败：" + type(page_error).__name__)
                    checkpoint(state)
                print(f"[原目录#{entry['index']}] {entry['bvid']} failed: {entry['error']}", flush=True)
            if args.limit and processed >= args.limit:
                break
        if not args.prepare_only:
            state["database_after"] = database_snapshot()
        checkpoint(state)
        print_status(state)
        return 1 if any(e.get("state") == "failed" for e in state["items"].values()) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
