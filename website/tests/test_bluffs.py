from copy import deepcopy

from website.api.bluffs import aggregate_bluffs, evaluate_success, review_items, source_fingerprint


def sample(*, exile=2, badge=3, phase="regular"):
    seats = [
        {"seat": 1, "person_id": "wolf", "name": "狼甲", "role": "狼人", "faction": "werewolf"},
        {"seat": 2, "person_id": "good", "name": "好甲", "role": "平民", "faction": "good"},
        {"seat": 3, "person_id": "seer", "name": "预甲", "role": "通灵师", "faction": "good"},
        {"seat": 4, "person_id": "wolf2", "name": "狼乙", "role": "机械狼", "faction": "werewolf"},
    ]
    events = [{"slot": "sheriff_result", "action": "elected", "targets": [badge]}]
    if exile is not None:
        events.append({"slot": "exile_result", "action": "exile", "targets": [exile]})
    return {"id": "test-game", "season": "S22", "date": "2026-06-01", "phase": phase,
            "seats": seats, "rounds": [{"number": 1, "day": events}],
            "voting": {"days": [{"day": 1, "sheriff": "recorded", "exile": "recorded"}], "ballots": []}}


def review(game, decision="yes"):
    return {"games": [{"game_id": game["id"], "source_fingerprint": source_fingerprint(game),
                      "assessments": [{"seat": 1, "name": "狼甲", "physical_role": "狼人",
                                       "decision": decision, "claimed_role": "通灵师", "claim_day": 1, "confidence": "high",
                                       "evidence": [{"kind": "recap", "text": "1号悍跳狼人"}]},
                                      {"seat": 4, "name": "狼乙", "physical_role": "机械狼",
                                       "decision": "no", "confidence": "medium", "evidence": []}]}]}


def test_team_first_day_good_exile_succeeds_without_personal_call_or_majority():
    game = sample(exile=2, badge=3)
    game["voting"]["ballots"] = [{"id": "vote1", "day": 1, "kind": "exile", "winner": 2,
                                   "votes": [{"voter": 1, "target": 4, "state": "cast"}]}]
    stats = aggregate_bluffs([game], review(game))["wolf"]
    assert stats["bluff_count"] == 1
    assert stats["bluff_success_rate"]["rate"] == 1
    assert evaluate_success(game, 1)["reasons"][0]["target"] == 2


def test_badge_alone_succeeds_and_repeated_conditions_do_not_double_count():
    game = sample(exile=4, badge=1)
    assert evaluate_success(game, 1)["value"] is True
    both = sample(exile=2, badge=1)
    stats = aggregate_bluffs([both], review(both))["wolf"]
    assert stats["bluff_success_rate"]["numerator"] == 1
    assert len(evaluate_success(both, 1)["reasons"]) == 2


def test_later_good_exile_and_badge_transfer_do_not_replace_first_day_conditions():
    game = sample(exile=4, badge=3)
    game["rounds"].append({"number": 2, "day": [
        {"slot": "exile_result", "action": "exile", "targets": [2]},
        {"slot": "badge", "action": "transfer", "targets": [1]},
    ]})
    assert evaluate_success(game, 1)["value"] is False


def test_self_destruct_does_not_move_first_day_to_the_first_vote_day():
    game = sample(exile=None, badge=3)
    game["voting"]["days"][0]["exile"] = "interrupted_self_destruct"
    game["rounds"].append({"number": 2, "day": [
        {"slot": "exile_result", "action": "exile", "targets": [2]}]})
    assert evaluate_success(game, 1)["value"] is False


def test_final_result_overrides_initial_pk_ballot_and_unknown_is_not_failure():
    game = sample(exile=4, badge=3)
    game["voting"]["ballots"] = [{"kind": "exile", "day": 1, "winner": 2},
                                   {"kind": "exile", "day": 1, "winner": 4}]
    assert evaluate_success(game, 1)["value"] is False
    game = sample(exile=None, badge=3)
    result = aggregate_bluffs([game], review(game))["wolf"]
    assert result["bluff_count"] == 1
    assert result["bluff_success_rate"]["rate"] is None
    assert result["bluff_success_rate"]["excluded"] == 1
    assert result["bluff_review_count"] == 1


def test_candidate_and_badge_without_bluff_evidence_never_create_a_bluff():
    game = sample(badge=1)
    payload = review(game, decision="uncertain")
    stats = aggregate_bluffs([game], payload)["wolf"]
    assert stats["bluff_count"] == 0 and stats["bluff_count_complete"] is False
    assert stats["bluff_success_rate"]["denominator"] == 0
    payload["games"][0]["assessments"][0]["decision"] = "yes"
    payload["games"][0]["assessments"][0]["evidence"] = []
    assert aggregate_bluffs([game], payload)["wolf"]["bluff_count"] == 0


def test_stale_identity_or_result_cannot_reuse_old_inference():
    game = sample()
    payload = review(game)
    changed = deepcopy(game)
    changed["rounds"][0]["day"][1]["targets"] = [4]
    stats = aggregate_bluffs([changed], payload)["wolf"]
    assert stats["bluff_count"] == 0 and stats["bluff_pending_games"] == 1
    assert "变化" in review_items([changed], payload)[0]["review_questions"][0]
    changed = deepcopy(game)
    changed["seats"][0]["name"] = "另一人"
    assert aggregate_bluffs([changed], payload)["wolf"]["bluff_count"] == 0


def test_mixed_blood_and_real_information_roles_are_not_wolf_card_bluffs():
    game = sample()
    game["seats"][0]["role"] = "混血儿"
    stats = aggregate_bluffs([game], review(game))
    assert stats["wolf"]["bluff_count"] == 0
    assert stats["seer"]["bluff_count"] == 0


def test_unknown_badge_after_deferral_is_not_proven_absent_by_later_not_applicable():
    game = sample(exile=4)
    game["rounds"][0]["day"][0] = {"slot": "sheriff_result", "action": "deferred", "targets": []}
    game["voting"]["days"] = [{"day": 1, "sheriff": "deferred", "exile": "recorded"},
                               {"day": 2, "sheriff": "not_applicable", "exile": "recorded"}]
    assert evaluate_success(game, 1)["value"] is None


def test_explicit_badge_loss_and_complete_final_pk_tie_are_known_results():
    game = sample(exile=4)
    game["rounds"][0]["day"][0] = {"slot": "sheriff_result", "action": "none", "targets": []}
    assert evaluate_success(game, 1)["value"] is False
    game["rounds"][0]["day"][0]["action"] = "unknown"
    game["voting"]["ballots"] = [{"kind": "sheriff", "day": 1, "stage": "pk", "status": "complete",
        "eligible_voters": [2, 4], "winner": None,
        "votes": [{"voter": 2, "state": "cast", "target": 1}, {"voter": 4, "state": "cast", "target": 3}]}]
    assert evaluate_success(game, 1)["value"] is False
    game["voting"]["ballots"][0]["votes"].pop()
    assert evaluate_success(game, 1)["value"] is None


def test_later_claim_cannot_reuse_earlier_badge_or_first_day_good_exile():
    game = sample(exile=2, badge=1)
    assert evaluate_success(game, 1, claim_day=2)["value"] is False
    assert evaluate_success(game, 1, claim_day=None)["value"] is None
    game["rounds"][0]["day"][0]["action"] = "deferred"
    game["rounds"].append({"number": 2, "day": [
        {"slot": "sheriff_result", "action": "elected", "targets": [1]}]})
    assert evaluate_success(game, 1, claim_day=2)["value"] is True


def test_human_confirmation_can_resolve_previously_missing_claim_evidence():
    game = sample()
    payload = review(game)
    row = payload["games"][0]["assessments"][0]
    row["evidence"] = []
    row["verification_status"] = "user_confirmed"
    assert aggregate_bluffs([game], payload)["wolf"]["bluff_count"] == 1


def test_complete_all_police_registration_proves_no_badge_but_partial_list_does_not():
    game = sample(exile=1)
    game["rounds"][0]["day"][0]["action"] = "unknown"
    game["voting"]["registrations"] = [{"day": 1, "on_police": [1, 2, 3, 4], "off_police": []}]
    assert evaluate_success(game, 1)["value"] is False
    game["voting"]["registrations"][0]["on_police"].pop()
    assert evaluate_success(game, 1)["value"] is None
    game["voting"]["registrations"][0]["on_police"].append(4)
    game["voting"]["registrations"][0]["off_police"] = None
    assert evaluate_success(game, 1)["value"] is None


def test_confirmed_bluff_without_day_is_counted_while_success_remains_unknown():
    game = sample()
    payload = review(game)
    row = payload["games"][0]["assessments"][0]
    row.update(claim_day=None, verification_status="user_confirmed")
    result = aggregate_bluffs([game], payload)["wolf"]
    assert result["bluff_count"] == 1
    assert result["bluff_success_rate"]["denominator"] == 0
    assert result["bluff_success_rate"]["excluded"] == 1
