"""Create a standalone, read-only HTML review page for transcript candidates."""

from __future__ import annotations

import argparse
import html
import json
import math
import os
from pathlib import Path
from urllib.parse import quote
from typing import Any


_STAGE_NAMES = {
    "opening": "开场候选",
    "night": "夜间候选",
    "sheriff_election": "警上/警长竞选候选",
    "daytime": "白天候选",
    "voting": "投票候选",
    "last_words": "遗言候选",
    "ended": "结束候选",
    "unknown": "未知阶段",
}
_SPEECH_NAMES = {
    "referee_recap_candidate": "法官最终复盘候选",
    "judge_instruction_candidate": "法官口令候选",
    "compound_instruction_candidate": "复合口令候选",
    "stage_change_candidate": "阶段切换候选",
    "game_end_candidate": "结束口令候选",
    "turn_end_candidate": "发言结束候选",
    "player_speech_candidate": "玩家发言候选",
    "unassigned_speech": "未归属发言",
}


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _seconds(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _segment_times_ms(segment: dict[str, Any]) -> tuple[int | None, int | None]:
    if "start_ms" in segment or "end_ms" in segment:
        try:
            start, end = int(segment["start_ms"]), int(segment["end_ms"])
        except (KeyError, TypeError, ValueError):
            return None, None
    else:
        start_value = segment.get("start", segment.get("from"))
        end_value = segment.get("end", segment.get("to"))
        start_seconds, end_seconds = _seconds(start_value), _seconds(end_value)
        if start_seconds is None or end_seconds is None:
            return None, None
        start, end = round(start_seconds * 1000), round(end_seconds * 1000)
    if start < 0 or end < start:
        return None, None
    return start, end


def _timestamp(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "时间未知"
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _duration_text(transcript: dict[str, Any]) -> str:
    duration_ms = transcript.get("audio_duration_ms")
    if duration_ms is None and transcript.get("audio_duration_seconds") is not None:
        seconds = _seconds(transcript.get("audio_duration_seconds"))
        duration_ms = round(seconds * 1000) if seconds is not None else None
    try:
        value = int(duration_ms)
    except (TypeError, ValueError):
        return "未知"
    if value < 0:
        return "未知"
    return _timestamp(value)


def _audio_source(transcript: dict[str, Any]) -> str:
    playback = transcript.get("playback_audio")
    if isinstance(playback, dict) and isinstance(playback.get("file"), str):
        return playback["file"]
    source = transcript.get("source")
    audio_file = source.get("audio_file") if isinstance(source, dict) else None
    audio_file = audio_file or transcript.get("audio_file")
    if not isinstance(audio_file, str) or not audio_file.strip():
        raise ValueError("transcript.source.audio_file is required")
    return audio_file


def resolve_audio_path(audio_file: str, transcript_path: Path) -> Path:
    """Resolve the local audio path using the run directory, project, and transcript."""
    supplied = Path(audio_file)
    if supplied.is_absolute():
        resolved = supplied.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"audio file not found: {resolved}")
        return resolved

    project_root = Path(__file__).resolve().parent.parent
    bases = (Path.cwd(), project_root, transcript_path.resolve().parent)
    tried: list[Path] = []
    for base in bases:
        candidate = (base / supplied).resolve()
        if candidate not in tried:
            tried.append(candidate)
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(path) for path in tried)
    raise FileNotFoundError(f"audio file from transcript.source.audio_file was not found; searched: {searched}")


def audio_relative_href(audio_file: str, transcript_path: Path, output_path: Path) -> str:
    audio_path = resolve_audio_path(audio_file, transcript_path)
    output_parent = output_path.resolve().parent
    try:
        relative = os.path.relpath(audio_path, output_parent).replace("\\", "/")
    except ValueError:
        # Different Windows drives have no relative path; keep the file local.
        return audio_path.as_uri()
    return quote(relative, safe="/:")


def _model_text(transcript: dict[str, Any]) -> str:
    model = transcript.get("model")
    engine = transcript.get("engine")
    config = transcript.get("config")
    if not model and isinstance(config, dict):
        models = config.get("models")
        if isinstance(models, dict):
            model = models.get("asr")
    parts = [str(value) for value in (engine, model) if value]
    return " / ".join(parts) if parts else "未提供"


def _player_label(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 12:
        return f"{value}号（候选）"
    return "未归属"


def _status_label(value: Any) -> str:
    if value == "unknown":
        return "未知 / 未归属"
    if value == "needs_review":
        return "待复核候选"
    if value:
        return f"{value}（候选）"
    return "候选"


def _json_for_display(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _time_link(segment: dict[str, Any], audio_origin_ms: int = 0) -> str:
    start_ms, _ = _segment_times_ms(segment)
    if start_ms is None:
        return '<span class="time unknown-time">时间未知</span>'
    seconds = f"{max(0, start_ms - audio_origin_ms) / 1000:.3f}"
    return (
        f'<a class="time" href="#audio" data-time="{seconds}" '
        f'aria-label="跳到 {_timestamp(start_ms)}">{_timestamp(start_ms)}</a>'
    )


def _raw_row(segment: dict[str, Any], audio_origin_ms: int = 0) -> str:
    start_ms, end_ms = _segment_times_ms(segment)
    speaker = segment.get("speaker")
    speaker_label = "匿名声纹候选：未标记" if speaker is None else f"匿名声纹候选：{speaker}"
    segment_id = segment.get("id", "未知 ID")
    status = segment.get("status", "machine_generated_unverified")
    return (
        '<article class="entry raw-entry">'
        f'<div class="entry-meta">{_time_link(segment, audio_origin_ms)}'
        f'<span>{_escape(speaker_label)}</span>'
        f'<span>片段 {_escape(segment_id)}</span>'
        f'<span>{_escape(_status_label(status))}</span></div>'
        f'<p class="transcript-text">{_escape(segment.get("text", ""))}</p>'
        f'<span class="end-time">结束 {_escape(_timestamp(end_ms))}</span>'
        '</article>'
    )


def _candidate_row(segment: dict[str, Any], audio_origin_ms: int = 0) -> str:
    start_ms, end_ms = _segment_times_ms(segment)
    stage = _STAGE_NAMES.get(segment.get("stage"), "未知阶段")
    speech_type = _SPEECH_NAMES.get(segment.get("speech_type"), segment.get("speech_type") or "候选发言")
    reasons = segment.get("review_reasons") or []
    evidence = segment.get("evidence") or []
    source_ids = segment.get("source_segment_ids") or []
    detail = _json_for_display(
        {
            "review_reasons": reasons,
            "source_segment_ids": source_ids,
            "evidence": evidence,
        }
    )
    speaker_candidate = segment.get("player_speaker_candidate")
    speaker_text = "声纹候选：未标记" if speaker_candidate is None else f"声纹候选：{speaker_candidate}"
    role_text = ("法官（复盘语境候选）" if segment.get("speech_type") == "referee_recap_candidate"
                 else _player_label(segment.get("player_number")))
    return (
        '<article class="entry candidate-entry">'
        f'<div class="entry-meta">{_time_link(segment, audio_origin_ms)}'
        f'<span class="seat">{_escape(role_text)}</span>'
        f'<span>{_escape(stage)}</span>'
        f'<span>{_escape(speech_type)}</span>'
        f'<span>{_escape(_status_label(segment.get("status")))}</span>'
        f'<span>{_escape(speaker_text)}</span></div>'
        f'<p class="transcript-text">{_escape(segment.get("text", ""))}</p>'
        f'<span class="end-time">结束 {_escape(_timestamp(end_ms))}</span>'
        f'<details><summary>来源与复核依据（{len(source_ids)} 个原始片段）</summary>'
        f'<pre>{_escape(detail)}</pre></details>'
        '</article>'
    )


def build_review_html(
    transcript: dict[str, Any],
    structure: dict[str, Any],
    transcript_path: Path,
    output_path: Path,
) -> str:
    """Render transcript and structure candidates as safe, static HTML."""
    raw_segments = transcript.get("segments")
    candidate_segments = structure.get("segments")
    if not isinstance(raw_segments, list) or not isinstance(candidate_segments, list):
        raise ValueError("both JSON inputs must contain a segments list")
    source_title = transcript.get("source", {})
    title = source_title.get("title") if isinstance(source_title, dict) else None
    title = title or "本地音频转写审阅"
    href = audio_relative_href(_audio_source(transcript), transcript_path, output_path)
    playback = transcript.get("playback_audio") or {}
    audio_origin_ms = int(playback.get("origin_ms", 0))
    if audio_origin_ms < 0:
        raise ValueError("playback audio origin must be non-negative")
    audio_attrs = f'src="{_escape(href)}"'
    transcript_status = transcript.get("status") or "candidate_unverified"
    structure_status = structure.get("status") or "candidate_unverified"
    note = (
        "以下内容都是机器转写或结构候选，尚未人工校对。声纹聚类标签不是座位号；"
        "报告不确认真实身份、游戏胜负或其他比赛事实。"
    )
    if playback:
        note += (f" 当前播放的是从原音频 {_timestamp(audio_origin_ms)} 起截取的复盘片段，"
                 "列表显示原音频时间，点击会跳到片段内对应位置。")
    raw_html = "\n".join(_raw_row(segment, audio_origin_ms) for segment in raw_segments if isinstance(segment, dict))
    candidate_html = "\n".join(
        _candidate_row(segment, audio_origin_ms) for segment in candidate_segments if isinstance(segment, dict)
    )
    if not raw_html:
        raw_html = '<p class="empty">没有转写片段。</p>'
    if not candidate_html:
        candidate_html = '<p class="empty">没有合并结构候选。</p>'

    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)} · 转写审阅</title>
<style>
:root {{ color-scheme: light; --ink:#18232d; --muted:#65737e; --line:#dce3e8; --panel:#fff; --wash:#f3f6f8; --accent:#146b78; --warn:#8a4e14; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--wash); color:var(--ink); font:16px/1.55 system-ui,"Microsoft YaHei",sans-serif; }}
main {{ max-width:1120px; margin:0 auto; padding:24px 18px 60px; }}
h1 {{ margin:0; font-size:1.65rem; line-height:1.3; overflow-wrap:anywhere; }}
.topline {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:18px; }}
.badge {{ flex:none; border:1px solid #e6c99f; border-radius:999px; padding:4px 10px; color:var(--warn); background:#fff8ec; font-size:.88rem; }}
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; margin:14px 0; box-shadow:0 2px 8px #1020300a; }}
.note {{ margin:0; color:#714314; background:#fff8ec; border-left:4px solid #d69a43; padding:11px 13px; border-radius:5px; }}
.facts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px 18px; margin:0 0 13px; }}
.facts div {{ min-width:0; }} .facts dt {{ color:var(--muted); font-size:.82rem; }} .facts dd {{ margin:2px 0 0; overflow-wrap:anywhere; }}
audio {{ display:block; width:100%; margin-top:10px; }}
.toolbar {{ display:flex; flex-wrap:wrap; align-items:center; gap:8px; }}
button,input {{ font:inherit; }}
button {{ border:1px solid #b9c7ce; background:#fff; color:var(--ink); border-radius:8px; padding:8px 12px; cursor:pointer; }}
button[aria-pressed="true"] {{ color:#fff; background:var(--accent); border-color:var(--accent); }}
button:hover {{ border-color:var(--accent); }}
input {{ flex:1 1 220px; min-width:170px; border:1px solid #b9c7ce; background:#fff; border-radius:8px; padding:8px 10px; }}
#visible-count {{ color:var(--muted); font-size:.9rem; margin-left:auto; }}
.entry {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:13px 15px; margin:10px 0; }}
.entry-meta {{ display:flex; flex-wrap:wrap; gap:7px 13px; align-items:center; color:var(--muted); font-size:.88rem; }}
.time {{ color:var(--accent); font-variant-numeric:tabular-nums; font-weight:700; text-decoration:none; }}
.time:hover {{ text-decoration:underline; }} .unknown-time {{ color:var(--muted); }}
.seat {{ color:#154e66; font-weight:700; }}
.transcript-text {{ white-space:pre-wrap; overflow-wrap:anywhere; margin:9px 0 5px; font-size:1.03rem; }}
.end-time {{ color:#8a969e; font-size:.78rem; }}
details {{ margin-top:8px; }} summary {{ color:var(--muted); cursor:pointer; font-size:.88rem; }}
pre {{ overflow:auto; padding:10px; background:#f4f6f7; border-radius:6px; white-space:pre-wrap; overflow-wrap:anywhere; font-size:.82rem; }}
.empty {{ color:var(--muted); text-align:center; padding:30px; }}
@media(max-width:620px) {{ main {{ padding:14px 10px 36px; }} .topline {{ display:block; }} .badge {{ display:inline-block; margin-top:10px; }} }}
</style>
</head>
<body>
<main>
  <header class="topline"><h1>{_escape(title)}</h1><span class="badge">候选 · 未人工校对</span></header>
  <section class="panel" aria-label="来源与状态">
    <dl class="facts">
      <div><dt>音频时长</dt><dd>{_escape(_duration_text(transcript))}</dd></div>
      <div><dt>转写模型</dt><dd>{_escape(_model_text(transcript))}</dd></div>
      <div><dt>句级片段</dt><dd>{len(raw_segments)}</dd></div>
      <div><dt>合并发言候选</dt><dd>{len(candidate_segments)}</dd></div>
      <div><dt>转写状态</dt><dd>{_escape(_status_label(transcript_status))}</dd></div>
      <div><dt>结构候选状态</dt><dd>{_escape(_status_label(structure_status))}</dd></div>
    </dl>
    <p class="note">{_escape(note)}</p>
    <audio id="audio" controls preload="metadata" {audio_attrs}>浏览器无法播放此本地音频。</audio>
  </section>

  <section class="panel toolbar" aria-label="审阅工具">
    <button type="button" class="view-button" data-view="raw" aria-pressed="true">句级原始转写</button>
    <button type="button" class="view-button" data-view="candidate" aria-pressed="false">合并发言候选</button>
    <input id="search" type="search" placeholder="检索当前视图中的文字" aria-label="关键词检索">
    <button type="button" id="copy-text">复制当前列表文本</button>
    <span id="visible-count" aria-live="polite"></span>
  </section>

  <section id="raw-view" class="entries" aria-label="句级原始转写">{raw_html}</section>
  <section id="candidate-view" class="entries" aria-label="合并发言候选" hidden>{candidate_html}</section>
</main>
<script>
(() => {{
  const audio = document.getElementById('audio');
  const search = document.getElementById('search');
  const count = document.getElementById('visible-count');
  const buttons = [...document.querySelectorAll('.view-button')];
  let currentView = 'raw';
  function refresh() {{
    const section = document.getElementById(currentView + '-view');
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    const entries = [...section.querySelectorAll('.entry')];
    for (const entry of entries) {{
      const matches = !query || entry.textContent.toLocaleLowerCase().includes(query);
      entry.hidden = !matches;
      if (matches) visible += 1;
    }}
    count.textContent = `显示 ${{visible}} / ${{entries.length}} 条`;
  }}
  buttons.forEach(button => button.addEventListener('click', () => {{
    currentView = button.dataset.view;
    document.getElementById('raw-view').hidden = currentView !== 'raw';
    document.getElementById('candidate-view').hidden = currentView !== 'candidate';
    buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    refresh();
  }}));
  search.addEventListener('input', refresh);
  document.addEventListener('click', event => {{
    const link = event.target.closest('a[data-time]');
    if (!link || !audio) return;
    event.preventDefault();
    audio.currentTime = Number(link.dataset.time);
    audio.play().catch(() => {{}});
  }});
  document.getElementById('copy-text').addEventListener('click', async () => {{
    const section = document.getElementById(currentView + '-view');
    const text = [...section.querySelectorAll('.entry:not([hidden])')]
      .map(entry => entry.innerText.trim()).join('\\n\\n');
    try {{
      await navigator.clipboard.writeText(text);
      count.textContent = '已复制当前列表';
    }} catch (_) {{
      const field = document.createElement('textarea');
      field.value = text;
      field.style.position = 'fixed';
      field.style.opacity = '0';
      document.body.appendChild(field);
      field.select();
      document.execCommand('copy');
      field.remove();
      count.textContent = '已复制当前列表';
    }}
  }});
  refresh();
}})();
</script>
</body>
</html>
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", type=Path, required=True, help="ASR transcript JSON")
    parser.add_argument("--structure", type=Path, required=True, help="structure candidate JSON")
    parser.add_argument("--out", type=Path, required=True, help="standalone review HTML output")
    args = parser.parse_args()
    transcript = json.loads(args.transcript.read_text(encoding="utf-8"))
    structure = json.loads(args.structure.read_text(encoding="utf-8"))
    page = build_review_html(transcript, structure, args.transcript, args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(f"已生成只读审阅页：{args.out}")


if __name__ == "__main__":
    main()
