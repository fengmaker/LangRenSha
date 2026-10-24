"""Remove user-excluded S22 games from the database and active review artifacts."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

import batch_s22 as batch
from database import connect
from game_scope import exclusion_reason, load_policy

ROOT = batch.ROOT
REPORT = ROOT / "data/reports/S22_非正赛移除记录.json"


def safe_move(source: Path, destination: Path, source_root: Path, archive_root: Path) -> bool:
    source, destination = source.resolve(), destination.resolve()
    # Verify both absolute boundaries before moving even a single directory.
    if source == source_root.resolve() or not source.is_relative_to(source_root.resolve()):
        raise ValueError("移除来源超出指定工作目录：" + str(source))
    if destination == archive_root.resolve() or not destination.is_relative_to(archive_root.resolve()):
        raise ValueError("恢复副本路径超出指定归档目录：" + str(destination))
    if not source.exists():
        return False
    if destination.exists():
        raise ValueError("恢复副本已存在，停止覆盖：" + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)
    return True


def plan() -> dict:
    state = batch.read_json(batch.STATE_FILE)
    policy = load_policy(ROOT)
    entries = batch.entries_from_catalog(include_excluded=True)
    selected = [state["items"].get(e["bvid"], e) for e in entries if exclusion_reason(e, root=ROOT)]
    if {e["bvid"] for e in selected} != set(policy.get("excluded_bvids", [])):
        raise ValueError("目录排除结果与用户确认的BVID清单不一致，停止移除")
    if any(e["bvid"] == "BV1yt7v6QE3Q" or e.get("state") == "preserved" for e in selected):
        raise ValueError("移除范围包含原保护样例，停止移除")
    old = batch.read_json(REPORT) if REPORT.is_file() else {}
    old_targets = {e["bvid"]: e for e in old.get("items", [])}
    targets = []
    for entry in selected:
        path = ROOT / entry["output_dir"] / "dossier.json"
        dossier = batch.read_json(path) if path.is_file() else old_targets.get(entry["bvid"], {})
        if not dossier.get("slug"):
            raise ValueError("无法唯一确认将删除的对局slug：" + entry["bvid"])
        targets.append({**entry, "slug": dossier["slug"], "removal_reason": exclusion_reason(entry, root=ROOT)})
    return {**{key: old[key] for key in ["backup", "deleted_rows", "database_matches", "moved_paths"] if key in old},
            "season": "S22", "state": "planned", "created_at": old.get("created_at") or batch.now(),
            "scope_policy": "config/S22_game_scope.json", "items": targets,
            "removed_games": len(targets), "phase_counts": dict(Counter(e["phase"] for e in targets)),
            "remaining_games": len(entries) - len(targets),
            "archive_root": old.get("archive_root") or "data/archive/S22_excluded_games/" + batch.now().replace(":", "").replace("+", "_"),
            "note": "按用户要求从数据库、当前对局目录、复核列表和续跑范围移除。删除前数据库与文件快照留作恢复副本。"}


def apply() -> dict:
    with batch.batch_lock():
        if REPORT.is_file():
            old = batch.read_json(REPORT)
            if old.get("state") == "complete":
                return old
        report = plan()
        archive = (ROOT / report["archive_root"]).resolve()
        if not archive.is_relative_to((ROOT / "data/archive/S22_excluded_games").resolve()):
            raise ValueError("恢复副本目录不在预期工作区内")
        archive.mkdir(parents=True, exist_ok=True)
        for path in [batch.STATE_FILE, ROOT / "data/reports/S22_转写逐句复核进度.json",
                     ROOT / "data/reports/S22_画面座位补全进度.json", ROOT / "data/reports/S22_画面截帧进度.json",
                     ROOT / "data/reports/S22_对局批处理验收.json", ROOT / "data/reports/S22_画面座位验收.json"]:
            target = archive / "before" / path.name
            if path.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        batch.atomic_json(REPORT, report)
        checkpoint = batch.checkpoint
        try:
            batch.checkpoint = lambda state, event=None, render=True: batch.atomic_json(REPORT, state)
            batch.backup_database(report)
        finally:
            batch.checkpoint = checkpoint

        slugs = [e["slug"] for e in report["items"]]
        deleted = {}
        with connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('S22-user-scope-removal'))")
            rows = conn.execute("""SELECT g.id,g.slug,s.code AS season FROM games g
                JOIN seasons s ON s.id=g.season_id WHERE g.slug=ANY(%s) FOR UPDATE OF g""", (slugs,)).fetchall()
            if any(row["season"] != "S22" for row in rows):
                raise ValueError("目标对局赛季不符，回滚")
            ids = [row["id"] for row in rows]
            matches = {row["slug"]: row for row in report.get("database_matches", [])}
            matches.update({row["slug"]: {"game_id": str(row["id"]), "slug": row["slug"]} for row in rows})
            report["database_matches"] = list(matches.values())
            for table in ["game_event_effects", "game_event_votes", "game_event_targets", "game_event_records",
                          "game_rounds", "game_staff", "game_seats", "game_files", "game_details"]:
                # table is from this fixed allowlist, never user-controlled SQL.
                deleted[table] = conn.execute(f"DELETE FROM {table} WHERE game_id=ANY(%s)", (ids,)).rowcount
            conn.execute("UPDATE games SET published_revision_id=NULL WHERE id=ANY(%s)", (ids,))
            revisions = [r["id"] for r in conn.execute("SELECT id FROM game_revisions WHERE game_id=ANY(%s)", (ids,)).fetchall()]
            deleted["publication_events"] = conn.execute("DELETE FROM publication_events WHERE game_id=ANY(%s)", (ids,)).rowcount
            for table in ["evidence_links", "reviews", "game_participants"]:
                deleted[table] = conn.execute(f"DELETE FROM {table} WHERE revision_id=ANY(%s)", (revisions,)).rowcount
            deleted["game_revisions"] = conn.execute("DELETE FROM game_revisions WHERE game_id=ANY(%s)", (ids,)).rowcount
            deleted["games"] = conn.execute("DELETE FROM games WHERE id=ANY(%s)", (ids,)).rowcount
            remaining = conn.execute("SELECT count(*) AS n FROM games g JOIN seasons s ON s.id=g.season_id WHERE s.code='S22'").fetchone()["n"]
            if remaining != report["remaining_games"]:
                raise ValueError("剩余S22对局数与排除计划不一致，回滚")
        prior_deleted = report.get("deleted_rows", {})
        report.update(state="database_removed", deleted_rows={key: prior_deleted.get(key, 0) + count for key, count in deleted.items()}, database_remaining=remaining)
        batch.atomic_json(REPORT, report)

        excluded = {e["bvid"] for e in report["items"]}
        moved = list(report.get("moved_paths", []))
        active = batch.load_state()
        active_dates = {e["date"] for e in active["items"].values()}
        for entry in report["items"]:
            source = ROOT / entry["output_dir"]
            if safe_move(source, archive / "games" / source.name, ROOT / "data/games/S22", archive):
                moved.append(batch.relative(source))
            source = ROOT / "data/extractions/S22/day_frame_seats" / (entry["bvid"] + ".json")
            if safe_move(source, archive / "day_annotations" / source.name, source.parent, archive):
                moved.append(batch.relative(source))
        for date in {e["date"] for e in report["items"]} - active_dates:
            source = ROOT / "data/extractions/S22/按日座位表" / (date + ".json")
            if safe_move(source, archive / "day_tables" / source.name, source.parent, archive):
                moved.append(batch.relative(source))

        from s22_text_review import PROGRESS, progress_summary
        import s22_frame_seats as frames
        text = batch.read_json(PROGRESS)
        text["items"] = {k: v for k, v in text["items"].items() if k not in excluded}
        text.update(summary=progress_summary(active, text), updated_at=batch.now(), scope_policy=report["scope_policy"])
        batch.atomic_json(PROGRESS, text)
        frame = frames._load_progress()
        frame["items"] = {k: v for k, v in frame["items"].items() if k not in excluded}
        frame["completion"] = {"catalog_games": len(active["items"]), "frame_stage_games": len(frame["items"]),
            "preserved_games": 1, "dates": len(active_dates), "complete_lineup_dates": len(active_dates),
            "complete_lineup_games": sum(e.get("named_seats") == 12 for e in active["items"].values()),
            "named_seats": sum(e.get("named_seats", 0) for e in active["items"].values()),
            "pending_dates": [], "processing_pending": 0, "processing_failed": 0, "frame_question_count": 0,
            "text_question_count": text["summary"]["questions"], "checked_at": batch.now()}
        frame.update(scope_policy=report["scope_policy"], review_url="http://127.0.0.1:8766/",
                     resume_steps=["当前有效范围149局，表演赛及7月3日娱乐局已移除；画面姓名处理与待核项均为0。",
                                   "后续更正通过审校工作台保存；续跑只处理当前范围，不恢复排除项。"])
        frames._save_progress(frame)
        active["scope"] = {"policy": report["scope_policy"], "excluded_games": len(excluded),
                           "active_games": len(active["items"]), "removal_report": batch.relative(REPORT)}
        batch.checkpoint(active, {"stage": "excluded_non_competition_games_removed", "games": len(excluded)})
        from batch_review import export_questions
        export_questions(batch.SEASON_DIR, list(active["items"].values()))
        import consolidate_s22_day_seats as consolidate
        consolidate.write_plan(consolidate.build_plan(active))
        report.update(state="complete", moved_paths=moved, completed_at=batch.now(),
                      active_dates=len(active_dates), next_frame_bvid=frame.get("next_frame_bvid"),
                      next_frame_review_bvid=frame.get("next_frame_review_bvid"))
        batch.atomic_json(REPORT, report)
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preview", "apply"])
    args = parser.parse_args()
    result = plan() if args.action == "preview" else apply()
    print(json.dumps({k: v for k, v in result.items() if k not in {"items", "moved_paths", "database_matches"}}, ensure_ascii=False, indent=2))
