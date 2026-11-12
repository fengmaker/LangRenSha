from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from scripts.game_review_page import render_review_page, seat_html, timeline_html

ROOT = Path(__file__).resolve().parents[1]


def test_treasure_review_shows_known_poisoner_name_and_preserves_physical_role():
    dossier = {'seats': [{'seat': 1, 'name': '焦阳', 'role': '盗宝大师', 'faction': 'werewolf'}],
               'rounds': [{'number': 1, 'night': [
                   {'slot': 'treasure_alignment', 'action': 'wolf', 'actor': 1,
                    'result': '本局为盗宝毒师，固定狼人阵营。'},
                   {'slot': 'treasure_choice', 'action': 'choose', 'actor': 1, 'result': '平民'},
               ], 'day': []}]}
    before = deepcopy(dossier)
    text = seat_html(dossier)
    assert '盗宝毒师<small>底牌：盗宝大师</small>' in text
    assert '<span class="faction wolf">狼人</span>' in text
    assert dossier == before


def test_neighbor_review_keeps_base_role_with_wolf_faction_and_chronological_surrender():
    dossier = {
        'board': 'neighbor_puppet', 'slug': 'fixture-neighbor', 'date': '2026-08-07',
        'game_number': 2, 'winner': 'good', 'commentators': [], 'referee': None,
        'seats': [{'seat': n, 'name': '大卫' if n == 12 else f'玩家{n}',
                   'role': '狼人' if n == 1 else '守卫' if n == 12 else '平民',
                   'faction': 'werewolf' if n == 1 else 'good'} for n in range(1, 13)],
        'rounds': [
            {'number': 1, 'night': [
                {'slot': 'puppet_select', 'action': 'select', 'actor': 1, 'targets': [4]},
                {'slot': 'guard', 'action': 'pass', 'actor': 12}],
             'day': [{'slot': 'night_deaths', 'action': 'peaceful'},
                     {'slot': 'exile_result', 'action': 'none'}]},
            {'number': 2, 'night': [], 'day': [
                {'slot': 'werewolf_surrender', 'action': 'surrender', 'actor': None,
                 'targets': [], 'result': '狼人交牌，好人阵营获胜。'}]},
        ],
        '_publication_context': {'terminal_observation': {'round': 2, 'phase': 'day'}},
    }
    voting = {'registrations': [], 'ballots': []}
    before = deepcopy(dossier)
    seats = seat_html(dossier)
    row = re.search(r'<tr data-seat="4">(.*?)</tr>', seats).group(1)
    assert '平民<small>傀儡 · 不带刀</small>' in row
    assert '<span class="faction wolf">狼人</span>' in row
    flow = timeline_html(dossier, voting)
    assert '12号大卫（守卫）本夜空守' in flow
    assert 'data-slot="puppet_skill_effect"' not in flow
    assert 'no_effect' not in flow
    assert flow.rfind('data-slot="night_deaths"') < flow.index('data-slot="werewolf_surrender"')
    assert '狼人选择交牌' in flow
    assert dossier == before


def test_wolf_girl_review_marks_confessed_civilian_as_wolf_partner_without_replacing_base_role():
    dossier = {
        'board': 's23_wolf_girl',
        'seats': [
            {'seat': 8, 'name': '目标', 'role': '平民', 'faction': 'good'},
            {'seat': 12, 'name': '狼女孩', 'role': '狼女孩', 'faction': 'werewolf'},
        ],
        'rounds': [{'number': 1, 'night': [
            {'slot': 'wolf_girl_confession', 'action': 'confess', 'targets': [8]},
        ]}],
    }
    row = re.search(r'<tr data-seat="8">(.*?)</tr>', seat_html(dossier)).group(1)
    assert '<td>平民<small>狼伴侣 · 不带刀</small></td>' in row
    assert '<span class="faction wolf">狼人</span>' in row


def sample(root):
    (root / 'assets').mkdir(exist_ok=True)
    (root / 'assets/identity.png').write_bytes(b'fixture-image')
    (root / 'assets/source.json').write_text(json.dumps({'body': [
        {'from': 0, 'to': 1, 'content': '不内嵌的局中全文'},
        {'from': 2, 'to': 3, 'content': '选中的连续复盘 <script>文字</script>'},
        {'from': 4, 'to': 5, 'content': '不内嵌的广告'}]}), encoding='utf-8')
    seats = [{'seat': n, 'name': '宝玉妹妹' if n == 11 else '小苍' if n == 9 else f'玩家{n}',
              'role': '狼人' if n in {1, 3, 11} else '女巫' if n == 9 else '平民',
              'faction': 'werewolf' if n in {1, 3, 11} else 'good'}
             for n in range(1, 13)]
    dossier = {'slug': 'bili-BV1RQx364EaF-p01-g01', 'date': '2026-10-27',
               'game_number': 1, 'board': 's23_mixed_blood', 'winner': 'good',
               'commentators': ['甲'], 'referee': '乙', 'roster': [s['name'] for s in seats],
               'seats': seats, 'rounds': [
                   {'number': 1, 'night': [], 'day': [
                       {'slot': 'sheriff_candidates', 'action': 'register', 'targets': [1, 2]},
                       {'slot': 'sheriff_result', 'action': 'elected', 'targets': [1]},
                       {'slot': 'night_deaths', 'action': 'peaceful'},
                       {'slot': 'exile_result', 'action': 'exile', 'targets': [4]}]},
                   {'number': 2, 'night': [], 'day': [
                       {'slot': 'night_deaths', 'action': 'peaceful'},
                       {'slot': 'exile_result', 'action': 'none'}]},
                   {'number': 3, 'night': [
                       {'slot': 'werewolf_surrender', 'action': 'surrender', 'actor': 11,
                        'targets': [], 'result': '狼人交牌，好人阵营获胜。'}], 'day': []}],
               'terminal_observation': {'round': 3, 'phase': 'night'}}
    voting = {'registrations': [{'day': 1, 'on_police': [1, 2], 'off_police': list(range(3, 13))}],
              'ballots': [
                  {'id': 'sheriff-1', 'day': 1, 'kind': 'sheriff', 'number': 1,
                   'stage': 'initial', 'votes': [{'voter': 3, 'target': 1, 'state': 'cast'}]},
                  {'id': 'exile-1', 'day': 1, 'kind': 'exile', 'number': 1,
                   'stage': 'initial', 'votes': [{'voter': 1, 'target': 4, 'state': 'cast'}]},
              ]}
    candidate = {'dossier': dossier, 'voting': voting, 'endgame': {'phases': []}}
    return {'entry': {'bvid': 'BV1RQx364EaF', 'cid': 43105127019, 'page': 1},
            'candidate': candidate, 'candidate_sha256': 'candidate-v1', 'source_sha256': 'source-v1',
            'review_display': {'identity_frames': [{'source_path': 'assets/identity.png', 'caption': '身份截图'}],
                               'recap': {'source_path': 'assets/source.json', 'start_ms': 2000, 'end_ms': 3000}}}


def test_approved_page_has_all_seats_single_bluff_row_combined_flow_and_only_recap(tmp_path):
    game = sample(tmp_path)
    before = deepcopy(game)
    output = tmp_path / 'page.html'
    result = render_review_page([game], output, root=tmp_path)
    text = output.read_text(encoding='utf-8')
    assert result['format'] == 'masters-incremental-review-v2'
    assert len(re.findall(r'<tr data-seat=', text)) == 12
    person_options = re.search(r'<select data-bluff-person[^>]*>(.*?)</select>', text, re.S).group(1)
    assert re.findall(r'<option value="(\d+)">', person_options) == [str(n) for n in range(1, 13)]
    assert text.count('<select data-bluff-person') == 1
    assert text.count('<select data-bluff-success disabled') == 1
    assert text.count('<input type="checkbox" data-no-bluff>') == 1
    assert '本局无人悍跳' in text
    assert '<aside' not in text and '<audio' not in text and '<video' not in text
    assert 'data:image/png;base64,' in text
    assert '选中的连续复盘 &lt;script&gt;文字&lt;/script&gt;' in text
    assert '不内嵌的局中全文' not in text and '不内嵌的广告' not in text
    assert 'AI推理与结论' not in text and '原文依据' not in text
    assert text.index('data-slot="sheriff_vote"') < text.index('data-slot="sheriff_result"')
    assert text.index('data-slot="exile_vote"') < text.index('data-slot="exile_result"')
    assert '第二天夜晚 · 游戏结束' in text
    assert '11号宝玉妹妹' in text
    assert game == before


def test_absent_display_selection_does_not_overwrite_an_existing_page(tmp_path):
    game = sample(tmp_path)
    del game['review_display']
    output = tmp_path / 'page.html'
    output.write_text('existing page', encoding='utf-8')
    with pytest.raises(ValueError, match='选择身份截图'):
        render_review_page([game], output, root=tmp_path)
    assert output.read_text(encoding='utf-8') == 'existing page'


def test_review_page_shows_independent_candidate_endgame_in_the_shared_flow(tmp_path):
    game = sample(tmp_path)
    dossier = game['candidate']['dossier']
    dossier['rounds'] = [{'number': 1, 'night': [], 'day': []}]
    dossier['winner'] = 'werewolf'
    game['candidate']['voting'] = {}
    game['candidate']['endgame'] = {'schema_version': 1, 'game_slug': dossier['slug'], 'phases': [
        {'kind': 'wolf_rush', 'day': 1, 'actor': None,
         'declared_targets': [9], 'result': 'werewolf_win'}]}
    before = deepcopy(game)
    output = tmp_path / 'page.html'

    render_review_page([game], output, root=tmp_path)

    text = output.read_text(encoding='utf-8')
    assert text.count('data-slot="wolf_rush"') == 1
    assert '目标集合为9号小苍（女巫）' in text
    assert '法官确认本次拍刀后游戏结束' in text
    assert game == before


def test_inline_images_cannot_read_a_file_outside_the_workspace(tmp_path):
    game = sample(tmp_path)
    game['review_display']['identity_frames'][0]['source_path'] = '../not-in-project.png'
    with pytest.raises(ValueError, match='不在项目内'):
        render_review_page([game], tmp_path / 'page.html', root=tmp_path)


def test_duplicate_identity_is_rejected(tmp_path):
    game = sample(tmp_path)
    with pytest.raises(ValueError, match='duplicate game identity'):
        render_review_page([game, game], tmp_path / 'page.html', root=tmp_path)
