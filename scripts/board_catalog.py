"""Canonical title lookup for S22 board templates."""
from __future__ import annotations

# Title spellings from the S22 catalogue. Keep the wolf-king variants distinct.
_CANONICAL_BOARD_CODES: dict[str, str] = {
    "预女猎白混": "mixed_blood",
    "机械狼通灵师": "mechanical_wolf_seer",
    "诡术之境": "guile_realm",
    "假面舞会": "masquerade",
    "盗宝大师": "treasure_master",
    "唯邻是从": "neighbor_puppet",
    "孤注一掷": "all_in",
    "狼王守卫": "wolf_king_guard",
    "狼王骑士": "wolf_king_knight",
    "预女猎白": "seer_witch_hunter_white",
    "黑狼王骑士": "black_wolf_king_knight",
    "四狼八猎": "four_wolves_eight_hunters",
    "鬼魂新娘": "ghost_bride",
}

# The season catalogue has one documented alternate title for this board.
BOARD_CODES: dict[str, str] = {
    **_CANONICAL_BOARD_CODES,
    "盗宝大师赛": "treasure_master",
}

_CANONICAL_NAMES: dict[str, str] = {
    code: title for title, code in _CANONICAL_BOARD_CODES.items()
}


def canonical_board_name(title: str | None) -> str | None:
    """Return the canonical board title, or None when the title is unknown.

    Exact catalogue titles and documented aliases are accepted. Full game titles
    ending in ``-<board title>`` are accepted as well. Similar wolf-king names
    are deliberately not inferred or merged.
    """
    if not isinstance(title, str):
        return None
    candidate = title.strip()
    code = BOARD_CODES.get(candidate)
    if code is None and candidate in _CANONICAL_NAMES:
        code = candidate
    if code is None and "-" in candidate:
        suffix = candidate.rsplit("-", 1)[-1].strip()
        code = BOARD_CODES.get(suffix)
    return _CANONICAL_NAMES.get(code) if code is not None else None
