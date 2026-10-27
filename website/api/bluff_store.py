"""Versioned PostgreSQL storage for reviewed bluff records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from . import bluffs, publisher


class BluffReviewError(publisher.PublishError):
    """A bluff review cannot be safely attached to the active game release."""


_DECISIONS = {"yes", "no", "uncertain"}
_VERIFICATION_STATUSES = {
    "assistant_inferred", "user_confirmed", "user_uncertain", "user_comment",
}
_CLAIMED_ROLES = {"预言家", "通灵师"}


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _as_object(value: Any, label: str) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise BluffReviewError(f"{label}不是有效 JSON") from exc
    if not isinstance(value, dict):
        raise BluffReviewError(f"{label}必须是 JSON 对象")
    return value


def _expected_game_count(season: str) -> int | None:
    path = publisher.PACKAGE_ROOT / "config" / f"{season}_formal_rules.json"
    if not path.is_file():
        return None
    try:
        rules = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BluffReviewError("赛季正式范围配置无法读取") from exc
    count = (rules.get("scope") or {}).get("scored_total")
    return count if type(count) is int and count >= 0 else None


def _validate_review(games: list[dict], payload: dict, season: str,
                     expected_game_count: int | None = None) -> tuple[list[dict], dict[str, Any]]:
    """Validate exact game and wolf-seat coverage against immutable snapshots."""
    if payload.get("schema_version") != 1 or payload.get("season") != season:
        raise BluffReviewError("悍跳复核版本或赛季与发布目标不匹配")
    inference_version = payload.get("inference_version")
    if not isinstance(inference_version, str) or not inference_version.strip():
        raise BluffReviewError("悍跳复核缺少推断版本")
    payload_games = payload.get("games")
    if not isinstance(payload_games, list):
        raise BluffReviewError("悍跳复核 games 必须是数组")
    if expected_game_count is not None and len(games) != expected_game_count:
        raise BluffReviewError("活动发布批次不符合该赛季正式游戏范围")

    by_id: dict[str, dict] = {}
    for game in games:
        game_id = game.get("id", game.get("slug"))
        if not isinstance(game_id, str) or not game_id:
            raise BluffReviewError("发布快照缺少对局 ID")
        if game_id in by_id:
            raise BluffReviewError("活动发布批次含有重复对局 ID")
        if game.get("season") != season:
            raise BluffReviewError("活动发布批次含有其他赛季的对局")
        by_id[game_id] = game
    if len(games) != len(by_id):
        raise BluffReviewError("发布批次对局范围不唯一")

    payload_by_id: dict[str, dict] = {}
    for reviewed_game in payload_games:
        if not isinstance(reviewed_game, dict):
            raise BluffReviewError("悍跳复核包含无效对局记录")
        game_id = reviewed_game.get("game_id")
        if not isinstance(game_id, str) or game_id in payload_by_id:
            raise BluffReviewError("悍跳复核包含缺失或重复的对局 ID")
        payload_by_id[game_id] = reviewed_game
    if set(payload_by_id) != set(by_id):
        raise BluffReviewError("悍跳复核必须精确覆盖活动发布批次的全部对局")

    wolf_count = 0
    yes_count = 0
    uncertain_count = 0
    user_confirmed_count = 0
    for game_id, game in by_id.items():
        reviewed_game = payload_by_id[game_id]
        fingerprint = bluffs.source_fingerprint(game)
        if reviewed_game.get("source_fingerprint") != fingerprint:
            raise BluffReviewError(f"对局 {game_id} 的来源指纹已过期")
        source = game.get("source") or {}
        if reviewed_game.get("bvid") != source.get("bvid"):
            raise BluffReviewError(f"对局 {game_id} 的视频编号与发布快照不一致")
        result_review=reviewed_game.get('result_review')
        if result_review is not None:
            if (season!='S23' or not isinstance(result_review,dict)
                    or result_review.get('badge')!='lost' or not result_review.get('note')
                    or not isinstance(result_review.get('evidence'),list) or not result_review['evidence']
                    or any(not isinstance(e,dict) or not e.get('text') for e in result_review['evidence'])
                    or reviewed_game.get('coverage')!='first_day_video_and_transcript'):
                raise BluffReviewError('补充警徽结果缺少已完成复核的定位证据')
            if any(bluffs._badge_result(game,s['seat'])[0] is True for s in game.get('seats',[])):
                raise BluffReviewError('补充流徽结果与正式竞选当选结果冲突')

        assessments = reviewed_game.get("assessments")
        if not isinstance(assessments, list):
            raise BluffReviewError(f"对局 {game_id} 的悍跳判断必须是数组")
        by_seat: dict[int, dict] = {}
        for assessment in assessments:
            if not isinstance(assessment, dict) or type(assessment.get("seat")) is not int:
                raise BluffReviewError(f"对局 {game_id} 包含无效的座位判断")
            seat = assessment["seat"]
            if seat in by_seat:
                raise BluffReviewError(f"对局 {game_id} 的狼人座位判断重复")
            by_seat[seat] = assessment

        wolf_seats = {
            seat["seat"]: seat for seat in game.get("seats", [])
            if bluffs.physical_wolf(game, seat)
        }
        if set(by_seat) != set(wolf_seats):
            raise BluffReviewError(f"对局 {game_id} 的狼人座位判断不完整或包含非狼人")
        wolf_count += len(wolf_seats)
        for seat_number, seat in wolf_seats.items():
            assessment = by_seat[seat_number]
            if assessment.get("name") != seat.get("name"):
                raise BluffReviewError(f"对局 {game_id} {seat_number} 号选手姓名已变化")
            if assessment.get("physical_role") != seat.get("role"):
                raise BluffReviewError(f"对局 {game_id} {seat_number} 号底牌身份已变化")
            if not isinstance(seat.get("person_id"), str) or not seat["person_id"]:
                raise BluffReviewError(f"对局 {game_id} {seat_number} 号缺少发布人物 ID")
            decision = assessment.get("decision")
            if not isinstance(decision, str) or decision not in _DECISIONS:
                raise BluffReviewError(f"对局 {game_id} {seat_number} 号判断无效")
            verification = assessment.get("verification_status", "assistant_inferred")
            if not isinstance(verification, str) or verification not in _VERIFICATION_STATUSES:
                raise BluffReviewError(f"对局 {game_id} {seat_number} 号核验状态无效")
            claimed_role = assessment.get("claimed_role")
            has_claimed_role = isinstance(claimed_role, str) and claimed_role in _CLAIMED_ROLES
            if decision == "yes" and not has_claimed_role:
                if verification != "user_confirmed" or claimed_role is not None:
                    raise BluffReviewError(f"对局 {game_id} {seat_number} 号悍跳身份无效或缺失")
            claim_day = assessment.get("claim_day")
            valid_claim_day = (claim_day is None or (type(claim_day) is int and claim_day in (1, 2))
                               or claim_day == "later")
            if not valid_claim_day:
                raise BluffReviewError(f"对局 {game_id} {seat_number} 号起跳天数无效")
            actual_day=assessment.get('actual_claim_day')
            if actual_day is not None and (claim_day!='later' or type(actual_day) is not int or actual_day<3):
                raise BluffReviewError(f"对局 {game_id} {seat_number} 号后日起跳天数无效")
            if verification == "user_uncertain" and decision != "uncertain":
                raise BluffReviewError(f"对局 {game_id} {seat_number} 号用户复核状态与结论不匹配")
            evidence = assessment.get("evidence", [])
            if not isinstance(evidence, list) or any(not isinstance(row, dict) for row in evidence):
                raise BluffReviewError(f"对局 {game_id} {seat_number} 号证据格式无效")
            if decision == "yes" and not evidence and verification != "user_confirmed":
                raise BluffReviewError(f"对局 {game_id} {seat_number} 号悍跳判断缺少证据")
            yes_count += int(decision == "yes")
            uncertain_count += int(decision == "uncertain")
            user_confirmed_count += int(verification == "user_confirmed")

    try:
        items = bluffs.review_items(games, payload)
        stats = bluffs.aggregate_bluffs(games, payload)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise BluffReviewError("悍跳复核无法依据当前发布快照计算") from exc
    if len(items) != wolf_count:
        raise BluffReviewError("悍跳明细数量与发布批次狼人座位数不一致")

    seat_by_key = {
        (game["id"], seat["seat"]): seat
        for game in games for seat in game.get("seats", []) if bluffs.physical_wolf(game, seat)
    }
    payload_assessment_by_key = {
        (game_id, assessment["seat"]): assessment
        for game_id, reviewed_game in payload_by_id.items()
        for assessment in reviewed_game["assessments"]
    }
    for item in items:
        key = (item["game_id"], item["seat"])
        assessment = payload_assessment_by_key.get(key)
        seat = seat_by_key.get(key)
        if assessment is None or seat is None:
            raise BluffReviewError("计算出的狼人明细无法关联至来源座位")
        if item["decision"] != assessment["decision"]:
            raise BluffReviewError(f"对局 {key[0]} {key[1]} 号判断未通过现有复核规则")
        if item["name"] != seat["name"] or item["physical_role"] != seat.get("role"):
            raise BluffReviewError(f"对局 {key[0]} {key[1]} 号姓名或底牌身份不一致")
        if item["player_id"] != seat.get("person_id"):
            raise BluffReviewError(f"对局 {key[0]} {key[1]} 号人物 ID 与发布快照不一致")
        if (assessment["decision"] == "yes" and assessment.get("claimed_role") is None
                and assessment.get("verification_status") == "user_confirmed"):
            item["needs_review"] = True
            question = "用户已确认悍跳，所跳身份尚待补充"
            if question not in item["review_questions"]:
                item["review_questions"].append(question)

    aggregate_yes = sum(row["bluff_count"] for row in stats.values())
    aggregate_pending = sum(row["bluff_pending_games"] for row in stats.values())
    aggregate_successes = sum(row["bluff_success_rate"]["numerator"] for row in stats.values())
    item_successes = sum(item["success"] is True for item in items if item["decision"] == "yes")
    if (aggregate_yes, aggregate_pending, aggregate_successes) != (yes_count, uncertain_count, item_successes):
        raise BluffReviewError("悍跳汇总与狼人明细计算结果不一致")

    summary = {
        "game_count": len(games),
        "wolf_count": wolf_count,
        "yes_count": yes_count,
        "success_count": item_successes,
        "pending_count": sum(item["needs_review"] for item in items),
        "user_confirmed_count": user_confirmed_count,
    }
    return items, summary


def _active_release(conn, season: str, *, lock: bool) -> dict:
    suffix = " FOR UPDATE OF ar" if lock else ""
    row = conn.execute(
        "SELECT r.id, r.season, r.game_count FROM active_release ar "
        "JOIN releases r ON r.id = ar.release_id WHERE ar.singleton = true" + suffix
    ).fetchone()
    if not row:
        raise BluffReviewError("网站数据库尚无活动游戏发布批次")
    count = conn.execute(
        "SELECT count(*) AS count FROM games WHERE release_id = %s AND season = %s",
        (row["id"], season),
    ).fetchone()["count"]
    if not count:
        raise BluffReviewError("活动游戏发布批次与悍跳复核赛季不一致")
    return {**row, "release_game_count": row["game_count"], "game_count": count}


def _published_games(conn, release: dict, season: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, snapshot FROM games WHERE release_id = %s AND season = %s ORDER BY id",
        (release["id"], season),
    ).fetchall()
    games = []
    for row in rows:
        game = _as_object(row["snapshot"], "网站对局快照")
        if game.get("id") != row["id"] or game.get("season") != season:
            raise BluffReviewError("网站对局快照 ID 或赛季与索引不一致")
        games.append(game)
    if len(games) != release["game_count"]:
        raise BluffReviewError("活动发布批次局数与数据库快照数量不一致")
    return games


def _load_payload(season: str, path: Path | None) -> dict:
    source = path or (bluffs.ASSET_ROOT / f"{season}.json")
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BluffReviewError("悍跳复核 JSON 无法读取") from exc
    if not isinstance(value, dict):
        raise BluffReviewError("悍跳复核 JSON 顶层必须是对象")
    return value


def read_review(conn, release_id: str, season: str) -> dict:
    """Read the active DB review for this release; an unpublished review is empty."""
    row = conn.execute(
        "SELECT p.payload FROM active_bluff_reviews a "
        "JOIN bluff_review_publications p "
        "ON p.id = a.publication_id AND p.release_id = a.release_id AND p.season = a.season "
        "WHERE a.release_id = %s AND a.season = %s",
        (release_id, season),
    ).fetchone()
    if not row:
        return {"games": []}
    payload = _as_object(row["payload"], "已发布悍跳复核")
    if payload.get("season") != season:
        raise BluffReviewError("已发布悍跳复核的赛季与查询条件不一致")
    return payload


def publish_review(season: str = "S22", path: Path | None = None, check: bool = False) -> dict:
    """Validate and atomically publish a review against the current active release."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", season):
        raise BluffReviewError("赛季参数格式不合法")
    payload = _load_payload(season, path)
    payload_hash = _sha256(_canonical_json(payload))
    inference_version = payload.get("inference_version")
    conn = publisher._connect("masters_web")
    try:
        with conn.transaction():
            if not check:
                publisher._create_schema(conn)
            release = _active_release(conn, season, lock=not check)
            expected_count = _expected_game_count(season)
            if expected_count is not None and release["game_count"] != expected_count:
                raise BluffReviewError("活动发布批次未完整覆盖赛季正式范围")
            games = _published_games(conn, release, season)
            items, summary = _validate_review(games, payload, season, expected_count)

            publication_id = "bluff-" + _sha256(_canonical_json({
                "release_id": release["id"], "season": season,
                "inference_version": inference_version, "payload_hash": payload_hash,
            }))
            result = {
                "season": season,
                "release_id": release["id"],
                "publication_id": publication_id,
                "payload_hash": payload_hash,
                **summary,
                "checked": bool(check),
                "published": False,
                "idempotent": False,
            }
            if check:
                return result

            previous = conn.execute(
                "SELECT publication_id FROM active_bluff_reviews "
                "WHERE release_id = %s AND season = %s FOR UPDATE",
                (release["id"], season),
            ).fetchone()
            existing = conn.execute(
                "SELECT payload_hash FROM bluff_review_publications WHERE id = %s",
                (publication_id,),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise BluffReviewError("相同悍跳版本 ID 对应了不同内容")
                count_row = conn.execute(
                    "SELECT count(*) AS item_count FROM bluff_review_items WHERE publication_id = %s",
                    (publication_id,),
                ).fetchone()
                if count_row["item_count"] != len(items):
                    raise BluffReviewError("已保存的悍跳版本明细数量不完整")
            else:
                conn.execute(
                    "INSERT INTO bluff_review_publications "
                    "(id, release_id, season, inference_version, payload_hash, payload) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (publication_id, release["id"], season, inference_version, payload_hash, Jsonb(payload)),
                )
                for item in items:
                    conn.execute(
                        "INSERT INTO bluff_review_items "
                        "(publication_id, release_id, game_id, seat, player_id, decision, success, "
                        "verification_status, needs_review, record) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (publication_id, release["id"], item["game_id"], item["seat"], item["player_id"],
                         item["decision"], item["success"], item["verification_status"],
                         item["needs_review"], Jsonb(item)),
                    )

            conn.execute(
                "INSERT INTO active_bluff_reviews(release_id, season, publication_id) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT(release_id, season) DO UPDATE SET publication_id = EXCLUDED.publication_id",
                (release["id"], season, publication_id),
            )
            result["published"] = True
            result["idempotent"] = bool(existing and previous
                                         and previous["publication_id"] == publication_id)
            return result
    finally:
        conn.close()
