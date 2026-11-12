from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from website.api.photos import MANIFEST_PATH, PHOTO_ROOT, manifest, photo_for


def game_names(season: str) -> set[str]:
    return {
        player["name"]
        for path in Path(f"data/games/{season}").glob("*/game.json")
        for player in json.loads(path.read_text(encoding="utf-8"))["players"]
    }


def test_photo_preparation_preserves_baseline_records_without_historical_review_inputs(monkeypatch):
    from website import prepare_photos

    original = prepare_photos.read_json(prepare_photos.OUTPUT_JSON)
    with TemporaryDirectory(prefix="photo-preparation-", dir=prepare_photos.ROOT / "tmp") as directory:
        output = Path(directory)
        (output / "player_photos.json").write_bytes(prepare_photos.OUTPUT_JSON.read_bytes())
        shutil.copytree(prepare_photos.OUTPUT_ASSETS, output / "player-photos")
        monkeypatch.setattr(prepare_photos, "OUTPUT_JSON", output / "player_photos.json")
        monkeypatch.setattr(prepare_photos, "OUTPUT_ASSETS", output / "player-photos")
        assert prepare_photos.build() == original
        assert not hasattr(prepare_photos, "MAPPING_CSV")
        assert not hasattr(prepare_photos, "SOURCE_INDEX_JSON")
        assert not hasattr(prepare_photos, "REVIEW_CSV")


def test_new_s23_player_uses_incremental_evidence_and_keeps_stable_photo_ids(tmp_path, monkeypatch):
    from website import prepare_photos

    baseline = prepare_photos.read_json(prepare_photos.OUTPUT_JSON)
    baseline_record = baseline["players"]["S23"]["天星"]
    monkeypatch.setattr(prepare_photos, "ROOT", tmp_path)
    output = tmp_path / "website/api/player_photos.json"
    assets = tmp_path / "website/assets/player-photos"
    output.parent.mkdir(parents=True)
    shutil.copyfile(prepare_photos.OUTPUT_JSON, output)
    shutil.copytree(prepare_photos.OUTPUT_ASSETS, assets)
    config = tmp_path / "config"
    config.mkdir()
    shutil.copyfile(Path("config/seasons.json"), config / "seasons.json")
    monkeypatch.setattr(prepare_photos, "OUTPUT_JSON", output)
    monkeypatch.setattr(prepare_photos, "OUTPUT_ASSETS", assets)

    game = tmp_path / "data/games/S23/game/game.json"
    game.parent.mkdir(parents=True)
    game.write_text(json.dumps({"players": [{"name": "天星"}, {"name": "新选手"}]}), encoding="utf-8")

    archive = tmp_path / "data/raw/weibo/window"
    archive.mkdir(parents=True)
    image = archive / "nameplate.jpg"
    image.write_bytes(b"new official photo")
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    source_url = "https://m.weibo.cn/detail/5358654468915627"
    (archive / "manifest.json").write_text(json.dumps({
        "request": {"uid": "7525583841"}, "posts": [{
            "post_id": "5358654468915627", "post_url": source_url,
            "author_uid": "7525583841", "text": "第23季阵容公告",
            "images": [{"file": "nameplate.jpg", "status": "downloaded", "sha256": sha}],
        }]}), encoding="utf-8")
    index = tmp_path / "data/weibo/window/S23_增量照片名牌核对.json"
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps({
        "season": "S23", "verification_method": "assistant_nameplate_read",
        "source_manifest": "data/raw/weibo/window/manifest.json", "photos": [{
            "name": "新选手", "nameplate_text": "新选手", "source_image": "data/raw/weibo/window/nameplate.jpg",
            "sha256": sha, "source_url": source_url, "source_date": "2026-10-27",
            "post_id": "5358654468915627", "image_index": 1,
        }],
    }), encoding="utf-8")

    result = prepare_photos.build("S23")
    assert result["players"]["S23"]["天星"] == baseline_record
    assert result["players"]["S23"]["新选手"]["photo_id"] == "WB5358654468915627_01"
    assert not (tmp_path / "data/reports/S23/S23_网站照片准备验收.json").exists()


def test_photo_assets_cover_current_s22_players():
    data = manifest()
    names = game_names("S22")
    assert set(data["players"]["S22"]) == names
    assert len(names) == 62 and not data["missing"]
    assert "source_image" not in MANIFEST_PATH.read_text(encoding="utf-8")
    for season, people in data["players"].items():
        for name, record in people.items():
            asset = PHOTO_ROOT / record["asset"]
            assert record["season"] == season == asset.parent.name
            assert hashlib.sha256(asset.read_bytes()).hexdigest() == record["sha256"]
            photo = photo_for(name, season)
            assert photo and photo["source_url"].startswith("https://m.weibo.cn/detail/")
    assert photo_for("JY", "S99") is None
    assert photo_for("不存在的选手", "S22") is None


def test_s23_manifest_covers_canonical_names_from_final_games():
    data = manifest()
    formal_paths = list(Path("data/games/S23").glob("*/game.json"))
    target_names = game_names("S23")
    s23_players = data["players"]["S23"]
    assert target_names <= set(s23_players)
    assert "天星" in s23_players  # Retain the original reviewed S23 roster entry.

    alias = s23_players["天天的星_"]
    name_mapping = alias["name_mapping"]
    assert name_mapping["type"] == "confirmed_same_post_alias"
    assert name_mapping["photo_name"] == "天星"
    assert name_mapping["evidence_url"] == "https://m.weibo.cn/detail/5349233155638005"
    assert name_mapping["evidence_date"] == "2026-10-01"
    assert "P0205" in name_mapping["evidence"] and "天天的星_" in name_mapping["evidence"]
    assert alias["photo_id"] == "P0205"
    assert alias["asset"] == s23_players["天星"]["asset"]
    assert alias["sha256"] == s23_players["天星"]["sha256"]

    formal_names = game_names("S23")
    assert formal_paths
    assert formal_names <= set(s23_players)


def test_s23_photos_cover_players_in_the_current_formal_archive():
    names = game_names("S23")
    missing = sorted(name for name in names if photo_for(name, "S23") is None)
    assert not missing, f"S23 formal players missing website photos: {missing}"


def test_incremental_photo_nameplate_is_bound_to_the_archived_original(tmp_path, monkeypatch):
    from website import prepare_photos

    monkeypatch.setattr(prepare_photos, "ROOT", tmp_path)
    archive = tmp_path / "data/raw/weibo/window"
    archive.mkdir(parents=True)
    image = archive / "nameplate.jpg"
    image.write_bytes(b"original official photo")
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    source_url = "https://m.weibo.cn/detail/5358654468915627"
    (archive / "manifest.json").write_text(json.dumps({
        "request": {"uid": "7525583841"}, "posts": [{
            "post_id": "5358654468915627", "post_url": source_url,
            "author_uid": "7525583841", "text": "第23季阵容公告",
            "images": [{"file": "nameplate.jpg", "status": "downloaded", "sha256": sha}],
        }]}), encoding="utf-8")
    index = tmp_path / "data/weibo/window/S23_增量照片名牌核对.json"
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps({"season": "S23", "verification_method": "assistant_nameplate_read",
        "source_manifest": "data/raw/weibo/window/manifest.json", "photos": [{
            "name": "小张", "nameplate_text": "小张", "source_image": "data/raw/weibo/window/nameplate.jpg",
            "sha256": sha, "source_url": source_url, "source_date": "2026-10-27",
            "post_id": "5358654468915627", "image_index": 1}]}), encoding="utf-8")

    choices, indexes = prepare_photos.incremental_photo_choices({"小张"}, "S23")
    assert indexes == [index]
    assert choices["小张"]["source_path"] == image
    assert choices["小张"]["photo_id"] == "WB5358654468915627_01"
    image.write_bytes(b"a different photo")
    with pytest.raises(ValueError, match="hash mismatch"):
        prepare_photos.incremental_photo_choices({"小张"}, "S23")


def test_s21_manifest_covers_players_from_final_games():
    names = game_names("S21")
    assert names
    players = manifest()["players"].get("S21", {})
    assert set(players) == names
    for name, record in players.items():
        assert hashlib.sha256((PHOTO_ROOT / record["asset"]).read_bytes()).hexdigest() == record["sha256"]
        assert photo_for(name, "S21") is not None
