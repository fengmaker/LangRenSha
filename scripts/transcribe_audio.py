"""Historical Whisper experiment; its dedicated environment/weights were removed.

Current ASR: transcribe_funasr.py. Nano clip review: review_asr_clip.py.
This source remains for provenance and its existing parser tests.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_clips(value: str, duration: float) -> list[tuple[float, float]]:
    if value == "full":
        return [(0, duration)]
    clips = []
    for pair in value.split(","):
        start, end = map(float, pair.split(":"))
        if not 0 <= start < end <= duration:
            raise ValueError(f"片段超出音频范围: {pair}")
        clips.append((start, end))
    return clips


def clock(seconds: float) -> str:
    total = round(seconds * 1000)
    hours, total = divmod(total, 3600000)
    minutes, total = divmod(total, 60000)
    secs, millis = divmod(total, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--model", default="base", help="多语言模型；不要使用 .en 模型")
    parser.add_argument("--clips", default="0:120", help="秒数起止如0:120,3756:3936，或full")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--prompt", default=None, help="可选术语提示；默认不加，避免静音段复述提示词")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    os.environ.setdefault("HF_HOME", str(root / ".cache" / "huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
    import av

    with av.open(str(args.audio)) as container:
        tracks = [{"type": s.type, "codec": s.codec_context.name} for s in container.streams]
    if any(track["type"] == "video" for track in tracks):
        raise ValueError("输入含视频轨，需先选取独立音频")
    print(json.dumps({"input_tracks": tracks, "model": args.model,
                      "device": "cpu", "compute_type": "int8"}, ensure_ascii=False), flush=True)
    waveform = decode_audio(str(args.audio), sampling_rate=16000)
    duration = len(waveform) / 16000
    clips = parse_clips(args.clips, duration)
    print(f"音频解码完成，时长 {duration:.2f} 秒；加载本地模型", flush=True)
    model = WhisperModel(args.model, device="cpu", compute_type="int8",
                         cpu_threads=args.threads, num_workers=1,
                         download_root=str(root / ".models"), local_files_only=args.offline)
    with args.audio.open("rb") as audio_input:
        audio_digest = hashlib.file_digest(audio_input, "sha256").hexdigest()
    result = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "audio_file": str(args.audio.as_posix()),
        "audio_sha256": audio_digest,
        "audio_duration_seconds": duration,
        "model": args.model, "engine": "faster-whisper", "language": "zh",
        "device": "cpu", "compute_type": "int8", "beam_size": 5,
        "initial_prompt": args.prompt,
        "status": "machine_generated_unverified", "speaker_identity_verified": False,
        "clips": clips, "segments": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for start, end in clips:
        data = waveform[int(start * 16000):int(end * 16000)]
        segments, _ = model.transcribe(data, language="zh", task="transcribe", beam_size=5,
                                      condition_on_previous_text=False, vad_filter=True,
                                      initial_prompt=args.prompt)
        for segment in segments:
            item = {"id": len(result["segments"]), "start": start + segment.start,
                    "end": start + segment.end, "text": segment.text,
                    "avg_logprob": segment.avg_logprob, "no_speech_prob": segment.no_speech_prob}
            result["segments"].append(item)
            print(f"[{item['start']:.1f}-{item['end']:.1f}] {item['text']}", flush=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    srt = []
    for index, item in enumerate(result["segments"], start=1):
        srt.append(f"{index}\n{clock(item['start'])} --> {clock(item['end'])}\n{item['text'].strip()}\n")
    args.out.with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")
    print(f"完成 {len(result['segments'])} 段机器转写，尚未人工核验；输出 {args.out}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
