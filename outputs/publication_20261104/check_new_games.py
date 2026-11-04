"""Verify the three confirmed new games on the published site."""
from pathlib import Path
import json
import sys
from urllib.request import urlopen
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
EXPECTED = [
    ('BV1Gnxm6sEjQ',1,3,19,'第四天白天 · 游戏结束',6),
    ('BV1Qnxm6sEQq',2,4,35,'第二天夜晚 · 游戏结束',2),
    ('BV1anxm6sEWy',3,0,0,'第三天夜晚 · 游戏结束',5),
]
bluffs = json.loads((ROOT/'website/assets/bluffs/S23.json').read_text(encoding='utf8'))
results = []
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome',headless=True)
    page = browser.new_page()
    page.on('pageerror',lambda error:errors.append(str(error)))
    for bv, number, ballots, votes, ending, jumper in EXPECTED:
        slug=f'bili-{bv}-p01-g{number:02d}'
        with urlopen('http://127.0.0.1:8000/api/v1/games/'+slug,timeout=30) as r:
            game=json.load(r)
        (OUT/f'{bv}.json').write_text(json.dumps(game,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        assert len(game['seats'])==12
        assert len(game['voting']['ballots'])==ballots
        assert sum(len(b['votes']) for b in game['voting']['ballots'])==votes
        assert game['timeline']['phases'][-1]['label']==ending
        decisions=next(r for r in bluffs['games'] if r['game_id']==slug)['assessments']
        assert {r['seat'] for r in decisions if r['decision']=='yes'}=={jumper}
        selected=next(r for r in decisions if r['seat']==jumper)
        assert selected['manual_success'] is False
        if number==1:
            partner=next(s for s in game['seats'] if s['seat']==8)
            assert partner['role']=='平民' and partner['faction']=='werewolf'
        for width,height in [(1440,1000),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            response=page.goto('http://127.0.0.1:3000/games/'+slug,wait_until='networkidle',timeout=45000)
            assert response.status==200
            assert page.locator('article[data-seat]').count()==12
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            if number==1:
                card=page.locator('article[data-seat="8"]')
                assert '狼伴侣 · 不带刀' in card.inner_text()
                assert card.get_attribute('data-role')=='平民'
                assert card.get_attribute('data-faction')=='werewolf'
                assert card.locator('xpath=ancestor::section[@data-seat-group="werewolf"]').count()==1
                card.screenshot(path=str(OUT/f'{bv}_{width}_partner.png'))
            if number==2:
                assert '3号不在舞池内' in page.locator('main').inner_text()
            if number==3:
                assert '第四天白天' not in page.locator('main').inner_text()
                assert '学习结果：机械女巫' in page.locator('article[data-seat="8"]').inner_text()
            page.screenshot(path=str(OUT/f'{bv}_{width}.png'),full_page=True)
        results.append({'bvid':bv,'game_id':slug,'release_id':game['release_id'],
                        'seats':12,'ballots':ballots,'votes':votes,'ending':ending,
                        'confirmed_bluff_seat':jumper,'confirmed_bluff_success':False,
                        'desktop_and_mobile':'passed'})
    browser.close()
assert errors==[]
report={'state':'passed','mode':'partial','games':results,'browser_pages':6,'browser_errors':errors}
(ROOT/'data/reports/S23/incremental/new_games_site_check_20261104.json').write_text(
    json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
sys.stdout.reconfigure(encoding='utf8')
print(json.dumps(report,ensure_ascii=False,indent=2))
