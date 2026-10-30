from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from website.api.app import app
from website.api.photos import MANIFEST_PATH, PHOTO_ROOT, manifest, photo_for, photo_path


def test_reviewed_assets_match_hashes_and_cover_current_s22_players():
    data = manifest()
    names = {
        seat["name"]
        for path in Path("data/games/S22").glob("*/dossier.json")
        for seat in json.loads(path.read_text(encoding="utf-8"))["seats"]
    }
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


def test_s23_manifest_covers_canonical_names_from_all_75_candidate_dossiers():
    data = manifest()
    progress = json.loads(Path("data/reports/S23/S23_逐局复核进度.json").read_text(encoding="utf-8"))
    target_names = {
        seat["name"]
        for relative_path in progress["candidate_dossiers"]
        for seat in json.loads(Path(relative_path).read_text(encoding="utf-8"))["seats"]
    }
    s23_players = data["players"]["S23"]
    assert len(progress["candidate_dossiers"]) == 75
    assert len(target_names) == 51
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

    report = json.loads(Path("data/reports/S23/S23_网站照片准备验收.json").read_text(encoding="utf-8"))
    formal_paths = list(Path("data/games/S23").glob("*/dossier.json"))
    formal_names = {seat["name"] for path in formal_paths
                    for seat in json.loads(path.read_text(encoding="utf-8"))["seats"]}
    assert report["formal_dossier_count"] == len(formal_paths)
    assert report["target_player_count"] == len(formal_names)
    assert report["covered_player_count"] == len(formal_names)
    assert report["coverage_rate"] == 1.0
    assert report["missing"] == []
    assert report["alias_matched_count"] == 1
    assert report["aliases_used"][0]["photo_id"] == "P0205"


def test_s23_photos_cover_players_in_the_current_formal_archive():
    names = {
        seat["name"] for path in Path("data/games/S23").glob("*/dossier.json")
        for seat in json.loads(path.read_text(encoding="utf-8"))["seats"]
        if seat.get("name")
    }
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

    choices, indexes = prepare_photos.s23_incremental_photo_choices()
    assert indexes == [index]
    assert choices["小张"]["source_path"] == image
    assert choices["小张"]["photo_id"] == "WB5358654468915627_01"
    image.write_bytes(b"a different photo")
    with pytest.raises(ValueError, match="hash mismatch"):
        prepare_photos.s23_incremental_photo_choices()


def test_s21_manifest_covers_published_players_using_viewed_same_season_nameplates():
    names = {
        seat["name"] for path in Path("data/games/S21").glob("*/dossier.json")
        for seat in json.loads(path.read_text(encoding="utf-8"))["seats"]
    }
    assert names
    source = json.loads(Path(
        "data/weibo/2026-02-24_2026-05-26/S21_姓名照片来源索引.json"
    ).read_text(encoding="utf-8"))
    by_id = {photo["photo_id"]: photo for photo in source["photos"]}
    players = manifest()["players"].get("S21", {})
    assert set(players) == names
    for name, record in players.items():
        photo = by_id[record["photo_id"]]
        assert photo["included_for_review"] and photo["nameplate_observations"]
        labels = photo["normalized_names_from_nameplate"] or photo["nameplate_read_texts"]
        assert name.casefold() in {label.casefold() for label in labels}
        assert record["sha256"] == photo["image_sha256"]
        assert any(occurrence["included_for_review"]
                   and occurrence["post_url"] == record["source_url"]
                   and occurrence["game_date"] == record["source_date"]
                   for occurrence in photo["source_occurrences"])
        assert photo_for(name, "S21") is not None


def test_photo_endpoint_serves_only_listed_season_assets():
    record = manifest()["players"]["S22"]["JY"]
    with TestClient(app) as client:
        response = client.get("/api/v1/photos/" + record["asset"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert "immutable" in response.headers["cache-control"]
        assert hashlib.sha256(response.content).hexdigest() == record["sha256"]
        filename = record["asset"].split("/")[1]
        s23_record = manifest()["players"]["S23"]["天天的星_"]
        s23_response = client.get("/api/v1/photos/" + s23_record["asset"])
        assert s23_response.status_code == 200
        assert hashlib.sha256(s23_response.content).hexdigest() == s23_record["sha256"]
        assert client.get(f"/api/v1/photos/S99/{filename}").status_code == 404
        assert client.get("/api/v1/photos/S22/" + "0" * 64 + ".jpg").status_code == 404
        assert client.get("/api/v1/photos/S22/player_photos.json").status_code == 404
    assert photo_path("..", filename) is None
    assert photo_path("S22", "../../api/player_photos.json") is None
