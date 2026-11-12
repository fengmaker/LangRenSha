from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest

from scripts.game_derivations import apply_precomputed, derive_game
from scripts.game_timeline import build_game_timeline
from final_fixtures import final_game
from website.public_data import _resolved_game

ROOT = Path(__file__).resolve().parents[2]



def _game_with_recorded_rush_day(day):
    def event(slot, action, *, actor=None, targets=None):
        return {'slot': slot, 'action': action, 'actor': actor, 'targets': list(targets or []),
                'result': None, 'description': f'记录槽：{slot}', 'effects': [],
                'availability': None, 'votes': []}

    return {
        'board': {'code': 'mixed_blood', 'name': 'mixed_blood'},
        'seats': [{'seat': 1, 'role': '狼人', 'learned_role': None}],
        'rounds': [
            {'number': 1, 'night': [event('night_deaths', 'peaceful')],
             'day': [event('self_destruct', 'self_destruct', actor=1)]},
            {'number': 2, 'night': [event('night_deaths', 'peaceful')],
             'day': [event('exile_result', 'exile', targets=[1])]},
        ],
        'voting': {'days': [], 'ballots': [], 'registrations': []},
        'winner': 'werewolf',
        'endgame': {'review_status': 'recorded', 'phases': [{
            'kind': 'wolf_rush', 'day': day, 'actor': None,
            'declared_targets': [1, 2], 'result': 'werewolf_win',
        }]},
    }


def test_recorded_endgame_with_unknown_day_does_not_invent_a_terminal_round():
    source = _game_with_recorded_rush_day(None)
    before = deepcopy(source)

    timeline = build_game_timeline(source)

    assert [(phase['number'], phase['phase']) for phase in timeline['phases']] == [
        (1, 'night'), (1, 'day'), (2, 'night'), (2, 'day')]
    assert not any(phase['terminal'] for phase in timeline['phases'])
    assert source == before


def test_recorded_endgame_with_invalid_non_null_day_is_an_internal_error():
    with pytest.raises(ValueError, match='拍刀游戏日不合法'):
        build_game_timeline(_game_with_recorded_rush_day('unknown'))


@pytest.mark.parametrize('bvid', ['BV1cJxc6zEgf', 'BV1FJxc6zEzg', 'BV1RQx364EVx'])
def test_static_game_detail_uses_the_same_sequence_as_the_review_page(bvid):
    public = final_game('S23', bvid)
    before = deepcopy(public)
    response = _resolved_game(public, 'fixture-release')
    expected = build_game_timeline(public)
    assert response['timeline'] == expected
    assert public == before
