"""Prepare current-batch inputs and validate candidates written by this window."""
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
from incremental_common import (ROOT, entry_key, load_state, read_json, save_state,
                                work_dir, write_json)
from media_ingest import validate_media
from season_config import load_season, season_codes


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
    config = load_season(season, root)
    formal = config.get("formal_import", {})
    mapping = formal.get("board_code_map", {})
    code = formal.get("board_overrides", {}).get(entry.get("bvid"))
    if code is None:
        code = BOARD_CODES.get(name) or {"青丘夜影": "qingqiu_night", "魔幻对决": "magic_duel"}.get(name)
    if not code:
        raise ValueError(f"新增版型尚未确认正式模板：{name}；需先核规则，不能套用其他版型")
    from game_scope import exclusion_reason
    reason = exclusion_reason({"season": season, "board": code, "bvid": entry.get("bvid"),
                               "date": entry["labels"].get("event_date_candidate"),
                               "phase": entry["labels"].get("phase_candidate")}, root=root)
    if reason:
        raise ValueError(reason)
    stored_code = mapping.get(code, code)
    load_template(stored_code, root)
    return stored_code


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
    from voting_core import validate as validate_voting
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
    if "endgame" in value:
        from endgame_records import validate as validate_endgame
        endgame = value["endgame"]
        if not isinstance(endgame, dict) or endgame.get("game_slug") != game["slug"]:
            raise ValueError("终局与对局slug不一致")
        validate_endgame(endgame)
    try:
        validate_batch(game)
        validate_voting(votes)
    except (KeyError, TypeError) as error:
        raise ValueError(f"AI结构字段缺失或类型错误：{error}") from error
    if not game["rounds"] or not candidate["evidence"]:
        raise ValueError("AI未提供实际日夜与证据，不能生成已分析候选")
    duration = entry["duration_seconds"] * 1000
    source_rows = normalized_segments(source_path)
    evidence_hashes = {}
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
        if path not in evidence_hashes:
            evidence_hashes[path] = sha256(path)
        digest = evidence_hashes[path]
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


def analyze_one(item: dict, season: str, *, root: Path = ROOT, device="cuda",
                auth="none", cookies: Path | None = None, prepare_only=True) -> dict:
    entry = item["entry"]
    print(f"处理新局：{entry['title']} · {entry_key(entry)}", flush=True)
    source = prepare_text(entry, season, root=root, device=device)
    source_hash = sha256(source)
    folder = work_dir(root, season, entry)
    folder.mkdir(parents=True, exist_ok=True)
    candidate_path = folder / "candidate.json"
    if candidate_path.is_file():
        if (item.get("source_sha256") != source_hash
                or item.get("candidate_sha256") not in (None, sha256(candidate_path))):
            raise ValueError("本局候选或文字版本已变化；保留原草稿，请明确核对后再重建")
        result = validate_candidate(read_json(candidate_path), entry, source, root=root)
        from game_derivations import derive_game
        rules = derive_game(result["dossier"], result["voting"], endgame=result.get("endgame"))
        write_json(folder / "rule_derivations.json", rules["derivations"])
        item["candidate_sha256"] = sha256(candidate_path)
        item["analysis"] = "ready"
        item.pop("analysis_error", None)
        print("复用已有候选和证据，不重新调用AI。", flush=True)
        return {"entry": entry, "candidate": {**result, "dossier": rules["dossier"],
                                               "voting": rules["voting"]},
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
    raise ValueError("请由当前窗口完成候选与证据，再运行 --validate-candidates")


def run(season="S23", *, root: Path = ROOT, device="cuda", auth="none",
        cookies=None, bvids=(), prepare_only=True) -> dict:
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
            game = analyze_one(item, season, root=root, device=device,
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
        from game_review_page import render_review_page
        # An explicit subset must not replace the all-pending review workspace.
        if selected:
            output = output.with_name(season + "_指定对局人工复核_" + "_".join(sorted(selected)) + ".html")
        render_review_page(games, output, season=season, root=root)
    report = {"season": season, "analyzed": len(games), "prepared": len(prepared),
              "waiting_acquisition": waiting, "failures": failures,
              "review_page": None if prepare_only else str(output),
              "final_data_written": False}
    write_json(root / f"data/reports/{season}/incremental/analysis.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", choices=season_codes(ROOT), default="S23")
    parser.add_argument("--bvid", action="append", default=[])
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--auth", choices=["none", "cookies"])
    parser.add_argument("--cookies-file", type=Path, default=Path(".secrets/bilibili.cookies.txt"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true", dest="prepare_only",
                      help="只准备本机文字输入（默认；保留此参数供旧命令兼容）")
    mode.add_argument("--validate-candidates", action="store_false", dest="prepare_only",
                      help="校验当前窗口保存的候选并生成本批人工复核页")
    parser.set_defaults(prepare_only=True)
    args = parser.parse_args(argv)
    auth = args.auth or ("cookies" if args.cookies_file.is_file() else "none")
    report = run(args.season, device=args.device, auth=auth,
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
