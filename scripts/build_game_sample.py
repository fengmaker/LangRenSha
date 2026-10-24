"""Build the single, transcript-grounded example requested on 2026-10-22.

This is a curated example, not an automatic season-wide fact extractor.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/games/S22/2026-06-25_g03_BV1yt7v6QE3Q"
TRANSCRIPT = "data/transcripts/S22/BV1yt7v6QE3Q_p01_funasr_hotwords343_20261022/transcript.json"
SUBTITLE = "data/raw/bilibili/BV1yt7v6QE3Q/p01/subtitle.01.raw.json"
BASE = "data/weibo/2026-05-26_2026-10-20/"
URL = "https://www.bilibili.com/video/BV1yt7v6QE3Q/?p=1"


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))


def rows(relative):
    with (ROOT / relative).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def digest(relative):
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def save_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clock(seconds):
    return f"{int(seconds)//60:02d}:{int(seconds)%60:02d}"


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    transcript = read_json(TRANSCRIPT)
    caption = read_json(SUBTITLE)
    manifest_file = "data/raw/bilibili/BV1yt7v6QE3Q/p01/manifest.json"
    manifest = read_json(manifest_file)
    assert transcript["source"]["audio_sha256"] == manifest["audio"]["sha256"]
    evidence = {}

    def ev(start, end, source="asr"):
        key = f"E{len(evidence)+1:03d}"
        if source == "asr":
            selected = [(i, s) for i, s in enumerate(transcript["segments"])
                        if s["start_ms"] < end*1000 and s["end_ms"] > start*1000]
            assert selected
            indexes = [i for i, _ in selected]
            values = [s for _, s in selected]
            record = {"source_ref": "transcript", "locator": f"segments[{indexes[0]}..{indexes[-1]}]",
                      "segment_ids": [s["id"] for s in values],
                      "start_seconds": values[0]["start_ms"]/1000,
                      "end_seconds": values[-1]["end_ms"]/1000,
                      "quote": "".join(s["text"] for s in values)}
        else:
            selected = [(i, s) for i, s in enumerate(caption["body"])
                        if s["from"] < end and s["to"] > start]
            assert selected
            indexes = [i for i, _ in selected]
            values = [s for _, s in selected]
            record = {"source_ref": "subtitle", "locator": f"body[{indexes[0]}..{indexes[-1]}]",
                      "body_indexes": indexes, "start_seconds": values[0]["from"],
                      "end_seconds": values[-1]["to"],
                      "quote": " / ".join(s["content"] for s in values)}
        record["id"] = key
        record["verification_status"] = "machine_text_unverified"
        evidence[key] = record
        return key

    schedule_file = BASE + "比赛排班.csv"
    references_file = BASE + "人名复核/照片人名_逐帖对应.csv"
    mapping_file = BASE + "参赛名单/人名去重_照片映射.csv"
    schedule = [r for r in rows(schedule_file) if r["比赛日期"] == "2026-06-25" and r["赛季"] == "S22"]
    assert len(schedule) == 1
    schedule = schedule[0]
    refs = [r for r in rows(references_file) if r["比赛日期"] == "2026-06-25" and r["微博ID"] == "5313722673268409"]
    mapping = {r["照片编号"]: r for r in rows(mapping_file)}
    roster = []
    for ref in refs:
        reviewed = mapping[ref["照片编号"]]
        assert reviewed["图片SHA256"] == ref["图片SHA256"]
        assert reviewed["纳入参赛名单"] == "是"
        assert reviewed["原人工确认状态"] in {"确认无误", "已修正"}
        roster.append({"name": reviewed["去重后姓名"], "picture_id": ref["照片编号"],
                       "schedule_image_index": int(ref["原帖图片序号"]),
                       "image_sha256": ref["图片SHA256"], "name_review_status": "user_reviewed",
                       "photo_reference_row": ref, "reviewed_name_row": reviewed})
    assert len(roster) == len({r["name"] for r in roster}) == 12
    snapshot = {"schedule": schedule, "roster": roster,
                "note": "图片顺序仅用于定位原帖图片，不能当作本局座次。逐帖表仍为初始识读状态；姓名采用用户复核后的照片映射。",
                "input_files": [{"path": f, "sha256": digest(f)} for f in [schedule_file, references_file, mapping_file]]}
    save_json("roster_source.snapshot.json", snapshot)
    roles_evidence = [ev(2040.415, 2051.49), ev(2040.37, 2052.51, "subtitle")]
    name_data = {
        1: ("张小凡", "role_link", "解说称张小凡为通灵师；复盘公布通灵师为1号。", [ev(178.46, 181.845)]),
        2: ("Happy", "direct_seat_name", "赛后直接播报2号玩家Happy。", [ev(2093.005, 2094.225)]),
        3: ("李斯", "context_link", "警下2/3/10的上下文点名李斯；3号发言感谢北影后援会。", [ev(910.545, 925.57), ev(1926.115, 1933.26)]),
        4: (None, "unresolved", "缺少4号姓名直接证据；华仔仔为排除法候选，未写成座位姓名。", []),
        5: ("小苍", "direct_seat_name", "赛后直接播报5号玩家小苍（本地识别为小仓）；平台字幕交叉对照。", [ev(2113.315, 2117.98), ev(2113, 2118, "subtitle")]),
        6: ("KS", "context_link", "11号复述5/6终有一战并说KS已经自爆，结合6号自爆播报。", [ev(1790.3, 1794.745), ev(1432.97, 1436.27)]),
        7: ("JY", "nickname_role_link", "解说称歪哥为猎人；复盘猎人为7号。排班正文JY戴士对应已复核JY；歪哥昵称归并仍待本次确认。", [ev(348.25, 353.19, "subtitle")]),
        8: ("牛肉干", "nickname_seat_link", "平台字幕直接说8号我们的干干；干干归并到排班牛肉干，待本次确认。", [ev(263.34, 268.03, "subtitle")]),
        9: ("翼风", "nickname_context_link", "4号谈9号并直呼峰哥，8号回顾歪哥发言前翼风的反应；翼风/峰哥归并为候选。", [ev(453.51, 475.51), ev(614.655, 627.215)]),
        10: ("葛小舞", "nickname_role_link", "解说称小舞为女巫；复盘女巫为10号。小舞归并到已复核葛小舞，待本次确认。", [ev(298.65, 304.43), ev(315.76, 319.58)]),
        11: (None, "unresolved", "夜间解说称给2号拉守卫的是图图，与11号动作相符；申屠是昵称候选，未确认为座位姓名。", [ev(1308.33, 1314.485), ev(750, 758)]),
        12: (None, "unresolved", "11号发言称后面还有勾勾和张小凡；可推12号被称勾勾，缺少勾勾与规范姓名的直接对应。", [ev(815.2, 819.56, "subtitle")]),
    }
    role_data = {1: "通灵师", 2: "平民", 3: "狼人", 4: "平民", 5: "守卫", 6: "狼人", 7: "猎人", 8: "机械狼", 9: "平民", 10: "女巫", 11: "平民", 12: "狼人"}
    participants = []
    for seat in range(1, 13):
        name, basis, note, name_evidence = name_data[seat]
        faction = "werewolf" if seat in {3, 6, 8, 12} else "good"
        participants.append({"seat_number": seat, "name_candidate": name, "name_basis": basis,
                             "name_note": note, "name_evidence_ids": name_evidence,
                             "role_candidate": role_data[seat], "role_evidence_ids": roles_evidence,
                             "opening_faction_candidate": faction, "settlement_faction_candidate": faction,
                             "personal_result_candidate": "loss" if faction == "werewolf" else "win",
                             "personal_result_basis": "derived_from_faction_and_result_candidate",
                             "learning_target_candidate": 12 if seat == 8 else None,
                             "learned_form_candidate": "机械双刀狼" if seat == 8 else None,
                             "official_points": None, "verification_status": "needs_review"})
    events = []

    def event(phase, day, kind, actor, targets, summary, windows, basis="recap_revelation", note=None):
        entry = {"id": f"G{len(events)+1:02d}", "sequence": len(events)+1, "game_phase": phase,
                 "day_number": day, "event_type": kind, "actor_seat": actor, "target_seats": targets,
                 "summary": summary, "statement_type": "candidate_fact", "basis": basis,
                 "evidence_ids": [ev(*w) for w in windows], "verification_status": "needs_review"}
        if note:
            entry["note"] = note
        events.append(entry)

    event("night", 1, "guard", 5, [12], "5号守卫守护12号。", [(2051.905, 2055.465)])
    event("night", 1, "wolf_attack", None, [8], "狼队首刀8号机械狼。", [(2051.905, 2055.465), (263.34, 268.03, "subtitle")])
    event("night", 1, "witch_save", 10, [8], "女巫解救8号（局中解说支持的候选）。", [(306.11, 307.27, "subtitle"), (325.039, 327.359, "subtitle")],
          "commentary_observation", "复盘原句识别为‘女娲/女王救起情人’，不能当作逐字确认；用局中女巫环节的救起8号补充，仍待听核。")
    event("night", 1, "mechanical_learn", 8, [12], "8号机械狼模仿12号狼人，形态为机械双刀狼。", [(2055.805, 2061.755)])
    event("night", 1, "seer_check", 1, [12], "1号通灵师查验12号为狼人。", [(2055.805, 2061.755)])
    event("election", 1, "registration", None, [1,4,5,6,7,8,9,11,12], "最终重播口令：2/3/10号警下，其余9人上警。", [(426.88, 430.3)], "judge_instruction",
          "此前两遍口令有不同号码，采用最后一遍完整重播口令为候选。")
    event("election", 1, "suicide", 12, [], "1号报12号查杀后，12号自爆，警长竞选中断。", [(1139.485, 1153.885), (1159.195, 1161.71), (2061.875, 2063.77)], "in_game_and_recap")
    event("election", 1, "peaceful_night_announcement", None, [], "法官随后公布首夜平安夜。", [(1164.755, 1166.015)], "judge_announcement")
    event("night", 2, "guard", 5, [3], "5号守卫守护3号。", [(2064.095, 2068.035)])
    event("night", 2, "wolf_attack", None, [1], "狼队击杀1号通灵师。", [(2064.095, 2068.035)])
    event("night", 2, "witch_pass", 10, [], "女巫技能空过。", [(2064.095, 2068.035)], note="空过指本次不使用技能，用户已确认词义；该行动仍为本局候选。")
    event("night", 2, "seer_check", 1, [3], "1号通灵师查验3号为狼人。", [(2068.035, 2071.025)])
    event("election", 2, "suicide", 6, [], "延期竞选环节6号自爆，警徽流失。", [(1432.97, 1436.27), (2071.025, 2072.945)], "in_game_and_recap")
    event("day", 2, "death_announcement", 1, [], "法官公布昨夜1号倒牌，没有遗言。", [(1439.3, 1441.62)], "judge_announcement")
    event("night", 3, "guard", 5, [5], "5号守卫自守。", [(2072.92, 2075.76, "subtitle")], note="用户已确认自守含义；并非把识别中的‘四手’写成守4号。")
    event("night", 3, "wolf_attack", None, [7], "狼队击杀7号猎人。", [(2072.92, 2075.76, "subtitle")])
    event("night", 3, "witch_pass", 10, [], "女巫技能空过。", [(2075.76, 2076.88, "subtitle")])
    event("day", 3, "death_announcement", 7, [], "法官公布昨夜7号倒牌，没有遗言。", [(1660.22, 1662.6)], "judge_announcement")
    event("day", 3, "hunter_shot", 7, [8], "7号猎人开枪带走8号机械双刀狼。", [(1667.26, 1675.365), (2077.135, 2080.095)], "in_game_and_recap")
    event("day", 3, "speech_order", None, [11,2,3], "无警徽，随机从11号开始顺序发言；本局实际发言至3号。", [(1680.55, 1689.215), (1813.15, 1815.81), (1926.115, 1928.975)], "judge_instruction")
    event("day", 3, "suicide", 3, [], "3号认狼并自爆。", [(1987.295, 1988.855), (2016.885, 2019.12), (2080.155, 2084.01)], "in_game_and_recap")
    event("ended", 3, "result", None, [], "游戏结束，好人阵营获胜。", [(2019.965, 2021.31), (2080.155, 2084.01)], "in_game_and_recap")

    # Each item is a player claim/summary. It does not establish the claimed role.
    turns_data = [
        (1,4,453.21,476.445,"自称好人，关注9号是否会跳通灵师。", "explicit_handoff"),
        (1,5,481.55,514.0,"自称好人，暂不分享抿牌信息，称图图似乎有话要说。", "explicit_handoff"),
        (1,6,523.69,563.36,"暂不给4/5定性，认为7/8/9或警下可能出身份。", "explicit_handoff"),
        (1,7,566.96,605.095,"以通灵师口吻报9号猎人，并安排警徽流2/10。实际身份候选为猎人。", "explicit_handoff"),
        (1,8,615.0,688.0,"倾向站7，认为9号像猎人，观察12号开牌像狼。", "explicit_handoff"),
        (1,9,692.955,748.72,"质疑10号警下状态转变；倾向站7。", "explicit_handoff"),
        (1,11,756.76,930.695,"以通灵师口吻给2号守卫，安排查验流；实际身份候选为平民。", "explicit_handoff"),
        (1,12,941.745,1119.355,"自称查验干干为金水，讨论7/11关系，警徽流10→5。", "sequence_inference",
         "15:30本地及平台字幕口令均误写‘10号’，而最终警下有10号；本段归12依赖顺序及后续查杀/自爆上下文，待听核。"),
        (1,1,1126.375,1159.195,"报首夜验12号狼人，称已查证，随后12号自爆。", "explicit_handoff"),
        (3,11,1690.06,1812.555,"解释自己是模拟预言家视角，认为9号偏好；继续考虑2/3/5/10。", "explicit_handoff"),
        (3,2,1815.91,1926.115,"拍平民，认为只余一狼，质疑11号排坑不完整，认可9号好人面。", "explicit_handoff",
         "30:19本地识别‘10号是自爆狼’，与已知12号自爆冲突，原文不改，摘要不沿用10号为狼。"),
        (3,3,1929.775,2016.885,"称8号大哥被枪带走后轮次落后、女巫压毒使自己无操作空间，最后认狼自爆。", "explicit_handoff"),
    ]
    turns = []
    for day, seat, start, end, summary, attribution, *note in turns_data:
        turns.append({"id": f"T{len(turns)+1:02d}", "day_number": day,
                      "game_phase": "election" if day == 1 else "day", "seat_number_candidate": seat,
                      "speaker_role_candidate": "player", "start_seconds": start, "end_seconds": end,
                      "content_type": "player_claim", "summary": summary,
                      "attribution_basis": attribution, "evidence_ids": [ev(start, end)],
                      "note": note[0] if note else None, "verification_status": "needs_review",
                      "coverage": "content_summary_and_evidence_window_not_word_perfect_diarization"})

    analyses = [
        {"id": "A01", "program_segment": "night_commentary", "game_phase": "night", "day_number": 2,
         "summary": "解说讨论狼队希望靠连续自爆给机械狼争取刀数，并提醒7号可能是猎人，刀7有被枪带走的风险。",
         "content_type": "commentary_analysis", "speaker_identity": None, "evidence_ids": [ev(1248.8, 1269.15), ev(1361.47, 1367.075)]},
        {"id": "A02", "program_segment": "night_commentary", "game_phase": "night", "day_number": 3,
         "summary": "解说把守卫不守1解释为搏刀，并讨论女巫开毒与压毒的利弊；这些是分析，不是玩家本人心路。",
         "content_type": "commentary_analysis", "speaker_identity": None, "evidence_ids": [ev(1452.2, 1474.53), ev(1594.14, 1631.055)]},
    ]
    recap_evidence = ev(2037.215, 2084.01)
    recap = {
        "program_segment": "post_game_recap", "speaker_role_candidate": "referee",
        "speaker_identity": None, "speaker_role_verified": False,
        "start_seconds": 2037.215, "end_seconds": 2084.01, "evidence_ids": [recap_evidence],
        "normalized_summary": [
            "身份：1通灵师、10女巫、7猎人、5守卫；3/6/12狼人、8机械狼；2/4/9/11平民。",
            "首夜：守12，狼刀8；8学12成为机械双刀狼，1验12为狼；首夜平安夜。女巫救8另由局中解说补充，复盘该词仍不清。",
            "首日：12号在警长竞选中自爆。",
            "第二夜及次日：守3、刀1、女巫空过、1验3为狼；延期竞选6号自爆、警徽流失，1号出局。",
            "第三夜及第三天：5自守、狼刀7、女巫空过；7猎人带走8，3号白天自爆，好人获胜。",
        ],
        "normalization_note": "整理为结构化转述；未替换或覆盖原始机器稿。身份清单按连续语序读取，不按字幕换行错配。",
        "reviewed_terms_source": "prior_user_review",
    }
    issues = [
        {"id": "Q01", "priority": "name_mapping", "question": "核对4/11/12号实际座位姓名。", "details": "4号仅余华仔仔的排除法候选；11号图图可能为申屠；12号勾勾可能为陈俊洁。三项未写为已匹配座位，完整12人名单单独保存。", "evidence_ids": name_data[11][3] + name_data[12][3]},
        {"id": "Q02", "priority": "critical_action", "question": "复听首夜女巫救8号。", "details": "平台局中字幕‘救起了8号’与‘救起来了’支持该候选；复盘仍识别成女娲/女王救起情人，不能据多模型一致宣称已听核。", "evidence_ids": events[2]["evidence_ids"] + [ev(2051.905, 2055.465)]},
        {"id": "Q03", "priority": "speaker_attribution", "question": "复听15:30口令，确认15:41–18:40发言为12号。", "details": "两份机器字幕都写10号，但10号在警下、后面1号报12查杀并遇12自爆。保留顺序推断，不能假称直接播报正确。", "evidence_ids": [ev(930.475, 945.46), turns[7]["evidence_ids"][0]]},
        {"id": "Q04", "priority": "transcript_number", "question": "30:19‘10号是自爆狼’的12/10异文。", "details": "与局中播报及复盘12号自爆、10号女巫冲突；不改变10号女巫角色候选，原文继续保留。", "evidence_ids": [ev(1819.47, 1823.295)]},
        {"id": "Q05", "priority": "nickname_mapping", "question": "确认歪哥→JY、干干→牛肉干、峰哥→翼风、小舞→葛小舞等昵称归并。", "details": "规范姓名来自用户已复核名单；本局昵称到姓名仍属于本次候选，不能借名单的人名确认状态自动批准。", "evidence_ids": sum([name_data[s][3] for s in [7,8,9,10]], [])},
    ]
    sources = {
        "manifest": {"platform": "bilibili", "external_key": "BV1yt7v6QE3Q:39404962859", "path": manifest_file, "kind": "manifest"},
        "transcript": {"platform": "bilibili", "external_key": "BV1yt7v6QE3Q:39404962859", "path": TRANSCRIPT, "kind": "asr"},
        "subtitle": {"platform": "bilibili", "external_key": "BV1yt7v6QE3Q:39404962859", "path": SUBTITLE, "kind": "subtitle"},
        "roster_snapshot": {"platform": "weibo", "external_key": "5313722673268409", "path": (OUT / "roster_source.snapshot.json").relative_to(ROOT).as_posix(), "kind": "candidate", "url": schedule["原帖链接"]},
        "weibo_post": {"platform": "weibo", "external_key": "5313722673268409", "path": (ROOT / BASE / schedule["正文原件"]).resolve().relative_to(ROOT).as_posix(), "kind": "weibo_json", "url": schedule["原帖链接"]},
        "prior_user_review": {"platform": "bilibili", "external_key": "BV1yt7v6QE3Q:39404962859", "path": "data/transcripts/S22/BV1yt7v6QE3Q_p01_funasr/user_review.json", "kind": "candidate"},
    }
    for item in sources.values():
        item["sha256"] = digest(item["path"])
    dossier = {
        "schema_version": 1, "layer": "game_dossier_candidate", "status": "needs_user_review",
        "extraction_method": "assistant_curated_from_complete_transcript_and_reviewed_schedule",
        "game_slug": "bili-BV1yt7v6QE3Q-p01-g03", "bvid": "BV1yt7v6QE3Q", "cid": 39404962859,
        "page": 1, "audio_sha256": manifest["audio"]["sha256"], "sources": sources,
        "metadata_candidates": {"season": "S22", "event_date": "2026-06-25", "phase": "regular", "episode": 4, "day_in_episode": 3,
                                "game_number": 3, "board_name": "机械狼通灵师", "expected_seats": 12,
                                "source_title": manifest["title"], "date_basis": "weibo_event_date_and_video_title_agree",
                                "match_status": "completed", "scoring_eligible": None},
        "roster": roster, "participant_candidates": participants, "game_events": events, "speech_turns": turns,
        "analyses": analyses, "recap": recap,
        "result_candidate": {"winning_faction": "good", "evidence_ids": events[-1]["evidence_ids"], "verification_status": "needs_review"},
        "ballots": {"sheriff": [], "exile": [], "status": "no_completed_ballot_evidence_in_reconstructed_flow",
                    "note": "两次警上/延期竞选自爆，第三天发言至3号自爆；不把无记录投票写成弃票，也不凭本样本确认规则。"},
        "evidence": evidence, "unresolved_items": issues,
        "coverage": {"full_transcript_read": True, "audio_listening_performed_this_pass": False,
                     "player_turn_summaries": len(turns), "game_events": len(events),
                     "formal_recap_preserved": True, "points_verified": False,
                     "excluded_program_content": [{"start": 0, "end": 104.25, "reason": "上一局分析，不属于本局事件"},
                                                  {"start": 2084.435, "end": 2169.985, "reason": "鲜花留言、节目收尾"},
                                                  {"start": 2182.525, "end": 2220.88, "reason": "广告剧情，含空刀/跳女巫/投3等台词，不能计入本局"}]},
        "review": {"review_complete": False, "reviewer": None, "batch_authorized_after_sample_review": False},
    }
    save_json("dossier.v1.json", dossier)
    render(dossier)
    print(json.dumps({"dossier": str(OUT / "dossier.v1.json"), "roster": len(roster), "seat_name_candidates": sum(p["name_candidate"] is not None for p in participants), "events": len(events), "turn_summaries": len(turns), "evidence": len(evidence)}, ensure_ascii=False))
    return dossier


def render(d):
    def citations(ids):
        return "、".join(f"[{x} {clock(d['evidence'][x]['start_seconds'])}](#e-{x})" for x in ids)
    md = ["# 单局数据库示例：2026-06-25 第三局", "", "S22 正赛第四期 Day-3 · 机械狼通灵师 · BV1yt7v6QE3Q", "",
          "**状态：待你审核的数据库草稿。** 结局候选为好人获胜。已结合整条转写与平台字幕整理，尚未在本轮听音确认。", "",
          "完整排班12人：" + "、".join(r["name"] for r in d["roster"]) + "。名单姓名采用你已复核的照片映射；照片序号没有用于匹配座位。", "",
          "## 座位与身份候选", "", "| 座位 | 姓名候选 | 身份候选 | 姓名对应依据 |", "|---:|---|---|---|"]
    for p in d["participant_candidates"]:
        md.append(f"| {p['seat_number']} | {p['name_candidate'] or '待对应'} | {p['role_candidate']}{'；学12→机械双刀狼' if p['seat_number']==8 else ''} | {p['name_note']} {citations(p['name_evidence_ids'])} |")
    md += ["", "身份清单证据：" + citations(d["participant_candidates"][0]["role_evidence_ids"]) + "。个人输赢按阵营结果推导，积分留空。", "",
           "## 逐夜与白天进程", "", "| 阶段 | 事件 | 依据 |", "|---|---|---|"]
    phases = {"night": "夜", "day": "天白天", "election": "天警长竞选", "ended": "天结束"}
    for event in d["game_events"]:
        md.append(f"| 第{event['day_number']}{phases[event['game_phase']]} | {event['summary']} | {citations(event['evidence_ids'])} |")
    md += ["", "## 玩家发言主张", "", "以下是发言内容摘要；自称查验、角色或狼坑不代表事实。12段记录覆盖本局主要玩家发言轮次，尚不是逐字精确的多人分离结果。", "", "| 阶段/座位 | 原视频时间 | 发言摘要 |", "|---|---|---|"]
    for turn in d["speech_turns"]:
        md.append(f"| 第{turn['day_number']}天 / {turn['seat_number_candidate']}号 | {clock(turn['start_seconds'])}–{clock(turn['end_seconds'])} | {turn['summary']} {citations(turn['evidence_ids'])} {'**归属待听核**' if turn['attribution_basis']=='sequence_inference' else ''} |")
    md += ["", "## 复盘整理", "", "复盘原视频时间：33:57–34:44。下文为整理转述，原始机器稿完整保留。", ""]
    md += [f"- {line}" for line in d["recap"]["normalized_summary"]]
    md += ["", citations(d["recap"]["evidence_ids"]), "", "局中解说的分析另列：", ""]
    md += [f"- {a['summary']} {citations(a['evidence_ids'])}" for a in d["analyses"]]
    md += ["", "## 需要你重点核对", ""]
    md += [f"- **{q['id']} {q['question']}** {q['details']} {citations(q['evidence_ids'])}" for q in d["unresolved_items"]]
    md += ["", "## 数据范围", "", "没有发现完成的警徽投票或放逐投票记录，票型数组留空并附说明；没有补造弃票或积分。00:00–01:44是上一局分析；34:44之后的鲜花、收尾与36:22之后的广告台词均不计入本局。", "",
           "数据库保存12个参赛人名、12座候选、逐夜/白天事件、玩家主张、解说分析、复盘原文、来源哈希与缺口。候选保存于 extraction_runs.payload 和 game_participants.proposed，版本保持 draft。", "",
           "## 逐条原文证据", ""]
    for key, value in d["evidence"].items():
        source = d["sources"][value["source_ref"]]
        md += [f"<a id=\"e-{key}\"></a>", f"### {key} · {clock(value['start_seconds'])}–{clock(value['end_seconds'])}", "",
               f"来源：`{source['path']}` · `{value['locator']}` · [原视频定位]({URL}&t={int(value['start_seconds'])})", "",
               "> " + value["quote"].replace("\n", "\n> "), ""]
    (OUT / "单局示例_审核.md").write_text("\n".join(md), encoding="utf-8")
    export_csv(OUT / "座位身份候选.csv", ["座位", "姓名候选", "身份候选", "姓名对应依据", "审核状态"],
               [[p["seat_number"], p["name_candidate"] or "待对应", p["role_candidate"], p["name_note"], "待本次审核"] for p in d["participant_candidates"]])
    export_csv(OUT / "游戏事件候选.csv", ["事件编号", "顺序", "天数", "阶段", "类型", "行动座位", "目标", "内容", "证据", "审核状态"],
               [[e["id"], e["sequence"], e["day_number"], e["game_phase"], e["event_type"], e["actor_seat"], "/".join(map(str,e["target_seats"])), e["summary"], "/".join(e["evidence_ids"]), "待审核"] for e in d["game_events"]])
    # A dependency-free review document with local audio, source jumps and exact quotes.
    esc = html.escape
    def local(relative):
        import os
        return quote(Path(os.path.relpath(ROOT / relative, OUT)).as_posix(), safe="/.:_")
    def links(ids):
        return " ".join(f'<a class="chip" href="#e-{x}">{x} {clock(d["evidence"][x]["start_seconds"])}</a>' for x in ids)
    def table(headers, values):
        return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{esc(x)}</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join(f'<td>{x}</td>' for x in row)+'</tr>' for row in values) + '</tbody></table></div>'
    sections = []
    sections.append('<section><h2>座位与身份候选</h2><p>12个姓名已由你复核；本局的姓名到座位、角色及事件待此次审核。4/11/12号暂不强行对应。</p>' + table(["座位", "姓名候选", "身份候选", "对应依据"], [[str(p["seat_number"]), esc(p["name_candidate"] or "待对应"), esc(p["role_candidate"] + (" · 学12→机械双刀狼" if p["seat_number"]==8 else "")), esc(p["name_note"]) + links(p["name_evidence_ids"])] for p in d["participant_candidates"]]) + '<p>身份清单：'+links(d["participant_candidates"][0]["role_evidence_ids"])+ '</p></section>')
    sections.append('<section><h2>逐夜与白天进程</h2>' + table(["编号/阶段", "过程候选", "证据"], [[f'{e["id"]} · 第{e["day_number"]}{phases[e["game_phase"]]}', esc(e["summary"]) + ('<small>'+esc(e["note"])+'</small>' if e.get("note") else ''), links(e["evidence_ids"])] for e in d["game_events"]]) + '</section>')
    sections.append('<section><h2>玩家发言主张</h2><p>主张存在不证明内容属实。以下保留12段内容摘要与整段证据窗口；发言内可能穿插解说，尚未逐字分离说话人。</p>'+table(["阶段/座位", "时间", "摘要"], [[f'第{t["day_number"]}天 · {t["seat_number_candidate"]}号', f'{clock(t["start_seconds"])}–{clock(t["end_seconds"])}', esc(t["summary"])+(('<small>'+esc(t["note"])+ '</small>') if t.get("note") else '')+links(t["evidence_ids"])] for t in d["speech_turns"]])+'</section>')
    sections.append('<section><h2>复盘整理 · 33:57–34:44</h2><p>结构化转述；原机器稿保留于证据中。</p><ul>'+''.join('<li>'+esc(x)+'</li>' for x in d["recap"]["normalized_summary"])+ '</ul>'+links(d["recap"]["evidence_ids"])+ '<h3>局中解说分析</h3>'+''.join('<p>'+esc(a["summary"])+links(a["evidence_ids"])+ '</p>' for a in d["analyses"])+ '</section>')
    sections.append('<section class="issues"><h2>重点审核 · 5项</h2>'+''.join(f'<article><h3>{q["id"]} {esc(q["question"])}</h3><p>{esc(q["details"])}</p>{links(q["evidence_ids"])}</article>' for q in d["unresolved_items"])+ '</section>')
    sections.append('<section><h2>范围与文件</h2><p>游戏过程含22条事件候选。没有识别到完成的警徽/放逐投票；不记作弃票。积分未知。上一局讨论、鲜花留言、节目收尾及36:22后的广告剧情已排除。</p><p><a href="dossier.v1.json">结构化JSON</a> · <a href="座位身份候选.csv">座位CSV</a> · <a href="游戏事件候选.csv">事件CSV</a> · <a href="单局示例_审核.md">Markdown</a> · <a href="roster_source.snapshot.json">排班与姓名复核快照</a></p><p>数据库：本地PostgreSQL，草稿候选保存在 extraction_runs.payload / game_participants.proposed；没有生成本次用户审核记录。</p></section>')
    details = []
    for key, value in d["evidence"].items():
        source = d["sources"][value["source_ref"]]
        details.append(f'<details id="e-{key}"><summary>{key} · {clock(value["start_seconds"])}–{clock(value["end_seconds"])} · {esc(value["source_ref"])}</summary><p><button type="button" data-seek="{value["start_seconds"]}" data-end="{value["end_seconds"]}">播放原音频此段</button> <a href="{URL}&t={int(value["start_seconds"])}" target="_blank" rel="noopener">原视频定位</a> · <a href="{local(source["path"])}">源文件</a></p><p class="locator">{esc(source["path"])} · {esc(value["locator"])}</p><blockquote>{esc(value["quote"])}</blockquote></details>')
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>单局审核 · 2026-06-25 第三局</title><style>
*{box-sizing:border-box}body{margin:0;background:#f1f4f6;color:#18313f;font:16px/1.7 "Microsoft YaHei",sans-serif}main{max-width:1180px;margin:auto;padding:30px 24px 180px}h1{font-size:30px;line-height:1.4;margin:0 0 10px}h2{font-size:23px;margin:0 0 16px}h3{font-size:17px}section{background:white;border:1px solid #dce4e8;border-radius:14px;padding:26px;margin:22px 0}a{color:#126ba0}table{border-collapse:collapse;width:100%;min-width:700px}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #e3eaee}th{background:#edf3f6;font-weight:600}td:first-child{white-space:nowrap}.scroll{overflow:auto}.chip{display:inline-block;background:#edf4fa;border-radius:6px;padding:1px 6px;margin:3px;font-size:12px;text-decoration:none;white-space:nowrap}small{display:block;color:#7b541b;margin:6px 0}.badge{background:#fff0c7;padding:5px 12px;border-radius:7px;display:inline-block}.lead{max-width:900px;color:#47606e}.issues{border-color:#e5ca8e}.issues article{border-top:1px solid #eee4cc;padding:8px 0 16px}.player{position:fixed;bottom:0;left:0;right:0;background:#18313f;color:#fff;padding:12px 24px;z-index:2;box-shadow:0 -3px 15px #0002}.player>div{max-width:1130px;margin:auto;display:flex;align-items:center;gap:15px;flex-wrap:wrap}.player audio{flex:1;min-width:250px;height:40px}details{background:white;border:1px solid #dce4e8;border-radius:8px;margin:10px 0;padding:14px;scroll-margin-top:15px}details:target{border-color:#126ba0}summary{cursor:pointer;font-weight:600}blockquote{white-space:pre-wrap;margin:15px 0;padding:15px;background:#f3f6f8;border-left:3px solid #126ba0}.locator{font-size:12px;overflow-wrap:anywhere;color:#617580}button{background:#126ba0;border:0;color:white;padding:7px 12px;border-radius:6px;cursor:pointer}.muted{font-size:13px;color:#617580}@media(max-width:650px){main{padding:22px 12px 190px}section{padding:16px}h1{font-size:25px}.player{padding:9px 12px}}
</style><main>'''
    document += '<h1>2026-06-25 · 第三局数据库示例</h1><p>S22 正赛第四期 Day-3 · 机械狼通灵师 · BV1yt7v6QE3Q</p><p class="badge">待你审核 · 好人获胜候选</p><p class="lead">'+esc('完整排班：'+'、'.join(r['name'] for r in d['roster']))+'。</p><p class="lead">点击证据编号可查看原文，或播放本地原音频。当前已通读整条转写，尚未在本轮听音确认。</p>' + ''.join(sections) + '<h2>原文证据 · '+str(len(details))+'条定位</h2>'+''.join(details)+'</main>'
    document += '<div class="player"><div><strong>原音频</strong><span id="now">点击证据播放</span><audio id="audio" controls preload="metadata" src="'+local("data/raw/bilibili/BV1yt7v6QE3Q/p01/audio.m4a")+'"></audio></div></div>'
    document += '''<script>
const audio=document.getElementById('audio');let stopAt=null;
document.querySelectorAll('[data-seek]').forEach(b=>b.addEventListener('click',()=>{audio.currentTime=Number(b.dataset.seek);stopAt=Number(b.dataset.end)+0.3;document.getElementById('now').textContent=b.closest('details').querySelector('summary').textContent;audio.play().catch(()=>{});}));
audio.addEventListener('timeupdate',()=>{if(stopAt!==null&&audio.currentTime>=stopAt){audio.pause();stopAt=null;}});
function openEvidence(){const id=location.hash.slice(1);if(id.startsWith('e-')){const d=document.getElementById(id);if(d)d.open=true;}}window.addEventListener('hashchange',openEvidence);openEvidence();
</script></html>'''
    (OUT / "单局示例_审核.html").write_text(document, encoding="utf-8")


def export_csv(path, headers, values):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(values)


if __name__ == "__main__":
    from build_fixed_game_sample import build as build_current
    build_current()
