"""Validate the endgame supplied by the current incremental batch."""
from typing import Any
from game_records import ReviewError

SCHEMA_VERSION = 1

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
