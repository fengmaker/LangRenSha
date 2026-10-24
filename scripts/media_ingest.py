"""Validate a downloaded official audio source without loading an ASR model."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_BILIBILI_MID = "19106800"


class MediaValidationError(ValueError):
    pass


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise MediaValidationError("原始清单或接口响应不存在，或不是有效 JSON") from None
    if not isinstance(value, dict):
        raise MediaValidationError("原始清单或接口响应必须是 JSON 对象")
    return value


def child_file(folder: Path, name: str) -> Path:
    if not isinstance(name, str) or not name:
        raise MediaValidationError("原始清单缺少文件名")
    target = (folder / name).resolve()
    if not target.is_relative_to(folder.resolve()) or not target.is_file() or target.suffix == ".part":
        raise MediaValidationError("原始文件缺失、未完成，或路径超出本次采集目录")
    return target


def probe_audio(path: Path, expected_duration: float) -> dict:
    try:
        import av
    except ImportError:
        raise MediaValidationError("缺少媒体校验依赖 PyAV，请安装 requirements-core.txt；不需要安装转写模型") from None
    try:
        with av.open(str(path)) as container:
            tracks = [{"type": stream.type, "codec": stream.codec_context.name} for stream in container.streams]
            if any(track["type"] == "video" for track in tracks) or not any(track["type"] == "audio" for track in tracks):
                raise MediaValidationError("第一步音频文件必须有音轨且不能含视频轨")
            duration = container.duration / av.time_base if container.duration is not None else None
            if duration is None or duration <= 0:
                raise MediaValidationError("媒体时长未知或不大于 0，不能确认采集完成")
            if abs(duration-expected_duration) > max(3.0, expected_duration * 0.01):
                raise MediaValidationError("音轨时长与原始元数据差异超过 3 秒或 1%，需检查缺失或错误分 P")
            if next(container.decode(audio=0), None) is None:
                raise MediaValidationError("音轨无法解码出音频帧")
    except MediaValidationError:
        raise
    except Exception:
        raise MediaValidationError("音频容器无法打开或起始音频无法解码，未视为完成") from None
    return {"tracks": tracks, "duration_seconds": duration, "first_frame_decoded": True,
            "full_stream_decoded": False}


def validate_media(manifest_path: Path, expected_bvid: str | None = None, expected_page: int | None = None) -> dict:
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to((ROOT / "data").resolve()):
        raise MediaValidationError("采集结果必须位于项目 data 目录")
    manifest = read_json(manifest_path)
    folder = manifest_path.parent
    raw_path = child_file(folder, "metadata.raw.json")
    raw = read_json(raw_path).get("data")
    if not isinstance(raw, dict):
        raise MediaValidationError("原始接口响应缺少 data")
    bvid = manifest.get("bvid")
    if not isinstance(bvid, str) or not re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid) or raw.get("bvid") != bvid:
        raise MediaValidationError("清单与原始接口响应的 BVID 不一致")
    if ((expected_bvid is not None and bvid != expected_bvid) or
        (expected_page is not None and manifest.get("page") != expected_page)):
        raise MediaValidationError("已有清单不是这次指定的 BV/分 P")
    owner = str((manifest.get("owner") or {}).get("mid", ""))
    raw_owner = str((raw.get("owner") or {}).get("mid", ""))
    if owner != OFFICIAL_BILIBILI_MID or raw_owner != owner:
        raise MediaValidationError("清单或原始接口响应的投稿者不是已确认的官方 UID 19106800")
    page = next((p for p in raw.get("pages", []) if p.get("page") == manifest.get("page")), None)
    if page is None or page.get("cid") != manifest.get("cid"):
        raise MediaValidationError("清单与原始接口响应的分 P/CID 不一致")
    declared_duration = manifest.get("duration_seconds")
    if type(declared_duration) not in {int, float} or declared_duration <= 0 or page.get("duration") != declared_duration:
        raise MediaValidationError("清单与原始接口响应的时长不一致或无有效时长")
    audio = manifest.get("audio")
    if not isinstance(audio, dict) or audio.get("video_downloaded") is not False:
        raise MediaValidationError("缺少已下载的独立音轨清单")
    audio_path = child_file(folder, audio.get("file"))
    if type(audio.get("bytes")) is not int or audio["bytes"] <= 0 or audio_path.stat().st_size != audio["bytes"]:
        raise MediaValidationError("音频文件大小与原始清单不一致")
    if not isinstance(audio.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", audio["sha256"]):
        raise MediaValidationError("清单缺少有效音频 SHA-256")
    with audio_path.open("rb") as stream:
        if hashlib.file_digest(stream,"sha256").hexdigest() != audio["sha256"]:
            raise MediaValidationError("音频 SHA-256 与原始清单不一致")
    probe = probe_audio(audio_path, declared_duration)
    subtitles = []
    for track in (manifest.get("subtitles") or {}).get("tracks") or []:
        subtitles.append((child_file(folder,track.get("file")),track))
    summary = {"status":"raw_media_ready", "checked_at_utc":datetime.now(timezone.utc).isoformat(),
               "bvid":bvid,"cid":manifest["cid"],"page":manifest["page"],"owner_mid":owner,
               "official_owner_matches":True,"audio_bytes":audio["bytes"],"audio_sha256":audio["sha256"],
               "probe":probe,"subtitle_status":(manifest.get("subtitles") or {}).get("status","unknown"),
               "game_facts_verified":False}
    return {"manifest":manifest,"manifest_path":manifest_path,"raw_path":raw_path,
            "audio_path":audio_path,"subtitles":subtitles,"summary":summary}
