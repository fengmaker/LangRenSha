"""Source-bound, idempotent S22 corrections from the 2026-10-28 dot audit.

The published candidate snapshot is a review input only. Runtime correction
uses the curated patch contract under data/extractions/S22 and fails closed if
the bound transcript hash or current value has changed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PATCHSET_PATH = ROOT / "data/extractions/S22/S22_dot_audit_patches_20261028.json"
REPORT_JSON = ROOT / "data/reports/S22_dot审计落地_20261028.json"
REPORT_MD = ROOT / "data/reports/S22_dot审计落地_20261028.md"
_VALIDATED_SOURCE_STAMPS: set[tuple[Any, ...]] = set()


class PatchConflict(ValueError):
    """A source-bound patch no longer matches the current S22 record."""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def load_patchset(path: Path = PATCHSET_PATH) -> dict[str, Any]:
    value = read_json(path)
    if value.get("schema_version") != 1 or value.get("season") != "S22":
        raise ValueError("S22 dot审计补丁文件的版本或赛季不正确")
    ids = [x["finding_id"] for x in value.get("findings", [])]
    if len(ids) != len(set(ids)):
        raise ValueError("S22 dot审计补丁中finding_id重复")
    return value


def validate_sources(patchset: dict[str, Any], root: Path = ROOT) -> dict[str, int]:
    """Verify every accepted patch source still has its recorded bytes."""
    refs = {}
    reference_count = 0
    for finding in patchset.get("findings", []):
        for source in [*finding.get("sources", []), *finding.get("supplemental_sources", [])]:
            reference_count += 1
            refs[source["path"]] = source["sha256"]
    # In a batch regeneration, each game calls the hook. Cache only while all
    # source file metadata remains stable; a source replacement invalidates the
    # key and gets a fresh full SHA-256 read.
    stamps = []
    for rel in sorted(refs):
        path = root / rel
        if not path.is_file():
            raise PatchConflict(f"来源缺失：{rel}")
        stat = path.stat()
        stamps.append((rel, stat.st_size, stat.st_mtime_ns))
    signature = (str(root.resolve()), tuple(stamps), tuple(sorted(refs.items())))
    if signature in _VALIDATED_SOURCE_STAMPS:
        return {"accepted_findings": sum(x.get("disposition") == "applied" for x in patchset.get("findings", [])),
                "source_references": reference_count,
                "unique_source_files": len(refs), "source_files_hash_matched": len(refs)}
    for rel, expected in refs.items():
        path = root / rel
        if digest(path) != expected:
            raise PatchConflict(f"来源SHA256变化：{rel}")
    _VALIDATED_SOURCE_STAMPS.add(signature)
    return {"accepted_findings": sum(x.get("disposition") == "applied" for x in patchset.get("findings", [])),
            "source_references": reference_count,
            "unique_source_files": len(refs), "source_files_hash_matched": len(refs)}


def _event(dossier: dict[str, Any], op: dict[str, Any]) -> dict[str, Any]:
    round_number = op["round"]
    rounds = [r for r in dossier.get("rounds", []) if r.get("number") == round_number]
    if len(rounds) != 1:
        raise PatchConflict(f"轮次不存在：{dossier.get('slug')} R{round_number}")
    events = rounds[0].get(op["phase"], [])
    matches = [x for x in events if x.get("slot") == op["slot"]]
    if len(matches) != 1:
        raise PatchConflict(f"事件槽位不唯一：{dossier.get('slug')} R{round_number}.{op['phase']}.{op['slot']}")
    return matches[0]


def _unresolved_value(field: str, value: Any, replacement: Any) -> bool:
    if value is None or (isinstance(value, str) and value in {"unknown", "not_observed", "unobserved"}):
        return True
    if field == "targets" and value == [] and replacement != []:
        return True
    return False


def _update_fields(current: dict[str, Any], expected: dict[str, Any], replacement: dict[str, Any], where: str,
                   *, allow_unresolved: bool = False,
                   before_alternatives: dict[str, list[Any]] | None = None) -> bool:
    if all(current.get(k) == v for k, v in replacement.items()):
        return False
    matches_before = all(current.get(k) == v for k, v in expected.items())
    matches_rebase = allow_unresolved and all(
        current.get(k) == expected.get(k) or current.get(k) == replacement.get(k) or
        current.get(k) in (before_alternatives or {}).get(k, []) or
        _unresolved_value(k, current.get(k), replacement.get(k))
        for k in set(expected) | set(replacement)
    )
    if not matches_before and not matches_rebase:
        bad = {k: {"expected": expected.get(k), "actual": current.get(k), "replacement": replacement.get(k)}
               for k in set(expected) | set(replacement)
               if current.get(k) != expected.get(k) and current.get(k) != replacement.get(k)}
        raise PatchConflict(f"修订前字段不匹配：{where} {json.dumps(bad, ensure_ascii=False)}")
    current.update(replacement)
    return True


def apply_dossier(dossier: dict[str, Any], bvid: str, *, patchset: dict[str, Any] | None = None,
                  root: Path = ROOT, allow_unresolved: bool = False) -> list[str]:
    patchset = patchset or load_patchset()
    changed = []
    for finding in patchset["findings"]:
        if finding.get("disposition") != "applied" or finding["bvid"] != bvid:
            continue
        if allow_unresolved and finding.get("generation_policy", {}).get("create_rounds_through"):
            _ensure_generated_rounds(dossier, finding["generation_policy"]["create_rounds_through"])
        for op in finding.get("patch", {}).get("dossier", []):
            current = _event(dossier, op)
            where = f"{dossier.get('slug')} R{op['round']}.{op['phase']}.{op['slot']}"
            if _update_fields(current, op["before"], op["set"], where, allow_unresolved=allow_unresolved,
                              before_alternatives=op.get("before_alternatives")):
                changed.append(finding["finding_id"])
    return sorted(set(changed))


def _ensure_generated_rounds(dossier: dict[str, Any], through: int) -> None:
    """Create only unknown template slots needed to host a source-bound later-round fact."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from game_records import empty_event, template
    board = template(dossier["board"])
    seats_by_role: dict[str, list[int]] = {}
    for seat in dossier.get("seats", []):
        if seat.get("role"):
            seats_by_role.setdefault(seat["role"], []).append(seat["seat"])
    rounds = dossier.setdefault("rounds", [])
    by_number = {r["number"]: r for r in rounds}
    for number in range(1, through + 1):
        if number in by_number:
            continue
        row = {"number": number, "night": [], "day": []}
        for phase in ("night", "day"):
            for slot in board[f"{phase}_slots"]:
                actors = seats_by_role.get(slot["actor_role"], []) if slot.get("actor_role") else []
                actor = actors[0] if len(actors) == 1 else None
                row[phase].append(empty_event(slot["code"], actor))
        rounds.append(row)
        by_number[number] = row
    rounds.sort(key=lambda r: r["number"])


def _ballot(facts: dict[str, Any], ballot_id: str) -> dict[str, Any] | None:
    return next((b for b in facts.get("ballots", []) if b.get("id") == ballot_id), None)


def _sort_and_recount(facts: dict[str, Any], *, after_rules: bool) -> None:
    ordinals: dict[tuple[Any, Any], int] = {}
    for ballot in facts.get("ballots", []):
        key = (ballot.get("day"), ballot.get("kind"))
        ordinals[key] = ordinals.get(key, 0) + 1
        ballot["number"] = ordinals[key]
        ballot["votes"].sort(key=lambda x: x["voter"])
        if after_rules:
            eligible = ballot.get("eligible_voters")
            voters = {v["voter"] for v in ballot["votes"]}
            ballot["unrecorded_voters"] = sorted(set(eligible) - voters) if eligible is not None else None
            ballot["status"] = "complete" if eligible is not None and not ballot["unrecorded_voters"] else "partial"


def apply_voting(facts: dict[str, Any], bvid: str, *, patchset: dict[str, Any] | None = None,
                 after_rules: bool = False) -> list[str]:
    """Apply reviewed ballot changes; leave voter eligibility to rules on rebuild."""
    patchset = patchset or load_patchset()
    changed = []
    for finding in patchset["findings"]:
        if finding.get("disposition") != "applied" or finding["bvid"] != bvid:
            continue
        for op in finding.get("patch", {}).get("voting", []):
            kind = op["op"]
            if kind == "vote_upsert":
                ballot = _ballot(facts, op["ballot_id"])
                if ballot is None:
                    raise PatchConflict(f"投票轮不存在：{bvid} {op['ballot_id']}")
                voter = op["after"]["voter"]
                current = next((v for v in ballot["votes"] if v["voter"] == voter), None)
                after = op["after"]
                if current == after:
                    continue
                before = op.get("before")
                if current is None and op.get("allow_missing", False):
                    ballot["votes"].append(dict(after))
                elif current is not None and before is not None and all(current.get(k) == v for k, v in before.items()):
                    current.update(after)
                else:
                    raise PatchConflict(f"投票者值冲突：{bvid} {op['ballot_id']} {voter}号")
                changed.append(finding["finding_id"])
            elif kind == "vote_remove":
                ballot = _ballot(facts, op["ballot_id"])
                if ballot is None:
                    raise PatchConflict(f"投票轮不存在：{bvid} {op['ballot_id']}")
                voter = op["voter"]
                current = next((v for v in ballot["votes"] if v["voter"] == voter), None)
                if current is None and op.get("allow_missing", False):
                    continue
                if current is None or not all(current.get(k) == v for k, v in op.get("before", {}).items()):
                    raise PatchConflict(f"待移除选票值冲突：{bvid} {op['ballot_id']} {voter}号")
                ballot["votes"].remove(current)
                if after_rules and op.get("remove_from_eligibility", False) and ballot.get("eligible_voters") is not None:
                    ballot["eligible_voters"] = [n for n in ballot["eligible_voters"] if n != voter]
                changed.append(finding["finding_id"])
            elif kind == "winner_set":
                ballot = _ballot(facts, op["ballot_id"])
                if ballot is None:
                    raise PatchConflict(f"投票轮不存在：{bvid} {op['ballot_id']}")
                if ballot.get("winner") == op["after"]:
                    continue
                if ballot.get("winner") not in op.get("before_any", []):
                    raise PatchConflict(f"投票结果冲突：{bvid} {op['ballot_id']}")
                ballot["winner"] = op["after"]
                changed.append(finding["finding_id"])
            elif kind == "ballot_remove":
                ballot = _ballot(facts, op["ballot_id"])
                if ballot is None and op.get("allow_missing", False):
                    continue
                if ballot is None:
                    raise PatchConflict(f"待移除投票轮不存在：{bvid} {op['ballot_id']}")
                if any(ballot.get(k) != v for k, v in op["where"].items()):
                    raise PatchConflict(f"待移除投票轮不匹配：{bvid} {op['ballot_id']}")
                if any(v.get("state") != "abstained" or v.get("target") is not None for v in ballot.get("votes", [])):
                    raise PatchConflict(f"重复轮不再是全弃票，停止移除：{bvid} {op['ballot_id']}")
                facts["ballots"].remove(ballot)
                changed.append(finding["finding_id"])
            else:
                raise ValueError(f"未知投票修订操作：{kind}")
    if changed:
        _sort_and_recount(facts, after_rules=after_rules)
        if after_rules:
            by_day = {d["day"]: d for d in facts.get("days", [])}
            for day in set(b.get("day") for b in facts["ballots"] if b.get("day") is not None):
                row = by_day.get(day)
                if row and any(b.get("day") == day and b.get("kind") == "exile" for b in facts["ballots"]):
                    row["exile"] = "recorded"
    return sorted(set(changed))


def apply_endgame(sidecar: dict[str, Any], bvid: str, *, patchset: dict[str, Any] | None = None) -> list[str]:
    patchset = patchset or load_patchset()
    changed = []
    for finding in patchset["findings"]:
        if finding.get("disposition") != "applied" or finding["bvid"] != bvid:
            continue
        for op in finding.get("patch", {}).get("endgame", []):
            phases = sidecar.get("phases", [])
            index = op["phase_index"]
            if index >= len(phases):
                raise PatchConflict(f"終局階段不存在：{bvid} index={index}")
            if _update_fields(phases[index], op["before"], op["set"], f"{bvid} endgame[{index}]"):
                changed.append(finding["finding_id"])
    return sorted(set(changed))


def apply_generated_dossier(value: dict[str, Any], entry: dict[str, Any], *, root: Path = ROOT) -> list[str]:
    patchset = load_patchset()
    if not any(f.get("disposition") == "applied" and f["bvid"] == entry["bvid"] for f in patchset["findings"]):
        return []
    validate_sources(patchset, root)
    return apply_dossier(value, entry["bvid"], patchset=patchset, root=root, allow_unresolved=True)


def apply_generated_voting(facts: dict[str, Any], audit: dict[str, Any], entry: dict[str, Any]) -> list[str]:
    patchset = load_patchset()
    if not any(f.get("disposition") == "applied" and f["bvid"] == entry["bvid"] and f.get("patch", {}).get("voting")
               for f in patchset["findings"]):
        return []
    validate_sources(patchset)
    changed = apply_voting(facts, entry["bvid"], patchset=patchset, after_rules=False)
    if changed:
        audit.setdefault("dot_audit_applied", []).extend(changed)
        audit["dot_audit_applied"] = sorted(set(audit["dot_audit_applied"]))
    return changed


def apply_current_files(*, root: Path = ROOT) -> dict[str, Any]:
    """Patch current S22 files only. Does not connect to or write the database."""
    patchset = load_patchset()
    source_check = validate_sources(patchset, root)
    import sys
    sys.path.insert(0, str(root / "scripts"))
    import batch_s22 as batch
    from voting_records import validate as validate_voting
    from game_records import validate as validate_dossier
    from voting_rules import apply_rules
    from voting_crosscheck import reconcile, day_outcomes
    from game_flow import collect_death_announcements
    state = batch.load_state()
    touched: list[str] = []
    changed_findings: set[str] = set()
    replayed_games: list[str] = []
    for bvid, entry in state["items"].items():
        findings = [f for f in patchset["findings"] if f.get("disposition") == "applied" and f["bvid"] == bvid]
        if not findings:
            continue
        folder = root / entry["output_dir"]
        dossier_path, voting_path = folder / "dossier.json", folder / "voting.json"
        dossier = batch.read_json(dossier_path)
        dchanged = apply_dossier(dossier, bvid, patchset=patchset, root=root)
        changed_findings.update(dchanged)
        validate_dossier(dossier, allow_incomplete=True)
        if dchanged:
            atomic_json(dossier_path, dossier)
            touched.append(dossier_path.relative_to(root).as_posix())

        voting = batch.read_json(voting_path)
        vchanged = apply_voting(voting, bvid, patchset=patchset, after_rules=False)
        changed_findings.update(vchanged)
        audit_path = root / "data/extractions/S22/voting" / f"{bvid}.json"
        audit = batch.read_json(audit_path) if audit_path.is_file() else None
        endgame_path = folder / "endgame.json"
        endgame = batch.read_json(endgame_path) if endgame_path.is_file() else None
        echanged = apply_endgame(endgame, bvid, patchset=patchset) if endgame is not None else []
        changed_findings.update(echanged)
        if echanged:
            atomic_json(endgame_path, endgame)
            touched.append(endgame_path.relative_to(root).as_posix())

        # Rebuild dependencies even when the correction itself was already
        # applied. This repairs interrupted prior runs and makes repeated apply
        # converge dossier, voting extract, endgame projection, and flow state.
        if audit is None:
            raise PatchConflict(f"缺少投票提取旁证，无法重放依赖：{bvid}")
        source_path = root / entry["source_path"]
        if audit.get("source_sha256") and audit["source_sha256"] != digest(source_path):
            raise PatchConflict(f"投票来源已变，不能沿用旧提取：{bvid}")
        segments = batch.load_segments(source_path)
        audit["night_death_supplements"] = collect_death_announcements(segments, dossier, voting, audit)
        if endgame is not None:
            audit["endgame_phases"] = endgame.get("phases", [])
        reconcile(voting, audit, dossier)
        apply_rules(voting, audit, dossier)
        audit["day_outcomes"] = day_outcomes(voting, audit, dossier)
        audit["facts"] = voting
        audit["dossier_sha256"] = digest(dossier_path)
        audit["dot_audit_applied"] = sorted(set(audit.get("dot_audit_applied", [])) |
                                               set(dchanged) | set(vchanged) | set(echanged))
        validate_voting(voting)
        atomic_json(audit_path, audit)
        touched.append(audit_path.relative_to(root).as_posix())
        atomic_json(voting_path, voting)
        touched.append(voting_path.relative_to(root).as_posix())
        replayed_games.append(bvid)
    return {"database_written": False, "source_check": source_check,
            "changed_findings": sorted(changed_findings), "replayed_games": sorted(set(replayed_games)),
            "modified_files": sorted(set(touched))}


def check_current_files(*, root: Path = ROOT) -> dict[str, Any]:
    patchset = load_patchset()
    source_check = validate_sources(patchset, root)
    import sys
    sys.path.insert(0, str(root / "scripts"))
    import batch_s22 as batch
    mismatches = []
    dependency_checks = {"games_checked": 0, "dossier_hash_mismatches": 0,
                         "facts_mismatches": 0, "flow_mismatches": 0,
                         "outcome_mismatches": 0, "endgame_mismatches": 0}
    from voting_crosscheck import day_outcomes
    from game_flow import replay
    for bvid, entry in batch.load_state()["items"].items():
        if not any(x.get("disposition") == "applied" and x["bvid"] == bvid for x in patchset["findings"]):
            continue
        folder = root / entry["output_dir"]
        dossier = batch.read_json(folder / "dossier.json")
        voting = batch.read_json(folder / "voting.json")
        audit_path = root / "data/extractions/S22/voting" / f"{bvid}.json"
        audit = batch.read_json(audit_path) if audit_path.is_file() else None
        if audit is not None:
            dependency_checks["games_checked"] += 1
            if audit.get("dossier_sha256") != digest(folder / "dossier.json"):
                dependency_checks["dossier_hash_mismatches"] += 1
                mismatches.append(f"{bvid} 投票旁证dossier_sha256过期")
            if audit.get("facts") != voting:
                dependency_checks["facts_mismatches"] += 1
                mismatches.append(f"{bvid} 投票旁证facts与voting.json不同")
            expected_flow = replay(dossier, voting, audit.get("night_death_supplements", []),
                                   audit.get("endgame_phases", []), audit.get("causal_terminal"))
            if audit.get("game_flow") != expected_flow:
                dependency_checks["flow_mismatches"] += 1
                mismatches.append(f"{bvid} game_flow未按当前事实重放")
            if audit.get("day_outcomes") != day_outcomes(voting, audit, dossier):
                dependency_checks["outcome_mismatches"] += 1
                mismatches.append(f"{bvid} day_outcomes与当前事实不一致")
            endgame_path = folder / "endgame.json"
            if endgame_path.is_file():
                endgame = batch.read_json(endgame_path)
                if audit.get("endgame_phases") != endgame.get("phases", []):
                    dependency_checks["endgame_mismatches"] += 1
                    mismatches.append(f"{bvid} endgame投影未同步")
        check = copy.deepcopy(dossier)
        expected = apply_dossier(check, bvid, patchset=patchset, root=root)
        if expected:
            mismatches.extend(f"{bvid} dossier还需应用:{x}" for x in expected)
        check_votes = copy.deepcopy(voting)
        expected_votes = apply_voting(check_votes, bvid, patchset=patchset, after_rules=True)
        if expected_votes:
            mismatches.extend(f"{bvid} voting还需应用:{x}" for x in expected_votes)
        endgame_path = folder / "endgame.json"
        if endgame_path.is_file():
            check_end = copy.deepcopy(batch.read_json(endgame_path))
            expected_end = apply_endgame(check_end, bvid, patchset=patchset)
            if expected_end:
                mismatches.extend(f"{bvid} endgame还需应用:{x}" for x in expected_end)
    return {"database_written": False, "source_check": source_check,
            "dependency_checks": dependency_checks,
            "patches_pending": len(mismatches), "mismatches": mismatches}


def build_report(*, root: Path = ROOT, verification: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    """Render complete candidate-by-candidate disposition from reviewed patchset."""
    patchset = load_patchset()
    source_check = validate_sources(patchset, root)
    findings = []
    for item in patchset["findings"]:
        sources = [{"path": s["path"], "sha256": s["sha256"], "start_ms": s.get("start_ms"),
                    "end_ms": s.get("end_ms"), "context": s.get("context", ""),
                    "classification": s.get("classification")} for s in item.get("sources", [])]
        supplemental_sources = item.get("supplemental_sources", [])
        ops = item.get("patch", {})
        entry = None
        try:
            import sys
            sys.path.insert(0, str(root / "scripts"))
            import batch_s22 as batch
            entry = batch.load_state()["items"].get(item["bvid"])
        except Exception:
            entry = None
        changed_files = []
        if item.get("disposition") == "applied" and entry:
            base = entry["output_dir"].replace("\\", "/")
            if ops.get("dossier"):
                changed_files.append(base + "/dossier.json")
            if ops.get("endgame"):
                changed_files.append(base + "/endgame.json")
            if ops.get("dossier") or ops.get("voting") or ops.get("endgame"):
                changed_files.extend([base + "/voting.json", f"data/extractions/S22/voting/{item['bvid']}.json"])
        level = item.get("evidence_class", "本地转写或复盘连续文字核读")
        pending_reason = None
        if item.get("disposition") == "held":
            pending_reason = "原字幕在6507.069–6509.930秒写作“当夜预言家验证武汉家为狼人身份”，目标座位号无法从字幕唯一确认。另一套本地FunASR Nano 2512对原音6497–6522秒转写为“验证五号玩家”，支持5号，但仍属机器转写且未真人核听；故不把它升级为直接确证，保留目标与反馈未知。"
        findings.append({
            "finding_id": item["finding_id"], "bvid": item["bvid"], "date": item.get("date"),
            "category": item.get("category"), "field": item.get("display_field", item.get("field")),
            "disposition": item["disposition"], "old_value": item.get("old_value"),
            "new_value": item.get("old_value") if item["disposition"] == "held" else item.get("candidate_value"),
            "candidate_value": item.get("candidate_value"),
            "candidate_applied": item["disposition"] == "applied", "sources": sources,
            "supplemental_sources": supplemental_sources,
            "evidence_class": level, "reason": item.get("reason"),
            "prior_decision_check": item.get("prior_decision_check"),
            "related_field_corrections": item.get("related_field_corrections", []),
            "unresolved_reason": pending_reason, "modified_files": changed_files,
            "patch": ops,
        })
    accepted = sum(x["disposition"] == "applied" for x in findings)
    held = sum(x["disposition"] == "held" for x in findings)
    report = {
        "schema_version": 1, "season": "S22", "reviewed_at": patchset.get("reviewed_at"),
        "database_written": False, "candidate_count": len(findings), "applied_count": accepted,
        "held_count": held, "source_check": source_check,
        "verification": verification or {"status": "not_run"},
        "boundary": {
            "review_method": "本次为AI语义审阅，不是人工审核；未进行真人原音回听。",
            "source_text": f"逐条读取候选引用的本地字幕/ASR/复盘连续上下文，校验{source_check['unique_source_files']}个唯一源文件SHA；字幕、SRT及同源转写不当作独立证据。",
            "original_media": "主审未直接回听或目视原音视频；主代理补充了FunASR Nano 2512原音重转写（machine_generated_unverified），该机器稿支持5号但未代替人工听核。唯一因此保留的目标号歧义见S22-A-027-02。",
            "inference": "因果/上下文推断、当季规则推导和本地连续文字核读分列；历史决策说明作为依赖记录保留，但不自动升级为用户确认。",
            "user_confirmation_claims": [],
            "user_confirmation_boundary": "本报告未依据prior_decision_check中的否定句或历史描述标注用户确认；本轮没有新建用户确认结论。既有决策文字仍随候选逐条保留以说明依赖。",
            "candidate_runtime_dependency": False,
            "database_written": False,
        },
        "common_modified_files": ["scripts/s22_dot_audit.py", "scripts/batch_s22.py", "scripts/voting_records.py",
                                  "scripts/endgame_records.py", "data/extractions/S22/S22_dot_audit_patches_20261028.json",
                                  "tests/test_s22_dot_audit.py", "tests/test_endgame_records.py",
                                  "data/reports/S22_dot审计落地_20261028.json", "data/reports/S22_dot审计落地_20261028.md"],
        "findings": findings,
    }
    md = ["# S22 dot 审计落地（2026-10-28）", "", "本次为AI语义审阅，不是人工审核；未进行真人原音回听。", "",
          f"处置：采纳 {accepted} 条，保留未决 {held} 条，共 {len(findings)} 条候选。",
          "", "## 复核边界", "", "- 逐条读候选引用的本地转写/复盘连续上下文，并核验全部唯一来源 SHA256。",
          "- 未进行真人原音回听；主代理另有本地FunASR Nano 2512转写支持5号，仍因机器稿未人工核音而保留S22-A-027-02为未知。",
          "- 每项证据类别显式保存在JSON中；prior_decision_check仅作为历史核对记录，不据此自动宣称用户确认。",
          "- 同源字幕副本不视为独立证据。",
          "- `data/extractions/S22/S22_dot_audit_patches_20261028.json` 是运行时唯一补丁来源，不依赖 dot-handoff 候选包。",
          "- 本轮未写数据库。", "", "## 逐条处置", "", "|候选ID|处置|字段|旧值 → 实际新值|候选值（held项未应用）|来源定位（SHA前12位）|证据类别/未决原因|改动文件|", "|---|---|---|---|---|---|---|---|"]
    for f in findings:
        loc = "; ".join(f"{s['path']}@{s.get('start_ms')}–{s.get('end_ms')}ms ({s['sha256'][:12]})"
                         for s in [*f["sources"], *f.get("supplemental_sources", [])])
        old = json.dumps(f["old_value"], ensure_ascii=False, separators=(",", ":"))
        new = json.dumps(f["new_value"], ensure_ascii=False, separators=(",", ":"))
        candidate = json.dumps(f["candidate_value"], ensure_ascii=False, separators=(",", ":"))
        reason = f["unresolved_reason"] or f["evidence_class"]
        files = ", ".join(f["modified_files"])
        disposition = f"{f['disposition']}（候选未应用）" if f["disposition"] == "held" else f["disposition"]
        md.append(f"|{f['finding_id']}|{disposition}|{f['field']}|`{old}` → `{new}`|`{candidate}`|{loc}|{reason}|{files}|")
    md.extend(["", "## 再生与检查", "", "```powershell",
               ".\\.venv\\Scripts\\python.exe scripts\\s22_dot_audit.py apply",
               ".\\.venv\\Scripts\\python.exe scripts\\s22_dot_audit.py check",
               ".\\.venv\\Scripts\\python.exe -m unittest tests.test_s22_dot_audit tests.test_endgame_records", "```", "",
               "- 结果：" + str((verification or {}).get("status", "not_run")),
               "- 来源校验：" + str(source_check["source_files_hash_matched"]) + "/" + str(source_check["unique_source_files"]) + " 个文件SHA匹配（" + str(source_check.get("source_references", "?")) + "条来源引用）。",
               "- 当前文件检查：" + str((verification or {}).get("check", {}).get("patches_pending", "未运行")) + " 条待应用补丁；依赖差异 " + str((verification or {}).get("check", {}).get("dependency_mismatch_total", "未运行")) + " 项。",
               "- 聚焦测试：" + str((verification or {}).get("tests", {}).get("result", "未运行")),
               "- 幂等检查：" + str((verification or {}).get("idempotence", {}).get("result", "未运行")),
               "- 数据库写入：未执行。"])
    fresh = (verification or {}).get("fresh_generation_probe", {})
    md.extend(["", "## 内存生成探针", "", str(fresh.get("status", "未运行"))])
    if fresh.get("known_failure"):
        failed = fresh["known_failure"]
        md.append(f"- 既有例外：{failed['bvid']}：{failed['reason']}")
    md.extend(["", "## 完整文件再生顺序", ""])
    commands = (verification or {}).get("commands", {})
    regeneration = commands.get("file_regeneration_order", [])
    if regeneration:
        md.append("```powershell")
        md.extend(regeneration)
        md.append("```")
    md.extend(["", "数据库导入：" + str((verification or {}).get("database_import", {}).get("result", "由主代理执行统一事务；本任务没有执行数据库写入。"))])
    return report, "\n".join(md) + "\n"


def write_report(*, root: Path = ROOT, verification: dict[str, Any] | None = None) -> dict[str, Any]:
    report, markdown = build_report(root=root, verification=verification)
    atomic_json(root / "data/reports/S22_dot审计落地_20261028.json", report)
    (root / "data/reports/S22_dot审计落地_20261028.md").write_text(markdown, encoding="utf-8")
    return {"json": str(root / "data/reports/S22_dot审计落地_20261028.json"),
            "markdown": str(root / "data/reports/S22_dot审计落地_20261028.md"),
            "candidates": report["candidate_count"], "applied": report["applied_count"], "held": report["held_count"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "apply", "report"])
    args = parser.parse_args(argv)
    result = check_current_files() if args.action == "check" else apply_current_files() if args.action == "apply" else write_report()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    main()
