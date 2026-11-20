"""Display-sized player photographs for static exports; originals stay intact."""
from __future__ import annotations

from contextlib import suppress
import hashlib
from io import BytesIO
from pathlib import Path
import re
import uuid

from PIL import Image, ImageOps, __version__ as PILLOW_VERSION, features

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


def _cached_thumbnail(source: Path, cache: Path, original_hash: str) -> tuple[str, bytes]:
    entry = cache / f'{original_hash}.bin'
    try:
        saved_digest, _, body = entry.read_bytes().partition(b'\n')
        digest = hashlib.sha256(body).hexdigest()
        if saved_digest == digest.encode('ascii') and body:
            return digest, body
    except OSError:
        pass

    body = thumbnail_bytes(source.read_bytes())
    digest = hashlib.sha256(body).hexdigest()
    temporary = entry.with_suffix(f'.{uuid.uuid4().hex}.tmp')
    try:
        cache.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(digest.encode('ascii') + b'\n' + body)
        temporary.replace(entry)
    except OSError:
        # A read-only or temporarily occupied cache does not prevent export.
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
    return digest, body


def create_thumbnails(media_root: Path, media_files: list[dict], *,
                      cache_root: Path | None = None) -> dict[str, str]:
    """Generate content-addressed display copies for the public player photos."""
    mapping = {}
    known_paths = {item['path'] for item in media_files}
    cache = (cache_root / f'{VERSION}-{PILLOW_VERSION}-{features.version("webp")}'
             if cache_root is not None else None)
    for asset in list(media_files):
        if not _PHOTO_URL.fullmatch(asset['url']):
            continue
        source = media_root / asset['path']
        try:
            if cache is None:
                body = thumbnail_bytes(source.read_bytes())
                digest = hashlib.sha256(body).hexdigest()
            else:
                # The exporter has already checked this content-addressed original.
                digest, body = _cached_thumbnail(source, cache, Path(asset['url']).stem)
        except (OSError, ValueError) as error:
            raise ValueError(f'Cannot create player photo thumbnail: {asset["url"]}') from error
        relative = f'{source.parent.relative_to(media_root).as_posix()}/{digest}.webp'
        target = media_root / relative
        url = f'/media/{relative}'
        if relative not in known_paths:
            target.write_bytes(body)
            media_files.append({'url': url, 'sha256': digest, 'path': relative})
            known_paths.add(relative)
        mapping[asset['url']] = url
    return mapping
