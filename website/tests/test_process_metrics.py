from website.api.process_metrics import election_badge, process_observations


def game(*, seats=None, rounds=None, voting=None, rules_state=None):
    return {
        "id": "metrics-test",
        "seats": seats or [
            {"seat": 1, "role": "狼人"},
            {"seat": 2, "role": "平民"},
            {"seat": 3, "role": "通灵师"},
        ],
        "rounds": rounds or [],
        "voting": voting or {},
        "rules_state": rules_state or {},
    }


def test_saved_first_night_attack_uses_original_target_not_resolved_target():
    snapshot = game(
        rounds=[{"number": 1, "night": [
            {"slot": "wolf_attack", "action": "attack", "targets": [2],
             "resolved_targets": [3], "effects": [{"type": "saved"}]},
            {"slot": "witch_save", "action": "save", "targets": [2]},
        ], "day": [{"slot": "night_deaths", "action": "peaceful", "targets": []}]}],
        rules_state={"living": [{"day": 1, "night_deaths": [], "night_deaths_complete": True}]},
    )

    result = process_observations(snapshot)

    assert result[1]["first_night_targeted"] is False
    assert result[2]["first_night_targeted"] is True
    assert result[3]["first_night_targeted"] is False
    assert result[2]["first_night_death"] is False


def test_incomplete_first_night_deaths_keep_confirmed_positives_but_not_negatives():
    snapshot = game(
        rounds=[{"number": 1, "day": [
            {"slot": "night_deaths", "action": "die", "targets": [3]},
            {"slot": "witch_poison", "action": "poison", "targets": [3]},
        ]}],
        rules_state={"living": [{"day": 1, "night_deaths": [3], "night_deaths_complete": False}]},
    )

    result = process_observations(snapshot)

    assert result[3]["first_night_death"] is True
    assert result[1]["first_night_death"] is None
    assert result[2]["first_night_death"] is None


def test_first_day_exile_does_not_follow_a_later_day_exile():
    snapshot = game(
        rounds=[
            {"number": 1, "day": [{"slot": "sheriff_result", "action": "none", "targets": []}]},
            {"number": 2, "day": [{"slot": "exile_result", "action": "exile", "targets": [2]}]},
        ],
        voting={"days": [{"day": 1, "exile": "not_held"}, {"day": 2, "exile": "recorded"}]},
    )

    result = process_observations(snapshot)

    assert all(row["first_day_exiled"] is False for row in result.values())
    assert result[3]["seer_first_day_exiled"] is False


def test_missing_records_are_unknown_and_only_native_seers_get_seer_metrics():
    snapshot = game(seats=[
        {"seat": 1, "role": "预言家"},
        {"seat": 2, "role": "通灵师"},
        {"seat": 3, "role": "盗宝预言家"},
        {"seat": 4, "role": "平民"},
    ])

    result = process_observations(snapshot)

    assert set(result) == {1, 2, 3, 4}
    assert all(value is None for value in result[1].values())
    assert all(value is None for value in result[2].values())
    assert set(result[3]) == {"first_night_targeted", "first_night_death", "first_day_exiled"}
    assert set(result[4]) == {"first_night_targeted", "first_night_death", "first_day_exiled"}


def test_first_registration_and_deferred_sheriff_election_count_for_native_seer():
    snapshot = game(
        seats=[{"seat": 1, "role": "预言家"}, {"seat": 2, "role": "平民"}],
        rounds=[{"number": 2, "day": [
            {"slot": "sheriff_result", "action": "elected", "targets": [1]},
        ]}],
        voting={"registrations": [
            {"id": "later", "day": 2, "on_police": [], "off_police": [1, 2]},
            {"id": "first", "day": 1, "on_police": [1], "off_police": [2]},
        ]},
    )

    result = process_observations(snapshot)

    assert result[1]["seer_campaign_count"] is True
    assert result[1]["seer_badge_count"] is True
    assert election_badge(snapshot, 1) is True


def test_badge_transfer_does_not_count_as_an_election_for_recipient():
    snapshot = game(
        seats=[
            {"seat": 1, "role": "狼人"},
            {"seat": 2, "role": "预言家"},
            {"seat": 3, "role": "通灵师"},
        ],
        rounds=[{"number": 1, "day": [
            {"slot": "sheriff_result", "action": "elected", "targets": [2]},
            {"slot": "badge", "action": "transfer", "actor": 2, "targets": [3]},
        ]}],
    )

    result = process_observations(snapshot)

    assert result[2]["seer_badge_count"] is True
    assert result[3]["seer_badge_count"] is False
    assert election_badge(snapshot, 3) is False


def test_explicitly_forbidden_attack_is_known_not_targeted_but_missing_targets_are_unknown():
    forbidden = game(rounds=[{"number": 1, "night": [
        {"slot": "wolf_attack", "action": "forbidden", "targets": []},
    ]}])
    missing = game(rounds=[{"number": 1, "night": [
        {"slot": "wolf_attack", "action": "attack", "targets": []},
    ]}])

    forbidden_result = process_observations(forbidden)
    missing_result = process_observations(missing)

    assert all(row["first_night_targeted"] is False for row in forbidden_result.values())
    assert all(row["first_night_targeted"] is None for row in missing_result.values())


def test_recorded_target_in_unknown_attack_event_proves_only_that_positive():
    snapshot = game(rounds=[{"number": 1, "night": [
        {"slot": "wolf_attack", "action": "unknown", "targets": [2]},
    ]}])

    result = process_observations(snapshot)

    assert result[2]["first_night_targeted"] is True
    assert result[1]["first_night_targeted"] is None


def test_explicit_night_one_death_includes_poison_but_not_later_day_skill():
    snapshot = game(
        rounds=[{"number": 1, "night": [
            {"slot": "witch_poison", "action": "poison", "targets": [3]},
        ], "day": [
            {"slot": "night_deaths", "action": "die", "targets": [3]},
            {"slot": "hunter_shot", "action": "shoot", "targets": [1]},
        ]}],
        rules_state={"living": [{"day": 1, "night_deaths": [3], "night_deaths_complete": True}]},
    )

    result = process_observations(snapshot)

    assert result[3]["first_night_death"] is True
    assert result[1]["first_night_death"] is False


def test_explicit_peaceful_or_no_death_event_proves_no_deaths_without_rules_state():
    for action in ("peaceful", "no_death"):
        snapshot = game(rounds=[{"number": 1, "day": [
            {"slot": "night_deaths", "action": action, "targets": []},
        ]}])

        result = process_observations(snapshot)

        assert all(row["first_night_death"] is False for row in result.values())


def test_day_one_exile_and_first_registration_membership_are_per_game_seat_observations():
    snapshot = game(
        rounds=[{"number": 1, "day": [
            {"slot": "exile_result", "action": "exile", "targets": [2]},
        ]}],
        voting={"registrations": [
            {"id": "first", "day": 1, "on_police": [3], "off_police": [1, 2]},
        ]},
    )

    result = process_observations(snapshot)

    assert result[2]["first_day_exiled"] is True
    assert result[1]["first_day_exiled"] is False
    assert result[3]["seer_campaign_count"] is True
    assert set(result) == {1, 2, 3}
