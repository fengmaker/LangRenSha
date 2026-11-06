"""Display-sized player photographs for static exports; originals stay intact."""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import re

from PIL import Image, ImageOps

VERSION = 1
_PHOTO_URL = re.compile(r'/media/player-photos/(S[0-9]{1,4})/[a-f0-9]{64}\.(?:jpg|jpeg|png|webp)')
_THUMBNAIL_URL = re.compile(r'/media/player-photos/(S[0-9]{1,4})/[a-f0-9]{64}\.webp')


def thumbnail_bytes(body: bytes) -> bytes:
    with Image.open(BytesIO(body)) as source:
        image = ImageOps.exif_transpose(source)
        image.thumbnail((600, 1067), Image.Resampling.LANCZOS)
        if image.mode not in {'RGB', 'RGBA'}:
            image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')
        output = BytesIO()
        image.save(output, 'WEBP', quality=82)
        return output.getvalue()


def thumbnail_mapping(manifest: dict) -> dict[str, str]:
    mapping = manifest.get('player_photo_thumbnails', {})
    if not isinstance(mapping, dict):
        raise ValueError('Invalid player photo thumbnail mapping')
    for source, target in mapping.items():
        original = _PHOTO_URL.fullmatch(source) if isinstance(source, str) else None
        thumbnail = _THUMBNAIL_URL.fullmatch(target) if isinstance(target, str) else None
        if not original or not thumbnail or original[1] != thumbnail[1]:
            raise ValueError(f'Invalid player photo thumbnail mapping: {source}')
    return mapping


def create_thumbnails(media_root: Path, media_files: list[dict],
                      previous_root: Path | None = None, previous_manifest: dict | None = None) -> dict[str, str]:
    previous = thumbnail_mapping(previous_manifest) if (previous_manifest or {}).get('photo_thumbnail_version') == VERSION else {}
    mapping = {}
    known_paths = {item['path'] for item in media_files}
    for asset in list(media_files):
        if not _PHOTO_URL.fullmatch(asset['url']):
            continue
        source = media_root / asset['path']
        cached_url = previous.get(asset['url']) if previous_root is not None else None
        if cached_url:
            cached = previous_root / cached_url.lstrip('/')
            body = cached.read_bytes()
            if hashlib.sha256(body).hexdigest() != cached.stem:
                raise ValueError(f'Reused player photo thumbnail hash mismatch: {cached_url}')
        else:
            try:
                body = thumbnail_bytes(source.read_bytes())
            except (OSError, ValueError) as error:
                raise ValueError(f'Cannot create player photo thumbnail: {asset["url"]}') from error
        digest = hashlib.sha256(body).hexdigest()
        relative = f'{source.parent.relative_to(media_root).as_posix()}/{digest}.webp'
        target = media_root / relative
        url = f'/media/{relative}'
        if relative not in known_paths:
            target.write_bytes(body)
            media_files.append({'url': url, 'sha256': digest, 'path': relative})
            known_paths.add(relative)
        mapping[asset['url']] = url
    return mapping
