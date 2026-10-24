"""Package a completed local ASR benchmark without treating machine text as gold."""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
MODELS = {"paraformer": "Paraformer", "qwen": "Qwen3-ASR-0.6B", "nano": "Fun-ASR-Nano"}
CONDITIONS = ("plain", "hint40")


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stamp(ms):
    value = int(ms / 1000)
    return f"{value // 3600:02}:{value // 60 % 60:02}:{value % 60:02}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "outputs/asr_model_benchmark_20261022")
    args = parser.parse_args()
    directory = args.directory
    corpus = json.loads((directory / "corpus.json").read_text(encoding="utf-8"))
    clips = corpus["clips"]
    corpus_sha = hashlib.sha256((directory / "corpus.json").read_bytes()).hexdigest()
    common_words = (directory / "benchmark_hotwords.txt").read_text(encoding="utf-8").split()
    assert len(common_words) == len(set(common_words)) == 40
    audio_seconds = sum((clip["end_ms"] - clip["start_ms"]) / 1000 for clip in clips)
    results, metrics, configurations = {}, [], {}
    missing = []
    for model, label in MODELS.items():
        configurations[model] = json.loads((directory / model / "config.json").read_text(encoding="utf-8"))
        config = configurations[model]
        assert config["corpus_sha256"] == corpus_sha, f"Corpus differs for {model}"
        assert config.get("hotwords", config.get("context_words")) == common_words, f"Hints differ for {model}"
        completion = json.loads((directory / model / "completion.json").read_text(encoding="utf-8"))
        assert completion["completed"] and completion["clips_per_condition"] == len(clips)
        for condition in CONDITIONS:
            items = []
            for clip in clips:
                source = directory / model / condition / (clip["id"] + ".json")
                if not source.exists():
                    missing.append(source.relative_to(directory).as_posix())
                    continue
                record = json.loads(source.read_text(encoding="utf-8"))
                assert record["id"] == clip["id"] and record["text"].strip()
                assert record["status"] == "complete"
                assert record["audio_file"] == clip["audio_file"]
                assert record["start_ms"] == clip["start_ms"] and record["end_ms"] == clip["end_ms"]
                assert not record.get("truncated", False)
                assert abs(record["duration_seconds"] - clip["duration_ms"] / 1000) < 0.001
                results.setdefault(clip["id"], {}).setdefault(model, {})[condition] = record
                items.append(record)
            metrics.append({"model": model, "label": label, "condition": condition, "clip_count": len(items), "audio_seconds": audio_seconds, "inference_seconds": sum(item["seconds"] for item in items), "rtf": sum(item["seconds"] for item in items) / audio_seconds, "peak_allocated_bytes": max((item["peak_allocated_bytes"] for item in items), default=0), "model_load_seconds": completion["model_load_seconds"], "accuracy": None})
    if missing:
        raise RuntimeError("Incomplete benchmark: " + ", ".join(missing))
    data = {"schema_version": 1, "clip_count": len(clips), "source_count": len({clip["bvid"] for clip in clips}), "audio_seconds": audio_seconds, "model_count": len(MODELS), "conditions": list(CONDITIONS), "run_count": len(clips) * len(MODELS) * len(CONDITIONS), "metrics": metrics, "configurations": configurations, "results": results, "reference_status": "No verbatim human gold transcript. Existing ASR and platform captions are unverified references, not accuracy targets.", "limitations": ["角色、数字和技能内容仍需按原音核验。", "多个模型相符不自动构成人工真值；词表命中次数不代表准确率。", "计时包括模型接口内音频读取及推理，排除权重下载与冷加载；首条有暖机开销，不能外推严格性能排名。", "预切片短音频测试，不证明整场长音频、多人归属和时间戳均已可靠。"]}
    save(directory / "summary.json", data)

    cards = []
    for clip in clips:
        audio = ROOT / clip["audio_file"]
        href = quote(os.path.relpath(audio, directory).replace("\\", "/"), safe="/")
        columns = []
        for model, label in MODELS.items():
            paragraphs = []
            for condition in CONDITIONS:
                record = results[clip["id"]][model][condition]
                paragraphs.append(f'<div class="output {condition}"><p>{html.escape(record["text"])}</p><small>{record["seconds"]:.2f} 秒 · 峰值显存分配 {record["peak_allocated_bytes"] / 1024**3:.2f} GiB</small></div>')
            columns.append(f'<div class="column"><h3>{label}</h3>{"".join(paragraphs)}</div>')
        cards.append(f'<article id="{html.escape(clip["id"], quote=True)}" data-category="{html.escape(clip["category"], quote=True)}"><h2><button data-audio="{html.escape(href, quote=True)}" data-label="{html.escape(clip["id"], quote=True)}">▶ 播放本段</button> {html.escape(clip["id"])}</h2><div class="source">{html.escape(clip["board"])} · {html.escape(clip["bvid"])} · 原音频 {stamp(clip["start_ms"])}—{stamp(clip["end_ms"])} · {html.escape(clip["category"])}</div><div class="columns">{"".join(columns)}</div><details><summary>已有机器稿与平台字幕 · 都未经逐字听核</summary><p><b>旧稿：</b>{html.escape(clip["old_text"])}</p><p><b>平台：</b>{html.escape(clip.get("platform_text") or "")}</p></details></article>')
    table_rows = []
    for metric in metrics:
        table_rows.append(f'<tr><td>{metric["label"]}</td><td>{"无提示" if metric["condition"] == "plain" else "40 词提示"}</td><td>{metric["clip_count"]}</td><td>{metric["inference_seconds"]:.1f} 秒</td><td>{metric["rtf"]:.3f}</td><td>{metric["peak_allocated_bytes"] / 1024**3:.2f} GiB</td></tr>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>狼人杀语音转写 · 三模型对照</title>
<style>body{font:16px/1.8 system-ui,sans-serif;background:#f3f6f9;color:#1c2b3b;margin:0}main{max-width:1500px;margin:auto;padding:24px}h1{font-size:27px}h2{font-size:19px;margin:0}h3{font-size:17px;color:#224e72;margin:0}article,section{background:white;border:1px solid #d8e0e8;border-radius:12px;padding:20px;margin:18px 0}.columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px}.column p{overflow-wrap:anywhere;white-space:pre-wrap}.column+.column{border-left:1px solid #dce3ea;padding-left:20px}.source,small{color:#5c6c7d}.source{margin:10px 0}button{background:#e6eff8;border:1px solid #a7bbce;border-radius:6px;padding:7px 12px;cursor:pointer;color:#17446b}.toolbar{position:sticky;top:0;background:#eaf1f8;border:1px solid #c6d5e4;padding:14px;z-index:2;border-radius:10px}audio{width:100%}select,input{padding:7px;margin:8px 6px;font-size:15px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;border-bottom:1px solid #e1e6ec;text-align:left}.hint40{display:none}details{border-top:1px solid #e0e6ed;margin-top:15px;padding-top:10px}a{color:#235f8e}@media(max-width:1000px){.columns{grid-template-columns:1fr}.column+.column{border-left:0;border-top:1px solid #dce3ea;padding:15px 0 0}main{padding:12px}}[hidden]{display:none!important}</style>
<main><h1>狼人杀音频 · 三模型实际对照</h1><p>__SCOPE__。相同 WAV 输入；每个模型分别跑无提示和共同 40 词提示。这里展示原始模型文字，没有让大语言模型润色或补身份。</p><p><a href="report.md">阅读审阅结论</a> · <a href="summary.json">完整机器结果</a> · <a href="corpus_review.md">语料与来源</a> · <a href="benchmark_hotwords.txt">共同提示词</a></p>
<div class=toolbar><audio id=player controls preload=none></audio><small id=playing>点击任一片段的播放按钮，回听完全相同的测试音频。</small><div><label>条件<select id=condition><option value=plain>无提示</option><option value=hint40>40 词提示</option></select></label><label><input id=recap type=checkbox>只看法官最终复盘</label><input id=search type=search placeholder="搜索片段或术语"></div></div>
<section><p>本测试没有逐字人工真值，因此不报告识别准确率。模型之间一致、文字更流畅和术语出现更多，都不能单独证明原声转写正确。表格仅描述本次推理资源开销，冷加载与下载另记。</p><table><thead><tr><th>模型</th><th>条件</th><th>片段</th><th>推理合计</th><th>RTF</th><th>峰值显存分配</th></tr></thead><tbody>__METRICS__</tbody></table></section>__CARDS__</main>
<script>const player=document.querySelector('#player');document.querySelectorAll('[data-audio]').forEach(b=>b.addEventListener('click',async()=>{player.src=b.dataset.audio;document.querySelector('#playing').textContent='正在播放：'+b.dataset.label;try{await player.play()}catch(e){document.querySelector('#playing').textContent='请点击音频播放器播放：'+b.dataset.label}}));function filter(){const condition=document.querySelector('#condition').value;document.querySelectorAll('.plain,.hint40').forEach(e=>e.style.display=e.classList.contains(condition)?'block':'none');const query=document.querySelector('#search').value.trim();const recap=document.querySelector('#recap').checked;document.querySelectorAll('article').forEach(e=>e.hidden=(recap&&e.dataset.category!=='referee_final_recap')||!e.textContent.includes(query))}['condition','search','recap'].forEach(id=>document.getElementById(id).addEventListener(id==='search'?'input':'change',filter));filter();</script></html>'''
    page = page.replace("__SCOPE__", f'{len(clips)} 个片段，来自 {data["source_count"]} 场对局，共 {audio_seconds:.2f} 秒；3 模型 × 2 条件，共 {data["run_count"]} 次推理')
    page = page.replace("__METRICS__", "".join(table_rows)).replace("__CARDS__", "\n".join(cards))
    (directory / "comparison.html").write_text(page, encoding="utf-8")
    print(json.dumps({key: data[key] for key in ("clip_count", "source_count", "audio_seconds", "run_count", "metrics")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    main()
