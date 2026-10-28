"""Validate semantic bluff assessments, bind them to facts, and build review artifacts."""
from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
from html import escape
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from website.api.bluffs import METHODOLOGY, S23_VIDEO_METHODOLOGY, physical_wolf, review_items, source_fingerprint
from website.api import publisher

WORK = ROOT / "data" / "extractions" / "S22" / "bluff_review"
PUBLIC = ROOT / "website" / "assets" / "bluffs" / "S22.json"


def normalized(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", text).lower()


@lru_cache(maxsize=512)
def source_segments(path: str) -> list[dict]:
    source = ROOT / path
    if source.suffix == ".json":
        data = json.loads(source.read_text(encoding="utf-8-sig"))
        rows = data.get("body", data.get("segments", data.get("recap_segments", [])))
        return [{"start_ms": row.get("start_ms", round(row.get("from", 0) * 1000)),
                 "end_ms": row.get("end_ms", round(row.get("to", 0) * 1000)),
                 "text": row.get("text", row.get("content", ""))} for row in rows]
    rows = []
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"\[([\d.]+)[–—-]([\d.]+)\]\s*(.*)", line)
        if match:
            rows.append({"start_ms": round(float(match[1]) * 1000),
                         "end_ms": round(float(match[2]) * 1000), "text": match[3]})
    return rows


def validate_evidence(entry: dict, game_dir: str, bvid: str) -> str | None:
    path = entry.get("source_path", "")
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT) or not resolved.is_file():
        return "证据来源不存在或不在本项目内"
    if bvid not in path and not resolved.is_relative_to((ROOT / game_dir).resolve()):
        return "证据来源不属于该局"
    start, end = entry.get("start_ms"), entry.get("end_ms")
    if type(start) is not int or type(end) is not int or start < 0 or end < start:
        return "证据时间范围无效"
    try:
        rows = source_segments(path)
    except (ValueError, KeyError, TypeError):
        return "证据来源无法解析"
    text = normalized("".join(row["text"] for row in rows
                             if row["end_ms"] >= start - 1000 and row["start_ms"] <= end + 1000))
    fragments = [normalized(part) for part in re.split(r"…+|\.{3,}", entry.get("text", ""))]
    fragments = [part for part in fragments if part]
    if not fragments:
        return "证据摘录为空"
    offset = 0
    for part in fragments:
        at = text.find(part, offset)
        if at == -1:
            return "摘录与指定时间窗转写不完全匹配，请复核数字、遗漏词或定位"
        offset = at + len(part)
    return None


def listening_hint(game: dict, seat: int) -> dict | None:
    """Offer a speaker-call timestamp for unresolved cases, never a classification."""
    numerals = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六",
                7: "七", 8: "八", 9: "九", 10: "十", 11: "十一", 12: "十二"}
    name = next(row["name"] for row in game["seats"] if row["seat"] == seat)
    number = rf"(?<![0-9一二三四五六七八九十])(?:{seat}|{numerals[seat]})号"
    actor = rf"(?:{number}|{re.escape(name)})"
    pattern = re.compile(rf"(?:请{actor}(?:玩家|老师)?发言|{actor}(?:玩家|老师|的)?请发言)")
    for file in game.get("files", []):
        if file.get("role") not in {"subtitle", "transcript"}:
            continue
        rows = source_segments(file["path"])
        for index, row in enumerate(rows):
            if row["start_ms"] >= 300_000 and pattern.search(row["text"]):
                selected = rows[index:index + 3]
                return {"kind": "listening_hint", "source_path": file["path"],
                        "start_ms": selected[0]["start_ms"], "end_ms": selected[-1]["end_ms"],
                        "text": "".join(entry["text"] for entry in selected),
                        "interpretation": f"转写中疑似请{seat}号发言的位置，仅提供回听入口，不作为已确认的说话归属或悍跳证据。"}
    return None


def build(*, allow_partial: bool = False) -> tuple[dict, list[dict], dict]:
    sources = {}
    entries, _, _ = publisher.load_publication(ROOT, "S22")
    for item in entries:
        dossier = item["dossier"]
        identities = {seat["name"]: seat["name"] for seat in dossier["seats"]}
        game = publisher._public_game(dossier, item["voting"], item["endgame"],
                                      item["audit"], item["board"], identities)
        # Evidence lookup stays local; binding and success evaluation use the
        # exact public timeline, including its source-bound terminal boundary.
        game["files"] = dossier.get("files", [])
        sources[game["id"]] = (game, item["folder"].relative_to(ROOT).as_posix())
    merged = {}
    for path in sorted(WORK.glob("part_?.json")):
        for game in json.loads(path.read_text(encoding="utf-8")).get("games", []):
            key = game["game_id"]
            if key in merged:
                raise ValueError(f"duplicate game assessment: {key}")
            if key not in sources:
                raise ValueError(f"assessment outside current S22 scope: {key}")
            merged[key] = game
    if not allow_partial and set(merged) != set(sources):
        raise ValueError(f"incomplete assessment: {len(merged)}/{len(sources)} games")

    required_rechecks = {(game_id, row["seat"]) for game_id, game in merged.items()
                         for row in game.get("assessments", []) if row.get("decision") in {"yes", "uncertain"}}
    rechecked = set()
    for path in sorted(WORK.glob("recheck_?.json")):
        audit = json.loads(path.read_text(encoding="utf-8"))
        for update in audit.get("games", []):
            key = update["game_id"]
            if key not in merged:
                raise ValueError(f"recheck outside scope: {key}")
            current = {row["seat"]: row for row in merged[key]["assessments"]}
            for row in update.get("assessments", []):
                entry_key = (key, row["seat"])
                if entry_key in rechecked:
                    raise ValueError(f"duplicate recheck: {entry_key}")
                rechecked.add(entry_key)
                current[row["seat"]] = row
            merged[key]["assessments"] = list(current.values())
            merged[key]["first_day_end_ms"] = update.get("first_day_end_ms")
    user_path = WORK / "user_confirmed.json"
    human = json.loads(user_path.read_text(encoding="utf-8")).get("records", {}) if user_path.exists() else {}

    validation_issues = []
    public_games = []
    for key, record in merged.items():
        game, game_dir = sources[key]
        fingerprint = source_fingerprint(game)
        bvid = game["source"]["bvid"]
        by_seat = {row["seat"]: row for row in game["seats"]}
        seen = set()
        assessments = []
        for row in record.get("assessments", []):
            seat = row["seat"]
            if seat in seen:
                raise ValueError(f"duplicate actor assessment: {key}/{seat}")
            seen.add(seat)
            actual = by_seat.get(seat)
            if actual is None or row.get("name") != actual["name"] or row.get("physical_role") != actual["role"]:
                raise ValueError(f"identity mismatch: {key}/{seat}")
            if row.get("decision") not in {"yes", "no", "uncertain"}:
                raise ValueError(f"unsupported decision: {key}/{seat}")
            if not physical_wolf(game, actual):
                continue
            clean = {key_: row.get(key_) for key_ in ("seat", "name", "physical_role", "decision", "claimed_role", "confidence",
                                                     "claim_day", "first_day_claim", "decision_note")}
            clean["verification_status"] = "assistant_inferred"
            clean["review_questions"] = list(row.get("review_questions", []))
            clean["evidence"] = []
            valid_count = 0
            for entry in row.get("evidence", []):
                problem = validate_evidence(entry, game_dir, bvid)
                valid_count += int(problem is None)
                public = {field: entry[field] for field in
                          ("kind", "start_ms", "end_ms", "text", "interpretation") if field in entry}
                if problem:
                    clean["review_questions"].append(problem)
                    validation_issues.append({"game_id": key, "seat": seat, "source_path": entry.get("source_path"),
                                              "start_ms": entry.get("start_ms"), "problem": problem})
                clean["evidence"].append(public)
            if clean["decision"] == "yes" and (valid_count == 0 or clean["claimed_role"] not in {"预言家", "通灵师"}):
                clean["decision"] = "uncertain"
                clean["review_questions"].append("定位证据或所跳身份尚不足以纳入已识别悍跳次数")
            if clean["decision"] == "uncertain":
                hint = listening_hint(game, seat)
                if hint is not None and validate_evidence(hint, game_dir, bvid) is None:
                    clean["evidence"].append({field: hint[field] for field in
                        ("kind", "start_ms", "end_ms", "text", "interpretation")})
            human_row = human.get(f"{bvid}:{seat}")
            if human_row and human_row.get("source_fingerprint") == fingerprint:
                action = human_row.get("decision")
                if action in {"yes", "no", "uncertain"}:
                    clean["decision"] = action
                    clean["claimed_role"] = (human_row.get("claimed_role") or clean.get("claimed_role")) if action == "yes" else None
                    clean["claim_day"] = human_row.get("claim_day") if human_row.get("claim_day") is not None else clean.get("claim_day")
                    clean["first_day_claim"] = (clean["claim_day"] == 1 if clean["claim_day"] is not None else None) if action == "yes" else False
                    clean["review_questions"] = [] if action != "uncertain" else [human_row.get("notes") or "用户复核后仍无法判断"]
                    if action == "yes" and clean["claimed_role"] not in {"预言家", "通灵师"}:
                        clean["review_questions"].append("用户已确认悍跳，所跳身份尚待补充")
                    clean["verification_status"] = "user_confirmed" if action != "uncertain" else "user_uncertain"
                    clean["decision_note"] = "用户复核：" + (human_row.get("notes") or ("确认是悍跳" if action == "yes" else "确认不是悍跳"))
                    if human_row.get("normalization_notes"):
                        clean["decision_note"] += "；整理说明：" + "；".join(human_row["normalization_notes"])
                else:
                    clean["review_questions"].append("用户意见：" + (human_row.get("notes") or "请重新核对后续天数的起跳"))
                    clean["verification_status"] = "user_comment"
                    if action == "later":
                        clean["decision"] = "uncertain"
            elif human_row:
                clean["review_questions"].append("已有用户反馈对应的原始记录已变化，需重新确认")
            clean["review_questions"] = list(dict.fromkeys(clean["review_questions"]))
            assessments.append(clean)
        expected = {seat["seat"] for seat in game["seats"] if physical_wolf(game, seat)}
        if not expected.issubset(seen):
            raise ValueError(f"missing wolf seats: {key}/{sorted(expected-seen)}")
        public_games.append({"game_id": key, "bvid": bvid,
                             "source_fingerprint": fingerprint,
                             "coverage": record.get("coverage"), "assessments": assessments})

    payload = {"schema_version": 1, "season": "S22", "inference_version": "S22-bluff-20261025-v3",
               "status": "user_review_applied_with_assistant_inference" if human else "assistant_inferred_pending_user_review", "methodology": METHODOLOGY,
               "games": public_games}
    games = [value[0] for value in sources.values()]
    items = review_items(games, payload)
    summary = {"games_total": len(sources), "games_assessed": len(merged),
               "wolf_appearances": len(items), "decisions": dict(Counter(row["decision"] for row in items)),
               "successful_bluffs": sum(row["decision"] == "yes" and row["success"] is True for row in items),
               "pending": sum(row["needs_review"] for row in items),
               "evidence_validation_issues": len(validation_issues), "validation_issues": validation_issues}
    summary["rechecked_candidates"] = len(required_rechecks.intersection(rechecked))
    summary["unrechecked_candidates"] = len(required_rechecks - rechecked)
    summary["user_confirmed_records"] = sum(row.get("verification_status") == "user_confirmed" for row in items)
    payload["summary"] = {key: value for key, value in summary.items() if key != "validation_issues"}
    return payload, items, summary


def feedback_fields(row: dict) -> str:
    prefix = f"feedback-{row['bvid']}-{row['seat']}"
    decisions = [("", "尚未填写"), ("yes", "确认是悍跳"), ("no", "确认不是悍跳"),
                 ("later", "仅后续天数起跳，请再核查"), ("uncertain", "仍无法确定"), ("comment", "有其他意见")]
    decision_options = "".join(f'<option value="{value}">{label}</option>' for value, label in decisions)
    role_options = "".join(f'<option value="{value}"' + (" selected" if value == (row['claimed_role'] or '') else "") + f'>{label}</option>'
                           for value, label in [("", "待定／不适用"), ("预言家", "预言家"), ("通灵师", "通灵师")])
    day_options = "".join(f'<option value="{value}"' + (" selected" if value == str(row.get('claim_day') or '') else "") + f'>{label}</option>'
                          for value, label in [("", "尚未确定"), ("1", "第一天"), ("2", "第二天（含延期竞选）"), ("later", "后续天数，请见意见")])
    attributes = {"review-id": row["review_id"], "game-id": row["game_id"], "bvid": row["bvid"],
                  "seat": row["seat"], "name": row["name"], "physical-role": row["physical_role"],
                  "fingerprint": row["source_fingerprint"]}
    attrs = " ".join(f'data-{key}="{escape(str(value), quote=True)}"' for key, value in attributes.items())
    return f'''<form class="bluff-feedback-form" {attrs} aria-label="复核 {escape(row['name'])} {row['review_id']}">
<h3>填写本条复核意见</h3><div class="choices">
<label for="{prefix}-decision">复核结论<select id="{prefix}-decision" name="decision">{decision_options}</select></label>
<label for="{prefix}-day">发生天数<select id="{prefix}-day" name="claim_day">{day_options}</select></label>
<label for="{prefix}-role">所跳身份<select id="{prefix}-role" name="claimed_role">{role_options}</select></label></div>
<label for="{prefix}-notes">其他意见<textarea id="{prefix}-notes" name="notes" rows="3" maxlength="4000" placeholder="可填写正确座位、首日时间点、所跳身份或不同意见。"></textarea></label>
<p data-feedback-row-status>尚未填写</p></form>'''


def render_html(items: list[dict], summary: dict, inference_version: str = "S22-bluff-20261025-v3",
                *, season: str = "S22", frame_paths: dict[str,str] | None = None) -> str:
    cards = []
    for row in sorted(items, key=lambda x: (not x["needs_review"], x["date"], x["game_id"], x["seat"])):
        label = ("悍跳归属待复核" if row["decision"] == "uncertain" else "推断不是悍跳" if row["decision"] == "no" else
                 "成功结果待复核" if row["success"] is None else "推断成功" if row["success"] else "推断未成功")
        if row.get("verification_status") == "user_confirmed":
            label = "用户确认不是悍跳" if row["decision"] == "no" else "用户确认悍跳 · " + ("成功结果待补" if row["success"] is None else "按规则成功" if row["success"] else "按规则未成功")
        if row.get('assistant_pending'):label='待助手继续核查'
        evidence = []
        for entry in row["evidence"]:
            stamp = entry.get("start_ms", 0) // 1000
            time = f"{stamp//3600:02}:{stamp//60%60:02}:{stamp%60:02}"
            evidence.append(f'<blockquote>{escape(entry.get("text", ""))}</blockquote>'
                            f'<p>{escape(entry.get("interpretation", ""))}</p>'
                            f'<a href="{escape(entry.get("url", ""))}" target="_blank" rel="noreferrer">原视频 {time}</a>')
            image_path=(frame_paths or {}).get(entry.get("image_url"))
            if image_path:
                evidence.append(f'<figure><a href="{escape(image_path,quote=True)}" target="_blank">'
                                f'<img src="{escape(image_path,quote=True)}" alt="原视频发言摘要截图 {time}" '
                                'loading="lazy" style="max-width:100%;height:auto"></a>'
                                f'<figcaption>原视频截图 {time}，点击查看原图；导播摘要与转写交叉核对。</figcaption></figure>')
        questions = "".join(f"<li>{escape(text)}</li>" for text in row["review_questions"])
        reasons = "".join(f"<p>{escape(reason['text'])}</p>" for reason in row["success_reasons"])
        search = escape(f"{row['date']} {row['name']} {row['bvid']} {row['seat']}号")
        phase = "第一天" if row.get("first_day_claim") is True else "第二天／延期竞选" if row.get("claim_day") == 2 else "见首日发言与前后推断"
        if row.get('claim_day')=='later' and type(row.get('actual_claim_day')) is int:
            phase=f"第{row['actual_claim_day']}天（后续起跳）"
        user_pending=row.get('requires_user_review',row['needs_review'])
        assistant_pending=row.get('assistant_pending',False)
        feedback=feedback_fields(row) if not assistant_pending else '<p>此项留待助手继续，不需要你填写。</p>'
        cards.append(f'<article data-pending="{int(user_pending)}" data-assistant-pending="{int(assistant_pending)}" data-search="{search}">'
                     f'<h2>{escape(row["date"])} 第{row["game_number"]}局 · {row["seat"]}号 {escape(row["name"])} · {label}</h2>'
                     f'<p>底牌：{escape(row["physical_role"])}；自称：{escape(row["claimed_role"] or "待定")}；起跳阶段：{phase}</p>'
                     f'<p>{escape(row.get("decision_note") or "")}</p><ul class="questions">{questions}</ul>{reasons}{"".join(evidence)}'
                     f'<p class="key">反馈编号：{row["review_id"]}</p>{feedback}</article>')
    notes = "".join(f"<li>{escape(note)}</li>" for note in METHODOLOGY + (S23_VIDEO_METHODOLOGY if season == 'S23' else []))
    summary_text = (f"已检查{summary['games_assessed']}/{summary['games_total']}局；暂识别{summary['decisions'].get('yes',0)}次悍跳；"
                    f"成功{summary['successful_bluffs']}次；{summary['pending']}项待复核；已应用{summary.get('user_confirmed_records',0)}条用户确认。用户复核与助手推断逐条标明。")
    if season=='S23':
        summary_text=(f"本轮已完成视频与转写复核{summary['games_assessed']}/{summary['games_total']}局；"
                      f"本轮已核实{summary.get('audited_identified_bluffs',0)}次悍跳；"
                      f"{summary['pending']}项需你判断；{summary.get('assistant_pending',0)}个狼位待助手继续。"
                      + ("全部对局已完成复核，截图与原文时间戳逐项保留。" if summary['games_assessed']==summary['games_total']
                         else "未完成场次的既有推断保留标记，不混入需要你亲自判断的清单。"))
    template = (ROOT / "scripts/templates/bluff_review_form.html").read_text(encoding="utf8")
    template = template.replace("S22 悍跳", f"{season} 悍跳")
    if season == 'S23':
        template = template.replace('悍跳推断与填写复核','悍跳推断与复核')
        template=template.replace('<button type="button" id="pending">只看待复核</button>',
                                  '<button type="button" id="pending">只需你判断</button><button type="button" id="assistant-pending">待助手继续</button>')
        script="""let mode='pending';
const filter=()=>{const q=document.querySelector('#search').value.trim().toLowerCase();document.querySelectorAll('article').forEach(el=>{const match=mode==='all'||(mode==='pending'?el.dataset.pending==='1':el.dataset.assistantPending==='1');el.hidden=!match||!el.dataset.search.toLowerCase().includes(q);});};
document.querySelector('#pending').onclick=()=>{mode='pending';filter();};
document.querySelector('#assistant-pending').onclick=()=>{mode='assistant';filter();};
document.querySelector('#all').onclick=()=>{mode='all';filter();};
document.querySelector('#search').oninput=filter;filter();"""
        template=re.sub(r"let pending=.*?document\.querySelector\('#search'\)\.oninput=filter;filter\(\);",lambda _:script,template,flags=re.S)
    runtime = (ROOT / "website/web/src/lib/bluff-feedback-runtime.js").read_text(encoding="utf8")
    options = json.dumps({"season": season, "inference_version": inference_version}, ensure_ascii=False)
    for key, value in [("__SUMMARY__", summary_text), ("__NOTES__", notes), ("__CARDS__", "".join(cards)),
                       ("__RUNTIME__", runtime), ("__OPTIONS__", options)]:
        template = template.replace(key, value)
    return template


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload, items, summary = build(allow_partial=args.allow_partial)
    if not args.check:
        if summary["unrechecked_candidates"]:
            raise ValueError(f"first-day recheck still incomplete: {summary['unrechecked_candidates']} candidate records")
        PUBLIC.parent.mkdir(parents=True, exist_ok=True)
        PUBLIC.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        WORK.mkdir(parents=True, exist_ok=True)
        (WORK / "validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        (ROOT / "data/exports/S22_悍跳推断与复核.html").write_text(render_html(items, summary, payload["inference_version"]), encoding="utf-8")
        (ROOT / "data/exports/S22_悍跳推断与复核.json").write_text(json.dumps({"summary": summary, "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
