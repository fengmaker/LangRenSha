"""Build conservative, review-only game-structure candidates from ASR JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


_CN_DIGITS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}
_NUMBER = r"(?:1[0-2]|[1-9]|十二|十一|十|[一二两三四五六七八九])"
_PLAYER_SPEAK = re.compile(
    rf"^(?:有请|请)?({_NUMBER})号(?:玩家)?(?:请)?(?:开始)?(?:发言|讲话|说话)吧?$"
)
_PLAYER_LAST_WORDS = re.compile(
    rf"^(?:有请|请)?({_NUMBER})号(?:玩家)?(?:请)?发表遗言$"
)
_PLAYER_TURN_END = re.compile(
    rf"^请?({_NUMBER})号(?:玩家)?(?:的)?(?:发言结束了?|结束发言|发言完毕)$"
)
_DAY_CUE = re.compile(rf"^第({_NUMBER})天(?:白天|开始)?$")
_EXPLOSION_NIGHT = re.compile(rf"^{_NUMBER}号(?:玩家)?选择自爆了?[，,。]?天黑请闭眼$")
_COMMAND_SEPARATOR = re.compile(r"[,，。.!！？?；;]+")

_EDGE_PUNCTUATION = " \t\r\n，,。.!！？?；;：:、"
_QUOTE_STARTS = "\"'“‘「『【（([{《"
_QUOTE_ENDS = "\"'”’」』】）)]}》"

_STAGE_CUES: dict[str, set[str]] = {
    "opening": {"游戏开始", "开始游戏", "欢迎进入本局游戏"},
    "night": {"天黑请闭眼", "天黑了请闭眼", "天黑了", "天黑"},
    "sheriff_election": {
        "警长竞选开始",
        "开始警长竞选",
        "进入警长竞选环节",
        "警上发言",
        "进入警上环节",
        "警上环节开始",
        "上警环节开始",
        "警下发言",
        "进入警下环节",
        "警长投票",
    },
    "daytime": {"天亮了", "天亮请睁眼", "天亮了请睁眼", "请睁眼"},
    "voting": {"开始投票", "投票开始", "进入投票环节", "请大家投票", "请投票", "放逐投票"},
    "last_words": {"发表遗言", "遗言时间", "进入遗言环节", "开始发表遗言"},
}

_GAME_END_CUES = {
    "游戏结束",
    "游戏结束了",
    "本局结束",
    "本局结束了",
    "本局游戏结束",
    "本局游戏结束了",
    "本场游戏结束",
    "本场游戏结束了",
    "本场结束",
}
_END_WITH_POLITE_TAIL = re.compile(
    r"^好?(?:本局游戏|本场游戏|本局|本场|游戏)结束了?[，,。.!！？?](?:谢谢(?:大家|各位)?[。.!！？?]?)?$"
)
_END_WITH_ORDINAL = re.compile(r"^第[一二三四五六七八九十0-9]+局游戏结束了?$")
_END_WITH_RESULT = re.compile(r"^游戏结束[，,。]?(?:好人|狼人)(?:阵营|正义)?(?:获得)?(?:获胜|胜利)$")


def _normalize_command_text(text: str) -> tuple[str, bool]:
    """Return compact text and whether it appears to be explicitly quoted."""
    value = text.strip()
    quoted = len(value) >= 2 and value[0] in _QUOTE_STARTS and value[-1] in _QUOTE_ENDS
    value = value.strip(_EDGE_PUNCTUATION)
    value = re.sub(r"\s+", "", value)
    return value, quoted


def _number_value(value: str) -> int | None:
    if value.isdigit():
        number = int(value)
    else:
        number = _CN_DIGITS.get(value)
    return number if number is not None and 1 <= number <= 12 else None


def _match_command_clause(text: str) -> dict[str, Any] | None:
    compact, quoted = _normalize_command_text(text)
    if quoted or len(compact) > 40:
        return None
    if _EXPLOSION_NIGHT.fullmatch(compact):
        return {"kind": "stage", "candidate_stage": "night", "explicit_day_number": None}
    match = _PLAYER_TURN_END.fullmatch(compact)
    if match:
        number = _number_value(match.group(1))
        return {"kind": "turn_end", "target_player_number": number} if number is not None else None
    match = _PLAYER_LAST_WORDS.fullmatch(compact)
    if match:
        number = _number_value(match.group(1))
        return {"kind": "instruction", "target_player_number": number, "instruction_kind": "last_words"} if number is not None else None
    match = _PLAYER_SPEAK.fullmatch(compact)
    if match:
        number = _number_value(match.group(1))
        return {"kind": "instruction", "target_player_number": number, "instruction_kind": "speak"} if number is not None else None
    if (compact in _GAME_END_CUES or _END_WITH_POLITE_TAIL.fullmatch(compact)
            or _END_WITH_ORDINAL.fullmatch(compact) or _END_WITH_RESULT.fullmatch(compact)):
        return {"kind": "stage", "candidate_stage": "ended", "explicit_day_number": None}
    day_match = _DAY_CUE.fullmatch(compact)
    if day_match:
        number = _number_value(day_match.group(1))
        if number is not None:
            return {"kind": "stage", "candidate_stage": "daytime", "explicit_day_number": number}
    for stage, cues in _STAGE_CUES.items():
        if compact in cues:
            return {"kind": "stage", "candidate_stage": stage, "explicit_day_number": None}
    return None


def _match_command_sequence(text: str) -> list[dict[str, Any]] | None:
    """Match a whole short utterance or a sequence of fully recognized clauses."""
    whole = _match_command_clause(text)
    if whole is not None:
        whole["matched_text"] = text.strip()
        return [whole]
    if len(re.sub(r"\s+", "", text)) > 80:
        return None
    clauses = [part.strip() for part in _COMMAND_SEPARATOR.split(text) if part.strip()]
    if not 2 <= len(clauses) <= 4:
        return None
    matches = [_match_command_clause(clause) for clause in clauses]
    if not all(match is not None for match in matches):
        return None
    for clause, match in zip(clauses, matches):
        match["matched_text"] = clause
    return matches


def _speaker_relation(left: str | None, right: str | None) -> str:
    if left is None or right is None:
        return "unknown"
    left_chunk = left.partition(":")[0] if ":" in left else None
    right_chunk = right.partition(":")[0] if ":" in right else None
    if left_chunk is not None and right_chunk is not None and left_chunk != right_chunk:
        # Per-chunk diarization labels have unrelated local namespaces.
        return "unknown_chunk_boundary"
    return "same" if left == right else "different"


def _validate_transcript(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    segments = transcript.get("segments")
    if not isinstance(segments, list):
        raise ValueError("transcript.segments must be a list")
    duration = transcript.get("audio_duration_ms")
    if duration is not None and (not isinstance(duration, int) or duration < 0):
        raise ValueError("audio_duration_ms must be a non-negative integer or null")

    seen_ids: set[Any] = set()
    previous_start = -1
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ValueError(f"segments[{index}] must be an object")
        for key in ("id", "start_ms", "end_ms", "text"):
            if key not in segment:
                raise ValueError(f"segments[{index}] is missing {key}")
        segment_id = segment["id"]
        try:
            if segment_id in seen_ids:
                raise ValueError(f"duplicate segment id: {segment_id!r}")
            seen_ids.add(segment_id)
        except TypeError as exc:
            raise ValueError(f"segments[{index}].id must be a scalar") from exc
        start, end = segment["start_ms"], segment["end_ms"]
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError(f"segments[{index}] timestamps must be integer milliseconds")
        if start < 0 or end < start or (duration is not None and end > duration):
            raise ValueError(f"segments[{index}] has invalid timestamps")
        if start < previous_start:
            raise ValueError("segments must be ordered by start_ms")
        previous_start = start
        if not isinstance(segment["text"], str):
            raise ValueError(f"segments[{index}].text must be a string")
        speaker = segment.get("speaker")
        if speaker is not None and not isinstance(speaker, str):
            raise ValueError(f"segments[{index}].speaker must be a string or null")
    return segments


def parse_transcript(transcript: dict[str, Any]) -> dict[str, Any]:
    """Return review-only game structure; speaker clusters never become seats."""
    if not isinstance(transcript, dict):
        raise ValueError("transcript must be an object")
    segments = _validate_transcript(transcript)
    stage = "unknown"
    day_number: int | None = None
    current_player: int | None = None
    instruction: dict[str, Any] | None = None
    player_speaker_candidate: str | None = None
    last_turn_speaker: str | None = None
    turn_blocked = False
    output: list[dict[str, Any]] = []

    def reset_turn() -> None:
        nonlocal current_player, instruction, player_speaker_candidate, last_turn_speaker, turn_blocked
        current_player = None
        instruction = None
        player_speaker_candidate = None
        last_turn_speaker = None
        turn_blocked = False

    def add_item(item: dict[str, Any]) -> None:
        # Adjacent ASR fragments with identical candidate context form one review unit.
        if output:
            previous = output[-1]
            mergeable = previous["speech_type"] not in {
                "judge_instruction_candidate",
                "stage_change_candidate",
                "game_end_candidate",
                "turn_end_candidate",
                "compound_instruction_candidate",
            } and item["speech_type"] not in {
                "judge_instruction_candidate",
                "stage_change_candidate",
                "game_end_candidate",
                "turn_end_candidate",
                "compound_instruction_candidate",
            }
            same_context = mergeable and all(
                previous[key] == item[key]
                for key in (
                    "player_number",
                    "pending_player_number_candidate",
                    "player_speaker_candidate",
                    "stage",
                    "day_number",
                    "speech_type",
                    "status",
                    "speaker_cluster_id",
                    "instruction_evidence",
                )
            )
            if same_context:
                previous["source_segment_ids"].extend(item["source_segment_ids"])
                previous["end_ms"] = max(previous["end_ms"], item["end_ms"])
                previous["text"] += item["text"]
                previous["evidence"].extend(item["evidence"])
                previous["review_reasons"] = sorted(
                    set(previous["review_reasons"]) | set(item["review_reasons"])
                )
                return
        output.append(item)

    for source_segment in segments:
        segment_id = source_segment["id"]
        text = source_segment["text"].strip()
        start_ms, end_ms = source_segment["start_ms"], source_segment["end_ms"]
        speaker = source_segment.get("speaker")
        command_sequence = _match_command_sequence(text)

        if command_sequence is not None:
            command_evidence: list[dict[str, Any]] = []
            review_reasons: set[str] = set()
            for command in command_sequence:
                applied = True
                event: dict[str, Any] = {
                    "source_segment_ids": [segment_id],
                    "matched_text": command.get("matched_text", text),
                    "applied": True,
                }
                if command["kind"] == "stage":
                    candidate_stage = command["candidate_stage"]
                    explicit_day = command["explicit_day_number"]
                    if stage == "ended" and candidate_stage != "opening":
                        applied = False
                        event["kind"] = "post_game_stage_cue_ignored"
                        event["candidate_stage"] = candidate_stage
                        review_reasons.add("post_game_control_ignored")
                    else:
                        stage = candidate_stage
                        reset_turn()
                        if stage in {"opening", "night"}:
                            day_number = None
                        elif explicit_day is not None:
                            day_number = explicit_day
                        event["kind"] = "stage_cue_match"
                        event["candidate_stage"] = candidate_stage
                        event["explicit_day_number"] = explicit_day
                        review_reasons.update({"stage_cue_requires_review", "judge_voice_unverified"})
                elif command["kind"] == "instruction":
                    target = command["target_player_number"]
                    instruction_kind = command["instruction_kind"]
                    if stage == "ended":
                        applied = False
                        event["kind"] = "post_game_player_instruction_ignored"
                        event["target_player_number"] = target
                        event["instruction_kind"] = instruction_kind
                        review_reasons.add("post_game_control_ignored")
                    else:
                        if instruction_kind == "last_words":
                            stage = "last_words"
                        current_player = target
                        instruction = {
                            "source_segment_ids": [segment_id],
                            "target_player_number": target,
                            "speaker_cluster_id": speaker,
                            "matched_text": command.get("matched_text", text),
                            "kind": instruction_kind,
                        }
                        player_speaker_candidate = None
                        last_turn_speaker = None
                        turn_blocked = False
                        event["kind"] = "player_instruction_match"
                        event["target_player_number"] = target
                        event["instruction_kind"] = instruction_kind
                        review_reasons.add("judge_voice_unverified")
                else:  # explicit player turn-end command
                    target = command["target_player_number"]
                    if stage == "ended":
                        applied = False
                        event["kind"] = "post_game_turn_end_ignored"
                        review_reasons.add("post_game_control_ignored")
                    else:
                        event["kind"] = "player_turn_end_match"
                        event["target_player_number"] = target
                        event["matches_pending_player"] = current_player == target
                        reset_turn()
                        review_reasons.add("turn_end_cue_requires_review")
                event["applied"] = applied
                command_evidence.append(event)

            command_evidence.append(
                {"kind": "asr_segment", "source_segment_ids": [segment_id], "text": text}
            )
            if len(command_sequence) > 1:
                speech_type = "compound_instruction_candidate"
            elif command_sequence[0]["kind"] == "instruction":
                speech_type = "judge_instruction_candidate"
            elif command_sequence[0].get("candidate_stage") == "ended":
                speech_type = "game_end_candidate"
            elif command_sequence[0]["kind"] == "turn_end":
                speech_type = "turn_end_candidate"
            else:
                speech_type = "stage_change_candidate"
            add_item(
                {
                    "source_segment_ids": [segment_id],
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "text": text,
                    "speaker_cluster_id": speaker,
                    "player_number": None,
                    "pending_player_number_candidate": current_player,
                    "player_speaker_candidate": player_speaker_candidate,
                    "stage": stage,
                    "day_number": day_number,
                    "speech_type": speech_type,
                    "status": "needs_review",
                    "review_reasons": sorted(review_reasons or {"command_candidate_requires_review"}),
                    "instruction_evidence": None,
                    "evidence": command_evidence,
                }
            )
            continue

        player_number: int | None = None
        pending_player_number: int | None = current_player
        status = "unknown"
        speech_type = "unassigned_speech"
        reasons: list[str] = []
        evidence: list[dict[str, Any]] = []
        instruction_evidence = instruction
        speaker_relation = "unknown"
        speaker_change_evidence: dict[str, Any] | None = None
        voice_candidate_evidence: dict[str, Any] | None = None

        if stage == "ended":
            reasons.extend(["no_explicit_player_instruction", "post_game_content_unassigned"])
            pending_player_number = None
        elif (current_player is not None and instruction is not None
              and player_speaker_candidate is None
              and _speaker_relation(instruction.get("speaker_cluster_id"), speaker) == "same"):
            reasons.append("judge_continuation_before_player_voice_unverified")
        elif current_player is not None and turn_blocked:
            reasons.append("speaker_changed_without_instruction")
        elif current_player is not None:
            if speaker is not None and player_speaker_candidate is None:
                player_speaker_candidate = speaker
                last_turn_speaker = speaker
                voice_candidate_evidence = {
                    "kind": "player_voice_candidate",
                    "source_segment_ids": [segment_id],
                    "speaker_cluster_id": speaker,
                    "for_player_number_candidate": current_player,
                    "verified": False,
                }
            elif speaker is not None and last_turn_speaker is not None:
                speaker_relation = _speaker_relation(last_turn_speaker, speaker)
                if speaker_relation == "different":
                    turn_blocked = True
                    speaker_change_evidence = {
                        "kind": "speaker_changed_without_instruction",
                        "source_segment_ids": [segment_id],
                        "previous_speaker_cluster_id": last_turn_speaker,
                        "current_speaker_cluster_id": speaker,
                        "for_player_number_candidate": current_player,
                    }
                else:
                    if speaker_relation == "unknown_chunk_boundary":
                        reasons.append("speaker_chunk_boundary")
                    last_turn_speaker = speaker
            elif speaker is not None:
                last_turn_speaker = speaker

            if turn_blocked:
                player_number = None
                status = "unknown"
                speech_type = "unassigned_speech"
                reasons.append("speaker_changed_without_instruction")
            else:
                player_number = current_player
                status = "needs_review"
                speech_type = "player_speech_candidate"
                reasons.extend(["judge_voice_unverified", "speaker_cluster_is_not_seat_identity"])
                if speaker is None:
                    reasons.append("speaker_cluster_missing")
                if speaker_relation == "unknown_chunk_boundary":
                    reasons.append("speaker_chunk_boundary")
                if instruction is not None:
                    instruction_relation = _speaker_relation(instruction.get("speaker_cluster_id"), speaker)
                    if instruction_relation == "same":
                        reasons.append("speech_shares_instruction_speaker_cluster")
                    elif instruction_relation == "different":
                        reasons.append("instruction_speaker_cluster_differs")
                    elif instruction_relation == "unknown_chunk_boundary":
                        reasons.append("instruction_speaker_chunk_boundary")
        else:
            reasons.append("no_explicit_player_instruction")

        if instruction_evidence is not None and stage != "ended":
            evidence.append(
                {
                    "kind": "player_instruction_context",
                    "source_segment_ids": instruction_evidence["source_segment_ids"],
                    "target_player_number": instruction_evidence["target_player_number"],
                    "matched_text": instruction_evidence["matched_text"],
                    "instruction_speaker_cluster_id": instruction_evidence["speaker_cluster_id"],
                    "speech_speaker_cluster_id": speaker,
                    "speaker_cluster_relation": _speaker_relation(
                        instruction_evidence["speaker_cluster_id"], speaker
                    ),
                    "player_speaker_candidate": player_speaker_candidate,
                    "candidate_status": status,
                }
            )
        if voice_candidate_evidence is not None:
            evidence.append(voice_candidate_evidence)
        if speaker_change_evidence is not None:
            evidence.append(speaker_change_evidence)
        evidence.append({"kind": "asr_segment", "source_segment_ids": [segment_id], "text": text})

        add_item(
            {
                "source_segment_ids": [segment_id],
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": text,
                "speaker_cluster_id": speaker,
                "player_number": player_number,
                "pending_player_number_candidate": pending_player_number,
                "player_speaker_candidate": player_speaker_candidate,
                "stage": stage,
                "day_number": day_number,
                "speech_type": speech_type,
                "status": status,
                "review_reasons": sorted(set(reasons)),
                "instruction_evidence": instruction_evidence,
                "evidence": evidence,
            }
        )

    return {
        "schema_version": 1,
        "source": transcript.get("source"),
        "audio_duration_ms": transcript.get("audio_duration_ms"),
        "transcript_status": transcript.get("status"),
        "status": "candidate_unverified",
        "verified": False,
        "judge_speaker_verified": False,
        "judge_speakers_candidate": transcript.get("judge_speakers", []),
        "day_number": None if not output else output[-1]["day_number"],
        "segments": output,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="JSON transcript with timed segments")
    parser.add_argument("--out", type=Path, required=True, help="candidate JSON output path")
    args = parser.parse_args()
    transcript = json.loads(args.input.read_text(encoding="utf-8"))
    candidate = parse_transcript(transcript)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
