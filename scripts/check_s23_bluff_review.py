"""Check the finished S23 review artifact, image evidence, feedback and live page."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.s23_bluff_audit import load_audits
from scripts.import_bluff_feedback import source_games,validate_feedback
from website.api import bluffs,publisher


def api(path):
    with urlopen('http://127.0.0.1:8000'+path,timeout=20) as response:return json.load(response)


def main():
    payload=json.loads((ROOT/'website/assets/bluffs/S23.json').read_text(encoding='utf-8'))
    games=source_games('S23')
    audits=load_audits(ROOT,games,require_complete=False)
    assert len(audits)==payload['summary']['independently_rechecked_games']
    items=bluffs.review_items(games,payload)
    assert len(items)==300
    assert all(row['evidence'] for row in items if not row['assistant_pending'])
    confirmed=[r for r in items if r['verification_status']=='user_confirmed']
    assert any(r['bvid']=='BV1U3p86dEJY' and r['seat']==6 and r['decision']=='yes' for r in confirmed)
    _,source_hash,_=publisher.load_release(ROOT,['S22','S23'])
    with publisher._connect() as conn:
        active=conn.execute('SELECT r.id,r.source_hash FROM releases r JOIN active_release a ON a.release_id=r.id').fetchone()
        assert active['source_hash']==source_hash,'Game source files changed during bluff review'
    manifest=json.loads((ROOT/'website/api/bluff_frames.json').read_text(encoding='utf-8'))['frames']['S23']
    for filename,record in manifest.items():
        path=ROOT/'website/assets/bluff-frames/S23'/filename
        assert hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256']==path.stem
    online=api('/api/v1/bluff-review?season=S23&status=all')
    assert online['summary']['wolf_appearances']==300
    assert online['summary']['identified_bluffs']==payload['summary']['decisions']['yes']
    assert online['summary']['pending']==payload['summary']['pending']
    old=api('/api/v1/bluff-review?season=S22&status=all')
    assert old['summary']['identified_bluffs']==121 and old['summary']['successes']==46 and old['summary']['pending']==0
    report={'games':75,'games_video_rechecked':len(audits),'wolf_seats':300,'summary':payload['summary'],'image_assets':len(manifest),
            'game_release_unchanged':active['id'],'S22_bluffs_unchanged':True,'browser_errors':[],'viewports':[1440,390]}
    offline=ROOT/'data/exports/S23_悍跳推断与复核.html'
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(accept_downloads=True)
        page=context.new_page()
        page.on('pageerror',lambda e:report['browser_errors'].append(str(e)))
        for url in [offline.as_uri(),'http://127.0.0.1:3000/seasons/S23/bluff-review']:
            page.goto(url,wait_until='networkidle')
            assert page.get_by_role('heading',name='S23 悍跳推断与复核',exact=False).count()==1
            cards='article[data-pending]:visible' if url.startswith('file:') else 'article.bluff-review-card:visible'
            assert page.locator(cards).count()==payload['summary']['pending']
            page.get_by_role('button' if url.startswith('file:') else 'link',name='全部记录（含推断不是悍跳）' if url.startswith('file:') else '全部推断',exact=True).click()
            page.wait_for_load_state('networkidle')
            expected_forms=sum(not row['assistant_pending'] for row in items)
            page.wait_for_function('(count)=>document.querySelectorAll("form.bluff-feedback-form").length===count',arg=expected_forms)
            assert page.locator('form.bluff-feedback-form').count()==expected_forms
            image=page.locator('img').first
            if image.count():
                image.scroll_into_view_if_needed()
                page.wait_for_function("() => {const img=document.querySelector('img'); return img?.complete && img.naturalWidth>0;}")
            form=page.locator('form.bluff-feedback-form').first
            form.locator('select[name="decision"]').select_option('comment')
            form.locator('textarea[name="notes"]').fill('验收测试草稿；不提交为用户确认。')
            page.locator('[data-feedback-copy-open]').click()
            exported=json.loads(page.locator('[data-feedback-copy-text]').input_value())
            assert exported['season']=='S23'
            assert len(validate_feedback(exported,games,'S23'))==1
            form.locator('select[name="decision"]').select_option('')
            form.locator('textarea[name="notes"]').fill('')
            for width in report['viewports']:
                page.set_viewport_size({'width':width,'height':900})
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            if not url.startswith('file:'):
                page.goto('http://127.0.0.1:3000/seasons/S23/bluff-review',wait_until='networkidle')
                page.screenshot(path=str(ROOT/'website/artifacts/S23-bluff-review-390.png'),full_page=True)
        context.close();browser.close()
    assert not report['browser_errors'],report['browser_errors']
    path=ROOT/'data/reports/S23_悍跳视频交叉复核验收_20261026.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
