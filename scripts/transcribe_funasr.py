"""Transcribe one local recording with Paraformer, VAD, punctuation and CAM++.

Raw model outputs are checkpointed separately from normalized sentence records.
Chunks meet in VAD gaps, so no voiced interval is deliberately cut or duplicated.
Anonymous speaker labels are scoped to each chunk, never to a player's seat.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = {"asr": "paraformer-zh", "vad": "fsmn-vad", "punctuation": "ct-punc", "speaker": "cam++"}
MODEL_IDS = {
    "asr": "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "punctuation": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
    "speaker": "iic/speech_campplus_sv_zh-cn_16k-common",
}


def model_location(kind):
    snapshot = ROOT / ".models/modelscope/models" / MODEL_IDS[kind].replace("/", "--") / "snapshots/master"
    return str(snapshot) if snapshot.exists() else MODEL_IDS[kind]


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    default=lambda x: x.tolist()) + "\n", encoding="utf-8")
    temporary.replace(path)


def clock(milliseconds, srt=False):
    seconds, ms = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}{',' if srt else '.'}{ms:03}"


def chunk_plan(vad, duration_ms, target_ms):
    """Meet only inside VAD silence; long uninterrupted speech stays together."""
    if target_ms <= 0:
        raise ValueError("chunk duration must be positive")
    candidates = [(a[1] + b[0]) // 2 for a, b in zip(vad, vad[1:])
                  if b[0] - a[1] >= 200]
    boundaries = [0]
    for boundary in candidates:
        if boundary - boundaries[-1] >= target_ms:
            boundaries.append(boundary)
    if boundaries[-1] != duration_ms:
        boundaries.append(duration_ms)
    return [[a, b] for a, b in zip(boundaries, boundaries[1:])]


def validate_plan(plan, digest, duration_ms):
    """A resumed run must still cover the same complete recording exactly once."""
    if plan.get("audio_sha256") != digest or plan.get("audio_duration_ms") != duration_ms:
        raise ValueError("VAD plan belongs to a different audio recording")
    cursor = 0
    for start, end in plan.get("chunks", []):
        if type(start) is not int or type(end) is not int or start != cursor or not start < end <= duration_ms:
            raise ValueError("VAD chunks must cover the full audio without gaps or overlap")
        cursor = end
    if cursor != duration_ms or duration_ms <= 0:
        raise ValueError("VAD plan does not reach the end of the audio")


def decode_audio(path):
    import av
    import numpy as np

    frames = []
    with av.open(str(path)) as container:
        if any(stream.type == "video" for stream in container.streams):
            raise ValueError("输入必须是独立音轨")
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(stream):
            for item in resampler.resample(frame):
                frames.append(item.to_ndarray().reshape(-1))
        for item in resampler.resample(None):
            frames.append(item.to_ndarray().reshape(-1))
    return np.concatenate(frames).astype(np.float32) / 32768.0


def aligned_sentences(item):
    """Use untouched ASR token times, rather than FunASR's compacted VAD joins.

    FunASR 1.4.16 joins adjacent Chinese VAD strings without a space. Its
    legacy sentence splitter can then pair merged tokens with individual
    timestamps. The raw_text / timestamp pair still has the original alignment.
    The punctuation surface is accepted only when every ASR character agrees.
    """
    if "raw_text" not in item or "timestamp" not in item:
        return item.get("sentence_info", [])
    tokens = item["raw_text"].split()
    timestamps = item["timestamp"]
    if len(tokens) != len(timestamps):
        raise ValueError("ASR raw token / timestamp count mismatch")
    characters = []
    for token, timestamp in zip(tokens, timestamps):
        for character in token:
            characters.append((character.casefold(), timestamp))
    cursor = 0
    text = ""
    word_times = []
    sentences = []

    def finish():
        nonlocal text, word_times
        if not word_times:
            return
        a, b = int(word_times[0][0]), int(word_times[-1][1])
        weights = {}
        for original in item.get("sentence_info", []):
            spk = original.get("spk")
            if spk is not None:
                overlap = max(0, min(b, int(original["end"])) - max(a, int(original["start"])))
                weights[spk] = weights.get(spk, 0) + overlap
        spk = max(weights, key=weights.get) if weights and max(weights.values()) else None
        ambiguous = bool(spk is not None and weights[spk] < sum(weights.values()) * 0.6)
        if ambiguous:
            spk = None
        sentences.append({"text": text.strip(), "start": a, "end": b, "spk": spk,
                          "speaker_ambiguous": ambiguous, "alignment": "raw_token_timestamps"})
        text, word_times = "", []

    for character in item.get("text", ""):
        if cursor < len(characters) and character.casefold() == characters[cursor][0]:
            word_times.append(characters[cursor][1])
            cursor += 1
        elif not character.isspace() and not unicodedata.category(character).startswith("P"):
            raise ValueError(f"Punctuation surface changed ASR text at character {cursor}")
        text += character
        if character in "，,。.!！？?；;":
            finish()
    finish()
    if cursor != len(characters):
        raise ValueError("Punctuation surface omitted ASR tokens")
    return sentences


def normalize(raw, index, start_ms, end_ms):
    segments = []
    for item in raw:
        sentences = aligned_sentences(item)
        if item.get("text", "").strip() and not sentences:
            raise RuntimeError(f"chunk {index}: ASR text has no sentence timestamps")
        for sentence in sentences:
            text = sentence.get("text") or sentence.get("sentence", "")
            if not text.strip():
                continue
            a, b = int(sentence["start"]) + start_ms, int(sentence["end"]) + start_ms
            if not start_ms <= a < b <= end_ms + 100:
                raise ValueError(f"Invalid model timestamp in chunk {index}: {a}, {b}")
            b = min(b, end_ms)
            spk = sentence.get("spk")
            segments.append({"id": f"c{index:04}_s{len(segments) + 1:04}",
                             "start_ms": a, "end_ms": b, "text": text.strip(),
                             "speaker": f"chunk_{index:04}:speaker_{spk}" if spk is not None else None,
                             "chunk_index": index, "status": "machine_generated_unverified",
                             "alignment": sentence.get("alignment", "model_sentence_info"),
                             "speaker_attribution": "cam++_timeline_overlap" if spk is not None else "unassigned",
                             "speaker_ambiguous": sentence.get("speaker_ambiguous", False)})
    return sorted(segments, key=lambda s: (s["start_ms"], s["end_ms"]))


def export(result, out):
    save_json(out / "transcript.json", result)
    sentences = result["segments"]
    (out / "transcript.srt").write_text("\n".join(
        f"{i}\n{clock(s['start_ms'], True)} --> {clock(s['end_ms'], True)}\n{s['text']}\n"
        for i, s in enumerate(sentences, 1)), encoding="utf-8")
    speaker_note = ("speaker 是每块内的匿名声纹标签，不是座位号。" if result.get("config", {}).get("speakers", True)
                    else "本次仅转写全文和时间戳，未做说话人归属。")
    heading = (f"{result['source'].get('title', '')}\nFunASR 本地音频转写（未人工校对）\n"
               f"音频：{result['source']['audio_file']}\n"
               f"已处理完整音频：{result['full_audio_processed']}\n"
               f"{speaker_note}\n\n")
    (out / "transcript.阅读.txt").write_text(heading + "\n".join(
        f"[{clock(s['start_ms'])} — {clock(s['end_ms'])}] {s['text']}" for s in sentences) + "\n",
        encoding="utf-8")


def rebuild(out):
    """Rebuild exports from finished model checkpoints without loading models."""
    result = json.loads((out / "transcript.json").read_text(encoding="utf-8"))
    if not result.get("full_audio_processed"):
        raise ValueError("Wait until every ASR chunk is complete before rebuilding exports")
    result["segments"] = []
    for chunk in result["chunks"]:
        index = chunk["index"]
        checkpoint = json.loads((out / "raw" / f"chunk_{index:04}.json").read_text(encoding="utf-8"))
        if any(checkpoint[k] != chunk[k] for k in ["index", "start_ms", "end_ms"]):
            raise ValueError("Checkpoint does not match the completed transcript")
        result["segments"].extend(normalize(checkpoint["result"], index, chunk["start_ms"], chunk["end_ms"]))
    result["normalization"] = {
        "version": 2, "text": "unaltered_punctuation_surface",
        "timestamps": "raw_text_tokens_paired_with_raw_timestamp_array",
        "speaker": "overlap_with_original_cam++_timeline_unverified",
        "reason": "Avoid compacted Chinese VAD-token joins in FunASR sentence_info",
    }
    export(result, out)
    print(f"Rebuilt {len(result['segments'])} aligned sentences from saved model outputs", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--chunk-seconds", type=int, default=600)
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--no-speakers", action="store_true")
    parser.add_argument("--hotwords", type=Path, default=ROOT / "config/asr_hotwords.txt")
    parser.add_argument("--rebuild-only", action="store_true", help="Rebuild finished checkpoints; no ASR rerun")
    args = parser.parse_args()
    if args.rebuild_only:
        rebuild(args.out)
        return
    os.environ.setdefault("MODELSCOPE_CACHE", str(ROOT / ".models/modelscope"))
    os.environ.setdefault("HF_HOME", str(ROOT / ".cache/huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("NUMBA_CACHE_DIR", str(ROOT / ".cache/numba"))
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    import torch
    from funasr import AutoModel

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; do not silently change the trial's runtime")
    torch.set_num_threads(4)
    hasher = hashlib.sha256()
    with args.audio.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    digest = hasher.hexdigest()
    source = {"audio_file": args.audio.as_posix(), "audio_sha256": digest}
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if manifest["audio"]["sha256"] != digest:
            raise ValueError("Audio SHA-256 does not match the source manifest")
        source.update({k: manifest[k] for k in ["bvid", "cid", "page", "title", "url"]})
        source["manifest"] = args.manifest.as_posix()
    print("Decoding independent audio track to mono 16 kHz float PCM", flush=True)
    waveform = decode_audio(args.audio)
    duration_ms = round(len(waveform) / 16)
    hotwords = " ".join(args.hotwords.read_text(encoding="utf-8").split()) if args.hotwords else ""
    config = {"models": MODEL_IDS, "device": args.device, "speakers": not args.no_speakers,
              "batch_size_s": 60, "chunk_seconds": args.chunk_seconds,
              "audio_sha256": digest, "audio_duration_ms": duration_ms, "hotwords": hotwords,
              "packages": {p: importlib.metadata.version(p) for p in
                           ["funasr", "torch", "torchaudio", "modelscope", "av", "numpy"]}}
    config_file = args.out / "config.json"
    if config_file.exists() and json.loads(config_file.read_text(encoding="utf-8")) != config:
        raise ValueError("Output belongs to a different run/configuration; use a new directory")
    save_json(config_file, config)
    print(f"Loading FunASR pipeline on {args.device}; duration={duration_ms / 1000:.3f}s", flush=True)
    options = dict(model=model_location("asr"), vad_model=model_location("vad"),
                   punc_model=model_location("punctuation"),
                   vad_kwargs={"device": "cpu", "max_single_segment_time": 30000},
                   punc_kwargs={"device": "cpu"}, device=args.device,
                   disable_update=True, disable_pbar=True, ncpu=4)
    if not args.no_speakers:
        options.update(spk_model=model_location("speaker"), spk_kwargs={"device": "cpu"})
    model = AutoModel(**options)
    plan_file = args.out / "vad_plan.json"
    if plan_file.exists():
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    else:
        print("Detecting speech to place chunk boundaries inside silence", flush=True)
        vad_start = time.perf_counter()
        vad = model.inference(input=waveform, model=model.vad_model, kwargs=model.vad_kwargs,
                              disable_pbar=True)[0]["value"]
        plan = {"audio_sha256": digest, "audio_duration_ms": duration_ms,
                "vad_processing_seconds": time.perf_counter() - vad_start, "vad_segments": vad,
                "chunks": chunk_plan(vad, duration_ms, args.chunk_seconds * 1000),
                "boundary_policy": "midpoint_of_vad_silence_at_least_200ms_no_overlap"}
        save_json(plan_file, plan)
    validate_plan(plan, digest, duration_ms)
    result = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "source": source, "audio_duration_ms": duration_ms, "engine": "FunASR",
              "config": config, "status": "machine_generated_unverified",
              "speaker_identity_verified": False, "judge_speakers": [],
              "full_audio_processed": False, "segments": [], "chunks": []}
    for index, (start_ms, end_ms) in enumerate(plan["chunks"], 1):
        raw_path = args.out / "raw" / f"chunk_{index:04}.json"
        if raw_path.exists():
            checkpoint = json.loads(raw_path.read_text(encoding="utf-8"))
            if any(checkpoint.get(k) != v for k, v in
                   {"index": index, "start_ms": start_ms, "end_ms": end_ms}.items()):
                raise ValueError("Checkpoint does not match this audio's VAD plan")
        else:
            print(f"ASR chunk {index}/{len(plan['chunks'])}: {clock(start_ms)} — {clock(end_ms)}", flush=True)
            chunk_start = time.perf_counter()
            raw = model.generate(input=waveform[start_ms * 16:end_ms * 16],
                                 batch_size_s=60, batch_size_threshold_s=30,
                                 sentence_timestamp=True, return_raw_text=True, hotword=hotwords,
                                 disable_pbar=True)
            checkpoint = {"index": index, "start_ms": start_ms, "end_ms": end_ms,
                          "processing_seconds": time.perf_counter() - chunk_start, "result": raw}
            save_json(raw_path, checkpoint)
        normalized = normalize(checkpoint["result"], index, start_ms, end_ms)
        result["segments"].extend(normalized)
        result["chunks"].append({k: v for k, v in checkpoint.items() if k != "result"})
        export(result, args.out)
        print(f"Checkpoint: {len(normalized)} sentences, {checkpoint['processing_seconds']:.1f}s", flush=True)
    result["full_audio_processed"] = True
    result["invocation_wall_seconds"] = time.perf_counter() - started
    result["asr_processing_seconds"] = sum(c["processing_seconds"] for c in result["chunks"])
    result["asr_rtf"] = result["asr_processing_seconds"] / (duration_ms / 1000)
    result["vad_processing_seconds"] = plan["vad_processing_seconds"]
    result["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated() if args.device == "cuda" else None
    export(result, args.out)
    print(f"COMPLETE: {len(result['segments'])} sentences; ASR RTF={result['asr_rtf']:.4f}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
