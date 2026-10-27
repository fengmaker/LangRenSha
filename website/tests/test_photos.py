from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
    progress = json.loads(Path("data/reports/S23_逐局复核进度.json").read_text(encoding="utf-8"))
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

    report = json.loads(Path("data/reports/S23_网站照片准备验收.json").read_text(encoding="utf-8"))
    assert report["candidate_dossier_count"] == 75
    assert report["target_player_count"] == 51
    assert report["covered_player_count"] == 51
    assert report["coverage_rate"] == 1.0
    assert report["missing"] == []
    assert report["alias_matched_count"] == 1
    assert report["aliases_used"][0]["photo_id"] == "P0205"


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
