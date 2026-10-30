"""Store source-reviewed S21 seat/name/physical-role facts.

The reviewed extraction layer and reviewed_identity_seats view support this
partial stage without constructing formal games, board rules or event slots.
Raw visual reviews stay unchanged; primary corrections are separate evidence.
An explicitly labelled fantasy-view sidebar is not physical-role evidence;
primary corrections can use hash-bound, verbatim terminal referee recaps.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from database import ROOT, ReviewError, artifact, connect
from psycopg.types.json import Jsonb

METHOD = "visual_identity_only_v1"
INDEX = Path("data/reports/S21/S21_文字与截图时点索引.json")
SCOPE = Path("config/seasons.json")
CORRECTIONS = Path("data/extractions/S21/identity_primary_corrections.json")
NAMES = Path("data/weibo/2026-05-26_2026-10-20/参赛名单/人名去重_照片映射.csv")
PHOTOS = Path("data/weibo/2026-02-24_2026-05-26/S21_姓名照片来源索引.json")
REPORT = Path("data/reports/S21/S21_座位姓名身份核实进度.json")


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha(path):
    with (ROOT / path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == data:
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(data, encoding="utf-8", newline="\n")
    temporary.replace(path)


def checked_evidence(ev, bvid):
    """Reject missing, changed or cross-media evidence before any writes."""
    if ev.get("kind") == "literal_transcript":
        expected = Path(f"data/extractions/S21/media_evidence/{bvid}/transcript.selected.json")
        if Path(ev["path"]).as_posix() != expected.as_posix() or sha(expected) != ev["sha256"]:
            raise ReviewError(f"{bvid}: 复盘文字证据来源或SHA不匹配")
        transcript = read(expected)
        if transcript.get("bvid") != bvid or sha(transcript["source_path"]) != transcript["source_sha256"]:
            raise ReviewError(f"{bvid}: 复盘原始来源不匹配")
        indices = ev.get("source_segment_indices", [])
        segments = transcript["segments"]
        if (not indices or indices != sorted(set(indices))
                or any(type(i) is not int or i < 0 or i >= len(segments) for i in indices)):
            raise ReviewError(f"{bvid}: 复盘证据索引不合法")
        quote = "\n".join(segments[i]["text"] for i in indices)
        if (ev.get("quote") != quote or ev.get("start_ms") != segments[indices[0]]["start_ms"]
                or ev.get("end_ms") != segments[indices[-1]]["end_ms"]):
            raise ReviewError(f"{bvid}: 复盘证据原文或时点不匹配")
        return dict(ev)
    path = (ROOT / ev["path"]).resolve()
    expected = (ROOT / "data/extractions/S21/frames" / bvid).resolve()
    if not path.is_relative_to(expected) or not path.is_file():
        raise ReviewError(f"{bvid}: 画面证据不属于本条媒体")
    if sha(path) != ev["sha256"]:
        raise ReviewError(f"{bvid}: 画面SHA不一致 {path.name}")
    result = {k: ev[k] for k in (
        "path", "sha256", "requested_time_ms", "actual_frame_time_ms", "time_kind", "kind",
    ) if k in ev}
    # Older corrections refer to a frame by immutable hash. Recover the locator
    # from the capture candidates, without inventing an actual presentation time.
    if "requested_time_ms" not in result:
        for filename in ("daytime_candidates.json", "capture.json"):
            candidate_path = expected / filename
            if not candidate_path.exists():
                continue
            value = read(candidate_path)
            frames = value.get("frames", []) + value.get("frames_checked", [])
            frames += [value.get("best_daytime_frame")]
            match = next((f for f in frames if isinstance(f, dict)
                          and f.get("frame_path") == ev["path"]), None)
            if match:
                result.update({k: match[k] for k in ("requested_time_ms", "actual_frame_time_ms") if k in match})
                break
    if "requested_time_ms" not in result:
        result["requested_time_ms"] = round(float(path.stem.rsplit("_", 1)[1]) * 1000)
        result["time_kind"] = "legacy_filename_seek_target_actual_pts_not_recorded"
    return result


def name_map():
    names = {}
    # User-confirmed spellings and explicit corrections take priority.
    with (ROOT / NAMES).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("原人工确认状态") not in {"确认无误", "已修正"}:
                continue
            label, normalized = row.get("原图名字", "").strip(), row.get("去重后姓名", "").strip()
            if label and normalized:
                names[label.casefold()] = normalized
    for photo in read(PHOTOS)["photos"]:
        for obs in photo.get("nameplate_observations", []):
            label, normalized = obs.get("read_text", "").strip(), (obs.get("normalized_name") or "").strip()
            if label and normalized:
                names.setdefault(label.casefold(), normalized)
    return names


def prepare(entry, names, corrections):
    bvid = entry["bvid"]
    visual_path = Path(f"data/extractions/S21/game_reviews/{bvid}/visual_review.json")
    if not (ROOT / visual_path).exists():
        return None
    visual = read(visual_path)
    if (visual.get("status") != "ai_visual_checked" or visual.get("bvid") != bvid
            or visual.get("cid") != entry["cid"] or visual.get("page") != entry["page"]):
        raise ReviewError(f"{bvid}: 核实状态或BV/CID/P不匹配")
    seats = visual["seats"]
    if sorted(s["seat"] for s in seats) != list(range(1, 13)):
        raise ReviewError(f"{bvid}: 实际查看的12个编号座位不完整或重复")
    inspected = {ev["path"] for ev in visual.get("actually_inspected_frames", [])}
    output = []
    applied = []
    for original in sorted(seats, key=lambda s: s["seat"]):
        refs = [original["evidence"]] if isinstance(original.get("evidence"), dict) else []
        for field in ("name", "role"):
            field_ref = original.get(field + "_evidence")
            if isinstance(field_ref, dict) and field_ref.get("source_frame_path"):
                refs.append({"path": field_ref["source_frame_path"], "sha256": field_ref["source_frame_sha256"],
                             **{k: field_ref[k] for k in ("requested_time_ms", "actual_frame_time_ms", "kind") if k in field_ref}})
        if not refs:
            raise ReviewError(f"{bvid}: 座位{original['seat']}缺少可追溯画面证据")
        evidence = list({ev["path"]: ev for ref in refs if (ev := checked_evidence(ref, bvid))}.values())
        if any(ev["path"] not in inspected for ev in evidence):
            raise ReviewError(f"{bvid}: 座位{original['seat']}证据未列入实际查看清单")
        label = original.get("display_name") or original.get("name") or None
        name = original.get("name") or label
        role = original.get("role") or None
        role_basis = original.get("role_evidence")
        for correction in corrections:
            if correction["bvid"] != bvid or correction["seat"] != original["seat"]:
                continue
            key = correction["field"]
            if original.get(key) != correction["before"]:
                raise ReviewError(f"{bvid}: 主审修订旧值不匹配")
            if key == "name":
                label = name = correction["after"]
            elif key == "role":
                role = correction["after"]
                if correction["evidence"].get("kind") == "literal_transcript":
                    role_basis = "terminal_referee_recap_overrides_fantasy_view"
            else:
                raise ReviewError("主审只允许修订name/role")
            evidence.append(checked_evidence(correction["evidence"], bvid))
            applied.append(correction)
        if name:
            name = names.get(name.casefold(), name)
        if role in {"未知", "unknown", "?"}:
            role = None
        output.append({"seat": original["seat"], "name": name, "display_name": label,
                       "role": role, "evidence": evidence,
                       "name_basis": original.get("name_evidence"),
                       "role_basis": role_basis})
    known_names = [s["name"] for s in output if s["name"]]
    if len(known_names) != len(set(known_names)):
        raise ReviewError(f"{bvid}: 规范姓名在同一录像座位中重复")
    payload = {
        "schema_version": 1, "season": "S21", "bvid": bvid,
        "cid": entry["cid"], "page": entry["page"],
        "field_scope": ["seat", "name", "role"], "seats": output,
        "review": {
            "status": "ai_visual_checked", "reviewer": visual["reviewer"],
            "visual_review_path": visual_path.as_posix(), "visual_review_sha256": sha(visual_path),
            "primary_corrections_path": CORRECTIONS.as_posix(), "primary_corrections_sha256": sha(CORRECTIONS),
            "applied_corrections": applied,
            "name_map_paths": {NAMES.as_posix(): sha(NAMES), PHOTOS.as_posix(): sha(PHOTOS)},
            "confirmation": "assistant_verified_not_user_per_field_confirmation",
        },
        "scope_note": "仅座位、姓名与物理底牌；身份专项核实记录不代表正式对局或完整复核。",
    }
    path = visual_path.with_name("identity.reviewed.json")
    save(path, payload)
    return {"entry": entry, "payload": payload, "path": path, "sha256": sha(path)}


def baseline(conn):
    return conn.execute("SELECT s.code,count(g.id) AS games FROM seasons s LEFT JOIN games g ON g.season_id=s.id "
                        "GROUP BY s.code ORDER BY s.code").fetchall()


def import_batch(items):
    stats = Counter()
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("s21-identity-only-import",))
        before = baseline(conn)
        for item in items:
            entry, value = item["entry"], item["payload"]
            external_key = f"{entry['bvid']}:{entry['cid']}"
            source = conn.execute("SELECT id,metadata FROM sources WHERE platform='bilibili' AND external_key=%s", (external_key,)).fetchone()
            if source and any(source["metadata"].get(k) not in (None, entry[k]) for k in ("bvid", "cid", "page")):
                raise ReviewError("既有来源的BV/CID/P不匹配")
            if not source:
                source = conn.execute("""INSERT INTO sources(platform,external_key,url,title,metadata)
                    VALUES('bilibili',%s,%s,%s,%s) RETURNING id""",
                    (external_key, f"https://www.bilibili.com/video/{entry['bvid']}/?p={entry['page']}", entry["title"],
                     Jsonb({k: entry[k] for k in ("bvid", "cid", "page")}))).fetchone()
            source_id = source["id"]
            for ev in {ev["path"]: ev for s in value["seats"] for ev in s["evidence"]}.values():
                kind = "subtitle" if ev.get("kind") == "literal_transcript" else "frame"
                artifact(conn, source_id, ROOT / ev["path"], kind, {"identity_only_locator": ev})
            artifact_id = artifact(conn, source_id, ROOT / item["path"], "candidate", {"field_scope": value["field_scope"], "method": METHOD})
            existing = conn.execute("SELECT id,method,payload,verification_status FROM extraction_runs WHERE artifact_id=%s", (artifact_id,)).fetchone()
            if existing:
                if existing["method"] != METHOD or existing["payload"] != value or existing["verification_status"] != "reviewed":
                    raise ReviewError("相同文件已有不一致提取记录")
                stats["unchanged"] += 1
                continue
            extraction = conn.execute("""INSERT INTO extraction_runs(source_id,artifact_id,method,payload,verification_status)
                VALUES(%s,%s,%s,%s,'reviewed') RETURNING id""", (source_id, artifact_id, METHOD, Jsonb(value))).fetchone()
            conn.execute("INSERT INTO audit_events(action,actor,entity_id,details) VALUES(%s,%s,%s,%s)",
                         ("import_identity_only_review", "codex_primary", extraction["id"],
                          Jsonb({"bvid": entry["bvid"], "sha256": item["sha256"], "scope": value["field_scope"]})))
            stats["inserted"] += 1
        after = baseline(conn)
        if before != after:
            raise ReviewError("身份专项导入意外改变正式局数，事务已回滚")
        rows = conn.execute("SELECT bvid,seat_number,name,display_name,role FROM reviewed_identity_seats WHERE season='S21' ORDER BY bvid,seat_number").fetchall()
        actual = {(r["bvid"], r["seat_number"]): (r["name"], r["display_name"], r["role"]) for r in rows}
        for item in items:
            for seat in item["payload"]["seats"]:
                if actual.get((item["entry"]["bvid"], seat["seat"])) != (seat["name"], seat["display_name"], seat["role"]):
                    raise ReviewError("入库回读与核实JSON不一致，事务已回滚")
    return {"records": dict(stats), "current_media": len({r["bvid"] for r in rows}), "current_seats": len(rows),
            "formal_game_counts_before": before, "formal_game_counts_after": after, "readback_exact": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-db", action="store_true")
    args = parser.parse_args()
    from rule_config import load_scope
    excluded = set(load_scope("S21", ROOT)["excluded_bvids"])
    entries = read(INDEX)["entries"]
    if len({e["bvid"] for e in entries}) != len(entries) or any(e["bvid"] in excluded for e in entries):
        raise ReviewError("媒体索引有重复或包含已排除来源")
    names, corrections = name_map(), read(CORRECTIONS)["records"]
    items = [item for e in entries if (item := prepare(e, names, corrections))]
    missing = [e["bvid"] for e in entries if e["bvid"] not in {i["entry"]["bvid"] for i in items}]
    unknown = [{"bvid": i["entry"]["bvid"], "seat": s["seat"], "missing": [k for k in ("name", "role") if s[k] is None]}
               for i in items for s in i["payload"]["seats"] if s["name"] is None or s["role"] is None]
    result = {"schema_version": 1, "season": "S21", "updated_at_utc": datetime.now(timezone.utc).isoformat(),
              "field_scope": ["seat", "name", "role"], "media_target": len(entries), "media_checked": len(items),
              "seats_checked": sum(len(i["payload"]["seats"]) for i in items), "pending_media": missing, "unknown_fields": unknown,
              "primary_corrections": len(corrections), "database_writes": args.import_db,
              "items": [{"bvid": i["entry"]["bvid"], "path": i["path"].as_posix(), "sha256": i["sha256"]} for i in items]}
    if args.import_db:
        result["database"] = import_batch(items)
    save(REPORT, result)
    print(json.dumps({k: v for k, v in result.items() if k not in {"items", "pending_media", "unknown_fields"}}, ensure_ascii=False, indent=2, default=str))
    print(f"pending_media={len(missing)}; unknown_fields={len(unknown)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
