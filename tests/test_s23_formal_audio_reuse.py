import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import import_s23_formal as formal
from database import ReviewError


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _ArtifactConn:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return _Result(self.rows)


def _missing_audio_fixture(tmp_path, monkeypatch, *, audio_path=None):
    monkeypatch.setattr(formal, "ROOT", tmp_path)
    bvid = "BVfixture123"
    raw_dir = tmp_path / "data/raw/bilibili" / bvid / "p01"
    raw_dir.mkdir(parents=True)
    audio_sha = "a" * 64
    manifest = {
        "bvid": bvid,
        "page": 1,
        "cid": 456,
        "audio": {"file": "audio.m4a", "sha256": audio_sha, "bytes": 1234},
        "subtitles": {"tracks": []},
    }
    manifest_path = raw_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (raw_dir / "metadata.raw.json").write_text("{}", encoding="utf-8")
    selected_audio_path = audio_path or f"data/raw/bilibili/{bvid}/p01/audio.m4a"
    dossier = {
        "slug": f"bili-{bvid}-p01-g01",
        "files": [{"role": "audio", "path": selected_audio_path, "kind": "audio"}],
    }
    return dossier, bvid, selected_audio_path, audio_sha


def test_missing_audio_requires_exact_registered_bilibili_path_and_manifest_hash(tmp_path, monkeypatch):
    dossier, bvid, audio_path, audio_sha = _missing_audio_fixture(tmp_path, monkeypatch)
    conn = _ArtifactConn([{"id": "audio-id", "sha256": audio_sha, "byte_size": 1234}])

    files, media = formal.resolve_source_files(dossier, audio_reuse_conn=conn)

    assert media["audio_sha256"] == audio_sha
    assert media["audio_bytes"] == 1234
    assert next(item for item in files if item["role"] == "audio")["path"] == audio_path
    assert conn.calls[0][1] == (f"{bvid}:456", audio_path, audio_path)
    assert "a.metadata->>'ingested_from'=%s" in " ".join(conn.calls[0][0].split())


def test_missing_audio_without_database_registration_stays_strict(tmp_path, monkeypatch):
    dossier, _bvid, _audio_path, _audio_sha = _missing_audio_fixture(tmp_path, monkeypatch)

    with pytest.raises(ReviewError, match="仅数据库导入"):
        formal.resolve_source_files(dossier)


def test_missing_non_audio_candidate_file_stays_strict(tmp_path, monkeypatch):
    dossier, _bvid, _audio_path, audio_sha = _missing_audio_fixture(tmp_path, monkeypatch)
    dossier["files"].append({
        "role": "transcript", "path": "data/extractions/missing-transcript.json", "kind": "transcript",
    })
    conn = _ArtifactConn([{"id": "audio-id", "sha256": audio_sha, "byte_size": 1234}])

    with pytest.raises(ReviewError, match="候选所列来源文件不存在"):
        formal.resolve_source_files(dossier, audio_reuse_conn=conn)


@pytest.mark.parametrize(
    "rows, message",
    [
        ([], "未唯一登记"),
        ([{"id": "audio-id", "sha256": "b" * 64, "byte_size": 1234}], "manifest哈希不一致"),
        ([{"id": "one", "sha256": "a" * 64, "byte_size": 1234},
          {"id": "two", "sha256": "a" * 64, "byte_size": 1234}], "未唯一登记"),
    ],
)
def test_missing_audio_rejects_absent_wrong_hash_or_ambiguous_registration(
        tmp_path, monkeypatch, rows, message):
    dossier, _bvid, _audio_path, _audio_sha = _missing_audio_fixture(tmp_path, monkeypatch)

    with pytest.raises(ReviewError, match=message):
        formal.resolve_source_files(dossier, audio_reuse_conn=_ArtifactConn(rows))


def test_missing_candidate_audio_must_match_its_registered_path(tmp_path, monkeypatch):
    alternate = "data/seasons/S23/another-copy/audio.m4a"
    dossier, bvid, _audio_path, audio_sha = _missing_audio_fixture(
        tmp_path, monkeypatch, audio_path=alternate)
    conn = _ArtifactConn([{"id": "audio-id", "sha256": audio_sha, "byte_size": 1234}])

    formal.resolve_source_files(dossier, audio_reuse_conn=conn)

    assert conn.calls[0][1] == (f"{bvid}:456", alternate, alternate)
