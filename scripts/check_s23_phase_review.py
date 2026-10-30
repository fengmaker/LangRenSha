"""Check the user's death/skill, vote-control and per-phase review scenarios."""
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
FIRST='BV1KfYE6HEDv'

def check():
    failures=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.goto((ROOT/'data/exports/S23_逐局推导与复核.html').as_uri())
        page.wait_for_selector('#game-status')
        snapshot=page.evaluate('window.__S23_REVIEW__.snapshot_id')
        first=page.evaluate('(b) => window.__S23_REVIEW__.games.find(g=>g.entry.bvid===b)',FIRST)
        day=first['dossier']['rounds'][0]['day']
        if not any(e['slot']=='night_deaths' and e['action']=='die' and set(e['targets'])=={2,5} for e in day):
            failures.append('首局第一天缺明确2/5双死结果')
        events=first['dossier']['rounds'][0]['night']+day
        if not any(e['slot']=='hunter_state' and e['action']=='cannot_shoot' and e.get('actor')==5 for e in events):
            failures.append('首局缺5号中毒不能开枪的明确状态')
        if not any(e['slot']=='hunter_shot' and e['action']=='unavailable' and e.get('actor')==5 for e in day):
            failures.append('首局把中毒猎人误写成主动不开枪，而非无法发动技能')
        if set(page.locator('table th').all_text_contents()) & {'票重','依据'}:
            failures.append('逐人票表仍显示票重或依据列')
        control=first.get('vote_control',{})
        row=next((x for x in control.get('phases',[]) if x.get('round')==1 and x.get('phase')=='day'),{})
        if (row.get('werewolf_votes'),row.get('good_votes'),row.get('controls_vote'))!=(5.5,5,True):
            failures.append('首局缺狼混计入后的5.5比5绑票说明')
        # A later review finding must appear at the exact night it belongs to.
        page.evaluate('''b=>{
            const g=window.__S23_REVIEW__.games.find(g=>g.entry.bvid===b);
            g.review.phase_findings=[...(g.review.phase_findings||[]),{
                id:'qa-phase-gap',round:1,phase:'night',status:'unresolved',
                field:'witch_save',title:'测试：首夜用药待核实',
                conclusion:'测试：必须保留在开局夜晚',reasoning:'仅在浏览器验收上下文中注入',evidence:[]}];
        }''',FIRST)
        page.locator(f'[data-game="{FIRST}"]').click()
        phase=page.locator('[data-round="1"][data-phase="night"]')
        if phase.count()!=1 or '测试：首夜用药待核实' not in phase.inner_text():
            failures.append('待核事项没有出现在对应的开局夜晚')
        page.locator('[data-game="BV1tneS6kEnQ"]').click()
        interrupted=page.locator('[data-round="1"][data-phase="day"] .vote-control')
        if interrupted.count()!=1 or '未举行放逐投票' not in interrupted.inner_text() or '理论票力' not in interrupted.inner_text():
            failures.append('自爆中断日没有区分未举行的投票与理论票力')
        browser.close()
    result={'first_game':FIRST,'snapshot_id':snapshot,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
            'failures':failures,'passed':not failures,'formal_database_writes':False}
    (ROOT/'data/reports/S23/S23_日夜页面场景验收.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result=check();print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
