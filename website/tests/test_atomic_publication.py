"""Publication boundaries must preserve the visitor's complete release."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shutil
import uuid

import pytest
from psycopg import sql

from website.api import bluff_store, bluffs, publish, publisher


@pytest.mark.parametrize("args", [[], ["--sample", "BV1yt7v6QE3Q"]])
def test_default_and_sample_commands_only_preflight(monkeypatch, args):
    checks = []
    monkeypatch.setattr(publish, "_preflight", lambda *args: checks.append(args) or {"valid": True})
    monkeypatch.setattr(publisher, "publish", lambda *args, **kwargs: pytest.fail("preview wrote a release"))
    assert publish.main(args) == 0
    assert len(checks) == 1


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class ActivationConnection:
    def __init__(self, seasons, reviews):
        self.seasons = seasons
        self.reviews = reviews
        self.activated = False

    @contextmanager
    def transaction(self):
        yield

    def execute(self, query, params=None):
        text = str(query)
        if text.startswith("SELECT game_count"):
            return Cursor([{"game_count": 2}])
        if "SELECT DISTINCT" in text and "active_release" in text:
            return Cursor([{"season": s} for s in ("S22", "S23")])
        if "SELECT DISTINCT" in text and "games" in text:
            return Cursor([{"season": s} for s in self.seasons])
        if "SELECT season" in text and "active_bluff_reviews" in text:
            return Cursor([{"season": s} for s in self.reviews])
        if text.startswith("INSERT INTO active_release"):
            self.activated = True
        return Cursor([])

    def close(self):
        pass


@pytest.mark.parametrize(("seasons", "reviews", "error"), [
    (["S22"], ["S22"], "赛季"),
    (["S22", "S23"], ["S22"], "悍跳"),
])
def test_direct_activation_guards_retained_seasons_and_reviews(monkeypatch, seasons, reviews, error):
    conn = ActivationConnection(seasons, reviews)
    monkeypatch.setattr(publisher, "_connect", lambda schema: conn)
    monkeypatch.setattr(publisher, "_create_schema", lambda conn: None)
    with pytest.raises(publisher.PublishError, match=error):
        publisher.activate("candidate")
    assert not conn.activated


@pytest.mark.parametrize("candidate", ["candidate", "old-release"])
def test_final_season_failure_preserves_game_and_review_pointers(monkeypatch, tmp_path, candidate):
    state = {"release": "old-release", "reviews": {"S22": "old-22", "S23": "old-23"}}
    before = deepcopy(state)

    class Connection:
        @contextmanager
        def transaction(self):
            try:
                yield
            except Exception:
                state.clear()
                state.update(deepcopy(before))
                raise

        def close(self):
            pass

    conn = Connection()

    def prepare(*args, activate=True, **kwargs):
        assert activate is False
        return {"id": candidate, "activated": False}

    def review(season, path=None, check=False, *, release_id=None, connection=None, root=None):
        assert release_id == candidate and connection is conn
        if season == "S23":
            raise bluff_store.BluffReviewError("forced final season failure")
        state["reviews"][season] = "new-22"
        return {"published": True}

    monkeypatch.setattr(publisher, "publish", prepare)
    monkeypatch.setattr(publisher, "_connect", lambda schema: conn)
    monkeypatch.setattr(bluff_store, "publish_review", review)
    for season in ("S22", "S23"):
        path = tmp_path / f"website/assets/bluffs/{season}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/seasons.json").write_text('{"seasons": {}}', encoding="utf-8")

    with pytest.raises(bluff_store.BluffReviewError, match="forced final season failure"):
        publisher.publish_complete(tmp_path, ["S22", "S23"])
    assert state == before


@pytest.fixture
def isolated_database(monkeypatch):
    """Use a disposable schema; never activate or alter the real website data."""
    real_connect = publisher._connect
    try:
        admin = real_connect()
    except Exception as exc:
        pytest.skip(f"local PostgreSQL unavailable: {type(exc).__name__}")
    schema = "test_atomic_" + uuid.uuid4().hex
    schema_source = publisher._schema_sql().replace("masters_web", schema)
    with admin.transaction():
        admin.execute(schema_source, prepare=False)
    monkeypatch.setattr(publisher, "_schema_sql", lambda: schema_source)
    monkeypatch.setattr(publisher, "_connect", lambda schema_name="masters_web": real_connect(schema))
    try:
        yield lambda: real_connect(schema)
    finally:
        # This exact, generated test schema is the only cleanup target.
        assert schema.startswith("test_atomic_") and len(schema) == 44
        with admin.transaction():
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


@pytest.mark.parametrize("same_release", [False, True])
def test_postgres_final_season_failure_keeps_visitor_snapshot(
    monkeypatch, tmp_path, isolated_database, same_release,
):
    root = Path(__file__).resolve().parents[2]
    (tmp_path / "website/assets").mkdir(parents=True)
    shutil.copy2(root / "website/assets/people.json", tmp_path / "website/assets/people.json")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/seasons.json").write_text(json.dumps({
        "seasons": {season: {"bluff_entry": "confirmed"} for season in ("S22", "S23")},
    }), encoding="utf-8")
    board = publisher._logical_rules(root, "S22")[1]["boards"]["mixed_blood"]
    entries = []
    for season in ("S22", "S23"):
        entries.append({
            "dossier": {"slug": f"{season}_BV1yt7v6QE3Q_p01_g01", "season": season,
                        "date": "2026-06-01", "phase": "regular", "game_number": 1,
                        "board": "mixed_blood", "winner": None, "rounds": [],
                        "seats": [{"seat": 1, "name": "JY", "role": "狼人", "faction": "werewolf"}]},
            "voting": {}, "endgame": {}, "audit": None, "board": board,
            "bvid": "BV1yt7v6QE3Q", "source_hashes": {},
        })
    generation = {"value": "old"}
    monkeypatch.setattr(publisher, "load_release", lambda *args: (
        entries, publisher.digest_bytes(generation["value"].encode()), "a" * 64,
    ))
    monkeypatch.setattr(publisher, "_logical_rules", lambda *args: ({}, {}))
    identities = publisher._person_ids(tmp_path, {"JY"})
    for item in entries:
        game = publisher._public_game(item["dossier"], {}, {}, None, board, identities)
        assessment = {"seat": 1, "name": "JY", "physical_role": "狼人", "decision": "no",
                      "verification_status": "user_confirmed", "evidence": []}
        assessment["claim_fingerprint"] = bluffs.claim_fingerprint(game, assessment)
        assessment["success_fingerprint"] = bluffs.success_fingerprint(game, 1, 1)
        path = tmp_path / f"website/assets/bluffs/{game['season']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "season": game["season"],
                                   "inference_version": "original", "games": [{
                                       "game_id": game["id"], "bvid": "BV1yt7v6QE3Q",
                                       "source_fingerprint": bluffs.source_fingerprint(game),
                                       "assessments": [assessment],
                                   }]}), encoding="utf-8")
    original = publisher.publish_complete(tmp_path, ["S22", "S23"])

    def visitor_rows():
        with isolated_database() as observer:
            return observer.execute(
                "SELECT a.release_id, b.season, b.publication_id FROM active_release a "
                "JOIN active_bluff_reviews b ON b.release_id = a.release_id ORDER BY b.season"
            ).fetchall()

    before = visitor_rows()
    assert len(before) == 2 and {row["release_id"] for row in before} == {original["id"]}
    first = tmp_path / "website/assets/bluffs/S22.json"
    payload = json.loads(first.read_text(encoding="utf-8"))
    payload["inference_version"] = "changed-first-season"
    first.write_text(json.dumps(payload), encoding="utf-8")
    last = tmp_path / "website/assets/bluffs/S23.json"
    payload = json.loads(last.read_text(encoding="utf-8"))
    payload["games"] = []  # Fail actual final-season coverage validation.
    last.write_text(json.dumps(payload), encoding="utf-8")
    if not same_release:
        generation["value"] = "candidate"

    with pytest.raises(bluff_store.BluffReviewError, match="覆盖"):
        publisher.publish_complete(tmp_path, ["S22", "S23"])
    assert visitor_rows() == before
    with isolated_database() as conn:
        assert conn.execute(
            "SELECT count(*) AS n FROM bluff_review_publications WHERE inference_version = %s",
            ("changed-first-season",),
        ).fetchone()["n"] == 0


def test_empty_website_database_rebuild_preserves_all_public_ids_and_urls(isolated_database):
    root = Path(__file__).resolve().parents[2]
    expected = json.loads((root / "website/assets/people.json").read_text(encoding="utf-8"))["people"]
    with isolated_database() as conn:
        assert conn.execute("SELECT count(*) AS n FROM players").fetchone()["n"] == 0
    result = publisher.publish(root, ["S21", "S22", "S23"], activate=False)
    with isolated_database() as conn:
        rows = conn.execute("SELECT name, id FROM players WHERE release_id = %s", (result["id"],)).fetchall()
    rebuilt = {row["name"]: row["id"] for row in rows}
    assert rebuilt == expected
    assert {name: f"/players/{person_id}/" for name, person_id in rebuilt.items()} == {
        name: f"/players/{person_id}/" for name, person_id in expected.items()
    }


def test_used_person_mapping_changes_release_id(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[2]
    path = tmp_path / "website/assets/people.json"
    path.parent.mkdir(parents=True)
    shutil.copy2(root / "website/assets/people.json", path)
    entries = [{"dossier": {"seats": [{"name": "JY"}]}}]
    monkeypatch.setattr(publisher, "load_release", lambda *args: (entries, "a" * 64, "b" * 64))
    _, original, rules, identities = publisher.prepare_release(tmp_path, "S22")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["people"]["JY"] = str(uuid.uuid4())
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, changed, _, changed_ids = publisher.prepare_release(tmp_path, "S22")
    assert identities != changed_ids
    assert publisher._release_id("S22", original, rules) != publisher._release_id("S22", changed, rules)
