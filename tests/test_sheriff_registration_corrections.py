"""Keep confirmed initial signups separate from the final sheriff candidates."""
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

CORRECTED_CASES = [
    ('BV1D2ak6XExH', [6, 10], [(6, 7), (10, 3)]),
    ('BV1VPaW66EZz', [4, 6, 8, 11, 12], [(4, 7), (6, None), (8, 5), (11, 5), (12, 7)]),
    ('BV1D2ak6XEMa', [3, 8, 12], [(3, 4), (8, 4), (12, 4)]),
    ('BV1UNaQ6kEWR', [4, 5, 9, 12], [(4, 8), (5, 6), (9, 8), (12, 8)]),
    ('BV1zmpB6PEWL', [2, 5, 6, 9, 11], [(2, 4), (5, 1), (6, 4), (9, 1), (11, 4)]),
]


def test_treasure_master_election_has_only_the_two_announced_off_police_voters():
    folder = ROOT / 'data/games/S23/2026-10-01_g02_BV1D2ak6XEji'
    voting = json.loads((folder / 'voting.json').read_text(encoding='utf-8'))
    registration = voting['registrations'][0]
    assert registration['off_police'] == [3, 11]
    assert registration['on_police'] == [1, 2, 4, 5, 6, 7, 8, 9, 10, 12]
    initial, pk = [ballot for ballot in voting['ballots'] if ballot['kind'] == 'sheriff']
    assert initial['candidates'] == [1, 8, 12]
    assert initial['eligible_voters'] == [3, 11]
    assert initial['votes'] == [
        {'voter': 3, 'target': 8, 'state': 'cast'},
        {'voter': 11, 'target': 12, 'state': 'cast'},
    ]
    assert initial['tied_candidates'] == [8, 12]
    assert pk['winner'] == 12 and len(pk['votes']) == 10


def test_corrected_registration_survives_candidate_rebuild_and_keeps_final_candidates_separate():
    from s23_effective_game import load_effective_game
    from scripts.game_timeline import build_game_timeline

    game = load_effective_game('BV1D2ak6XEji', require_complete=True)
    voting = game['voting']
    assert voting['registrations'][0]['off_police'] == [3, 11]
    assert voting['ballots'][0]['eligible_voters'] == [3, 11]
    dossier = json.loads((ROOT / game['entry']['output_dir'] / 'dossier.json').read_text(encoding='utf-8'))
    phases = build_game_timeline(dossier, voting)['phases']
    first_day = next(phase for phase in phases if phase['number'] == 1 and phase['phase'] == 'day')
    signup = [item for item in first_day['items'] if item['slot'] == 'sheriff_candidates']
    assert [item['title'] for item in signup] == ['首次上警', '退水后候选']
    assert signup[0]['text'].split('\n警下：')[1] == '3号亚亚（摄梦人）、11号蛋黄派（平民）。'
    assert signup[0]['events'][0]['targets'] == [1, 2, 4, 5, 6, 7, 8, 9, 10, 12]
    assert signup[1]['events'][0]['targets'] == [1, 8, 12]


@pytest.mark.parametrize('bvid,off_police,expected_votes', CORRECTED_CASES)
def test_confirmed_sheriff_electorates_remove_ineligible_voters(bvid, off_police, expected_votes):
    folder = next((ROOT / 'data/games/S23').glob('*' + bvid))
    voting = json.loads((folder / 'voting.json').read_text(encoding='utf-8'))
    registration = next(row for row in voting['registrations'] if row['day'] == 1)
    assert registration['off_police'] == off_police
    assert registration['on_police'] == [seat for seat in range(1, 13) if seat not in off_police]
    ballot = next(row for row in voting['ballots'] if row['day'] == 1 and row['kind'] == 'sheriff')
    assert ballot['eligible_voters'] == off_police
    assert [(vote['voter'], vote['target']) for vote in ballot['votes']] == expected_votes
    assert ballot['status'] == 'complete' and ballot['unrecorded_voters'] == []
    assert all(vote['state'] == ('abstained' if vote['target'] is None else 'cast') for vote in ballot['votes'])


@pytest.mark.parametrize('bvid,off_police,expected_votes', CORRECTED_CASES)
def test_confirmed_corrections_survive_rebuilding_and_render_with_the_right_signup(bvid, off_police, expected_votes):
    from s23_effective_game import load_effective_game
    from scripts.game_timeline import build_game_timeline

    game = load_effective_game(bvid, require_complete=True)
    folder = ROOT / game['entry']['output_dir']
    voting = json.loads((folder / 'voting.json').read_text(encoding='utf-8'))
    assert game['voting'] == voting
    dossier = json.loads((folder / 'dossier.json').read_text(encoding='utf-8'))
    phases = build_game_timeline(dossier, voting)['phases']
    day = next(phase for phase in phases if phase['number'] == 1 and phase['phase'] == 'day')
    signup = next(item for item in day['items'] if item['slot'] == 'sheriff_candidates')
    assert signup['events'][0]['off_police'] == off_police
    assert signup['events'][0]['targets'] == [seat for seat in range(1, 13) if seat not in off_police]
