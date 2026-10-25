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
from website.api.bluffs import METHODOLOGY as BLUFF_METHODOLOGY, aggregate_bluffs, review_items
from website.api.bluff_store import read_review
from website.api.game_presentation import build_game_presentation


app = FastAPI(title="Masters archive API", version="1.0.0", debug=False)
ANALYTICS_VERSION = 6
SEASON_CATALOG = json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))


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
    presentation: dict[str, Any] = Field(default_factory=dict)
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
        " ORDER BY g.event_date DESC, g.game_number NULLS LAST, g.id LIMIT %s OFFSET %s",
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
    return {**snapshot, "presentation": build_game_presentation(snapshot)}


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
                  phase: Literal["all", "regular", "finals_week"] = "all",
                  conn=Depends(connection_dependency)):
    release = _release(conn)
    player = conn.execute(
        "SELECT id,name FROM players WHERE release_id=%s AND id=%s",
        (release["id"], player_id),
    ).fetchone()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    snapshots = _scope_snapshots(conn, release["id"], season)
    player_games = [snapshot for snapshot in snapshots
                    if any(seat.get("person_id") == player_id for seat in snapshot.get("seats", []))]
    player_games.sort(key=lambda snapshot: (
        snapshot.get("game_number") is None,
        snapshot.get("game_number") if snapshot.get("game_number") is not None else 0,
        snapshot.get("id", ""),
    ))
    player_games.sort(key=lambda snapshot: snapshot.get("date", ""), reverse=True)
    board_counts: Counter[tuple[str, str]] = Counter(
        ((snapshot.get("board") or {}).get("code", ""), (snapshot.get("board") or {}).get("name", ""))
        for snapshot in player_games
    )
    boards = [{"code": code, "name": name, "count": count}
              for (code, name), count in sorted(board_counts.items(), key=lambda row: (-row[1], row[0][1]))]
    stats = compute_player_stats(player_id, snapshots, season=season, name=player["name"])
    bluff_payload = read_review(conn, release["id"], season)
    stats.update(aggregate_bluffs(snapshots, bluff_payload).get(player_id, {}))
    roles = [{"role": role["role"], "count": role["appearances"]} for role in stats["roles"]]
    return {**player, "appearances": stats["appearances"], "roles": roles,
            "photo": photo_for(player["name"], season),
            "boards": boards, "games": [_summary(snapshot) for snapshot in player_games],
            "release_id": release["id"], "stats": stats,
            "bluff_data_source": "database", "bluff_inference_version": bluff_payload.get("inference_version"),
            "scope": {"season": season, "phase": "all", "games": len(snapshots)},
            "available_seasons": _available_seasons(conn, release["id"])}


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
        "notes": analytics_notes(season_snapshots, season=season, phase=phase) + BLUFF_METHODOLOGY,
    }


@app.get("/api/v1/bluff-review")
def bluff_review(season: str = Query(default="S22", max_length=20),
                 status: Literal["all", "pending"] = "pending",
                 player: str = Query(default="", max_length=100),
                 conn=Depends(connection_dependency)):
    release = _release(conn)
    snapshots = _scope_snapshots(conn, release["id"], season, "all")
    payload = read_review(conn, release["id"], season)
    rows = review_items(snapshots, payload)
    if player:
        rows = [row for row in rows if row["player_id"] == player]
    identified = [row for row in rows if row["decision"] == "yes"]
    return {
        "release_id": release["id"], "analytics_version": ANALYTICS_VERSION,
        "season": season, "status": status, "player": player,
        "summary": {"games": len(snapshots), "wolf_appearances": len(rows),
                    "identified_bluffs": len(identified),
                    "successes": sum(row["success"] is True for row in identified),
                    "pending": sum(row["needs_review"] for row in rows)},
        "items": [row for row in rows if row["needs_review"]] if status == "pending" else rows,
        "notes": BLUFF_METHODOLOGY,
        "inference_version": payload.get("inference_version"),
        "bluff_data_source": "database",
    }


@app.get("/api/v1/stats", response_model=Stats)
def stats(season: str = Query(default="S22", max_length=32), conn=Depends(connection_dependency)):
    release = _release(conn)
    rows = conn.execute(
        "SELECT id,board_code,board_name,winner,snapshot FROM games WHERE release_id=%s AND season=%s "
        "ORDER BY event_date,id", (release["id"], season)
    ).fetchall()
    if not rows:
        return {"release_id": release["id"], "game_count": 0, "roles": [], "boards": [],
                "players": [], "methodology": ["没有符合赛季筛选条件的正式对局。"]}
    role_counts: Counter[str] = Counter()
    board_counts: dict[str, dict] = {}
    player_data: dict[str, dict] = {}
    for row in rows:
        winner = row["winner"]
        board = board_counts.setdefault(row["board_code"], {
            "code": row["board_code"], "name": row["board_name"], "games": 0,
            "good_wins": 0, "werewolf_wins": 0, "unknown": 0,
        })
        board["games"] += 1
        if winner == "good":
            board["good_wins"] += 1
        elif winner == "werewolf":
            board["werewolf_wins"] += 1
        else:
            board["unknown"] += 1
        for seat in row["snapshot"]["seats"]:
            role = seat["role"] or "身份未知"
            role_counts[role] += 1
            player = player_data.setdefault(seat["person_id"], {
                "id": seat["person_id"], "name": seat["name"], "appearances": 0, "roles": Counter(),
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
    }


@app.get("/api/v1/releases", response_model=Releases)
def releases(conn=Depends(connection_dependency)):
    rows = conn.execute(
        "SELECT r.id,r.published_at,r.game_count,r.source_hash,(a.release_id IS NOT NULL) AS active "
        "FROM releases r LEFT JOIN active_release a ON a.release_id=r.id "
        "ORDER BY r.published_at DESC,r.id"
    ).fetchall()
    return {"items": rows}
