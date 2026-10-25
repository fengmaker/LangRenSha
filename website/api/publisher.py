"""Build and atomically publish immutable public game snapshots."""

from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_ROOT = Path(os.environ.get("MASTERS_SOURCE_ROOT", PACKAGE_ROOT))
PERSON_NAMESPACE = uuid.UUID("5a1e9a41-663d-4dcc-9ce6-f5e75e9efb18")
PUBLICATION_FORMAT_VERSION = 2
STATISTICS_VERSION = 2
BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")
EVENT_FIELDS = (
    "slot", "action", "actor", "targets", "result", "start_seat", "direction",
    "random_point", "speech_scope", "availability", "votes", "effects",
)
EFFECT_FIELDS = ("kind", "intended_target", "dead_seat", "shield_actor")
VOTE_FIELDS = ("round", "voter", "target", "abstained")
REGISTRATION_FIELDS = ("id", "day", "on_police", "off_police")
BALLOT_FIELDS = (
    "id", "day", "kind", "number", "stage", "status", "candidates", "eligible_voters",
    "votes", "tied_candidates", "winner", "unrecorded_voters",
)
INTERRUPTION_FIELDS = ("id", "day", "actor", "reason", "ends_day")
DAY_FIELDS = ("day", "sheriff", "exile")
ENDGAME_FIELDS = ("kind", "day", "actor", "declared_targets", "result", "note")
ACTION_LABELS = {
    "guard": "执行守护", "attack": "执行击杀", "save": "使用解药", "poison": "使用毒药",
    "check": "执行查验", "learn": "学习身份", "can_shoot": "可以开枪", "cannot_shoot": "不能开枪",
    "carrying": "已带刀", "not_carrying": "未带刀", "shoot": "开枪", "self_destruct": "自爆",
    "die": "出局", "die_after_speech": "发言后出局", "suicide": "自杀出局", "peaceful": "平安夜",
    "register": "登记上警", "elected": "当选警长", "deferred": "竞选延期", "continued": "继续竞选",
    "transfer": "移交警徽", "hold": "持有警徽", "order": "安排发言顺序", "exile": "被放逐",
    "vote": "投票", "not_held": "未举行投票", "none": "没有结果", "pass": "选择不行动",
    "unknown": "记录未知", "unavailable": "行动不可用", "not_eligible": "无投票资格",
    "forbidden": "该行动被禁止", "invalid_exchange": "交换无效", "trade": "选择交易",
    "betray": "选择背叛", "trade_betray": "分别选择交易和背叛", "betray_trade": "分别选择背叛和交易",
    "transform": "变换身份", "mask": "使用面具", "dance": "参与共舞", "win": "胜出",
}


class PublishError(ValueError):
    """A source snapshot cannot be safely published."""


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise PublishError("源 JSON 顶层必须是对象")
    return value, digest_bytes(raw)


def _logical_rules(root: Path, season: str) -> tuple[dict[str, str], dict[str, dict]]:
    config_dir = root / "config"
    scope_path = config_dir / f"{season}_game_scope.json"
    formal_path = config_dir / f"{season}_formal_rules.json"
    board_dir = config_dir / "board_templates"
    if not scope_path.is_file() or not formal_path.is_file() or not board_dir.is_dir():
        raise PublishError("缺少正式范围、正式规则或版型模板配置")
    scope, scope_digest = _read_json(scope_path)
    formal, formal_digest = _read_json(formal_path)
    if scope.get("season") != season or formal.get("season") != season:
        raise PublishError("赛季范围配置不匹配")
    hashes = {
        f"config/{scope_path.name}": scope_digest,
        f"config/{formal_path.name}": formal_digest,
    }
    boards: dict[str, dict] = {}
    for path in sorted(board_dir.glob("*.json")):
        data, data_digest = _read_json(path)
        code = data.get("code")
        if not isinstance(code, str) or code in boards:
            raise PublishError("版型模板缺少唯一代码")
        boards[code] = data
        hashes[f"config/board_templates/{path.name}"] = data_digest
    if not boards:
        raise PublishError("版型模板为空")
    return hashes, {"scope": scope, "formal": formal, "boards": boards}


def _bvid(dossier: dict) -> str:
    slug = dossier.get("slug")
    match = BVID_RE.search(slug) if isinstance(slug, str) else None
    if not match:
        raise PublishError("对局缺少可识别的视频编号")
    return match.group(0)


def _included(dossier: dict, scope: dict) -> bool:
    bvid = _bvid(dossier)
    return not (
        dossier.get("board") in scope.get("excluded_board_codes", [])
        or dossier.get("phase") in scope.get("excluded_phases", [])
        or dossier.get("date") in scope.get("excluded_dates", [])
        or bvid in scope.get("excluded_bvids", [])
        or (scope.get("retained_phases") and dossier.get("phase") not in scope["retained_phases"])
    )


def _pick(source: dict, fields: tuple[str, ...]) -> dict:
    return {key: source[key] for key in fields if key in source}


def _clean_ballot(ballot: dict, rule_defaults: set[tuple[str, int]]) -> dict:
    result = _pick(ballot, BALLOT_FIELDS)
    votes = []
    ballot_id = ballot.get("id")
    for vote in ballot.get("votes", []):
        cleaned = _pick(vote, ("voter", "target", "state"))
        if vote.get("state") == "abstained":
            cleaned["basis"] = (
                "rule_default" if (ballot_id, vote.get("voter")) in rule_defaults else "abstained"
            )
        else:
            cleaned["basis"] = "recorded"
        votes.append(cleaned)
    result["votes"] = votes
    return result


def _rounds(dossier: dict, board: dict) -> list[dict]:
    labels = {
        phase: {slot["code"]: slot["label"] for slot in board.get(f"{phase}_slots", [])}
        for phase in ("night", "day")
    }
    result = []
    for round_ in dossier.get("rounds", []):
        number = round_.get("number")
        row = {"number": number}
        for phase in ("night", "day"):
            events = []
            for event in round_.get(phase, []):
                slot = event.get("slot")
                if slot not in labels[phase]:
                    raise PublishError("事件槽位不在当前版型中")
                output = _pick(event, EVENT_FIELDS)
                output["votes"] = [_pick(vote, VOTE_FIELDS) for vote in event.get("votes", [])]
                output["effects"] = [_pick(effect, EFFECT_FIELDS) for effect in event.get("effects", [])]
                output["slot_label"] = labels[phase][slot]
                period = f"第{number}夜" if phase == "night" else f"第{number}天白天"
                action = event.get("action")
                description = f"{period}，{labels[phase][slot]}：{ACTION_LABELS.get(action, '记录动作 ' + str(action))}"
                actor = event.get("actor")
                if actor is not None:
                    description += f"；行动者 {actor} 号"
                targets = event.get("targets") or []
                if targets:
                    description += "；目标 " + "、".join(f"{target} 号" for target in targets)
                output["description"] = description
                events.append(output)
            row[phase] = events
        result.append(row)
    return result


def _public_game(dossier: dict, voting: dict, endgame: dict, audit: dict | None,
                 board: dict, person_ids: dict[str, str]) -> dict:
    bvid = _bvid(dossier)
    seats = []
    for seat in dossier.get("seats", []):
        name = seat.get("name")
        if not isinstance(name, str) or not name.strip():
            raise PublishError("座位姓名为空")
        seats.append({
            "seat": seat["seat"], "person_id": person_ids[name], "name": name,
            "role": seat["role"], "faction": seat["faction"],
            "learning_target": seat.get("learning_target"), "learned_role": seat.get("learned_role"),
        })
    default_rules: set[tuple[str, int]] = set()
    applications = []
    if audit is not None:
        if audit.get("facts") != voting:
            raise PublishError("投票旁证与当前投票档案不一致")
        for item in audit.get("rule_applications", []):
            if not isinstance(item, dict) or not isinstance(item.get("target"), str):
                raise PublishError("默认弃票旁证格式不合法")
            voters = item.get("voters", [])
            if not isinstance(voters, list) or any(type(voter) is not int for voter in voters):
                raise PublishError("默认弃票旁证缺少有效座位")
            rule, target, day = item.get("rule"), item["target"], item.get("day")
            if not isinstance(rule, str) or type(day) is not int:
                raise PublishError("默认弃票旁证字段不完整")
            applications.append({"rule": rule, "target": target, "day": day, "voters": voters})
            default_rules.update((target, voter) for voter in voters)
    public_voting = {
        "registrations": [_pick(row, REGISTRATION_FIELDS) for row in voting.get("registrations", [])],
        "ballots": [_clean_ballot(row, default_rules) for row in voting.get("ballots", [])],
        "interruptions": [_pick(row, INTERRUPTION_FIELDS) for row in voting.get("interruptions", [])],
        "days": [_pick(row, DAY_FIELDS) for row in voting.get("days", [])],
        "rule_applications": applications,
        "notes": (["未明确投向的票权位按已确认规则标注为默认弃票。"] if applications else
                  ["原文弃票与规则默认弃票按逐票旁证区分。"]),
    }
    if not voting.get("ballots"):
        public_voting["notes"].append("当前档案没有投票记录；这不表示该局投票数为零。")
    if audit is None:
        public_voting["notes"].append("默认弃票旁证缺失，未把弃票标记为规则默认。")

    winner = dossier.get("winner")
    if winner not in {"good", "werewolf", "draw", None}:
        raise PublishError("胜方字段不在允许的公开值内")
    details = {
        "id": dossier["slug"], "season": dossier["season"], "date": dossier["date"],
        "phase": dossier["phase"], "game_number": dossier.get("game_number"),
        "board": {"code": dossier["board"], "name": board["name"]}, "winner": winner,
        "players": [{"id": s["person_id"], "name": s["name"], "seat": s["seat"],
                     "role": s["role"], "faction": s["faction"]} for s in seats],
        "ballot_count": len(public_voting["ballots"]), "round_count": len(dossier.get("rounds", [])),
        "release_id": None,
        "commentators": list(dossier.get("commentators", [])), "referee": dossier.get("referee"),
        "seats": seats, "rounds": _rounds(dossier, board), "voting": public_voting,
        "endgame": {"phases": [_pick(item, ENDGAME_FIELDS) for item in endgame.get("phases", [])]},
        "source": {"url": f"https://www.bilibili.com/video/{bvid}/", "bvid": bvid},
        "data_notes": [],
    }
    if not public_voting["ballots"]:
        details["data_notes"].append("没有可发布的投票记录；投票数未按零票推断。")
    if winner is None:
        details["data_notes"].append("整局胜方待核。")
    if any(seat["role"] is None for seat in seats):
        details["data_notes"].append("部分座位身份待核，保留未知值。")
    if any(seat["faction"] is None for seat in seats):
        details["data_notes"].append("部分座位阵营待核，保留未知值。")
    if any(event["action"] == "unknown" for r in details["rounds"] for phase in ("night", "day") for event in r[phase]):
        details["data_notes"].append("部分行动仍为未知，保留来源状态。")
    return details


def load_publication(root: Path, season: str, sample: str | None = None) -> tuple[list[dict], str, str]:
    root = root.resolve()
    rules_hashes, rules = _logical_rules(root, season)
    scope = rules["scope"]
    rules_hash = digest_bytes(canonical_json(rules_hashes))
    season_dir = root / "data" / "games" / season
    if not season_dir.is_dir():
        raise PublishError("找不到指定赛季的游戏数据")
    entries = []
    for dossier_path in sorted(season_dir.glob("*/dossier.json")):
        try:
            dossier, dossier_digest = _read_json(dossier_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise PublishError("对局档案无法读取") from exc
        if dossier.get("season") != season or not _included(dossier, scope):
            continue
        if sample and _bvid(dossier) != sample:
            continue
        folder = dossier_path.parent
        paths = {key: folder / f"{key}.json" for key in ("voting", "endgame")}
        if any(not path.is_file() for path in paths.values()):
            raise PublishError("正式对局缺少投票或终局档案")
        voting, voting_digest = _read_json(paths["voting"])
        endgame, endgame_digest = _read_json(paths["endgame"])
        slug = dossier.get("slug")
        if voting.get("game_slug") != slug or endgame.get("game_slug") != slug:
            raise PublishError("对局、投票和终局档案关联不一致")
        audit_path = root / "data" / "extractions" / season / "voting" / f"{_bvid(dossier)}.json"
        audit = None
        audit_digest = None
        if audit_path.is_file():
            audit, audit_digest = _read_json(audit_path)
        board = rules["boards"].get(dossier.get("board"))
        if not board:
            raise PublishError("正式对局使用了未知版型")
        file_hashes = {"dossier": dossier_digest, "voting": voting_digest, "endgame": endgame_digest}
        if audit_digest is not None:
            file_hashes["voting_audit"] = audit_digest
        entries.append({
            "dossier": dossier, "voting": voting, "endgame": endgame, "audit": audit,
            "board": board, "folder": folder, "bvid": _bvid(dossier), "source_hashes": file_hashes,
        })
    if sample and not entries:
        raise PublishError("指定样例不在已确认正式范围内或不存在")
    if not sample and season == "S22":
        expected = rules["formal"].get("scope", {}).get("scored_total")
        if type(expected) is int and len(entries) != expected:
            raise PublishError("正式范围数量与已确认统计口径不一致")
    hashes = []
    for item in entries:
        hashes.append({"game_id": item["dossier"]["slug"], "files": item["source_hashes"]})
    source_hash = digest_bytes(canonical_json(hashes))
    return entries, source_hash, rules_hash


def _connect(schema: str = "masters_web"):
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        conn = psycopg.connect(database_url, row_factory=dict_row)
        conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        conn.commit()
        return conn
    # Existing local installs keep their credentials in scripts/database.py;
    # this import is publisher-only and never required by the API runtime.
    import sys
    scripts = str(PACKAGE_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import database
    conn = database.connect(schema)
    conn.commit()
    return conn


def _schema_sql() -> str:
    return (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")


def _person_ids(conn, names: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    # A local jcms.people table is an optional identity source. The public
    # schema deliberately has no FK or dependency on the source database.
    conn.execute("SAVEPOINT person_lookup")
    try:
        cols = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = ANY(%s)",
            ("jcms", "people", ["id", "name"]),
        ).fetchall()
        if {row["column_name"] for row in cols} == {"id", "name"}:
            rows = conn.execute(
                "SELECT name, id::text AS id FROM jcms.people WHERE name = ANY(%s)", (list(names),)
            ).fetchall()
            result.update({row["name"]: row["id"] for row in rows})
        conn.execute("RELEASE SAVEPOINT person_lookup")
    except psycopg.Error:
        # No jcms schema or permissions: use deterministic public UUIDs.
        conn.execute("ROLLBACK TO SAVEPOINT person_lookup")
    for name in names:
        result.setdefault(name, str(uuid.uuid5(PERSON_NAMESPACE, name.strip().casefold())))
    return result


def _create_schema(conn) -> None:
    conn.execute("SAVEPOINT publish_schema")
    try:
        conn.execute(_schema_sql(), prepare=False)
        conn.execute("RELEASE SAVEPOINT publish_schema")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT publish_schema")
        raise


def _release_id(season: str, source_hash: str, rules_hash: str) -> str:
    return (f"{season}-{source_hash[:16]}-{rules_hash[:8]}-"
            f"p{PUBLICATION_FORMAT_VERSION}-s{STATISTICS_VERSION}")


def publish(root: Path = DEFAULT_SOURCE_ROOT, season: str = "S22", sample: str | None = None,
            *, activate: bool = True) -> dict:
    entries, source_hash, rules_hash = load_publication(root, season, sample)
    release_id = _release_id(season, source_hash, rules_hash)
    conn = _connect("masters_web")
    try:
        with conn.transaction():
            _create_schema(conn)
            names = {seat["name"] for item in entries for seat in item["dossier"].get("seats", [])}
            person_ids = _person_ids(conn, names)
            existing = conn.execute("SELECT game_count FROM releases WHERE id = %s", (release_id,)).fetchone()
            if existing:
                if existing["game_count"] != len(entries):
                    raise PublishError("同一发布批次的局数发生冲突")
            else:
                manifest_games = []
                docs = []
                player_rows: dict[str, dict] = {}
                for item in entries:
                    dossier = item["dossier"]
                    doc = _public_game(dossier, item["voting"], item["endgame"], item["audit"],
                                       item["board"], person_ids)
                    doc["release_id"] = release_id
                    docs.append((item, doc))
                    manifest_games.append({"id": dossier["slug"], "files": item["source_hashes"]})
                    for seat in doc["seats"]:
                        player = player_rows.setdefault(seat["person_id"], {
                            "id": seat["person_id"], "name": seat["name"], "appearances": 0,
                            "roles": Counter(),
                        })
                        player["appearances"] += 1
                        player["roles"][seat["role"] or "身份未知"] += 1
                manifest = {"season": season, "publication_format_version": PUBLICATION_FORMAT_VERSION,
                            "statistics_version": STATISTICS_VERSION, "games": manifest_games,
                            "rules": sorted((name, digest) for name, digest in _logical_rules(Path(root), season)[0].items())}
                conn.execute(
                    "INSERT INTO releases(id, season, game_count, source_hash, rules_hash, manifest) "
                    "VALUES(%s, %s, %s, %s, %s, %s)",
                    (release_id, season, len(entries), source_hash, rules_hash, Jsonb(manifest)),
                )
                for player in player_rows.values():
                    roles = [{"role": role, "count": count} for role, count in sorted(player["roles"].items())]
                    conn.execute(
                        "INSERT INTO players(release_id, id, name, appearances, roles) VALUES(%s,%s,%s,%s,%s)",
                        (release_id, player["id"], player["name"], player["appearances"], Jsonb(roles)),
                    )
                for item, doc in docs:
                    dossier = item["dossier"]
                    search_text = " ".join([
                        dossier["slug"], item["bvid"], dossier["date"], item["board"]["name"],
                        " ".join(s["name"] for s in doc["seats"]),
                    ])
                    vote_count = sum(len(ballot["votes"]) for ballot in doc["voting"]["ballots"])
                    conn.execute(
                        "INSERT INTO games(release_id,id,season,event_date,phase,game_number,board_code,board_name,"
                        "winner,bvid,search_text,ballot_count,vote_count,round_count,snapshot) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                         (release_id, doc["id"], doc["season"], date.fromisoformat(doc["date"]), doc["phase"], doc["game_number"],
                         doc["board"]["code"], doc["board"]["name"], doc["winner"], item["bvid"], search_text,
                         doc["ballot_count"], vote_count, doc["round_count"], Jsonb(doc)),
                    )
                    for seat in doc["seats"]:
                        conn.execute(
                            "INSERT INTO game_players(release_id,game_id,person_id,name,seat,role,faction) "
                            "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                            (release_id, doc["id"], seat["person_id"], seat["name"], seat["seat"],
                             seat["role"], seat["faction"]),
                        )
            if activate:
                conn.execute(
                    "INSERT INTO active_release(singleton, release_id) VALUES(true,%s) "
                    "ON CONFLICT(singleton) DO UPDATE SET release_id=EXCLUDED.release_id",
                    (release_id,),
                )
        return {"id": release_id, "game_count": len(entries), "source_hash": source_hash,
                "rules_hash": rules_hash, "activated": activate, "idempotent": bool(existing)}
    finally:
        conn.close()


def activate(release_id: str) -> dict:
    conn = _connect("masters_web")
    try:
        with conn.transaction():
            _create_schema(conn)
            row = conn.execute("SELECT game_count FROM releases WHERE id = %s", (release_id,)).fetchone()
            if not row:
                raise PublishError("发布批次不存在")
            conn.execute(
                "INSERT INTO active_release(singleton, release_id) VALUES(true,%s) "
                "ON CONFLICT(singleton) DO UPDATE SET release_id=EXCLUDED.release_id", (release_id,)
            )
        return {"id": release_id, "game_count": row["game_count"], "activated": True}
    finally:
        conn.close()


def list_games(root: Path = DEFAULT_SOURCE_ROOT, season: str = "S22") -> list[dict]:
    entries, _, _ = load_publication(root, season)
    return [{"id": item["dossier"]["slug"], "date": item["dossier"]["date"],
             "game_number": item["dossier"].get("game_number"), "board": item["board"]["name"],
             "bvid": item["bvid"]} for item in entries]
