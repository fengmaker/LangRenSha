import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "scripts"))
from analyze_incremental import normalized_segments, validate_candidate
from game_derivations import derive_game

folder = Path(__file__).resolve().parent
data = json.loads((folder / "input.json").read_text(encoding="utf-8"))
entry = data["entry"]
source_rel = data["source_path"]
source = ROOT / source_rel
rows = normalized_segments(source)
c = copy.deepcopy(data["skeleton"])
g, v = c["dossier"], c["voting"]

def text_ev(field, first, last=None, note=None):
    last = first if last is None else last
    selected = rows[first:last + 1]
    e = {"field": field, "kind": "text", "source_path": source_rel,
         "start_ms": selected[0]["start_ms"], "end_ms": selected[-1]["end_ms"],
         "quote": "".join(x["text"] for x in selected)}
    if note:
        e["note"] = note
    c["evidence"].append(e)

def image_ev(field, seconds, note):
    c["evidence"].append({"field": field, "kind": "image",
        "source_path": f"data/extractions/S23/incremental/{folder.name}/frames/BV1RQx364EaF_{seconds:09.3f}.png",
        "seconds": seconds, "note": note})

def weibo_ev(field, note):
    c["evidence"].append({"field": field, "kind": "weibo",
        "source_path": "data/raw/weibo/2026-10-20_2026-10-30_京城大师赛_UID7525583841/long_text/2026-10/2026-10-27_15-30-47_S23_第07期_阵容公告__WB5358654468915627.长文原始.json",
        "note": note})

def event(round_no, phase, slot):
    return next(x for x in next(r for r in g["rounds"] if r["number"] == round_no)[phase]
                if x["slot"] == slot)

def set_event(round_no, phase, slot, action, actor=None, targets=None, result=None, votes=None):
    e = event(round_no, phase, slot)
    e.update(action=action, actor=actor, targets=targets or [], result=result,
             votes=votes or [])

names = ["焦阳在这呢", "智贤", "小张受气包", "亚亚NiaNia", "耿许儿", "北影掌门-李斯",
         "BobbyJ波比儿", "荣耀Forry", "小苍cany", "老狼狼人杀", "宝玉妹妹_", "牛肉干干丶"]
roles = ["狼人", "猎人", "狼人", "平民", "白神", "混血儿", "预言家", "平民", "女巫", "狼人", "狼人", "平民"]
for seat, (name, role) in enumerate(zip(names, roles), 1):
    person = g["seats"][seat - 1]
    person["name"] = name
    person["role"] = role
    person["faction"] = "werewolf" if role == "狼人" else "good"
    image_ev(f"dossier.seats.{seat}.name", 5820,
             f"终局全席名牌逐座显示{seat}号及其舞台名；与官方阵容公告中的规范账号名对应。")
    image_ev(f"dossier.seats.{seat}.role", 5820,
             f"终局身份揭晓图显示{seat}号底牌为{role}。")
    if role == "混血儿":
        person["faction"] = "good"
        image_ev("dossier.rounds.1.night.mixed_blood_model", 5820,
                 "终局复盘图显示6号混血儿、5号榜样；5号底牌白神。")
g["roster"] = names
g["commentators"] = ["JY戴士", "李鬼鬼Supr"]
g["referee"] = "萧亚辉"
g["winner"] = "good"
weibo_ev("dossier.roster", "官方第七期阵容公告列出12名嘉宾；以视频席位名牌逐座匹配，未按微博名单顺序分配座位。")
weibo_ev("dossier.commentators", "官方公告列出解说JY戴士、李鬼鬼Supr。")
weibo_ev("dossier.referee", "官方公告列出法官萧亚辉。")
text_ev("dossier.winner", 3128, 3130)
image_ev("dossier.winner", 5820, "终局画面显示好人阵营获胜，并公开全席身份。")

# Round 1: first night and first daylight.
set_event(1, "night", "mixed_blood_model", "choose", 6, [5])
text_ev("dossier.rounds.1.night.mixed_blood_model", 3113, 3114)
set_event(1, "night", "mixed_blood_alignment", "good", 6)
text_ev("dossier.rounds.1.night.mixed_blood_alignment", 3113, 3115,
        "目标5号为白神；依混血规则个人胜利阵营随榜样，故记录good。")
set_event(1, "night", "wolf_attack", "attack", None, [12])
set_event(1, "night", "witch_save", "save", 9, [12])
set_event(1, "night", "seer_check", "check", 7, [2], "good")
text_ev("dossier.rounds.1.night.wolf_attack", 3116, 3118)
text_ev("dossier.rounds.1.night.witch_save", 3116, 3117)
text_ev("dossier.rounds.1.night.seer_check", 3118, 3120)
set_event(1, "day", "night_deaths", "peaceful", result="首夜平安夜（12号被救）")
text_ev("dossier.rounds.1.day.night_deaths", 3116, 3118)

on_police = [1, 2, 5, 6, 7, 8, 9, 10, 12]
off_police = [3, 4, 11]
set_event(1, "day", "sheriff_candidates", "register", targets=on_police)
text_ev("dossier.rounds.1.day.sheriff_candidates", 720, 724)
sheriff_votes = [{"round": 1, "voter": 3, "target": 10, "abstained": False},
                 {"round": 1, "voter": 4, "target": 7, "abstained": False},
                 {"round": 1, "voter": 11, "target": 7, "abstained": False}]
set_event(1, "day", "sheriff_vote", "vote", votes=sheriff_votes)
set_event(1, "day", "sheriff_result", "elected", targets=[7], result="7号当选警长")
set_event(1, "day", "badge", "hold", actor=7, result="7号持有警徽")
text_ev("dossier.rounds.1.day.sheriff_vote", 1213, 1219)
text_ev("dossier.rounds.1.day.sheriff_result", 3119, 3120)
text_ev("dossier.rounds.1.day.badge", 3119, 3120)

exile_votes = [
    (1, 11), (2, 11), (3, 11), (4, 10), (5, 10), (6, 11),
    (7, 10), (8, 10), (9, 10), (10, 11), (11, 10), (12, 10),
]
dossier_votes = [{"round": 1, "voter": voter, "target": target, "abstained": False}
                 for voter, target in exile_votes]
set_event(1, "day", "exile_vote", "vote", votes=dossier_votes)
set_event(1, "day", "exile_result", "exile", targets=[10], result="10号玩家7.5票出局")
text_ev("dossier.rounds.1.day.exile_vote", 2320, 2334)
text_ev("dossier.rounds.1.day.exile_result", 2334, 2336)
image_ev("dossier.rounds.1.day.exile_vote", 2334, "首轮放逐投票阶段画面；逐人投向按同期法官字幕记录。")

# Round 2: second night, double death, then wolf self-destruct.
g["rounds"].append(copy.deepcopy(g["rounds"][0]))
g["rounds"][1] = copy.deepcopy(data["skeleton"]["dossier"]["rounds"][0])
g["rounds"][1]["number"] = 2
set_event(2, "night", "wolf_attack", "attack", None, [9])
set_event(2, "night", "witch_poison", "poison", 9, [1])
set_event(2, "night", "seer_check", "check", 7, [5], "good")
set_event(2, "day", "night_deaths", "die", targets=[1, 9], result="9号女巫与1号狼人双死")
text_ev("dossier.rounds.2.night.wolf_attack", 3123, 3124)
text_ev("dossier.rounds.2.night.witch_poison", 3123, 3124)
text_ev("dossier.rounds.2.night.seer_check", 3125, 3126)
text_ev("dossier.rounds.2.day.night_deaths", 3123, 3125)
set_event(2, "day", "self_destruct", "self_destruct", 3, result="3号狼人自爆，结束第二天")
set_event(2, "day", "exile_vote", "not_held", result="未进入放逐投票")
text_ev("dossier.rounds.2.day.self_destruct", 3126, 3128)

# Round 3 began at night and ended by the last wolf surrendering before another ballot.
g["rounds"].append(copy.deepcopy(g["rounds"][0]))
g["rounds"][2] = copy.deepcopy(data["skeleton"]["dossier"]["rounds"][0])
g["rounds"][2]["number"] = 3
set_event(3, "night", "wolf_attack", "unknown", 11,
          result="最后一张狼人11号选择交牌，游戏结束；未确认发生狼刀")
text_ev("dossier.rounds.3.night.wolf_attack", 3128, 3130)

v["registrations"] = [{"id": "registration-1", "day": 1,
    "on_police": on_police, "off_police": off_police}]
v["ballots"] = [
    {"id": "ballot-1", "day": 1, "kind": "sheriff", "number": 1, "stage": "initial",
     "status": "complete", "candidates": [7, 10], "eligible_voters": off_police,
     "votes": [{"voter": x, "target": y, "state": "cast"} for x, y in [(3, 10), (4, 7), (11, 7)]],
     "tied_candidates": [], "winner": 7, "unrecorded_voters": []},
    {"id": "ballot-2", "day": 1, "kind": "exile", "number": 1, "stage": "initial",
     "status": "complete", "candidates": None, "eligible_voters": list(range(1, 13)),
     "votes": [{"voter": x, "target": y, "state": "cast"} for x, y in exile_votes],
     "tied_candidates": [], "winner": 10, "unrecorded_voters": []},
]
v["interruptions"] = [{"id": "interruption-1", "day": 2, "actor": 3,
                        "reason": "self_destruct", "ends_day": True}]
v["days"] = [{"day": 1, "sheriff": "recorded", "exile": "recorded"},
             {"day": 2, "sheriff": "not_applicable", "exile": "interrupted_self_destruct"}]
text_ev("voting.registrations.1", 720, 724)
text_ev("voting.ballots.ballot-1", 1213, 1219)
text_ev("voting.ballots.ballot-2", 2320, 2336)
text_ev("voting.interruptions.interruption-1", 3126, 3128)

c["issues"] = [
    "首轮放逐逐人票型共12张，10号收到7张原始票、11号5张；字幕公布10号7.5票出局，差额对应持徽7号的半票，不能当成额外座位票。",
    "第三夜最后一张狼人11号交牌结束对局；记录在该夜wolf_attack.result，action保留unknown，不把交牌伪装成狼刀、自爆或放逐。",
    "未见证据确认首夜/第二夜守卫守护目标、猎人技能是否可用/发动及未列出的女巫药剂动作，相关槽位保留unknown。",
]

c = validate_candidate(c, entry, source, root=ROOT)
rules = derive_game(c["dossier"], c["voting"])
(folder / "rule_derivations.json").write_text(json.dumps(rules["derivations"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
c["issues"].extend("规则冲突：" + json.dumps(x, ensure_ascii=False) for x in rules["derivations"].get("issues", []))
c = validate_candidate(c, entry, source, root=ROOT)
(folder / "candidate.json").write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"candidate": str(folder / "candidate.json"), "roles_known": sum(x["role"] is not None for x in g["seats"]),
                  "names_known": sum(x["name"] is not None for x in g["seats"]), "ballots": len(v["ballots"]),
                  "votes": sum(len(x["votes"]) for x in v["ballots"]), "derivation_issues": rules["derivations"].get("issues", [])}, ensure_ascii=False))
