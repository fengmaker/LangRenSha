"""Read-only FastAPI application for published Masters snapshots."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from website.api.analytics import (
    analytics_notes,
    build_leaderboard,
    compute_player_stats,
    compute_player_summaries,
    effective_faction,
    scope_games,
)
from website.api.photos import photo_for, photo_path
from website.api.bluff_frames import frame_path as bluff_frame_path
from website.api.bluffs import METHODOLOGY as BLUFF_METHODOLOGY, S23_VIDEO_METHODOLOGY, aggregate_bluffs, review_items
from website.api.bluff_store import read_review
from website.api.game_presentation import build_game_presentation
from scripts.season_config import load_season, season_codes


app = FastAPI(title="Masters archive API", version="1.0.0", debug=False)
ANALYTICS_VERSION = 9
SEASON_CATALOG = {code: load_season(code) for code in season_codes()}


class Count(BaseModel):
    role: str | None
    count: int


class Board(BaseModel):
    code: str
    name: str


class PlayerInGame(BaseModel):
    id: str
    name: str
    seat: int
    role: str | None
    faction: str | None


class GameSummary(BaseModel):
    id: str
    season: str
    date: str
    phase: str
    game_number: int | None
    board: Board
    winner: str | None
    players: list[PlayerInGame]
    ballot_count: int
    round_count: int


class GameDetail(GameSummary):
    analytics_version: int = ANALYTICS_VERSION
    release_id: str
    commentators: list[str]
    referee: str | None
    seats: list[dict[str, Any]]
    rounds: list[dict[str, Any]]
    rules_state: dict[str, Any] = Field(default_factory=dict)
    presentation: dict[str, Any] = Field(default_factory=dict)
    terminal_observation: dict[str, Any] | None = None
    terminal_events: list[dict[str, Any]] | None = None
    voting: dict[str, Any]
    endgame: dict[str, Any]
    source: dict[str, str]
    data_notes: list[str]


class PlayerSummary(BaseModel):
    id: str
    name: str
    appearances: int
    roles: list[Count]
    stats: dict[str, Any] | None = None
    photo: dict[str, Any] | None = None


class PageGames(BaseModel):
    items: list[GameSummary]
    total: int
    page: int
    page_size: int
    release_id: str


class PagePlayers(BaseModel):
    analytics_version: int = ANALYTICS_VERSION
    items: list[PlayerSummary]
    total: int
    page: int
    page_size: int
    release_id: str


class Overview(BaseModel):
    release: dict[str, Any]
    totals: dict[str, int]
    seasons: list[dict[str, Any]]
    boards: list[dict[str, Any]]
    recent_games: list[GameSummary]


class PlayerDetail(BaseModel):
    analytics_version: int = ANALYTICS_VERSION
    bluff_data_source: Literal["database"] = "database"
    bluff_inference_version: str | None = None
    photo: dict[str, Any] | None = None
    id: str
    name: str
    appearances: int
    roles: list[Count]
    boards: list[dict[str, Any]]
    games: list[GameSummary]
    release_id: str
    stats: dict[str, Any]
    scope: dict[str, Any]
    available_seasons: list[str]


class BoardStats(BaseModel):
    code: str
    name: str
    games: int
    good_wins: int
    werewolf_wins: int
    unknown: int


class Stats(BaseModel):
    analytics_version: int = ANALYTICS_VERSION
    release_id: str
    game_count: int
    roles: list[Count]
    boards: list[BoardStats]
    players: list[PlayerSummary]
    methodology: list[str]
    scope: dict[str, Any]
    available_seasons: list[str]


class ReleaseSummary(BaseModel):
    id: str
    published_at: datetime
    game_count: int
    source_hash: str
    active: bool


class Releases(BaseModel):
    items: list[ReleaseSummary]


def _connect_readonly():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        conn = psycopg.connect(database_url, row_factory=dict_row)
    else:
        # Local development fallback; deployed API works with only this package
        # and DATABASE_URL and never imports source ingestion modules.
        import sys
        from pathlib import Path
        scripts = str(Path(__file__).resolve().parents[2] / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import database
        conn = database.connect("masters_web")
        conn.commit()
    conn.execute("BEGIN READ ONLY")
    conn.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier("masters_web")))
    return conn


def connection_dependency():
    try:
        conn = _connect_readonly()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _release(conn) -> dict:
    try:
        row = conn.execute(
            "SELECT r.id, r.published_at, r.game_count, r.source_hash "
            "FROM active_release a JOIN releases r ON r.id = a.release_id WHERE a.singleton = true"
        ).fetchone()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="No published release") from exc
    if not row:
        raise HTTPException(status_code=503, detail="No published release")
    return row


def _resolved_snapshot(snapshot: dict) -> dict:
    """Resolve derived factions for display without changing persisted source facts."""
    seats = [{**seat, "faction": effective_faction(snapshot, seat),
              "faction_inferred": seat.get("faction") is None and effective_faction(snapshot, seat) is not None}
             for seat in snapshot["seats"]]
    by_number = {seat["seat"]: seat for seat in seats}
    notes = list(snapshot.get("data_notes", []))
    if all(seat["faction"] is not None for seat in seats):
        notes = [note for note in notes if note != "部分座位阵营待核，保留未知值。"]
    for seat in seats:
        if seat["faction_inferred"]:
            notes.append(f"{seat['seat']}号 {seat['name']}为混血儿，个人阵营按已记录榜样确定。")
    return {**snapshot, "seats": seats, "data_notes": notes,
            "players": [{**player, "faction": by_number[player["seat"]]["faction"]}
                        for player in snapshot["players"]]}


def _summary(snapshot: dict) -> dict:
    snapshot = _resolved_snapshot(snapshot)
    return {key: snapshot[key] for key in (
        "id", "season", "date", "phase", "game_number", "board", "winner", "players",
        "ballot_count", "round_count",
    )}


def _game_query(conn, release_id: str, *, season=None, phase=None, board=None, player=None, q=None,
                page=1, page_size=24) -> tuple[list[dict], int]:
    conditions = ["g.release_id = %s"]
    values: list[Any] = [release_id]
    if season:
        conditions.append("g.season = %s")
        values.append(season)
    if phase:
        conditions.append("g.phase = %s")
        values.append(phase)
    if board:
        conditions.append("g.board_code = %s")
        values.append(board)
    if player:
        conditions.append(
            "EXISTS (SELECT 1 FROM game_players gp WHERE gp.release_id=g.release_id AND gp.game_id=g.id "
            "AND (gp.person_id=%s OR strpos(lower(gp.name), lower(%s)) > 0))"
        )
        values.extend((player, player))
    if q:
        conditions.append("strpos(lower(g.search_text), lower(%s)) > 0")
        values.append(q)
    where = " AND ".join(conditions)
    total = conn.execute(f"SELECT count(*) AS total FROM games g WHERE {where}", values).fetchone()["total"]
    rows = conn.execute(
        "SELECT snapshot FROM games g WHERE " + where +
        " ORDER BY g.event_date DESC, g.game_number DESC NULLS LAST, g.id LIMIT %s OFFSET %s",
        [*values, page_size, (page - 1) * page_size],
    ).fetchall()
    return [_summary(row["snapshot"]) for row in rows], total


def _scope_snapshots(conn, release_id: str, season: str, phase: str = "all") -> list[dict[str, Any]]:
    conditions = ["release_id=%s", "season=%s"]
    values: list[Any] = [release_id, season]
    if phase != "all":
        conditions.append("phase=%s")
        values.append(phase)
    rows = conn.execute(
        "SELECT snapshot FROM games WHERE " + " AND ".join(conditions) +
        " ORDER BY event_date,game_number NULLS LAST,id", values,
    ).fetchall()
    return [row["snapshot"] for row in rows]


def _available_seasons(conn, release_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT season FROM games WHERE release_id=%s ORDER BY season", (release_id,)
    ).fetchall()
    return [row["season"] for row in rows]


def _player_season_range(available: list[str], season: str, season_start: str | None,
                         season_end: str | None) -> tuple[str, str, list[str]]:
    """Resolve and validate the player's inclusive season range."""
    latest = available[-1] if available else None
    start_value = season_start or season
    end_value = season_end or ("latest" if season_start is not None else season)
    start = latest if start_value == "latest" else start_value
    end = latest if end_value == "latest" else end_value

    if start is None or start not in available:
        raise HTTPException(status_code=422, detail=f"Unknown season_start: {start_value}")
    if end is None or end not in available:
        raise HTTPException(status_code=422, detail=f"Unknown season_end: {end_value}")

    start_index = available.index(start)
    end_index = available.index(end)
    if start_index > end_index:
        raise HTTPException(status_code=422, detail="season_start must not be later than season_end")
    return start, end, available[start_index:end_index + 1]


def _combine_player_bluff_stats(snapshots_by_season: list[tuple[str, list[dict[str, Any]]]],
                                release_id: str, conn) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Combine season-local bluff results, always pairing games with their own review."""
    combined: dict[str, dict[str, Any]] = {}
    inference_versions: list[tuple[str, str | None]] = []
    for season, snapshots in snapshots_by_season:
        payload = read_review(conn, release_id, season)
        inference_versions.append((season, payload.get("inference_version")))
        season_stats = aggregate_bluffs(snapshots, payload)
        for player_id, season_row in season_stats.items():
            row = combined.setdefault(player_id, {
                "bluff_count": 0, "bluff_count_complete": True, "bluff_pending_games": 0,
                "bluff_review_count": 0, "bluff_success_rate": {
                    "numerator": 0, "denominator": 0, "rate": None, "excluded": 0, "game_ids": []},
            })
            row["bluff_count"] += season_row["bluff_count"]
            row["bluff_count_complete"] = row["bluff_count_complete"] and season_row["bluff_count_complete"]
            row["bluff_pending_games"] += season_row["bluff_pending_games"]
            row["bluff_review_count"] += season_row["bluff_review_count"]
            metric = row["bluff_success_rate"]
            season_metric = season_row["bluff_success_rate"]
            for key in ("numerator", "denominator", "excluded"):
                metric[key] += season_metric[key]
            metric["game_ids"].extend(season_metric["game_ids"])

    for row in combined.values():
        metric = row["bluff_success_rate"]
        metric["game_ids"] = list(dict.fromkeys(metric["game_ids"]))
        metric["rate"] = metric["numerator"] / metric["denominator"] if metric["denominator"] else None

    versions = [version for _, version in inference_versions]
    if not any(versions):
        inference_version = None
    elif len(inference_versions) == 1:
        inference_version = versions[0]
    else:
        inference_version = ", ".join(f"{season}: {version or 'unpublished'}"
                                       for season, version in inference_versions)
    return combined, inference_version


@app.get("/health")
def health():
    try:
        conn = _connect_readonly()
        conn.execute("SELECT 1")
        conn.rollback()
        conn.close()
        return {"status": "ok"}
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@app.get("/api/v1/overview", response_model=Overview)
def overview(conn=Depends(connection_dependency)):
    release = _release(conn)
    totals = conn.execute(
        "SELECT count(*) AS games, count(DISTINCT event_date) AS days, "
        "coalesce(sum(ballot_count),0) AS ballots, coalesce(sum(vote_count),0) AS votes "
        "FROM games WHERE release_id=%s", (release["id"],)
    ).fetchone()
    totals["players"] = conn.execute(
        "SELECT count(*) AS n FROM players WHERE release_id=%s", (release["id"],)
    ).fetchone()["n"]
    seasons = conn.execute(
        "SELECT season AS id, season AS name, count(*) AS games, count(DISTINCT event_date) AS days "
        "FROM games WHERE release_id=%s GROUP BY season ORDER BY season", (release["id"],)
    ).fetchall()
    for season in seasons:
        season["name"] = SEASON_CATALOG.get(season["id"], {}).get("name", season["id"])
    boards = conn.execute(
        "SELECT board_code AS code, board_name AS name, count(*) AS games FROM games "
        "WHERE release_id=%s GROUP BY board_code,board_name ORDER BY games DESC,name", (release["id"],)
    ).fetchall()
    recent, _ = _game_query(conn, release["id"], page=1, page_size=12)
    return {"release": release, "totals": totals, "seasons": seasons,
            "boards": boards, "recent_games": recent}


@app.get("/api/v1/games", response_model=PageGames)
def games(season: str | None = Query(default=None, max_length=32),
          phase: str | None = Query(default=None, max_length=32),
          board: str | None = Query(default=None, max_length=64),
          player: str | None = Query(default=None, max_length=120),
          q: str | None = Query(default=None, max_length=120),
          page: int = Query(default=1, ge=1, le=100000),
          page_size: int = Query(default=24, ge=1, le=100),
          conn=Depends(connection_dependency)):
    release = _release(conn)
    items, total = _game_query(conn, release["id"], season=season, phase=phase,
                               board=board, player=player, q=q, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "release_id": release["id"]}


@app.get("/api/v1/games/{game_id}", response_model=GameDetail)
def game_detail(game_id: str, conn=Depends(connection_dependency)):
    release = _release(conn)
    row = conn.execute("SELECT snapshot FROM games WHERE release_id=%s AND id=%s", (release["id"], game_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Game not found")
    snapshot = _resolved_snapshot(row["snapshot"])
    presentation = snapshot.get("presentation")
    if not isinstance(presentation, dict) or not presentation:
        presentation = build_game_presentation(snapshot)
    return {**snapshot, "presentation": presentation}


@app.get("/api/v1/photos/{season}/{filename}")
def player_photo(season: str, filename: str):
    path = photo_path(season, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[path.suffix]
    return FileResponse(path, media_type=media_type, headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff", "ETag": f'"{path.stem}"',
    })


@app.get("/api/v1/bluff-frames/{season}/{filename}")
def bluff_frame(season: str, filename: str):
    path=bluff_frame_path(season,filename)
    if path is None:
        raise HTTPException(status_code=404,detail="Frame not found")
    return FileResponse(path,media_type="image/png",headers={
        "Cache-Control":"public, max-age=31536000, immutable",
        "X-Content-Type-Options":"nosniff", "ETag":f'"{path.stem}"',
    })


@app.get("/api/v1/players", response_model=PagePlayers)
def players(q: str | None = Query(default=None, max_length=120),
            season: str = Query(default="S22", max_length=32),
            phase: Literal["all", "regular", "finals_week"] = "all",
            page: int = Query(default=1, ge=1, le=100000),
            page_size: int = Query(default=48, ge=1, le=100),
            conn=Depends(connection_dependency)):
    release = _release(conn)
    snapshots = _scope_snapshots(conn, release["id"], season)
    summaries = compute_player_summaries(snapshots, season=season)
    if q:
        summaries = [item for item in summaries if q.casefold() in item["name"].casefold()]
    total = len(summaries)
    start = (page - 1) * page_size
    items = summaries[start:start + page_size]
    for item in items:
        item["photo"] = photo_for(item["name"], season)
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "release_id": release["id"]}


@app.get("/api/v1/players/{player_id}", response_model=PlayerDetail)
def player_detail(player_id: str,
                  season: str = Query(default="S22", max_length=32),
                  season_start: str | None = Query(default=None, max_length=32),
                  season_end: str | None = Query(default=None, max_length=32),
                  phase: Literal["all", "regular", "finals_week"] = "all",
                  conn=Depends(connection_dependency)):
    release = _release(conn)
    player = conn.execute(
        "SELECT id,name FROM players WHERE release_id=%s AND id=%s",
        (release["id"], player_id),
    ).fetchone()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    available_seasons = _available_seasons(conn, release["id"])
    resolved_start, resolved_end, selected_seasons = _player_season_range(
        available_seasons, season, season_start, season_end,
    )
    snapshots_by_season = [
        (selected_season, _scope_snapshots(conn, release["id"], selected_season))
        for selected_season in selected_seasons
    ]
    snapshots = [snapshot for _, season_snapshots in snapshots_by_season for snapshot in season_snapshots]
    player_games = [snapshot for snapshot in snapshots
                    if any(seat.get("person_id") == player_id for seat in snapshot.get("seats", []))]
    player_games.sort(key=lambda snapshot: (
        snapshot.get("game_number") is None,
        -snapshot["game_number"] if snapshot.get("game_number") is not None else 0,
        snapshot.get("id", ""),
    ))
    player_games.sort(key=lambda snapshot: snapshot.get("date", ""), reverse=True)
    board_counts: Counter[tuple[str, str]] = Counter(
        ((snapshot.get("board") or {}).get("code", ""), (snapshot.get("board") or {}).get("name", ""))
        for snapshot in player_games
    )
    boards = [{"code": code, "name": name, "count": count}
              for (code, name), count in sorted(board_counts.items(), key=lambda row: (-row[1], row[0][1]))]
    stats = compute_player_stats(player_id, snapshots, season=resolved_start, seasons=selected_seasons,
                                 name=player["name"])
    bluff_stats, bluff_inference_version = _combine_player_bluff_stats(
        snapshots_by_season, release["id"], conn,
    )
    stats.update(bluff_stats.get(player_id, {}))
    roles = [{"role": role["role"], "count": role["appearances"]} for role in stats["roles"]]
    return {**player, "appearances": stats["appearances"], "roles": roles,
            "photo": photo_for(player["name"], resolved_end),
            "boards": boards, "games": [_summary(snapshot) for snapshot in player_games],
            "release_id": release["id"], "stats": stats,
            "bluff_data_source": "database", "bluff_inference_version": bluff_inference_version,
            "scope": {"season": resolved_end, "season_start": resolved_start,
                      "season_end": resolved_end, "seasons": selected_seasons,
                      "phase": "all", "games": len(snapshots)},
            "available_seasons": available_seasons}


@app.get("/api/v1/leaderboard")
def leaderboard(season: str = Query(default="S22", max_length=32),
                 phase: Literal["all", "regular", "finals_week"] = "all",
                 conn=Depends(connection_dependency)):
    release = _release(conn)
    phase = "all" if phase == "regular" else phase
    season_snapshots = _scope_snapshots(conn, release["id"], season, "all")
    snapshots = scope_games(season_snapshots, season, phase)
    items = build_leaderboard(season_snapshots, season=season, phase=phase)
    bluff_payload = read_review(conn, release["id"], season)
    bluff_stats = aggregate_bluffs(season_snapshots, bluff_payload)
    for item in items:
        item["photo"] = photo_for(item["name"], season)
        item.update(bluff_stats.get(item["id"], {}))
    return {
        "release_id": release["id"], "analytics_version": ANALYTICS_VERSION,
        "season": season, "phase": phase,
        "season_status": SEASON_CATALOG.get(season, {}).get("status", "unknown"),
        "bluff_data_source": "database", "bluff_inference_version": bluff_payload.get("inference_version"),
        "game_count": len(snapshots),
        "pending_games": sum(item["pending_games"] for item in items),
        "scoring": {"werewolf_win": 1.5, "good_win": 1, "loss": -1},
        "items": items,
        "notes": analytics_notes(season_snapshots, season=season, phase=phase) + BLUFF_METHODOLOGY
        + (["本季已采用用户人工复核；明确选中的混血儿与人工成功结果按该批记录优先。"]
           if bluff_payload.get('manual_review') else []),
    }


@app.get("/api/v1/bluff-review")
def bluff_review(season: str = Query(default="S22", max_length=20),
                 status: Literal["all", "pending", "assistant_pending"] = "pending",
                 player: str = Query(default="", max_length=100),
                 conn=Depends(connection_dependency)):
    release = _release(conn)
    snapshots = _scope_snapshots(conn, release["id"], season, "all")
    payload = read_review(conn, release["id"], season)
    rows = review_items(snapshots, payload)
    if player:
        rows = [row for row in rows if row["player_id"] == player]
    identified = [row for row in rows if row["decision"] == "yes"]
    manual = bool(payload.get('manual_review'))
    notes = ([
        '本批悍跳归属与成功结果采用用户逐局人工复核；未选中的座位按该局明确名单处理。',
        '用户明确选中的混血儿按对应记录纳入，不扩展其他赛季的默认统计范围。',
        '人工成功结果优先于自动规则计算；暂定结果保留原备注和待核标记。',
        '成功率为成功数除以成功与失败数之和，结果待定不进入分母。',
    ] if manual else BLUFF_METHODOLOGY + (S23_VIDEO_METHODOLOGY if season == 'S23' else []))
    return {
        "release_id": release["id"], "analytics_version": ANALYTICS_VERSION,
        "season": season, "status": status, "player": player,
        "manual_review": manual,
        "summary": {"games": len(snapshots), "wolf_appearances": sum(not row['manual_included'] for row in rows),
                    "manual_included_appearances": sum(row['manual_included'] for row in rows),
                    "identified_bluffs": len(identified),
                    "successes": sum(row["success"] is True for row in identified),
                    "pending": sum(row["requires_user_review"] for row in rows),
                    "assistant_pending":sum(row['assistant_pending'] for row in rows),
                    "reviewed_games":payload.get('summary',{}).get('manual_reviewed_games',
                        payload.get('summary',{}).get('independently_rechecked_games'))},
        "items": ([row for row in rows if row["requires_user_review"]] if status == "pending" else
                  [row for row in rows if row['assistant_pending']] if status=='assistant_pending' else rows),
        "notes": notes,
        "inference_version": payload.get("inference_version"),
        "bluff_data_source": "database",
    }


@app.get("/api/v1/stats", response_model=Stats)
def stats(season: str | None = Query(default=None, max_length=32),
          season_start: str | None = Query(default=None, max_length=32),
          season_end: str | None = Query(default=None, max_length=32),
          conn=Depends(connection_dependency)):
    release = _release(conn)
    available_seasons = _available_seasons(conn, release["id"])

    # Preserve the old single-season query, including its empty-result behavior
    # for a season that is not present in the active release.
    if season is not None and season_start is None and season_end is None:
        resolved_start = resolved_end = season
        selected_seasons = [season] if season in available_seasons else []
    elif season_start is None and season_end is None:
        # The data page defaults to the first published season through latest.
        if available_seasons:
            resolved_start, resolved_end, selected_seasons = _player_season_range(
                available_seasons, "S22", "S22", "latest",
            )
        else:
            resolved_start = resolved_end = "S22"
            selected_seasons = []
    else:
        resolved_start, resolved_end, selected_seasons = _player_season_range(
            available_seasons, season or "S22", season_start, season_end,
        )

    rows = [snapshot for selected_season in selected_seasons
            for snapshot in _scope_snapshots(conn, release["id"], selected_season)]
    if not rows:
        return {"release_id": release["id"], "game_count": 0, "roles": [], "boards": [],
                "players": [], "methodology": ["没有符合赛季筛选条件的正式对局。"],
                "scope": {"season": resolved_end, "season_start": resolved_start,
                          "season_end": resolved_end, "seasons": selected_seasons,
                          "phase": "all", "games": 0},
                "available_seasons": available_seasons}
    role_counts: Counter[str] = Counter()
    board_counts: dict[str, dict] = {}
    player_data: dict[str, dict] = {}
    for snapshot in rows:
        winner = snapshot.get("winner")
        board_info = snapshot.get("board") or {}
        board_code = board_info.get("code") or snapshot.get("board_code") or ""
        board_name = board_info.get("name") or snapshot.get("board_name") or board_code
        board = board_counts.setdefault(board_code, {
            "code": board_code, "name": board_name, "games": 0,
            "good_wins": 0, "werewolf_wins": 0, "unknown": 0,
        })
        board["games"] += 1
        if winner == "good":
            board["good_wins"] += 1
        elif winner == "werewolf":
            board["werewolf_wins"] += 1
        else:
            board["unknown"] += 1
        for seat in snapshot.get("seats", []):
            role = seat.get("role") or "身份未知"
            role_counts[role] += 1
            person_id = seat.get("person_id") or ""
            player = player_data.setdefault(person_id, {
                "id": person_id, "name": seat.get("name") or "未知选手", "appearances": 0,
                "roles": Counter(),
            })
            player["appearances"] += 1
            player["roles"][role] += 1
    player_summaries = [
        {"id": player["id"], "name": player["name"], "appearances": player["appearances"],
         "roles": [{"role": role, "count": count} for role, count in sorted(player["roles"].items())]}
        for player in player_data.values()
    ]
    player_summaries.sort(key=lambda item: (-item["appearances"], item["name"], item["id"]))
    return {
        "release_id": release["id"], "game_count": len(rows),
        "roles": [{"role": role, "count": count} for role, count in sorted(role_counts.items())],
        "boards": sorted(board_counts.values(), key=lambda item: (-item["games"], item["name"])),
        "players": player_summaries,
        "methodology": [
            "个人胜率、出场率、上警率与投票指标统一按整季统计，包含决赛周。",
            "整季积分包含全部正式对局；决赛周另设冠军积分榜，只累计该周积分。狼人胜+1.5，好人胜+1，输-1。",
            "混血儿按榜样阵营计算个人胜负与指标；零有效样本的比例显示为暂无样本。",
            "胜负按整局好人或狼人阵营记录汇总；未记录胜方与平局计入 unknown。",
            "投票记录为空表示档案没有票型，不能据此推断为零票。",
        ],
        "scope": {"season": resolved_end, "season_start": resolved_start,
                  "season_end": resolved_end, "seasons": selected_seasons,
                  "phase": "all", "games": len(rows)},
        "available_seasons": available_seasons,
    }


@app.get("/api/v1/releases", response_model=Releases)
def releases(conn=Depends(connection_dependency)):
    rows = conn.execute(
        "SELECT r.id,r.published_at,r.game_count,r.source_hash,(a.release_id IS NOT NULL) AS active "
        "FROM releases r LEFT JOIN active_release a ON a.release_id=r.id "
        "ORDER BY r.published_at DESC,r.id"
    ).fetchall()
    return {"items": rows}
