"""Validate the saved, local three-model ASR comparison artifacts."""
import hashlib
import json
import re
import subprocess
import tempfile
import wave
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "outputs/asr_model_benchmark_20261022"


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.articles = 0
        self.audio = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.articles += tag == "article"
        if "data-audio" in attrs:
            self.audio.append(attrs["data-audio"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])


def main():
    corpus = json.loads((DIRECTORY / "corpus.json").read_text(encoding="utf-8"))
    summary = json.loads((DIRECTORY / "summary.json").read_text(encoding="utf-8"))
    assert summary["clip_count"] == len(corpus["clips"]) == 13
    assert summary["run_count"] == 78 and len(summary["metrics"]) == 6
    words = (DIRECTORY / "benchmark_hotwords.txt").read_text(encoding="utf-8").split()
    assert len(words) == len(set(words)) == 40
    assert words[0] == "\u72fc\u4eba\u6740"
    assert not any("\ufffd" in word or "\x00" in word for word in words)
    for clip in corpus["clips"]:
        path = ROOT / clip["audio_file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == clip["clip_audio_sha256"]
        with wave.open(str(path), "rb") as audio:
            assert audio.getframerate() == 16000 and audio.getnchannels() == 1
            assert audio.getsampwidth() == 2 and audio.getnframes() == clip["frames"]
        for model in ("paraformer", "qwen", "nano"):
            for condition in ("plain", "hint40"):
                result = summary["results"][clip["id"]][model][condition]
                assert result["text"].strip() and result["status"] == "complete"
                assert result["condition"] == condition and result["seconds"] > 0
                assert result["audio_file"] == clip["audio_file"]
    for row in summary["metrics"]:
        assert row["clip_count"] == 13 and row["accuracy"] is None
        assert row["audio_seconds"] > 328 and row["peak_allocated_bytes"] > 0
    source_hashes = {}
    for clip in corpus["clips"]:
        source_hashes[clip["source_audio_file"]] = clip["source_audio_sha256"]
    for source, expected_hash in source_hashes.items():
        assert hashlib.sha256((ROOT / source).read_bytes()).hexdigest() == expected_hash

    html = (DIRECTORY / "comparison.html").read_text(encoding="utf-8")
    page = Page()
    page.feed(html)
    assert page.articles == len(page.audio) == 13
    for target in page.audio + page.links:
        assert (DIRECTORY / unquote(target)).resolve().is_file(), target
    assert not re.search(r"__[A-Z]+__", html)
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(scripts) == 1
    electron = Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe"
    if not electron.is_file():
        raise RuntimeError("JavaScript syntax validator is unavailable")
    import os
    environment = dict(os.environ, ELECTRON_RUN_AS_NODE="1")
    (ROOT / ".cache").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="asr-comparison-", dir=str(ROOT / ".cache")) as temp:
        javascript = Path(temp) / "comparison.js"
        javascript.write_text(scripts[0], encoding="utf-8")
        subprocess.run([str(electron), "--check", str(javascript)], env=environment, check=True, capture_output=True)
    validation = {"validated": True, "outputs": 78, "clips": 13, "source_audio_hashes": len(source_hashes), "html_audio_targets": len(page.audio), "javascript_syntax": "passed", "human_accuracy_score": None}
    (DIRECTORY / "validation.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    main()
