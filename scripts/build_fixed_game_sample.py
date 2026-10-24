"""Create the one-game example using the board's fixed night/day slots."""
from __future__ import annotations

import csv
import html
import json
import os
from pathlib import Path
from urllib.parse import quote

from game_records import ROOT, apply_derived_rules, chinese, describe, empty_event, template, validate

OUT=ROOT/"data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q"
BASE=ROOT/"data/weibo/2026-05-26_2026-10-20"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def csv_rows(path):
    with path.open(encoding="utf-8-sig",newline="") as stream:
        return list(csv.DictReader(stream))


def build():
    board=template("mechanical_wolf_seer")
    snapshot=read(OUT/"roster_source.snapshot.json")
    schedule=snapshot["schedule"]
    roster=[p["name"] for p in snapshot["roster"]]
    intro=read(ROOT/"outputs/game_sample_review_20261022/intro_mapping.json")
    names={p["seat_number"]:p["name"] for p in intro["participants"]}
    # The introduction's KA is KS: the following introduction refers back to KS.
    names[6]="KS"
    names.update({7:"JY",9:"翼风",11:"申屠",12:"陈俊洁"})
    roles={1:"通灵师",2:"平民",3:"狼人",4:"平民",5:"守卫",6:"狼人",7:"猎人",8:"机械狼",9:"平民",10:"女巫",11:"平民",12:"狼人"}
    seats=[{"seat":seat,"name":names[seat],"role":role,"faction":"werewolf" if role in {"狼人","机械狼"} else "good",
            "learning_target":12 if seat==8 else None,"learned_role":"机械双刀狼" if seat==8 else None} for seat,role in roles.items()]
    actors={p["role"]:p["seat"] for p in seats if p["role"] not in {"平民","狼人"}}
    rounds=[]
    for number in range(1,4):
        round_={"number":number}
        for phase in ["night","day"]:
            round_[phase]=[empty_event(s["code"],actors.get(s["actor_role"])) for s in board[phase+"_slots"]]
        rounds.append(round_)

    def fill(number,phase,slot,action,actor=None,targets=None,result=None,start=None,direction=None,random_point=None,speech_scope=None):
        event=next(e for e in rounds[number-1][phase] if e["slot"]==slot)
        event.update(action=action,targets=targets or [],result=result,start_seat=start,direction=direction,random_point=random_point,speech_scope=speech_scope)
        if actor is not None: event["actor"]=actor

    for number,target in [(1,12),(2,3),(3,5)]:
        fill(number,"night","guard","guard",5,[target])
    for number,target in [(1,8),(2,1),(3,7)]:
        fill(number,"night","wolf_attack","attack",targets=[target])
    # The final recap's first-night save wording remains unclear. Keep this cell unknown.
    for number in [2,3]:
        fill(number,"night","witch_save","pass",10)
    for number in [1,2,3]:
        fill(number,"night","witch_poison","pass",10)
    fill(1,"night","mechanical_action","learn",8,[12],"机械双刀狼")
    fill(2,"night","mechanical_action","unavailable",8)
    fill(3,"night","mechanical_action","unavailable",8)
    fill(1,"night","seer_check","check",1,[12],"狼人")
    fill(2,"night","seer_check","check",1,[3],"狼人")
    fill(3,"night","seer_check","unavailable",1)
    fill(1,"day","sheriff_candidates","register",targets=[1,4,5,6,7,8,9,11,12])
    fill(2,"day","sheriff_candidates","continued")
    fill(3,"day","sheriff_candidates","unavailable")
    for number in [1,2]:
        fill(number,"day","sheriff_vote","not_held")
    fill(3,"day","sheriff_vote","unavailable")
    fill(1,"day","sheriff_result","deferred")
    fill(2,"day","sheriff_result","none")
    fill(3,"day","sheriff_result","unavailable")
    fill(1,"day","night_deaths","peaceful")
    fill(2,"day","night_deaths","die",targets=[1])
    fill(3,"day","night_deaths","die",targets=[7])
    fill(1,"day","hunter_shot","unavailable",7)
    fill(2,"day","hunter_shot","unavailable",7)
    fill(3,"day","hunter_shot","shoot",7,[8])
    for number in [1,2,3]:
        fill(number,"day","badge","none")
        fill(number,"day","exile_vote","not_held")
        fill(number,"day","exile_result","none")
    fill(1,"day","speech_order","order",direction="forward",random_point=3,speech_scope="sheriff")
    fill(2,"day","speech_order","not_held")
    fill(3,"day","speech_order","order",direction="forward",random_point=11,speech_scope="day")
    for number,seat in [(1,12),(2,6),(3,3)]:
        fill(number,"day","self_destruct","self_destruct",seat)
    for number in [1,2,3]:
        fill(number,"day","mechanical_day_skill","unavailable",8)
    manifest=read(ROOT/"data/raw/bilibili/BV1yt7v6QE3Q/p01/manifest.json")
    intro_manifest=read(ROOT/"data/raw/bilibili/BV1Pt7v6XEP4/p01/manifest.json")
    video_key=f"{manifest['bvid']}:{manifest['cid']}"
    intro_key=f"{intro_manifest['bvid']}:{intro_manifest['cid']}"
    files=[]
    def file(role,path,kind,platform="bilibili",key=video_key):
        files.append({"role":role,"path":path,"kind":kind,"platform":platform,"external_key":key})
    raw="data/raw/bilibili/BV1yt7v6QE3Q/p01/"
    file("audio",raw+"audio.m4a","audio")
    file("manifest",raw+"manifest.json","manifest")
    file("metadata",raw+"metadata.raw.json","metadata")
    file("subtitle",raw+"subtitle.01.raw.json","subtitle")
    file("transcript","data/transcripts/S22/BV1yt7v6QE3Q_p01_funasr_hotwords343_20261022/transcript.json","asr")
    file("introduction",intro["introduction_source_file"],"subtitle",key=intro_key)
    post=(BASE/schedule["正文原件"]).resolve().relative_to(ROOT).as_posix()
    file("schedule",post,"weibo_json","weibo","5313722673268409")
    value={"slug":"bili-BV1yt7v6QE3Q-p01-g03","season":"S22","date":"2026-06-25","phase":"regular",
           "episode":4,"day_in_episode":3,"game_number":3,"board":board["code"],"winner":"good",
           "roster":roster,"commentators":["其人","桃子"],"referee":"豆儿啵",
           "seats":seats,"rounds":rounds,"files":files}
    apply_derived_rules(value)
    validate(value)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"dossier.json").write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    render(value)
    print(json.dumps({"file":str(OUT/"dossier.json"),"night_slots":len(board["night_slots"]),"day_slots":len(board["day_slots"]),"rounds":len(rounds),"event_records":len(rounds)*(len(board["night_slots"])+len(board["day_slots"])),"named_seats":sum(p["name"] is not None for p in seats)},ensure_ascii=False))
    return value


def render(value):
    board=template(value["board"])
    esc=html.escape
    def local(path):
        return quote(Path(os.path.relpath(ROOT/path,OUT)).as_posix(),safe="/.:_")
    def table(heads,rows):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in heads)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+cell+'</td>' for cell in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    participants=[[str(p["seat"]),esc(p["name"] or "—"),esc(p["role"]),esc(p["learned_role"] or "—")] for p in value["seats"]]
    sections=['<section><h2>本局人物</h2><p>解说：其人、桃子　法官：豆儿啵</p>'+table(["座位","姓名","身份","学习形态"],participants)+'<p class="note">座位姓名根据首局自我介绍及用户确认整理；JY在场时固定为7号。</p></section>']
    md=["# 2026-06-25 第三局 · 机械狼通灵师","","S22 正赛第四期 Day-3 · 好人获胜","","解说：其人、桃子。法官：豆儿啵。","","| 座位 | 姓名 | 身份 | 学习形态 |","|---:|---|---|---|"]
    md.extend('| '+' | '.join(row)+' |' for row in participants)
    md.extend(["",f"每轮固定：夜间{len(board['night_slots'])}个槽位，白天{len(board['day_slots'])}个槽位。未知留空或记为未知；未发动和不适用分别记录。",""])
    csv_events=[]
    for round_ in value["rounds"]:
        number=round_["number"]
        for phase in ["night","day"]:
            title="第"+chinese(number)+( "夜" if phase=="night" else "天白天")
            rows=[]
            md.extend(["## "+title,"","| 固定槽位 | 事件 |","|---|---|"])
            for slot,event in zip(board[phase+"_slots"],round_[phase]):
                text=describe(value,number,phase,event)
                rows.append([esc(slot["label"]),esc(text)])
                md.append(f"| {slot['label']} | {text} |")
                csv_events.append([number,phase,slot["code"],slot["label"],event["action"],text])
            md.append("")
            sections.append('<section><h2>'+title+'</h2>'+table(["固定槽位","事件"],rows)+'</section>')
    file_labels={"audio":"原音频","subtitle":"平台字幕","transcript":"转写文件","metadata":"视频信息","manifest":"媒体清单","schedule":"微博排班","introduction":"首局自我介绍"}
    files=[[esc(file_labels[f["role"]]),'<a href="'+local(f["path"])+'">'+esc(Path(f["path"]).name)+'</a>'] for f in value["files"]]
    sections.append('<section><h2>源文件登记</h2>'+table(["用途","文件"],files)+'<p><a href="dossier.json">对局JSON</a> · <a href="游戏事件.csv">事件CSV</a> · <a href="查询示例.sql">数据库查询</a></p></section>')
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>单局游戏数据 · 2026-06-25 第三局</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f5f7;color:#173342;font:16px/1.7 "Microsoft YaHei",sans-serif}main{max-width:1050px;margin:auto;padding:35px 24px 60px}h1{font-size:29px;line-height:1.5;margin:0 0 10px}h2{font-size:23px;margin:0 0 15px}section{background:#fff;border:1px solid #dbe5ea;border-radius:12px;padding:24px;margin:22px 0}table{border-collapse:collapse;width:100%}th,td{text-align:left;vertical-align:top;padding:11px 14px;border-bottom:1px solid #e4eaee}th{background:#edf3f6;white-space:nowrap}td:first-child{white-space:nowrap;width:135px}a{color:#176e9d}.scroll{overflow:auto}.note{color:#5d737f;font-size:14px}.meta{display:flex;gap:12px;flex-wrap:wrap}.meta span{background:#e4eef3;border-radius:6px;padding:3px 11px}@media(max-width:600px){main{padding:22px 12px}section{padding:15px}h1{font-size:24px}td:first-child{width:95px}th,td{padding:9px 7px}}
</style><main><h1>2026-06-25 · 第三局</h1><p>S22 正赛第四期 Day-3 · 机械狼通灵师</p><div class="meta"><span>好人获胜</span><span>每夜NIGHT_COUNT项</span><span>每天DAY_COUNT项</span><span>ROUND_COUNT轮</span></div><p class="note">夜间顺序：守卫 → 狼人 → 女巫 → 猎人 → 机械狼 → 通灵师</p>'''.replace('NIGHT_COUNT',str(len(board['night_slots']))).replace('DAY_COUNT',str(len(board['day_slots']))).replace('ROUND_COUNT',str(len(value['rounds'])))+''.join(sections)+'</main></html>'
    for name in ["单局示例.html","单局示例_审核.html"]:
        (OUT/name).write_text(document,encoding="utf-8")
    for name in ["单局示例.md","单局示例_审核.md"]:
        (OUT/name).write_text("\n".join(md),encoding="utf-8")
    with (OUT/"游戏事件.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["轮次","阶段","槽位代码","固定槽位","动作","事件"])
        writer.writerows(csv_events)
    with (OUT/"座位身份.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["座位","姓名","身份","学习形态"])
        writer.writerows([[p["seat"],p["name"],p["role"],p["learned_role"]] for p in value["seats"]])


if __name__=="__main__":
    build()
