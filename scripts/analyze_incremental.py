"""Prepare only new games with ASR when needed, AI evidence review, and a notes page."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from board_catalog import BOARD_CODES
from board_config import load_template
from collect_bilibili_audio import is_chinese_subtitle
from incremental_ai import run_json
from incremental_common import (ROOT, entry_key, load_state, read_json, save_state,
                                work_dir, write_json)
from media_ingest import validate_media
from season_config import load_season


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def data_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to((root / "data").resolve()) or not path.is_file():
        raise ValueError(f"来源文件不存在或超出data：{relative}")
    return path


def normalized_segments(source: Path) -> list[dict]:
    document = read_json(source)
    rows = document.get("body", document.get("segments", []))
    result = []
    for index, row in enumerate(rows):
        if "start_ms" in row:
            start, end, text = row["start_ms"], row["end_ms"], row.get("text", "")
        else:
            start = round(row.get("from", row.get("start", 0)) * 1000)
            end = round(row.get("to", row.get("end", 0)) * 1000)
            text = row.get("content", row.get("text", ""))
        if type(start) not in (int, float) or type(end) not in (int, float) or start < 0 or end < start:
            raise ValueError("字幕/转写段落时间不合法")
        if not isinstance(text, str):
            raise ValueError("字幕/转写文本必须为字符串")
        if text.strip():
            result.append({"index": index, "start_ms": start, "end_ms": end, "text": text})
    if not result:
        raise ValueError("本局没有可用文字段落")
    return result


def prepare_text(entry: dict, season: str, *, root: Path = ROOT, device="cuda") -> Path:
    folder = root / "data/raw/bilibili" / entry["bvid"] / f"p{entry['page']:02d}"
    checked = validate_media(folder / "manifest.json", entry["bvid"], entry["page"])
    manifest = checked["manifest"]
    if manifest["cid"] != entry["cid"]:
        raise ValueError("已采媒体CID与增量队列不一致")
    chinese = [(path, track) for path, track in checked["subtitles"]
               if is_chinese_subtitle(track.get("language"))]
    if chinese:
        # All tracks have already been validated. Prefer human Chinese over AI tracks.
        chinese.sort(key=lambda item: str(item[1].get("language", "")).startswith("ai-"))
        return chinese[0][0]
    if checked["audio_path"] is None:
        raise ValueError("没有中文字幕或完整音轨，不能开始分析")
    paths = [root / f"data/transcripts/{season}/{entry['bvid']}_p{entry['page']:02d}_cid{entry['cid']}_funasr",
             root / f"data/transcripts/{season}/{entry['bvid']}_p{entry['page']:02d}_funasr"]
    for out in paths:
        transcript = out / "transcript.json"
        if transcript.is_file():
            value = read_json(transcript)
            source = value.get("source", {})
            if (value.get("full_audio_processed") is True
                    and source.get("audio_sha256") == manifest["audio"]["sha256"]
                    and all(source.get(key) == entry[key] for key in ("bvid", "cid", "page"))):
                return transcript
    out = paths[0]
    command = [str(root / ".venv-funasr39/Scripts/python.exe"),
               str(root / "scripts/transcribe_funasr.py"), str(checked["audio_path"]),
               "--manifest", str(folder / "manifest.json"), "--no-speakers",
               "--device", device, "--out", str(out)]
    subprocess.run(command, cwd=root, check=True)
    transcript = out / "transcript.json"
    value = read_json(transcript)
    if (value.get("full_audio_processed") is not True
            or value.get("source", {}).get("audio_sha256") != manifest["audio"]["sha256"]):
        raise ValueError("ASR尚未完整完成或音轨版本不匹配")
    return transcript


def board_for(entry: dict, season: str, root: Path) -> str:
    name = entry["labels"].get("board_candidate")
    code = BOARD_CODES.get(name) or {"青丘夜影": "qingqiu_night", "魔幻对决": "magic_duel"}.get(name)
    config = load_season(season, root)
    mapping = config.get("formal_import", {}).get("board_code_map", {})
    if not code or code not in mapping:
        raise ValueError(f"新增版型尚未确认正式模板：{name}；需先核规则，不能套用其他版型")
    return mapping[code]


def skeleton(entry: dict, source: Path, *, root: Path = ROOT, season="S23") -> dict:
    from game_records import empty_event
    labels = entry["labels"]
    board = board_for(entry, season, root)
    template = load_template(board, root)
    number = labels.get("game_number_candidate")
    if type(number) is not int or number < 1 or not labels.get("event_date_candidate"):
        raise ValueError("标题缺少日期/局次；需先核实后开始该局分析")
    slug = f"bili-{entry['bvid']}-p{entry['page']:02d}-g{number:02d}"
    role = "subtitle" if "body" in read_json(source) else "transcript"
    dossier = {"slug": slug, "season": season, "date": labels["event_date_candidate"],
               "phase": labels["phase_candidate"], "episode": labels.get("issue_candidate"),
               "day_in_episode": labels.get("original_day_label"), "game_number": number,
               "board": board, "winner": None, "roster": [], "commentators": [], "referee": None,
               "seats": [{"seat": n, "name": None, "role": None, "faction": None,
                          "learning_target": None, "learned_role": None}
                         for n in range(1, template["seat_count"] + 1)],
               "rounds": [{"number": 1, **{phase: [empty_event(slot["code"])
                                                        for slot in template[phase + "_slots"]]
                                           for phase in ("night", "day")}}],
               "files": [{"role": role, "kind": role, "platform": "bilibili",
                          "external_key": f"{entry['bvid']}:{entry['cid']}",
                          "path": source.relative_to(root).as_posix()}]}
    return {"dossier": dossier, "voting": {"schema_version": 1, "game_slug": slug,
             "registrations": [], "ballots": [], "interruptions": [], "days": []},
            "evidence": [], "issues": []}


def validate_candidate(candidate: dict, entry: dict, source_path: Path, *, root: Path = ROOT) -> dict:
    """Validate the AI boundary; facts, evidence and source ownership stay distinct."""
    from game_records import validate_batch
    from voting_records import validate as validate_voting
    if (not isinstance(candidate, dict) or not isinstance(candidate.get("dossier"), dict)
            or not isinstance(candidate.get("voting"), dict)
            or not isinstance(candidate.get("evidence"), list)
            or not isinstance(candidate.get("issues"), list)
            or any(not isinstance(issue, str) for issue in candidate["issues"])):
        raise ValueError("AI候选须包含dossier、voting、evidence、issues")
    value = deepcopy(candidate)
    game, votes = value["dossier"], value["voting"]
    season = game.get("season")
    if season != entry["labels"].get("season", "S23"):
        raise ValueError("AI候选赛季与采集来源不一致")
    expected = skeleton(entry, source_path, root=root, season=season)["dossier"]
    for field in ("slug", "season", "files", "board", "phase"):
        if game.get(field) != expected[field]:
            raise ValueError(f"AI不得更换来源及已选范围：{field}")
    if not isinstance(game.get("date"), str):
        raise ValueError("候选比赛日期必须为ISO日期字符串")
    date.fromisoformat(game["date"])
    if votes.get("game_slug") != game["slug"]:
        raise ValueError("票型与对局slug不一致")
    try:
        validate_batch(game)
        validate_voting(votes)
    except (KeyError, TypeError) as error:
        raise ValueError(f"AI结构字段缺失或类型错误：{error}") from error
    if not game["rounds"] or not candidate["evidence"]:
        raise ValueError("AI未提供实际日夜与证据，不能生成已分析候选")
    duration = entry["duration_seconds"] * 1000
    source_rows = normalized_segments(source_path)
    for evidence in value["evidence"]:
        if not isinstance(evidence, dict) or not isinstance(evidence.get("source_path"), str):
            raise ValueError("证据缺少本地来源路径")
        if evidence.get("kind") not in ("text", "image", "weibo") or not evidence.get("field"):
            raise ValueError("证据需要字段定位及text/image/weibo类型")
        path = data_path(root, evidence["source_path"])
        if path != source_path.resolve() and not path.is_relative_to(work_dir(root, season, entry).resolve()):
            # Weibo original images/text may be used, but not unrelated game sources.
            if not path.is_relative_to((root / "data/raw/weibo").resolve()):
                raise ValueError("证据属于另一对局或未经提供的来源")
        digest = sha256(path)
        if evidence.get("sha256") not in (None, digest):
            raise ValueError("证据SHA与本地原件不一致")
        evidence["sha256"] = digest
        if evidence["kind"] == "image" and path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ValueError("图片证据必须指向真实图片文件")
        if evidence.get("kind") == "text":
            start, end = evidence.get("start_ms"), evidence.get("end_ms")
            quote = evidence.get("quote")
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not 0 <= start <= end <= duration + 1000 or not isinstance(quote, str) or not quote):
                raise ValueError("文字证据缺少合法时间窗口及原话")
            if path != source_path.resolve():
                raise ValueError("本局文字证据必须引用本次字幕/转写")
            matching = [row["text"] for row in source_rows
                        if row["end_ms"] >= start and row["start_ms"] <= end]
            if "".join(quote.split()) not in "".join("".join(matching).split()):
                raise ValueError("引用原话不在所指文字窗口内")
    return value


def weibo_sources(root: Path, event_date: str) -> list[dict]:
    """Expose nearby post text and actual local photo paths for roster checking."""
    posts = {}
    for path in sorted((root / "data/raw/weibo").glob("*/manifest.json")):
        document = read_json(path)
        request = document.get("request", {})
        if request.get("uid") != "7525583841":
            continue
        # Announcement can precede the match. Read metadata for just the target
        # date and preceding seven days, not images of every historical roster.
        from datetime import timedelta
        start = (date.fromisoformat(event_date) - timedelta(days=7)).isoformat()
        for post in document.get("posts", []):
            if start <= (post.get("published_date") or "") <= event_date:
                sources = []
                for field in ("full_text_file", "raw_file"):
                    if post.get(field):
                        source = (path.parent / post[field]).resolve()
                        if source.is_relative_to(path.parent.resolve()) and source.is_file():
                            sources.append(source.relative_to(root).as_posix())
                images = []
                for image in post.get("images", []):
                    if image.get("status") == "downloaded" and image.get("file"):
                        source = (path.parent / image["file"]).resolve()
                        if source.is_relative_to(path.parent.resolve()) and source.is_file():
                            images.append(source.relative_to(root).as_posix())
                if sources:
                    posts[post["post_id"]] = {"post_id": post["post_id"],
                        "published_date": post["published_date"], "text_sources": sources,
                        "images": images, "post_url": post.get("post_url")}
    return list(posts.values())


def analyze_one(item: dict, season: str, *, root: Path = ROOT, codex="codex", device="cuda",
                auth="none", cookies: Path | None = None, prepare_only=False) -> dict:
    entry = item["entry"]
    print(f"处理新局：{entry['title']} · {entry_key(entry)}", flush=True)
    source = prepare_text(entry, season, root=root, device=device)
    source_hash = sha256(source)
    folder = work_dir(root, season, entry)
    folder.mkdir(parents=True, exist_ok=True)
    candidate_path = folder / "candidate.json"
    if candidate_path.is_file():
        if (item.get("source_sha256") != source_hash
                or item.get("candidate_sha256") != sha256(candidate_path)):
            raise ValueError("本局候选或文字版本已变化；保留原草稿，请明确核对后再重建")
        validate_candidate(read_json(candidate_path), entry, source, root=root)
        item["analysis"] = "ready"
        item.pop("analysis_error", None)
        print("复用已有候选和证据，不重新调用AI。", flush=True)
        return {"entry": entry, "candidate": read_json(candidate_path),
                "candidate_sha256": item["candidate_sha256"], "source_sha256": source_hash}
    base = skeleton(entry, source, root=root, season=season)
    rows = normalized_segments(source)
    text_path = folder / "reading.txt"
    text_path.write_text("\n".join(f"[{r['index']} {r['start_ms']}..{r['end_ms']}] {r['text']}" for r in rows) + "\n", encoding="utf-8")
    source_rel = source.relative_to(root).as_posix()
    write_json(folder / "input.json", {"entry": entry, "source_path": source_rel,
               "source_sha256": source_hash, "skeleton": base,
               "weibo_sources": weibo_sources(root, entry["labels"]["event_date_candidate"])})
    item.update(source_path=source_rel, source_sha256=source_hash)
    if prepare_only:
        return {"prepared": True, "input": str(folder / "input.json")}
    plan_path = folder / "frame_plan.json"
    if plan_path.is_file():
        plan = read_json(plan_path)
        if plan.get("source_sha256") != source_hash:
            raise ValueError("已有截图计划属于其他文字版本")
    else:
        plan = run_json(
            f"只为这一局定位取证画面。读取{(folder / 'input.json').relative_to(root).as_posix()}及"
            f"{text_path.relative_to(root).as_posix()}，完整阅读连续法官复盘，结合白天发言定位名牌和真实底牌揭晓。"
            "复盘可能在视频中段，不能固定取片尾。选择最多12个有必要的画面时点，"
            "优先完整12席身份画面、姓名牌以及文字中确有歧义的票型；不用逐秒扫描。"
            "返回{frame_times_seconds:[数字秒数],notes:[定位理由字符串]}。不得判断或输出悍跳。",
            folder / "frame_plan.response.json", root=root, codex=codex)
        times = plan.get("frame_times_seconds")
        if (not isinstance(times, list) or not 1 <= len(times) <= 12
                or any(type(t) not in (int, float) or not 0 <= t < entry["duration_seconds"] for t in times)):
            raise ValueError("AI截图时点缺失或越界")
        plan["source_sha256"] = source_hash
        write_json(plan_path, plan)
    times = plan["frame_times_seconds"]
    frames = folder / "frames"
    expected_images = [frames / f"{entry['bvid']}_{t:09.3f}.png" for t in times]
    missing_times = [t for t, path in zip(times, expected_images) if not path.is_file()]
    if missing_times:
        from capture_bilibili_frame import capture
        capture(entry["bvid"], entry["cid"], missing_times, frames, auth, cookies)
    prompt = (
        f"只分析本局，输入与空白结构在{(folder / 'input.json').relative_to(root).as_posix()}，全文在"
        f"{text_path.relative_to(root).as_posix()}，原文路径{source_rel}，SHA256={source_hash}。"
        "先核实12席座位/规范姓名/物理底牌，姓名依据名牌及官方阵容，底牌依据真实揭晓和连续复盘；"
        "input.weibo_sources列出邻近日期官方帖原文和本机配图，先按正文定位本场阵容，"
        "只读对应原图名牌，不凭人脸认姓名，不按正文与合照顺序逐一配对。"
        "同一截图名牌可用不代表其当时展示的底牌真实。再按真实日夜恢复动作、原目标/结果、"
        "死亡离场、警徽和每轮逐人选票；PK/重投分别保留。不能把复盘顺序当睁眼顺序，"
        "不能把未知当空过、平安夜、弃票或无人悍跳。阅读本季规则和模板，"
        "依据docs/01第2、3步及docs/02字段规范进行本局预处理。"
        "返回JSON {dossier,voting,evidence,issues}，沿用input中的结构与来源files/slug/season/board/phase，"
        "复制第一轮固定槽位生成实际存在的后续轮次，不虚构终局后的阶段；"
        "投票结构使用schema_version:1、game_slug、registrations、ballots、interruptions、days。"
        "ballot固定字段id/day/kind/number/stage/status/candidates/eligible_voters/votes/tied_candidates/winner/unrecorded_voters；"
        "votes每项{voter,target,state:'cast'或'abstained'}，未知投向不写弃票，列入unrecorded_voters。"
        "每项事实均保留可定位的evidence（field、kind、source_path、start_ms、end_ms、quote或note）；"
        "field使用业务座位号/日号标明字段，kind只能是text、image、weibo。"
        "文字quote逐字引用原文，图片kind='image'并指向本次frames内文件，时间为请求定位点，不能冒充实际帧PTS。"
        "证据不足的字段保持null/unknown并写具体issues，不凭理论唯一以外的猜测补齐。"
        "悍跳只由用户在备注填写，本次不得识别或预填。禁止改写磁盘或其他局。"
        "可参考以下本季实际模板：\n" + json.dumps(load_template(base["dossier"]["board"], root), ensure_ascii=False)
    )
    result = run_json(prompt, folder / "ai_candidate.json", root=root, codex=codex, images=expected_images)
    result = validate_candidate(result, entry, source, root=root)
    from game_derivations import derive_game
    rules = derive_game(result["dossier"], result["voting"])
    write_json(folder / "rule_derivations.json", rules["derivations"])
    # Keep direct evidence and AI facts separate from reproducible rule suggestions.
    result["issues"].extend("规则冲突：" + json.dumps(row, ensure_ascii=False)
                            for row in rules["derivations"].get("issues", []))
    write_json(candidate_path, result)
    item.update(analysis="ready", candidate_sha256=sha256(candidate_path),
                source_sha256=source_hash, source_path=source_rel)
    item.pop("analysis_error", None)
    return {"entry": entry, "candidate": result, "candidate_sha256": item["candidate_sha256"],
            "source_sha256": source_hash}


def run(season="S23", *, root: Path = ROOT, codex="codex", device="cuda", auth="none",
        cookies=None, bvids=(), prepare_only=False) -> dict:
    state = load_state(root, season)
    selected = set(bvids)
    known = {item["entry"]["bvid"] for item in state["items"].values()}
    if selected - known:
        raise ValueError("指定BV不在增量队列：" + ", ".join(sorted(selected - known)))
    games, failures, prepared, waiting = [], [], [], []
    for key, item in state["items"].items():
        entry = item["entry"]
        if (item.get("applied") or item.get("formal_dossier")
                or item.get("scope") in ("scope_gap", "out_of_scope")
                or selected and entry["bvid"] not in selected):
            continue
        if entry["labels"].get("phase_candidate") not in ("regular", "finals_week"):
            continue
        if item.get("acquisition") != "ready":
            waiting.append(key)
            continue
        try:
            game = analyze_one(item, season, root=root, codex=codex, device=device,
                               auth=auth, cookies=cookies, prepare_only=prepare_only)
            if game.get("prepared"):
                prepared.append(key)
            else:
                games.append(game)
        except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
            item.update(analysis="failed", analysis_error=str(error))
            failures.append({"review_id": key, "error": str(error)})
            print(f"{entry['bvid']} 分析未完成：{error}", flush=True)
        save_state(root, season, state)
    output = root / f"data/manual_review/{season}_新增对局人工复核.html"
    if not prepare_only:
        from incremental_review_page import render_review_page
        # An explicit subset must not replace the all-pending review workspace.
        if selected:
            output = output.with_name(season + "_指定对局人工复核_" + "_".join(sorted(selected)) + ".html")
        render_review_page(games, output, season=season, root=root)
    report = {"season": season, "analyzed": len(games), "prepared": len(prepared),
              "waiting_acquisition": waiting, "failures": failures,
              "review_page": None if prepare_only else str(output),
              "database_written": False, "publication": False}
    write_json(root / f"data/reports/{season}/incremental/analysis.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", choices=["S23"], default="S23")
    parser.add_argument("--bvid", action="append", default=[])
    parser.add_argument("--codex", default="codex", help="已登录的Codex CLI路径")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--auth", choices=["none", "cookies"])
    parser.add_argument("--cookies-file", type=Path, default=Path(".secrets/bilibili.cookies.txt"))
    parser.add_argument("--prepare-only", action="store_true", help="只准备本机文字输入（缺文字仍需ASR），不调用AI/截图，不生成假分析页面")
    args = parser.parse_args(argv)
    auth = args.auth or ("cookies" if args.cookies_file.is_file() else "none")
    report = run(args.season, codex=args.codex, device=args.device, auth=auth,
                 cookies=args.cookies_file if auth == "cookies" else None,
                 bvids=args.bvid, prepare_only=args.prepare_only)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failures"] or report["waiting_acquisition"] else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
