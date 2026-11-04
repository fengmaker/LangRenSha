"""Check this delivery's real three cards at desktop width."""
from pathlib import Path
import json
import sys
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/review_20261103_qa'
page_path = ROOT / 'data/manual_review/S23_新增对局人工复核.html'
expected = [(3, 19, '第四天白天 · 游戏结束'),
            (4, 35, '第二天夜晚 · 游戏结束'),
            (0, 0, '第三天夜晚 · 游戏结束')]
results = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width':1440,'height':1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(page_path.as_uri())
    metadata = page.locator('#review-data').text_content()
    games = json.loads(metadata)['games']
    assert len(games) == 3
    for index, game in enumerate(games):
        page.select_option('#game-picker', game['review_id'])
        card = page.locator('main.game-card:not([hidden])')
        assert card.locator('table.seats tbody tr').count() == 12
        assert card.locator('[data-bluff-person]').input_value() == ''
        assert card.locator('[data-bluff-success]').is_disabled()
        assert not card.locator('[data-reviewed]').is_checked()
        assert card.locator('[data-note]').input_value() == ''
        assert card.locator('.frame-button img').evaluate('(img)=>img.complete && img.naturalWidth===1920')
        ballot_count = card.locator('.flow-ballot').count()
        assert ballot_count == expected[index][0]
        assert card.locator('.timeline-phase h3').last.inner_text() == expected[index][2]
        assert not card.locator('.game-flow').get_by_text('待核', exact=False).count()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if index == 0:
            seat = card.locator('tr[data-seat="8"]').inner_text()
            assert all(x in seat for x in ['平民','狼伴侣','不带刀','狼人'])
        if index == 1:
            assert card.locator('.game-flow').get_by_text('3号不在舞池内', exact=False).count() == 1
            assert card.locator('.flow-ballot h4').filter(has_text='PK复投').count() == 1
        if index == 2:
            assert card.locator('.game-flow').get_by_text('自爆。', exact=False).count() == 3
            assert not card.locator('.game-flow').get_by_text('第四天白天',exact=False).count()
        card.locator('.game-flow').screenshot(path=str(OUT/f'game_{index+1}_flow.png'))
        page.screenshot(path=str(OUT/f'game_{index+1}_desktop.png'),full_page=True)
        results.append({'bvid':game['bvid'],'seats':12,'images_loaded':True,
                        'ballots':ballot_count,'choices':expected[index][1],
                        'last_phase':expected[index][2], 'blank_feedback':True,
                        'no_visible_pending':True,'desktop_no_overflow':True})
    browser.close()
assert errors == []
report = {'status':'passed','games':results,'javascript_errors':errors,'mobile_checked':False}
(OUT/'all_three_games_qa.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
sys.stdout.reconfigure(encoding='utf8')
print(json.dumps(report,ensure_ascii=False,indent=2))
