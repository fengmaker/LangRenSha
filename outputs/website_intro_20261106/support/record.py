"""Record real interactions on desktop pages, with a visible demonstration pointer."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[3]
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'tmp'/'website_video_browser')
sys.path.insert(0,str(ROOT/"tmp"/"website_video_deps"))
import imageio_ffmpeg
SUP=Path(__file__).resolve().parent
STORY=json.loads((SUP/"timeline.json").read_text(encoding="utf-8"))
CAPTURE=json.loads((SUP/"capture_manifest.json").read_text(encoding="utf-8"))
REC=SUP/"recordings";REC.mkdir(exist_ok=True)
BASE="http://127.0.0.1:3000"
GAME=CAPTURE["game_seats"]["url"]
PLAYER=CAPTURE["player"]["url"]
pointer="""document.addEventListener('DOMContentLoaded',()=>{
 const p=document.createElement('div');p.id='walkthrough-pointer';
 p.style.cssText='position:fixed;left:1500px;top:800px;width:17px;height:24px;z-index:2147483647;pointer-events:none;background:#7ce1bf;clip-path:polygon(0 0,0 100%,34% 73%,62% 100%,80% 88%,53% 62%,100% 62%);filter:drop-shadow(0 0 3px #000)';document.body.appendChild(p);
 document.addEventListener('mousemove',e=>{p.style.left=e.clientX+'px';p.style.top=e.clientY+'px'});
 document.addEventListener('mousedown',e=>{const r=document.createElement('div');r.style.cssText='position:fixed;z-index:2147483646;pointer-events:none;border:3px solid #7ce1bf;border-radius:50%;width:34px;height:34px;left:'+(e.clientX-17)+'px;top:'+(e.clientY-17)+'px';document.body.appendChild(r);r.animate([{transform:'scale(.4)',opacity:1},{transform:'scale(1.7)',opacity:0}],{duration:650,fill:'forwards'}).onfinish=()=>r.remove()});
});"""

def scroll(page,y,seconds=1.1):
    page.evaluate("""([target,seconds]) => new Promise(resolve=>{
      const begin=scrollY,start=performance.now();function tick(now){let t=Math.min(1,(now-start)/(seconds*1000));let e=t<.5?2*t*t:1-Math.pow(-2*t+2,2)/2;window.scrollTo({top:begin+(target-begin)*e,behavior:'instant'});if(t<1)requestAnimationFrame(tick);else resolve()}requestAnimationFrame(tick)
    })""",[y,seconds])

def move(page,locator):
    box=locator.bounding_box()
    page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2,steps=18)
    page.wait_for_timeout(220)

def wait(page,seconds):page.wait_for_timeout(seconds*1000)
def probe(path):
    r=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-i',str(path)],capture_output=True,text=True)
    import re
    m=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',r.stderr)
    return int(m[1])*3600+int(m[2])*60+float(m[3])

paths={"home":BASE,"games":BASE+"/games","seats":GAME,"timeline":GAME,"player":PLAYER,"leaderboard":BASE+"/leaderboard"}
records={}
with sync_playwright() as p:
    browser=p.chromium.launch(channel="chrome",headless=True)
    for scene in STORY[1:-1]:
        sid=scene['id'];ctx=browser.new_context(viewport={"width":1600,"height":840},device_scale_factor=1,record_video_dir=str(REC),record_video_size={"width":1600,"height":840})
        ctx.add_init_script(pointer)
        page=ctx.new_page();page.goto(paths[sid],wait_until="networkidle",timeout=60000)
        page.evaluate("document.fonts.ready")
        if sid=="timeline":scroll(page,1230,.01)
        page.mouse.move(1450,770)
        wait(page,.3);start=time.monotonic()
        if sid=="home":
            wait(page,1.5);scroll(page,580,1.4);wait(page,1.2);scroll(page,0,1.3)
        elif sid=="games":
            wait(page,.8)
            sel=page.get_by_label("赛季",exact=True);move(page,sel);sel.select_option("S23")
            wait(page,.35);sel=page.get_by_label("版型",exact=True);move(page,sel);sel.select_option("mechanical_wolf_seer")
            wait(page,.35);button=page.get_by_role('button',name='检索对局',exact=True);move(page,button);button.click();page.wait_for_load_state('networkidle')
            wait(page,1.2);scroll(page,370,1.3)
        elif sid=="seats":
            wait(page,1.1);move(page,page.get_by_role('link',name='观看原始视频',exact=True));wait(page,.8)
            scroll(page,490,1.5);wait(page,1);page.mouse.move(660,570,steps=20)
        elif sid=="timeline":
            wait(page,1.2);scroll(page,1770,2.0);wait(page,1.2);scroll(page,2130,1.4);wait(page,1.3);scroll(page,2590,1.5)
        elif sid=="player":
            wait(page,1.3);scroll(page,870,1.5);wait(page,1);scroll(page,1825,1.6);wait(page,1.2);scroll(page,3260,1.5)
        elif sid=="leaderboard":
            wait(page,1.5);move(page,page.locator('select').first);wait(page,.3)
            page.mouse.move(1150,420,steps=20);wait(page,1.5)
            link=page.get_by_role('navigation').get_by_role('link',name='数据说明',exact=True).first
            if not link.count():link=page.get_by_role('link',name='数据说明',exact=True).first
            move(page,link);link.click();page.wait_for_load_state('networkidle')
            wait(page,.5);scroll(page,410,1.2)
        remaining=scene['duration']-(time.monotonic()-start)
        if remaining>0:wait(page,remaining)
        actual=time.monotonic()-start
        wait(page,.35);finish=time.monotonic();video=page.video
        ctx.close();file=Path(video.path());dest=REC/(sid+'.webm');file.replace(dest)
        video_duration=probe(dest)
        offset=video_duration-(finish-start)
        if offset<0:raise RuntimeError(f'Invalid record offset {sid}: {offset}')
        records[sid]={"path":str(dest.relative_to(SUP)),"trim_start":offset,"duration":scene['duration'],"recorded_action_seconds":actual,"video_duration":video_duration}
        (SUP/'recordings.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(sid,records[sid],flush=True)
    browser.close()
