"""Build public website responses from the final, versioned game JSON files."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.game_inference import build_game_presentation
from scripts.game_time import display_time_text
from scripts.game_timeline import build_game_timeline
from scripts.role_constraints import puppet_target
from website.api.analytics import (
    PlayerStatsScope,
    analytics_notes,
    build_leaderboard,
    compute_player_summaries,
    effective_faction,
    role_label,
    scope_games,
)
from website.api.bluffs import aggregate_bluffs
from website.api.photos import photo_for


ROOT = Path(__file__).resolve().parents[1]
ANALYTICS_VERSION = 22
GAME_SCHEMA_VERSION = 1

STATS_METHODOLOGY = [
    "个人胜率、出场率、上警率与投票指标统一按整季统计，包含决赛周。",
    "整季积分包含全部正式对局；决赛周另设冠军积分榜，只累计该周积分。狼人胜+1.5，好人胜+1，输-1。",
    "混血儿按榜样阵营计算个人胜负与指标；零有效样本的比例显示为暂无样本。",
    "胜负按整局好人或狼人阵营记录汇总；未记录胜方与平局计入 unknown。",
    "投票记录为空表示档案没有票型，不能据此推断为零票。",
]


class PublicDataError(RuntimeError):
    """Canonical game data cannot be used to build public website responses."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json_with_hash(path: Path) -> tuple[dict[str, Any], str]:
    try:
        body = path.read_bytes()
        value = json.loads(body.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicDataError(f"无法读取公开 JSON：{path}") from exc
    if not isinstance(value, dict):
        raise PublicDataError(f"公开 JSON 须为对象：{path}")
    return value, _sha256(body)


def _load_catalog(root: Path) -> tuple[dict[str, dict[str, Any]], str]:
    path = root / "config" / "seasons.json"
    value, digest = _read_json_with_hash(path)
    rows = value.get("seasons")
    if not isinstance(rows, dict):
        raise PublicDataError("config/seasons.json 缺少 seasons 对象")
    catalog = {}
    for season, row in rows.items():
        if not isinstance(season, str) or not isinstance(row, dict):
            raise PublicDataError("config/seasons.json 含有无效赛季")
        catalog[season] = row
    return catalog, digest


def _load_games(root: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    games_root = root / "data" / "games"
    if not games_root.is_dir():
        raise PublicDataError(f"找不到最终对局目录：{games_root}")
    games: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    seen_ids: set[str] = set()
    for path in sorted(games_root.rglob("game.json")):
        relative = path.relative_to(root).as_posix()
        game, digest = _read_json_with_hash(path)
        game_id, season = game.get("id"), game.get("season")
        if (game.get("schema_version") != GAME_SCHEMA_VERSION
                or not isinstance(game_id, str) or not game_id
                or not isinstance(season, str) or path.parent.parent.name != season
                or not isinstance(game.get("seats"), list)
                or not isinstance(game.get("rounds"), list)):
            raise PublicDataError(f"最终对局格式或路径无效：{relative}")
        if game_id in seen_ids:
            raise PublicDataError(f"最终对局 ID 重复：{game_id}")
        seen_ids.add(game_id)
        hashes[relative] = digest
        games.append(game)
    if not games:
        raise PublicDataError("data/games 下没有最终 game.json")
    return games, hashes


def _source_fingerprint(root: Path, game_hashes: dict[str, str], catalog_hash: str) -> str:
    people_path = root / "website" / "assets" / "people.json"
    people_hash = _sha256(people_path.read_bytes()) if people_path.is_file() else None
    return _sha256(_canonical_json({
        "games": game_hashes,
        "seasons": catalog_hash,
        "people": people_hash,
    }))


def _ranges(seasons: list[str]) -> list[dict[str, Any]]:
    return [
        {"start": seasons[start], "end": seasons[end], "seasons": seasons[start:end + 1]}
        for start in range(len(seasons)) for end in range(start, len(seasons))
    ]


def _summary(game: dict[str, Any]) -> dict[str, Any]:
    fields = ("id", "season", "date", "phase", "game_number", "board", "winner", "players",
              "ballot_count", "round_count")
    source = game.get("source") or {}
    board = game.get("board") or {}
    names = [seat.get("name", "") for seat in game.get("seats", [])]
    return {**{key: game[key] for key in fields},
            "search_text": " ".join([game.get("id", ""), source.get("bvid", ""),
                                      game.get("date", ""), board.get("name", ""), " ".join(names)])}


def _resolved_game(source: dict[str, Any], release_id: str) -> dict[str, Any]:
    """Apply the same personal-faction and role-label projection as the old API."""
    game = {key: value for key, value in source.items()
            if key not in {"schema_version", "bluffs", "bluff_review_available"}}
    seats = []
    by_number = {}
    notes = list(game.get("data_notes", []))
    for seat in game.get("seats", []):
        faction = effective_faction(game, seat)
        inferred = (seat.get("faction") is None and not (seat.get("role") or "").startswith("盗宝")
                    and faction is not None)
        resolved = {**seat, "role_label": role_label(game, seat), "faction": faction,
                    "is_puppet": seat.get("seat") == puppet_target(game), "faction_inferred": inferred}
        seats.append(resolved)
        by_number[seat.get("seat")] = resolved
    if seats and all(seat["faction"] is not None for seat in seats):
        notes = [note for note in notes if note != "部分座位阵营待核，保留未知值。"]
    for seat in seats:
        if seat["faction_inferred"]:
            notes.append(f"{seat['seat']}号 {seat['name']}为混血儿，个人阵营按已记录榜样确定。")
    players = [
        {**player,
         "faction": by_number[player["seat"]]["faction"],
         "role_label": by_number[player["seat"]]["role_label"]}
        for player in game.get("players", [])
    ]
    game.update(seats=seats, players=players, data_notes=notes, release_id=release_id)
    game.setdefault("rules_state", {})
    game.setdefault("terminal_observation", None)
    game.setdefault("terminal_events", None)
    game.setdefault("commentators", [])
    game.setdefault("referee", None)
    game.setdefault("data_notes", [])
    game["search_text"] = _summary(game)["search_text"]
    presentation = build_game_presentation(game)
    for round_ in presentation.get("rounds", []):
        for phase in ("night", "day"):
            for event in round_.get(phase, []):
                if isinstance(event.get("inference_note"), str):
                    event["inference_note"] = display_time_text(event["inference_note"])
    for event in (presentation.get("terminal") or {}).get("events", []):
        if isinstance(event.get("inference_note"), str):
            event["inference_note"] = display_time_text(event["inference_note"])
    game["presentation"] = presentation
    game["timeline"] = build_game_timeline(game)
    return game


def _game_order_recent(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = sorted(games, key=lambda game: game["id"])
    result = sorted(result, key=lambda game: (
        game.get("game_number") is not None,
        game.get("game_number") if game.get("game_number") is not None else 0,
    ), reverse=True)
    return sorted(result, key=lambda game: game.get("date", ""), reverse=True)


def _player_detail(player_id: str, name: str, games: list[dict[str, Any]],
                   seasons: list[str], release_id: str, stats_scope: PlayerStatsScope,
                   all_seasons: list[str], public_games: dict[str, dict[str, Any]]) -> dict[str, Any]:
    profile_games = [game for game in games
                     if any(seat.get("person_id") == player_id for seat in game.get("seats", []))]
    profile_games = sorted(profile_games, key=lambda game: game["id"])
    profile_games = sorted(profile_games, key=lambda game: (
        game.get("game_number") is None,
        -game.get("game_number") if game.get("game_number") is not None else 0,
    ))
    profile_games = sorted(profile_games, key=lambda game: game.get("date", ""), reverse=True)
    board_counts = Counter(((game.get("board") or {}).get("code", ""),
                            (game.get("board") or {}).get("name", "")) for game in profile_games)
    boards = [{"code": code, "name": board_name, "count": count}
              for (code, board_name), count in sorted(board_counts.items(),
                                                      key=lambda item: (-item[1], item[0][1]))]
    selected_seasons = [season for season in seasons
                        if any(game.get("season") == season for game in games)]
    start, end = selected_seasons[0], selected_seasons[-1]
    stats = stats_scope.for_player(player_id, name=name)
    roles = [{"role": role["role"], "count": role["appearances"]} for role in stats["roles"]]
    return {
        "id": player_id, "name": name, "appearances": stats["appearances"], "roles": roles,
        "photo": photo_for(name, end), "boards": boards,
        "games": [_summary(public_games[game["id"]]) for game in profile_games],
        "release_id": release_id, "analytics_version": ANALYTICS_VERSION, "stats": stats,
        "scope": {"season": end, "season_start": start, "season_end": end,
                  "seasons": selected_seasons, "minimum_appearances": 0,
                  "phase": "all", "games": len(games)},
        "available_seasons": all_seasons,
    }


def build_public_data(root: Path | str = ROOT) -> dict[str, Any]:
    """Return every JSON response consumed by the current static website."""
    root = Path(root).resolve()
    catalog, catalog_hash = _load_catalog(root)
    source_games, game_hashes = _load_games(root)
    seasons = sorted({game["season"] for game in source_games})
    unknown = [season for season in seasons if season not in catalog]
    if unknown:
        raise PublicDataError("config/seasons.json 缺少正式对局赛季：" + ", ".join(unknown))
    source_hash = _source_fingerprint(root, game_hashes, catalog_hash)
    release_id = f"direct-{source_hash[:24]}"
    release = {"id": release_id, "published_at": None, "game_count": len(source_games),
               "source_hash": source_hash}
    games = source_games
    public_games = {game["id"]: _resolved_game(game, release_id) for game in games}
    games_by_season = {season: [game for game in games if game["season"] == season]
                       for season in seasons}
    season_rows = []
    for season in seasons:
        rows = games_by_season[season]
        phases = sorted({game["phase"] for game in rows})
        season_rows.append({"season": season, "game_count": len(rows), "phases": phases})
    ranges = _ranges(seasons)

    recent = _game_order_recent(games)
    game_summaries = [_summary(public_games[game["id"]]) for game in recent]
    date_counts = Counter(game["date"] for game in games)
    board_counts: dict[tuple[str, str], int] = Counter(
        ((game.get("board") or {}).get("code", ""), (game.get("board") or {}).get("name", ""))
        for game in games
    )
    season_overview = []
    for season in seasons:
        rows = games_by_season[season]
        season_overview.append({
            "id": season, "name": catalog[season].get("name", season),
            "games": len(rows), "days": len({game["date"] for game in rows}),
        })
    overview = {
        "release": release,
        "totals": {"games": len(games), "days": len(date_counts),
                   "players": len({seat.get("person_id") for game in games
                                   for seat in game.get("seats", []) if seat.get("person_id") is not None}),
                   "ballots": sum(len((game.get("voting") or {}).get("ballots", [])) for game in games),
                   "votes": sum(len(ballot.get("votes", [])) for game in games
                                for ballot in (game.get("voting") or {}).get("ballots", []))},
        "seasons": season_overview,
        "boards": [{"code": code, "name": name, "games": count}
                   for (code, name), count in sorted(board_counts.items(), key=lambda item: (-item[1], item[0][1]))],
        "recent_games": game_summaries[:12],
    }
    releases = {"items": [{**release, "active": True}]}

    player_summaries: dict[str, dict[str, Any]] = {}
    players_by_season: dict[str, dict[str, Any]] = {}
    for season in seasons:
        items = compute_player_summaries(games_by_season[season], season=season)
        for item in items:
            item["photo"] = photo_for(item["name"], season)
            player_summaries[item["id"]] = item["name"]
        players_by_season[season] = {
            "analytics_version": ANALYTICS_VERSION, "items": items,
            "total": len(items), "page": 1, "page_size": max(1, len(items)),
            "release_id": release_id,
        }

    # The old exporter used the latest season's player-card spelling in the
    # shared index while profile names remain the first spelling in release order.
    index_names = dict(player_summaries)
    first_names: dict[str, str] = {}
    for game in sorted(games, key=lambda row: (row.get("date", ""), row.get("game_number") is None,
                                                row.get("game_number") or 0, row["id"])):
        for seat in game.get("seats", []):
            person_id = seat.get("person_id")
            if person_id is not None:
                first_names.setdefault(str(person_id), seat.get("name") or "")
    index_items = sorted(({"id": player_id, "name": name} for player_id, name in index_names.items()),
                         key=lambda item: (item["name"].casefold(), item["name"], item["id"]))
    player_index = {"release_id": release_id, "seasons": seasons, "items": index_items}

    documents: dict[str, Any] = {
        "overview.json": overview,
        "releases.json": releases,
        "games/index.json": {"release_id": release_id, "total": len(games), "items": game_summaries},
        "players/index.json": player_index,
    }
    documents.update({f"games/{game['id']}.json": public_games[game["id"]] for game in games})
    documents.update({f"players/by-season/{season}.json": page
                      for season, page in players_by_season.items()})

    all_bluff_stats: dict[str, dict[str, Any]] = {}
    for season in seasons:
        all_bluff_stats[season] = aggregate_bluffs(games_by_season[season])

    for interval in ranges:
        start, end = interval["start"], interval["end"]
        selected_games = [game for game in games if game["season"] in interval["seasons"]]
        bluff_stats = aggregate_bluffs(selected_games)
        scope = PlayerStatsScope(selected_games, seasons=interval["seasons"], bluff_stats=bluff_stats)
        range_name = f"{start}--{end}"

        role_counts: Counter[str] = Counter()
        board_stats: dict[str, dict[str, Any]] = {}
        player_rollup: dict[str, dict[str, Any]] = {}
        for game in selected_games:
            winner = game.get("winner")
            board = game.get("board") or {}
            code, name = board.get("code") or "", board.get("name") or board.get("code") or ""
            item = board_stats.setdefault(code, {"code": code, "name": name, "games": 0,
                                                  "good_wins": 0, "werewolf_wins": 0, "unknown": 0})
            item["games"] += 1
            if winner == "good":
                item["good_wins"] += 1
            elif winner == "werewolf":
                item["werewolf_wins"] += 1
            else:
                item["unknown"] += 1
            for seat in game.get("seats", []):
                role = seat.get("role") or "身份未知"
                role_counts[role] += 1
                player_id = seat.get("person_id") or ""
                player = player_rollup.setdefault(player_id, {
                    "id": player_id, "name": seat.get("name") or "未知选手", "appearances": 0,
                    "roles": Counter(),
                })
                player["appearances"] += 1
                player["roles"][role] += 1
        stat_players = [
            {"id": player["id"], "name": player["name"], "appearances": player["appearances"],
             "roles": [{"role": role, "count": count} for role, count in sorted(player["roles"].items())]}
            for player in player_rollup.values()
        ]
        stat_players.sort(key=lambda item: (-item["appearances"], item["name"], item["id"]))
        documents[f"stats/{range_name}.json"] = {
            "analytics_version": ANALYTICS_VERSION, "release_id": release_id,
            "game_count": len(selected_games),
            "roles": [{"role": role, "count": count} for role, count in sorted(role_counts.items())],
            "boards": sorted(board_stats.values(), key=lambda item: (-item["games"], item["name"])),
            "players": stat_players, "methodology": STATS_METHODOLOGY,
            "scope": {"season": end, "season_start": start, "season_end": end,
                      "seasons": interval["seasons"], "phase": "all", "games": len(selected_games)},
            "available_seasons": seasons,
        }
        for player_id, index_name in index_names.items():
            profile = _player_detail(player_id, first_names.get(player_id, index_name),
                                     selected_games, interval["seasons"], release_id,
                                     scope, seasons, public_games)
            documents[f"players/{player_id}/{range_name}.json"] = profile

    for season in seasons:
        season_games = games_by_season[season]
        phase_rows = ["all"] + (["finals_week"] if "finals_week" in next(
            row["phases"] for row in season_rows if row["season"] == season) else [])
        bluff_stats = all_bluff_stats[season]
        for phase in phase_rows:
            leaderboard_items = build_leaderboard(season_games, season=season, phase=phase)
            for item in leaderboard_items:
                item["photo"] = photo_for(item["name"], season)
                item.update(bluff_stats.get(item["id"], {}))
            documents[f"leaderboards/{season}/{phase}.json"] = {
                "release_id": release_id, "analytics_version": ANALYTICS_VERSION,
                "season": season, "phase": phase,
                "season_status": catalog[season].get("status", "unknown"),
                "bluff_data_source": "final_games", "bluff_inference_version": None,
                "game_count": len(scope_games(season_games, season, phase)),
                "pending_games": sum(item["pending_games"] for item in leaderboard_items),
                "scoring": {"werewolf_win": 1.5, "good_win": 1, "loss": -1},
                "items": leaderboard_items,
                "sample_games": [{
                    "game_id": game["id"], "season": game["season"], "date": game["date"],
                    "game_number": game.get("game_number"), "board_name": game["board"]["name"],
                    "roles": {seat["person_id"]: role_label(game, seat)
                              for seat in game.get("seats", []) if seat.get("person_id") is not None},
                } for game in season_games],
                "notes": analytics_notes(season_games, season=season, phase=phase) + [
                    "悍跳统计使用最终对局中的逐局结果；待定归属与成功结果按统计口径排除。"
                ],
            }

    expected_profiles = len(index_names) * len(ranges)
    if len([name for name in documents if name.startswith("players/") and "--" in name]) != expected_profiles:
        raise PublicDataError("选手详情没有覆盖全部赛季区间")
    return {
        "release_id": release_id,
        "source_hash": source_hash,
        "game_hashes": game_hashes,
        "seasons": seasons,
        "season_rows": season_rows,
        "ranges": ranges,
        "release": release,
        "games": games,
        "game_summaries": game_summaries,
        "player_index": player_index,
        "documents": documents,
        "counts": {
            "games": len(games), "players": len(index_names),
            "game_details": len(games), "player_ranges": expected_profiles,
            "stats_ranges": len(ranges),
            "leaderboards": sum(1 + ("finals_week" in row["phases"]) for row in season_rows),
        },
    }


def check_public_data(root: Path | str = ROOT) -> dict[str, Any]:
    """Read-only validation of direct response coverage, scopes, and JSON shape."""
    direct = build_public_data(root)
    documents = direct["documents"]
    release_id = direct["release_id"]
    expected_game_ids = {game["id"] for game in direct["games"]}
    game_index = documents["games/index.json"]
    if (game_index.get("release_id") != release_id or game_index.get("total") != len(expected_game_ids)
            or {row.get("id") for row in game_index.get("items", [])} != expected_game_ids):
        raise PublicDataError("games/index.json 不完整或发布版本不一致")

    details = {name.removeprefix("games/").removesuffix(".json")
               for name in documents if name.startswith("games/") and name.endswith(".json")
               and name != "games/index.json"}
    if details != expected_game_ids:
        raise PublicDataError("对局详情 JSON 未覆盖最终对局清单")
    for game_id in expected_game_ids:
        detail = documents[f"games/{game_id}.json"]
        required = {"id", "release_id", "seats", "rounds", "voting", "endgame", "presentation", "timeline"}
        if (not required.issubset(detail) or detail["id"] != game_id
                or detail["release_id"] != release_id
                or {"schema_version", "bluffs", "bluff_review_available"}.intersection(detail)):
            raise PublicDataError(f"对局详情格式无效：{game_id}")

    player_ids = {row["id"] for row in direct["player_index"]["items"]}
    expected_profiles = {f"players/{player_id}/{item['start']}--{item['end']}.json"
                         for player_id in player_ids for item in direct["ranges"]}
    actual_profiles = {name for name in documents if name.startswith("players/")
                       and name.count("/") == 2 and "--" in PurePosixPath(name).name}
    if actual_profiles != expected_profiles:
        raise PublicDataError("选手详情 JSON 未覆盖全部选手与赛季区间")
    for relative in expected_profiles:
        profile = documents[relative]
        stats = profile.get("stats")
        if (profile.get("release_id") != release_id or not isinstance(stats, dict)
                or not isinstance(stats.get("ranking_boards"), dict)
                or not isinstance(stats.get("ledger"), list)
                or any(key in stats and not isinstance(stats[key], dict)
                       for key in ("bluff_rate", "bluff_success_rate"))):
            raise PublicDataError(f"选手统计 JSON 格式无效：{relative}")

    for interval in direct["ranges"]:
        relative = f"stats/{interval['start']}--{interval['end']}.json"
        stats = documents.get(relative)
        scope = stats.get("scope") if isinstance(stats, dict) else None
        if (stats is None or stats.get("release_id") != release_id or not isinstance(scope, dict)
                or scope.get("seasons") != interval["seasons"]):
            raise PublicDataError(f"赛季统计 JSON 范围无效：{relative}")

    expected_leaderboards = {
        f"leaderboards/{row['season']}/{phase}.json"
        for row in direct["season_rows"]
        for phase in (["all", "finals_week"] if "finals_week" in row["phases"] else ["all"])
    }
    actual_leaderboards = {name for name in documents if name.startswith("leaderboards/")}
    if actual_leaderboards != expected_leaderboards:
        raise PublicDataError("积分榜 JSON 未覆盖各赛季适用的榜单阶段")
    for relative in expected_leaderboards:
        board = documents[relative]
        if board.get("release_id") != release_id or not isinstance(board.get("items"), list):
            raise PublicDataError(f"积分榜 JSON 格式无效：{relative}")

    for relative, value in documents.items():
        try:
            _canonical_json(value)
        except (TypeError, ValueError) as exc:
            raise PublicDataError(f"响应不能编码为 JSON：{relative}") from exc
    return {"state": "passed", "games": len(expected_game_ids), "seasons": direct["seasons"],
            "players": len(player_ids), "ranges_checked": len(direct["ranges"]),
            "leaderboards": len(expected_leaderboards), "release_id": release_id,
            "source_hash": direct["source_hash"]}
