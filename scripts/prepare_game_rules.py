"""Compute shared rule sidecars for existing formal records; no DB or publish."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from game_derivations import ROOT, derive_game, fingerprint, restore_source_records
from sheriff_speech_evidence import load_bound_sheriff_speeches


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else None


def _has_saved_derived_values(records, report):
    for patch in report.get("changes", []):
        node = records
        try:
            for key in patch["path"]:
                node = node[key]
        except (KeyError, IndexError, TypeError):
            continue
        if node == patch["after"] and patch["before"] != patch["after"]:
            return True
    return False


def prepare(seasons, *, bvids=(), apply=False, materialize=False):
    games, totals = [], Counter()
    for season in seasons:
        for folder in sorted((ROOT / "data/games" / season).iterdir()):
            if bvids and not any(b in folder.name for b in bvids):
                continue
            dossier, voting = read(folder / "dossier.json"), read(folder / "voting.json")
            if dossier is None or voting is None:
                continue
            audit_path = ROOT / "data/extractions/S22/voting" / f"{folder.name.rsplit('_', 1)[-1]}.json"
            audit = read(audit_path) if season == "S22" else None
            if apply and audit is not None:
                source_hash = hashlib.sha256((ROOT / audit["source_path"]).read_bytes()).hexdigest()
                if source_hash != audit["source_sha256"]:
                    raise ValueError(f"投票来源已变化，不能沿用旧提取：{audit_path.name}")
            stored = {"dossier": dossier, "voting": voting}
            prior = read(folder / "rule_derivations.json")
            was_materialized = False
            current_hashes = {key: fingerprint(value) for key, value in stored.items()}
            source_hashes = {key: (prior or {}).get("input_hashes", {}).get(key) for key in stored}
            if prior and prior.get("game_slug") == dossier.get("slug") and current_hashes != source_hashes:
                was_materialized = (current_hashes == prior.get("output_hashes")
                                    or _has_saved_derived_values(stored, prior))
                original = restore_source_records(dossier, voting, prior)
                dossier, voting = original["dossier"], original["voting"]
            supplemental = read(folder / "supplemental.json")
            # S23 already persists observed terminal boundaries here.
            context = read(folder / "formal_context.json")
            result = derive_game(dossier, voting, supplemental=supplemental, endgame=read(folder / "endgame.json"),
                                 terminal_observation=(context or {}).get("terminal_observation"),
                                 speech_evidence=load_bound_sheriff_speeches(supplemental, root=ROOT, voting=voting))
            report = result["derivations"]
            totals.update(games=1, slots=len(report["slot_states"]), review_tasks=len(report["review_tasks"]),
                          unavailable=sum(s["status"] == "unavailable" for s in report["slot_states"]),
                          changes=len(report["changes"]), issues=len(report["issues"]), gaps=len(report.get("gaps", [])),
                          vote_review_tasks=len(report.get("vote_review_tasks", [])))
            games.append({"slug": dossier["slug"], "season": season, "changes": len(report["changes"]),
                          "review_tasks": len(report["review_tasks"]), "issues": report["issues"]})
            if apply:
                (folder / "rule_derivations.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                # Once typed records contain our derived fields, refresh those
                # fields along with the sidecar; otherwise neither the saved
                # input nor output fingerprint would match the old typed file.
                if materialize or was_materialized:
                    for key in ("dossier", "voting"):
                        if materialize or stored[key] != result[key]:
                            (folder / f"{key}.json").write_text(json.dumps(result[key], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                            totals["typed_files_written"] += 1
                if audit is not None:
                    from game_flow import replay
                    from voting_crosscheck import day_outcomes

                    current = result if materialize or was_materialized else stored
                    updated = dict(audit, facts=current["voting"],
                                   dossier_sha256=hashlib.sha256((folder / "dossier.json").read_bytes()).hexdigest(),
                                   game_flow=replay(current["dossier"], current["voting"],
                                                    audit.get("night_death_supplements", []),
                                                    audit.get("endgame_phases", []), audit.get("causal_terminal")))
                    updated["day_outcomes"] = day_outcomes(current["voting"], updated, current["dossier"])
                    if updated != audit:
                        audit_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                        totals["voting_audits_written"] += 1
    return {"schema_version": 1, "applied": apply, "materialized": materialize and apply,
            "typed_files_written": totals["typed_files_written"],
            "database_write": False, "publication": False, "totals": dict(totals), "games": games}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", nargs="+", default=["S21", "S22", "S23"])
    parser.add_argument("--bvid", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--materialize", action="store_true", help="Also replace typed formal JSON; source evidence is unchanged")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = prepare(args.season, bvids=args.bvid, apply=args.apply, materialize=args.materialize)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "games"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
