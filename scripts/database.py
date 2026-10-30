"""Migrations, provenance ingestion and explicit local review for the pilot game."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from media_ingest import MediaValidationError, validate_media

ROOT = Path(__file__).resolve().parents[1]
PILOT = "bili-BV1tj8p6REqy-p01-g01"


class ReviewError(ValueError):
    pass


def configuration() -> dict:
    path = ROOT / ".secrets" / "database.json"
    if not path.exists() and not os.environ.get("DATABASE_URL"):
        raise ReviewError("请先执行 local_postgres.py setup，或配置 DATABASE_URL")
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    value["schema"] = os.environ.get("DATABASE_SCHEMA", value.get("schema", "jcms"))
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value["schema"]):
        raise ReviewError("数据库 schema 名称不合法")
    return value


def connect(schema: str | None = None):
    config = configuration()
    schema = schema or config.pop("schema")
    config.pop("schema", None)
    if os.environ.get("DATABASE_URL"):
        conn = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    else:
        conn = psycopg.connect(**config, row_factory=dict_row)
    conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
    return conn


def migrate(schema: str | None = None) -> list[str]:
    schema = schema or configuration()["schema"]
    applied = []
    with connect(schema) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("jcms-migrate-" + schema,))
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
        for path in sorted((ROOT / "db" / "migrations").glob("*.sql")):
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            previous = conn.execute("SELECT sha256 FROM schema_migrations WHERE name=%s", (path.name,)).fetchone()
            if previous:
                if previous["sha256"] != digest:
                    raise ReviewError("已经执行的迁移文件发生变化；请新增迁移，不要覆盖旧文件")
                continue
            conn.execute(data.decode("utf-8"), prepare=False)
            conn.execute("INSERT INTO schema_migrations(name,sha256) VALUES(%s,%s)", (path.name, digest))
            applied.append(path.name)
    return applied


def artifact(conn, source_id, path: Path, kind: str, metadata: dict | None = None):
    path = path.resolve()
    if not path.is_relative_to((ROOT / "data").resolve()):
        raise ReviewError("来源文件必须放在项目 data 目录，禁止导入配置或凭据文件")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    original_path = path.relative_to(ROOT).as_posix()
    # Small text evidence is snapshotted before a collector can refresh its input
    # file. Audio stays at its existing location, avoiding a second media copy.
    if kind in {"metadata","manifest","subtitle","asr","candidate","weibo_json"}:
        snapshot = ROOT / "data/archive" / digest[:2] / (digest + path.suffix)
        snapshot.parent.mkdir(parents=True,exist_ok=True)
        if not snapshot.exists():
            temporary = snapshot.with_name(snapshot.name + "." + uuid.uuid4().hex + ".part")
            try:
                shutil.copyfile(path,temporary)
                with temporary.open("rb") as stream:
                    if hashlib.file_digest(stream,"sha256").hexdigest() != digest:
                        raise ReviewError("来源文件在入库时发生变化，请重新采集或转写后重试")
                temporary.replace(snapshot)
            finally:
                temporary.unlink(missing_ok=True)
        with snapshot.open("rb") as stream:
            if hashlib.file_digest(stream,"sha256").hexdigest() != digest:
                raise ReviewError("证据快照与文件名哈希不一致，停止导入")
        path = snapshot
    return conn.execute("""INSERT INTO artifacts(source_id,kind,relative_path,sha256,byte_size,metadata)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(source_id,kind,sha256)
        DO UPDATE SET relative_path=EXCLUDED.relative_path,metadata=artifacts.metadata||EXCLUDED.metadata RETURNING id""",
        (source_id, kind, path.relative_to(ROOT).as_posix(), digest, path.stat().st_size,
         Jsonb({**(metadata or {}),"ingested_from":original_path}))).fetchone()["id"]


def import_transcript(conn, source_id, path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReviewError("转写文件根节点必须是 JSON 对象")
    config = value.get("config", {})
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ReviewError("转写配置必须是 JSON 对象")
    source = value.get("source", {})
    if source is None:
        source = {}
    if not isinstance(source, dict):
        raise ReviewError("转写来源必须是 JSON 对象")

    segments = value.get("segments")
    if not isinstance(segments, list):
        raise ReviewError("转写 segments 必须是数组")

    # Validate and normalize every segment before registering an artifact or
    # inserting a transcription run, so malformed input cannot leave partial
    # rows behind. Older transcript files use seconds; FunASR exports ms.
    normalized_segments = []
    max_seconds = Decimal("999999999.999")  # transcript_segments uses numeric(12,3)
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ReviewError(f"转写片段 {index} 必须是 JSON 对象")
        if "start_ms" in segment or "end_ms" in segment:
            start_key, end_key, divisor = "start_ms", "end_ms", Decimal(1000)
        else:
            start_key, end_key, divisor = "start", "end", Decimal(1)
        if start_key not in segment or end_key not in segment:
            raise ReviewError(f"转写片段 {index} 缺少成对的开始或结束时间")

        times = []
        for key in (start_key, end_key):
            raw = segment[key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ReviewError(f"转写片段 {index} 的时间必须是有限数值")
            numeric_time = Decimal(str(raw))
            if not numeric_time.is_finite():
                raise ReviewError(f"转写片段 {index} 的时间必须是有限数值")
            times.append(numeric_time / divisor)
        start_seconds, end_seconds = times
        if start_seconds < 0 or end_seconds < 0:
            raise ReviewError(f"转写片段 {index} 的时间不能为负数")
        if end_seconds < start_seconds:
            raise ReviewError(f"转写片段 {index} 的结束时间不能早于开始时间")
        if start_seconds > max_seconds or end_seconds > max_seconds:
            raise ReviewError(f"转写片段 {index} 的时间超出数据库数值范围")
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ReviewError(f"转写片段 {index} 的文字必须是非空字符串")
        metadata = {key: segment[key] for key in (
            "avg_logprob", "no_speech_prob", "speaker", "chunk_index", "status",
            "alignment", "speaker_attribution", "speaker_ambiguous",
        ) if key in segment}
        normalized_segments.append((start_seconds, end_seconds, text, metadata))

    models = config.get("models")
    configured_model = (models.get("asr") if isinstance(models, dict) else
                        ", ".join(str(item) for item in models) if isinstance(models, list) else models)
    model = value.get("model") or config.get("model") or configured_model or "unknown"
    language = value.get("language") or config.get("language")
    audio_sha256 = (value.get("audio_sha256") or source.get("audio_sha256")
                    or config.get("audio_sha256"))
    parameters = {key: value[key] for key in (
        "clips", "device", "compute_type", "beam_size", "initial_prompt",
    ) if key in value}
    if config:
        parameters["config"] = config
    if audio_sha256 is not None:
        parameters["audio_sha256"] = audio_sha256

    artifact_id = artifact(conn, source_id, path, "asr")
    run = conn.execute("""INSERT INTO transcription_runs(source_id,artifact_id,engine,model,language,parameters)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(artifact_id) DO NOTHING RETURNING id""",
        (source_id, artifact_id, value.get("engine", "unknown"), str(model),
         language, Jsonb(parameters))).fetchone()
    if run is None:
        return conn.execute("SELECT id FROM transcription_runs WHERE artifact_id=%s", (artifact_id,)).fetchone()["id"]
    for index, (start_seconds, end_seconds, text, metadata) in enumerate(normalized_segments):
        conn.execute("""INSERT INTO transcript_segments(run_id,segment_index,start_seconds,end_seconds,text,metadata)
            VALUES(%s,%s,%s,%s,%s,%s)""", (run["id"], index, start_seconds, end_seconds, text,
            Jsonb(metadata)))
    return run["id"]


def import_media(manifest_path: Path, expected_bvid: str | None = None, expected_page: int | None = None) -> dict:
    """Stage 1 only: register media provenance, without creating game facts."""
    checked = validate_media(manifest_path,expected_bvid,expected_page)
    manifest = checked["manifest"]
    metadata = {k:manifest.get(k) for k in ["bvid","cid","page","duration_seconds","subtitles","access_mode","collection_context"]}
    metadata["raw_media_validation"] = checked["summary"]
    with connect() as conn:
        source_id = conn.execute("""INSERT INTO sources(platform,external_key,url,title,author_id,published_at,metadata)
            VALUES('bilibili',%s,%s,%s,%s,to_timestamp(%s),%s)
            ON CONFLICT(platform,external_key) DO UPDATE SET title=EXCLUDED.title,
                metadata=sources.metadata||EXCLUDED.metadata RETURNING id""",
            (f"{manifest['bvid']}:{manifest['cid']}",
             f"https://www.bilibili.com/video/{manifest['bvid']}/?p={manifest['page']}",manifest.get("title"),
             str(manifest["owner"]["mid"]),manifest.get("published_timestamp"),Jsonb(metadata))).fetchone()["id"]
        artifact_ids = [artifact(conn,source_id,checked["manifest_path"],"manifest"),
                        artifact(conn,source_id,checked["raw_path"],"metadata")]
        if checked["audio_path"] is not None:
            artifact_ids.append(artifact(conn,source_id,checked["audio_path"],"audio",manifest["audio"]))
        for path,track in checked["subtitles"]:
            artifact_ids.append(artifact(conn,source_id,path,"subtitle",track))
        audit_details = {"bvid":manifest["bvid"],
                         "audio_available":checked["summary"]["audio_available"],
                         "subtitle_available":checked["summary"]["subtitle_available"]}
        if manifest.get("audio"):
            audit_details["audio_sha256"] = manifest["audio"]["sha256"]
        conn.execute("INSERT INTO audit_events(action,actor,entity_id,details) VALUES('register_raw_media','collector',%s,%s)",
                     (source_id,Jsonb(audit_details)))
    return {"source_id":str(source_id),"artifact_ids":[str(key) for key in artifact_ids],
            "validation":checked["summary"],"transcription_started":False,"game_facts_changed":False}


def raw_status() -> dict:
    with connect() as conn:
        sources = conn.execute("""SELECT s.id,s.platform,s.external_key,s.title,s.author_id,
            s.metadata->'raw_media_validation' AS media_validation,
            (SELECT count(*) FROM artifacts a WHERE a.source_id=s.id AND a.kind IN ('metadata','manifest','audio','subtitle','weibo_json','image')) AS raw_artifact_count
            FROM sources s WHERE s.platform IN ('bilibili','weibo') ORDER BY s.platform,s.external_key""").fetchall()
        return {"raw_source_count":len(sources),"validated_audio_source_count":sum(
                bool((row["media_validation"] or {}).get(
                    "audio_available", (row["media_validation"] or {}).get("status") == "raw_media_ready"))
                for row in sources),
                "validated_subtitle_source_count":sum(
                    bool((row["media_validation"] or {}).get("subtitle_available")) for row in sources),
                "sources":sources,"note":"仅显示原始来源；不代表比赛已解析或核验"}


def import_pilot(manifest_path: Path, candidate_path: Path, extra_transcript: Path | None = None) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if manifest["bvid"] != candidate["bvid"] or manifest["cid"] != candidate["cid"]:
        raise ReviewError("候选与媒体的 BVID/CID 不一致")
    folder = manifest_path.parent
    expected_audio_hash = (manifest.get("audio") or {}).get("sha256")
    if candidate.get("audio_sha256") != expected_audio_hash:
        raise ReviewError("候选未对应到本条音轨哈希")
    metadata = candidate["metadata_candidates"]
    bvid = manifest["bvid"]
    slug = f"bili-{bvid}-p{manifest['page']:02d}-g{metadata['game_number']:02d}"
    with connect() as conn:
        source_id = conn.execute("""INSERT INTO sources(platform,external_key,url,title,author_id,published_at,metadata)
            VALUES('bilibili',%s,%s,%s,%s,to_timestamp(%s),%s)
            ON CONFLICT(platform,external_key) DO UPDATE SET metadata=EXCLUDED.metadata,title=EXCLUDED.title
            RETURNING id""", (f"{bvid}:{manifest['cid']}", manifest["url"], manifest["title"],
            str(manifest["owner"]["mid"]), manifest.get("published_timestamp"),
            Jsonb({k: manifest.get(k) for k in ["bvid","cid","page","duration_seconds","subtitles","access_mode"]}))).fetchone()["id"]
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("import-"+slug,))
        artifact(conn, source_id, manifest_path, "manifest")
        artifact(conn, source_id, folder / "metadata.raw.json", "metadata")
        if manifest.get("audio"):
            audio_path = folder / manifest["audio"]["file"]
            audio_id = artifact(conn, source_id, audio_path, "audio", manifest["audio"])
            actual = conn.execute("SELECT sha256 FROM artifacts WHERE id=%s", (audio_id,)).fetchone()["sha256"]
            if actual != expected_audio_hash:
                raise ReviewError("音频文件已变化，拒绝导入")
        for track in (manifest.get("subtitles") or {}).get("tracks") or []:
            artifact(conn, source_id, folder / track["file"], "subtitle", track)
        asr_path = ROOT / candidate["source_asr_file"]
        asr_value = json.loads(asr_path.read_text(encoding="utf-8"))
        if asr_value.get("audio_sha256") != expected_audio_hash:
            raise ReviewError("转写与原始音轨不一致")
        transcription_id = import_transcript(conn, source_id, asr_path)
        if extra_transcript and extra_transcript.resolve() != asr_path.resolve():
            extra = json.loads(extra_transcript.read_text(encoding="utf-8"))
            if extra.get("audio_sha256") != expected_audio_hash:
                raise ReviewError("补充转写与原始音轨不一致")
            import_transcript(conn, source_id, extra_transcript)
        candidate_id = artifact(conn, source_id, candidate_path, "candidate")
        extraction = conn.execute("""INSERT INTO extraction_runs(source_id,transcription_run_id,artifact_id,method,payload)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT(artifact_id) DO NOTHING RETURNING id""",
            (source_id, transcription_id, candidate_id, candidate["extraction_method"], Jsonb(candidate))).fetchone()
        if extraction is None:
            extraction = conn.execute("SELECT id FROM extraction_runs WHERE artifact_id=%s", (candidate_id,)).fetchone()
        season = conn.execute("""INSERT INTO seasons(code,name,metadata) VALUES(%s,%s,%s)
            ON CONFLICT(code) DO NOTHING RETURNING id""", (metadata["season"],
            "曙光航纪" if metadata["season"] == "S22" else metadata["season"], Jsonb({"origin":"source_metadata"}))).fetchone()
        season_id = season["id"] if season else conn.execute("SELECT id FROM seasons WHERE code=%s", (metadata["season"],)).fetchone()["id"]
        for phase in ["regular", "finals_week"]:
            conn.execute("INSERT INTO scoring_periods(season_id,phase) VALUES(%s,%s) ON CONFLICT DO NOTHING", (season_id, phase))
        game = conn.execute("""INSERT INTO games(slug,season_id,primary_source_id) VALUES(%s,%s,%s)
            ON CONFLICT(slug) DO NOTHING RETURNING id""", (slug, season_id, source_id)).fetchone()
        game_id = game["id"] if game else conn.execute("SELECT id FROM games WHERE slug=%s", (slug,)).fetchone()["id"]
        revision = conn.execute("SELECT id FROM game_revisions WHERE game_id=%s AND from_extraction_id=%s ORDER BY revision_no DESC LIMIT 1", (game_id, extraction["id"])).fetchone()
        if not revision:
            number = conn.execute("SELECT COALESCE(max(revision_no),0)+1 AS n FROM game_revisions WHERE game_id=%s", (game_id,)).fetchone()["n"]
            revision = conn.execute("""INSERT INTO game_revisions(game_id,revision_no,from_extraction_id,event_date,phase,
                game_number,board_name,expected_seats,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (game_id, number, extraction["id"], metadata["event_date"], metadata["phase"], metadata["game_number"],
                 metadata["board_name"], len(candidate["participant_candidates"]), Jsonb({"candidate_metadata_unreviewed":True}))).fetchone()
            for item in candidate["participant_candidates"]:
                conn.execute("INSERT INTO game_participants(revision_id,seat_number,proposed) VALUES(%s,%s,%s)",
                             (revision["id"], item["seat_number"], Jsonb(item)))
            conn.execute("INSERT INTO audit_events(action,actor,entity_id,details) VALUES('import_candidate','collector',%s,%s)",
                         (revision["id"], Jsonb({"source_id":str(source_id),"extraction_id":str(extraction["id"])})))
        return {"game": slug, "revision_id": str(revision["id"]), "source_id": str(source_id),
                "candidate_seats": len(candidate["participant_candidates"]), "published": False}


def status() -> dict:
    with connect() as conn:
        tables = ["sources","artifacts","transcription_runs","transcript_segments","extraction_runs",
                  "candidate_participants","games","game_revisions","players","published_games","player_basic_stats"]
        counts = {name: conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(name))).fetchone()["n"] for name in tables}
        counts["server_version"] = conn.execute("SHOW server_version").fetchone()["server_version"]
        counts["games_detail"] = conn.execute("""SELECT g.slug,r.id AS revision_id,r.review_state,r.expected_seats,
            g.published_revision_id IS NOT NULL AS published FROM games g JOIN game_revisions r ON r.game_id=g.id
            ORDER BY g.slug,r.revision_no""").fetchall()
        return counts


def latest_revision(conn, slug: str):
    row = conn.execute("""SELECT r.*,g.slug,g.primary_source_id FROM games g JOIN game_revisions r ON r.game_id=g.id
        WHERE g.slug=%s ORDER BY r.revision_no DESC LIMIT 1 FOR UPDATE OF r""", (slug,)).fetchone()
    if row is None:
        raise ReviewError("没有找到比赛")
    return row


def export_review(slug: str, target: Path) -> None:
    if target.exists():
        raise ReviewError("复核文件已存在，拒绝覆盖你的人工修改；请指定新路径")
    with connect() as conn:
        r = latest_revision(conn, slug)
        participants = conn.execute("SELECT * FROM game_participants WHERE revision_id=%s ORDER BY seat_number", (r["id"],)).fetchall()
        value = {"game_slug": slug, "based_on_revision_id": str(r["id"]), "reviewer": "", "review_type": "manual_single",
                 "review_complete": False,
                 "instructions": "请逐项核对来源后填写 facts；proposed 是机器候选。player_id 可填已有 UUID，或明确填 new:昵称 创建选手。不要直接把候选视作真值。",
                 "facts": {key: r[key] for key in ["event_date","phase","game_number","board_name","board_rule_id","expected_seats","is_extra_game","scoring_eligible","scoring_period_id","scope_confirmed","match_status","winning_faction"]},
                 "participants": [{"seat_number":p["seat_number"], "player_id":p["player_id"],
                      "nickname_as_broadcast":p["nickname_as_broadcast"], "role_code":p["role_code"],
                      "opening_faction":p["opening_faction"], "settlement_faction":p["settlement_faction"],
                      "personal_result":p["personal_result"], "base_points":p["base_points"],
                      "adjustments":p["adjustments"], "official_points":p["official_points"],
                      "proposed":p["proposed"]} for p in participants],
                 "evidence": [{"field_key":key,"source_id":str(r["primary_source_id"]),"locator":"",
                               "start_seconds":None,"end_seconds":None} for key in ["scope","roster","roles","results","rules","scoring"]]}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def apply_review(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("review_complete") is not True or not str(value.get("reviewer", "")).strip():
        raise ReviewError("必须由你完成复核，填写 reviewer 并显式设置 review_complete=true")
    with connect() as conn:
        r = latest_revision(conn, value["game_slug"])
        if str(r["id"]) != value["based_on_revision_id"] or r["review_state"] != "draft":
            raise ReviewError("复核文件不对应最新草稿；请重新导出，不能覆盖已提交版本")
        facts = value["facts"]
        columns = ["event_date","phase","game_number","board_name","board_rule_id","expected_seats","is_extra_game",
                   "scoring_eligible","scoring_period_id","scope_confirmed","match_status","winning_faction"]
        conn.execute(sql.SQL("UPDATE game_revisions SET {} WHERE id=%s").format(sql.SQL(",").join(
            sql.SQL("{}=%s").format(sql.Identifier(c)) for c in columns)), [facts.get(c) for c in columns] + [r["id"]])
        conn.execute("DELETE FROM evidence_links WHERE revision_id=%s", (r["id"],))
        conn.execute("DELETE FROM game_participants WHERE revision_id=%s", (r["id"],))
        for item in value["participants"]:
            player = item.get("player_id")
            if isinstance(player, str) and player.startswith("new:"):
                name = player[4:].strip()
                if not name or conn.execute("SELECT 1 FROM players WHERE display_name=%s", (name,)).fetchone():
                    raise ReviewError("新选手名称为空或已有同名选手；请明确使用稳定选手 UUID")
                player = conn.execute("INSERT INTO players(display_name) VALUES(%s) RETURNING id", (name,)).fetchone()["id"]
                conn.execute("INSERT INTO player_aliases(player_id,alias) VALUES(%s,%s)", (player, name))
            conn.execute("""INSERT INTO game_participants(revision_id,seat_number,player_id,nickname_as_broadcast,role_code,
                opening_faction,settlement_faction,personal_result,base_points,adjustments,official_points)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (r["id"], item["seat_number"], player,
                item.get("nickname_as_broadcast"), item.get("role_code"), item.get("opening_faction"),
                item.get("settlement_faction"), item.get("personal_result", "unknown"), item.get("base_points"),
                item.get("adjustments"), item.get("official_points")))
        for item in value["evidence"]:
            conn.execute("""INSERT INTO evidence_links(revision_id,source_id,artifact_id,field_key,locator,start_seconds,end_seconds)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""", (r["id"], item["source_id"], item.get("artifact_id"),
                item["field_key"], item["locator"], item.get("start_seconds"), item.get("end_seconds")))
        conn.execute("SELECT assert_revision_ready(%s)", (r["id"],))
        conn.execute("UPDATE game_revisions SET review_state='submitted' WHERE id=%s", (r["id"],))
        conn.execute("INSERT INTO reviews(revision_id,reviewer,review_type,decision,comment) VALUES(%s,%s,%s,'approved',%s)",
                     (r["id"], value["reviewer"], value.get("review_type", "manual_single"), "由本地复核文件显式确认"))
        conn.execute("UPDATE game_revisions SET review_state='approved' WHERE id=%s", (r["id"],))
        conn.execute("INSERT INTO audit_events(action,actor,entity_id) VALUES('approve_review',%s,%s)", (value["reviewer"], r["id"]))
        return {"approved_revision_id":str(r["id"]),"published":False}


def publish(slug: str, actor: str, withdraw: bool = False, reason: str = "人工复核后发布") -> dict:
    if not actor.strip() or not reason.strip():
        raise ReviewError("操作人和原因不能为空")
    with connect() as conn:
        game = conn.execute("SELECT * FROM games WHERE slug=%s FOR UPDATE", (slug,)).fetchone()
        if not game:
            raise ReviewError("没有找到比赛")
        old = game["published_revision_id"]
        if withdraw:
            target = old
            if target is None:
                return {"game":slug,"published":False,"changed":False}
        else:
            target = latest_revision(conn, slug)["id"]
            if target == old:
                return {"game":slug,"published":True,"changed":False}
        conn.execute("UPDATE games SET published_revision_id=%s WHERE id=%s", (None if withdraw else target, game["id"]))
        conn.execute("INSERT INTO publication_events(game_id,revision_id,action,actor,reason) VALUES(%s,%s,%s,%s,%s)",
                     (game["id"], target, "withdraw" if withdraw else "publish", actor, reason))
        return {"game":slug,"published":not withdraw,"changed":True}


def import_rule(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("kind") not in {"board", "scoring"} or not str(value.get("code", "")).strip():
        raise ReviewError("规则需要 code 和 kind（board/scoring）")
    verified = value.get("verified") is True
    if verified and (value.get("review_complete") is not True or
                     not str(value.get("reviewer", "")).strip() or
                     not str(value.get("evidence_locator", "")).strip() or not value.get("season_code")):
        raise ReviewError("已核验规则必须指定赛季、reviewer、evidence_locator 并设置 review_complete=true")
    definition = value.get("definition")
    if not isinstance(definition, dict):
        raise ReviewError("definition 必须是 JSON 对象")
    if verified and value["kind"] == "board":
        counts = definition.get("role_counts")
        if (not isinstance(counts, dict) or not counts or
            any(type(n) is not int or n < 1 for n in counts.values()) or
            sum(counts.values()) != definition.get("participant_count") or
            definition.get("result_mode") not in {"faction", "explicit"}):
            raise ReviewError("已核验板子需要人数、各角色数量和 result_mode（faction/explicit）")
    with connect() as conn:
        season_id = None
        if value.get("season_code"):
            season = conn.execute("SELECT id FROM seasons WHERE code=%s", (value["season_code"],)).fetchone()
            if not season:
                raise ReviewError("请先导入该赛季的比赛候选")
            season_id = season["id"]
        source_id = value.get("source_id")
        if not source_id and value.get("source"):
            ref = value["source"]
            source = conn.execute("SELECT id FROM sources WHERE platform=%s AND external_key=%s",
                                  (ref.get("platform"), ref.get("external_key"))).fetchone()
            source_id = source["id"] if source else None
        source = conn.execute("SELECT platform FROM sources WHERE id=%s", (source_id,)).fetchone() if source_id else None
        if not source or (verified and source["platform"] == "user_reported"):
            raise ReviewError("规则需要已入库的证据来源；用户口述不能直接成为已核验官源规则")
        definition = {**definition, "verification": {"reviewer": value.get("reviewer"),
                      "evidence_locator": value.get("evidence_locator"), "review_complete": verified}}
        previous = conn.execute("SELECT * FROM rule_versions WHERE code=%s", (value["code"],)).fetchone()
        if previous:
            if (previous["definition"] != definition or previous["verified"] != verified or
                previous["kind"] != value["kind"] or previous["source_id"] != uuid.UUID(str(source_id)) or
                previous["season_id"] != season_id):
                raise ReviewError("同一 code 已有不同规则；请使用新版本 code，保留原记录")
            return {"rule_id":str(previous["id"]), "code":value["code"], "verified":verified, "changed":False}
        row = conn.execute("""INSERT INTO rule_versions(code,kind,season_id,source_id,verified,definition)
            VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",
            (value["code"],value["kind"],season_id,source_id,verified,Jsonb(definition))).fetchone()
        conn.execute("INSERT INTO audit_events(action,actor,entity_id,details) VALUES('import_rule',%s,%s,%s)",
                     (value.get("reviewer") or "collector",row["id"],Jsonb({"verified":verified,"code":value["code"]})))
        return {"rule_id":str(row["id"]),"code":value["code"],"verified":verified,"changed":True}


def seed_reported_rules() -> dict:
    value = json.loads((ROOT / "config/game_rules.json").read_text(encoding="utf-8"))["scoring"]
    with connect() as conn:
        source = conn.execute("""INSERT INTO sources(platform,external_key,title,metadata)
            VALUES('user_reported','2026-10-20-base-rules','用户报告的共同基础赛制',%s)
            ON CONFLICT(platform,external_key) DO UPDATE SET title=EXCLUDED.title RETURNING id""",
            (Jsonb({"official_verified":False}),)).fetchone()["id"]
        row = conn.execute("""INSERT INTO rule_versions(code,kind,source_id,definition)
            VALUES(%s,'scoring',%s,%s) ON CONFLICT(code) DO NOTHING RETURNING id""",
            (value["config_id"],source,Jsonb(value))).fetchone()
        rule_id = row["id"] if row else conn.execute("SELECT id FROM rule_versions WHERE code=%s", (value["config_id"],)).fetchone()["id"]
        return {"rule_id":str(rule_id),"verified":False,"season_id":None,"bound_to_period":False}


def catalog(kind: str) -> list[dict]:
    queries = {
        "sources":"SELECT id,platform,external_key,title,url FROM sources ORDER BY collected_at",
        "players":"SELECT id,display_name FROM players ORDER BY display_name",
        "people":"SELECT id,name FROM people ORDER BY name",
        "rules":"SELECT r.id,r.code,r.kind,s.code AS season,r.verified,r.source_id FROM rule_versions r LEFT JOIN seasons s ON s.id=r.season_id ORDER BY r.code",
        "periods":"SELECT p.id,s.code AS season,p.phase,p.version_no,p.rule_version_id,p.metadata FROM scoring_periods p JOIN seasons s ON s.id=p.season_id ORDER BY s.code,p.phase,p.version_no"}
    with connect() as conn:
        return conn.execute(queries[kind]).fetchall()


def bind_period(season: str, phase: str, code: str, actor: str) -> dict:
    if not actor.strip():
        raise ReviewError("操作人不能为空")
    with connect() as conn:
        season_row = conn.execute("SELECT id FROM seasons WHERE code=%s FOR UPDATE", (season,)).fetchone()
        if not season_row:
            raise ReviewError("赛季不存在")
        rule = conn.execute("SELECT * FROM rule_versions WHERE code=%s", (code,)).fetchone()
        if not rule or not rule["verified"] or rule["kind"] != "scoring" or rule["season_id"] != season_row["id"]:
            raise ReviewError("请选择该赛季已经核验的 scoring 规则版本")
        period = conn.execute("SELECT * FROM scoring_periods WHERE season_id=%s AND phase=%s ORDER BY version_no DESC LIMIT 1 FOR UPDATE",
                              (season_row["id"],phase)).fetchone()
        if period and period["rule_version_id"] == rule["id"]:
            return {"scoring_period_id":str(period["id"]),"changed":False}
        frozen = period and conn.execute("SELECT 1 FROM game_revisions WHERE scoring_period_id=%s AND review_state<>'draft' LIMIT 1", (period["id"],)).fetchone()
        if period and not frozen:
            conn.execute("UPDATE scoring_periods SET rule_version_id=%s WHERE id=%s", (rule["id"],period["id"]))
            period_id = period["id"]
        else:
            period_id = conn.execute("""INSERT INTO scoring_periods(season_id,phase,version_no,rule_version_id)
                VALUES(%s,%s,%s,%s) RETURNING id""", (season_row["id"],phase,period["version_no"]+1 if period else 1,rule["id"])).fetchone()["id"]
        conn.execute("INSERT INTO audit_events(action,actor,entity_id,details) VALUES('bind_scoring_rule',%s,%s,%s)",
                     (actor,period_id,Jsonb({"rule_code":code,"season":season,"phase":phase})))
        return {"scoring_period_id":str(period_id),"changed":True}


def new_draft(slug: str, actor: str) -> dict:
    if not actor.strip():
        raise ReviewError("操作人不能为空")
    with connect() as conn:
        conn.execute("SELECT id FROM games WHERE slug=%s FOR UPDATE", (slug,))
        old = latest_revision(conn,slug)
        if old["review_state"] == "draft":
            raise ReviewError("已有草稿；请导出它进行复核")
        columns = ["game_id","revision_no","from_extraction_id","event_date","phase","game_number","board_name",
                   "board_rule_id","expected_seats","is_extra_game","scoring_eligible","scoring_period_id","scope_confirmed",
                   "match_status","winning_faction","metadata"]
        values = [old[c] if c != "revision_no" else old[c]+1 for c in columns]
        values[-1] = Jsonb({**values[-1],"copied_from_revision":str(old["id"])})
        row = conn.execute(sql.SQL("INSERT INTO game_revisions({}) VALUES({}) RETURNING id").format(
            sql.SQL(",").join(map(sql.Identifier,columns)),sql.SQL(",").join([sql.Placeholder()]*len(columns))),values).fetchone()
        mapping = {}
        for item in conn.execute("SELECT * FROM game_participants WHERE revision_id=%s", (old["id"],)).fetchall():
            participant_columns = [c for c in item if c not in {"id","revision_id"}]
            params = [Jsonb(item[c]) if c == "proposed" else item[c] for c in participant_columns]
            new_id = conn.execute(sql.SQL("INSERT INTO game_participants(revision_id,{}) VALUES(%s,{}) RETURNING id").format(
                sql.SQL(",").join(map(sql.Identifier,participant_columns)),sql.SQL(",").join([sql.Placeholder()]*len(params))),
                [row["id"]]+params).fetchone()["id"]
            mapping[item["id"]] = new_id
        for evidence in conn.execute("SELECT * FROM evidence_links WHERE revision_id=%s", (old["id"],)).fetchall():
            conn.execute("""INSERT INTO evidence_links(revision_id,participant_id,source_id,artifact_id,field_key,locator,
                start_seconds,end_seconds,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (row["id"],mapping.get(evidence["participant_id"]),evidence["source_id"],evidence["artifact_id"],
                 evidence["field_key"],evidence["locator"],evidence["start_seconds"],evidence["end_seconds"],Jsonb(evidence["metadata"])))
        conn.execute("INSERT INTO audit_events(action,actor,entity_id,details) VALUES('new_draft',%s,%s,%s)",
                     (actor,row["id"],Jsonb({"previous_revision_id":str(old["id"])})))
        return {"revision_id":str(row["id"]),"revision_no":old["revision_no"]+1,"published_pointer_changed":False}


def import_weibo(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("source") != "https://m.weibo.cn" or not isinstance(value.get("posts"),list):
        raise ReviewError("不是 collect_weibo.py 生成的清单")
    ids = []
    with connect() as conn:
        for post in value["posts"]:
            raw = (path.parent / post["raw_file"]).resolve()
            if not raw.is_relative_to(path.parent.resolve()):
                raise ReviewError("微博原文路径超出本次采集目录")
            source_id = conn.execute("""INSERT INTO sources(platform,external_key,url,title,author_id,metadata)
                VALUES('weibo',%s,%s,%s,%s,%s) ON CONFLICT(platform,external_key)
                DO UPDATE SET metadata=EXCLUDED.metadata RETURNING id""", (str(post["post_id"]),post["post_url"],
                post["text"][:160],str(post["author_uid"]),Jsonb({**post,"collection_status":value["status"],"facts_verified":False}))).fetchone()["id"]
            artifact(conn,source_id,path,"manifest")
            artifact(conn,source_id,raw,"weibo_json")
            for picture in post.get("images",[]):
                if picture.get("status") == "downloaded":
                    image = (path.parent / picture["file"]).resolve()
                    if not image.is_relative_to(path.parent.resolve()):
                        raise ReviewError("微博图片路径超出本次采集目录")
                    artifact(conn,source_id,image,"image",picture)
            ids.append(str(source_id))
    return {"imported_posts":len(ids),"source_ids":ids,"collection_status":value.get("status"),"game_facts_changed":False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    commands.add_parser("status")
    commands.add_parser("raw-status")
    media = commands.add_parser("import-media")
    media.add_argument("manifest",type=Path)
    commands.add_parser("seed-reported-rules")
    rule = commands.add_parser("import-rule")
    rule.add_argument("file",type=Path)
    listing = commands.add_parser("catalog")
    listing.add_argument("kind",choices=["sources","players","people","rules","periods"])
    weibo = commands.add_parser("import-weibo")
    weibo.add_argument("manifest",type=Path)
    period = commands.add_parser("bind-period")
    period.add_argument("--season",required=True)
    period.add_argument("--phase",choices=["regular","finals_week"],required=True)
    period.add_argument("--rule",required=True)
    period.add_argument("--actor",required=True)
    draft = commands.add_parser("new-draft")
    draft.add_argument("--game",default=PILOT)
    draft.add_argument("--actor",required=True)
    pilot = commands.add_parser("import-pilot")
    pilot.add_argument("--manifest", type=Path, default=ROOT / "data/raw/bilibili/BV1tj8p6REqy/p01/manifest.json")
    pilot.add_argument("--candidate", type=Path, default=ROOT / "data/candidates/BV1tj8p6REqy.game.candidate.json")
    pilot.add_argument("--transcript", type=Path)
    export = commands.add_parser("export-review")
    export.add_argument("--game", default=PILOT)
    export.add_argument("--out", type=Path, default=ROOT / "data/reviews/pilot.review.json")
    review = commands.add_parser("apply-review")
    review.add_argument("file", type=Path)
    for action in ["publish", "withdraw"]:
        item = commands.add_parser(action)
        item.add_argument("--game", default=PILOT)
        item.add_argument("--actor", required=True)
        item.add_argument("--reason", default="人工复核后发布" if action == "publish" else "人工撤回")
    args = parser.parse_args()
    if args.command == "migrate":
        result = {"applied":migrate()}
    elif args.command == "status":
        result = status()
    elif args.command == "raw-status":
        result = raw_status()
    elif args.command == "import-media":
        result = import_media(args.manifest)
    elif args.command == "seed-reported-rules":
        result = seed_reported_rules()
    elif args.command == "import-rule":
        result = import_rule(args.file)
    elif args.command == "catalog":
        result = catalog(args.kind)
    elif args.command == "bind-period":
        result = bind_period(args.season,args.phase,args.rule,args.actor)
    elif args.command == "new-draft":
        result = new_draft(args.game,args.actor)
    elif args.command == "import-weibo":
        result = import_weibo(args.manifest.resolve())
    elif args.command == "import-pilot":
        result = import_pilot(args.manifest.resolve(),args.candidate.resolve(),args.transcript.resolve() if args.transcript else None)
    elif args.command == "export-review":
        export_review(args.game,args.out.resolve())
        result = {"review_file":str(args.out),"published":False}
    elif args.command == "apply-review":
        result = apply_review(args.file)
    else:
        result = publish(args.game,args.actor,args.command == "withdraw",args.reason)
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        main()
    except (ReviewError, psycopg.Error, OSError, ValueError) as error:
        # Never echo connection strings, SQL parameters or credentials.
        message = str(error) if isinstance(error, (ReviewError,MediaValidationError)) else (error.diag.message_primary if isinstance(error,psycopg.Error) and error.diag.message_primary else type(error).__name__)
        print("数据库操作停止：" + message,file=sys.stderr)
        raise SystemExit(1)
