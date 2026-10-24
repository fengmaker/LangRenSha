"""Seek to a local audio window and save mono 16 kHz PCM with original offsets."""

import argparse
import hashlib
import json
import sys
import time
from fractions import Fraction
from pathlib import Path


def decode_window(audio, start_ms, end_ms):
    import av
    import numpy as np

    if not 0 <= start_ms < end_ms:
        raise ValueError("Require 0 <= start_ms < end_ms")
    rate = 16000
    first, last = start_ms * 16, end_ms * 16
    cursor = first
    pieces = []
    decoded_frames = 0
    with av.open(str(audio)) as container:
        if any(s.type == "video" for s in container.streams):
            raise ValueError("Input must be an independent audio track")
        stream = container.streams.audio[0]
        origin = Fraction(stream.start_time or 0) * stream.time_base
        # Preroll permits decoder warmup and a globally aligned resampling phase.
        seek_time = max(Fraction(0), Fraction(start_ms, 1000) - 30) + origin
        container.seek(int(seek_time / stream.time_base), stream=stream, backward=True)
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
        started = False

        def consume(frame):
            nonlocal cursor
            if frame.pts is None:
                raise ValueError("Decoded window has no timestamp")
            position = round((Fraction(frame.pts) * frame.time_base - origin) * rate)
            values = frame.to_ndarray().reshape(-1)
            lo, hi = max(position, first), min(position + len(values), last)
            if lo < hi:
                if lo != cursor:
                    raise ValueError("Discontinuous audio timestamps; window requires review")
                pieces.append(values[lo - position:hi - position])
                cursor = hi

        for frame in container.decode(stream):
            decoded_frames += 1
            if frame.pts is None:
                raise ValueError("Input frame has no timestamp")
            if not started:
                position = (Fraction(frame.pts) * frame.time_base - origin) * rate
                if position.denominator != 1:
                    continue
                if position > first:
                    raise ValueError("Could not align window before its requested beginning")
                started = True
            for converted in resampler.resample(frame):
                consume(converted)
            if cursor >= last:
                break
        else:
            for converted in resampler.resample(None):
                consume(converted)
    if cursor != last:
        raise ValueError(f"Window exceeds decoded audio or is incomplete: {cursor - first}/{last - first} samples")
    return np.concatenate(pieces), decoded_frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--start-ms", type=int, required=True)
    parser.add_argument("--end-ms", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.suffix.lower() != ".wav" or args.audio.resolve() == args.out.resolve():
        raise ValueError("Use a separate .wav output file")
    started = time.perf_counter()
    values, frames = decode_window(args.audio, args.start_ms, args.end_ms)
    import soundfile as sf

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(args.out), values, 16000, subtype="PCM_16")
    digest = hashlib.sha256()
    with args.audio.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    record = {"source_audio": args.audio.as_posix(), "source_audio_sha256": digest.hexdigest(),
              "clip_file": args.out.as_posix(), "start_ms_in_original": args.start_ms,
              "end_ms_in_original": args.end_ms, "duration_ms": args.end_ms - args.start_ms,
              "sample_rate": 16000, "samples": len(values), "channels": 1,
              "decoder": "PyAV seek with preroll and timestamp cropping",
              "decoded_frames": frames, "processing_seconds": time.perf_counter() - started}
    args.out.with_suffix(".source.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
