from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest

from scripts.game_derivations import apply_precomputed
from scripts.game_timeline import build_game_timeline
from website.api import publisher

ROOT = Path(__file__).resolve().parents[2]
api = importlib.import_module('website.api.app')


@pytest.mark.parametrize('bvid', ['BV1cJxc6zEgf', 'BV1FJxc6zEzg', 'BV1RQx364EVx'])
def test_game_detail_api_uses_the_same_sequence_as_the_review_page(bvid, monkeypatch):
    folder = next((ROOT / 'data/extractions/S23/incremental').glob(bvid + '_*'))
    candidate = json.loads((folder / 'candidate.json').read_text(encoding='utf-8'))
    report = json.loads((folder / 'rule_derivations.json').read_text(encoding='utf-8'))
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
            return {'snapshot': public}

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
