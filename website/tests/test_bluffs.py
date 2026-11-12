from copy import deepcopy
import pytest
from website.api.bluffs import aggregate_bluffs, evaluate_success, physical_wolf


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


def final(game, decision='yes', success=True, *, manual_included=False):
    game['bluff_review_available'] = True
    game['bluffs'] = [{
        'game_id':game['id'], 'seat':1, 'player_id':'wolf', 'name':'狼甲',
        'physical_role':game['seats'][0]['role'], 'decision':decision, 'success':success,
        'manual_included':manual_included, 'verification_status':'user_confirmed',
        'needs_review':decision == 'uncertain' or (decision == 'yes' and success is None),
    }, {'game_id':game['id'], 'seat':4, 'player_id':'wolf2', 'decision':'no',
        'manual_included':False, 'verification_status':'user_confirmed', 'success':None,
        'needs_review':False}]
    return game


def test_final_success_samples_preserve_success_failure_and_unknown_denominators():
    games=[]
    for label, result in [('success',True),('failure',False),('pending',None)]:
        game=sample()
        game['id']=label
        games.append(final(game, success=result))
    stats=aggregate_bluffs(games)['wolf']
    assert stats['bluff_count'] == 3
    metric=stats['bluff_success_rate']
    assert (metric['numerator'],metric['denominator'],metric['excluded']) == (1,2,1)
    assert metric['samples'] == [{'game_id':'success','positive':1,'negative':0},
                                 {'game_id':'failure','positive':0,'negative':1}]


@pytest.mark.parametrize('value',[True,False,None])
def test_final_human_success_is_not_recomputed_from_changed_votes(value):
    game=final(sample(exile=2,badge=1),success=value)
    game['rounds'][0]['day']=[]
    metric=aggregate_bluffs([game])['wolf']['bluff_success_rate']
    assert metric['numerator'] == int(value is True)
    assert metric['denominator'] == int(value is not None)
    assert game['bluffs'][0]['success'] is value


def test_unknown_bluff_is_excluded_but_confirmed_no_is_in_rate_denominator():
    unknown=final(sample(),decision='uncertain',success=None)
    known=final(sample(),decision='no',success=None)
    known['id']='known'
    for row in known['bluffs']: row['game_id']='known'
    result=aggregate_bluffs([unknown,known])['wolf']
    assert result['bluff_count'] == 0 and result['bluff_count_complete'] is False
    assert result['bluff_rate']['denominator'] == 1
    assert result['bluff_rate']['excluded'] == 1


def test_missing_review_keeps_good_only_players_counts_incomplete():
    game=sample()
    game['bluffs']=[]
    game['bluff_review_available']=False
    assert aggregate_bluffs([game])['good']['bluff_count_complete'] is False


def test_explicitly_included_mixed_blood_keeps_its_final_bluff_result():
    game=sample()
    game['seats'][0].update(role='混血儿',faction='good')
    assert not physical_wolf(game,game['seats'][0])
    final(game,manual_included=True)
    assert aggregate_bluffs([game])['wolf']['bluff_count'] == 1
    assert aggregate_bluffs([game])['wolf']['bluff_rate']['numerator'] == 1


def test_success_rule_uses_first_day_team_exile_or_badge_once():
    assert evaluate_success(sample(exile=2,badge=3),1)['value'] is True
    assert evaluate_success(sample(exile=4,badge=1),1)['value'] is True
    both=final(sample(exile=2,badge=1))
    assert len(evaluate_success(both,1)['reasons']) == 2
    assert aggregate_bluffs([both])['wolf']['bluff_success_rate']['numerator'] == 1


def test_final_pk_result_overrides_initial_ballot_and_unknown_is_not_failure():
    game=sample(exile=4,badge=3)
    game['voting']['ballots']=[{'kind':'exile','day':1,'winner':2},
                               {'kind':'exile','day':1,'winner':4}]
    assert evaluate_success(game,1)['value'] is False
    assert evaluate_success(sample(exile=None,badge=3),1)['value'] is None
