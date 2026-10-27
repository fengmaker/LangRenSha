from __future__ import annotations

import pytest

from website.api import bluff_store, publisher


SEASON_COUNTS = {"S22": 148, "S23": 75}


def test_load_release_keeps_both_seasons_in_combined_release(monkeypatch, tmp_path):
    loaded = []

    def fake_load_publication(root, season, sample=None):
        assert root == tmp_path
        assert sample is None
        loaded.append(season)
        entries = [
            {"dossier": {"slug": f"{season}-g{number:03}", "season": season}}
            for number in range(1, SEASON_COUNTS[season] + 1)
        ]
        return entries, f"source-{season}", f"rules-{season}"

    monkeypatch.setattr(publisher, "load_publication", fake_load_publication)

    entries, source_hash, rules_hash = publisher.load_release(tmp_path, ["S23", "S22"])

    assert loaded == ["S22", "S23"]
    assert len(entries) == 223
    assert {season: sum(entry["dossier"]["season"] == season for entry in entries)
            for season in SEASON_COUNTS} == SEASON_COUNTS
    assert len({entry["dossier"]["slug"] for entry in entries}) == 223
    expected_sources = {"S22": "source-S22", "S23": "source-S23"}
    expected_rules = {"S22": "rules-S22", "S23": "rules-S23"}
    assert source_hash == publisher.digest_bytes(publisher.canonical_json(expected_sources))
    assert rules_hash == publisher.digest_bytes(publisher.canonical_json(expected_rules))


@pytest.mark.parametrize("seasons", [["S22", "S22"], ["S23", "S22", "S23"]])
def test_load_release_rejects_duplicate_seasons_before_loading(monkeypatch, tmp_path, seasons):
    def unexpected_load(*args, **kwargs):
        pytest.fail("duplicate seasons must be rejected before loading source data")

    monkeypatch.setattr(publisher, "load_publication", unexpected_load)

    with pytest.raises(publisher.PublishError, match="唯一"):
        publisher.load_release(tmp_path, seasons)


def test_load_release_rejects_single_game_sample_for_multiple_seasons(monkeypatch, tmp_path):
    def unexpected_load(*args, **kwargs):
        pytest.fail("sample-plus-multiseason must be rejected before loading source data")

    monkeypatch.setattr(publisher, "load_publication", unexpected_load)

    with pytest.raises(publisher.PublishError, match="多赛季发布不能指定单局样例"):
        publisher.load_release(tmp_path, ["S22", "S23"], sample="BV1yt7v6QE3Q")


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeCombinedReleaseConnection:
    def __init__(self, season_counts=None):
        self.season_counts = season_counts or SEASON_COUNTS
        self.queries = []

    def execute(self, query, params=None):
        query_text = str(query)
        self.queries.append((query_text, params))
        if query_text.startswith("SELECT r.id, r.season, r.game_count FROM active_release"):
            return FakeCursor({"id": "release-S22_S23", "season": "S22_S23", "game_count": 223})
        if query_text.startswith("SELECT count(*) AS count FROM games WHERE release_id = %s AND season = %s"):
            release_id, season = params
            assert release_id == "release-S22_S23"
            return FakeCursor({"count": self.season_counts.get(season, 0)})
        pytest.fail(f"unexpected query in _active_release: {query_text}")


@pytest.mark.parametrize(("season", "expected_count"), [("S22", 148), ("S23", 75)])
def test_active_release_binds_combined_release_to_requested_season_subset(season, expected_count):
    conn = FakeCombinedReleaseConnection()

    release = bluff_store._active_release(conn, season, lock=False)

    assert release == {
        "id": "release-S22_S23",
        "season": "S22_S23",
        "game_count": expected_count,
        "release_game_count": 223,
    }
    count_query = next(query for query, _ in conn.queries if "SELECT count(*) AS count FROM games" in query)
    assert "season = %s" in count_query
    assert conn.queries[-1][1] == ("release-S22_S23", season)


def test_active_release_rejects_missing_season_in_combined_release():
    conn = FakeCombinedReleaseConnection({"S22": 148})

    with pytest.raises(bluff_store.BluffReviewError, match="赛季不一致"):
        bluff_store._active_release(conn, "S23", lock=False)
