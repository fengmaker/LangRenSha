"""Render a standalone, offline, incremental human review page for AI game records."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).resolve().parent / "templates" / "incremental_review.html"

try:
    from .game_time import phase_label
    from .board_config import load_template
except ImportError:  # Support direct script import with scripts/ on sys.path.
    from game_time import phase_label
    from board_config import load_template


_SLOT_LABELS = {
    "wolf_attack": "狼人袭击", "witch_save": "女巫救人", "witch_poison": "女巫用毒",
    "seer_check": "预言家查验", "guard": "守卫守护", "night_deaths": "夜间死亡情况",
    "sheriff_candidates": "警长候选人", "sheriff_vote": "警长竞选投票",
    "sheriff_result": "警长选举结果", "exile_vote": "放逐投票", "exile_result": "放逐结果",
    "hunter_shot": "猎人开枪", "badge": "警徽处理", "speech_order": "发言顺序",
    "self_destruct": "狼人自爆", "white_god_reveal": "白神技能", "mixed_blood_model": "混血儿选择榜样",
    "mixed_blood_alignment": "混血儿阵营", "mechanical_action": "机械狼行动",
    "mechanical_learning": "机械狼学习", "fox_mark": "九尾狐标记", "fox_hunt": "九尾狐猎杀",
    "baize_purge": "白泽清除", "baize_inherit": "白泽传承", "wolf_sorcerer_exchange": "狼术师交换",
    "magic_duel_wolf_sorcerer_swap": "狼术师交换", "magic_duel_magician_swap": "魔术师交换",
    "disqualification": "违规判离", "concession": "交牌认输", "werewolf_surrender": "狼人交牌",
}
_ACTION_LABELS = {
    "unknown": "未知", "attack": "袭击", "choose": "选择", "guard": "守护", "save": "救人",
    "poison": "用毒", "check": "查验", "die": "死亡", "shoot": "开枪", "exile": "放逐",
    "vote": "投票", "abstain": "弃票", "peaceful": "平安夜", "elected": "当选",
    "transfer": "移交", "destroy": "撕毁", "unavailable": "技能不可用", "no_action": "未行动",
    "learn": "学习", "kill": "击杀", "betray": "背叛", "pass": "放弃",
    "register": "上警登记", "continued": "继续竞选", "deferred": "延期",
    "not_held": "未举行", "none": "无", "forbidden": "禁止使用",
    "good": "好人阵营", "wolf": "狼人阵营", "can_shoot": "可以开枪", "cannot_shoot": "不能开枪",
    "carrying": "已接刀", "not_carrying": "未接刀", "wounded": "负伤", "not_wounded": "未负伤",
    "poisoned": "中毒", "not_triggered": "未触发", "die_after_speech": "发言后离场",
    "view": "查看", "verify": "验证", "give_mask": "赐面", "dance": "邀请进入舞池",
    "no_death": "无人离场", "minority_dies": "少数阵营离场", "no_skill": "无技能",
    "delay_death": "延迟死亡", "disqualify": "判离", "exchange": "交换",
}
_FIELD_LABELS = {
    "number": "轮次", "slot": "事项", "action": "动作", "actor": "执行位", "targets": "目标位",
    "result": "结果", "start_seat": "起始座位", "direction": "方向", "votes": "关联投票",
    "random_point": "随机点", "speech_scope": "发言范围", "availability": "技能状态", "effects": "效果",
    "day": "白天", "kind": "类型", "id": "记录编号", "stage": "阶段", "status": "状态",
    "candidates": "候选位", "eligible_voters": "可投票位", "tied_candidates": "平票候选位",
    "winner": "结果位", "unrecorded_voters": "未记录投票位", "on_police": "上警位",
    "off_police": "不上警位", "sheriff": "警长记录", "exile": "放逐记录", "interruptions": "中断记录",
    "registration": "警长报名", "sha256": "SHA-256", "source_path": "证据文件",
    "start_ms": "视频起始时间（毫秒）", "end_ms": "视频结束时间（毫秒）", "quote": "证据原文",
    "note": "证据说明", "source": "来源", "seat": "座位", "name": "姓名", "role": "物理身份",
    "faction": "阵营（候选）", "learning_target": "学习目标", "learned_role": "学习身份",
}
_VOTE_STATE_LABELS = {"cast": "已投票", "abstained": "弃票", "unknown": "未知"}
_FACTION_LABELS = {"good": "好人", "werewolf": "狼人", "third_party": "第三方"}
_BALLOT_KIND_LABELS = {"sheriff": "警长竞选", "exile": "放逐"}
_BALLOT_STAGE_LABELS = {"initial": "初始投票", "pk": "PK 投票", "revote": "复投"}
_STATUS_LABELS = {"complete": "已完成", "recorded": "已记录", "unknown": "未知",
                  "not_applicable": "不适用", "incomplete": "未完成", "pending": "待记录",
                  "none": "无", "not_held": "未举行", "deferred": "延期", "badge_lost": "警徽流失",
                  "interrupted_self_destruct": "自爆中断"}
_EVIDENCE_KIND_LABELS = {"video_frame": "画面截图", "subtitle": "字幕", "transcript": "转写文本",
                         "text": "文字材料", "audio": "音频", "image": "图片", "weibo": "微博原件"}
_DIRECTION_LABELS = {"clockwise": "顺时针", "counterclockwise": "逆时针", "anticlockwise": "逆时针"}


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _unknown(value: object) -> str:
    if value is None or value == "":
        return "未知"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _field_name(value: object) -> str:
    raw = str(value)
    return _FIELD_LABELS.get(raw, raw)


def _seat_label(value: object, seats: dict[int, dict]) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        return "未知"
    seat = seats.get(value)
    name = _unknown(seat.get("name") if seat else None)
    return f"{value}号位（{name}）"


def _seat_list(values: object, seats: dict[int, dict]) -> str:
    if values is None:
        return "未知"
    if not isinstance(values, list):
        return _unknown(values)
    return "、".join(_seat_label(value, seats) for value in values) if values else "未记录"


def _safe_link(source: object, *, root: Path, output_dir: Path) -> tuple[str, Path | None]:
    """Return a root-contained local relative URL or a validated HTTP(S) URL."""
    if not isinstance(source, str) or not source.strip():
        return "", None
    source = source.strip()
    parsed = urlsplit(source)
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        return source, None
    if parsed.scheme or parsed.netloc:
        return "", None
    candidate = Path(source)
    target = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return "", None
    if not target.is_file():
        return "", None
    relative = os.path.relpath(target, output_dir).replace("\\", "/")
    return quote(relative, safe="/.:_-"), target


def _video_url(bvid: object, page: object, start_ms: object = None) -> str:
    if not isinstance(bvid, str) or not bvid:
        return ""
    try:
        page_number = max(1, int(page))
    except (TypeError, ValueError):
        page_number = 1
    query = f"p={page_number}"
    if isinstance(start_ms, (int, float)) and not isinstance(start_ms, bool) and start_ms >= 0:
        query += f"&t={int(start_ms // 1000)}"
    return f"https://www.bilibili.com/video/{quote(bvid, safe='')}?{query}"


def _anchor(url: str, label: str) -> str:
    if not url:
        return ""
    return f'<a href="{_esc(url)}" rel="noopener noreferrer">{_esc(label)}</a>'


def _value_html(value: object, seats: dict[int, dict], *, key: str = "") -> str:
    if key in {"actor", "voter", "seat", "target", "winner", "start_seat"}:
        return _esc(_seat_label(value, seats))
    if key in {"targets", "candidates", "eligible_voters", "tied_candidates", "unrecorded_voters", "on_police", "off_police"}:
        return _esc(_seat_list(value, seats))
    if key == "state" and isinstance(value, str):
        return _esc(_VOTE_STATE_LABELS.get(value, _unknown(value)))
    if key in {"faction", "result"} and isinstance(value, str):
        return _esc(_FACTION_LABELS.get(value, _unknown(value)))
    if key == "kind" and isinstance(value, str):
        return _esc(_BALLOT_KIND_LABELS.get(value, _EVIDENCE_KIND_LABELS.get(value, _unknown(value))))
    if key == "stage" and isinstance(value, str):
        return _esc(_BALLOT_STAGE_LABELS.get(value, _unknown(value)))
    if key in {"status", "sheriff", "exile"} and isinstance(value, str):
        return _esc(_STATUS_LABELS.get(value, _unknown(value)))
    if key == "direction" and isinstance(value, str):
        return _esc(_DIRECTION_LABELS.get(value, _unknown(value)))
    if value == "unknown":
        return "未知（unknown）"
    return _esc(_unknown(value))


def _key_values(items: dict, seats: dict[int, dict], *, omit: set[str] | None = None) -> str:
    omit = omit or set()
    rows = []
    for key, value in items.items():
        if key in omit:
            continue
        rows.append(f"<div class=kv><dt>{_esc(_field_name(key))}</dt><dd>{_value_html(value, seats, key=str(key))}</dd></div>")
    return '<dl class=kv-list>' + "".join(rows) + "</dl>" if rows else '<p class=muted>没有其他记录。</p>'


def _technical_details(items: dict, seats: dict[int, dict], summary: str = "补充记录") -> str:
    values = {key: value for key, value in items.items() if _has_data(value)}
    if not values:
        return '<span class=muted>无</span>'
    return f'<details class=other><summary>{_esc(summary)}</summary>{_key_values(values, seats)}</details>'


def _render_seats(dossier: dict) -> str:
    seats = dossier.get("seats")
    if not isinstance(seats, list) or not seats:
        return '<p class=muted>未知：AI 候选未提供座位与身份。</p>'
    rows = []
    for player in seats:
        if not isinstance(player, dict):
            rows.append(f"<tr><td colspan=4>{_esc(_unknown(player))}</td></tr>")
            continue
        rows.append("<tr>" + "".join((
            f"<td>{_value_html(player.get('seat'), {})}</td>",
            f"<td>{_esc(_unknown(player.get('name')))}</td>",
            f"<td>{_esc(_unknown(player.get('role')))}</td>",
            f"<td>{_value_html(player.get('faction'), {}, key='faction')}</td>",
        )) + "</tr>")
    return '<div class=table-wrap><table><thead><tr><th>座位</th><th>姓名</th><th>物理身份</th><th>AI 阵营记录</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"


def _round_label(number: object, phase: str) -> str:
    if not isinstance(number, int) or isinstance(number, bool):
        return f"第{_unknown(number)}轮" + ("夜晚" if phase == "night" else "白天")
    return phase_label(number, phase)


def _has_data(value: object) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, dict)):
        return any(_has_data(item) for item in value.values()) if isinstance(value, dict) else any(_has_data(item) for item in value)
    return True


def _render_event(event: object, seats: dict[int, dict], slot_labels: dict[str, str]) -> str:
    if not isinstance(event, dict):
        return f"<tr><td colspan=5>{_esc(_unknown(event))}</td></tr>"
    slot = event.get("slot")
    action = event.get("action")
    slot_label = slot_labels.get(str(slot), "其他事项")
    action_label = _ACTION_LABELS.get(str(action), "未知" if action == "unknown" else "其他动作")
    extras = {key: value for key, value in event.items()
              if key not in {"slot", "action", "actor", "targets", "result"} and _has_data(value)}
    if str(slot) not in slot_labels:
        extras["slot"] = slot
    if action is not None and str(action) not in _ACTION_LABELS:
        extras["action"] = action
    extra_markup = _technical_details(extras, seats, "技能与其他记录")
    return ("<tr>"
            f"<td><strong>{_esc(slot_label)}</strong><div class=muted>{_esc(action_label)}</div></td>"
            f"<td>{_value_html(event.get('actor'), seats, key='actor')}</td>"
            f"<td>{_value_html(event.get('targets'), seats, key='targets')}</td>"
            f"<td>{_value_html(event.get('result'), seats, key='result')}</td>"
            f"<td>{extra_markup}</td></tr>")


def _render_rounds(dossier: dict, root: Path) -> str:
    rounds = dossier.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        return '<p class=muted>未知：AI 候选未提供轮次。</p>'
    seats = {seat["seat"]: seat for seat in dossier.get("seats", [])
             if isinstance(seat, dict) and isinstance(seat.get("seat"), int)}
    slot_labels = dict(_SLOT_LABELS)
    board = dossier.get("board")
    if isinstance(board, str) and board:
        try:
            template = load_template(board, root)
            for phase in ("night", "day"):
                for definition in template.get(phase + "_slots", []):
                    if isinstance(definition.get("code"), str) and definition.get("label"):
                        slot_labels[definition["code"]] = str(definition["label"])
        except (FileNotFoundError, KeyError, ValueError):
            pass
    sections = []
    for round_ in rounds:
        if not isinstance(round_, dict):
            sections.append(f'<section class=round><h4>{_esc(_unknown(round_))}</h4></section>')
            continue
        number = round_.get("number")
        phases = []
        for phase in ("night", "day"):
            events = round_.get(phase)
            label = _round_label(number, phase)
            if not isinstance(events, list) or not events:
                phases.append(f'<section class=phase><h5>{_esc(label)}</h5><p class=muted>AI 候选未提供事件记录。</p></section>')
                continue
            phases.append(f'<section class=phase><h5>{_esc(label)}</h5><div class=table-wrap><table class=events>'
                          '<thead><tr><th>行动</th><th>执行位</th><th>目标</th><th>结果</th><th>附加记录</th></tr></thead>'
                          '<tbody>' + "".join(_render_event(event, seats, slot_labels) for event in events) + '</tbody></table></div></section>')
        round_extras = {key: value for key, value in round_.items() if key not in {"number", "night", "day"}}
        extra_markup = f'<details class=other><summary>轮次补充记录</summary>{_key_values(round_extras, seats)}</details>' if round_extras else ""
        sections.append(f'<section class=round><h4>第{_esc(_unknown(number))}轮</h4>{"".join(phases)}{extra_markup}</section>')
    return "".join(sections)


def _render_votes(voting: dict, seats: dict[int, dict]) -> str:
    parts = []
    ballots = voting.get("ballots")
    if isinstance(ballots, list):
        if ballots:
            for index, ballot in enumerate(ballots, 1):
                if not isinstance(ballot, dict):
                    parts.append(f'<article class=ballot><h5>投票 {index}</h5><p>{_esc(_unknown(ballot))}</p></article>')
                    continue
                vote_rows = []
                votes = ballot.get("votes")
                if isinstance(votes, list):
                    for vote in votes:
                        if isinstance(vote, dict):
                            vote_rows.append(f'<tr><td>{_value_html(vote.get("voter"), seats, key="voter")}</td>'
                                f'<td>{_value_html(vote.get("target"), seats, key="targets")}</td>'
                                f'<td>{_value_html(vote.get("state"), seats, key="state")}</td>'
                                f'<td>{_key_values({k:v for k,v in vote.items() if k not in {"voter","target","state"}}, seats)}</td></tr>')
                        else:
                            vote_rows.append(f'<tr><td colspan=4>{_esc(_unknown(vote))}</td></tr>')
                votes_markup = ('<div class=table-wrap><table><thead><tr><th>投票者</th><th>投向</th><th>状态</th><th>其他字段</th></tr></thead><tbody>'
                                + "".join(vote_rows) + '</tbody></table></div>') if isinstance(votes, list) else '<p class=muted>未知：此投票未提供逐票记录。</p>'
                ballot_kind = _BALLOT_KIND_LABELS.get(str(ballot.get("kind")), _unknown(ballot.get("kind")))
                extra_markup = _technical_details({k: v for k, v in ballot.items() if k != "votes"}, seats, "投票概况")
                heading = f'第{_esc(_unknown(ballot.get("day")))}天 · {index} · {_esc(ballot_kind)}'
                parts.append(f'<article class=ballot><h5>{heading}</h5>{extra_markup}{votes_markup}</article>')
        else:
            parts.append('<p class=muted>AI 候选未提供投票记录。</p>')
    else:
        parts.append('<p class=muted>未知：AI 候选未提供投票记录。</p>')

    for key, title in (("registrations", "警长报名记录"), ("days", "逐日投票状态"), ("interruptions", "中断记录")):
        rows = voting.get(key)
        if isinstance(rows, list):
            parts.append(f'<h5>{_esc(title)}</h5>')
            if not rows:
                parts.append('<p class=muted>AI 候选未提供记录。</p>')
            else:
                parts.append('<div class=table-wrap><table><tbody>')
                for row in rows:
                    if isinstance(row, dict):
                        parts.append(f'<tr><td>{_key_values(row, seats)}</td></tr>')
                    else:
                        parts.append(f'<tr><td>{_esc(_unknown(row))}</td></tr>')
                parts.append('</tbody></table></div>')
    known = {"schema_version", "game_slug", "registrations", "ballots", "interruptions", "days"}
    other = {key: value for key, value in voting.items() if key not in known}
    if other:
        parts.append('<h5>其他投票数据</h5>' + _key_values(other, seats))
    if "schema_version" in voting:
        parts.insert(0, f'<p class=muted>投票结构版本：{_esc(_unknown(voting["schema_version"]))}</p>')
    return "".join(parts)


def _render_evidence(evidence: object, *, game: dict, root: Path, output_dir: Path) -> str:
    if not isinstance(evidence, list) or not evidence:
        return '<p class=muted>AI 候选未提供证据条目。</p>'
    entry = game.get("entry", {})
    bvid, page = entry.get("bvid"), entry.get("page")
    cards = []
    for index, item in enumerate(evidence, 1):
        if not isinstance(item, dict):
            cards.append(f'<article class=evidence><strong>证据 {index}</strong><p>{_esc(_unknown(item))}</p></article>')
            continue
        start_ms = item.get("start_ms")
        kind_value = item.get("kind")
        kind = _EVIDENCE_KIND_LABELS.get(str(kind_value), _unknown(kind_value))
        path = item.get("source_path")
        source_url, local_path = _safe_link(path, root=root, output_dir=output_dir)
        if not source_url:
            source_url, external_path = _safe_link(item.get("url"), root=root, output_dir=output_dir)
            local_path = external_path
        video = _video_url(bvid, page, start_ms)
        refs = []
        if source_url:
            refs.append(_anchor(source_url, "打开本地来源" if local_path else "打开外部来源"))
        if video:
            refs.append(_anchor(video, "在视频中定位到该页码与时间" if isinstance(start_ms, (int, float)) else "打开本局视频页"))
        image_markup = ""
        if local_path and local_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            image_markup = f'<a href="{_esc(source_url)}"><img loading=lazy src="{_esc(source_url)}" alt="证据截图 {index}"></a>'
        fields = []
        for key, label in (("start_ms", "视频起点"), ("end_ms", "视频终点")):
            value = item.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                fields.append(f'<div class=kv><dt>{label}</dt><dd>{value / 1000:g} 秒</dd></div>')
            elif key in item:
                fields.append(f'<div class=kv><dt>{label}</dt><dd>{_esc(_unknown(value))}</dd></div>')
        extras = {key: value for key, value in item.items()
                  if key not in {"source_path", "url", "kind", "quote", "note", "start_ms", "end_ms"}}
        content = [f'<article class=evidence><h5>证据 {index} · {_esc(kind)}</h5>']
        if item.get("quote") is not None:
            content.append(f'<blockquote>{_esc(_unknown(item.get("quote")))}</blockquote>')
        if item.get("note") is not None:
            content.append(f'<p><strong>说明：</strong>{_esc(_unknown(item.get("note")))}</p>')
        if fields:
            content.append('<dl class=kv-list>' + "".join(fields) + '</dl>')
        if extras:
            content.append(_technical_details(extras, {}, "来源与证据编号"))
        if refs:
            content.append('<p class=links>' + '　'.join(refs) + '</p>')
        elif path or item.get("url"):
            content.append('<p class=muted>来源未链接：文件不存在、路径超出工作区或链接协议不安全。</p>')
        if image_markup:
            content.append(image_markup)
        content.append('</article>')
        cards.append("".join(content))
    return '<div class=evidence-list>' + "".join(cards) + '</div>'


def _game_html(game: dict, *, root: Path, output_dir: Path, review_id: str) -> str:
    entry = game.get("entry", {})
    candidate = game.get("candidate", {})
    if not isinstance(candidate, dict):
        candidate = {}
    dossier = candidate.get("dossier")
    if not isinstance(dossier, dict):
        dossier = {}
    voting = candidate.get("voting")
    if not isinstance(voting, dict):
        voting = {}
    seats = {seat["seat"]: seat for seat in dossier.get("seats", [])
             if isinstance(seat, dict) and isinstance(seat.get("seat"), int)}
    bvid = _unknown(entry.get("bvid"))
    cid = _unknown(entry.get("cid"))
    page = entry.get("page", 1)
    try:
        page_number = int(page)
    except (TypeError, ValueError):
        page_number = 1
    labels = entry.get("labels") if isinstance(entry.get("labels"), dict) else {}
    title = _unknown(entry.get("title"))
    date = _unknown(dossier.get("date") or labels.get("event_date_candidate"))
    game_number = _unknown(dossier.get("game_number") or labels.get("game_number_candidate"))
    video = _video_url(entry.get("bvid"), page_number)
    extra_evidence = game.get("evidence", candidate.get("evidence", []))
    issues = candidate.get("issues", [])
    issue_markup = ("<ul>" + "".join(f"<li>{_esc(_unknown(issue))}</li>" for issue in issues) + "</ul>"
                    if isinstance(issues, list) and issues else '<p class=muted>AI 候选未列出问题。</p>')
    meta = []
    board_name = dossier.get("board")
    if isinstance(board_name, str):
        try:
            from board_config import load_template
            board_name = load_template(board_name, root).get("name", board_name)
        except (OSError, ValueError):
            pass
    for label, value in (("版型", board_name), ("AI 记录胜方", dossier.get("winner")),
                         ("阶段", dossier.get("phase")), ("局内日期", dossier.get("date"))):
        if label == "版型" or value is not None:
            if label == "阶段":
                value = {"regular": "正赛", "finals_week": "决赛周"}.get(value, value)
            value_html = _value_html(value, {}, key="faction") if label == "AI 记录胜方" else _esc(_unknown(value))
            meta.append(f'<span><b>{_esc(label)}</b>：{value_html}</span>')
    return f'''<article class="game-card" id="game-{_esc(review_id)}" data-review-id="{_esc(review_id)}">
      <header class="game-head"><p class="eyebrow">{_esc(date)} · 第 {_esc(game_number)} 局 · 第 {page_number} 页</p>
        <h2>{_esc(title)}</h2><p class="ident">BVID {_esc(bvid)} · CID {_esc(cid)} · 复核 ID {_esc(review_id)}</p>
        <p class="links">{_anchor(video, "打开本局 Bilibili 视频（页码已指定）")}</p>
        <div class="meta">{"".join(meta)}</div></header>
      <section><h3>AI 候选座位与物理身份</h3>{_render_seats(dossier)}</section>
      <section><h3>夜晚与白天行动</h3>{_render_rounds(dossier, root)}</section>
      <section><h3>投票记录</h3>{_render_votes(voting, seats)}</section>
      <section><h3>证据</h3>{_render_evidence(extra_evidence, game=game, root=root, output_dir=output_dir)}</section>
      <section><h3>AI 候选问题</h3>{issue_markup}</section>
      <section class="review-controls"><h3>人工复核</h3>
        <label class="reviewed"><input type="checkbox" data-reviewed> 已复核此局</label>
        <label class="note-label" for="note-{_esc(review_id)}">本局备注（修正意见、口误或悍跳相关意见等均写在这里）</label>
        <textarea id="note-{_esc(review_id)}" data-note rows="4" placeholder="记录本局所有希望人工确认或修正的内容"></textarea>
        <p class="muted">勾选表示认可当前候选；即使备注为空，该局也视为已复核。未勾选的游戏不会进入后续流程。</p>
      </section>
    </article>'''


def render_review_page(games: list[dict], output: Path, *, season: str = "S23", root: Path = ROOT) -> dict:
    """Write an offline review page and return a small manifest for its caller."""
    output = Path(output)
    output_dir = output.resolve().parent
    root = Path(root).resolve()
    template = TEMPLATE.read_text(encoding="utf-8")
    cards = []
    manifest = []
    seen = set()
    for game in games:
        entry = game["entry"]
        bvid = str(entry["bvid"])
        cid = str(entry["cid"])
        page = int(entry["page"])
        if page < 1:
            raise ValueError(f"page must be positive: {entry['bvid']}:{entry['cid']}")
        review_id = f"{bvid}:{cid}:p{page:02d}"
        if review_id in seen:
            raise ValueError(f"duplicate game identity: {review_id}")
        seen.add(review_id)
        candidate_sha256 = game.get("candidate_sha256")
        source_sha256 = game.get("source_sha256", entry.get("source_sha256"))
        if not isinstance(candidate_sha256, str) or not candidate_sha256:
            raise ValueError(f"candidate_sha256 is required: {review_id}")
        if not isinstance(source_sha256, str) or not source_sha256:
            raise ValueError(f"source_sha256 is required: {review_id}")
        manifest.append({"review_id": review_id, "bvid": bvid, "cid": cid, "page": page,
                         "candidate_sha256": candidate_sha256, "source_sha256": source_sha256})
        cards.append(_game_html(game, root=root, output_dir=output_dir, review_id=review_id))
    data = json.dumps({"season": str(season), "games": manifest}, ensure_ascii=False,
                      separators=(",", ":")).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    page_html = (template.replace("__SEASON__", _esc(season))
                 .replace("__REVIEW_DATA__", data)
                 .replace("__GAME_CARDS__", "".join(cards)))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page_html, encoding="utf-8")
    return {"season": str(season), "format": "masters-incremental-review-v1",
            "games": len(manifest), "review_ids": [item["review_id"] for item in manifest],
            "output": output.as_posix()}
