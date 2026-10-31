from copy import deepcopy
from pathlib import Path
import json

import pytest

from scripts.role_constraints import neighbor_puppet_sides, puppet_target, event_constraint
from scripts.game_derivations import derive_game
from scripts.game_inference import _known_god_seats, terminal_last_wolf_king_exile
from scripts.game_timeline import build_game_timeline
from website.api.analytics import compute_player_stats, effective_faction
from website.api.app import _resolved_snapshot
from website.api import publisher

ROOT = Path(__file__).resolve().parents[2]


def sample(target=4):
    roles = ['狼人', '狼人', '狼王', '平民', '平民', '平民', '平民', '平民', '预言家', '女巫', '猎人', '守卫']
    seats = [dict(seat=n, person_id=str(n), name=str(n), role=role,
                  faction='werewolf' if n <= 3 else 'good') for n, role in enumerate(roles, 1)]
    return dict(id='puppet-test', slug='puppet-test', season='S22', date='2026-08-07', phase='regular',
                board={'code': 'neighbor_puppet', 'name': '唯邻是从'}, winner='good', seats=seats,
                players=[dict(id=s['person_id'], **{k:s[k] for k in ('seat','name','role','faction')}) for s in seats],
                rounds=[dict(number=1, night=[dict(slot='puppet_select', action='select', targets=[target])], day=[])],
                voting={'registrations': [], 'ballots': [], 'days': []})


@pytest.mark.parametrize('target', [4, 9, 10, 11, 12])
def test_puppet_follows_wolves_for_every_base_role_and_good_metric(target):
    game = sample(target)
    before = deepcopy(game)
    seat = game['seats'][target-1]
    assert effective_faction(game, seat) == 'werewolf'
    result = compute_player_stats(str(target), [game])
    assert result['good_win_rate']['denominator'] == 0
    assert result['good_sheriff_registration_rate']['denominator'] == 0
    assert result['wolf_vote_rate']['denominator'] == 0
    assert result['seer_follow_rate']['denominator'] == 0
    assert result['werewolf_appearances'] == 1
    assert result['losses'] == 1 and result['wins'] == 0 and result['points'] == -1
    resolved = _resolved_snapshot(game)
    assert resolved['seats'][target-1]['is_puppet']
    assert resolved['seats'][target-1]['faction'] == 'werewolf'
    assert resolved['seats'][target-1]['role'] == seat['role']
    assert game == before


@pytest.mark.parametrize('target,gods,civilians', [(4,4,4), (9,3,5)])
def test_puppet_victory_sides_do_not_grant_a_knife(target, gods, civilians):
    game = sample(target)
    sides = neighbor_puppet_sides(game)
    assert len(sides['god']) == gods and len(sides['civilian']) == civilians
    assert sides['werewolf'] == {1,2,3,target} and sides['knife'] == {1,2,3}
    assert _known_god_seats(game) == sides['god']
    terminal = {'round':1, 'phase':'day'}
    assert not terminal_last_wolf_king_exile(game, 1, {1,2}, {3}, {3}, terminal)
    assert terminal_last_wolf_king_exile(game, 1, {1,2,target}, {3}, {3}, terminal)
    for actor, departed in [(target, set()), (None, {1,2,3})]:
        result = event_constraint(game, 2, 'night', {'slot':'wolf_attack','action':'unknown'},
                                  actor=actor, dead_before=departed, uses={}, used_targets={}, previous={}, learning={})
        assert result['status'] == 'unavailable'


def test_real_civilian_puppet_hides_effect_slot_and_prepares_wolf_faction():
    folder=ROOT/'data/games/S22/2026-08-07_g02_BV1pSuN62Ekr'
    dossier=json.loads((folder/'dossier.json').read_text(encoding='utf-8'))
    voting=json.loads((folder/'voting.json').read_text(encoding='utf-8'))
    prepared=derive_game(dossier, voting)['dossier']
    assert prepared['seats'][3]['role']=='平民' and prepared['seats'][3]['faction']=='werewolf'
    items=[i for p in build_game_timeline(dossier,voting)['phases'] for i in p['items']]
    assert not any(i['slot']=='puppet_skill_effect' for i in items)
    assert not any('no_effect' in i.get('text','') for i in items)
    selection = next(i for i in items if i['slot'] == 'puppet_select')
    assert '4号园长（平民）' in selection['text'] and '胜利阵营为狼人' in selection['text']
    _, rules = publisher._logical_rules(ROOT, 'S22')
    public = publisher._public_game(dossier, voting, {}, None, rules['boards']['neighbor_puppet'],
                                    {seat['name']: str(seat['seat']) for seat in dossier['seats']})
    assert public['seats'][3]['faction'] == 'werewolf' and public['seats'][3]['is_puppet']
    assert public['seats'][3]['role'] == '平民'


def test_puppet_seer_explains_reversal_at_actual_check_without_changing_feedback():
    game=sample(9)
    game['rounds'].append(dict(number=2,night=[dict(slot='seer_check',action='check',actor=9,targets=[1],result='good')],day=[]))
    items=[i for p in build_game_timeline(game)['phases'] for i in p['items']]
    check=next(i for i in items if i['slot']=='seer_check')
    assert '结果为好人' in check['text'] and '傀儡预言家' in check['text'] and '相反' in check['text']
    assert check['events'][0]['result']=='good'
    assert not any(i['slot']=='puppet_skill_effect' for i in items)
