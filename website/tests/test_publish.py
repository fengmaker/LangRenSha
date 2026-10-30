from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import shutil

import pytest

from website.api import publisher


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = "BV1yt7v6QE3Q"
DEFAULT_BASIS = "本轮票权由已核死亡及存活唯一确定；未播报投向按既有用户口径默认弃票"


@pytest.mark.parametrize(("stored_code", "canonical_code"), [
    ("s21_mechanical_wolf_seer", "mechanical_wolf_seer"),
    ("s21_seer_witch_hunter_white_mixed", "mixed_blood"),
    ("s21_guile_realm", "guile_realm"),
    ("s21_treasure_master", "treasure_master"),
    ("s21_masquerade", "masquerade"),
    ("s21_neighbor_puppet", "neighbor_puppet"),
    ("s21_all_in", "all_in"),
    ("s21_wolf_king_guard", "wolf_king_guard"),
])
def test_publication_merges_storage_variants_into_the_same_public_board(stored_code, canonical_code):
    _, rules = publisher._logical_rules(ROOT, "S21")

    def publish_board(code):
        dossier = {"slug": "bili-BVfixture1234-p01", "season": "S21", "date": "2026-03-03",
                   "phase": "regular", "board": code, "winner": None, "seats": [], "rounds": []}
        doc = publisher._public_game(dossier, {}, {}, None, rules["boards"][code], {})
        assert dossier["board"] == code
        assert rules["boards"][code]["code"] == code
        return doc["board"]

    assert publish_board(stored_code) == publish_board(canonical_code)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _publication_fixture(root: Path, *, with_derivations: bool = True) -> tuple[Path, dict]:
    from scripts.game_derivations import fingerprint, rule_sources

    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    for name in ("seasons.json", "game_rules.json"):
        shutil.copy2(ROOT / "config" / name, config / name)
    shutil.copytree(ROOT / "config/board_templates", config / "board_templates")

    slug = f"S22_{SAMPLE}_p01_g01"
    folder = root / "data/games/S22" / slug
    dossier = {
        "slug": slug, "season": "S22", "date": "2026-06-01", "phase": "regular",
        "game_number": 1, "board": "mixed_blood", "winner": None, "seats": [],
        "rounds": [{"number": 1, "night": [], "day": []}],
    }
    voting = {
        "game_slug": slug, "registrations": [], "interruptions": [], "days": [],
        "ballots": [{
            "id": "exile-1", "day": 1, "kind": "exile", "number": 1,
            "stage": "initial", "status": "partial", "candidates": None,
            "eligible_voters": None, "votes": [
                {"voter": 1, "target": None, "state": "abstained", "basis": "recorded"},
            ],
        }],
    }
    endgame = {"game_slug": slug, "phases": []}
    _write_json(folder / "dossier.json", dossier)
    _write_json(folder / "voting.json", voting)
    _write_json(folder / "endgame.json", endgame)
    _write_json(root / "data/extractions/S22/voting" / f"{SAMPLE}.json", {
        "facts": deepcopy(voting), "rule_applications": [],
    })

    output_dossier, output_voting = deepcopy(dossier), deepcopy(voting)
    output_dossier["winner"] = "good"
    output_voting["ballots"][0]["votes"][0]["basis"] = DEFAULT_BASIS
    report = {
        "schema_version": 1, "version": 1, "game_slug": slug,
        "input_hashes": {
            "dossier": fingerprint(dossier), "voting": fingerprint(voting),
            "supplemental": fingerprint(None), "endgame": fingerprint(endgame),
        },
        "output_hashes": {
            "dossier": fingerprint(output_dossier), "voting": fingerprint(output_voting),
        },
        "rule_sources": rule_sources(),
        "terminal": {"round": 1, "phase": "day", "basis": "fixture"},
        "rounds": [{"day": 1, "dead_before_night": [], "night_deaths": [],
                    "night_deaths_complete": True, "living_before_vote": [1, 2],
                    "living_after_day": [2], "known_departed_after_day": [1]}],
        "slot_states": [{"round": 1, "phase": "night", "slot": "witch_save",
                         "actor": 1, "status": "unavailable", "reason": "actor_departed",
                         "legal_targets": [2], "review_required": True,
                         "consequences": [{"type": "wolf_attack_immunity", "seat": 2,
                                           "rule": "dreamer_target_immune_to_wolf_attack_that_night",
                                           "source_path": "C:/private/source.json"}],
                         "source_path": "C:/private/source.json"}],
        "review_tasks": [{"source_path": "C:/private/review.json"}],
        "issues": [{"code": "illegal_targets", "source_path": "C:/private/source.json",
                    "detail": "private detail"}],
        "changes": [
            {"path": ["dossier", "winner"], "before": None, "after": "good"},
            {"path": ["voting", "ballots", 0, "votes", 0, "basis"],
             "before": "recorded", "after": DEFAULT_BASIS},
        ],
    }
    if with_derivations:
        _write_json(folder / "rule_derivations.json", report)
    return folder, report


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
    from scripts.rule_config import load_formal_rules, load_scope
    formal = load_formal_rules("S22", ROOT)
    scope = load_scope("S22", ROOT)
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
    raw_votings = [json.loads((item["folder"] / "voting.json").read_text(encoding="utf-8-sig"))
                   for item in entries]
    raw_ballot_count = sum(len(raw.get("ballots", [])) for raw in raw_votings)
    raw_vote_count = sum(len(ballot.get("votes", []))
                         for raw in raw_votings for ballot in raw.get("ballots", []))
    assert seat_count == 1776
    # Read the formal JSON files independently of load_publication so a dropped
    # round or vote remains visible without pinning a stale season total.
    assert ballot_count == raw_ballot_count
    assert vote_count == raw_vote_count


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
    # Keep this contract test independent of further source review completing
    # the last unknown in the real game.
    dossier = deepcopy(item["dossier"])
    event = next(e for e in dossier["rounds"][0]["night"] if e["slot"] == "witch_save")
    event.update(action="unknown", targets=[], result=None)
    ids = {seat["name"]: "00000000-0000-0000-0000-000000000001"
           for seat in item["dossier"]["seats"]}
    doc = publisher._public_game(dossier, item["voting"], item["endgame"], item["audit"],
                                 item["board"], ids, source_voting=item.get("source_voting"),
                                 derivations=None)
    assert doc["ballot_count"] == 0
    assert doc["voting"]["ballots"] == []
    assert any("不表示该局投票数为零" in note for note in doc["voting"]["notes"])
    events = [event for round_ in doc["rounds"] for phase in ("night", "day") for event in round_[phase]]
    assert all("slot_label" in event and "description" in event for event in events)
    assert {event["action"] for event in events} >= {"unknown", "pass"}
    unknown = next(event for event in events if event["action"] == "unknown")
    passed = next(event for event in events if event["action"] == "pass")
    assert "未知" in unknown["description"] and "不行动" in passed["description"]
    assert unknown["description"].startswith("首夜，")


def test_public_snapshot_excludes_source_paths_and_review_text():
    entries, _, _ = publisher.load_publication(ROOT, "S22", SAMPLE)
    item = entries[0]
    identities = {seat["name"]: "person" for seat in item["dossier"]["seats"]}
    doc = publisher._public_game(item["dossier"], item["voting"], item["endgame"], item["audit"],
                                 item["board"], identities, source_voting=item.get("source_voting"),
                                 derivations=item.get("derivations"))
    assert set(doc["source"]) == {"url", "bvid"}
    assert "files" not in doc and "evidence" not in doc and "transcript" not in doc
    assert "voting_audit" not in json.dumps(doc, ensure_ascii=False)
    assert "data/" not in json.dumps(doc, ensure_ascii=False)
    assert "source_path" not in json.dumps(doc, ensure_ascii=False)


def test_publication_consumes_precomputed_rules_without_rerunning(monkeypatch, tmp_path):
    from scripts import game_derivations

    _publication_fixture(tmp_path)
    monkeypatch.setattr(
        game_derivations, "derive_game",
        lambda *args, **kwargs: pytest.fail("publisher reran game derivation"),
    )
    entries, _, _ = publisher.load_publication(tmp_path, "S22", SAMPLE)
    item = entries[0]
    assert item["dossier"]["winner"] == "good"
    assert item["voting"]["ballots"][0]["votes"][0]["basis"] == DEFAULT_BASIS
    assert item["source_voting"] == item["audit"]["facts"]
    assert item["dossier"]["_publication_context"]["terminal_observation"] == {
        "round": 1, "phase": "day",
    }
    assert "rule_derivations" in item["source_hashes"]

    person_ids = {}
    doc = publisher._public_game(
        item["dossier"], item["voting"], item["endgame"], item["audit"], item["board"], person_ids,
        source_voting=item["source_voting"], derivations=item["derivations"],
    )
    assert doc["voting"]["ballots"][0]["votes"][0]["basis"] == "rule_default"
    assert doc["rules_state"]["living"][0]["living_before_vote"] == [1, 2]
    assert doc["rules_state"]["slots"] == [{
        "round": 1, "phase": "night", "slot": "witch_save", "status": "unavailable",
        "reason": "actor_departed", "legal_targets": [2], "review_required": True,
        "consequences": [{"type": "wolf_attack_immunity", "seat": 2,
                          "rule": "dreamer_target_immune_to_wolf_attack_that_night"}],
    }]
    assert doc["rules_state"]["issues"] == ["illegal_targets"]
    assert "档案确认本局在第一天白天结束。" in doc["data_notes"]
    assert "source_path" not in json.dumps(doc, ensure_ascii=False)
    assert "private detail" not in json.dumps(doc, ensure_ascii=False)
    assert set(doc["bluff_source_binding"]) == {"derived_fingerprint", "source_fingerprint"}
    assert doc["presentation"]


def test_materialized_derived_voting_still_binds_audit_to_original_input(tmp_path):
    folder, _ = _publication_fixture(tmp_path)
    dossier_path, voting_path = folder / "dossier.json", folder / "voting.json"
    dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
    voting = json.loads(voting_path.read_text(encoding="utf-8"))
    dossier["winner"] = "good"
    voting["ballots"][0]["votes"][0]["basis"] = DEFAULT_BASIS
    _write_json(dossier_path, dossier)
    _write_json(voting_path, voting)

    entries, _, _ = publisher.load_publication(tmp_path, "S22", SAMPLE)
    item = entries[0]
    assert item["source_voting"] == item["voting"]
    assert item["audit"]["facts"]["ballots"][0]["votes"][0]["basis"] == "recorded"
    doc = publisher._public_game(
        item["dossier"], item["voting"], item["endgame"], item["audit"], item["board"], {},
        source_voting=item["source_voting"], derivations=item["derivations"],
    )
    assert doc["winner"] == "good"
    assert doc["voting"]["ballots"][0]["votes"][0]["basis"] == "rule_default"


def test_audit_voting_mismatch_stays_strict_without_a_precomputed_report(tmp_path):
    _publication_fixture(tmp_path, with_derivations=False)
    entries, _, _ = publisher.load_publication(tmp_path, "S22", SAMPLE)
    item = entries[0]
    audit = deepcopy(item["audit"])
    audit["facts"]["game_slug"] = "different-game"
    with pytest.raises(publisher.PublishError, match="投票旁证"):
        publisher._public_game(
            item["dossier"], item["voting"], item["endgame"], audit, item["board"], {},
            source_voting=item["source_voting"],
        )


def test_stale_precomputed_rules_are_rejected(tmp_path):
    folder, _ = _publication_fixture(tmp_path)
    dossier_path = folder / "dossier.json"
    dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
    dossier["referee"] = "source changed"
    _write_json(dossier_path, dossier)
    with pytest.raises(publisher.PublishError, match="已变化|过期"):
        publisher.load_publication(tmp_path, "S22", SAMPLE)


def test_rule_derivation_sidecar_bytes_change_publication_source_hash(tmp_path):
    folder, report = _publication_fixture(tmp_path, with_derivations=False)
    _, source_without, _ = publisher.load_publication(tmp_path, "S22", SAMPLE)
    _write_json(folder / "rule_derivations.json", report)
    entries, source_with, _ = publisher.load_publication(tmp_path, "S22", SAMPLE)
    assert source_with != source_without
    assert "rule_derivations" in entries[0]["source_hashes"]


def test_bluff_evidence_source_hashes_ignore_candidate_and_receipt_json(tmp_path):
    folder, _ = _publication_fixture(tmp_path, with_derivations=False)
    transcript = folder / "evidence.txt"
    transcript.write_text("第一版发言证据", encoding="utf-8")
    dossier_path = folder / "dossier.json"
    dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
    dossier["files"] = [{"role": "transcript", "path": transcript.relative_to(tmp_path).as_posix()}]
    _write_json(dossier_path, dossier)
    _, source_before, _ = publisher.load_publication(tmp_path, "S22", SAMPLE)

    for name in ("dossier.candidate.json", "voting.candidate.json",
                 "formal_import_receipt.json", "ai_review.json"):
        _write_json(folder / name, {"changed": False})
    _, source_with_candidates, _ = publisher.load_publication(tmp_path, "S22", SAMPLE)
    assert source_with_candidates == source_before

    transcript.write_text("第二版发言证据", encoding="utf-8")
    _, source_after_evidence_change, _ = publisher.load_publication(tmp_path, "S22", SAMPLE)
    assert source_after_evidence_change != source_with_candidates


def test_bound_sheriff_evidence_is_checked_without_rerunning_parser(tmp_path, monkeypatch):
    import hashlib
    from scripts.game_derivations import fingerprint
    from scripts import sheriff_speech_evidence

    folder, report = _publication_fixture(tmp_path)
    source = tmp_path / "selected.json"
    source.write_text('{"segments": []}', encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    supplemental = {"game_slug": report["game_slug"], "source_binding": {
        "selected_transcript_path": "selected.json", "selected_transcript_sha256": digest}}
    speech = {"rounds": [], "evidence": [], "gaps": [],
              "source_binding": {"path": "selected.json", "sha256": digest}}
    report["input_hashes"]["supplemental"] = fingerprint(supplemental)
    report["input_hashes"]["speech_evidence"] = fingerprint(speech)
    report["sheriff_speech_evidence"] = speech
    _write_json(folder / "supplemental.json", supplemental)
    _write_json(folder / "rule_derivations.json", report)

    def forbidden(*args, **kwargs):
        raise AssertionError("publication must consume prepared evidence")
    monkeypatch.setattr(sheriff_speech_evidence, "analyze_sheriff_speeches", forbidden)
    assert publisher.load_publication(tmp_path, "S22", SAMPLE)[0]
    source.write_text('{"segments": [], "edited": true}', encoding="utf-8")
    with pytest.raises(publisher.PublishError, match="警上发言旁证的字幕来源已变化"):
        publisher.load_publication(tmp_path, "S22", SAMPLE)


def test_game_detail_uses_persisted_presentation_and_keeps_legacy_fallback(monkeypatch):
    from website.api import app

    assert "rules_state" in app.GameDetail.model_fields
    stored = {"id": "game", "presentation": {"rounds": [{"number": 9}]}}
    monkeypatch.setattr(app, "_release", lambda conn: {"id": "release"})
    monkeypatch.setattr(app, "_resolved_snapshot", lambda snapshot: snapshot)

    class Conn:
        def __init__(self, snapshot):
            self.snapshot = snapshot

        def execute(self, *args):
            snapshot = self.snapshot

            class Cursor:
                def fetchone(self):
                    return {"snapshot": snapshot}

            return Cursor()

    monkeypatch.setattr(
        app, "build_game_presentation",
        lambda snapshot: {"legacy": True},
    )
    assert app.game_detail("game", Conn(stored))["presentation"] == stored["presentation"]
    assert app.game_detail("game", Conn({"id": "old"}))["presentation"] == {"legacy": True}


def test_explicit_unknown_faction_and_nullable_role_round_trip_without_publish_inference():
    from website.api.app import GameSummary, _summary

    entries, _, _ = publisher.load_publication(ROOT, "S22")
    # Upstream rules now resolve ordinary factions in the real data. Test the
    # publication boundary with an explicit unknown input rather than relying
    # on a particular unresolved historical game remaining unresolved forever.
    item = deepcopy(entries[0])
    item["dossier"]["seats"][0]["faction"] = None
    identities = {seat["name"]: "stable-id" for seat in item["dossier"]["seats"]}
    doc = publisher._public_game(item["dossier"], item["voting"], item["endgame"], item["audit"],
                                 item["board"], identities, source_voting=item.get("source_voting"),
                                 derivations=item.get("derivations"))
    source_unknown = next(seat for seat in item["dossier"]["seats"] if seat.get("faction") is None)
    published_unknown = next(seat for seat in doc["seats"] if seat["seat"] == source_unknown["seat"])
    assert published_unknown["faction"] is None
    assert "部分座位阵营待核" in " ".join(doc["data_notes"])

    # Current formal data has no null roles; verify the same boundary with an
    # in-memory source variant, without modifying any source file.
    variant = deepcopy(item["dossier"])
    variant["seats"][0]["role"] = None
    variant_doc = publisher._public_game(variant, item["voting"], item["endgame"], item["audit"],
                                         item["board"], identities,
                                         source_voting=item.get("source_voting"),
                                         derivations=item.get("derivations"))
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
