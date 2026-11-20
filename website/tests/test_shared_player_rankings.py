from website.public_data import ROOT, build_public_data
from website.static_publish.player_rankings import restore_player_rankings, split_player_rankings


def test_real_player_profiles_round_trip_through_shared_static_rankings():
    direct = build_public_data(ROOT)
    documents = direct["documents"]
    shared_by_range = {}
    checked_profiles = set()

    for name, profile in documents.items():
        if not name.startswith("players/") or "--" not in name.rsplit("/", 1)[-1]:
            continue
        compact, shared = split_player_rankings(profile)
        range_name = name.rsplit("/", 1)[-1]
        if range_name in shared_by_range:
            assert shared_by_range[range_name] == shared
        else:
            shared_by_range[range_name] = shared
        assert "ranking_boards" not in compact["stats"]
        assert restore_player_rankings(compact, shared) == profile
        checked_profiles.add(name)

    expected_ranges = {f"{start}--{end}.json" for start, end in (
        ("S21", "S21"), ("S21", "S22"), ("S21", "S23"),
        ("S22", "S22"), ("S22", "S23"), ("S23", "S23"),
    )}
    assert set(shared_by_range) == expected_ranges
    assert checked_profiles == {
        f"players/{player['id']}/{range_name}" for player in direct["player_index"]["items"]
        for range_name in expected_ranges
    }
