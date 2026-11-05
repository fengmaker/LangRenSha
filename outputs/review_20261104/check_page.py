"""Desktop-only acceptance of the delivered three-game offline page."""
from pathlib import Path
import json
import sys
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'qa'
OUT.mkdir(exist_ok=True)
EXPECTED = [(3, 26, '第四天白天 · 游戏结束', 0),
            (7, 50, '第四天白天 · 游戏结束', 1),
            (0, 0, '第三天夜晚 · 游戏结束', 1)]
results = []
with sync_playwright() as pw:
    browser = pw.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width':1440, 'height':1000}, accept_downloads=True)
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto((ROOT/'data/manual_review/S23_新增对局人工复核.html').as_uri())
    games = json.loads(page.locator('#review-data').text_content())['games']
    assert len(games) == 3
    for index, game in enumerate(games):
        page.select_option('#game-picker', game['review_id'])
        card = page.locator('main.game-card:not([hidden])')
        assert card.locator('table.seats tbody tr').count() == 12
        assert card.locator('[data-bluff-person]').input_value() == ''
        assert card.locator('[data-bluff-success]').is_disabled()
        assert not card.locator('[data-reviewed]').is_checked()
        assert card.locator('[data-note]').input_value() == ''
        assert card.locator('.frame-button img').evaluate('(im)=>im.complete && im.naturalWidth===1920')
        ballots, choices, terminal, pending = EXPECTED[index]
        assert card.locator('.flow-ballot').count() == ballots
        assert card.locator('.ballot-grid tbody td').count() == choices
        assert card.locator('.timeline-phase h3').last.inner_text() == terminal
        assert card.locator('.game-flow').get_by_text('具体情况待核',exact=False).count() == pending
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert 'speak' not in card.locator('.game-flow').inner_text()
        if index == 0:
            row = card.locator('tr[data-seat="9"]').inner_text()
            assert '混血儿' in row and '狼人' in row
            assert card.get_by_text('绑票终局',exact=True).count() == 1
        if index == 1:
            assert card.locator('.flow-ballot h4').filter(has_text='PK复投').count() == 1
            assert card.locator('.flow-ballot h4').filter(has_text='技能重投').count() == 1
            assert card.get_by_text('赛后最终裁定',exact=True).count() == 1
        if index == 2:
            row = card.locator('tr[data-seat="1"]').inner_text()
            assert '机械狼' in row and '机械守卫' in row
            assert card.locator('.game-flow').get_by_text('自爆。',exact=False).count() == 3
        card.locator('.frame-button').click()
        assert page.locator('#image-dialog').is_visible()
        page.click('#close-image')
        page.screenshot(path=str(OUT/f'game_{index+1}_desktop.png'))
        card.locator('.game-flow').screenshot(path=str(OUT/f'game_{index+1}_flow.png'))
        results.append({'bvid':game['bvid'],'seats':12,'ballots':ballots,'choices':choices,
                        'last_phase':terminal,'visible_pending':pending,'identity_image_enlarges':True,
                        'blank_feedback':True,'desktop_no_overflow':True})
    # Draft restoration, selection enablement, all-no toggle and v2 JSON roundtrip.
    page.select_option('#game-picker',games[0]['review_id'])
    card = page.locator('main.game-card:not([hidden])')
    card.locator('[data-bluff-person]').select_option('4')
    assert card.locator('[data-bluff-success]').is_enabled()
    card.locator('[data-bluff-success]').select_option('failure')
    card.locator('[data-note]').fill('桌面验收草稿，不是用户复核意见。')
    card.locator('[data-reviewed]').check()
    page.reload()
    card = page.locator('main.game-card:not([hidden])')
    assert card.locator('[data-bluff-person]').input_value() == '4'
    assert card.locator('[data-note]').input_value() == '桌面验收草稿，不是用户复核意见。'
    assert card.locator('[data-reviewed]').is_checked()
    card.locator('[data-no-bluff]').check()
    assert card.locator('[data-bluff-person]').is_disabled()
    page.reload()
    card = page.locator('main.game-card:not([hidden])')
    assert card.locator('[data-no-bluff]').is_checked()
    def export(name):
        with page.expect_download() as got:
            page.click('#export')
        path = OUT/name
        got.value.save_as(path)
        return json.loads(path.read_text(encoding='utf8'))
    exported = export('qa_all_no.json')
    assert exported['format'] == 'masters-incremental-review-v2'
    assert all(x['decision']=='no' and x['success']=='' for x in exported['games'][0]['bluffs'])
    card.locator('[data-no-bluff]').uncheck()
    cancelled = export('qa_cancelled.json')
    assert all(x['decision']=='' for x in cancelled['games'][0]['bluffs'])
    page.set_input_files('#import-file',str(OUT/'qa_all_no.json'))
    page.locator('#status').filter(has_text='已导入3局').wait_for()
    assert card.locator('[data-no-bluff]').is_checked()
    assert export('qa_roundtrip.json') == exported
    page.click('#next-game')
    assert page.locator('#game-picker').input_value() == games[1]['review_id']
    page.click('#previous-game')
    assert page.locator('#game-picker').input_value() == games[0]['review_id']
    browser.close()
assert errors == []
report = {'status':'passed','games':results,'draft_restored':True,'all_no_toggle':True,
          'import_export_roundtrip':True,'navigation':True,'javascript_errors':errors,'mobile_checked':False}
(OUT/'page_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
sys.stdout.reconfigure(encoding='utf8')
print(json.dumps(report,ensure_ascii=False,indent=2))
