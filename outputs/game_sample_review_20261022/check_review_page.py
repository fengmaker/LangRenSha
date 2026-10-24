"""Check the current local fixed-event page in isolated headless Chrome."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
PAGE=ROOT/"data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q/单局示例.html"
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe",headless=True)
    context=browser.new_context(viewport={"width":1280,"height":960},device_scale_factor=1)
    page=context.new_page()
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)))
    page.goto(PAGE.as_uri(),wait_until="load")
    assert page.title()=="单局游戏数据 · 2026-06-25 第三局"
    tables=page.locator("table")
    assert tables.count()==8
    row_counts=[tables.nth(i).locator("tbody tr").count() for i in range(8)]
    assert row_counts==[12,8,11,8,11,8,11,7],row_counts
    text=page.locator("body").inner_text()
    for removed in ["审核状态","待审核","证据编号","实际发言至","认狼","查杀后"]:
        assert removed not in text,removed
    for required in ["第一天白天12号狼人自爆","第三天白天3号狼人自爆","第一天白天随机点数3，从4号平民开始顺序发言","第三天白天随机点数11，从11号平民开始顺序发言","第二天白天未进入白天发言","解说：其人、桃子"]:
        assert required in text,required
    for night in ["一","二","三"]:
        assert f"第{night}夜7号猎人可以开枪" in text
        assert f"第{night}夜8号机械狼未带刀" in text
    for night in ["二","三"]:
        assert f"第{night}夜8号机械双刀狼尚未带刀，不能发动技能刀" in text
    assert text.count("8号机械双刀狼无白天技能")==3
    seat_names={row.locator("td").nth(0).inner_text():row.locator("td").nth(1).inner_text() for row in tables.nth(0).locator("tbody tr").all()}
    assert {s:seat_names[s] for s in ["7","9","11","12"]}=={"7":"JY","9":"翼风","11":"申屠","12":"陈俊洁"}
    page.screenshot(path=str(OUT/"review_desktop.png"))
    tables.nth(6).scroll_into_view_if_needed()
    page.screenshot(path=str(OUT/"review_events.png"))
    page.set_viewport_size({"width":390,"height":844})
    page.goto(PAGE.as_uri(),wait_until="load")
    assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
    page.screenshot(path=str(OUT/"review_mobile.png"))
    assert not errors,errors
    report={"page_loaded":True,"desktop_and_mobile_rendered":True,"javascript_errors":errors,"table_rows":row_counts,"fixed_slots_each_round":{"night":8,"day":11},"event_rows":57,"concise_role_labels":True,"source_file_rows":7,"no_review_or_evidence_ui":True,"mechanical_skill_gates_rendered":True}
    (OUT/"page_validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    context.close()
    browser.close()
