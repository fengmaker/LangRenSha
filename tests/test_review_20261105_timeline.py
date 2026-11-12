"""Timeline and ballot regressions preserved in final 2026-11-05 game records."""
import json
from pathlib import Path

from scripts.game_timeline import build_game_timeline
from scripts.game_review_page import ballot_html

ROOT = Path(__file__).resolve().parents[1]


def game_for_bvid(bvid):
    for path in (ROOT / 'data/games/S23').glob('*/game.json'):
        game = json.loads(path.read_text(encoding='utf-8'))
        if (game.get('source') or {}).get('bvid') == bvid:
            return game
    raise AssertionError(f'No final game.json for {bvid}')


def test_revenge_death_excludes_guard_from_next_ballot_without_changing_signup_vote():
    game = game_for_bvid('BV1Ve4861EtL')
    original = json.dumps(game, ensure_ascii=False, sort_keys=True)
    sheriff, exile = game['voting']['ballots']
    assert 12 in sheriff['eligible_voters']
    assert exile['eligible_voters'] == [1, 2, 3, 5, 7, 9, 10, 11]
    assert exile['status'] == 'complete' and not exile['unrecorded_voters']
    phases = build_game_timeline(game)['phases']
    assert json.dumps(game, ensure_ascii=False, sort_keys=True) == original
    day = next(p for p in phases if p['number'] == 1 and p['phase'] == 'day')
    slots = [i['slot'] for i in day['items']]
    assert slots.index('night_deaths') < slots.index('self_destruct') < slots.index('wolf_girl_revenge')
    assert phases[-1]['number'] == 2 and phases[-1]['terminal']
    seats = {row['seat']: row for row in game['seats']}
    assert '弃票' in ballot_html({'slot': 'sheriff_vote', 'title': '警长投票', 'ballot': sheriff}, seats)


def test_disqualified_guard_requires_daytime_pursuit_and_user_confirmed_remaining_votes():
    game = game_for_bvid('BV1Ve4861Etu')
    phases = build_game_timeline(game)['phases']
    night = next(p for p in phases if p['number'] == 2 and p['phase'] == 'night')
    assert '需追刀追投' in next(i['text'] for i in night['items'] if i['slot'] == 'guard')
    last = phases[-1]
    assert last['phase'] == 'day' and last['number'] == 2 and last['terminal']
    death = next(i for i in last['items'] if i['slot'] == 'night_deaths')
    assert death['events'][0]['targets'] == [2, 7, 12]
    b = next(i['ballot'] for i in last['items'] if i['kind'] == 'ballot')
    assert 5 not in b['eligible_voters'] and 5 in b['candidates']
    assert {v['voter']: v['target'] for v in b['votes']} == {1: 8, 3: 8, 4: 5, 6: 5, 8: 5, 9: 5, 11: 8}
    assert b['status'] == 'complete' and b['unrecorded_voters'] == []
    slots = [i['slot'] for i in last['items']]
    assert slots.index('exile_vote') < slots.index('exile_result') < slots.index('game_result')
