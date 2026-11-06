from io import BytesIO
import hashlib
import json

import pytest
from PIL import Image, ImageDraw

from website.static_publish import photo_thumbnails
from website.static_publish import check_static as checker
from website.static_publish.check_static import StaticAcceptanceError, _load_snapshot, _read_documents, _structure_check
from website.tests.test_static_acceptance import _snapshot, _write_json
from website.tests.test_incremental_acceptance import _api_fixture


def _photo(media_root, size=(1440, 2560)):
    image = Image.new('RGB', size, '#203040')
    draw = ImageDraw.Draw(image)
    for x in range(0, size[0], 30):
        draw.line((x, 0, size[0] - x, size[1]), fill=(x % 256, 170, 90), width=5)
    buffer = BytesIO()
    image.save(buffer, 'JPEG', quality=95)
    body = buffer.getvalue()
    digest = hashlib.sha256(body).hexdigest()
    relative = f'player-photos/S23/{digest}.jpg'
    path = media_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {'url': f'/media/{relative}', 'sha256': digest, 'path': relative}, body


def test_static_thumbnail_is_small_content_addressed_and_preserves_original_and_frames(tmp_path):
    media = tmp_path / 'media'
    photo, original = _photo(media)
    frame = {'url': '/media/bluff-frames/S23/frame.png', 'path': 'bluff-frames/S23/frame.png'}
    files = [photo, frame]

    mapping = photo_thumbnails.create_thumbnails(media, files)

    assert (media / photo['path']).read_bytes() == original
    assert len(files) == 3
    assert set(mapping) == {photo['url']}
    derived = media.parent / mapping[photo['url']].lstrip('/')
    assert hashlib.sha256(derived.read_bytes()).hexdigest() == derived.stem
    assert derived.suffix == '.webp'
    assert derived.stat().st_size < len(original) / 3
    with Image.open(derived) as image:
        assert image.format == 'WEBP'
        assert image.width <= 600 and image.height <= 1067
        assert image.width / image.height == pytest.approx(1440 / 2560, abs=.002)
    assert frame == files[1]


def test_thumbnail_does_not_upscale_small_photos(tmp_path):
    photo, _ = _photo(tmp_path / 'media', size=(100, 180))
    mapping = photo_thumbnails.create_thumbnails(tmp_path / 'media', [photo])
    with Image.open(tmp_path / mapping[photo['url']].lstrip('/')) as image:
        assert image.size == (100, 180)


def test_incremental_thumbnail_reuses_verified_derivative(tmp_path, monkeypatch):
    previous = tmp_path / 'previous'
    photo, original = _photo(previous / 'media')
    mapping = photo_thumbnails.create_thumbnails(previous / 'media', [photo])
    previous_manifest = {'player_photo_thumbnails': mapping, 'photo_thumbnail_version': photo_thumbnails.VERSION}
    current = tmp_path / 'current'
    current_photo, _ = _photo(current / 'media')
    monkeypatch.setattr(photo_thumbnails, 'thumbnail_bytes', lambda _: pytest.fail('unchanged thumbnail must be reused'))

    assert photo_thumbnails.create_thumbnails(current / 'media', [current_photo], previous, previous_manifest) == mapping
    assert (current / mapping[photo['url']].lstrip('/')).read_bytes() == (previous / mapping[photo['url']].lstrip('/')).read_bytes()
    assert (current / 'media' / photo['path']).read_bytes() == original


def test_invalid_photo_fails_instead_of_publishing_a_broken_thumbnail(tmp_path):
    photo, _ = _photo(tmp_path / 'media')
    (tmp_path / 'media' / photo['path']).write_bytes(b'invalid image')
    with pytest.raises(ValueError, match='Cannot create player photo thumbnail'):
        photo_thumbnails.create_thumbnails(tmp_path / 'media', [photo])


@pytest.mark.parametrize('wrong_image', [False, True])
def test_api_acceptance_preserves_original_binding_and_verifies_derived_thumbnail(tmp_path, monkeypatch, wrong_image):
    out = _snapshot(tmp_path)
    old_source = next((out / 'media/player-photos/S21').iterdir())
    _, body = _photo(tmp_path / 'source')
    original = old_source.with_name(hashlib.sha256(body).hexdigest() + '.jpg')
    original.write_bytes(body)
    old_url = '/' + old_source.relative_to(out).as_posix()
    source_url = '/' + original.relative_to(out).as_posix()
    for path in (out / 'data/releases').rglob('*.json'):
        path.write_text(path.read_text(encoding='utf-8').replace(old_url, source_url), encoding='utf-8')
    old_source.unlink()
    snapshot, docs, _, _, _, get_json = _api_fixture(out)
    files = [{'url': source_url, 'path': original.relative_to(out / 'media').as_posix()}]
    mapping = photo_thumbnails.create_thumbnails(out / 'media', files)
    if wrong_image:
        other_body = photo_thumbnails.thumbnail_bytes(_photo(tmp_path / 'other', size=(100, 180))[1])
        unrelated = original.with_name(hashlib.sha256(other_body).hexdigest() + '.webp')
        unrelated.write_bytes(other_body)
        mapping[source_url] = '/' + unrelated.relative_to(out).as_posix()
    snapshot['manifest']['player_photo_thumbnails'] = mapping
    monkeypatch.setattr(checker, '_get_json', get_json)
    if wrong_image:
        with pytest.raises(StaticAcceptanceError, match='thumbnail differs from its source'):
            checker._api_check(snapshot, docs, 'http://api.test')
    else:
        assert checker._api_check(snapshot, docs, 'http://api.test')['state'] == 'passed'


def test_acceptance_checks_thumbnail_hash_and_source_link(tmp_path):
    out = _snapshot(tmp_path)
    manifest_path = out / 'data/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    source = next((out / 'media/player-photos/S21').iterdir())
    body = photo_thumbnails.thumbnail_bytes(_photo(tmp_path / 'source')[1])
    derivative = source.with_name(hashlib.sha256(body).hexdigest() + '.webp')
    derivative.write_bytes(body)
    source_url = '/' + source.relative_to(out).as_posix()
    manifest['player_photo_thumbnails'] = {source_url: '/' + derivative.relative_to(out).as_posix()}
    manifest['photo_thumbnail_version'] = photo_thumbnails.VERSION
    manifest['counts']['media_files'] += 1
    _write_json(manifest_path, manifest)
    snapshot = _load_snapshot(out, '/example-site')
    assert _structure_check(snapshot, _read_documents(snapshot))['media_references_checked'] == 2

    derivative.write_bytes(b'corrupted thumbnail')
    with pytest.raises(StaticAcceptanceError, match='Media content hash differs'):
        _structure_check(snapshot, _read_documents(snapshot))

    manifest['player_photo_thumbnails'] = {'/media/bluff-frames/S21/invalid.png': manifest['player_photo_thumbnails'][source_url]}
    _write_json(manifest_path, manifest)
    snapshot = _load_snapshot(out, '/example-site')
    with pytest.raises(StaticAcceptanceError, match='thumbnail'):
        _structure_check(snapshot, _read_documents(snapshot), basic=True)
