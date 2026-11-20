from io import BytesIO
import hashlib

import pytest
from PIL import Image, ImageDraw

from website.static_publish import photo_thumbnails


def _photo(media_root, size=(1440, 2560)):
    image = Image.new("RGB", size, "#203040")
    draw = ImageDraw.Draw(image)
    for x in range(0, size[0], 30):
        draw.line((x, 0, size[0] - x, size[1]), fill=(x % 256, 170, 90), width=5)
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=95)
    body = buffer.getvalue()
    digest = hashlib.sha256(body).hexdigest()
    relative = f"player-photos/S23/{digest}.jpg"
    path = media_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {"url": f"/media/{relative}", "sha256": digest, "path": relative}, body


def test_static_thumbnail_is_small_content_addressed_and_preserves_original(tmp_path):
    media = tmp_path / "media"
    photo, original = _photo(media)
    files = [photo]

    mapping = photo_thumbnails.create_thumbnails(media, files)

    assert (media / photo["path"]).read_bytes() == original
    assert len(files) == 2
    assert set(mapping) == {photo["url"]}
    generated = media / mapping[photo["url"]].removeprefix("/media/")
    assert hashlib.sha256(generated.read_bytes()).hexdigest() == generated.stem
    assert generated.suffix == ".webp"
    assert generated.stat().st_size < len(original) / 3
    with Image.open(generated) as image:
        assert image.format == "WEBP"
        assert image.width <= 480 and image.height <= 854
        assert image.width / image.height == pytest.approx(1440 / 2560, abs=.002)


def test_thumbnail_does_not_upscale_small_photos(tmp_path):
    photo, _ = _photo(tmp_path / "media", size=(100, 180))
    mapping = photo_thumbnails.create_thumbnails(tmp_path / "media", [photo])
    with Image.open(tmp_path / "media" / mapping[photo["url"]].removeprefix("/media/")) as image:
        assert image.size == (100, 180)


def test_invalid_photo_fails_instead_of_publishing_a_broken_thumbnail(tmp_path):
    photo, _ = _photo(tmp_path / "media")
    (tmp_path / "media" / photo["path"]).write_bytes(b"invalid image")
    with pytest.raises(ValueError, match="Cannot create player photo thumbnail"):
        photo_thumbnails.create_thumbnails(tmp_path / "media", [photo])
