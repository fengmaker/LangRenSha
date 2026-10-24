"""Prepare a small, independently reviewable ASR benchmark corpus.

This script only decodes existing source audio windows. It does not load or
invoke any ASR model. Clip boundaries come from existing timed transcripts.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import gc
from pathlib import Path
from typing import Any

import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "asr_model_benchmark_20261022"
CLIPS_DIR = OUTPUT_DIR / "clips"
CORPUS_PATH = OUTPUT_DIR / "corpus.json"
REVIEW_PATH = OUTPUT_DIR / "corpus_review.md"

SOURCE_INFO = {
    "BV1yt7v6QE3Q": {
        "audio": "data/raw/bilibili/BV1yt7v6QE3Q/p01/audio.m4a",
        "transcript": "data/transcripts/S22/BV1yt7v6QE3Q_p01_funasr/transcript.srt",
        "board": "机械狼通灵师",
        "title": "20260625 正赛 第四期 Day-3 第三局-机械狼通灵师",
    },
    "BV1dJ7R6fEUw": {
        "audio": "data/raw/bilibili/BV1dJ7R6fEUw/p01/audio.m4a",
        "transcript": "data/transcripts/S22/BV1dJ7R6fEUw_p01_funasr_full/transcript.srt",
        "board": "机械狼通灵师",
        "title": "20260603 正赛 第一期 Day-2 第三局-机械狼通灵师",
    },
    "BV1vH7R6tEQp": {
        "audio": "data/raw/bilibili/BV1vH7R6tEQp/p01/audio.m4a",
        "transcript": "data/transcripts/S22/BV1vH7R6tEQp_p01_funasr_full/transcript.srt",
        "board": "假面舞会",
        "title": "20260603 正赛 第一期 Day-2 第二局-假面舞会",
    },
}

# These are candidate windows chosen against existing timed SRT boundaries.
# Text is loaded from the SRT/platform subtitle at runtime and remains a
# comparison candidate, never an asserted ground-truth transcript.
CLIP_SPECS = [
    {"id": "std_recap_01", "bvid": "BV1yt7v6QE3Q", "start_ms": 2037210, "end_ms": 2061760, "category": "referee_final_recap"},
    {"id": "std_recap_02", "bvid": "BV1yt7v6QE3Q", "start_ms": 2061880, "end_ms": 2084010, "category": "referee_final_recap"},
    {"id": "std_flow_01", "bvid": "BV1yt7v6QE3Q", "start_ms": 1429720, "end_ms": 1449540, "category": "referee_flow"},
    {"id": "std_player_turn_01", "bvid": "BV1yt7v6QE3Q", "start_ms": 449770, "end_ms": 476810, "category": "player_speech"},
    {"id": "mech_flow_01", "bvid": "BV1dJ7R6fEUw", "start_ms": 441430, "end_ms": 464090, "category": "referee_flow"},
    {"id": "mech_player_01", "bvid": "BV1dJ7R6fEUw", "start_ms": 473730, "end_ms": 503080, "category": "player_speech"},
    {"id": "mech_player_02", "bvid": "BV1dJ7R6fEUw", "start_ms": 663770, "end_ms": 685860, "category": "player_speech"},
    {"id": "mech_player_03", "bvid": "BV1dJ7R6fEUw", "start_ms": 687340, "end_ms": 710640, "category": "player_speech"},
    {"id": "mask_fast_commentary_01", "bvid": "BV1vH7R6tEQp", "start_ms": 315440, "end_ms": 342670, "category": "fast_commentary"},
    {"id": "mask_flow_01", "bvid": "BV1vH7R6tEQp", "start_ms": 348340, "end_ms": 375840, "category": "referee_flow"},
    {"id": "mask_player_01", "bvid": "BV1vH7R6tEQp", "start_ms": 385880, "end_ms": 414010, "category": "player_speech"},
    {"id": "mask_player_02", "bvid": "BV1vH7R6tEQp", "start_ms": 419890, "end_ms": 447120, "category": "player_speech"},
    {"id": "mask_player_03", "bvid": "BV1vH7R6tEQp", "start_ms": 860170, "end_ms": 887240, "category": "player_speech"},
]

REFERENCE_STATUS = "candidate_machine_and_platform_text_only_not_human_verified"
SRT_TIME = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$")


def load_decode_audio():
    script = ROOT / "scripts" / "transcribe_funasr.py"
    spec = importlib.util.spec_from_file_location("transcribe_funasr_audio", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load existing audio decoder: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.decode_audio


def timestamp_ms(value: str) -> int:
    match = SRT_TIME.match(value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value!r}")
    hours, minutes, seconds, milliseconds = map(int, match.groups())
    return (((hours * 60 + minutes) * 60 + seconds) * 1000) + milliseconds


def read_srt(path: Path) -> list[tuple[int, int, str]]:
    cues: list[tuple[int, int, str]] = []
    for block in re.split(r"\r?\n\s*\r?\n", path.read_text(encoding="utf-8-sig").strip()):
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = (part.strip() for part in lines[1].split("-->", maxsplit=1))
        text = " ".join(line.strip() for line in lines[2:] if line.strip())
        if text:
            cues.append((timestamp_ms(start), timestamp_ms(end), text))
    if not cues:
        raise ValueError(f"No timed text cues in {path}")
    return cues


def text_in_window(cues: list[tuple[int, int, str]], start_ms: int, end_ms: int) -> str:
    parts = [text for start, end, text in cues if end > start_ms and start < end_ms]
    return " ".join(parts)


def platform_text_for(bvid: str, start_ms: int, end_ms: int) -> str | None:
    source_dir = ROOT / "data" / "raw" / "bilibili" / bvid / "p01"
    files = sorted(source_dir.glob("subtitle*.raw.json"), key=lambda p: ("subtitle.01." not in p.name, p.name))
    parts: list[str] = []
    for path in files:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        for cue in obj.get("body", []):
            try:
                cue_start = float(cue["from"]) * 1000
                cue_end = float(cue["to"]) * 1000
            except (KeyError, TypeError, ValueError):
                continue
            content = str(cue.get("content", "")).strip()
            if content and cue_end > start_ms and cue_start < end_ms:
                parts.append(content)
    return " ".join(parts) if parts else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def build_review(clips: list[dict[str, Any]], total_ms: int) -> str:
    category_labels = {
        "referee_final_recap": "法官最终复盘",
        "referee_flow": "流程口令与阶段提示",
        "player_speech": "玩家发言候选段",
        "fast_commentary": "解说快语速候选段",
    }
    rows = []
    for clip in clips:
        start = clip["start_ms"] / 1000
        end = clip["end_ms"] / 1000
        rows.append(
            f"| `{clip['id']}` | {clip['bvid']} | {category_labels[clip['category']]} | "
            f"{start:.3f}–{end:.3f} | {clip['duration_ms'] / 1000:.2f} |"
        )
    return f"""# 独立 ASR 测试语料候选集

本语料包含 **{len(clips)} 条**、合计 **{total_ms / 1000:.2f} 秒（{total_ms / 60000:.2f} 分钟）**。来源为标准样本 BV1yt7v6QE3Q、另一局机械狼通灵师 BV1dJ7R6fEUw，以及假面舞会 BV1vH7R6tEQp；三条均有现成的带时全文转写。每个来源由项目现有 `scripts/transcribe_funasr.py` 中纯音频函数 `decode_audio` 完整解码一次，再按原全轨 16 kHz 采样索引裁切；按来源处理后释放波形。该步骤未调用 ASR，也未使用 GPU。

`old_text` 取自已有 FunASR 带时转写，`platform_text` 取自可用的 Bilibili 字幕文件。两者都只是机器或平台候选稿，**都不是人工真值**；这批语料没有逐条人耳核验，不能据此报告人工参考准确率。JSON 中的文字只供离线对照；送入待测 ASR 时只给 WAV，不把 `old_text`、`platform_text` 或下方候选检查词提供给模型。

标准样本的最终复盘分成前后两段，覆盖从复盘开场、局势摘要到最终胜负结算的主要内容；两段之间保留转写中约120毫秒的间隔。流程片段覆盖开灯、随机点数、发言顺序、玩家呼叫和闭眼等候选术语。玩家片段依据现有句级时标选择完整短语边界；其中标准样本 `std_player_turn_01` 覆盖一段完整的转写轮次，其余仍是较长发言中的语义段候选，不宣称覆盖了说话者整轮发言。

| ID | 来源 | 类型 | 原音频时间（秒） | 时长（秒） |
|---|---|---|---:|---:|
{chr(10).join(rows)}

## 候选检查点

可在各模型输出中重点留意这些角色、座位或流程词的识别与一致性：**机械狼、通灵师、守卫、女巫、猎人、警徽、警徽流失、平安夜、上警、逆序发言、悍跳、金水**。这些词只是候选检查点，并不代表本语料给出了正确转写或对局事实。

## 文件核验

脚本为每条 WAV 写入 SHA-256、原音频 SHA-256、采样率、声道数和帧数。落盘核验要求每条均为 **16 kHz、单声道、PCM 16-bit WAV**，且帧数与毫秒区间相符；总时长按 WAV 帧数统计。原音频和裁切音频的 SHA-256 均记录在 `corpus.json`。切点依据现有带时转写定位，仍是待人工复核的候选边界。
"""


def main() -> None:
    if len(CLIP_SPECS) < 12 or len(CLIP_SPECS) > 16:
        raise ValueError("Expected 12–16 clips")
    ids = [spec["id"] for spec in CLIP_SPECS]
    if len(ids) != len(set(ids)):
        raise ValueError("Clip IDs must be unique")

    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    decode_audio = load_decode_audio()
    source_hashes: dict[str, str] = {}
    srt_cues: dict[str, list[tuple[int, int, str]]] = {}
    clips: list[dict[str, Any]] = []

    grouped_specs: dict[str, list[dict[str, Any]]] = {}
    for clip_spec in CLIP_SPECS:
        grouped_specs.setdefault(clip_spec["bvid"], []).append(clip_spec)

    for bvid, source_specs in grouped_specs.items():
        source_info = SOURCE_INFO[bvid]
        source_audio = ROOT / source_info["audio"]
        transcript = ROOT / source_info["transcript"]
        if not source_audio.is_file() or not transcript.is_file():
            raise FileNotFoundError(f"Missing source audio or timed transcript for {bvid}")
        if bvid not in srt_cues:
            srt_cues[bvid] = read_srt(transcript)
        if bvid not in source_hashes:
            source_hashes[bvid] = sha256_file(source_audio)
        waveform = decode_audio(source_audio)
        if waveform.ndim != 1:
            raise ValueError(f"Full-track decode must be mono for {bvid}: shape={waveform.shape}")
        for clip_spec in source_specs:
            start_ms = int(clip_spec["start_ms"])
            end_ms = int(clip_spec["end_ms"])
            duration_ms = end_ms - start_ms
            if start_ms < 0 or duration_ms <= 0 or duration_ms > 30_000:
                raise ValueError(f"Invalid clip range for {clip_spec['id']}: {start_ms}–{end_ms}")
            first_sample, last_sample = start_ms * 16, end_ms * 16
            if last_sample > len(waveform):
                raise ValueError(f"Clip extends past decoded full track: {clip_spec['id']}")
            old_text = text_in_window(srt_cues[bvid], start_ms, end_ms)
            if not old_text:
                raise ValueError(f"No timed transcript text overlaps {clip_spec['id']}")

            output_audio = CLIPS_DIR / f"{clip_spec['id']}.wav"
            samples = waveform[first_sample:last_sample]
            expected_frames = duration_ms * 16
            if len(samples) != expected_frames:
                raise ValueError(f"Decoded sample count mismatch for {clip_spec['id']}: {len(samples)} != {expected_frames}")
            sf.write(str(output_audio), samples, 16000, subtype="PCM_16")
            info = sf.info(str(output_audio))
            if (info.samplerate, info.channels, info.frames, info.subtype) != (16000, 1, expected_frames, "PCM_16"):
                raise ValueError(f"WAV format verification failed for {clip_spec['id']}: {info}")

            clips.append({
                "id": clip_spec["id"],
                "audio_file": relative(output_audio),
                "bvid": bvid,
                "source_audio_file": source_info["audio"],
                "start_ms": start_ms,
                "end_ms": end_ms,
                "category": clip_spec["category"],
                "board": source_info["board"],
                "old_text": old_text,
                "platform_text": platform_text_for(bvid, start_ms, end_ms),
                "reference_status": REFERENCE_STATUS,
                "decoder": "full_track_decode_then_sample_crop",
                "source_audio_sha256": source_hashes[bvid],
                "clip_audio_sha256": sha256_file(output_audio),
                "sample_rate_hz": info.samplerate,
                "channels": info.channels,
                "frames": info.frames,
                "duration_ms": duration_ms,
            })
        del waveform
        gc.collect()

    total_ms = sum(clip["duration_ms"] for clip in clips)
    if not 300_000 <= total_ms <= 480_000:
        raise ValueError(f"Corpus duration {total_ms}ms is outside 5–8 minutes")
    corpus = {"schema_version": 1, "clips": clips}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CORPUS_PATH.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REVIEW_PATH.write_text(build_review(clips, total_ms), encoding="utf-8")
    print(json.dumps({
        "corpus": relative(CORPUS_PATH),
        "review": relative(REVIEW_PATH),
        "clip_count": len(clips),
        "total_ms": total_ms,
        "sources": sorted(source_hashes),
        "all_wavs_verified_pcm16_mono_16khz": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
