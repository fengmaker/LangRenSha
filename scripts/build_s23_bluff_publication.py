"""Build the public S23 bluff-review asset from formal game snapshots.

The source game fingerprints are computed from the same public projection used
by the website publisher. This script validates and writes a static JSON asset;
it never connects to or publishes to the website database.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from website.api import bluff_store, bluffs, publisher  # noqa: E402
from scripts.s23_bluff_audit import AuditError, digest, load_audits


SEASON = "S23"
EXPECTED_GAMES = 75
INFERENCE_VERSION = "S23-bluff-20261026-v3-video-continuation"
_INFO_ROLES = {"预言家", "通灵师"}
_LOCAL_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s，。；、]+|(?:data|outputs|transcripts|extractions|config|website)[\\/][^\s，。；、]+)",
    re.IGNORECASE,
)


class BuildError(ValueError):
    """The formal game data or bluff review cannot be safely projected."""


def _public_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _LOCAL_PATH.sub("本地来源已省略", value).strip()


def _claim_day(value: Any) -> int | str | None:
    if type(value) is int and value in (1, 2):
        return value
    if type(value) is int and value > 2:
        return "later"
    if value == "later":
        return value
    return None


def _evidence(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = _public_text(row.get("quote", row.get("text")))
        if not text:
            continue
        item: dict[str, Any] = {
            "kind": row.get("kind") if isinstance(row.get("kind"), str) else "source",
            "text": text,
        }
        interpretation=_public_text(row.get('interpretation'))
        if interpretation:
            item['interpretation']=interpretation
        start = row.get("start_ms", row.get("frame_time_ms"))
        end = row.get("end_ms")
        if type(start) is int and start >= 0:
            item["start_ms"] = start
        if type(end) is int and end >= 0:
            item["end_ms"] = end
        if row.get("kind") == "video_frame" and re.fullmatch(r'[a-f0-9]{64}',str(row.get("source_sha256",''))):
            item["image_url"] = f"/media/bluff-frames/S23/{row['source_sha256']}.png"
        result.append(item)
    return result


def _indexed_bluffs(review: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = review.get("bluffs", [])
    if not isinstance(rows, list):
        raise BuildError("ai_review.bluffs 必须为数组")
    indexed: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("seat")) is not int:
            raise BuildError("悍跳判断缺少有效座位")
        seat = row["seat"]
        if seat in indexed:
            raise BuildError(f"ai_review.bluffs 中 {seat} 号判断重复")
        indexed[seat] = row

    changes = review.get("daily_bluff_changes", []) or []
    if isinstance(changes, dict):
        changes = [changes]
    if not isinstance(changes, list):
        raise BuildError("daily_bluff_changes 格式无效")
    for change in changes:
        if not isinstance(change, dict):
            continue
        before, after = change.get("before"), change.get("after")
        target = after if isinstance(after, dict) else before if isinstance(before, dict) else None
        seat = target.get("seat") if target else None
        if type(seat) is not int:
            continue
        if isinstance(after, dict):
            indexed[seat] = after
        else:
            indexed.pop(seat, None)
    return indexed


def _separate_identity_claims(review: dict[str, Any]) -> list[dict[str, Any]]:
    rows = review.get("separate_identity_claims", []) or []
    if not isinstance(rows, list):
        raise BuildError("separate_identity_claims 必须为数组")
    result = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get("seat")) is not int:
            continue
        category = _public_text(row.get("category_label"))
        counting_note = _public_text(row.get("counting_note"))
        unresolved = "遗言" in category or "待用户决定" in counting_note or "口径待" in counting_note
        item: dict[str, Any] = {
            "seat": row["seat"],
            "day": _claim_day(row.get("day")),
            "claimed_role": row.get("claimed_role") if row.get("claimed_role") in _INFO_ROLES else None,
            "category": category or "独立身份宣称",
            "count_in_physical_wolf_bluffs": row.get("count_in_physical_wolf_bluffs") is True,
            "decision": "uncertain" if unresolved else "not_counted",
            "note": ("遗言阶段的信息神自称是否计入常规悍跳统计尚未确定，暂列待复核。"
                     if unresolved else "该身份宣称保留为独立记录，不计入物理狼人悍跳次数。"),
            "evidence": _evidence(row.get("evidence")),
        }
        if type(row.get("day")) is int and row["day"] > 2:
            item["day_note"] = f"来源记录为第{row['day']}天；在常规字段中保留为后续日期。"
        result.append(item)
    return result


def _assessment(seat: dict[str, Any], row: dict[str, Any] | None,
                separate_claims: list[dict[str, Any]]) -> dict[str, Any]:
    separate = [claim for claim in separate_claims if claim["seat"] == seat["seat"]]
    attempted = row.get("attempted") if row else None
    decision = "yes" if attempted is True else "no" if attempted is False else "uncertain"
    claimed_role = row.get("claimed_role") if row else None
    original_claimed_role = _public_text(claimed_role)
    if claimed_role not in _INFO_ROLES:
        claimed_role = None
    evidence = _evidence(row.get("evidence")) if row else []
    verification = "user_confirmed" if row and row.get("confirmation_status") == "user_confirmed" else "assistant_inferred"
    questions = []
    if attempted is True and not evidence and verification != "user_confirmed":
        raise BuildError(f"{seat['seat']}号 attempted=true 缺少可公开的定位证据")
    if separate and (row is None or type(attempted) is not bool):
        decision = "uncertain"
        questions.append("该座位存在不计入常规统计的独立身份宣称，是否属于常规悍跳尚待确认。")
    if attempted is True and claimed_role is None and verification != "user_confirmed":
        decision = "uncertain"
        questions.append("所跳身份原始字段无法唯一归一为预言家或通灵师，暂列待复核。")
    if decision == "uncertain" and not questions:
        questions.append("该狼人座位尚无明确悍跳结论；未按未尝试计入。")

    day = _claim_day(row.get("day")) if row else None
    first_day_claim = row.get("first_day_claim") if row else None
    if type(first_day_claim) is not bool:
        first_day_claim = True if day == 1 else False if day in (2, "later") else None
    confidence = row.get("confidence") if row else None
    if confidence not in {"high", "medium", "low"}:
        confidence = "high" if verification == "user_confirmed" else "medium" if decision in {"yes", "no"} else "low"
    note = _public_text(row.get("reasoning")) if row else ""
    if attempted is True and claimed_role is None and verification != "user_confirmed":
        note = f"原始所跳身份记录为“{original_claimed_role or '未提供'}”，无法唯一归一为预言家或通灵师；暂列待复核。"
    if row and type(row.get("day")) is int and row["day"] > 2:
        suffix = f"来源记录起跳日为第{row['day']}天，按后续日期保留；成功结果待复核。"
        note = f"{note} {suffix}".strip()
    if separate:
        note = "遗言阶段的信息神自称保留为独立记录；常规悍跳统计口径未定，暂列待复核。"
    return {
        "seat": seat["seat"],
        "name": seat["name"],
        "physical_role": seat.get("role"),
        "decision": decision,
        "claimed_role": claimed_role,
        "confidence": confidence,
        "claim_day": day,
        "actual_claim_day":row.get('day') if row and type(row.get('day')) is int and row['day']>2 else None,
        "first_day_claim": first_day_claim,
        "decision_note": note,
        "verification_status": verification,
        "review_questions": questions,
        "evidence": evidence,
    }


def _public_game(entry: dict[str, Any], person_ids: dict[str, str]) -> dict[str, Any]:
    return publisher._public_game(
        entry["dossier"], entry["voting"], entry["endgame"], entry.get("audit"),
        entry["board"], person_ids,
    )


def build_payload(root: Path, *, allow_partial_audit: bool=False) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    try:
        entries, _, _ = publisher.load_publication(root, SEASON)
    except Exception as exc:
        raise BuildError(f"正式 S23 dossier.json/voting.json 尚未就绪或无法载入：{exc}") from exc
    if len(entries) != EXPECTED_GAMES:
        raise BuildError(f"正式 S23 范围应为 {EXPECTED_GAMES} 局，当前读取到 {len(entries)} 局")

    names = {seat.get("name") for entry in entries for seat in entry["dossier"].get("seats", [])}
    person_ids = {
        name: str(uuid.uuid5(publisher.PERSON_NAMESPACE, name.strip().casefold()))
        for name in names if isinstance(name, str)
    }
    public_games = [_public_game(entry, person_ids) for entry in entries]
    try:
        audits=load_audits(root,public_games,require_complete=not allow_partial_audit)
    except AuditError as exc:
        raise BuildError(str(exc)) from exc
    by_id = {game["id"]: game for game in public_games}
    if len(by_id) != EXPECTED_GAMES:
        raise BuildError("正式 S23 对局 ID 缺失或重复")

    payload_games = []
    separate_total = 0
    human_path=root/'data/extractions/S23/bluff_review/user_confirmed.json'
    human=json.loads(human_path.read_text(encoding='utf-8')).get('records',{}) if human_path.is_file() else {}
    for entry, game in zip(entries, public_games, strict=True):
        review_path = entry["folder"] / "ai_review.json"
        try:
            review = json.loads(review_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BuildError(f"{game['id']} 缺少有效 ai_review.json") from exc
        if review.get("bvid") != entry["bvid"]:
            raise BuildError(f"{game['id']} 的悍跳复核 BVID 与正式档案不一致")

        separate = _separate_identity_claims(review)
        separate_total += len(separate)
        reviewed = _indexed_bluffs(review)
        wolf_seats = [seat for seat in game.get("seats", []) if bluffs.physical_wolf(game, seat)]
        assessments = [_assessment(seat, reviewed.get(seat["seat"]), separate) for seat in wolf_seats]
        independent=audits.get(game['id'])
        if independent:
            assessments=[]
            for source_assessment in independent['assessments']:
                assessment={key:source_assessment.get(key) for key in (
                    'seat','name','physical_role','decision','claimed_role','claim_day',
                    'first_day_claim','verification_status','decision_note','review_questions')}
                assessment['actual_claim_day']=source_assessment.get('actual_claim_day')
                assessment['confidence']=source_assessment.get('confidence','high' if assessment['decision']!='uncertain' else 'low')
                assessment['evidence']=_evidence(source_assessment.get('evidence',[]))
                if assessment['verification_status']!='user_confirmed':
                    assessment['verification_status']='assistant_inferred'
                if entry['bvid']=='BV1U3p86dEJY' and assessment['seat']==6:
                    if assessment['decision']!='yes' or assessment['claimed_role']!='通灵师':
                        raise BuildError('独立复核与用户已确认的6号悍跳冲突')
                    assessment['verification_status']='user_confirmed'
                assessments.append(assessment)
            for assessment in assessments:
                pending_eulogy=any(claim['seat']==assessment['seat'] and claim.get('decision')=='uncertain'
                                   and '遗言' in claim.get('category','') for claim in separate)
                if pending_eulogy and assessment['decision']!='yes':
                    assessment['decision']='uncertain'
                    assessment['decision_note']+=' 首日常规发言与遗言身份自称分开记录；遗言是否计入常规悍跳仍待你决定。'
                    assessment['review_questions']=['遗言阶段才自称信息神，是否纳入常规悍跳统计？']
        source = game.get("source") or {}
        for assessment in assessments:
            assessment['review_stage']='reviewed' if independent else 'assistant_pending'
            assessment['requires_user_review']=bool(independent and any(
                claim['seat']==assessment['seat'] and claim.get('decision')=='uncertain'
                and '遗言' in claim.get('category','') for claim in separate))
            if not independent:
                assessment['decision_note']='本轮视频交叉复核尚未完成，保留既有推断，待助手继续；此项不要求你亲自核对。 '+assessment.get('decision_note','')
        for assessment in assessments:
            feedback=human.get(f"{source.get('bvid')}:{assessment['seat']}")
            if not feedback:continue
            if feedback.get('source_fingerprint')!=bluffs.source_fingerprint(game):
                raise BuildError('用户反馈对应的正式底牌或结果已变化，需要重新核对')
            action=feedback.get('decision')
            if action in {'yes','no','uncertain'}:
                assessment.update(decision=action,claimed_role=feedback.get('claimed_role'),claim_day=feedback.get('claim_day'),
                                  first_day_claim=True if feedback.get('claim_day')==1 else False if feedback.get('claim_day') in {2,'later'} else None,
                                  verification_status='user_uncertain' if action=='uncertain' else 'user_confirmed',review_questions=[])
                assessment['requires_user_review']=action=='uncertain'
                if feedback.get('claim_day')!='later':assessment['actual_claim_day']=None
                if action=='no':
                    for claim in separate:
                        if claim['seat']==assessment['seat']:
                            claim.update(decision='not_counted',count_in_physical_wolf_bluffs=False,
                                         verification_status='user_confirmed',
                                         note='用户确认不计入常规悍跳。 '+_public_text(feedback.get('notes')))
            else:
                assessment['verification_status']='user_comment'
                if action=='later':assessment['decision']='uncertain'
            if feedback.get('notes'):
                if action in {'yes','no'}:
                    assessment['decision_note']='用户确认：'+_public_text(feedback['notes'])
                else:
                    assessment['decision_note']+=' 用户意见：'+_public_text(feedback['notes'])
        record = {
            "game_id": game["id"],
            "bvid": source.get("bvid"),
            "source_fingerprint": bluffs.source_fingerprint(game),
            "coverage": "first_day_video_and_transcript" if independent else "recap_and_claims",
            "assessments": assessments,
        }
        if separate:
            record["separate_identity_claims"] = separate
        if independent and independent.get('result_review'):
            result_review=independent['result_review']
            record['result_review']={'badge':result_review['badge'],
                                     'note':_public_text(result_review['note']),
                                     'evidence':_evidence(result_review['evidence'])}
        payload_games.append(record)

    payload = {
        "schema_version": 1,
        "season": SEASON,
        "inference_version": INFERENCE_VERSION,
        "status": "reviewed_with_user_confirmed_fields_and_pending_items",
        "methodology": list(bluffs.METHODOLOGY) + bluffs.S23_VIDEO_METHODOLOGY,
        "games": payload_games,
    }
    try:
        items, validation = bluff_store._validate_review(
            public_games, payload, SEASON, expected_game_count=EXPECTED_GAMES,
        )
    except bluff_store.BluffReviewError as exc:
        raise BuildError(f"S23 悍跳资产未通过现有发布校验：{exc}") from exc

    decisions = {key: 0 for key in ("yes", "no", "uncertain")}
    for game in payload_games:
        for assessment in game["assessments"]:
            decisions[assessment["decision"]] += 1
    payload["summary"] = {
        "games_total": len(public_games),
        "games_assessed": len(audits),
        "wolf_appearances": validation["wolf_count"],
        "decisions": decisions,
        "successful_bluffs": validation["success_count"],
        "pending": sum(item['requires_user_review'] for item in items),
        "statistics_pending": validation["pending_count"],
        "assistant_pending":sum(item['assistant_pending'] for item in items),
        "games_pending":len(public_games)-len(audits),
        "audited_identified_bluffs":sum(item['decision']=='yes' and not item['assistant_pending'] for item in items),
        "evidence_validation_issues": 0,
        "user_confirmed_records": validation["user_confirmed_count"],
        "separate_identity_claims": separate_total,
        "independently_rechecked_games": len(audits),
        "first_day_frames":sum(bool(a.get('frame_selection',{}).get('frame_path')) for a in audits.values()),
    }
    return payload, items, validation


def save_frames(root: Path) -> dict[str,str]:
    """Copy only reviewed source frames; retain their original bytes and digest."""
    manifest_path=root/'website/api/bluff_frames.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {'schema_version':1,'frames':{}}
    records={}
    for part in sorted((root/'data/extractions/S23/bluff_review/parts').glob('audit_*.json')):
        for game in json.loads(part.read_text(encoding='utf-8-sig')).get('games',[]):
            for assessment in game['assessments']:
                for evidence in assessment.get('evidence',[]):
                    if evidence.get('kind')!='video_frame':continue
                    source=(root/evidence['source_path']).resolve()
                    sha=digest(source)
                    if sha!=evidence['source_sha256']:raise BuildError('截图复制前哈希已变化')
                    filename=sha+'.png'
                    target=root/'website/assets/bluff-frames/S23'/filename
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if not target.is_file():shutil.copyfile(source,target)
                    if digest(target)!=sha:raise BuildError('公开截图与原始截图字节不同')
                    when=evidence.get('frame_time_ms',evidence.get('start_ms',0))
                    records[filename]={'bvid':game['bvid'],'frame_time_ms':when,'sha256':sha,
                                       'source_url':f"https://www.bilibili.com/video/{game['bvid']}/?t={when/1000:g}"}
    manifest['frames']['S23']=records
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {f'/media/bluff-frames/S23/{name}':f'../../website/assets/bluff-frames/S23/{name}' for name in records}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=publisher.DEFAULT_SOURCE_ROOT,
                        help="project/source root containing formal data/games/S23 records")
    parser.add_argument("--output", type=Path, default=bluffs.ASSET_ROOT / "S23.json")
    parser.add_argument("--check", action="store_true", help="build and validate without writing the asset")
    parser.add_argument("--allow-partial-audit",action="store_true",help="交付当前已核范围；未核项明确保留待助手继续")
    args = parser.parse_args(argv)
    try:
        payload, items, validation = build_payload(args.root,allow_partial_audit=True) if args.allow_partial_audit else build_payload(args.root)
        if not args.check:
            frames=save_frames(args.root)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            from scripts.build_bluff_inference import render_html
            export=args.root/'data/exports/S23_悍跳推断与复核.html'
            export.write_text(render_html(items,payload['summary'],payload['inference_version'],season='S23',frame_paths=frames),encoding='utf-8')
            export.with_suffix('.json').write_text(json.dumps({'summary':payload['summary'],'items':items},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({
            "season": SEASON,
            "games": payload["summary"]["games_total"],
            "wolf_appearances": validation["wolf_count"],
            "decisions": payload["summary"]["decisions"],
            "successful_bluffs": validation["success_count"],
            "pending": payload['summary']['pending'],
            "statistics_pending":validation['pending_count'],
            "games_rechecked":payload['summary']['independently_rechecked_games'],
            "games_pending":payload['summary']['games_pending'],
            "assistant_pending":payload['summary']['assistant_pending'],
            "user_confirmed_records": validation["user_confirmed_count"],
            "separate_identity_claims": payload["summary"]["separate_identity_claims"],
            "checked": True,
            "written": not args.check,
            "path": str(args.output) if not args.check else None,
        }, ensure_ascii=False, indent=2))
        return 0
    except BuildError as exc:
        print(json.dumps({"error": "s23_bluff_asset_failed", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
