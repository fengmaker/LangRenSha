"""Generate independent, source-bound S22 wolf-rush endgame sidecars.

The curated events below are restricted to judge recaps or ending announcements
that describe a completed wolf-rush phase. A player's speculative or first-
person post-game discussion is kept in the cross-check report as a candidate,
never promoted into game facts. ``declared_targets`` is a sorted set: list order
does not imply knife order.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from database import ReviewError, connect

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = Path("data/reports/S22/S22_拍刀交叉复核.json")
REVIEWED_SOURCES = Path("data/extractions/S22/endgame_reviewed_sources.json")
SCHEMA_VERSION = 1
RULE_REFERENCE = {
    "url": "https://www.sina.cn/news/detail/5219888094251252.html",
    "author": "萧亚辉",
    "date": "2025-10-09",
    "summary": "连续自爆后可省略常规阶段，由存活狼人决定刀路并由法官结算有效击杀和胜负；自爆者仅有建议权，放逐者不可参与。",
}


# Each span is an inclusive source-time window in milliseconds, lifted from
# the reviewed recap's timestamps. The source transcript is re-read on every
# build to create the evidence quote and bind each sidecar with SHA-256.
# Targets are listed as an unordered set; only seats explicitly named in the
# judge recap/ending announcement are included.
REVIEWED_PHASES: dict[str, dict[str, Any]] = {
    "BV1pGVC6cEbW": {
        "day": 4, "actor": 1, "targets": [9], "result": "werewolf_win",
        "note": "第四天放逐投票两轮平票、无人被放逐而形成平安日；复盘明确最后一张狼人1号拍刀、最后一名9号并播报狼队获胜。",
        "spans": [[4493920, 4509750]],
    },
    "BV1hb7R6XEtD": {
        "day": 4, "actor": None, "targets": [9], "result": "werewolf_win",
        "note": "结束播报称狼人拍到9号并获胜；后续复盘称第四天狼人击杀最后一张平民，作为同一终局的复核证据。",
        "spans": [[4989555, 4996560], [5046945, 5056560]],
    },
    "BV1vH7R6tEQp": {
        "day": None, "actor": None, "targets": [2], "result": "werewolf_win",
        "note": "复核记录确认末尾“最后一声二号”为终局拍刀目标；法官播报随即宣布游戏结束、狼人阵营获胜。日号和行动人未明确。",
        "spans": [[4507615, 4510720]],
    },
    "BV12GEA6iEx5": {
        "day": 1, "actor": None, "targets": [1, 2, 3], "result": "werewolf_win",
        "note": "第一天白天12号被放逐后，法官播报狼队拍刀1、2、3号并宣布拍刀成功；目标集合不表示刀序。",
        "spans": [[4821890, 4832075]],
    },
    "BV1jaE26kELR": {
        "day": 2, "actor": None, "targets": [], "result": "werewolf_win",
        "note": "第二天法官播报狼人阵营互认拍刀并结束游戏，未公布刀路或行动人。",
        "spans": [[4583109, 4588540]],
    },
    "BV1xYEo6QEGV": {
        "day": 4, "actor": None, "targets": [2], "result": "werewolf_win",
        "note": "终局播报及第四天复盘互相印证拍刀成功；复盘点名2号。另一处“最后一张平民牌”不另推座位。",
        "spans": [[3903260, 3908860], [3976900, 3983890]],
    },
    "BV13tEB6VEVV": {
        "day": 4, "actor": None, "targets": [6], "result": "werewolf_win",
        "note": "法官复盘明确狼队拍刀场上最后一名6号并播报成功；6号是被拍目标，不据此推断其阵营。",
        "spans": [[4382410, 4387110]],
    },
    "BV1wmEB68Exu": {
        "day": 4, "actor": None, "targets": [3], "result": "werewolf_win",
        "note": "终局播报与赛后复盘均点名3号拍刀成功并报狼队获胜；未明确行动人。",
        "spans": [[7496380, 7502820], [7562689, 7571280]],
    },
    "BV11KJ56PEPY": {
        "day": 4, "actor": None, "targets": [3], "result": "werewolf_win",
        "note": "第四天11号狼人自爆后，法官单独播报狼队拍刀场上最后一名3号、拍刀成功及狼队获胜；未把自爆者推定为拍刀行动人。",
        "spans": [[6748169, 6758309]],
    },
    "BV1W6jG6HEeT": {
        "day": 2, "actor": None, "targets": [], "result": "good_win",
        "note": "法官明确播报狼人阵营决定拍刀、刀数不足、拍刀失败及好人获胜；没有明确刀路。",
        "spans": [[6409190, 6419660]],
    },
    "BV1Hej66FE1Y": {
        "day": 3, "actor": None, "targets": [10], "result": "good_win",
        "note": "第三天放逐后狼队选择拍刀，法官明确点名10号平民拍刀失败并播报好人获胜。",
        "spans": [[5758530, 5767020]],
    },
    "BV1QAjo6sEEc": {
        "day": 2, "actor": None, "targets": [2, 11], "result": "werewolf_win",
        "note": "第二天放逐后法官播报狼队拍刀，随后点名2号女巫、11号白神并宣布狼队屠神获胜；列表不表示刀序。",
        "spans": [[5945290, 5956190]],
    },
    "BV1YmTc6yEFd": {
        "day": None, "actor": None, "targets": [4, 11], "result": "werewolf_win",
        "note": "法官复盘明确狼队拍刀4号白神及11号猎人成功并播报狼队屠神获胜；日号未能从该结算段确认。",
        "spans": [[3294970, 3304430]],
    },
    "BV1Y2Tc6LEt4": {
        "day": 3, "actor": None, "targets": [9, 12], "result": "werewolf_win",
        "note": "第三天法官播报场上剩三狼拍刀9、12号，随后宣布拍刀成功和狼队获胜；目标集合不表示刀序。",
        "spans": [[6214430, 6221600]],
    },
    "BV1gvTi66EFF": {
        "day": 4, "actor": None, "targets": [12], "result": "werewolf_win",
        "note": "第四天法官播报狼队选择拍刀，点名场上最后一张平民12号并宣布成功。",
        "spans": [[3636140, 3642460]],
    },
    "BV119TJ6pEtC": {
        "day": None, "actor": 7, "targets": [8], "result": "werewolf_win",
        "note": "复盘明确最后一张狼人7号盗宝大师拍刀最后一张神牌8号猎人，随后播报狼队获胜；日号未明确。",
        "spans": [[6447250, 6458195]],
    },
    "BV1BjMh63EEK": {
        "day": 2, "actor": None, "targets": [3, 4], "result": "werewolf_win",
        "note": "法官复盘经交叉核对明确实际终局刀路为4、3号并播报狼队屠神获胜；未把名单顺序解释为刀序。",
        "spans": [[5818260, 5827990]],
    },
    "BV1BjMh63ED9": {
        "day": None, "actor": 5, "targets": [11], "result": "werewolf_win",
        "note": "法官复盘明确最后一狼5号拍刀最后一神11号，狼队屠神获胜；日号未明确。",
        "spans": [[5886720, 5890780]],
    },
    "BV1suMG6PEYP": {
        "day": 4, "actor": None, "targets": [11, 12], "result": "werewolf_win",
        "note": "第四天复盘明确机械狼给出12、11号刀路，小刀击杀12号、大刀击杀11号并结束游戏；目标数组按集合保存，刀种关系保留在此备注。",
        "spans": [[6342135, 6356190]],
    },
    "BV1BPNB6QE1s": {
        "day": None, "actor": None, "targets": [3, 4], "result": "werewolf_win",
        "note": "法官复盘明确狼队决定拍两刀，目标3号平民和4号混血儿，随后播报拍刀成功、狼队获胜；本段日号表述冲突，留空。",
        "spans": [[7996290, 8011380]],
    },
    "BV1jYKV6SETU": {
        "day": 2, "actor": None, "targets": [11], "result": "werewolf_win",
        "note": "第二天白神出局后，法官播报狼队拍刀第一刀即命中场上最后一神11号猎人，狼队屠神获胜。",
        "spans": [[5490410, 5500320]],
    },
    "BV1bWKY6tEri": {
        "day": None, "actor": None, "targets": [1, 3], "result": "werewolf_win",
        "note": "法官复盘明确狼队决定拍刀并给出1、3号刀路，结尾播报狼队获胜；日号和行动人未明确，目标顺序未知。",
        "spans": [[6954870, 6965605]],
    },
    "BV1Pxgy68EQC": {
        "day": 2, "actor": None, "targets": [7, 12], "result": "good_win",
        "note": "第二天法官明确狼队决定两刀、给出12和7号刀路但拍刀失败，随后播报好人获胜；目标数组不表示刀序。",
        "spans": [[5212690, 5220590]],
    },
    "BV1RGgx6xEun": {
        "day": 2, "actor": None, "targets": [4, 8], "result": "werewolf_win",
        "note": "第二天1号狼人自爆后狼队拍刀，法官点名4号平民、8号混血儿拍刀成功并播报狼队获胜；未将自爆者推定为行动人。",
        "spans": [[5086620, 5096760]],
    },
    "BV1iMgq6ZE5t": {
        "day": 3, "actor": None, "targets": [2], "result": "good_win",
        "note": "第三天11号白神被放逐后，狼队拍刀2号猎人失败，法官播报好人获胜。",
        "spans": [[3202370, 3213550]],
    },
    "BV1hQ3t6hEbS": {
        "day": 2, "actor": None, "targets": [8, 12], "result": "good_win",
        "note": "第二天法官明确狼队选择拍刀8号平民和12号女巫，拍刀失败并播报好人获胜；目标集合不表示刀序。",
        "spans": [[4838929, 4851480]],
    },
    "BV1oXMB6fEQ4": {
        "day": 4, "actor": 8, "targets": [4], "result": "werewolf_win",
        "note": "第三天7号自爆后进入第四夜，复盘依次说明守卫守护12、狼刀6；第四天12号被放逐后，8号机械平民才拍刀最后一神4号猎人并播报狼队屠神获胜。行动人依播报明示座位记录，不据角色转写补充其他信息。",
        "spans": [[3203780, 3217340]],
    },
    "BV1DFM26ME2R": {
        "day": 3, "actor": None, "targets": [9, 10], "result": "werewolf_win",
        "note": "第三天法官复盘点明狼队的两个拍刀目标为9、10号并播报狼队获胜；没有将名单顺序解释为刀序。",
        "spans": [[3579850, 3589319]],
    },
    "BV1mDun6wEhp": {
        "day": 4, "actor": None, "targets": [7], "result": "werewolf_win",
        "note": "第4日放逐4号后，法官复盘明示狼队拍刀目标为7号定序王子，随后播报拍刀成功和狼队获胜；无新增夜晚或投票。",
        "spans": [[4259389, 4269590]],
    },
    "BV1CSuN62Ee2": {
        "day": None, "actor": None, "targets": [2, 12], "result": "werewolf_win",
        "note": "法官复盘明确机械双刀狼拍刀12号女巫及2号猎人成功并播报狼队屠神获胜；未将前述自爆者推定为拍刀行动人，日号未明确。",
        "spans": [[4496310, 4510120]],
    },
    "BV1JNgj6gEty": {
        "day": 2, "actor": None, "targets": [1, 7], "result": "werewolf_win",
        "note": "第二天8号自爆入夜后，法官复盘明确狼队两刀目标为1号平民、7号混血儿并播报拍刀成功、狼队获胜；未将自爆者推定为拍刀行动人。",
        "spans": [[6012930, 6023520]],
    },
    "BV1GXgW6HEmA": {
        "day": 4, "actor": None, "targets": [2], "result": "werewolf_win",
        "note": "第四天11号被放逐后狼队拍刀，2号白神拍刀成功，法官播报狼队屠蛇获胜。",
        "spans": [[4141220, 4149539]],
    },
    "BV1XXgW6nEZ5": {
        "day": 3, "actor": 7, "targets": [2], "result": "werewolf_win",
        "note": "终局播报与第三天复盘互相印证：8号自爆后7号机械女巫选择拍到场上最后一神，2号女巫拍刀成功，狼队屠神获胜。",
        "spans": [[4946510, 4951890], [5019090, 5031110]],
    },
    "BV1jM8B6jEkF": {
        "day": 4, "actor": 9, "targets": [11], "result": "werewolf_win",
        "note": "第四天平安日，法官明确9号鬼术师拍刀最后一神11号并播报狼队拍刀成功、屠神获胜。",
        "spans": [[3229770, 3237380]],
    },
}


# Explicit keyword-only candidate: the excerpt is first-person post-game
# strategy discussion, not a judge's resolution or ending announcement.
REVIEW_CANDIDATES = {
    "BV1KkL96MEuH": {
        "span": [4540370, 4553650],
        "reason": "复盘原文中虽有“决定拍刀”和6/7/12号，但该段是第一人称战术讨论并称狼人交牌；没有明确法官拍刀结算/胜负播报，故只列候选、不补入实际阶段。",
    },
}


def _batch_module():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import batch_s22
    return batch_s22


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_for_window(segments: list[dict[str, Any]], path: str,
                         start_ms: int, end_ms: int) -> dict[str, Any]:
    selected = [s for s in segments
                if s["end_ms"] >= start_ms and s["start_ms"] <= end_ms]
    if not selected:
        raise ValueError(f"证据时间窗在来源中没有转写片段：{path} {start_ms}-{end_ms}")
    return {
        "path": path,
        "start_ms": min(s["start_ms"] for s in selected),
        "end_ms": max(s["end_ms"] for s in selected),
        "quote": "\n".join(s["text"] for s in selected),
    }


def _phase_record(spec: dict[str, Any], segments: list[dict[str, Any]],
                  source_path: str) -> dict[str, Any]:
    targets = sorted({int(x) for x in spec["targets"]})
    if any(not 1 <= target <= 12 for target in targets):
        raise ValueError(f"拍刀目标座位越界：{targets}")
    if spec["result"] not in {"werewolf_win", "good_win", "unknown"}:
        raise ValueError(f"拍刀阶段胜负值不合法：{spec['result']}")
    day, actor = spec["day"], spec["actor"]
    if day is not None and (not isinstance(day, int) or day < 1):
        raise ValueError(f"拍刀阶段日号不合法：{day}")
    if actor is not None and (not isinstance(actor, int) or not 1 <= actor <= 12):
        raise ValueError(f"拍刀行动人座位不合法：{actor}")
    return {
        "kind": "wolf_rush",
        "day": day,
        "actor": actor,
        "declared_targets": targets,
        "result": spec["result"],
        "note": spec["note"],
        "evidence": [_evidence_for_window(segments, source_path, lo, hi)
                     for lo, hi in spec["spans"]],
    }


def validate(sidecar: dict[str, Any]) -> None:
    """Validate the complete replacement before opening a write transaction."""
    if (sidecar.get("schema_version") != SCHEMA_VERSION or
            not isinstance(sidecar.get("game_slug"), str) or not sidecar["game_slug"].strip() or
            not isinstance(sidecar.get("phases"), list)):
        raise ReviewError("拍刀档案版本、对局关联或阶段列表不合法")
    for phase in sidecar["phases"]:
        if (not isinstance(phase, dict) or not {"kind", "day", "actor", "declared_targets", "result"} <= phase.keys()
                or phase.get("kind") != "wolf_rush"):
            raise ReviewError("拍刀阶段类型不合法")
        if phase.get("result") not in {"werewolf_win", "good_win", "unknown"}:
            raise ReviewError("拍刀阶段结算不合法")
        day, actor, targets = phase.get("day"), phase.get("actor"), phase.get("declared_targets")
        if day is not None and (type(day) is not int or day < 1):
            raise ReviewError("拍刀游戏日不合法")
        if actor is not None and (type(actor) is not int or not 1 <= actor <= 12):
            raise ReviewError("拍刀行动人座位不合法")
        if (not isinstance(targets, list) or any(type(n) is not int or not 1 <= n <= 12 for n in targets)
                or len(targets) != len(set(targets))):
            raise ReviewError("拍刀目标座位须合法且不重复")


def import_endgame(sidecar: dict[str, Any], *, conn=None) -> dict[str, int]:
    """Replace one game's terminal phases atomically, keeping unknowns as NULL."""
    validate(sidecar)
    transaction = connect() if conn is None else nullcontext(conn)
    with transaction as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("game-record-" + sidecar["game_slug"],))
        game = conn.execute("SELECT id FROM games WHERE slug=%s", (sidecar["game_slug"],)).fetchone()
        if game is None:
            raise ReviewError("拍刀档案对应的对局尚未入库")
        conn.execute("DELETE FROM game_endgame_phases WHERE game_id=%s", (game["id"],))
        for number, phase in enumerate(sidecar["phases"], 1):
            conn.execute("""INSERT INTO game_endgame_phases
                (game_id,phase_number,kind,day_number,actor_seat,declared_targets,result)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (game["id"], number, phase["kind"], phase["day"], phase["actor"],
                 sorted(phase["declared_targets"]), phase["result"]))
    return {"phases": len(sidecar["phases"])}


def build(*, root: Path | str = ROOT, state: dict[str, Any] | None = None,
          write: bool = True, write_database: bool = False) -> dict[str, Any]:
    """Build a sidecar for every game in ``batch_s22.load_state()``.

    Returns the deterministic cross-check report. ``write=False`` is useful
    for validation; it does not mutate the project files.
    """
    root = Path(root).resolve()
    if write_database and not write:
        raise ValueError("只检查模式不能写入数据库")
    batch = _batch_module()
    state = state if state is not None else batch.load_state()
    if state.get("season") != "S22" or not isinstance(state.get("items"), dict):
        raise ValueError("S22批处理状态无效")
    if write_database:
        from database import migrate
        migrate()

    games: list[dict[str, Any]] = []
    phases_report: list[dict[str, Any]] = []
    counts = {"werewolf_win": 0, "good_win": 0, "unknown": 0}
    games_with_phase = 0
    reviewed_sources = batch.read_json(root / REVIEWED_SOURCES)
    for bvid, entry in sorted(state["items"].items()):
        folder = root / entry["output_dir"]
        source_rel = entry.get("source_path")
        if not source_rel:
            raise ValueError(f"{bvid}没有可绑定的来源转写")
        source = root / source_rel
        if not source.is_file():
            raise FileNotFoundError(f"{bvid}来源转写缺失：{source_rel}")
        source_hash = _digest(source)
        if bvid in REVIEWED_PHASES or bvid in REVIEW_CANDIDATES:
            binding = reviewed_sources["items"][bvid]
            if binding["path"] != source_rel or binding["sha256"] != source_hash:
                raise ValueError("拍刀复核所绑定的转写已变化，需要重新检查时间窗及结论：" + bvid)
        segments = batch.load_segments(source)
        dossier_path = folder / "dossier.json"
        dossier = batch.read_json(dossier_path)
        slug = dossier.get("slug")
        if not slug:
            raise ValueError(f"{bvid}档案缺少slug")
        spec = REVIEWED_PHASES.get(bvid)
        phases = [_phase_record(spec, segments, source_rel)] if spec else []
        if phases:
            games_with_phase += 1
            counts[phases[0]["result"]] += 1
            phase = phases[0]
            phases_report.append({
                "game_slug": slug, "bvid": bvid, "date": entry.get("date"),
                "game_number": entry.get("game_number"), **phase,
            })
        sidecar = {
            "schema_version": SCHEMA_VERSION,
            "game_slug": slug,
            "phases": phases,
            "source_sha256": source_hash,
        }
        if phases and dossier.get("winner"):
            if phases[0]["result"].replace("_win", "") != dossier["winner"]:
                raise ValueError("拍刀结算与当前档案胜负不一致：" + bvid)
        validate(sidecar)
        games.append({
            "game_slug": slug, "bvid": bvid, "date": entry.get("date"),
            "game_number": entry.get("game_number"),
            "file": (Path(entry["output_dir"]) / "endgame.json").as_posix(),
            "source_sha256": source_hash, "phases": len(phases),
        })
        if write:
            batch.atomic_json(folder / "endgame.json", sidecar)
        if write_database:
            games[-1]["database"] = import_endgame(sidecar)

    candidates = []
    for bvid, candidate in sorted(REVIEW_CANDIDATES.items()):
        if bvid not in state["items"]:
            continue
        entry = state["items"][bvid]
        source_rel = entry["source_path"]
        source = root / source_rel
        evidence = _evidence_for_window(
            batch.load_segments(source), source_rel, *candidate["span"])
        candidates.append({
            "game_slug": batch.read_json(root / entry["output_dir"] / "dossier.json")["slug"],
            "bvid": bvid, "evidence": evidence, "reason": candidate["reason"],
        })

    total_phases = sum(g["phases"] for g in games)
    report = {
        "schema_version": SCHEMA_VERSION,
        "season": "S22",
        "rule_reference": RULE_REFERENCE,
        "summary": {
            "games": len(games), "games_with_wolf_rush": games_with_phase,
            "games_without_confirmed_wolf_rush": len(games) - games_with_phase,
            "phases": total_phases, "werewolf_win": counts["werewolf_win"],
            "good_win": counts["good_win"], "unknown_result": counts["unknown"],
            "with_declared_targets": sum(bool(p["declared_targets"]) for p in phases_report),
            "without_declared_targets": sum(not p["declared_targets"] for p in phases_report),
            "candidates_not_promoted": len(candidates),
            "database_written": write_database,
        },
        "games": games,
        "phases": phases_report,
        "candidates": candidates,
        "method": "只把法官复盘/结束播报明确发生的拍刀结算写入局内阶段；普通夜刀和放逐不混入。declared_targets为空表示未明确点名，目标数组按集合排序且不表示刀序。",
    }
    if write:
        batch.atomic_json(root / REPORT_PATH, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="项目根目录（默认脚本所在项目）")
    parser.add_argument("--check", action="store_true",
                        help="只重建并打印统计，不写文件")
    parser.add_argument("--import-db", action="store_true", help="同步独立拍刀阶段到本地数据库")
    args = parser.parse_args(argv)
    if args.check and args.import_db:
        parser.error("--check 与 --import-db 不能同时使用")
    report = build(root=args.root, write=not args.check, write_database=args.import_db)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
