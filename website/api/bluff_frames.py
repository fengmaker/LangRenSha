"""Only manifest-listed, content-addressed review screenshots are public."""
from functools import lru_cache
import json
from pathlib import Path
import re

ASSETS=Path(__file__).resolve().parents[1]/'assets/bluff-frames'
MANIFEST=Path(__file__).with_name('bluff_frames.json')


@lru_cache(maxsize=1)
def manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.is_file() else {'frames':{}}


def frame_path(season: str, filename: str) -> Path | None:
    if not re.fullmatch(r'S[0-9]{1,4}',season) or not re.fullmatch(r'[a-f0-9]{64}\.png',filename):
        return None
    if filename not in manifest().get('frames',{}).get(season,{}):
        return None
    path=(ASSETS/season/filename).resolve()
    return path if path.is_relative_to(ASSETS.resolve()) and path.is_file() else None


def public_image_url(value: object) -> str | None:
    if not isinstance(value,str):
        return None
    match=re.fullmatch(r'/media/bluff-frames/(S[0-9]{1,4})/([a-f0-9]{64}\.png)',value)
    return value if match else None
