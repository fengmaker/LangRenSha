"""Apply source-bound, sentence-by-sentence S22 transcript review without video."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

import batch_s22 as batch
from game_records import empty_event, import_game, template, validate

PROGRESS = batch.ROOT / "data/reports/S22_转写逐句复核进度.json"
ANNOTATIONS = batch.ROOT / "data/extractions/S22"
REVIEW_VERSION = 3


def load_annotations():
    items = {}
    for path in sorted(ANNOTATIONS.glob("逐句核对_*.json")):
        value = batch.read_json(path)
        for bvid, annotation in value.get("items", {}).items():
            if bvid in items:
                raise ValueError("逐句核对范围重复：" + bvid)
            items[bvid] = annotation
    return items


def question(field, reason, quote="", start_ms=None, end_ms=None, candidate=None):
    value = {"field": field, "reason": reason, "quote": quote, "start_ms": start_ms, "end_ms": end_ms}
    if candidate is not None:
        value["candidate"] = candidate
    value["id"] = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:14]
    return value


def make_round(board, number, seats):
    result = {"number": number}
    for phase in ("night", "day"):
        events = []
        for slot in board[phase + "_slots"]:
            actors = [s["seat"] for s in seats if s.get("role") == slot["actor_role"]]
            events.append(empty_event(slot["code"], actors[0] if len(actors) == 1 else None))
        result[phase] = events
    return result


def question_label(field, board):
    seat = re.search(r"seats\[(\d+)\]\.(role|name|faction|learning_target|learned_role)", field)
    if seat:
        return seat[1] + "号" + {"role": "身份", "name": "姓名", "faction": "阵营", "learning_target": "学习目标", "learned_role": "学习形态"}[seat[2]]
    event = re.search(r"round(\d+)\.(night|day)\.([a-z_]+)", field)
    if event:
        label = next((s["label"] for s in board[event[2] + "_slots"] if s["code"] == event[3]), event[3])
        return "第" + event[1] + ("夜" if event[2] == "night" else "天") + " · " + label
    return {"seats": "座位身份名单", "seats.role": "座位身份名单", "events": "行动记录", "rounds": "轮次数", "winner": "胜方", "recap": "集中复盘缺失"}.get(field, field)


def attach_context(questions, segments):
    """Link gaps to raw same-round text; this is navigation, not new evidence."""
    from recap_parser import _stage_spans
    pieces, ranges, position = [], [], 0
    for segment in segments:
        text = re.sub(r"\s+", "", segment.get("text", ""))
        pieces.append(text)
        ranges.append((position, position + len(text), segment))
        position += len(text)
    source = "".join(pieces)
    spans = _stage_spans(source)
    for q in questions:
        if q.get("quote") or not ranges:
            continue
        field = q["field"]
        event = re.search(r"round(\d+)\.(night|day)(?:\.|_)", field)
        selected = []
        if event:
            number, phase = int(event[1]), event[2]
            selected = [i for i, s in enumerate(spans) if s[2] == number and s[1] == phase]
            # Night deaths are often announced before the explicit day cue.
            if (phase == "day" and "night_deaths" in field) or not selected:
                selected += [i for i, s in enumerate(spans) if s[2] == number and s[1] == "night"]
        elif field.startswith("seats") and any(x in field for x in ("learning_target", "learned_role")):
            selected = [i for i, s in enumerate(spans) if s[2] == 1 and s[1] == "night"]
        elif field == "rounds":
            selected = list(range(max(0, len(spans) - 2), len(spans)))
        if selected:
            intervals = [(spans[i][0], spans[i + 1][0] if i + 1 < len(spans) else len(source)) for i in set(selected)]
        elif field.startswith("seats"):
            first_night = next((s[0] for s in spans if s[1] == "night" and s[2] == 1), len(source))
            intervals = [(0, first_night)]
        else:
            continue
        rows = [s for start, end, s in ranges if any(end > a and start < b for a, b in intervals)]
        if rows:
            q.update(context_quote="\n".join(s["text"] for s in rows), context_start_ms=rows[0]["start_ms"],
                     context_end_ms=rows[-1]["end_ms"])


def normalize_result(slot, result, board):
    if result is None:
        return None
    if slot in {"wolf_attack", "witch_save", "witch_poison", "guard", "sheriff_result", "badge",
                "exile_result", "night_deaths", "hunter_shot", "self_destruct", "mixed_blood_model"}:
        return None
    if slot in {"seer_check", "masquerade_verify"}:
        text = str(result)
        if "好人" in text:
            return "好人"
        if "狼人" in text:
            return "狼人"
        for role in sorted(set(board.get("role_counts", {})) | set(board.get("role_pool", {})), key=len, reverse=True):
            if role in text:
                return role
    return result


def merge_review(original, annotation):
    """Fill confirmed gaps; contradictory existing facts remain visible for a person."""
    value = copy.deepcopy(original)
    board = template(value["board"])
    questions = [question(q.get("field", "本局"), q.get("reason", "转写不清楚"), q.get("quote", ""),
                          q.get("start_ms"), q.get("end_ms")) for q in annotation.get("unresolved", [])]
    changes = []
    seats = {s["seat"]: s for s in value["seats"]}
    role_limits = board.get("role_counts", {})
    for proposed in annotation.get("seats", []):
        number = proposed.get("seat")
        if number not in seats:
            questions.append(question("seats", "补充座位越界，未采用", candidate=proposed))
            continue
        seat = seats[number]
        for key in ("role", "name", "learning_target", "learned_role"):
            incoming = proposed.get(key)
            if key == "role" and incoming in {"白神", "白痴"}:
                incoming = "白神" if "白神" in role_limits else "白痴" if "白痴" in role_limits else incoming
            if incoming is None or incoming == seat.get(key):
                continue
            if key in {"learning_target", "learned_role"} and seat.get("role") != "机械狼":
                questions.append(question(f"seats[{number}].{key}", "学习候选无法对应已知机械狼座位，未移植给其他身份", candidate=incoming))
                continue
            if key == "learned_role":
                incoming = {"狼人": "机械双刀狼", "通灵师": "机械通灵师", "女巫": "机械女巫",
                            "猎人": "机械猎人", "守卫": "机械守卫", "平民": "机械平民"}.get(incoming, incoming)
                if incoming not in board.get("mechanical_forms", {}):
                    questions.append(question(f"seats[{number}].learned_role", "学习形态词无法对应本版型，未采用", candidate=incoming))
                    continue
                target_role = seats.get(seat.get("learning_target"), {}).get("role")
                learned_from = board["mechanical_forms"][incoming].get("learned_from")
                if target_role and target_role != learned_from:
                    questions.append(question(f"seats[{number}].learned_role", "学习候选与已知学习目标底牌不符，需核对", candidate=incoming))
                    continue
            if incoming == seat.get(key):
                continue
            if seat.get(key) is not None:
                questions.append(question(f"seats[{number}].{key}", "新核对候选与现有记录不同，保留原值供你确认", candidate=incoming))
                continue
            if key == "role" and not board.get("dynamic_roles"):
                if incoming not in role_limits or sum(s.get("role") == incoming for s in seats.values()) >= role_limits[incoming]:
                    questions.append(question(f"seats[{number}].role", "候选身份与版型已知人数冲突，未猜补", candidate=incoming))
                    continue
            if key == "name" and any(s.get("name") == incoming for s in seats.values()):
                questions.append(question(f"seats[{number}].name", "同一姓名已有其他座位，需核对", candidate=incoming))
                continue
            seat[key] = incoming
            if key == "role":
                seat["faction"] = batch.faction_for(incoming)
            changes.append({"field": f"seats[{number}].{key}", "before": None, "after": incoming})
        if proposed.get("faction") is not None and proposed["faction"] != seat.get("faction"):
            dynamic = seat.get("role") == "混血儿" or board["code"] == "ghost_bride"
            if seat.get("faction") is None or dynamic:
                old = seat.get("faction")
                seat["faction"] = proposed["faction"]
                changes.append({"field": f"seats[{number}].faction", "before": old, "after": seat["faction"]})
            elif seat.get("role") == "盗宝大师":
                questions.append(question(f"seats[{number}].faction", "盗宝大师始终属于狼人阵营，未采用冲突候选", candidate=proposed["faction"]))
    for round_ in value["rounds"]:
        for phase in ("night", "day"):
            specs = {slot["code"]: slot for slot in board[phase + "_slots"]}
            for index, event in enumerate(round_[phase]):
                actor_role = seats.get(event.get("actor"), {}).get("role")
                expected = specs[event["slot"]].get("actor_role")
                bad_actor = actor_role and expected and expected != "狼队" and actor_role != expected
                if bad_actor and not (event["slot"] == "self_destruct" and actor_role in batch.WOLF_ROLES):
                    questions.append(question(f"round{round_['number']}.{phase}.{event['slot']}",
                        "补充身份后发现原行动者与底牌不一致，原动作保留为待核候选", candidate=event))
                    round_[phase][index] = empty_event(event["slot"])
    declared_rounds = annotation.get("round_count")
    if type(declared_rounds) is int and len(value["rounds"]) < declared_rounds <= 12:
        for number in range(len(value["rounds"]) + 1, declared_rounds + 1):
            value["rounds"].append(make_round(board, number, value["seats"]))
            changes.append({"field": "rounds", "before": None, "after": number})
    elif type(declared_rounds) is int and declared_rounds != len(value["rounds"]):
        questions.append(question("rounds", "文字核对轮数与现有轮次不同，未自动删除记录", candidate=declared_rounds))
    for proposed in annotation.get("events", []):
        number, phase, slot = proposed.get("number"), proposed.get("phase"), proposed.get("slot")
        if type(number) is not int or not 1 <= number <= len(value["rounds"]) or phase not in {"night", "day"}:
            questions.append(question("events", "动作没有对应的明确轮次，未采用", candidate=proposed))
            continue
        spec = next((s for s in board[phase + "_slots"] if s["code"] == slot), None)
        if not spec:
            questions.append(question(f"round{number}.{phase}.{slot}", "本版型没有该槽位，保留待核候选", candidate=proposed))
            continue
        events = value["rounds"][number - 1][phase]
        event_index = next(i for i, e in enumerate(events) if e["slot"] == slot)
        previous = events[event_index]
        candidate = copy.deepcopy(previous)
        for key in empty_event(slot):
            if key in proposed:
                candidate[key] = copy.deepcopy(proposed[key])
        candidate["result"] = normalize_result(slot, candidate["result"], board)
        actor = candidate.get("actor")
        expected_role = spec.get("actor_role")
        if actor is None and expected_role and expected_role != "狼队":
            actors = [s["seat"] for s in seats.values() if s.get("role") == expected_role]
            candidate["actor"] = actors[0] if len(actors) == 1 else None
        if previous["action"] != "unknown" and (previous["action"], previous["targets"]) != (candidate["action"], candidate["targets"]):
            questions.append(question(f"round{number}.{phase}.{slot}", "动作或目标与已有记录不同，保留双方候选供你确认", candidate=proposed))
            continue
        if candidate == previous:
            continue
        events[event_index] = candidate
        try:
            validate(value, check_files=False, allow_incomplete=True)
        except Exception as exc:
            events[event_index] = previous
            questions.append(question(f"round{number}.{phase}.{slot}", "候选未通过规则校验：" + str(exc), candidate=proposed))
        else:
            changes.append({"field": f"round{number}.{phase}.{slot}", "before": previous, "after": candidate})
    if annotation.get("winner") and value.get("winner") is None:
        value["winner"] = annotation["winner"]
        changes.append({"field": "winner", "before": None, "after": value["winner"]})
    validate(value, check_files=False, allow_incomplete=True)
    for q in questions:
        if not q.get("quote"):
            evidence = [c for c in annotation.get("corrections", []) if c.get("field") == q["field"]]
            if not evidence and re.fullmatch(r"seats\[\d+\]\.role", q["field"]):
                evidence = [c for c in annotation.get("corrections", []) if c.get("field") in {"seats", "seats.role"}]
            if len(evidence) == 1:
                for key in ("quote", "start_ms", "end_ms"):
                    q[key] = evidence[0].get(key)
        q["label"] = question_label(q["field"], board)
    return value, changes, questions


def progress_summary(state, progress):
    entries = list(state["items"].values())
    active_progress = {bvid: item for bvid, item in progress.get("items", {}).items() if bvid in state["items"]}
    done = [e for e in entries if progress.get("items", {}).get(e["bvid"], {}).get("status") in {"text_checked", "questions", "no_recap", "preserved", "user_reviewed"}]
    pending = [e for e in entries if e not in done]
    return {"total": len(entries), "text_checked": len(done) - sum(e.get("state") == "preserved" for e in done),
            "preserved": sum(e.get("state") == "preserved" for e in done), "pending": len(pending),
            "questions": sum(x.get("question_count", 0) for x in active_progress.values()),
            "with_questions": sum(x.get("status") == "questions" for x in active_progress.values()),
            "no_recap": sum(x.get("status") == "no_recap" for x in active_progress.values()),
            "supplemented_fields": sum(x.get("changes", 0) for x in active_progress.values()),
            "last_processed": progress.get("last_processed"), "next_text_bvid": pending[0]["bvid"] if pending else None}


def apply_all():
    from batch_review import render_game, export_questions
    with batch.batch_lock():
        state = batch.load_state()
        progress = batch.read_json(PROGRESS) if PROGRESS.exists() else {"items": {}, "created_at": batch.now()}
        if not progress.get("backup"):
            batch.backup_database(progress)
            batch.atomic_json(PROGRESS, progress)
        annotations = load_annotations()
        frame_progress_path = batch.ROOT / "data/reports/S22_画面座位补全进度.json"
        frame_progress = batch.read_json(frame_progress_path) if frame_progress_path.exists() else {"items": {}}
        for entry in state["items"].values():
            bvid = entry["bvid"]
            if entry.get("state") in {"preserved", "reviewed"}:
                progress["items"][bvid] = {"status": "preserved" if entry["state"] == "preserved" else "user_reviewed", "question_count": 0}
                continue
            if bvid not in annotations:
                continue
            annotation = annotations[bvid]
            if annotation.get("scope") not in {"recap_text", "full_transcript"}:
                raise ValueError("本轮仅允许转写文字依据：" + bvid)
            out = batch.ROOT / entry["output_dir"]
            signature = hashlib.sha256(json.dumps(annotation, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            old_progress = progress["items"].get(bvid, {})
            if old_progress.get("annotation_sha256") == signature and old_progress.get("review_version") == REVIEW_VERSION:
                continue
            if batch.digest(out / "复盘原文.txt") != annotation.get("recap_sha256"):
                progress["items"][bvid] = {"status": "source_changed", "error": "复盘原文已变化，未采用旧核对"}
                continue
            original = batch.read_json(out / "dossier.json")
            try:
                review = batch.read_json(out / "复核记录.json")
                backup = batch.ROOT / "data/archive/S22_text_review" / (bvid + ".before.json")
                # A revised AI annotation replaces its own earlier suggestions.
                # A person's intervening edits remain the merge base instead.
                unchanged_since_apply = old_progress.get("dossier_sha256") == batch.digest(out / "dossier.json")
                frame_hash = frame_progress.get("items", {}).get(bvid, {}).get("dossier_sha256")
                only_frame_update = (review.get("frame_seats") and not review.get("user_saved_at")
                                     and frame_hash == batch.digest(out / "dossier.json"))
                unchanged_since_apply = unchanged_since_apply or only_frame_update
                basis = batch.read_json(backup) if backup.exists() and unchanged_since_apply else original
                if review.get("frame_seats"):
                    actual_names = {s["seat"]: s.get("name") for s in original["seats"]}
                    for seat in basis["seats"]:
                        seat["name"] = actual_names[seat["seat"]]
                    basis["roster"] = copy.deepcopy(original["roster"])
                value, changes, questions = merge_review(basis, annotation)
                if not backup.exists():
                    batch.atomic_json(backup, original)
                attach_context(questions, review.get("recap_segments", []))
                review["text_review"] = {"checked_at": batch.now(), "scope": annotation.get("scope", "recap_text"),
                    "summary": annotation.get("summary", ""), "corrections": annotation.get("corrections", []),
                    "changes": changes, "questions": questions, "source_sha256": annotation.get("recap_sha256")}
                old_answers = review.get("question_answers", {})
                all_questions = questions + review.get("frame_seats", {}).get("questions", [])
                review["question_answers"] = {q["id"]: old_answers[q["id"]] for q in all_questions if q["id"] in old_answers}
                review["issues"] = [q["field"] + "：" + q["reason"] for q in all_questions]
                batch.atomic_json(out / "dossier.json", value)
                try:
                    receipt = import_game(value, allow_incomplete=True)
                except Exception:
                    batch.atomic_json(out / "dossier.json", original)
                    raise
                batch.atomic_json(out / "database_receipt.json", receipt)
                review.update(db_receipt=receipt, state="imported")
                batch.atomic_json(out / "复核记录.json", review)
                file_hash = batch.digest(out / "dossier.json")
                status = "no_recap" if annotation.get("status") == "no_recap" else "questions" if questions else "text_checked"
                entry.update(batch.coverage(value), state="imported", auto_protected=True, imported_dossier_sha256=file_hash,
                             db_receipt=receipt, text_review_status=status, text_question_count=len(questions),
                             issues=review["issues"], updated_at=batch.now())
                entry.pop("generated_dossier_sha256", None)
                progress["items"][bvid] = {"status": status, "question_count": len(questions), "changes": len(changes),
                    "review_version": REVIEW_VERSION,
                    "annotation_sha256": signature, "dossier_sha256": file_hash, "checked_at": batch.now()}
                progress["last_processed"] = f"原目录#{entry['index']} {bvid}"
                render_game(out, value, review)
                batch.checkpoint(state, {"bvid": bvid, "stage": "text_review_applied", "changes": len(changes), "questions": len(questions)})
                print(f"[原目录#{entry['index']}] {bvid}: 补充{len(changes)}项，疑点{len(questions)}项", flush=True)
            except Exception as exc:
                progress["items"][bvid] = {"status": "failed", "error": type(exc).__name__ + ": " + str(exc)}
                print(f"[原目录#{entry['index']}] {bvid}: failed {type(exc).__name__}: {exc}", flush=True)
            progress["updated_at"] = batch.now()
            progress["summary"] = progress_summary(state, progress)
            batch.atomic_json(PROGRESS, progress)
        progress["updated_at"] = batch.now()
        progress["summary"] = progress_summary(state, progress)
        batch.atomic_json(PROGRESS, progress)
        batch.checkpoint(state)
        export_questions(batch.SEASON_DIR, list(state["items"].values()))
        print(json.dumps(progress["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["apply", "status"])
    args = parser.parse_args()
    if args.action == "apply":
        apply_all()
    else:
        state = batch.load_state()
        progress = batch.read_json(PROGRESS) if PROGRESS.exists() else {"items": {}}
        print(json.dumps(progress_summary(state, progress), ensure_ascii=False, indent=2))
