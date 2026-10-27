"""Exercise local S23 review navigation, feedback round-trip and source links."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'data/exports/S23_逐局推导与复核.html'


def check(require_complete=False):
    errors = []
    with sync_playwright() as pw, TemporaryDirectory(prefix='s23-review-qa-') as temp:
        browser = pw.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width':1440,'height':1000}, accept_downloads=True)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(PAGE.as_uri(), wait_until='load')
        page.wait_for_selector('#game-status')
        metadata = page.evaluate('''() => ({snapshot:window.__S23_REVIEW__.snapshot_id,
            games:window.__S23_REVIEW__.games.map(g=>({bvid:g.entry.bvid,date:g.entry.date,
            source:g.source_url,audio:g.audio_url,frame:g.frame_url,dossier:g.dossier_url,
            pending:(g.review.phase_findings||[]).filter(f=>f.status==='unresolved').map(f=>({round:f.round,phase:f.phase}))}))})''')
        games = metadata['games']
        if require_complete:
            assert len(games) == 75, f'只有{len(games)}局'
        links = 0
        phase_markers = 0
        for game in games:
            for kind in ['source','audio','frame','dossier']:
                path = (PAGE.parent / unquote(game[kind])).resolve()
                assert path.is_relative_to(ROOT) and path.is_file(), (game['bvid'], kind, str(path))
                links += 1
            page.locator(f'[data-game="{game["bvid"]}"]').click()
            assert page.locator('.seat').count() == 12, game['bvid']
            assert game['date'] in page.locator('h2').inner_text()
            assert not set(page.locator('table th').all_text_contents()) & {'票重','依据'}, game['bvid']
            groups={}
            for item in game['pending']:
                key=(item['round'],item['phase']);groups[key]=groups.get(key,0)+1
            for (number,phase),count in groups.items():
                wrapper=page.locator(f'[data-round="{number}"][data-phase="{phase}"]')
                assert wrapper.count()==1,(game['bvid'],number,phase,'日夜定位缺失')
                assert wrapper.locator('.phase-finding.question').count()==count,(game['bvid'],number,phase,'待核标记遗漏')
                assert '需你确认' in wrapper.inner_text(),(game['bvid'],number,phase)
                phase_markers+=count
        first = games[0]['bvid']
        page.locator(f'[data-game="{first}"]').click()
        page.locator('#reviewer').fill('自动验收')
        page.locator('#game-status').select_option('correction')
        page.locator('#game-comment').fill('QA：持久化与导入导出校验')
        page.reload(wait_until='load')
        assert page.locator('#game-status').input_value() == 'correction'
        assert page.locator('#game-comment').input_value() == 'QA：持久化与导入导出校验'
        with page.expect_download() as download_info:
            page.locator('#export').click()
        exported = Path(temp) / 'feedback.json'
        download_info.value.save_as(exported)
        feedback = json.loads(exported.read_text(encoding='utf-8'))
        assert feedback['snapshot_id'] == metadata['snapshot']
        assert feedback['games'][first]['status'] == 'correction'
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='load')
        assert page.locator('#game-status').input_value() == 'pending'
        page.locator('#file').set_input_files(exported)
        page.wait_for_function("document.getElementById('game-status').value === 'correction'")
        assert page.locator('#game-comment').input_value() == 'QA：持久化与导入导出校验'
        feedback['snapshot_id'] = 'wrong-snapshot'
        rejected = Path(temp) / 'wrong.json'
        rejected.write_text(json.dumps(feedback,ensure_ascii=False),encoding='utf-8')
        page.locator('#file').set_input_files(rejected)
        page.wait_for_function("document.getElementById('status').textContent.includes('导入未完成')")
        assert page.locator('#game-status').input_value() == 'correction'
        page.evaluate('localStorage.clear()')
        page.reload(wait_until='load')
        (ROOT/'outputs').mkdir(exist_ok=True)
        page.screenshot(path=str(ROOT/'outputs/S23_review_preview.png'))
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), '窄屏横向溢出'
        page.screenshot(path=str(ROOT/'outputs/S23_review_mobile.png'))
        browser.close()
    assert not errors, errors
    result = {'games_rendered':len(games),'local_links_checked':links,'javascript_errors':errors,
              'per_phase_pending_markers_checked':phase_markers,'vote_table_columns':['投票者','投向'],
              'feedback_persistence':True,'feedback_export_import':True,'wrong_snapshot_rejected':True,
              'mobile_390px_without_overflow':True,'snapshot_id':metadata['snapshot'],
              'formal_database_writes':False}
    (ROOT/'data/reports/S23_逐局复核页面验收.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-complete',action='store_true')
    print(json.dumps(check(parser.parse_args().require_complete),ensure_ascii=False,indent=2))
