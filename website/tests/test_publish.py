from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from website.api import publisher


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = "BV1yt7v6QE3Q"


def _active_release_id() -> str | None:
    conn = publisher._connect("masters_web")
    try:
        row = conn.execute(
            "SELECT release_id FROM active_release WHERE singleton=true"
        ).fetchone()
        return row["release_id"] if row else None
    finally:
        conn.close()


def _require_published_db() -> None:
    try:
        active = _active_release_id()
    except Exception as exc:  # pragma: no cover - depends on local PostgreSQL availability
        pytest.skip(f"masters_web integration database is unavailable: {type(exc).__name__}")
    if not active:
        pytest.skip("Publish a sample release before running the API integration tests")


def test_formal_scope_and_source_totals_are_derived_from_current_files():
    entries, source_hash, rules_hash = publisher.load_publication(ROOT, "S22")
    formal = json.loads((ROOT / "config/S22_formal_rules.json").read_text(encoding="utf-8"))
    scope = json.loads((ROOT / "config/S22_game_scope.json").read_text(encoding="utf-8"))
    assert len(entries) == formal["scope"]["scored_total"] == 148
    assert len(source_hash) == len(rules_hash) == 64
    assert len({item["dossier"]["slug"] for item in entries}) == len(entries)
    assert all(item["dossier"]["season"] == "S22" for item in entries)
    assert all(item["dossier"]["phase"] in scope["retained_phases"] for item in entries)
    assert all(item["dossier"]["board"] not in scope["excluded_board_codes"] for item in entries)
    assert all(item["audit"] is not None for item in entries)
    seat_count = sum(len(item["dossier"]["seats"]) for item in entries)
    ballot_count = sum(len(item["voting"]["ballots"]) for item in entries)
    vote_count = sum(len(ballot["votes"]) for item in entries for ballot in item["voting"]["ballots"])
    assert seat_count == 1776
    assert ballot_count == 347
    assert vote_count == 2513


def test_unknown_states_and_default_abstentions_keep_distinct_meanings():
    ballot = {
        "id": "ballot-1", "day": 1, "kind": "exile", "number": 1, "stage": "initial",
        "status": "partial", "votes": [
            {"voter": 1, "target": None, "state": "abstained"},
            {"voter": 2, "target": None, "state": "abstained"},
            {"voter": 3, "target": 4, "state": "cast"},
        ],
    }
    cleaned = publisher._clean_ballot(ballot, {("ballot-1", 1)})
    assert [vote["basis"] for vote in cleaned["votes"]] == ["rule_default", "abstained", "recorded"]
    assert cleaned["votes"][0]["state"] == cleaned["votes"][1]["state"] == "abstained"

    entries, _, _ = publisher.load_publication(ROOT, "S22", SAMPLE)
    item = entries[0]
    ids = {seat["name"]: "00000000-0000-0000-0000-000000000001"
           for seat in item["dossier"]["seats"]}
    doc = publisher._public_game(item["dossier"], item["voting"], item["endgame"], item["audit"],
                                 item["board"], ids)
    assert doc["ballot_count"] == 0
    assert doc["voting"]["ballots"] == []
    assert any("不表示该局投票数为零" in note for note in doc["voting"]["notes"])
    events = [event for round_ in doc["rounds"] for phase in ("night", "day") for event in round_[phase]]
    assert all("slot_label" in event and "description" in event for event in events)
    assert {event["action"] for event in events} >= {"unknown", "pass"}
    unknown = next(event for event in events if event["action"] == "unknown")
    passed = next(event for event in events if event["action"] == "pass")
    assert "未知" in unknown["description"] and "不行动" in passed["description"]


def test_public_snapshot_excludes_source_paths_and_review_text():
    entries, _, _ = publisher.load_publication(ROOT, "S22", SAMPLE)
    item = entries[0]
    identities = {seat["name"]: "person" for seat in item["dossier"]["seats"]}
    doc = publisher._public_game(item["dossier"], item["voting"], item["endgame"], item["audit"],
                                 item["board"], identities)
    assert set(doc["source"]) == {"url", "bvid"}
    assert "files" not in doc and "evidence" not in doc and "transcript" not in doc
    assert "voting_audit" not in json.dumps(doc, ensure_ascii=False)
    assert "data/" not in json.dumps(doc, ensure_ascii=False)
    assert "source_path" not in json.dumps(doc, ensure_ascii=False)


def test_real_unknown_faction_and_nullable_role_round_trip_without_inference():
    from website.api.app import GameSummary, _summary

    entries, _, _ = publisher.load_publication(ROOT, "S22")
    item = next(item for item in entries if any(seat.get("faction") is None
                                                 for seat in item["dossier"]["seats"]))
    identities = {seat["name"]: "stable-id" for seat in item["dossier"]["seats"]}
    doc = publisher._public_game(item["dossier"], item["voting"], item["endgame"], item["audit"],
                                 item["board"], identities)
    source_unknown = next(seat for seat in item["dossier"]["seats"] if seat.get("faction") is None)
    published_unknown = next(seat for seat in doc["seats"] if seat["seat"] == source_unknown["seat"])
    assert published_unknown["faction"] is None
    assert "部分座位阵营待核" in " ".join(doc["data_notes"])

    # Current formal data has no null roles; verify the same boundary with an
    # in-memory source variant, without modifying any source file.
    variant = deepcopy(item["dossier"])
    variant["seats"][0]["role"] = None
    variant_doc = publisher._public_game(variant, item["voting"], item["endgame"], item["audit"],
                                         item["board"], identities)
    assert variant_doc["seats"][0]["role"] is None
    assert "部分座位身份待核" in " ".join(variant_doc["data_notes"])
    GameSummary.model_validate(_summary(variant_doc))


def test_publish_failure_does_not_change_active_release(monkeypatch):
    _require_published_db()
    previous = _active_release_id()
    failure_id = "test-forced-activation-failure"
    monkeypatch.setattr(publisher, "_release_id", lambda *args: failure_id)
    real_connect = publisher._connect

    class FailAtActivation:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def execute(self, query, *args, **kwargs):
            if str(query).startswith("INSERT INTO active_release"):
                raise RuntimeError("forced activation failure")
            return self._conn.execute(query, *args, **kwargs)

    monkeypatch.setattr(publisher, "_connect", lambda schema: FailAtActivation(real_connect(schema)))
    with pytest.raises(RuntimeError):
        publisher.publish(ROOT, "S22", SAMPLE, activate=True)
    assert _active_release_id() == previous
    conn = publisher._connect("masters_web")
    try:
        assert conn.execute("SELECT 1 FROM releases WHERE id=%s", (failure_id,)).fetchone() is None
    finally:
        conn.close()


def test_publish_is_idempotent_and_can_leave_active_pointer_unchanged():
    _require_published_db()
    previous = _active_release_id()
    first = publisher.publish(ROOT, "S22", SAMPLE, activate=False)
    second = publisher.publish(ROOT, "S22", SAMPLE, activate=False)
    assert first["id"] == second["id"]
    assert second["idempotent"] is True
    assert first["activated"] is second["activated"] is False
    assert _active_release_id() == previous


def test_schema_and_api_have_no_dependency_on_legacy_views():
    sql_text = (ROOT / "website/api/schema.sql").read_text(encoding="utf-8").lower()
    app_text = (ROOT / "website/api/app.py").read_text(encoding="utf-8").lower()
    assert "current_game_" not in sql_text
    assert "current_game_" not in app_text
