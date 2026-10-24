"""Validate and register one evidence-backed game dossier as an unpublished draft.

Curated candidates remain in extraction_runs.payload and participants.proposed.
This command cannot approve a review or publish a game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from psycopg.types.json import Jsonb

from database import ROOT, ReviewError, artifact, connect


def project_data_file(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to((ROOT / "data").resolve()) or not path.is_file():
        raise ReviewError(f"证据必须是data目录中的现存文件：{relative}")
    return path


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate(path):
    path = project_data_file(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("layer") != "game_dossier_candidate" or value.get("status") != "needs_user_review":
        raise ReviewError("仅接收待用户审核的本局信息候选")
    if value.get("review", {}).get("review_complete") is not False:
        raise ReviewError("此入口不接收或伪造用户审核完成状态")
    sources = value["sources"]
    loaded = {}
    for ref, source in sources.items():
        source_path = project_data_file(source["path"])
        if sha256(source_path) != source["sha256"]:
            raise ReviewError(f"来源哈希已变化：{ref}")
        loaded[ref] = json.loads(source_path.read_text(encoding="utf-8-sig"))
    manifest, transcript = loaded["manifest"], loaded["transcript"]
    for key in ["bvid", "cid", "page"]:
        if value[key] != manifest[key] or value[key] != transcript["source"][key]:
            raise ReviewError(f"媒体/转写与候选的{key}不一致")
    if value["audio_sha256"] != manifest["audio"]["sha256"] or value["audio_sha256"] != transcript["source"]["audio_sha256"]:
        raise ReviewError("候选与媒体音轨哈希不一致")
    audio = project_data_file(str(Path(sources["manifest"]["path"]).parent / manifest["audio"]["file"]))
    if sha256(audio) != value["audio_sha256"]:
        raise ReviewError("本地音轨内容已变化")
    meta = value["metadata_candidates"]
    expected = meta["expected_seats"]
    participants = value["participant_candidates"]
    if sorted(p["seat_number"] for p in participants) != list(range(1, expected+1)):
        raise ReviewError("座位必须完整且不重复")
    roster = value["roster"]
    names = {r["name"] for r in roster}
    if len(roster) != expected or len(names) != expected or roster != loaded["roster_snapshot"]["roster"]:
        raise ReviewError("排班12人去重或快照对应失败")
    assigned = [p["name_candidate"] for p in participants if p["name_candidate"] is not None]
    if len(assigned) != len(set(assigned)) or not set(assigned) <= names:
        raise ReviewError("座位姓名候选重复或不在排班中")
    if any(p["official_points"] is not None for p in participants):
        raise ReviewError("当前候选入口不能填充未经审核的官方积分")
    evidence = value["evidence"]
    for key, item in evidence.items():
        if key != item["id"]:
            raise ReviewError("证据ID不一致")
        source = loaded[item["source_ref"]]
        if "segment_ids" in item:
            indexes = {s["id"]: (i, s) for i, s in enumerate(source["segments"])}
            selected = [indexes[sid] for sid in item["segment_ids"]]
            ids = [i for i, _ in selected]
            if ids != list(range(ids[0], ids[-1]+1)):
                raise ReviewError("转写证据不是连续片段")
            rows = [s for _, s in selected]
            quote = "".join(s["text"] for s in rows)
            start, end = rows[0]["start_ms"]/1000, rows[-1]["end_ms"]/1000
        elif "body_indexes" in item:
            indexes = item["body_indexes"]
            if indexes != list(range(indexes[0], indexes[-1]+1)):
                raise ReviewError("平台字幕证据不是连续片段")
            rows = [source["body"][i] for i in indexes]
            quote = " / ".join(s["content"] for s in rows)
            start, end = rows[0]["from"], rows[-1]["to"]
        else:
            raise ReviewError("缺少原始片段定位")
        if quote != item["quote"] or start != item["start_seconds"] or end != item["end_seconds"]:
            raise ReviewError(f"证据原文或时间与原文件不符：{key}")
        if not 0 <= start <= end <= transcript["audio_duration_ms"]/1000:
            raise ReviewError("证据超出音轨范围")

    def check_references(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key.endswith("evidence_ids") and (not isinstance(child, list) or any(x not in evidence for x in child)):
                    raise ReviewError(f"引用不存在的证据：{key}")
                check_references(child)
        elif isinstance(node, list):
            for child in node:
                check_references(child)
    check_references(value)
    for event in value["game_events"]:
        if event["actor_seat"] is not None and event["actor_seat"] not in range(1, expected+1):
            raise ReviewError("行动座位越界")
        if any(t not in range(1, expected+1) for t in event["target_seats"]) or not event["evidence_ids"]:
            raise ReviewError("行动缺证据或目标越界")
    slug = f"bili-{value['bvid']}-p{value['page']:02d}-g{meta['game_number']:02d}"
    if value["game_slug"] != slug:
        raise ReviewError("比赛标识与媒体、局次不一致")
    return value, loaded


def import_dossier(path):
    value, loaded = validate(path)
    path = project_data_file(path)
    meta, manifest = value["metadata_candidates"], loaded["manifest"]
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("dossier-"+value["game_slug"],))
        source_ids, artifact_ids = {}, {}
        for ref, source in value["sources"].items():
            row = conn.execute("SELECT id FROM sources WHERE platform=%s AND external_key=%s", (source["platform"], source["external_key"])).fetchone()
            if row is None:
                if source["platform"] != "weibo":
                    raise ReviewError("先登记原始媒体，不能由对局候选替代原始采集")
                row = conn.execute("""INSERT INTO sources(platform,external_key,url,title,author_id,metadata)
                    VALUES('weibo',%s,%s,%s,'7525583841',%s) ON CONFLICT(platform,external_key)
                    DO UPDATE SET external_key=EXCLUDED.external_key RETURNING id""",
                    (source["external_key"], source["url"], "2026-06-25 S22第四期排班公告", Jsonb({"event_date_candidate": meta["event_date"], "registered_from": "game_dossier"}))).fetchone()
            source_ids[ref] = row["id"]
            artifact_ids[ref] = artifact(conn, row["id"], project_data_file(source["path"]), source["kind"], {"dossier_source_ref": ref})
        source_id = source_ids["manifest"]
        candidate_artifact_id = artifact(conn, source_id, path, "candidate")
        existing = conn.execute("""SELECT g.slug,r.id,r.review_state,g.published_revision_id FROM extraction_runs e
            JOIN game_revisions r ON r.from_extraction_id=e.id JOIN games g ON g.id=r.game_id
            WHERE e.artifact_id=%s ORDER BY r.revision_no LIMIT 1""", (candidate_artifact_id,)).fetchone()
        if existing:
            return {"game_slug": existing["slug"], "revision_id": str(existing["id"]), "review_state": existing["review_state"],
                    "reused_existing": True, "published": existing["published_revision_id"] is not None}
        transcript = loaded["transcript"]
        run = conn.execute("""INSERT INTO transcription_runs(source_id,artifact_id,engine,model,language,parameters)
            VALUES(%s,%s,%s,%s,'zh',%s) ON CONFLICT(artifact_id) DO NOTHING RETURNING id""",
            (source_id, artifact_ids["transcript"], transcript["engine"], transcript["config"]["models"]["asr"],
             Jsonb({"config": transcript["config"], "source_sha256": value["sources"]["transcript"]["sha256"], "audio_sha256": value["audio_sha256"], "time_unit_in_source": "milliseconds"}))).fetchone()
        if run:
            for index, segment in enumerate(transcript["segments"]):
                conn.execute("""INSERT INTO transcript_segments(run_id,segment_index,start_seconds,end_seconds,text,metadata)
                    VALUES(%s,%s,%s,%s,%s,%s)""", (run["id"], index, segment["start_ms"]/1000, segment["end_ms"]/1000,
                    segment["text"], Jsonb({"source_segment_id": segment["id"], "speaker_anonymous": segment.get("speaker"), "speaker_identity_verified": False})))
        else:
            run = conn.execute("SELECT id FROM transcription_runs WHERE artifact_id=%s", (artifact_ids["transcript"],)).fetchone()
        extraction = conn.execute("""INSERT INTO extraction_runs(source_id,transcription_run_id,artifact_id,method,payload)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT(artifact_id) DO NOTHING RETURNING id""",
            (source_id, run["id"], candidate_artifact_id, value["extraction_method"], Jsonb(value))).fetchone()
        if extraction is None:
            extraction = conn.execute("SELECT id FROM extraction_runs WHERE artifact_id=%s", (candidate_artifact_id,)).fetchone()
        season = conn.execute("SELECT id FROM seasons WHERE code=%s", (meta["season"],)).fetchone()
        if season is None:
            season = conn.execute("INSERT INTO seasons(code,name) VALUES(%s,%s) RETURNING id", (meta["season"], meta["season"])).fetchone()
        game = conn.execute("""INSERT INTO games(slug,season_id,primary_source_id) VALUES(%s,%s,%s)
            ON CONFLICT(slug) DO NOTHING RETURNING id""", (value["game_slug"], season["id"], source_id)).fetchone()
        if game is None:
            game = conn.execute("SELECT id,primary_source_id,season_id FROM games WHERE slug=%s", (value["game_slug"],)).fetchone()
            if game["primary_source_id"] != source_id or game["season_id"] != season["id"]:
                raise ReviewError("同名比赛已关联其他来源或赛季")
        number = conn.execute("SELECT COALESCE(max(revision_no),0)+1 AS n FROM game_revisions WHERE game_id=%s", (game["id"],)).fetchone()["n"]
        revision = conn.execute("""INSERT INTO game_revisions(game_id,revision_no,from_extraction_id,event_date,phase,
            game_number,board_name,expected_seats,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (game["id"], number, extraction["id"], meta["event_date"], meta["phase"], meta["game_number"], meta["board_name"], meta["expected_seats"],
             Jsonb({"dossier_schema_version": value["schema_version"], "candidate_metadata_unreviewed": True,
                    "dossier_artifact_id": str(candidate_artifact_id), "result_candidate": value["result_candidate"],
                    "candidate_event_count": len(value["game_events"]), "candidate_turn_count": len(value["speech_turns"]),
                    "review_report": path.parent.relative_to(ROOT).as_posix()+"/单局示例_审核.html"}))).fetchone()
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('dossier-canonical-player-names'))")
        players = {}
        for item in value["roster"]:
            matches = conn.execute("SELECT id FROM players WHERE display_name=%s", (item["name"],)).fetchall()
            if len(matches) > 1:
                raise ReviewError("人名存在多个玩家ID，需要先消歧")
            player = matches[0] if matches else conn.execute("INSERT INTO players(display_name) VALUES(%s) RETURNING id", (item["name"],)).fetchone()
            players[item["name"]] = str(player["id"])
            conn.execute("INSERT INTO player_aliases(player_id,alias) VALUES(%s,%s) ON CONFLICT DO NOTHING", (player["id"], item["name"]))
        for participant in value["participant_candidates"]:
            proposed = dict(participant)
            proposed["roster_player_id_candidate"] = players.get(participant["name_candidate"])
            conn.execute("INSERT INTO game_participants(revision_id,seat_number,proposed) VALUES(%s,%s,%s)",
                         (revision["id"], participant["seat_number"], Jsonb(proposed)))
        for key, item in value["evidence"].items():
            ref = item["source_ref"]
            conn.execute("""INSERT INTO evidence_links(revision_id,source_id,artifact_id,field_key,locator,start_seconds,end_seconds,metadata)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", (revision["id"], source_ids[ref], artifact_ids[ref], "dossier_evidence:"+key,
                item["locator"], item["start_seconds"], item["end_seconds"], Jsonb(item)))
        conn.execute("""INSERT INTO evidence_links(revision_id,source_id,artifact_id,field_key,locator,metadata)
            VALUES(%s,%s,%s,'schedule_roster','roster_source.snapshot.json: schedule + roster',%s)""",
            (revision["id"], source_ids["roster_snapshot"], artifact_ids["roster_snapshot"], Jsonb({"canonical_player_ids": players, "schedule_image_order_is_not_seat_order": True})))
        conn.execute("INSERT INTO audit_events(action,actor,entity_id,details) VALUES('import_game_dossier_draft','assistant',%s,%s)",
                     (revision["id"], Jsonb({"candidate_artifact_id": str(candidate_artifact_id), "extraction_id": str(extraction["id"]), "user_review_complete": False})))
        return {"game_slug": value["game_slug"], "revision_id": str(revision["id"]), "extraction_id": str(extraction["id"]),
                "review_state": "draft", "reused_existing": False, "roster_names": len(players), "candidate_seats": len(value["participant_candidates"]),
                "candidate_events": len(value["game_events"]), "candidate_turns": len(value["speech_turns"]), "evidence_links": len(value["evidence"])+1,
                "formal_participant_facts_approved": False, "published": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dossier", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.check_only:
        value, _ = validate(args.dossier)
        result = {"valid": True, "game_slug": value["game_slug"], "evidence_count": len(value["evidence"])}
    else:
        result = import_dossier(args.dossier)
    if args.receipt:
        args.receipt.resolve().relative_to(ROOT.resolve())
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    from game_records import main as import_current
    import_current()
