from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.game_timeline import build_game_timeline

ROOT = Path(__file__).resolve().parents[1]


def reviewed_mixed_game():
    folder = ROOT / 'data/games/S23/2026-10-27_g01_BV1RQx364EaF'
    dossier = json.loads((folder / 'dossier.json').read_text(encoding='utf-8'))
    voting = json.loads((folder / 'voting.json').read_text(encoding='utf-8'))
    return dossier, voting


def test_mixed_first_night_places_alignment_after_model_without_hunter_status():
    dossier, voting = reviewed_mixed_game()
    before = deepcopy(dossier)
    timeline = build_game_timeline(dossier, voting)
    night = timeline['phases'][0]
    slots = [item['slot'] for item in night['items']]
    assert slots[:2] == ['mixed_blood_model', 'mixed_blood_alignment']
    assert 'hunter_state' not in slots
    assert dossier == before


def test_later_phases_hide_spent_once_only_and_unchanged_badge_slots():
    dossier, voting = reviewed_mixed_game()
    timeline = build_game_timeline(dossier, voting)
    later = [phase for phase in timeline['phases'] if phase['number'] > 1]
    slots = [item['slot'] for phase in later for item in phase['items']]
    assert not {'mixed_blood_model', 'mixed_blood_alignment', 'hunter_state',
                'sheriff_candidates', 'sheriff_vote', 'sheriff_result', 'badge'} & set(slots)
    day_two = next(phase for phase in later if phase['phase'] == 'day')
    assert [item['slot'] for item in day_two['items']] == ['night_deaths', 'self_destruct']


def test_ballots_are_inside_their_day_between_registration_and_result():
    dossier, voting = reviewed_mixed_game()
    timeline = build_game_timeline(dossier, voting)
    day = next(phase for phase in timeline['phases'] if phase['phase'] == 'day')
    items = day['items']
    slots = [item['slot'] for item in items]
    assert slots.index('sheriff_candidates') < slots.index('sheriff_vote') < slots.index('sheriff_result')
    assert slots.index('night_deaths') < slots.index('exile_vote') < slots.index('exile_result')
    ballots = [item for phase in timeline['phases'] for item in phase['items'] if item['kind'] == 'ballot']
    assert len(ballots) == 2
    assert sum(len(item['ballot']['votes']) for item in ballots) == 15


def test_night_surrender_stops_before_unplayed_deaths_shots_and_exile():
    dossier, voting = reviewed_mixed_game()
    timeline = build_game_timeline(dossier, voting)
    assert [(phase['number'], phase['phase']) for phase in timeline['phases']] == [
        (1, 'night'), (1, 'day'), (2, 'night'), (2, 'day'), (3, 'night')]
    terminal = timeline['phases'][-1]
    assert terminal['label'] == '第二天夜晚 · 游戏结束'
    assert [item['slot'] for item in terminal['items']] == ['werewolf_surrender']
    assert '11号宝玉妹妹' in terminal['items'][0]['text']
    assert '好人阵营获胜' in terminal['items'][0]['text']


def event(slot, action='unknown', actor=None, targets=(), votes=(), result=None):
    return {'slot': slot, 'action': action, 'actor': actor, 'targets': list(targets),
            'votes': list(votes), 'effects': [], 'result': result}


@pytest.mark.parametrize('board', ['mixed_blood', 'mechanical_wolf_seer'])
def test_hunter_shot_only_appears_at_the_actual_departure(board):
    source = {'board': board, 'seats': [
        {'seat': 1, 'name': '甲', 'role': '狼人'},
        {'seat': 2, 'name': '乙', 'role': '猎人'},
        {'seat': 3, 'name': '丙', 'role': '平民'}], 'rounds': [
            {'number': 1, 'night': [event('hunter_state', 'can_shoot', 2)],
             'day': [event('night_deaths', 'peaceful'), event('hunter_shot', 'unavailable', 2)]},
            {'number': 2, 'night': [event('hunter_state', 'can_shoot', 2)],
             'day': [event('night_deaths', 'die', targets=[2]), event('hunter_shot', 'shoot', 2, [1])]}]}
    phases = build_game_timeline(source)['phases']
    shots = [(phase['number'], phase['phase'], item['slot'])
             for phase in phases for item in phase['items'] if item['slot'] in {'hunter_state', 'hunter_shot'}]
    assert shots == [(2, 'day', 'hunter_shot')]
    day = next(phase for phase in phases if phase['number'] == 2 and phase['phase'] == 'day')
    assert [item['slot'] for item in day['items']][:2] == ['night_deaths', 'hunter_shot']


def test_continued_election_is_kept_without_repeating_registration():
    source = {'board': 'mixed_blood', 'seats': [
        {'seat': 1, 'name': '甲', 'role': '预言家'},
        {'seat': 2, 'name': '乙', 'role': '平民'},
        {'seat': 3, 'name': '丙', 'role': '狼人'},
        {'seat': 4, 'name': '丁', 'role': '平民'}], 'rounds': [
            {'number': 1, 'night': [], 'day': [event('sheriff_candidates', 'register', targets=[1, 2]),
                event('sheriff_result', 'deferred'), event('self_destruct', 'self_destruct', 3)]},
            {'number': 2, 'night': [], 'day': [event('sheriff_candidates', 'continued', targets=[1, 2]),
                event('sheriff_vote', 'vote', votes=[{'round': 1, 'voter': 4, 'target': 1, 'abstained': False}]),
                event('sheriff_result', 'elected', targets=[1])]}]}
    voting = {'registrations': [{'day': 1, 'on_police': [1, 2], 'off_police': [3, 4]}],
              'ballots': [{'id': 'sheriff-2', 'day': 2, 'kind': 'sheriff', 'number': 1,
                           'stage': 'initial', 'votes': [{'voter': 4, 'target': 1, 'state': 'cast'}]}]}
    phases = build_game_timeline(source, voting)['phases']
    first = next(phase for phase in phases if phase['number'] == 1)
    assert [item['slot'] for item in first['items']].index('self_destruct') < [
        item['slot'] for item in first['items']].index('sheriff_result')
    continued = next(phase for phase in phases if phase['number'] == 2)
    assert [item['title'] for item in continued['items']][0] == '继续警长竞选'
    assert [item['kind'] for item in continued['items']] == ['event', 'ballot', 'event']


def test_skill_revote_follows_prince_reveal_instead_of_first_ballot():
    folder = ROOT / 'data/games/S23/2026-10-27_g02_BV1RQx364EVx'
    dossier = json.loads((folder / 'dossier.json').read_text(encoding='utf-8'))
    voting = json.loads((folder / 'voting.json').read_text(encoding='utf-8'))
    phases = build_game_timeline(dossier, voting)['phases']
    first_day = next(phase for phase in phases if phase['phase'] == 'day')
    items = first_day['items']
    exile_indices = [i for i, item in enumerate(items) if item['kind'] == 'ballot' and item['ballot']['kind'] == 'exile']
    reveal_index = next(i for i, item in enumerate(items) if 'prince' in item['slot'] and item['slot'] != 'prince_state')
    assert len(exile_indices) == 2
    assert exile_indices[0] < reveal_index < exile_indices[1]
    assert sum(len(item['ballot']['votes']) for phase in phases for item in phase['items'] if item['kind'] == 'ballot') == 27


def test_real_unknown_attack_is_kept_instead_of_hiding_every_unknown():
    source = {'board': 'mixed_blood', 'seats': [{'seat': 1, 'name': '甲', 'role': '狼人'}],
              'rounds': [{'number': 1, 'night': [event('wolf_attack')], 'day': []}]}
    item = build_game_timeline(source)['phases'][0]['items'][0]
    assert item['slot'] == 'wolf_attack' and '待核' in item['text']


def test_retained_ballots_are_not_lost_when_an_archive_has_no_vote_slot():
    source = {'board': 'mixed_blood', 'seats': [{'seat': 1, 'name': '甲', 'role': '狼人'}],
              'rounds': [{'number': 1, 'night': [], 'day': [event('exile_result')]}]}
    voting = {'ballots': [{'id': 'b1', 'day': 1, 'kind': 'exile', 'number': 1,
                           'stage': 'initial', 'votes': [{'voter': 1, 'target': 1, 'state': 'cast'}]}]}
    items = build_game_timeline(source, voting)['phases'][0]['items']
    assert [item['kind'] for item in items] == ['ballot', 'event']


@pytest.mark.parametrize(('bvid', 'number', 'phase'), [
    ('BV1cJxc6zEbr', 4, 'night'),
    ('BV1kksX6DEK8', 3, 'night'),
    ('BV1cJxc6zEgf', 2, 'day'),
    ('BV1HksX6QEr5', 3, 'day'),
    ('BV1kksX6DEbH', 2, 'day'),
    ('BV1FJxc6zEzg', 4, 'night'),
    ('BV1RQx364Eit', 5, 'day'),
    ('BV1RQx364EVx', 2, 'day'),
])
def test_recorded_latest_game_endings_stop_at_the_actual_phase(bvid, number, phase):
    folder = next((ROOT / 'data/extractions/S23/incremental').glob(bvid + '_*'))
    candidate = json.loads((folder / 'candidate.json').read_text(encoding='utf-8'))
    before = deepcopy(candidate)
    timeline = build_game_timeline(candidate['dossier'], candidate['voting'])
    ending = timeline['phases'][-1]
    assert (ending['number'], ending['phase'], ending['terminal']) == (number, phase, True)
    assert '获胜' in ending['items'][-1]['text']
    assert candidate == before


def test_surrender_note_keeps_the_self_destruct_that_preceded_it():
    folder = next((ROOT / 'data/extractions/S23/incremental').glob('BV1kksX6DEbH_*'))
    candidate = json.loads((folder / 'candidate.json').read_text(encoding='utf-8'))
    ending = build_game_timeline(candidate['dossier'], candidate['voting'])['phases'][-1]
    slots = [item['slot'] for item in ending['items']]
    assert slots.index('self_destruct') < slots.index('werewolf_surrender')
    assert '8号荣耀' in ending['items'][-1]['text']


def test_swap_effects_keep_original_targets_and_actual_results_visible():
    folder = ROOT / 'data/games/S23/2026-10-27_g02_BV1RQx364EVx'
    dossier = json.loads((folder / 'dossier.json').read_text(encoding='utf-8'))
    night = next(p for p in build_game_timeline(dossier)['phases'] if p['number'] == 2 and p['phase'] == 'night')
    attack = next(item['text'] for item in night['items'] if item['slot'] == 'wolf_attack')
    check = next(item['text'] for item in night['items'] if item['slot'] == 'seer_check')
    assert '3号小张' in attack and '实际1号' in attack
    assert '1号焦阳' in check and '实际验到3号' in check


def test_existing_sheriff_does_not_restart_a_later_election():
    source = {'board': 'mixed_blood', 'seats': [], 'rounds': [
        {'number': 1, 'night': [], 'day': [event('sheriff_result', 'elected', targets=[1])]},
        {'number': 2, 'night': [], 'day': [event('sheriff_candidates', 'continued'), event('night_deaths', 'peaceful')]}]}
    later = next(p for p in build_game_timeline(source)['phases'] if p['number'] == 2)
    assert [item['slot'] for item in later['items']] == ['night_deaths']
