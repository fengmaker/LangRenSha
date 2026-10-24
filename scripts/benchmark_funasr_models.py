"""Run Paraformer/Nano on the fixed local ASR comparison corpus."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("paraformer", "nano"), required=True)
    parser.add_argument("--corpus", type=Path, default=ROOT / "outputs/asr_model_benchmark_20261022/corpus.json")
    parser.add_argument("--hotwords", type=Path, default=ROOT / "outputs/asr_model_benchmark_20261022/benchmark_hotwords.txt")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    os.environ["HF_HOME"] = str(ROOT / ".cache/huggingface")
    os.environ["MODELSCOPE_CACHE"] = str(ROOT / ".models/modelscope")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["NUMBA_CACHE_DIR"] = str(ROOT / ".cache/numba")
    import numpy as np
    import soundfile as sf
    import torch
    from funasr import AutoModel

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this benchmark; do not silently change hardware")
    torch.set_num_threads(4)
    corpus_bytes = args.corpus.read_bytes()
    corpus = json.loads(corpus_bytes)
    words = args.hotwords.read_text(encoding="utf-8").split()
    assert len(words) == len(set(words)) == 40
    clips = corpus["clips"][:args.limit] if args.limit else corpus["clips"]
    if args.model == "nano":
        model_path = ROOT / ".models/fun-asr-nano-2512"
        model_id = "FunAudioLLM/Fun-ASR-Nano-2512"
        source_record = json.loads((args.corpus.parent / "nano_model_source.json").read_text(encoding="utf-8"))
        revision = source_record["revision"]
        options = dict(model=str(model_path), device="cuda:0", trust_remote_code=False, disable_update=True, disable_pbar=True, ncpu=4)
    else:
        model_id = "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        model_path = ROOT / ".models/modelscope/models" / model_id.replace("/", "--") / "snapshots/master"
        punctuation = ROOT / ".models/modelscope/models/iic--punc_ct-transformer_cn-en-common-vocab471067-large/snapshots/master"
        options = dict(model=str(model_path), punc_model=str(punctuation), punc_kwargs={"device": "cpu"}, device="cuda:0", disable_update=True, disable_pbar=True, ncpu=4)
        revision = "existing_local_master_snapshot"
    config = {"engine": "FunASR", "model_id": model_id, "model_path": model_path.relative_to(ROOT).as_posix(), "revision": revision, "device": torch.cuda.get_device_name(0), "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(), "hotwords": words, "conditions": ["plain", "hint40"], "seed": 0, "batch_size": 1, "vad": "none; identical precut clips", "speaker_model": None, "max_new_tokens": 512 if args.model == "nano" else None, "packages": {p: importlib.metadata.version(p) for p in ("funasr", "torch", "torchaudio", "transformers", "numpy")}}
    config_path = args.out / "config.json"
    if config_path.exists() and json.loads(config_path.read_text(encoding="utf-8")) != config:
        raise RuntimeError("Benchmark output configuration differs; choose a new directory")
    write_json(config_path, config)
    print(f"Loading {model_id}", flush=True)
    started = time.perf_counter()
    model = AutoModel(**options)
    load_seconds = time.perf_counter() - started
    write_json(args.out / "runtime.json", {"model_load_seconds": load_seconds})
    for condition in config["conditions"]:
        for index, clip in enumerate(clips, 1):
            path = args.out / condition / (clip["id"] + ".json")
            if path.exists():
                previous = json.loads(path.read_text(encoding="utf-8"))
                if previous.get("status") == "complete":
                    continue
            audio_path = ROOT / clip["audio_file"]
            wave, rate = sf.read(str(audio_path), dtype="float32")
            assert rate == 16000 and wave.ndim == 1
            np.random.seed(0)
            torch.manual_seed(0)
            torch.cuda.manual_seed_all(0)
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            started = time.perf_counter()
            if args.model == "paraformer":
                result = model.generate(input=str(audio_path), hotword=" ".join(words) if condition == "hint40" else None, batch_size=1, return_raw_text=True, sentence_timestamp=True, disable_pbar=True)
            else:
                result = model.generate(input=str(audio_path), hotwords=words if condition == "hint40" else [], language="中文", itn=False, batch_size=1, llm_dtype="bf16", max_length=512, llm_kwargs={"do_sample": False, "num_beams": 1}, disable_pbar=True)
            torch.cuda.synchronize()
            seconds = time.perf_counter() - started
            text = "".join(item.get("text", "") for item in result)
            assert text.strip(), f"Empty transcription: {clip['id']}"
            record = {"id": clip["id"], "model": args.model, "condition": condition, "bvid": clip["bvid"], "start_ms": clip["start_ms"], "end_ms": clip["end_ms"], "audio_file": clip["audio_file"], "text": text, "seconds": seconds, "duration_seconds": len(wave) / rate, "peak_allocated_bytes": torch.cuda.max_memory_allocated(), "status": "complete", "raw_result": result}
            write_json(path, record)
            print(f"{condition} {index}/{len(clips)} {clip['id']} {seconds:.2f}s {text[:110]}", flush=True)
    write_json(args.out / "completion.json", {"completed": True, "conditions": config["conditions"], "clips_per_condition": len(clips), "model_load_seconds": load_seconds})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
