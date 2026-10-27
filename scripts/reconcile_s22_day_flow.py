"""Apply the sourced S22 treasure alignment and confirmed no-exile day correction."""
import sys

import batch_s22 as batch
from batch_review import render_game
from game_records import validate_batch
from s22_inference_review import changed_value

CONFIRMATION = "data/extractions/S22/用户确认_20261025.txt"
ALIGNMENT = batch.ROOT / "data/reports/S22_正式规则对齐记录.json"
REPORT = batch.ROOT / "data/reports/S22_日序与阵营更正.json"


def build():
    state = batch.load_state()
    alignment = batch.read_json(ALIGNMENT)
    results = []
    for bvid, entry in state["items"].items():
        folder = batch.ROOT / entry["output_dir"]
        path = folder / "dossier.json"
        value = batch.read_json(path)
        changes, quotes = [], []
        if value["board"] == "treasure_master":
            for s in value["seats"]:
                if s["role"] == "盗宝大师" and s["faction"] != "werewolf":
                    changes.append({"kind": "seat", "seat": s["seat"], "fields": {"faction": "werewolf"}})
                    quotes.append("京城大师赛的盗宝大师一定是狼人阵营的，其他小狼都出局后带刀。")
        if bvid == "BV1pGVC6cEbW":
            r = next(r for r in value["rounds"] if r["number"] == 4)
            e = next(e for e in r["day"] if e["slot"] == "exile_result")
            fields = {"action": "none", "targets": [], "result": "两轮投票均平票，平安日，无人被放逐；随后狼人拍刀。"}
            if any(e[k] != v for k, v in fields.items()):
                changes.append({"kind": "event", "number": 4, "phase": "day", "slot": "exile_result", "fields": fields})
                quotes.append("白天如果两轮投票都平票就是平安日，无人被放逐。6月2日第三局第四天白天两轮平票平安日，无人被放逐，随后狼人拍刀。")
        if not changes:
            continue
        before = batch.digest(path)
        row = next((x for x in alignment["items"] if x["bvid"] == bvid), None)
        if row and row["after_sha256"] != before:
            raise ValueError("正式规则对齐谱系已变化：" + bvid)
        snapshot = batch.ROOT / "data/archive/S22_formal_rule_alignment/20261025" / f"{bvid}_{before}.json"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        if not snapshot.exists():
            snapshot.write_bytes(path.read_bytes())
        updated = changed_value(value, changes, allow_legacy_treasure_faction=True)
        validate_batch(updated)
        batch.atomic_json(path, updated)
        proof = [{"path": CONFIRMATION, "start_ms": None, "end_ms": None, "quote": q,
                  "source_sha256": batch.digest(batch.ROOT / CONFIRMATION), "source_type": "user_confirmation"} for q in quotes]
        if row:
            row["changes"].extend(changes)
            row["evidence"].extend(proof)
            row["reason"] += "；2026-10-25按用户确认补正盗宝阵营或平票平安日。"
        else:
            row = {"bvid": bvid, "file": batch.relative(path), "before_sha256": before,
                   "before_snapshot": batch.relative(snapshot), "state": "applied", "changes": changes,
                   "evidence": proof, "reason": "2026-10-25按用户确认补正盗宝阵营或平票平安日。"}
            alignment["items"].append(row)
        row.update(after_sha256=batch.digest(path), applied_at=batch.now())
        assert changed_value(batch.read_json(batch.ROOT / row["before_snapshot"]), row["changes"],
                             allow_legacy_treasure_faction=True) == updated
        results.append({"bvid": bvid, "before_sha256": before, "after_sha256": row["after_sha256"],
                        "before_snapshot": batch.relative(snapshot), "changes": changes, "evidence": proof})
        alignment["updated_at"] = batch.now()
        batch.atomic_json(ALIGNMENT, alignment)
        batch.atomic_json(REPORT, {"generated_at": batch.now(), "items": results, "games": len(results)})
        review = batch.read_json(folder / "复核记录.json")
        render_game(folder, updated, review)
    alignment["updated_at"] = batch.now()
    batch.atomic_json(ALIGNMENT, alignment)
    if results or not REPORT.exists():
        batch.atomic_json(REPORT, {"generated_at": batch.now(), "items": results, "games": len(results)})
    return results


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print({"updated_games": len(build())})
