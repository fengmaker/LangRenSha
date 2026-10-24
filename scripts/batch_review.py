"""Render local batch-review pages and CSV exports for S22 game dossiers."""
from __future__ import annotations

import csv
import html
import json
import os
from pathlib import Path
import re
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]

_UNKNOWN = "未知"
_STATE_LABELS = {
    "reviewed": "人工复核完成",
    "processing": "处理中",
    "prepared": "已生成待入库",
    "awaiting_import": "已校验待入库",
    "imported": "已入库待复核",
    "imported_pending_review": "已入库待复核",
    "已入库待复核": "已入库待复核",
    "preserved": "已保留",
    "pending": "待处理",
    "failed": "失败",
    "needs_review": "待人工复核",
}
_ACTION_LABELS = {
    "unknown": "未知",
    "pass": "主动空过",
    "unavailable": "不适用",
    "not_held": "未举行",
    "none": "无",
    "peaceful": "平安夜",
    "guard": "守护",
    "attack": "击杀",
    "save": "使用解药",
    "poison": "使用毒药",
    "check": "查验",
    "learn": "学习",
    "shoot": "开枪",
    "register": "报名",
    "continued": "延续",
    "vote": "投票",
    "elected": "当选",
    "deferred": "暂缓",
    "die": "出局",
    "exile": "放逐",
    "transfer": "移交警徽",
    "hold": "保留警徽",
    "self_destruct": "自爆",
    "choose": "选择",
    "select": "选定",
    "view": "查看",
    "exchange": "交换",
    "verify": "验证",
    "give_mask": "给予面具",
    "dance": "共舞",
    "reveal": "翻牌",
    "duel": "决斗",
    "dream": "梦游",
    "communicate": "交流",
    "arrest": "抓捕",
    "meet": "见面",
    "good": "好人阵营",
    "wolf": "狼人阵营",
    "can_shoot": "可以开枪",
    "cannot_shoot": "不能开枪",
    "carrying": "已带刀",
    "not_carrying": "未带刀",
    "apply": "生效",
    "cancelled": "取消",
    "speak": "发言",
    "minority_dies": "少数阵营出局",
    "no_death": "无出局",
    "single_wolf_attack": "单狼行动",
    "couple_attack": "情侣行动",
    "witness_attack": "证婚人行动",
    "suicide": "殉情",
    "not_triggered": "未触发",
    "swallow": "吞警徽",
    "wolves_win": "狼人胜利",
    "good_win": "好人胜利",
    "couple_win": "情侣胜利",
    "ongoing": "继续游戏",
    "reverse_check": "反转查验",
    "skill_disabled": "技能失效",
    "no_effect": "无效果",
    "forbidden": "禁止发动",
    "delay_death": "延迟死亡",
    "no_skill": "无技能",
    "wounded": "受伤",
    "poisoned": "中毒",
    "not_wounded": "未受伤",
    "die_after_speech": "发言后死亡",
    "avoid_exile": "免于放逐",
    "order": "安排发言顺序",
}


def _string(value: object, *, none: str = _UNKNOWN) -> str:
    if value is None:
        return none
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _escape(value: object, *, none: str = _UNKNOWN) -> str:
    return html.escape(_string(value, none=none), quote=True)


def _state_label(state: object) -> str:
    raw = _string(state)
    return _STATE_LABELS.get(raw, raw)


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [value]
    return [value]


def _template(board_code: object) -> dict:
    code = _string(board_code, none="")
    if not code or not re.fullmatch(r"[A-Za-z0-9_]+", code):
        return {"name": code or _UNKNOWN, "night_slots": [], "day_slots": []}
    path = ROOT / "config" / "board_templates" / f"{code}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"name": code, "night_slots": [], "day_slots": []}
    return value if isinstance(value, dict) else {"name": code, "night_slots": [], "day_slots": []}


def _relative_url(root_relative_path: object, from_dir: Path) -> str | None:
    """Make a browser-safe relative URL from a path rooted at ROOT."""
    if not isinstance(root_relative_path, str) or not root_relative_path.strip():
        return None
    try:
        raw = Path(root_relative_path)
        if raw.is_absolute():
            return None
        resolved = (ROOT / raw).resolve()
        resolved.relative_to(ROOT.resolve())
        relative = os.path.relpath(resolved, Path(from_dir).resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    normalized = relative.replace("\\", "/")
    return "/".join(quote(part, safe="-._~") for part in normalized.split("/"))


def _video_url(bvid: object, start_ms: object = None) -> str | None:
    if not isinstance(bvid, str) or not bvid.strip():
        return None
    url = f"https://www.bilibili.com/video/{quote(bvid.strip(), safe='')}/"
    if isinstance(start_ms, (int, float)) and not isinstance(start_ms, bool) and start_ms >= 0:
        url += f"?t={int(start_ms // 1000)}"
    return url


def _timecode(milliseconds: object) -> str:
    if not isinstance(milliseconds, (int, float)) or isinstance(milliseconds, bool) or milliseconds < 0:
        return _UNKNOWN
    total_ms = int(milliseconds)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _seat_map(value: dict) -> dict[int, dict]:
    result = {}
    for seat in _as_list(value.get("seats")):
        if isinstance(seat, dict) and isinstance(seat.get("seat"), int) and not isinstance(seat.get("seat"), bool):
            result[seat["seat"]] = seat
    return result


def _seat_ref(seat_number: object, seats: dict[int, dict]) -> str:
    if not isinstance(seat_number, int) or isinstance(seat_number, bool):
        return _UNKNOWN
    seat = seats.get(seat_number)
    if seat is None:
        return f"{seat_number}号（座位记录缺失，身份未知）"
    role = _string(seat.get("role"), none="身份未知")
    name = _string(seat.get("name"), none="姓名未知")
    return f"{seat_number}号（{role}，{name}）"


def _expected_actor(actor_role: object) -> str:
    if actor_role is None:
        return _UNKNOWN
    return f"未知（槽位行动方：{_string(actor_role)}）"


def _event_description(event: dict, slot: dict, seats: dict[int, dict]) -> str:
    label = _string(slot.get("label", event.get("slot")))
    raw_action = _string(event.get("action"))
    action = _ACTION_LABELS.get(raw_action, raw_action)
    actor = event.get("actor")
    actor_text = _seat_ref(actor, seats) if actor is not None else (slot.get("actor_role") or "")
    targets = [t for t in _as_list(event.get("targets")) if t is not None]
    if targets:
        target_text = "、".join(_seat_ref(target, seats) for target in targets)
    elif raw_action in {"pass", "unavailable", "none", "not_held", "peaceful"}:
        target_text = "无"
    else:
        target_text = _UNKNOWN
    if raw_action == "unknown":
        return f"{label}：转写没有说明，留待补充"
    if raw_action in {"pass", "unavailable", "none", "not_held", "peaceful"}:
        return f"{label}：{action}"
    if event.get("slot") == "sheriff_result" and raw_action == "elected":
        return f"{target_text}当选警长"
    if event.get("slot") == "night_deaths" and raw_action == "die":
        return f"夜间出局：{target_text}"
    if event.get("slot") == "exile_result" and raw_action == "exile":
        return f"{target_text}被放逐"
    result_text = f"；结果：{event['result']}" if event.get("result") is not None else ""
    target_clause = target_text if targets else ""
    return f"{label}：{actor_text}{action}{target_clause}{result_text}"


def _ordered_events(round_value: dict, phase: str, slots: list[dict]):
    events = [event for event in _as_list(round_value.get(phase)) if isinstance(event, dict)]
    by_code: dict[str, list[dict]] = {}
    for event in events:
        by_code.setdefault(_string(event.get("slot")), []).append(event)
    slot_codes = set()
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        code = _string(slot.get("code"))
        slot_codes.add(code)
        matching = by_code.pop(code, [])
        if matching:
            for event in matching:
                yield slot, event, False
        else:
            yield slot, None, False
    for code, unmatched in by_code.items():
        for event in unmatched:
            yield {"code": code, "label": code, "actor_role": None}, event, True


def _table(headers: list[str], rows: list[list[str]], *, class_name: str = "") -> str:
    css = f' class="{html.escape(class_name, quote=True)}"' if class_name else ""
    head = "".join(f"<th scope=\"col\">{_escape(item)}</th>" for item in headers)
    body_rows = []
    for row in rows:
        body_rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    if not body_rows:
        body_rows.append(f'<tr><td colspan="{len(headers)}" class="empty">暂无记录</td></tr>')
    return f"<div class=\"table-wrap\"><table{css}><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"


def _md_cell(value: object) -> str:
    text = html.escape(_string(value)).replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>])", r"\\\1", text)


def _issues(review: dict) -> list[str]:
    return [_string(item) for item in _as_list(review.get("issues")) if item is not None and str(item).strip()]


def _unmapped(review: dict) -> list[str]:
    return [_string(item) for item in _as_list(review.get("unmapped_events")) if item is not None]


def _segment_bounds(segment: dict) -> tuple[object, object]:
    start = segment.get("start_ms")
    end = segment.get("end_ms")
    if isinstance(start, bool) or not isinstance(start, (int, float)) or start < 0:
        start = None
    if isinstance(end, bool) or not isinstance(end, (int, float)) or end < 0:
        end = None
    return start, end


def render_game(out_dir: Path, value: dict, review: dict) -> None:
    """Render the four review artifacts for one dossier without touching its JSON files."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    value = value if isinstance(value, dict) else {}
    review = review if isinstance(review, dict) else {}
    board = _template(value.get("board"))
    seats = _seat_map(value)
    seat_rows = []
    seat_csv_rows = []
    for seat_number in sorted(seats):
        seat = seats[seat_number]
        name = _string(seat.get("name"), none="姓名未知")
        role = _string(seat.get("role"), none="身份未知")
        faction = {"good": "好人", "werewolf": "狼人", "third_party": "第三方"}.get(seat.get("faction"), _UNKNOWN)
        learning_target = seat.get("learning_target")
        learned_role = _string(seat.get("learned_role"))
        seat_rows.append([_escape(seat_number), _escape(name), _escape(role), _escape(faction),
                          _escape(learning_target), _escape(learned_role)])
        seat_csv_rows.append([seat_number, name, role, faction,
                              _string(learning_target), learned_role])

    title = _string(review.get("title") or value.get("title") or value.get("slug") or "S22 对局复核")
    bvid = _string(review.get("bvid") or value.get("bvid"), none="")
    board_name = _string(review.get("board_name") or board.get("name") or value.get("board"))
    state = _string(review.get("state"))
    state_label = _state_label(state)
    audio_url = _relative_url(review.get("audio_path"), out_dir)
    source_url = _relative_url(review.get("source_path"), out_dir)
    video_url = _video_url(bvid, review.get("recap_start_ms"))
    recap_status = {"localized_candidate": "已定位候选复盘，待回听", "localization_required": "待定位集中复盘"}.get(review.get("recap_status"), _string(review.get("recap_status")))
    recap_end_ms = review.get("recap_end_ms")
    if isinstance(recap_end_ms, bool) or not isinstance(recap_end_ms, (int, float)) or recap_end_ms < 0:
        recap_end_ms = None
    issues = _issues(review)
    unmapped = _unmapped(review)
    recap_segments = [item for item in _as_list(review.get("recap_segments")) if isinstance(item, dict)]

    role_section = (
        "<section><h2>座位身份</h2>"
        + _table(["座位", "姓名", "身份", "阵营", "学习目标", "学习形态"], seat_rows)
        + "</section>"
    )
    audio_html = "<p>未提供可播放的本地原音频。</p>"
    if audio_url:
        end_attr = f' data-recap-end-ms="{int(recap_end_ms)}"' if recap_end_ms is not None else ""
        audio_html = (
            f'<audio id="source-audio" controls preload="metadata" src="{html.escape(audio_url, quote=True)}"{end_attr}>'
            "浏览器不支持音频播放。</audio>"
            f'<span class="muted">复盘区间：{_escape(_timecode(review.get("recap_start_ms")))} – '
            f'{_escape(_timecode(review.get("recap_end_ms")))}。播放到复盘末尾会自动暂停。</span>'
        )
    if source_url:
        source_link = f'<a href="{html.escape(source_url, quote=True)}">打开复盘源文件</a>'
    else:
        source_link = "未提供复盘源文件路径"
    if video_url:
        video_link = f'<a href="{html.escape(video_url, quote=True)}" target="_blank" rel="noopener noreferrer">打开原视频并定位复盘起点</a>'
    else:
        video_link = "原视频标识未知"

    recap_rows = []
    recap_md = []
    for index, segment in enumerate(recap_segments, 1):
        start, end = _segment_bounds(segment)
        text = _string(segment.get("text"), none="复盘原文未知")
        start_text = _timecode(start)
        end_text = _timecode(end)
        if audio_url and start is not None:
            stop_at = end if end is not None else recap_end_ms
            stop_attr = f' data-end-ms="{int(stop_at)}"' if stop_at is not None else ""
            seek_control = (
                f'<button type="button" class="seek" data-start-ms="{int(start)}"{stop_attr}>'
                "定位并回听</button>"
            )
        else:
            seek_control = '<span class="muted">无可用音频定位</span>'
        recap_rows.append([
            _escape(index),
            _escape(f"{start_text} – {end_text}"),
            _escape(text),
            seek_control,
        ])
        recap_md.append(f"- **{_md_cell(start_text)} – {_md_cell(end_text)}**：{_md_cell(text)}")
    recap_section = (
        "<section><h2>复盘原文对照</h2>"
        f"<p>复盘状态：{_escape(recap_status)}</p><div class=\"audio-block\">{audio_html}</div><p>{video_link} · {source_link}</p>"
        '<p id="audio-status" class="muted" aria-live="polite">选择一段原文可跳转到音频时间点。</p>'
        + _table(["#", "时间", "复盘原文", "音频"], recap_rows)
        + "</section>"
    )

    round_sections = []
    md_rounds = []
    game_event_rows = []
    rounds = [item for item in _as_list(value.get("rounds")) if isinstance(item, dict)]
    for round_value in rounds:
        number = round_value.get("number", _UNKNOWN)
        round_title = f"第{_string(number)}轮"
        md_rounds.extend([f"## {round_title}", ""])
        phase_sections = []
        for phase, phase_name in (("night", "夜间"), ("day", "白天")):
            slot_list = [item for item in _as_list(board.get(f"{phase}_slots")) if isinstance(item, dict)]
            if not slot_list:
                seen = set()
                slot_list = []
                for event in _as_list(round_value.get(phase)):
                    if isinstance(event, dict):
                        code = _string(event.get("slot"))
                        if code not in seen:
                            seen.add(code)
                            slot_list.append({"code": code, "label": code, "actor_role": None})
            rows = []
            unknown_rows = []
            md_rounds.extend([f"### {phase_name}", "", "| 固定槽位 | 事件 |", "|---|---|"])
            for slot, event, is_unmapped in _ordered_events(round_value, phase, slot_list):
                slot_code = _string(slot.get("code"))
                label = _string(slot.get("label", slot_code))
                if event is None:
                    description = f"{label}：未记录（未知）"
                    unknown_rows.append([_escape(label), _escape(description)])
                    md_rounds.append(f"| {_md_cell(label)} | {_md_cell(description)} |")
                    continue
                description = _event_description(event, slot, seats)
                if is_unmapped:
                    description = f"未映射槽位；{description}"
                (unknown_rows if event.get("action") == "unknown" else rows).append([_escape(label), _escape(description)])
                md_rounds.append(f"| {_md_cell(label)} | {_md_cell(description)} |")
                actor = _seat_ref(event.get("actor"), seats) if event.get("actor") is not None else _expected_actor(slot.get("actor_role"))
                targets = "、".join(_seat_ref(t, seats) for t in _as_list(event.get("targets")) if t is not None)
                game_event_rows.append([
                    _string(number), phase_name, slot_code, label,
                    _string(event.get("action")), actor,
                    targets or ("无" if _string(event.get("action")) in {"pass", "unavailable", "none", "not_held", "peaceful"} else _UNKNOWN),
                    _string(event.get("result")), description,
                ])
            known_table = _table(['事项', '已知事实'], rows) if rows else '<p class="muted">这部分转写没有给出可确认事件。</p>'
            gaps = ('<details><summary>展开转写未提供的' + str(len(unknown_rows)) + '个槽位</summary>' + _table(['事项', '缺口'], unknown_rows) + '</details>') if unknown_rows else ''
            phase_sections.append(f"<section class=\"phase\"><h3>{_escape(phase_name)}</h3>{known_table}{gaps}</section>")
            md_rounds.append("")
        round_sections.append(f"<section><h2>{_escape(round_title)}</h2>{''.join(phase_sections)}</section>")

    if not round_sections:
        round_sections.append('<section><h2>固定槽位事件</h2><p class="muted">暂无已记录轮次；没有生成或推断任何轮次事件。</p></section>')
        md_rounds = ["## 固定槽位事件", "", "暂无已记录轮次；没有生成或推断任何轮次事件。", ""]

    issue_items = [f"<li>{_escape(item)}</li>" for item in issues]
    if not issue_items:
        issue_items = ['<li class="muted">暂无已登记问题。</li>']
    unmapped_items = [f"<li>{_escape(item)}</li>" for item in unmapped]
    if not unmapped_items:
        unmapped_items = ['<li class="muted">暂无未映射事件。</li>']
    issue_section = (
        "<section><h2>问题与未映射事件</h2><h3>问题清单</h3><ul>" + "".join(issue_items)
        + "</ul><h3>未映射事件</h3><ul>" + "".join(unmapped_items) + "</ul></section>"
    )

    receipt = review.get("db_receipt")
    receipt_text = "暂无数据库收据。" if receipt is None else json.dumps(receipt, ensure_ascii=False, indent=2, default=str)
    links_section = (
        '<section><h2>本局文件与状态</h2>'
        f'<p>状态：<strong>{_escape(state_label)}</strong></p>'
        + (f'<p>复核备注：{_escape(review["review_note"])}</p>' if review.get("review_note") else '')
        + '<p class="notice">入库状态只表示数据已写入数据库，不代表人工核实。</p>'
        '<p><a href="dossier.json">对局 JSON</a> · <a href="复核记录.json">复核记录 JSON</a></p>'
        '<h3>数据库收据</h3><pre>' + _escape(receipt_text) + '</pre></section>'
    )

    text_review = review.get("text_review", {})
    questions = text_review.get("questions", [])
    workbench = "http://127.0.0.1:8766/#" + quote(bvid, safe="")
    text_section = '<section><h2>文字补充与具体疑点</h2>'
    text_section += '<p>' + _escape(text_review.get("summary") or "本局尚未逐句核对，以下为已有提取结果。") + '</p>'
    for item in questions:
        answer = review.get("question_answers", {}).get(item["id"], {})
        answer_label = "AI已核实" if answer.get("resolved") and answer.get("reviewer") == "ai" else "已核对" if answer.get("resolved") else "待核实"
        text_section += '<details' + ("" if answer.get("resolved") else " open") + '><summary>' + _escape(answer_label) + " · " + _escape(item.get("label") or item.get("field")) + '：' + _escape(item.get("reason")) + '</summary>'
        if item.get("quote"):
            text_section += '<blockquote>' + _escape(item["quote"]) + '</blockquote>'
        if item.get("context_quote"):
            text_section += '<details><summary>同轮转写上下文</summary><blockquote>' + _escape(item["context_quote"]) + '</blockquote></details>'
        if "candidate" in item:
            candidate_text = json.dumps(item["candidate"], ensure_ascii=False) if isinstance(item["candidate"], (dict, list)) else str(item["candidate"])
            text_section += '<p>待核候选：' + _escape(candidate_text) + '</p>'
        location = item.get("start_ms") if item.get("start_ms") is not None else item.get("context_start_ms")
        if location is not None:
            text_section += '<p>转写时间：' + _escape(_timecode(location)) + '</p>'
        if answer.get("note"):
            text_section += "<p><strong>核查结论与依据</strong></p><pre>" + _escape(answer["note"]) + "</pre>"
        text_section += '</details>'
    text_section += '<p><a href="' + _escape(workbench) + '">进入本局审校：填写结论、修改座位或事件并保存入库</a></p></section>'

    frame_section = ''
    frame_review = review.get("frame_seats")
    if frame_review:
        source = frame_review.get("source", {})
        frame_path = source.get("frame_path") or frame_review.get("frame_path")
        frame_section = '<section><h2>画面座位姓名核对</h2>'
        if source.get("kind") == "same_day_frame":
            frame_section += '<p>按同日固定座位复用：' + _escape(source.get("source_date")) + '。每座保留实际来源截图，未跨比赛日推定。</p>'
        if frame_path:
            url = _relative_url(frame_path, out_dir)
            frame_section += '<p>截图来源：' + _escape(source.get("source_bvid")) + ' · ' + _escape(_timecode(source.get("frame_time_ms"))) + '</p>'
            frame_section += '<a href="' + _escape(url) + '"><img loading="lazy" style="width:100%;max-width:1100px" src="' + _escape(url) + '" alt="同日座位姓名牌来源截图"></a>'
        frame_section += '<div class="table-wrap"><table><tr><th>座位</th><th>画面ID</th><th>统一人名</th><th>来源</th></tr>'
        for seat in frame_review.get("seats", []):
            seat_source = seat.get("source") or {}
            seat_path = seat_source.get("frame_path")
            seat_link = ''
            if seat_path:
                label = str(seat_source.get("source_bvid") or '') + ' · ' + _timecode(seat_source.get("frame_time_ms"))
                seat_link = '<a href="' + _escape(_relative_url(seat_path, out_dir)) + '">' + _escape(label) + '</a>'
            frame_section += '<tr><td>' + _escape(seat.get("seat")) + '号</td><td>' + _escape(seat.get("visible_label")) + '</td><td>' + _escape(seat.get("name") or '待确认') + '</td><td>' + seat_link + '</td></tr>'
        frame_section += '</table></div>'
        for q in frame_review.get("questions", []):
            frame_section += '<p class="notice">' + _escape(q.get("label") or q.get("field")) + '：' + _escape(q.get("reason")) + '</p>'
        frame_section += '<p><a href="' + _escape(workbench) + '">进入本局保存更正与核对结论</a></p></section>'

    document = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{_escape(title)} · 批量复核</title><style>'
        '*{box-sizing:border-box}body{margin:0;background:#f2f5f7;color:#173342;font:16px/1.65 "Microsoft YaHei",sans-serif}'
        'main{max-width:1180px;margin:auto;padding:30px 22px 60px}h1{font-size:28px;margin:0 0 8px;line-height:1.45}h2{font-size:22px;margin:0 0 16px}h3{font-size:17px;margin:18px 0 8px}'
        'section{background:#fff;border:1px solid #dbe5ea;border-radius:12px;padding:22px;margin:20px 0}section.phase{margin:12px 0;padding:16px}'
        '.meta,.links{display:flex;gap:10px;flex-wrap:wrap}.pill{background:#e4eef3;border-radius:7px;padding:3px 10px}.notice{color:#9a4c00;background:#fff4df;padding:10px 12px;border-radius:7px}'
        'table{border-collapse:collapse;width:100%}th,td{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid #e4eaee;overflow-wrap:anywhere}th{background:#edf3f6;white-space:nowrap}.table-wrap{overflow:auto}.empty,.muted{color:#647985}.muted{font-size:14px}'
        'a{color:#176e9d}.seek{border:1px solid #78a9bf;background:#eff8fc;color:#145b7a;border-radius:6px;padding:5px 9px;cursor:pointer}audio{width:min(100%,720px)}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8f9;padding:12px;border-radius:7px;max-height:360px;overflow:auto}ul{padding-left:23px}'
        '@media(max-width:650px){main{padding:18px 10px}section{padding:14px}h1{font-size:23px}th,td{padding:8px 7px}}'
        '</style></head><body><main>'
        f'<h1>{_escape(title)}</h1><div class="meta"><span class="pill">{_escape(bvid or "BVID 未知")}</span>'
        f'<span class="pill">{_escape(board_name)}</span><span class="pill">{_escape(state_label)}</span></div>'
        '<p class="notice">机器整理或已入库均不代表人工核实；请依据原文和来源逐项复核。</p>'
        f'{text_section}{frame_section}{role_section}{"".join(round_sections)}{recap_section}{issue_section}{links_section}'
        '<script>\n'
        'const audio=document.getElementById("source-audio");\n'
        'const statusNode=document.getElementById("audio-status");\n'
        'const recapEnd=audio&&audio.dataset.recapEndMs?Number(audio.dataset.recapEndMs)/1000:null;\n'
        'let stopAt=recapEnd;\n'
        'function showAudioStatus(value){if(statusNode)statusNode.textContent=value;}\n'
        'if(audio){audio.addEventListener("timeupdate",()=>{if(stopAt!==null&&audio.currentTime>=stopAt){audio.pause();audio.currentTime=stopAt;stopAt=recapEnd;showAudioStatus("已在当前复盘片段末尾暂停。");}});}\n'
        'document.querySelectorAll("button.seek").forEach(button=>button.addEventListener("click",()=>{if(!audio)return;const start=Number(button.dataset.startMs);const localEnd=button.dataset.endMs?Number(button.dataset.endMs)/1000:null;stopAt=localEnd===null?recapEnd:(recapEnd===null?localEnd:Math.min(localEnd,recapEnd));audio.currentTime=start/1000;showAudioStatus("正在回听 "+audio.currentTime.toFixed(3)+" 秒处。");audio.play().catch(()=>showAudioStatus("浏览器未能播放该音频，请使用播放器手动播放。"));}));\n'
        '</script></main></body></html>'
    )
    (out_dir / "复核.html").write_text(document, encoding="utf-8")

    md = [
        f"# {_md_cell(title)}", "",
        f"- BVID：{_md_cell(bvid)}",
        f"- 版型：{_md_cell(board_name)}",
        f"- 状态：{_md_cell(state_label)}",
        "- 入库状态只表示数据已写入数据库，不代表人工核实。",
        f"- 对局 JSON：`dossier.json`；复核记录：`复核记录.json`。", "",
        "## 座位身份", "",
        "| 座位 | 姓名 | 身份 | 阵营 | 学习目标 | 学习形态 |",
        "|---:|---|---|---|---|---|",
    ]
    md.extend("| " + " | ".join(_md_cell(item) for item in row) + " |" for row in seat_csv_rows)
    if not seat_csv_rows:
        md.append("| — | 暂无座位记录 | 未知 | 未知 | 未知 | 未知 |")
    md.extend(["", *md_rounds, "## 复盘原文对照", ""])
    if recap_md:
        md.extend(recap_md)
    else:
        md.append("暂无复盘原文片段。")
    md.extend(["", "## 问题清单", ""])
    if review.get("review_note"):
        md.extend(["复核备注：" + _md_cell(review["review_note"]), ""])
    md.extend(f"- {_md_cell(item)}" for item in issues) if issues else md.append("暂无已登记问题。")
    md.extend(["", "## 未映射事件", ""])
    md.extend(f"- {_md_cell(item)}" for item in unmapped) if unmapped else md.append("暂无未映射事件。")
    receipt_markdown = "暂无数据库收据。" if receipt is None else json.dumps(receipt, ensure_ascii=False, indent=2, default=str)
    longest_fence = max((len(match.group(0)) for match in re.finditer(r"`+", receipt_markdown)), default=0)
    fence = "`" * max(3, longest_fence + 1)
    md.extend(["", "## 数据库收据", "", fence + "json", receipt_markdown, fence, ""])
    (out_dir / "复核.md").write_text("\n".join(md), encoding="utf-8")

    with (out_dir / "座位身份.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["座位", "姓名", "身份", "阵营", "学习目标", "学习形态"])
        writer.writerows(seat_csv_rows)
    with (out_dir / "游戏事件.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["轮次", "阶段", "槽位代码", "固定槽位", "动作", "行动者", "目标", "结果", "事件描述"])
        writer.writerows(game_event_rows)


def _metric(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, (dict, list, tuple)):
        return _string(value)
    return str(value)


def _entry_issues(entry: dict) -> list[str]:
    return [_string(item) for item in _as_list(entry.get("issues")) if item is not None and str(item).strip()]


def export_questions(base_dir: Path, entries: list[dict]) -> dict:
    """A flat, source-linked queue; answers stay in each game's review record."""
    rows = []
    for entry in entries:
        file = ROOT / entry.get("output_dir", "") / "复核记录.json"
        if not file.is_file():
            continue
        review = json.loads(file.read_text(encoding="utf-8-sig"))
        answers = review.get("question_answers", {})
        for q in (review.get("text_review", {}).get("questions", []) + review.get("frame_seats", {}).get("questions", [])):
            answer = answers.get(q["id"], {})
            rows.append({"序号": entry["index"], "日期": entry["date"], "局次": entry.get("game_number"),
                         "版型": entry.get("board_name"), "BVID": entry["bvid"], "疑点ID": q["id"],
                         "待核字段": q.get("label", q["field"]), "疑点说明": q["reason"], "原句": q.get("quote", ""),
                         "同轮转写上下文": q.get("context_quote", ""),
                         "开始毫秒": q.get("start_ms") if q.get("start_ms") is not None else q.get("context_start_ms"),
                         "结束毫秒": q.get("end_ms") if q.get("end_ms") is not None else q.get("context_end_ms"),
                         "候选值": json.dumps(q.get("candidate"), ensure_ascii=False) if "candidate" in q else "",
                         "已核对": "是" if answer.get("resolved") else "否", "核对结论": answer.get("note", ""),
                         "复核入口": "http://127.0.0.1:8766/#" + entry["bvid"]})
    columns = ["序号", "日期", "局次", "版型", "BVID", "疑点ID", "待核字段", "疑点说明", "原句", "同轮转写上下文", "开始毫秒", "结束毫秒", "候选值", "已核对", "核对结论", "复核入口"]
    with (Path(base_dir) / "待复核疑点.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return {"questions": len(rows), "unresolved": sum(r["已核对"] == "否" for r in rows)}


def render_overview(base_dir: Path, entries: list[dict], summary: dict) -> None:
    """Render a searchable local batch overview and a progress CSV."""
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    entries = [entry for entry in _as_list(entries) if isinstance(entry, dict)]
    summary = summary if isinstance(summary, dict) else {}

    columns = [
        "index", "bvid", "date", "game_number", "board_name", "state", "output_dir",
        "known_roles", "named_seats", "rounds", "known_events", "total_events", "issues", "updated_at", "text_review_status", "text_question_count",
    ]
    with (base_dir / "批量进度.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for entry in entries:
            writer.writerow([
                _metric(entry.get("index")), _metric(entry.get("bvid")), _metric(entry.get("date")),
                _metric(entry.get("game_number")), _metric(entry.get("board_name")),
                _metric(entry.get("state")), _metric(entry.get("output_dir")),
                _metric(entry.get("known_roles")), _metric(entry.get("named_seats")),
                _metric(entry.get("rounds")), _metric(entry.get("known_events")),
                _metric(entry.get("total_events")), "；".join(_entry_issues(entry)),
                _metric(entry.get("updated_at")),
                _metric(entry.get("text_review_status")), _metric(entry.get("text_question_count")),
            ])

    states = sorted({_string(entry.get("state")) for entry in entries}, key=str.casefold)
    summary_labels = [
        ("total", "总场次"),
        ("imported", "本批已入库"),
        ("preserved", "已保留"),
        ("reviewed", "人工复核完成"),
        ("pending", "待处理"),
        ("failed", "失败"),
        ("needs_review", "待人工复核"),
    ]
    summary_cards = "".join(
        f'<div class="card"><span>{_escape(label)}</span><strong>{_escape(summary.get(key))}</strong></div>'
        for key, label in summary_labels
    )
    last_processed = _string(summary.get("last_processed"), none="暂无")
    next_bvid = _string(summary.get("next_bvid"), none="暂无")
    next_review_bvid = _string(summary.get("next_review_bvid"), none="暂无")
    status_options = ''.join(
        f'<option value="{_escape(state)}">{_escape(_state_label(state))}</option>'
        for state in states
    )
    rows = []
    for entry in entries:
        issue_values = _entry_issues(entry)
        issue_text = "；".join(issue_values) if issue_values else "无已登记问题"
        raw_state = _string(entry.get("state"))
        output_dir = entry.get("output_dir")
        output_url = _relative_url(output_dir, base_dir)
        page_name = "复核.html"
        if output_url and raw_state == "preserved" and isinstance(output_dir, str):
            if (ROOT / output_dir / "单局示例.html").is_file():
                page_name = "单局示例.html"
        output_link = (
            f'<a href="{html.escape(output_url.rstrip("/") + "/" + page_name, quote=True)}">打开复核页</a>'
            if output_url else "无复核目录"
        )
        values = [
            _string(entry.get("index")), _string(entry.get("bvid")), _string(entry.get("date")),
            _string(entry.get("game_number")), _string(entry.get("board_name")),
            _state_label(entry.get("state")), _metric(entry.get("known_roles")),
            _metric(entry.get("named_seats")), _metric(entry.get("rounds")),
            _metric(entry.get("known_events")), _metric(entry.get("total_events")), issue_text,
            _string(entry.get("updated_at")),
        ]
        search_text = " ".join(values).casefold()
        cells = [
            _escape(entry.get("index")), _escape(entry.get("bvid")), _escape(entry.get("date")),
            _escape(entry.get("game_number")), _escape(entry.get("board_name")),
            _escape(_state_label(entry.get("state"))), _escape(_metric(entry.get("known_roles"))),
            _escape(_metric(entry.get("named_seats"))), _escape(_metric(entry.get("rounds"))),
            _escape(_metric(entry.get("known_events"))), _escape(_metric(entry.get("total_events"))),
            _escape(issue_text), _escape(entry.get("updated_at")), output_link,
            _escape("AI疑点核查完成" if entry.get("text_resolved_question_count") and entry.get("text_pending_question_count") == 0 else {"text_checked": "文字已核对", "questions": "有文字疑点", "no_recap": "未定位复盘"}.get(entry.get("text_review_status"), "尚未逐句核对")),
            _escape(entry.get("text_pending_question_count", entry.get("text_question_count", "—"))),
        ]
        rows.append(
            f'<tr data-state="{_escape(raw_state)}" data-state-label="{_escape(_state_label(raw_state))}" data-search="{_escape(search_text)}">'
            + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="16" class="empty">暂无批量处理记录；可从 next_bvid 继续。</td></tr>')
    state_stats = '<div id="state-stats" class="status-stats" aria-live="polite"></div>'

    document = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>S22 批量复核</title><style>'
        '*{box-sizing:border-box}body{margin:0;background:#f2f5f7;color:#173342;font:15px/1.6 "Microsoft YaHei",sans-serif}'
        'main{max-width:1480px;margin:auto;padding:28px 18px 55px}h1{font-size:28px;margin:0 0 8px}.muted{color:#647985}.notice{color:#9a4c00;background:#fff4df;padding:11px 14px;border-radius:8px}'
        '.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:20px 0}.card{background:#fff;border:1px solid #dbe5ea;border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:3px}.card span{color:#647985}.card strong{font-size:22px}'
        '.resume{display:flex;gap:20px;flex-wrap:wrap;background:#fff;border:1px solid #dbe5ea;border-radius:10px;padding:12px 15px}.controls{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}.controls input,.controls select{font:inherit;padding:9px 11px;border:1px solid #b9cbd4;border-radius:7px;background:#fff;min-width:220px}'
        '.status-stats{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 14px}.status-stats span{background:#e4eef3;padding:3px 9px;border-radius:6px}.table-wrap{overflow:auto;background:#fff;border:1px solid #dbe5ea;border-radius:10px}table{border-collapse:collapse;width:100%;min-width:1300px}th,td{text-align:left;vertical-align:top;padding:9px 10px;border-bottom:1px solid #e4eaee;overflow-wrap:anywhere}th{background:#edf3f6;position:sticky;top:0;white-space:nowrap}a{color:#176e9d}.empty{color:#647985;text-align:center;padding:24px}tr[hidden]{display:none}@media(max-width:600px){main{padding:18px 9px}h1{font-size:23px}}'
        '</style></head><body><main>'
        '<h1>S22 批量复核</h1>'
        '<p><a href="http://127.0.0.1:8766/">进入可编辑的审校工作台：逐局疑点、原文定位、保存更正</a></p>'
        '<p><a href="待复核疑点.csv">下载具体疑点清单（附原句、时间与逐局复核入口）</a></p>'
        f'<p><a href="../../extractions/S22/按日座位表/按日座位表.html">查看{len({entry.get("date") for entry in entries})}个比赛日的座位总表（点击姓名可对照截图）</a></p>'
        '<p class="notice">“已入库待复核”仅表示数据已写入数据库，不代表人工核实。机器抽取结果仍需人工逐局检查。</p>'
        f'<div class="cards">{summary_cards}</div>'
        f'<div class="resume"><span>最近处理：<strong>{_escape(last_processed)}</strong></span>'
        f'<span>建议续跑 BVID：<strong>{_escape(next_bvid)}</strong></span>'
        f'<span>下一条待复核：<strong>{_escape(next_review_bvid)}</strong></span>'
        '<a href="批量进度.csv">下载批量进度 CSV</a></div>'
        '<div class="controls"><input id="search" type="search" placeholder="搜索 BVID、版型、日期或问题" aria-label="搜索批量复核记录">'
        '<select id="state-filter" aria-label="按状态筛选"><option value="*">全部状态</option>' + status_options + '</select></div>'
        + state_stats
        + '<div class="table-wrap"><table><thead><tr>'
        + ''.join(f'<th scope="col">{_escape(label)}</th>' for label in ["序号", "BVID", "日期", "局次", "版型", "状态", "已知身份", "已命名座位", "轮次", "已知事件", "事件总数", "问题", "更新时间", "复核页", "文字核对", "疑点数"])
        + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
        '<script>\n'
        'const searchBox=document.getElementById("search");\n'
        'const stateFilter=document.getElementById("state-filter");\n'
        'const tableRows=[...document.querySelectorAll("tbody tr[data-state]")];\n'
        'const statsNode=document.getElementById("state-stats");\n'
        'function updateRows(){const query=searchBox.value.trim().toLocaleLowerCase();const selected=stateFilter.value;const counts=new Map();let shown=0;for(const row of tableRows){const matchesText=row.dataset.search.includes(query);const matchesState=selected==="*"||row.dataset.state===selected;row.hidden=!(matchesText&&matchesState);if(!row.hidden){shown++;const key=row.dataset.state;const item=counts.get(key)||{label:row.dataset.stateLabel,count:0};item.count++;counts.set(key,item);}}statsNode.replaceChildren();for(const [state,itemValue] of [...counts.entries()].sort((a,b)=>a[0].localeCompare(b[0]))){const item=document.createElement("span");item.textContent=itemValue.label+": "+itemValue.count;statsNode.appendChild(item);}const total=document.createElement("span");total.textContent="当前显示："+shown+" / "+tableRows.length;statsNode.appendChild(total);}\n'
        'searchBox.addEventListener("input",updateRows);stateFilter.addEventListener("change",updateRows);updateRows();\n'
        '</script></main></body></html>'
    )
    (base_dir / "批量复核.html").write_text(document, encoding="utf-8")

