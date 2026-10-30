from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from scripts.game_review_page import render_review_page

ROOT = Path(__file__).resolve().parents[1]


def sample(root):
    folder = ROOT / 'data/extractions/S23/incremental/BV1RQx364EaF_p01_cid43105127019'
    candidate = json.loads((folder / 'candidate.json').read_text(encoding='utf-8'))
    (root / 'assets').mkdir(exist_ok=True)
    (root / 'assets/identity.png').write_bytes(b'fixture-image')
    (root / 'assets/source.json').write_text(json.dumps({'body': [
        {'from': 0, 'to': 1, 'content': '不内嵌的局中全文'},
        {'from': 2, 'to': 3, 'content': '选中的连续复盘 <script>文字</script>'},
        {'from': 4, 'to': 5, 'content': '不内嵌的广告'}]}), encoding='utf-8')
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


def test_inline_images_cannot_read_a_file_outside_the_workspace(tmp_path):
    game = sample(tmp_path)
    game['review_display']['identity_frames'][0]['source_path'] = '../not-in-project.png'
    with pytest.raises(ValueError, match='不在项目内'):
        render_review_page([game], tmp_path / 'page.html', root=tmp_path)


def test_duplicate_identity_is_rejected(tmp_path):
    game = sample(tmp_path)
    with pytest.raises(ValueError, match='duplicate game identity'):
        render_review_page([game, game], tmp_path / 'page.html', root=tmp_path)
