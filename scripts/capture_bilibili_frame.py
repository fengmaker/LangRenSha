"""Capture selected original-video frames for game fact checking; no stream URLs logged."""
import argparse
from fractions import Fraction
from pathlib import Path
import sys

from collect_bilibili_audio import Collector

ROOT = Path(__file__).resolve().parents[1]


def capture(bvid, cid, seconds, out):
    import av
    client = Collector(quiet=True)
    play = client.api("/x/player/playurl", {"bvid": bvid, "cid": cid, "fnval": 16, "fnver": 0, "qn": 80})["data"]
    tracks = [v for v in play.get("dash", {}).get("video", []) if (v.get("baseUrl") or v.get("base_url"))]
    if not tracks:
        raise RuntimeError("官方接口没有返回可用视频流")
    chosen = max(tracks, key=lambda v: (v.get("height", 0), str(v.get("codecs", "")).startswith("avc")))
    url = chosen.get("baseUrl") or chosen["base_url"]
    out.mkdir(parents=True, exist_ok=True)
    with av.open(url, options={"headers": "Referer: https://www.bilibili.com/\r\nUser-Agent: Mozilla/5.0\r\n", "rw_timeout": "20000000"}) as media:
        stream = media.streams.video[0]
        for second in seconds:
            media.seek(int(Fraction(str(second)) / stream.time_base), stream=stream, backward=True)
            for frame in media.decode(stream):
                if frame.time is not None and frame.time >= second:
                    path = out / f"{bvid}_{second:09.3f}.png"
                    image_frame = frame.reformat(format="rgb24")
                    image_frame.pts = 0
                    image_frame.time_base = Fraction(1, 1)
                    with av.open(str(path), mode="w", format="image2") as output:
                        encoder = output.add_stream("png", rate=1)
                        encoder.width, encoder.height, encoder.pix_fmt = frame.width, frame.height, "rgb24"
                        for packet in encoder.encode(image_frame):
                            output.mux(packet)
                        for packet in encoder.encode(None):
                            output.mux(packet)
                    print(f"{bvid} {second:.3f}s {frame.width}x{frame.height} -> {path.relative_to(ROOT)}", flush=True)
                    break
            else:
                raise RuntimeError("指定时间没有可解码画面")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bvid")
    parser.add_argument("cid", type=int)
    parser.add_argument("--times", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        capture(args.bvid, args.cid, [float(s) for s in args.times.split(",")], args.out.resolve())
    except Exception as exc:
        print("原视频画面抓取失败：" + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
