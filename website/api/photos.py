"""Season-specific, reviewed photographs; only manifest-listed assets are public."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from urllib.parse import urlparse

PHOTO_ROOT = Path(__file__).resolve().parents[1] / "assets" / "player-photos"
MANIFEST_PATH = Path(__file__).with_name("player_photos.json")
SEASON_PATTERN = re.compile(r"S[0-9]{1,4}")
FILE_PATTERN = re.compile(r"[a-f0-9]{64}\.(?:jpg|jpeg|png|webp)")


@lru_cache(maxsize=1)
def manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        return {"players": {}, "missing": []}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def photo_for(name: str, season: str) -> dict | None:
    record = manifest().get("players", {}).get(season, {}).get(name)
    if not record or not SEASON_PATTERN.fullmatch(season):
        return None
    asset = record.get("asset", "")
    parts = asset.split("/")
    if len(parts) != 2 or parts[0] != season or not FILE_PATTERN.fullmatch(parts[1]):
        return None
    if not (PHOTO_ROOT / asset).is_file():
        return None
    source = record.get("source_url", "")
    parsed = urlparse(source)
    if parsed.scheme != "https" or parsed.hostname not in {"m.weibo.cn", "weibo.com", "www.weibo.com"}:
        source = ""
    return {"url": f"/media/player-photos/{asset}", "season": season,
            "source_url": source, "source_date": record.get("source_date"),
            "photo_id": record.get("photo_id")}


def photo_path(season: str, filename: str) -> Path | None:
    if not SEASON_PATTERN.fullmatch(season) or not FILE_PATTERN.fullmatch(filename):
        return None
    asset = f"{season}/{filename}"
    if not any(record.get("asset") == asset for record in manifest().get("players", {}).get(season, {}).values()):
        return None
    path = (PHOTO_ROOT / asset).resolve()
    if not path.is_relative_to(PHOTO_ROOT.resolve()) or not path.is_file():
        return None
    return path
