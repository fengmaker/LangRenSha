from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest

from scripts.game_derivations import apply_precomputed, derive_game
from scripts.game_timeline import build_game_timeline
from website.api import publisher

ROOT = Path(__file__).resolve().parents[2]
api = importlib.import_module('website.api.app')


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
def test_game_detail_api_uses_the_same_sequence_as_the_review_page(bvid, monkeypatch):
    folder = next((ROOT / 'data/extractions/S23/incremental').glob(bvid + '_*'))
    candidate = json.loads((folder / 'candidate.json').read_text(encoding='utf-8'))
    # Historical incremental sidecars bind older rule hashes. This parity test
    # needs a current, in-memory report; stale-report rejection is tested apart.
    report = derive_game(candidate['dossier'], candidate['voting'])['derivations']
    records = apply_precomputed(candidate['dossier'], candidate['voting'], report)
    dossier, voting = records['dossier'], records['voting']
    _, rules = publisher._logical_rules(ROOT, 'S23')
    public = publisher._public_game(dossier, voting, {}, None, rules['boards'][dossier['board']],
                                    {s['name']: f'person-{s["seat"]}' for s in dossier['seats']})
    public['release_id'] = 'fixture-release'
    before = deepcopy(public)

    class Connection:
        def execute(self, query, params):
            return self

        def fetchone(self):
            return {'snapshot': public, 'search_text': api._search_text(public)}

    monkeypatch.setattr(api, '_release', lambda conn: {'id': 'fixture-release'})
    response = api.GameDetail(**api.game_detail(public['id'], Connection())).model_dump()
    expected = build_game_timeline(dossier, voting)
    assert [(p['number'], p['phase'], p['terminal']) for p in response['timeline']['phases']] == [
        (p['number'], p['phase'], p['terminal']) for p in expected['phases']]
    for actual_phase, review_phase in zip(response['timeline']['phases'], expected['phases']):
        assert [(i['kind'], i['slot'], i['title'], i.get('text')) for i in actual_phase['items']] == [
            (i['kind'], i['slot'], i['title'], i.get('text')) for i in review_phase['items']]
        def votes(phase):
            return [[(v['voter'], v['target'], v['state']) for v in i['ballot']['votes']]
                    for i in phase['items'] if i['kind'] == 'ballot']
        assert votes(actual_phase) == votes(review_phase)
    assert public == before
