"""Replay source-bound contextual reviews without claiming human verification."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data/extractions/S22/causal_review_20261025/accepted.json"


def load(entry):
    if not REVIEW.is_file():
        return None
    report = json.loads(REVIEW.read_text(encoding="utf-8"))
    item = next((x for x in report["items"] if x["bvid"] == entry["bvid"]), None)
    if item is None:
        return None
    seen = set()
    for decision in item.get("decisions", []):
        key = decision["question_id"]
        if (key in seen or not key.startswith("vote-" + entry["bvid"] + "-") or
                type(decision.get("resolved")) is not bool or
                decision.get("confidence") not in {"high", "medium", "low"} or
                not decision.get("reason") or not decision.get("conclusion") or
                (decision["resolved"] and decision["confidence"] == "low")):
            raise ValueError("因果复核结论格式或置信度不合法：" + key)
        seen.add(key)
    source = ROOT / entry["source_path"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != item["source_sha256"]:
        raise ValueError("因果复核所依据的转写已变化：" + entry["bvid"])
    confirmation = item.get("user_confirmation")
    if confirmation and hashlib.sha256((ROOT / confirmation["path"]).read_bytes()).hexdigest() != confirmation["sha256"]:
        raise ValueError("人工确认记录已变化：" + entry["bvid"])
    return copy.deepcopy(item)


def evidence(item, entry):
    return [{"path": entry["source_path"], **span} for decision in item.get("decisions", [])
            for span in decision.get("source_spans", [])]


def apply(facts, audit, entry):
    item = load(entry)
    if item is None:
        return
    for patch in item.get("patches", []):
        kind = patch["kind"]
        if kind == "registration_set":
            before, after = patch["before"], patch["after"]
            if facts["registrations"] not in (before, after):
                raise ValueError("报名名单因果修正基线已变化：" + entry["bvid"])
            facts["registrations"] = copy.deepcopy(after)
            for r in after:
                audit["evidence"][r["id"]] = patch.get("evidence") or evidence(item, entry)
        elif kind == "ballot_add":
            after = patch["after"]
            current = next((b for b in facts["ballots"] if b["id"] == after["id"]), None)
            if current is not None and current != after:
                raise ValueError("补录轮次与当前提取冲突：" + entry["bvid"] + "." + after["id"])
            if current is None:
                facts["ballots"].append(copy.deepcopy(after))
            audit["evidence"][after["id"]] = patch.get("evidence") or evidence(item, entry)
        elif kind == "interruption_add":
            after = patch["after"]
            if not any(x["id"] == after["id"] for x in facts["interruptions"]):
                facts["interruptions"].append(copy.deepcopy(after))
            audit["evidence"][after["id"]] = patch.get("evidence") or evidence(item, entry)
        elif kind in {"ballot", "interruption"}:
            rows = facts["ballots" if kind == "ballot" else "interruptions"]
            current = next(x for x in rows if x["id"] == patch["id"])
            for field, value in patch["after"].items():
                if current[field] not in (patch["before"][field], value):
                    raise ValueError("因果修正字段基线已变化：" + entry["bvid"] + "." + patch["id"] + "." + field)
                current[field] = copy.deepcopy(value)
            audit["evidence"].setdefault(patch["id"], []).extend(patch.get("evidence", []))
        elif kind == "ballot_remove":
            current = next((b for b in facts["ballots"] if b["id"] == patch["id"]), None)
            if current is not None:
                if current != patch["before"]:
                    raise ValueError("排除误提取轮次的基线已变化：" + entry["bvid"])
                facts["ballots"].remove(current)
        else:
            raise ValueError("未知因果复核修正：" + kind)
    # Recover original chronological order after inserting missed first/PK rounds.
    facts["ballots"].sort(key=lambda b: (audit["evidence"].get(b["id"], [{}])[0].get("start_ms", float("inf")), b["id"]))
    resolved_codes = {d["question_id"].split("-source_conflict-", 1)[1] for d in item["decisions"]
                      if d["resolved"] and "-source_conflict-" in d["question_id"]}
    resolved_issues = [s for s in audit.get("issues", []) if hashlib.sha256(s.encode()).hexdigest()[:8] in resolved_codes]
    audit["issues"] = [s for s in audit.get("issues", []) if s not in resolved_issues]
    audit.setdefault("resolved_issues", []).extend(resolved_issues)
    audit["causal_review"] = item
    if item.get("human_confirmations"):
        audit["human_confirmations"] = copy.deepcopy(item["human_confirmations"])
    if item.get("default_abstentions"):
        audit.setdefault("rule_applications", []).extend(
            {"target": x["target"], "voters": x["voters"]} for x in item["default_abstentions"])
    if item.get("terminal"):
        audit["causal_terminal"] = item["terminal"]


def day_outcomes(rows, audit):
    updates = {d["day"]: d for d in audit.get("causal_review", {}).get("day_outcomes", [])}
    return [{**r, **updates.get(r["day"], {})} for r in rows]


def disposition(questions, audit):
    decisions = audit.get("causal_review", {}).get("decisions", [])
    mapping = {d["question_id"]: d for d in decisions}
    remaining = []
    for q in questions:
        decision = mapping.get(q["id"])
        if decision and decision["resolved"]:
            continue
        if decision:
            q = {**q, "reason": decision.get("residual_reason") or decision["reason"],
                 "causal_review": decision, "manual_required": True}
        remaining.append(q)
    return remaining, decisions
