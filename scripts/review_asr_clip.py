"""Review one short audio window with the retained local Fun-ASR-Nano model."""
import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

from transcribe_funasr import ROOT, decode_audio, save_json

MODEL = ROOT / ".models/fun-asr-nano-2512"
REVISION = "272c57b82523ada6fd87095e955f8e29100979ab"


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="独立音轨或已经截取的 WAV")
    parser.add_argument("--start-ms", type=int, help="既有 ASR 解码时间线上的开始毫秒")
    parser.add_argument("--end-ms", type=int, help="结束毫秒；与 --start-ms 一起使用")
    parser.add_argument("--hotwords", type=Path, default=ROOT / "config/asr_review_hotwords.txt")
    parser.add_argument("--no-hotwords", action="store_true")
    parser.add_argument("--out", type=Path, required=True, help="新的输出目录，保存片段与未校对文字")
    args = parser.parse_args()
    if not args.audio.is_file():
        parser.error("输入音频不存在")
    if (args.start_ms is None) != (args.end_ms is None):
        parser.error("--start-ms 和 --end-ms 必须同时提供")
    if args.start_ms is not None and not 0 <= args.start_ms < args.end_ms <= args.start_ms + 30000:
        parser.error("复核窗口需大于 0 且不超过 30 秒")
    if args.out.exists() and (not args.out.is_dir() or any(args.out.iterdir())):
        parser.error("输出目录已有文件，请选择新的目录")
    if not (MODEL / "model.pt").is_file() or not (MODEL / "Qwen3-0.6B/config.json").is_file():
        parser.error("本地 Nano 权重或其必需的文本组件缺失")
    words = [] if args.no_hotwords else args.hotwords.read_text(encoding="utf-8-sig").split()
    if len(words) != len(set(words)) or len(words) > 50:
        parser.error("请提供不超过 50 个、无重复的精简术语；已有 343/261 词包不用于此入口")

    os.environ["HF_HOME"] = str(ROOT / ".cache/huggingface")
    os.environ["MODELSCOPE_CACHE"] = str(ROOT / ".models/modelscope")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["NUMBA_CACHE_DIR"] = str(ROOT / ".cache/numba")
    import numpy as np
    import soundfile as sf
    import torch
    from funasr import AutoModel

    if not torch.cuda.is_available():
        raise RuntimeError("此入口使用现有 CUDA 环境，请用 .venv-funasr39 执行")
    # Full decode preserves the same sample timeline as the production ASR,
    # including sources whose container PTS are discontinuous. No seek fallback.
    samples = decode_audio(args.audio)
    start = args.start_ms or 0
    end = args.end_ms if args.end_ms is not None else len(samples) // 16
    if not 0 <= start < end or end * 16 > len(samples) or end - start > 30000:
        parser.error("音频或窗口需在真实解码范围内，且不超过 30 秒")
    args.out.mkdir(parents=True, exist_ok=True)
    clip = args.out / "clip.wav"
    sf.write(str(clip), samples[start * 16:end * 16], 16000, subtype="PCM_16")
    del samples
    np.random.seed(0)
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.set_num_threads(4)
    print("加载本地 Nano，复核片段；首次加载可能需要约一分钟。", flush=True)
    loaded = time.perf_counter()
    model = AutoModel(model=str(MODEL), device="cuda:0", trust_remote_code=False,
                      disable_update=True, disable_pbar=True, ncpu=4)
    load_seconds = time.perf_counter() - loaded
    torch.cuda.synchronize()
    started = time.perf_counter()
    result = model.generate(input=str(clip.resolve()), hotwords=words, language="中文",
                            itn=False, batch_size=1, llm_dtype="bf16", max_length=512,
                            llm_kwargs={"do_sample": False, "num_beams": 1}, disable_pbar=True)
    torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - started
    text = "".join(item.get("text", "") for item in result)
    if not text.strip():
        raise RuntimeError("Nano 返回空文字；片段已保留，未生成完成记录")
    record = {"status": "machine_generated_unverified", "model": "FunAudioLLM/Fun-ASR-Nano-2512",
              "revision": REVISION, "source_audio": str(args.audio.resolve()),
              "source_audio_sha256": digest(args.audio), "clip_audio_sha256": digest(clip),
              "start_ms": start, "end_ms": end, "timeline": "production ASR decoded samples",
              "hotwords": words, "model_load_seconds": load_seconds,
              "inference_seconds": inference_seconds, "text": text, "raw_result": result,
              "word_timestamps": None, "speaker_identity_verified": False}
    save_json(args.out / "transcript.json", record)
    (args.out / "transcript.txt").write_text(text + "\n", encoding="utf-8")
    print(text, flush=True)
    print(f"已保存 {args.out}；这是待听核的复核稿，不覆盖原转写。", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
