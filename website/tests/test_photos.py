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


def test_photo_endpoint_serves_only_listed_season_assets():
    record = manifest()["players"]["S22"]["JY"]
    with TestClient(app) as client:
        response = client.get("/api/v1/photos/" + record["asset"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert "immutable" in response.headers["cache-control"]
        assert hashlib.sha256(response.content).hexdigest() == record["sha256"]
        filename = record["asset"].split("/")[1]
        assert client.get(f"/api/v1/photos/S99/{filename}").status_code == 404
        assert client.get("/api/v1/photos/S22/" + "0" * 64 + ".jpg").status_code == 404
        assert client.get("/api/v1/photos/S22/player_photos.json").status_code == 404
    assert photo_path("..", filename) is None
    assert photo_path("S22", "../../api/player_photos.json") is None
