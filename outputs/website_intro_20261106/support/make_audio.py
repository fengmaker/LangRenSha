"""Generate Chinese narration and retain speech boundary timings."""
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tmp" / "website_video_deps"))
import edge_tts

SUPPORT = Path(__file__).resolve().parent
STORY = json.loads((SUPPORT / "storyboard.json").read_text(encoding="utf-8"))
AUDIO = SUPPORT / "audio"
AUDIO.mkdir(exist_ok=True)

async def main():
    sem = asyncio.Semaphore(3)
    async def generate(scene):
        async with sem:
            path = AUDIO / (scene["id"] + ".mp3")
            boundaries = []
            tts = edge_tts.Communicate(scene["narration"], "zh-CN-YunxiNeural", rate="+8%", boundary="WordBoundary")
            with path.open("wb") as f:
                async for chunk in tts.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        boundaries.append(chunk)
            path.with_suffix(".json").write_text(json.dumps(boundaries, ensure_ascii=False, indent=2), encoding="utf-8")
            print(scene["id"], path.stat().st_size, flush=True)
    await asyncio.gather(*(generate(scene) for scene in STORY))

asyncio.run(main())
