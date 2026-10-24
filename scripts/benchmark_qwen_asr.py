"""Historical Qwen benchmark, with saved results retained for comparison.

Its weights and dedicated environment were removed on 2026-10-22 after model
selection. Reinstall them before attempting a fresh run; retained Paraformer
and Nano workflows do not import this module.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_REPO = "Qwen/Qwen3-ASR-0.6B"
MODEL_REVISION = "5eb144179a02acc5e5ba31e748d22b0cf3e303b0"
MODEL_WEIGHT_SHA256 = "79d6cbd4c98c7bbffe9db2edac07f56cd6637d0d5944b27f6c2b8353840323ea"
MAX_NEW_TOKENS = 1024


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed-as-distribution (loaded from local cache)"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "outputs/asr_model_benchmark_20261022/corpus.json")
    parser.add_argument("--hotwords", type=Path, default=ROOT / "outputs/asr_model_benchmark_20261022/benchmark_hotwords.txt")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, default=ROOT / ".models/qwen3-asr-0.6b")
    parser.add_argument("--limit", type=int, help="Run only the first N clips; use a separate --out for smoke runs.")
    args = parser.parse_args()

    os.environ.setdefault("HF_HOME", str(ROOT / ".cache/huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    import numpy as np
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ASRModel

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the Qwen benchmark; refusing to silently switch devices")
    if not args.model_path.is_dir():
        raise FileNotFoundError(f"Model snapshot missing: {args.model_path}")

    corpus_bytes = args.corpus.read_bytes()
    corpus = json.loads(corpus_bytes)
    hotword_bytes = args.hotwords.read_bytes()
    if hotword_bytes.startswith(b"\xef\xbb\xbf"):
        raise ValueError("The hotword file must be UTF-8 without a BOM")
    words = hotword_bytes.decode("utf-8").split()
    if len(words) != 40 or len(set(words)) != 40:
        raise ValueError(f"Expected 40 unique context words; got {len(words)} words / {len(set(words))} unique")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be >= 1")
    clips = corpus["clips"][:args.limit] if args.limit is not None else corpus["clips"]
    if not clips:
        raise ValueError("Corpus contains no clips")

    manifest_path = ROOT / "outputs/asr_model_benchmark_20261022/qwen_setup/model_download_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("revision") != MODEL_REVISION:
        raise RuntimeError(f"Downloaded model revision mismatch: {manifest.get('revision')}")
    actual_weight_hash = next(item["sha256"] for item in manifest["files"] if item["file"] == "model.safetensors")
    if actual_weight_hash != MODEL_WEIGHT_SHA256:
        raise RuntimeError(f"Downloaded model SHA-256 mismatch: {actual_weight_hash}")
    compatibility_path = ROOT / "outputs/asr_model_benchmark_20261022/qwen_setup/compatibility.json"
    compatibility_record = json.loads(compatibility_path.read_text(encoding="utf-8"))

    hotword_context = " ".join(words)
    generation_config = json.loads((args.model_path / "generation_config.json").read_text(encoding="utf-8"))
    config = {
        "engine": "Qwen3-ASR Transformers backend",
        "model": MODEL_REPO,
        "revision": MODEL_REVISION,
        "model_path": args.model_path.resolve().relative_to(ROOT).as_posix(),
        "model_file": "model.safetensors",
        "model_sha256": MODEL_WEIGHT_SHA256,
        "corpus_sha256": sha256_bytes(corpus_bytes),
        "device": torch.cuda.get_device_name(0),
        "dtype": "float16",
        "batch_size": 1,
        "language": "Chinese",
        "forced_aligner": None,
        "max_new_tokens": MAX_NEW_TOKENS,
        "generation_config": generation_config,
        "conditions": ["plain", "hint40"],
        "context_word_count": len(words),
        "context_words": words,
        "hotwords_sha256": sha256_bytes(hotword_bytes),
        "hotwords_encoding": "UTF-8 without BOM",
        "context_passing": "space-joined context string to Qwen3ASRModel.transcribe(context=...)",
        "compatibility": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "transformers": package_version("transformers"),
            "qwen-asr": package_version("qwen-asr"),
            "accelerate": package_version("accelerate"),
            "numpy": package_version("numpy"),
            "librosa": package_version("librosa"),
            "soundfile": package_version("soundfile"),
            "torch_source": str(torch.__file__),
            "torch_site_packages_reused_from": "D:/miniconda/miniconda-version/pkgs/pytorch-2.5.1-py3.9_cuda11.8_cudnn9_0",
            "shim": compatibility_record,
        },
        "run_clip_ids": [clip["id"] for clip in clips],
    }

    config_path = args.out / "config.json"
    if config_path.exists() and json.loads(config_path.read_text(encoding="utf-8")) != config:
        raise RuntimeError("Benchmark output configuration differs; choose a new --out directory")
    write_json(config_path, config)

    torch.set_num_threads(4)
    print(f"Loading {MODEL_REPO}@{MODEL_REVISION} on {config['device']}", flush=True)
    load_started = time.perf_counter()
    model = Qwen3ASRModel.from_pretrained(
        str(args.model_path.resolve()),
        dtype=torch.float16,
        device_map="cuda:0",
        max_inference_batch_size=1,
        max_new_tokens=MAX_NEW_TOKENS,
        local_files_only=True,
    )
    load_seconds = time.perf_counter() - load_started
    write_json(args.out / "runtime.json", {"model_load_seconds": load_seconds})
    print(f"Loaded in {load_seconds:.2f}s; generating {len(clips)} clips x 2 conditions", flush=True)

    original_generate = model.model.generate
    generation_stats = []

    def tracked_generate(*positional, **kwargs):
        output = original_generate(*positional, **kwargs)
        input_ids = kwargs.get("input_ids")
        if input_ids is None and positional:
            input_ids = positional[0]
        if input_ids is not None:
            max_tokens = int(kwargs.get("max_new_tokens", MAX_NEW_TOKENS))
            sequences = getattr(output, "sequences", output)
            generated = int(sequences.shape[-1] - input_ids.shape[-1])
            generation_stats.append({"generated_tokens": generated, "max_new_tokens": max_tokens, "truncated": generated >= max_tokens})
        return output

    model.model.generate = tracked_generate
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)

    condition_contexts = (("plain", ""), ("hint40", hotword_context))
    expected_outputs = len(clips) * len(condition_contexts)
    complete_count = 0
    failed_count = 0

    for condition, context in condition_contexts:
        for index, clip in enumerate(clips, 1):
            output_path = args.out / condition / (clip["id"] + ".json")
            if output_path.exists():
                previous = json.loads(output_path.read_text(encoding="utf-8"))
                if previous.get("status") == "complete":
                    complete_count += 1
                    continue

            audio_path = ROOT / clip["audio_file"]
            waveform, sample_rate = sf.read(str(audio_path), dtype="float32")
            if sample_rate != 16000 or waveform.ndim != 1:
                raise ValueError(f"Expected 16 kHz mono WAV for {clip['id']}; got {sample_rate} Hz, shape={waveform.shape}")

            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            generation_stats.clear()
            started = time.perf_counter()
            try:
                result = model.transcribe(
                    audio=(waveform, sample_rate),
                    context=context,
                    language="Chinese",
                    return_time_stamps=False,
                )[0]
                torch.cuda.synchronize()
                seconds = time.perf_counter() - started
                gen = generation_stats[-1] if generation_stats else None
                truncated = bool(gen and gen["truncated"])
                record = {
                    "id": clip["id"],
                    "model": "qwen",
                    "model_revision": MODEL_REVISION,
                    "model_sha256": MODEL_WEIGHT_SHA256,
                    "condition": condition,
                    "bvid": clip.get("bvid"),
                    "start_ms": clip.get("start_ms"),
                    "end_ms": clip.get("end_ms"),
                    "audio_file": clip["audio_file"],
                    "text": result.text,
                    "language": result.language,
                    "seconds": seconds,
                    "duration_seconds": len(waveform) / sample_rate,
                    "peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
                    "max_new_tokens": MAX_NEW_TOKENS,
                    "generated_tokens": gen["generated_tokens"] if gen else None,
                    "truncated": truncated,
                    "status": "complete",
                }
                write_json(output_path, record)
                complete_count += 1
                print(f"{condition} {index}/{len(clips)} {clip['id']} {seconds:.2f}s tokens={record['generated_tokens']} truncated={truncated} {result.text[:100]}", flush=True)
            except Exception as error:
                torch.cuda.synchronize()
                seconds = time.perf_counter() - started
                record = {
                    "id": clip["id"],
                    "model": "qwen",
                    "model_revision": MODEL_REVISION,
                    "model_sha256": MODEL_WEIGHT_SHA256,
                    "condition": condition,
                    "bvid": clip.get("bvid"),
                    "audio_file": clip["audio_file"],
                    "text": "",
                    "seconds": seconds,
                    "peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
                    "max_new_tokens": MAX_NEW_TOKENS,
                    "generated_tokens": generation_stats[-1]["generated_tokens"] if generation_stats else None,
                    "truncated": bool(generation_stats and generation_stats[-1]["truncated"]),
                    "status": "error",
                    "error": f"{type(error).__name__}: {error}",
                }
                write_json(output_path, record)
                failed_count += 1
                print(f"ERROR {condition} {clip['id']}: {record['error']}", file=sys.stderr, flush=True)

    completion = {
        "completed": failed_count == 0 and complete_count == expected_outputs,
        "expected_outputs": expected_outputs,
        "complete_outputs": complete_count,
        "failed_outputs": failed_count,
        "conditions": [condition for condition, _ in condition_contexts],
        "clips_per_condition": len(clips),
        "model_load_seconds": load_seconds,
        "truncated_outputs": sum(
            1
            for condition, _ in condition_contexts
            for clip in clips
            if (args.out / condition / (clip["id"] + ".json")).exists()
            and json.loads((args.out / condition / (clip["id"] + ".json")).read_text(encoding="utf-8")).get("truncated")
        ),
    }
    write_json(args.out / "completion.json", completion)
    print(json.dumps(completion, ensure_ascii=False), flush=True)
    if failed_count:
        raise SystemExit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
