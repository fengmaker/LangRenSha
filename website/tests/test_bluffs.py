from copy import deepcopy
import pytest

from website.api.bluffs import (
    aggregate_bluffs, claim_fingerprint, evaluate_success, review_items, source_fingerprint,
    success_fingerprint,
)


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
            "voting": {"days": [{"day": 1, "sheriff": "recorded", "exile": "recorded"}], "ballots": []},
            "bluff_evidence_sources": {"e" * 64: "a" * 64}}


def review(game, decision="yes"):
    payload = {"games": [{"game_id": game["id"], "source_fingerprint": source_fingerprint(game),
                      "assessments": [{"seat": 1, "name": "狼甲", "physical_role": "狼人",
                                       "decision": decision, "claimed_role": "通灵师", "claim_day": 1, "confidence": "high",
                                       "evidence": [{"kind": "recap", "text": "1号悍跳狼人",
                                                    "source_ref": "e" * 64, "source_sha256": "a" * 64}]},
                                      {"seat": 4, "name": "狼乙", "physical_role": "机械狼",
                                       "decision": "no", "confidence": "medium", "evidence": []}]}]}
    return sign_assessments(game, payload)


def sign_assessments(game, payload):
    record = payload["games"][0]
    for assessment in record["assessments"]:
        assessment["claim_fingerprint"] = claim_fingerprint(game, assessment)
        assessment["success_fingerprint"] = success_fingerprint(
            game, assessment["seat"], assessment.get("claim_day", 1),
            result_review=record.get("result_review"),
        )
    return payload


@pytest.mark.parametrize('manual_result', [True, False, None])
@pytest.mark.parametrize('change', ['missing_signatures', 'effective_faction', 'evidence_source'])
def test_user_confirmed_result_stays_locked_until_the_user_explicitly_changes_it(manual_result, change):
    game = sample()
    payload = review(game)
    row = payload['games'][0]['assessments'][0]
    row.update(verification_status='user_confirmed', manual_success=manual_result,
               decision_note='人工定案，不因技术签名变化重置')
    changed = deepcopy(game)
    if change == 'missing_signatures':
        row.pop('claim_fingerprint')
        row.pop('success_fingerprint')
    elif change == 'effective_faction':
        changed['seats'][1]['faction'] = 'werewolf'
    else:
        changed['bluff_evidence_sources']['e' * 64] = 'b' * 64
    original = deepcopy(payload)
    item = next(item for item in review_items([changed], payload) if item['seat'] == 1)
    assert item['decision'] == 'yes'
    assert item['success'] is manual_result
    assert item['success_source'] == 'user'
    assert item['claim_needs_review'] is False
    assert item['success_needs_review'] is False
    assert item['legacy_success_needs_review'] is False
    assert item['decision_note'] == row['decision_note']
    assert payload == original
    stats = aggregate_bluffs([changed], payload)['wolf']
    assert stats['bluff_count'] == 1
    assert stats['bluff_success_rate']['denominator'] == (0 if manual_result is None else 1)


def test_user_confirmed_no_bluff_is_not_reopened_by_evidence_changes():
    game = sample()
    payload = review(game, decision='no')
    payload['games'][0]['assessments'][0]['verification_status'] = 'user_confirmed'
    changed = deepcopy(game)
    changed['bluff_evidence_sources']['e' * 64] = 'b' * 64
    item = next(item for item in review_items([changed], payload) if item['seat'] == 1)
    assert item['decision'] == 'no'
    assert item['claim_needs_review'] is False


def test_unpublished_review_keeps_all_player_counts_incomplete_even_with_unknown_factions():
    game = sample()
    for seat in game["seats"]:
        seat["faction"] = None
    stats = aggregate_bluffs([game], {"games": []})
    assert len(stats) == len(game["seats"])
    assert all(row["bluff_count"] == 0 and row["bluff_count_complete"] is False
               and row["bluff_success_rate"]["rate"] is None for row in stats.values())


def test_bluff_rate_uses_wolf_appearances_and_excludes_undecided_claims():
    games, reviewed = [], []
    for decision in ('yes', 'no', 'uncertain'):
        game = sample()
        game['id'] = decision
        games.append(game)
        reviewed.extend(review(game, decision)['games'])
    mixed = sample()
    mixed['id'] = 'wolf-mixed'
    mixed['seats'][0]['role'] = '混血儿'
    good = sample()
    good['id'] = 'good'
    good['seats'][0].update(role='平民', faction='good')
    unknown = sample()
    unknown['id'] = 'unknown'
    unknown['seats'][0]['faction'] = None
    games.extend([mixed, good, unknown])

    metric = aggregate_bluffs(games, {'games': reviewed})['wolf']['bluff_rate']

    assert (metric['numerator'], metric['denominator'], metric['excluded']) == (1, 3, 2)
    assert metric['rate'] == 1 / 3
    assert metric['game_ids'] == ['yes', 'no', 'wolf-mixed']
    assert aggregate_bluffs([good], {'games': []})['wolf']['bluff_rate']['rate'] is None


def test_bluff_success_samples_match_confirmed_results_and_exclude_pending():
    games, records = [], []
    for gid, result in [('success', True), ('failure', False), ('pending', None)]:
        game = sample()
        game['id'] = gid
        payload = review(game)
        payload['games'][0]['assessments'][0].update(
            verification_status='user_confirmed', manual_success=result)
        games.append(game)
        records.extend(payload['games'])
    metric = aggregate_bluffs(games, {'games': records})['wolf']['bluff_success_rate']
    assert (metric['numerator'], metric['denominator'], metric['excluded']) == (1, 2, 1)
    assert metric['samples'] == [
        {'game_id': 'success', 'positive': 1, 'negative': 0},
        {'game_id': 'failure', 'positive': 0, 'negative': 1},
    ]


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
    item = review_items([changed], payload)[0]
    assert item["decision"] == "yes" and item["success_needs_review"]
    assert aggregate_bluffs([changed], payload)["wolf"]["bluff_success_rate"]["denominator"] == 0
    changed = deepcopy(game)
    changed["seats"][0]["name"] = "另一人"
    assert aggregate_bluffs([changed], payload)["wolf"]["bluff_count"] == 0


def test_changed_effective_faction_reports_inputs_without_changing_a_confirmed_result():
    game = sample(exile=2, badge=3)
    payload = review(game)
    assessment = payload["games"][0]["assessments"][0]
    assessment.update(verification_status="user_confirmed", manual_success=True,
                      decision_note="用户上次确认悍跳成功。")

    changed = deepcopy(game)
    changed["seats"][1]["faction"] = "werewolf"

    assert source_fingerprint(changed) == payload["games"][0]["source_fingerprint"]
    item = next(row for row in review_items([changed], payload) if row["seat"] == 1)
    assert item["decision"] == "yes"
    assert item["success"] is True
    assert item["success_source"] == "user"
    assert item["previous_success"] is True
    assert item["needs_review"] is False
    assert item['input_change_notes']
    assert item["decision_note"] == "用户上次确认悍跳成功。"


def test_unrelated_second_day_ballot_and_other_seat_faction_reuse_both_conclusions():
    game = sample(exile=2, badge=3)
    payload = review(game)
    record = payload["games"][0]["assessments"][0]
    record.update(verification_status="user_confirmed", manual_success=True)

    changed = deepcopy(game)
    changed["seats"][3]["faction"] = "good"
    changed["voting"]["ballots"].append({"kind": "exile", "day": 2, "winner": 4})

    item = next(row for row in review_items([changed], payload) if row["seat"] == 1)
    assert item["decision"] == "yes"
    assert item["success"] is True and item["success_source"] == "user"
    assert item["claim_needs_review"] is False and item["success_needs_review"] is False
    assert item["needs_review"] is False


def test_evidence_source_change_rechecks_claim_but_keeps_previous_decision_and_note():
    game = sample()
    payload = review(game)
    assessment = payload["games"][0]["assessments"][0]
    assessment.update(verification_status="assistant_inferred", decision_note="上次备注保留")
    changed = deepcopy(game)
    changed["bluff_evidence_sources"]["e" * 64] = "b" * 64

    assert source_fingerprint(changed) == payload["games"][0]["source_fingerprint"]
    item = next(row for row in review_items([changed], payload) if row["seat"] == 1)
    assert item["decision"] == "uncertain" and item["claim_needs_review"] is True
    assert item["previous_decision"] == "yes" and item["decision_note"] == "上次备注保留"
    assert item["success"] is None

    unbound = deepcopy(game)
    unbound.pop("bluff_evidence_sources")
    item = next(row for row in review_items([unbound], payload) if row["seat"] == 1)
    assert item["claim_needs_review"] is True


def test_manually_included_mixed_blood_faction_change_does_not_invalidate_speech_claim():
    game = sample()
    game["seats"][0]["role"] = "混血儿"
    payload = review(game)
    row = payload["games"][0]["assessments"][0]
    row.update(physical_role="混血儿", verification_status="user_confirmed",
               manual_included=True, manual_success=True)
    sign_assessments(game, payload)

    changed = deepcopy(game)
    changed["seats"][0]["faction"] = "good"
    item = next(row for row in review_items([changed], payload) if row["seat"] == 1)
    assert item["decision"] == "yes" and item["claim_needs_review"] is False
    assert item["success"] is True


def test_manual_success_with_unknown_claim_day_stays_locked_after_exile_faction_change():
    game = sample(exile=2, badge=3)
    payload = review(game)
    row = payload["games"][0]["assessments"][0]
    row.update(verification_status="user_confirmed", manual_success=True, claim_day=None,
               decision_note="第几天待补，旧成功结论保留")
    sign_assessments(game, payload)

    changed = deepcopy(game)
    changed["seats"][1]["faction"] = "werewolf"
    item = next(row for row in review_items([changed], payload) if row["seat"] == 1)
    assert item["decision"] == "yes" and item["claim_needs_review"] is False
    assert item["success"] is True and item["success_needs_review"] is False
    assert item['input_change_notes']
    assert item["previous_success"] is True and item["decision_note"] == "第几天待补，旧成功结论保留"


def test_legacy_human_results_stay_locked_without_technical_dependency_signatures():
    game = sample()
    payload = review(game)
    assessment = payload["games"][0]["assessments"][0]
    assessment.update(verification_status="user_confirmed", manual_success=True)
    assessment.pop("claim_fingerprint")
    assessment.pop("success_fingerprint")

    current = next(row for row in review_items([game], payload) if row["seat"] == 1)
    assert current["decision"] == "yes" and current["success"] is True
    assert current["legacy_success_needs_review"] is False
    assert current["previous_success"] is True
    changed = deepcopy(game)
    changed["voting"]["ballots"].append({"kind": "exile", "day": 2, "winner": 4})
    stale = next(row for row in review_items([changed], payload) if row["seat"] == 1)
    assert stale["decision"] == "yes" and stale["claim_needs_review"] is False
    assert stale["previous_success"] is True and stale["success"] is True


def test_source_binding_survives_equal_derived_view_but_rejects_changed_identity_or_vote():
    game = sample()
    game["voting"]["ballots"] = [{"id": "vote1", "day": 1, "kind": "exile", "winner": 2,
                                   "votes": [{"voter": 1, "target": 2, "state": "cast"}]}]
    derived_fingerprint = source_fingerprint(game)
    source_fingerprint_value = "a" * 64
    game["bluff_source_binding"] = {
        "derived_fingerprint": derived_fingerprint,
        "source_fingerprint": source_fingerprint_value,
    }
    assert source_fingerprint(game) == source_fingerprint_value

    changed_seat = deepcopy(game)
    changed_seat["seats"][0]["name"] = "新名字"
    assert source_fingerprint(changed_seat) != source_fingerprint_value

    changed_vote = deepcopy(game)
    changed_vote["voting"]["ballots"][0]["votes"][0]["target"] = 4
    assert source_fingerprint(changed_vote) != source_fingerprint_value

    changed_faction = deepcopy(game)
    changed_faction["seats"][1]["faction"] = "werewolf"
    assert source_fingerprint(changed_faction) == source_fingerprint_value


def test_mixed_blood_and_real_information_roles_are_not_wolf_card_bluffs():
    game = sample()
    game["seats"][0]["role"] = "混血儿"
    stats = aggregate_bluffs([game], review(game))
    assert stats["wolf"]["bluff_count"] == 0
    assert stats["seer"]["bluff_count"] == 0


@pytest.mark.parametrize('value', [True, False, None])
def test_manual_success_overrides_rules_including_explicit_unknown(value):
    game = sample(exile=2)
    payload = review(game)
    payload['games'][0]['assessments'][0].update(
        verification_status='user_confirmed', manual_success=value, claim_day=None)
    sign_assessments(game, payload)
    item = review_items([game], payload)[0]
    assert item['success'] is value
    assert item['success_source'] == 'user'
    assert item['success_reasons'][0]['kind'] == 'user_review'
    metric = aggregate_bluffs([game], payload)['wolf']['bluff_success_rate']
    assert metric['denominator'] == (value is not None)
    assert metric['numerator'] == (value is True)


def test_only_explicitly_included_user_reviewed_mixed_blood_is_counted():
    game = sample()
    game['seats'][0]['role'] = '混血儿'
    payload = review(game)
    row = payload['games'][0]['assessments'][0]
    row.update(physical_role='混血儿', verification_status='user_confirmed',
               manual_included=True, manual_success=True)
    sign_assessments(game, payload)
    assert aggregate_bluffs([game], payload)['wolf']['bluff_count'] == 1
    assert review_items([game], payload)[0]['manual_included'] is True
    row['verification_status'] = 'assistant_inferred'
    assert aggregate_bluffs([game], payload)['wolf']['bluff_count'] == 0


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
    sign_assessments(game, payload)
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
    sign_assessments(game, payload)
    result = aggregate_bluffs([game], payload)["wolf"]
    assert result["bluff_count"] == 1
    assert result["bluff_success_rate"]["denominator"] == 0
    assert result["bluff_success_rate"]["excluded"] == 1
