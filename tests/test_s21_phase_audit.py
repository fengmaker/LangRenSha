"""Regression cases from actual S21 subtitle and delayed-announcement errors."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_s21_phases import audit


def vote_value(voter, target, literal):
    return {'events': [], 'ballots': [{'ballot_id': 'b', 'day': 1, 'type': 'sheriff',
        'votes': [{'voter': voter, 'target': target, 'state': 'cast',
                   'evidence': [{'quote': literal}]}]}]}


def test_clear_literal_vote_cannot_be_reassigned_to_neighbouring_seat():
    warnings = audit(vote_value(10, 1, '11号投给1号'))
    assert warnings[0]['kind'] == 'vote_literal_pair_mismatch'


def test_split_twelve_and_grouped_declarations_are_supported():
    assert audit(vote_value(12, 2, '十\n2号投给2号')) == []
    assert audit(vote_value(8, 12, '8号11号投给12号')) == []


def event(action, phase, actor, targets, quote):
    return {'event_id': action, 'action': action, 'phase': phase, 'round': 1,
            'actor': actor, 'actor_physical_role': '女巫' if action == 'poison' else '狼人',
            'targets': targets, 'state': 'performed', 'evidence': [{'quote': quote}]}


def test_explicit_poisoned_explosion_is_not_counted_as_a_second_departure():
    rows = [event('poison', 'night', 8, [7], '女巫毒杀7号狼人'),
            event('night_deaths', 'night', None, [7, 8], '7号八号双死'),
            event('self_destruct', 'day', 7, [], '7号狼人吞毒自爆')]
    assert audit({'events': rows, 'ballots': []}) == []
    rows[-1]['evidence'][0]['quote'] = '7号狼人自爆'
    warnings = audit({'events': rows, 'ballots': []})
    assert any(w['kind'] == 'day_departure_repeats_dead_player' for w in warnings)
