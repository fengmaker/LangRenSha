"""Human-readable source labels and subtitle exports, never verified game facts."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from collect_bilibili_audio import is_chinese_subtitle, validate_cues

ROOT = Path(__file__).resolve().parents[1]
NUMBERS = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10,
           "十一":11,"十二":12,"十三":13,"十四":14,"十五":15,"十六":16,"十七":17,"十八":18,"十九":19,"二十":20}


def number(value: str) -> int:
    return int(value) if value.isdigit() else NUMBERS[value]


def safe_name(value: str, limit: int = 65) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]',"_",value)
    text = re.sub(r"\s+","_",text).strip(" ._")
    return text[:limit].rstrip(" .") or "待核"


def naming(title: str, bvid: str, cid: int, page: int, anchor: str, season: str = "S22") -> dict:
    match = re.search(r"(?<!\d)(20\d{6})(?!\d)",title)
    event_date = None
    if match:
        try:
            event_date = datetime.strptime(match[1],"%Y%m%d").date()
        except ValueError:
            pass
    first_day = date.fromisoformat(anchor)
    date_conflict = event_date is not None and event_date.year != first_day.year
    phase = "showmatch" if "表演赛" in title else "finals_week" if "决赛" in title else "regular" if "正赛" in title else "special" if "特辑" in title else "unknown"
    issue_match = re.search(r"第([一二三四五六七八九十]+|\d+)期",title)
    issue = number(issue_match[1]) if issue_match else None
    game_match = re.search(r"第([一二三四五六七八九十]+|\d+)局",title)
    game = number(game_match[1]) if game_match else None
    warnings = []
    week = None
    week_method = "unknown"
    if phase == "showmatch":
        week,week_method = 1,"opening_showmatch_week"
    elif phase == "regular" and issue is not None:
        week,week_method = issue+1,"title_issue_plus_opening_showmatch_week"
    elif event_date and not date_conflict and event_date >= first_day:
        week,week_method = (event_date-first_day).days//7+1,"calendar_7_day_blocks_from_first_showmatch"
    if date_conflict:
        warnings.append("标题年份与该季开场日期不一致；保留原题日期，未纠正比赛年份")
    if game is None:
        warnings.append("原题未明确局次，不按相邻视频猜测")
    if phase in {"special","unknown"}:
        warnings.append("合集附带内容或赛事性质待核，不自动纳入正式对局")
    # Day is retained for provenance, but not used in filenames: some original
    # titles have repeated/mistaken Day labels.
    day_match = re.search(r"Day[-\s]*(\d+)",title,re.I)
    if phase == "regular" and issue and event_date and not date_conflict and day_match:
        day_from_date = (event_date-first_day).days % 7+1
        if day_from_date <= 4 and int(day_match[1]) != day_from_date:
            warnings.append("原题 Day 与开场日七天归档位置不同；文件名不采用 Day")
    phase_label = {"showmatch":"表演赛","finals_week":"决赛周","regular":f"正赛第{issue:02d}期" if issue else "正赛期次待核","special":"特辑待核","unknown":"赛事性质待核"}[phase]
    week_label = f"第{week:02d}周" if week else "周次待核"
    date_label = event_date.isoformat() if event_date else "日期待核"
    if date_conflict:
        date_label += "原题日期存疑"
    game_label = f"第{game:02d}局" if game else "局次待核"
    if game_match:
        board = title[game_match.end():].strip(" -—_：:") or "配置待核"
    else:
        tail = re.split(r"Day[-\s]*\d+",title,flags=re.I)
        board = tail[-1].strip(" -—_：:") if len(tail)>1 else "配置待核"
    stem = f"{date_label}_{season}_{week_label}_{phase_label}_{game_label}_{safe_name(board,35)}__{bvid}_P{page:02d}_CID{cid}"
    return {"season":season,"original_title":title,"event_date_candidate":event_date.isoformat() if event_date else None,
            "date_conflict":date_conflict,"phase_candidate":phase,"phase_label":phase_label,
            "issue_candidate":issue,"week_number":week,"week_method":week_method,"week_verified":False,
            "week_definition":"从表演赛开场起累计的归档周；正赛期次另列，不冒充官方周编号",
            "game_number_candidate":game,"board_candidate":board,"original_day_label":int(day_match[1]) if day_match else None,
            "warnings":warnings,"stem":stem,"group":f"{week_label}_{phase_label}","date_folder":date_label,
            "game_facts_verified":False}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def preserve_copy(source: Path, target: Path, hardlink: bool = False) -> None:
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if os.path.samefile(source,target) or digest(source) == digest(target):
            return
        raise ValueError("整理目录已有不同内容的同名文件，停止覆盖")
    if hardlink:
        os.link(source,target)
    else:
        shutil.copyfile(source,target)


def timestamp(value: float, srt: bool = False) -> str:
    total = round(value*1000)
    hours,total = divmod(total,3600000)
    minutes,total = divmod(total,60000)
    seconds,millis = divmod(total,1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{',' if srt else '.'}{millis:03d}"


def export_source(manifest_path: Path, labels: dict) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = ROOT / "data/seasons" / labels["season"] / labels["group"] / labels["date_folder"]
    base.mkdir(parents=True,exist_ok=True)
    stem = labels["stem"]
    audio_source = manifest_path.parent / manifest["audio"]["file"]
    audio_target = base / (stem+".音频.m4a")
    preserve_copy(audio_source,audio_target,hardlink=True)
    result = {"audio":audio_target.relative_to(ROOT).as_posix(),"audio_storage":"hardlink_same_bytes_no_second_media_copy",
              "subtitles":[],"source_manifest":manifest_path.relative_to(ROOT).as_posix()}
    for index,track in enumerate((manifest.get("subtitles") or {}).get("tracks") or [],start=1):
        if not is_chinese_subtitle(track.get('language')):
            continue
        source = manifest_path.parent/track["file"]
        document = json.loads(source.read_text(encoding="utf-8"))
        cues = validate_cues(document)
        kind = "平台AI字幕" if document.get("type") == "AIsubtitle" or str(track.get("language","")).startswith("ai-") else "平台字幕"
        subtitle_stem = stem+f".{kind}_{safe_name(track.get('language') or '语言待核',15)}_{index:02d}"
        raw_target = base/(subtitle_stem+".原始.json")
        if raw_target.exists() and digest(raw_target) != digest(source):
            # Preserve an earlier short/stale subtitle version instead of
            # overwriting it when the refreshed endpoint returns new content.
            subtitle_stem += "_"+digest(source)[:10]
            raw_target = base/(subtitle_stem+".原始.json")
        preserve_copy(source,raw_target)
        srt_target = base/(subtitle_stem+".srt")
        text_target = base/(subtitle_stem+".阅读.txt")
        srt = "\n".join(f"{i}\n{timestamp(row['from'],True)} --> {timestamp(row['to'],True)}\n{row['content']}\n" for i,row in enumerate(cues,start=1))
        srt_target.write_text(srt,encoding="utf-8")
        header = [stem,f"官方来源：{manifest['url']}",f"原始标题：{manifest['title']}",
                  f"BV/CID/P：{manifest['bvid']} / {manifest['cid']} / {manifest['page']}",
                  f"资料类型：{kind}；平台语言 {track.get('language')}；原始 type={document.get('type')}",
                  f"字幕段数：{len(cues)}；原始文件：{raw_target.name}",
                  "日期/阶段/局次来自标题，周次为归档导航候选，尚未人工核验。",
                  "这是带时间戳的原始平台转写，未纠正姓名、票数、身份；未完成说话人归属或对局复盘。"]
        header += ["待核事项："+note for note in labels["warnings"]]
        text_target.write_text("\n".join(header)+"\n\n"+"\n".join(
            f"[{timestamp(row['from'])} → {timestamp(row['to'])}] {row['content']}" for row in cues)+"\n",encoding="utf-8")
        result["subtitles"].append({"language":track.get("language"),"type":document.get("type"),"segment_count":len(cues),
            "raw":raw_target.relative_to(ROOT).as_posix(),"srt":srt_target.relative_to(ROOT).as_posix(),
            "readable":text_target.relative_to(ROOT).as_posix(),"sha256":digest(raw_target)})
    description = {**labels,"bvid":manifest["bvid"],"cid":manifest["cid"],"page":manifest["page"],
                   "url":manifest["url"],"audio_bytes":manifest["audio"]["bytes"],"audio_sha256":manifest["audio"]["sha256"],
                   "collected_at_utc":manifest.get("collected_at_utc"),"exports":result}
    info = base/(stem+".来源与命名.json")
    info.write_text(json.dumps(description,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    result["description"] = info.relative_to(ROOT).as_posix()
    return result
