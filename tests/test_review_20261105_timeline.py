"""Source-bound regressions for the 2026-11-05 review batch."""
import json
from pathlib import Path

from scripts.game_derivations import derive_game
from scripts.game_timeline import build_game_timeline
from scripts.game_review_page import ballot_html

ROOT = Path(__file__).resolve().parents[1]


def candidate(bvid):
    path = next((ROOT / 'data/extractions/S23/incremental').glob(bvid + '*/candidate.json'))
    return json.loads(path.read_text(encoding='utf-8'))


def test_revenge_death_excludes_guard_from_next_ballot_without_changing_signup_vote():
    c = candidate('BV1Ve4861EtL')
    original = json.dumps(c, ensure_ascii=False, sort_keys=True)
    result = derive_game(c['dossier'], c['voting'], endgame=c['endgame'])
    sheriff, exile = result['voting']['ballots']
    assert 12 in sheriff['eligible_voters']
    assert exile['eligible_voters'] == [1, 2, 3, 5, 7, 9, 10, 11]
    assert exile['status'] == 'complete' and not exile['unrecorded_voters']
    assert json.dumps(c, ensure_ascii=False, sort_keys=True) == original
    phases = build_game_timeline({**c['dossier'], 'endgame': c['endgame']}, c['voting'])['phases']
    day = next(p for p in phases if p['number'] == 1 and p['phase'] == 'day')
    slots = [i['slot'] for i in day['items']]
    assert slots.index('night_deaths') < slots.index('self_destruct') < slots.index('wolf_girl_revenge')
    assert phases[-1]['number'] == 2 and phases[-1]['terminal']
    seats = {row['seat']: row for row in c['dossier']['seats']}
    assert '原文明确弃票' in ballot_html({'slot': 'sheriff_vote', 'title': '警长投票', 'ballot': sheriff}, seats)


def test_disqualified_guard_requires_daytime_pursuit_and_user_confirmed_remaining_votes():
    c = candidate('BV1Ve4861Etu')
    phases = build_game_timeline(c['dossier'], c['voting'])['phases']
    night = next(p for p in phases if p['number'] == 2 and p['phase'] == 'night')
    assert '需追刀追投' in next(i['text'] for i in night['items'] if i['slot'] == 'guard')
    last = phases[-1]
    assert last['phase'] == 'day' and last['number'] == 2 and last['terminal']
    death = next(i for i in last['items'] if i['slot'] == 'night_deaths')
    assert death['events'][0]['targets'] == [2, 7, 12]
    b = next(i['ballot'] for i in last['items'] if i['kind'] == 'ballot')
    assert 5 not in b['eligible_voters'] and 5 in b['candidates']
    assert {v['voter']: v['target'] for v in b['votes']} == {1: 8, 3: 8, 4: 5, 6: 5, 8: 5, 9: 5, 11: 8}
    assert c['manual_confirmations'][0]['applied']['cast_8'] == [1, 3, 11]
    slots = [i['slot'] for i in last['items']]
    assert slots.index('exile_vote') < slots.index('exile_result') < slots.index('game_result')


def test_publisher_preserves_revenge_but_not_as_normal_death_for_pursuit_dq():
    from website.api.publisher import _public_supplemental_events
    c = candidate('BV1Ve4861EtL')
    revenge = c['dossier']['_publication_context']['supplemental_events']
    public = _public_supplemental_events({'events': revenge})
    assert public[0]['event']['slot'] == 'wolf_girl_revenge'
    assert public[0]['event']['targets'] == [12]
    assert '报复' in public[0]['event']['slot_label']
    pursuit = {'round': 2, 'phase': 'night', 'event': {'slot': 'guard_disqualification',
        'action': 'disqualify', 'actor': 5, 'targets': [5], 'result': '连守被判离，仍需追刀追投'}}
    assert _public_supplemental_events({'events': [pursuit]}) == []
