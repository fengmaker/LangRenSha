"""Display-sized player photographs for static exports; originals stay intact."""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import re

from PIL import Image, ImageOps

VERSION = 2
_PHOTO_URL = re.compile(r'/media/player-photos/(S[0-9]{1,4})/[a-f0-9]{64}\.(?:jpg|jpeg|png|webp)')


def thumbnail_bytes(body: bytes) -> bytes:
    with Image.open(BytesIO(body)) as source:
        image = ImageOps.exif_transpose(source)
        image.thumbnail((480, 854), Image.Resampling.LANCZOS)
        if image.mode not in {'RGB', 'RGBA'}:
            image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')
        output = BytesIO()
        image.save(output, 'WEBP', quality=74)
        return output.getvalue()


def create_thumbnails(media_root: Path, media_files: list[dict]) -> dict[str, str]:
    """Generate content-addressed display copies for the public player photos."""
    mapping = {}
    known_paths = {item['path'] for item in media_files}
    for asset in list(media_files):
        if not _PHOTO_URL.fullmatch(asset['url']):
            continue
        source = media_root / asset['path']
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
