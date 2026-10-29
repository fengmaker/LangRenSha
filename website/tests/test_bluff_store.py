from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json

import pytest

from website.api import bluff_store, bluffs


def sample_game():
    return {
        "id": "game-1", "season": "TST", "date": "2026-06-01", "game_number": 1,
        "source": {"bvid": "BV1yt7v6QE3Q"},
        "seats": [
            {"seat": 1, "person_id": "wolf-1", "name": "狼甲", "role": "狼人", "faction": "werewolf"},
            {"seat": 2, "person_id": "good-1", "name": "好甲", "role": "平民", "faction": "good"},
            {"seat": 4, "person_id": "wolf-2", "name": "狼乙", "role": "机械狼", "faction": "werewolf"},
        ],
        "rounds": [{"number": 1, "day": [
            {"slot": "sheriff_result", "action": "elected", "targets": [1]},
            {"slot": "exile_result", "action": "exile", "targets": [2]},
        ]}],
        "voting": {"days": [{"day": 1, "sheriff": "recorded", "exile": "recorded"}], "ballots": []},
    }


def sample_payload(game=None):
    game = game or sample_game()
    return {
        "schema_version": 1,
        "season": "TST",
        "inference_version": "TST-v1",
        "games": [{
            "game_id": game["id"], "bvid": game["source"]["bvid"],
            "source_fingerprint": bluffs.source_fingerprint(game),
            "assessments": [
                {"seat": 1, "name": "狼甲", "physical_role": "狼人", "decision": "yes",
                 "claimed_role": "预言家",
                 "claim_day": 1, "verification_status": "assistant_inferred",
                 "evidence": [{"kind": "recap", "text": "公开自称信息神"}]},
                {"seat": 4, "name": "狼乙", "physical_role": "机械狼", "decision": "no",
                 "verification_status": "assistant_inferred", "evidence": []},
            ],
        }],
    }


def test_validate_review_binds_all_games_and_wolf_seats_to_published_snapshots():
    game = sample_game()
    items, summary = bluff_store._validate_review([game], sample_payload(game), "TST", 1)

    assert len(items) == 2
    assert [(item["seat"], item["decision"], item["success"]) for item in items] == [
        (1, "yes", True), (4, "no", None),
    ]
    assert summary == {
        "game_count": 1, "wolf_count": 2, "yes_count": 1, "success_count": 1,
        "pending_count": 0, "user_confirmed_count": 0,
    }


def test_current_s22_payload_retains_accepted_scope_and_totals():
    payload = json.loads((bluffs.ASSET_ROOT / "S22.json").read_text(encoding="utf-8"))
    rows = [assessment for game in payload["games"] for assessment in game["assessments"]]
    summary = payload["summary"]

    assert len(payload["games"]) == summary["games_total"] == summary["games_assessed"] == 148
    assert len(rows) == summary["wolf_appearances"] == 586
    assert summary["decisions"]["yes"] == 121
    assert summary["successful_bluffs"] == 46
    assert summary["pending"] == 0
    assert summary["user_confirmed_records"] == 46


@pytest.mark.parametrize("mutation", ["missing_game", "duplicate_game", "stale_fingerprint", "changed_name",
                                       "changed_role", "missing_wolf", "duplicate_seat", "invalid_decision"])
def test_validate_review_rejects_incomplete_stale_or_invalid_payload(mutation):
    game = sample_game()
    payload = sample_payload(game)
    reviewed = payload["games"][0]
    if mutation == "missing_game":
        payload["games"] = []
    elif mutation == "duplicate_game":
        payload["games"].append(deepcopy(reviewed))
    elif mutation == "stale_fingerprint":
        reviewed["source_fingerprint"] = "0" * 64
    elif mutation == "changed_name":
        reviewed["assessments"][0]["name"] = "改名"
    elif mutation == "changed_role":
        reviewed["assessments"][0]["physical_role"] = "平民"
    elif mutation == "missing_wolf":
        reviewed["assessments"].pop()
    elif mutation == "duplicate_seat":
        reviewed["assessments"].append(deepcopy(reviewed["assessments"][0]))
    elif mutation == "invalid_decision":
        reviewed["assessments"][0]["decision"] = "maybe"

    with pytest.raises(bluff_store.BluffReviewError):
        bluff_store._validate_review([game], payload, "TST", 1)


def test_yes_requires_a_supported_claimed_role_except_for_confirmed_missing_metadata():
    game = sample_game()
    payload = sample_payload(game)
    payload["games"][0]["assessments"][0]["claimed_role"] = None
    with pytest.raises(bluff_store.BluffReviewError, match="悍跳身份"):
        bluff_store._validate_review([game], payload, "TST", 1)

    assessment = payload["games"][0]["assessments"][0]
    assessment.update(verification_status="user_confirmed", claim_day="later")
    items, summary = bluff_store._validate_review([game], payload, "TST", 1)

    confirmed = next(item for item in items if item["seat"] == 1)
    assert confirmed["decision"] == "yes"
    assert confirmed["success"] is None
    assert confirmed["needs_review"] is True
    assert "所跳身份尚待补充" in " ".join(confirmed["review_questions"])
    assert summary["pending_count"] == 1


def test_manual_results_accept_selected_mixed_blood_and_do_not_require_unasked_metadata():
    game = sample_game()
    game['seats'].append({'seat': 7, 'person_id': 'mixed', 'name': '混甲', 'role': '混血儿', 'faction': 'werewolf'})
    payload = sample_payload(game)
    first = payload['games'][0]['assessments'][0]
    first.update(verification_status='user_confirmed', manual_success=False, claimed_role=None, claim_day=None)
    payload['games'][0]['assessments'].append({
        'seat': 7, 'name': '混甲', 'physical_role': '混血儿', 'decision': 'yes',
        'verification_status': 'user_confirmed', 'manual_included': True, 'manual_success': True,
        'claimed_role': None, 'claim_day': None, 'evidence': [],
    })
    items, summary = bluff_store._validate_review([game], payload, 'TST', 1)
    assert [(i['seat'], i['success']) for i in items] == [(1, False), (4, None), (7, True)]
    assert not any(i['needs_review'] for i in items)
    assert summary['yes_count'] == 2 and summary['success_count'] == 1


@pytest.mark.parametrize('mutation', ['non_boolean', 'unconfirmed', 'no_decision', 'unconfirmed_inclusion'])
def test_manual_overrides_require_valid_values_and_explicit_user_confirmation(mutation):
    game = sample_game()
    payload = sample_payload(game)
    row = payload['games'][0]['assessments'][0]
    row.update(verification_status='user_confirmed', manual_success=True)
    if mutation == 'non_boolean': row['manual_success'] = 1
    elif mutation == 'unconfirmed': row['verification_status'] = 'assistant_inferred'
    elif mutation == 'no_decision': row['decision'] = 'no'
    else:
        row.pop('manual_success')
        row.update(verification_status='assistant_inferred', manual_included=True)
    with pytest.raises(bluff_store.BluffReviewError):
        bluff_store._validate_review([game], payload, 'TST', 1)


@pytest.mark.parametrize("status,decision", [
    ("user_uncertain", "uncertain"),
    ("user_comment", "no"),
])
def test_builder_human_review_statuses_are_accepted(status, decision):
    game = sample_game()
    payload = sample_payload(game)
    payload["games"][0]["assessments"][1].update(verification_status=status, decision=decision)

    items, _ = bluff_store._validate_review([game], payload, "TST", 1)

    assert next(item for item in items if item["seat"] == 4)["decision"] == decision


@pytest.mark.parametrize("claim_day", [0, 3, True, "first", [], {}])
def test_invalid_claim_day_values_are_rejected(claim_day):
    game = sample_game()
    payload = sample_payload(game)
    payload["games"][0]["assessments"][0]["claim_day"] = claim_day

    with pytest.raises(bluff_store.BluffReviewError, match="起跳天数"):
        bluff_store._validate_review([game], payload, "TST", 1)


class FakeCursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, game, *, existing_payload_hash=None, active_publication=None):
        self.game = game
        self.existing_payload_hash = existing_payload_hash
        self.active_publication = active_publication
        self.executed = []
        self.transaction_count = 0
        self.closed = False

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield

    def execute(self, query, params=None, **kwargs):
        text = str(query)
        self.executed.append((text, params))
        if text.startswith("SELECT r.id, r.season, r.game_count"):
            return FakeCursor({"id": "release-1", "season": "TST", "game_count": 1})
        if text.startswith("SELECT count(*) AS count FROM games"):
            return FakeCursor({"count": 1})
        if text.startswith("SELECT id, snapshot FROM games"):
            return FakeCursor(rows=[{"id": self.game["id"], "snapshot": self.game}])
        if text.startswith("SELECT publication_id FROM active_bluff_reviews"):
            row = ({"publication_id": self.active_publication} if self.active_publication else None)
            return FakeCursor(row)
        if text.startswith("SELECT payload_hash FROM bluff_review_publications"):
            row = ({"payload_hash": self.existing_payload_hash} if self.existing_payload_hash else None)
            return FakeCursor(row)
        if text.startswith("SELECT count(*) AS item_count"):
            return FakeCursor({"item_count": 2})
        return FakeCursor()

    def close(self):
        self.closed = True


def test_read_review_returns_empty_when_no_database_publication_exists():
    class Connection:
        def execute(self, query, params):
            assert "active_bluff_reviews" in str(query)
            assert params == ("release-1", "TST")
            return FakeCursor()

    assert bluff_store.read_review(Connection(), "release-1", "TST") == {"games": []}


def test_read_review_returns_database_payload_without_file_fallback():
    payload = {"season": "TST", "games": [{"game_id": "game-1"}]}

    class Connection:
        def execute(self, query, params):
            return FakeCursor({"payload": payload})

    assert bluff_store.read_review(Connection(), "release-1", "TST") is payload


def test_check_mode_validates_active_snapshots_without_issuing_writes(monkeypatch, tmp_path):
    game = sample_game()
    payload = sample_payload(game)
    path = tmp_path / "review.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    conn = FakeConnection(game)
    monkeypatch.setattr(bluff_store.publisher, "_connect", lambda schema: conn)

    result = bluff_store.publish_review("TST", path, check=True)

    assert result["checked"] is True and result["published"] is False
    assert result["game_count"] == 1 and result["wolf_count"] == 2
    assert conn.transaction_count == 1 and conn.closed
    assert all(not query.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))
               for query, _ in conn.executed)


def test_apply_writes_version_items_and_active_pointer_in_one_transaction(monkeypatch, tmp_path):
    game = sample_game()
    payload = sample_payload(game)
    path = tmp_path / "review.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    conn = FakeConnection(game)
    monkeypatch.setattr(bluff_store.publisher, "_connect", lambda schema: conn)
    monkeypatch.setattr(bluff_store.publisher, "_create_schema", lambda connection: None)

    result = bluff_store.publish_review("TST", path)

    queries = [query for query, _ in conn.executed]
    assert result["published"] is True and result["idempotent"] is False
    assert conn.transaction_count == 1 and conn.closed
    assert sum(query.startswith("INSERT INTO bluff_review_items") for query in queries) == 2
    assert any(query.startswith("INSERT INTO bluff_review_publications") for query in queries)
    assert any(query.startswith("INSERT INTO active_bluff_reviews") for query in queries)


def test_apply_of_same_version_is_idempotent(monkeypatch, tmp_path):
    game = sample_game()
    payload = sample_payload(game)
    path = tmp_path / "review.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    publication_id = "bluff-" + bluff_store._sha256(bluff_store._canonical_json({
        "release_id": "release-1", "season": "TST", "inference_version": "TST-v1",
        "payload_hash": bluff_store._sha256(bluff_store._canonical_json(payload)),
    }))
    payload_hash = bluff_store._sha256(bluff_store._canonical_json(payload))
    conn = FakeConnection(game, existing_payload_hash=payload_hash, active_publication=publication_id)
    monkeypatch.setattr(bluff_store.publisher, "_connect", lambda schema: conn)
    monkeypatch.setattr(bluff_store.publisher, "_create_schema", lambda connection: None)

    result = bluff_store.publish_review("TST", path)

    assert result["published"] is True and result["idempotent"] is True
    assert not any(query.startswith("INSERT INTO bluff_review_items") for query, _ in conn.executed)
