"""One-time curation bridge for the reviewed 2026-10-28 S22 dot audit.

This file is removed after emitting the source-bound formal patchset. Runtime
generation uses only that formal patchset, never the unpublished candidate JSON.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import batch_s22

CANDIDATES = ROOT / "dot-handoff/LangRenSha-S22-S23-audit-3476a56-20261027/audit-published/S22/S22_字段问题候选.json"
OUT = ROOT / "data/extractions/S22/S22_dot_audit_patches_20261028.json"
HOLD = {"S22-A-027-02"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_rows(finding):
    raw = finding.get("evidence") or []
    rows = raw if isinstance(raw, list) else [raw]
    result = []
    for row in rows:
        path = row.get("source_path") or row.get("path")
        digest = row.get("source_sha256") or row.get("sha256")
        start = row.get("original_media_start_ms", row.get("start_ms"))
        end = row.get("original_media_end_ms", row.get("end_ms"))
        segments = row.get("segments", [])
        result.append({
            "path": path,
            "sha256": digest,
            "start_ms": start,
            "end_ms": end,
            "context": "\n".join(s.get("text", "") for s in segments),
            "classification": row.get("classification") or row.get("evidence_type"),
        })
    return result


def pointer_value(value, pointer):
    current = value
    for token in pointer.strip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def event(dossier, round_no, phase, slot):
    matches = [x for x in dossier["rounds"][round_no - 1].get(phase, []) if x.get("slot") == slot]
    if len(matches) != 1:
        raise ValueError(f"事件不唯一: {dossier.get('slug')} R{round_no}.{phase}.{slot}")
    return matches[0]


def dossier_patch(f, dossier):
    fid = f["finding_id"]
    if fid == "S22-A-020-01":
        src = event(dossier, 4, "day", "sequential_prince_skill")
        dst = event(dossier, 3, "day", "sequential_prince_skill")
        if src != f["old_value"]:
            raise ValueError(f"{fid} 源轮旧值不匹配")
        if dst.get("action") != "unknown" or dst.get("actor") != 10:
            raise ValueError(f"{fid} 目标轮不是未知占位")
        return [
            {"round": 3, "phase": "day", "slot": "sequential_prince_skill",
             "before": {"action": "unknown", "actor": 10, "targets": [], "result": None},
             "set": {"action": "reveal", "actor": 10, "result": "定序王子翻牌"}},
            {"round": 4, "phase": "day", "slot": "sequential_prince_skill",
             "before": {"action": "reveal", "actor": 10, "result": "定序王子翻牌"},
             "set": {"action": "unknown", "actor": 10, "result": None}},
        ]
    if fid == "S22-B-84-1":
        cur = event(dossier, 1, "day", "badge")
        expected = f["old_value"][0]
        if cur != expected:
            raise ValueError(f"{fid} 旧值不匹配")
        return [{"round": 1, "phase": "day", "slot": "badge",
                 "before": {"action": "transfer", "actor": None, "targets": [11]},
                 "set": {"action": "unknown", "actor": None, "targets": [], "result": None}}]
    if fid == "S22-B-84-2":
        attack = event(dossier, 3, "night", "wolf_attack")
        skill = event(dossier, 3, "night", "mechanical_action")
        return [
            {"round": 3, "phase": "night", "slot": "wolf_attack",
             "before": {"action": "unknown", "actor": None, "targets": []},
             "set": {"action": "attack", "actor": 9, "targets": [1]}},
            {"round": 3, "phase": "night", "slot": "mechanical_action",
             "before": {"action": "attack", "actor": 9, "targets": [1]},
             "set": {"action": "pass", "targets": [], "result": "破盾刀技能通过"}},
        ]
    if fid == "S22-B-116-1":
        return [
            {"round": 3, "phase": "night", "slot": "witch_poison",
             "before": {"action": "poison", "actor": 6, "targets": [11]},
             "set": {"action": "pass", "targets": []}},
            {"round": 4, "phase": "night", "slot": "witch_poison",
             "before": {"action": "unknown", "actor": 6, "targets": []},
             "set": {"action": "poison", "actor": 6, "targets": [11]}},
        ]
    if fid == "S22-B-112-2":
        return []

    # A-series pointers name the exact array element. B-series display paths
    # name an exact round/phase/slot and carry a one-element old event array.
    if f["field"].startswith("/"):
        cur = pointer_value(dossier, f["field"])
        if cur != f["old_value"]:
            raise ValueError(f"{fid} 指针旧值不匹配")
        round_no = int(f["field"].split("/")[2]) + 1
        phase = "night" if "/night/" in f["field"] else "day"
        slot = cur["slot"]
    else:
        m = re.fullmatch(r"R(\d+)\.(night|day)\.([a-z_]+)(?:\.result|\.None)?", f["field"])
        if not m:
            raise ValueError(f"未解析字段路径 {fid}: {f['field']}")
        round_no, phase, slot = int(m.group(1)), m.group(2), m.group(3)
        cur = event(dossier, round_no, phase, slot)
        old = f["old_value"]
        if isinstance(old, list):
            if len(old) != 1 or cur != old[0]:
                raise ValueError(f"{fid} 旧值不匹配")
        elif cur != old:
            raise ValueError(f"{fid} 旧值不匹配")
    sets = {k: v for k, v in f["candidate_value"].items() if k in cur and k not in {"note", "move_to_round"}}
    if not sets:
        raise ValueError(f"{fid} 没有可落地的正式字段")
    before = {k: cur.get(k) for k in sets}
    return [{"round": round_no, "phase": phase, "slot": slot, "before": before, "set": sets}]


def voting_patch(f, voting):
    fid = f["finding_id"]
    ballot_match = re.search(r"((?:causal-)?ballot-[^.]+)", f["field"])
    if not ballot_match:
        raise ValueError(f"{fid} 无法定位票轮")
    ballot_id = ballot_match.group(1)
    ballot = next((b for b in voting["ballots"] if b["id"] == ballot_id), None)
    if ballot is None:
        raise ValueError(f"{fid} 票轮不存在 {ballot_id}")
    if fid == "S22-V-012":
        return [{"op": "ballot_remove", "ballot_id": "ballot-4",
                 "where": {"day": 4, "kind": "exile", "number": 2}, "allow_missing": True}]
    if fid == "S22-V-030":
        return [{"op": "winner_set", "ballot_id": ballot_id,
                 "before_any": [f["old_value"]], "after": f["candidate_value"]}]
    if fid in {"S22-V-005", "S22-V-006"}:
        prior = f["old_value"]
        vote = prior.get("vote") if isinstance(prior, dict) else None
        voter = (vote or prior).get("voter")
        if voter is None:
            voter = int(re.search(r"\[(\d+)\]", f["field"]).group(1))
        return [{"op": "vote_remove", "ballot_id": ballot_id, "voter": voter,
                 "before": {"voter": voter, "target": None, "state": "abstained"},
                 "remove_from_eligibility": True, "allow_missing": True}]

    after_rows = f["candidate_value"] if isinstance(f["candidate_value"], list) else [f["candidate_value"]]
    ops = []
    for after in after_rows:
        voter = after["voter"]
        current = next((x for x in ballot["votes"] if x["voter"] == voter), None)
        if current is None:
            ops.append({"op": "vote_upsert", "ballot_id": ballot_id,
                        "after": after, "before": None, "allow_missing": True})
        else:
            ops.append({"op": "vote_upsert", "ballot_id": ballot_id,
                        "after": after, "before": {k: current.get(k) for k in ("voter", "target", "state")}})
    return ops


def main():
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8-sig"))["findings"]
    state = batch_s22.load_state()
    ids = [x["finding_id"] for x in candidates]
    if len(ids) != 101 or len(set(ids)) != 101:
        raise SystemExit(f"候选数/ID异常: {len(ids)}")
    findings = []
    for source_finding in candidates:
        f = copy.deepcopy(source_finding)
        f["disposition"] = "held" if f["finding_id"] in HOLD else "applied"
        f["review_basis"] = {
            "source_verified": True,
            "continuous_context_read": True,
            "prior_decision_checked": True,
            "boundary": "原文明确/因果唯一推断/既有用户定案按该项具体reason与prior_decision_check区分；未将ASR格式副本视为独立来源。",
        }
        f["sources"] = evidence_rows(f)
        for src in f["sources"]:
            if not src["path"] or not src["sha256"]:
                raise ValueError(f"{f['finding_id']} 证据缺路径/hash")
            actual = sha(ROOT / src["path"])
            if actual != src["sha256"]:
                raise ValueError(f"{f['finding_id']} 来源SHA不符: {src['path']}")
        f["patch"] = {"dossier": [], "voting": [], "endgame": []}
        if f["disposition"] == "applied":
            entry = state["items"][f["bvid"]]
            folder = ROOT / entry["output_dir"]
            if f["finding_id"].startswith("S22-V-"):
                voting = batch_s22.read_json(folder / "voting.json")
                f["patch"]["voting"] = voting_patch(f, voting)
            elif f["finding_id"] == "S22-B-112-2":
                f["patch"]["endgame"] = [{"phase_index": 0,
                    "before": {"day": 3}, "set": {"day": 4,
                    "note": "复盘先述第三天7号自爆，随后N4守卫守12、狼刀6，第四天放逐12后才拍刀。"}}]
            else:
                dossier = batch_s22.read_json(folder / "dossier.json")
                f["patch"]["dossier"] = dossier_patch(f, dossier)
        findings.append(f)

    patchset = {
        "schema_version": 1,
        "season": "S22",
        "reviewed_at": "2026-10-28",
        "review_protocol": "逐条对照来源原件/同源连续文本、哈希和当季正式规则；候选JSON仅为一次性审阅入口，运行时应用下列明确补丁。",
        "review_input": {"path": batch_s22.relative(CANDIDATES), "sha256": sha(CANDIDATES)},
        "findings": findings,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(patchset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"findings": len(findings), "applied": sum(x['disposition']=='applied' for x in findings),
                      "held": sum(x['disposition']=='held' for x in findings), "path": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
