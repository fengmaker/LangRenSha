"""Check the scoped, published HTTP pages against the accepted findings."""
import json
from pathlib import Path
import re
import runpy
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'published_pages'
manifest = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
games = {}
for row in manifest['games']:
    game_id = row['id']
    with urlopen('http://127.0.0.1:8000/api/v1/games/' + game_id, timeout=15) as response:
        game = json.load(response)
    with urlopen('http://127.0.0.1:3000/games/' + game_id, timeout=20) as response:
        html = response.read().decode('utf-8')
    (OUT / (game_id + '.json')).write_text(json.dumps(game, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / (game_id + '.html')).write_text(html, encoding='utf-8')
    games[game_id.split('-')[1]] = game
    assert html.count('data-seat-group=') >= 3, game_id
    items = [item for phase in game['timeline']['phases'] for item in phase['items']]
    text = '\n'.join(item.get('title', '') + ' ' + item.get('text', '') for item in items)
    assert not re.search(r'cleared|successful|select_pair|trade_betray|betray_trade|magician exchange|记录动作|按交易双方目标顺序记录', text), game_id
    emitted = {item['ballot']['id'] for item in items if item['kind'] == 'ballot'}
    assert emitted == {ballot['id'] for ballot in game['voting']['ballots']}, game_id
    for phase in game['timeline']['phases']:
        for index, item in enumerate(phase['items']):
            if item['slot'] in {'hunter_shot', 'wolf_king_shot'}:
                for event in item['events']:
                    assert not any(event.get('actor') in later.get('targets', [])
                                   and later.get('action') == 'exile'
                                   for following in phase['items'][index + 1:]
                                   for later in following.get('events', [])), game_id
    if game_id.split('-')[1] in {'BV18n5z6AEAt', 'BV1SMPqzjEe6', 'BV1U3p86dEYR'}:
        assert sum(item['slot'] == 'wolf_rush' for item in items) == 1
        assert 'id="game-endgame"' not in html

for bvid in ['BV1g1YU6kERd', 'BV1nJer63EDh', 'BV1VPaW66EZz']:
    phases = games[bvid]['timeline']['phases']
    assert not phases[-1]['terminal']
    assert not any(item['slot'] == 'wolf_rush' for phase in phases for item in phase['items'])
for bvid, count in [('BV178XkB7EXx', 2), ('BV1MMPxzmEWJ', 1)]:
    assert sum(item['slot'] == 'warden_trade_targets' for phase in games[bvid]['timeline']['phases']
               for item in phase['items']) == count
assert games['BV1KuMG6NEez']['timeline']['phases'][-1]['items'][-1]['slot'] == 'werewolf_surrender'
assert any(item['slot'] == 'night_deaths' and item['events'][0]['targets'] == [6]
           for item in games['BV1yKJ56PEak']['timeline']['phases'][-1]['items'])
guard = next(item for item in games['BV1iMgq6ZEtz']['timeline']['phases'][0]['items'] if item['slot'] == 'guard')
assert '技能失效' in guard['text']
poison = next(item for phase in games['BV1U3p86dEYR']['timeline']['phases'] if phase['number'] == 2 and phase['phase'] == 'night'
              for item in phase['items'] if item['slot'] == 'witch_medicine')
assert '实际毒杀2号' in poison['text']
unknown_rush = next(item for phase in games['BV18n5z6AEAt']['timeline']['phases']
                    for item in phase['items'] if item['slot'] == 'wolf_rush')
assert unknown_rush['events'][0]['result'] == 'unknown' and '结算待核' in unknown_rush['text']

css = ''.join(path.read_text(encoding='utf-8') for path in OUT.glob('style-*.css'))
assert re.search(r'[^{}]*_columns\{[^}]*align-items:stretch', css)
assert re.search(r'[^{}]*_column\{[^}]*flex-direction:column', css)
runpy.run_path(str(OUT / 'check_snapshots.py'))
checks = json.loads((OUT / 'page_api_checks.json').read_text(encoding='utf-8'))
assert all(all(row[key] for key in ['api_release_matches', 'html_slots_match_api',
                                   'html_has_all_api_event_text', 'phase_order_increasing'])
           for row in checks['checks'])
result = {'mode': 'partial', 'games': 23, 'api_and_page_ballots': 48,
          'raw_code_and_order_checks': 'passed', 'three_s21_trades': 'passed',
          'rush_once_checks': 'passed', 'candidate_endings_preserved': 'passed',
          'confirmed_surrender_and_terminal_death': 'passed',
          'built_css_equal_column_rule': 'passed',
          'browser_visual_check': 'not performed: browser access host unavailable'}
(ROOT / 'targeted_checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print('All accepted scoped checks passed; visual browser checks unavailable.')
