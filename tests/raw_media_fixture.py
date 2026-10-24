"""Tiny synthetic media fixture; never a real tournament source."""

import hashlib
import json
from pathlib import Path
import wave


def make_media(folder: Path, cid: int = 123456) -> Path:
    folder.mkdir(parents=True,exist_ok=True)
    audio = folder/'audio.m4a'
    # PyAV detects the actual WAVE container; a short local fixture avoids a codec
    # encoder dependency. Production inputs still come from DASH audio/mp4.
    with wave.open(str(audio),'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b'\x00\x00'*8000)
    page = {'page':1,'cid':cid,'duration':1}
    owner = {'mid':19106800,'name':'synthetic test only'}
    raw = {'data':{'bvid':'BV1tj8p6REqy','owner':owner,'pages':[page]}}
    (folder/'metadata.raw.json').write_text(json.dumps(raw),encoding='utf-8')
    manifest = {'bvid':'BV1tj8p6REqy','cid':cid,'page':1,'owner':owner,'title':'synthetic fixture, not a real post',
                'duration_seconds':1,'published_timestamp':None,'access_mode':'public_without_cookies',
                'audio':{'file':'audio.m4a','bytes':audio.stat().st_size,'sha256':hashlib.sha256(audio.read_bytes()).hexdigest(),'video_downloaded':False},
                'subtitles':{'status':'login_required','tracks':[]}}
    path = folder/'manifest.json'
    path.write_text(json.dumps(manifest),encoding='utf-8')
    return path
