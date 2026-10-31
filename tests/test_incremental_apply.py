import hashlib
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import apply_incremental_review as apply


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_prepared_hash_matches_the_formal_file_writer(tmp_path):
    from incremental_common import write_json

    value = {"name": "小苍", "nested": {"note": "第一行\n第二行"}}
    path = tmp_path / "formal.json"
    write_json(path, value)

    assert apply._json_sha256(value) == digest(path)


def test_cli_reports_codex_runtime_failure_as_json(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(apply, "apply_review",
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Codex unavailable")))

    assert apply.main([str(tmp_path / "review.json")]) == 1
    assert json.loads(capsys.readouterr().err) == {
        "state": "blocked", "error": "Codex unavailable"}


def candidate(slug="bili-BV1abc-p01-g01"):
    return {
        "dossier": {
            "slug": slug, "season": "S23", "date": "2026-10-01", "phase": "regular",
            "game_number": 1, "board": "s23_test", "winner": None, "files": [
                {"role": "transcript", "kind": "transcript", "platform": "bilibili",
                 "external_key": "BV1abc:123", "path": "data/source.json"},
            ], "rounds": [], "seats": [],
        },
        "voting": {"schema_version": 1, "game_slug": slug, "registrations": [],
                    "ballots": [], "interruptions": [], "days": []},
        "evidence": [], "issues": [],
    }


def setup_review(tmp_path: Path, *, reviewed=True, note=""):
    root = tmp_path
    source = root / "data" / "source.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({"source": {"bvid": "BV1abc", "cid": 123, "page": 1}}),
                      encoding="utf-8")
    entry = {"bvid": "BV1abc", "cid": 123, "page": 1,
             "labels": {"season": "S23"}, "duration_seconds": 60}
    folder = root / "data" / "extractions" / "S23" / "incremental" / "BV1abc_p01_cid123"
    folder.mkdir(parents=True)
    candidate_path = folder / "candidate.json"
    candidate_path.write_text(json.dumps(candidate()), encoding="utf-8")
    manifest = root / "data" / "raw" / "bilibili" / "BV1abc" / "p01" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    item = {"entry": entry, "analysis": "ready", "source_path": "data/source.json",
            "source_sha256": digest(source), "candidate_sha256": digest(candidate_path)}
    state = {"schema_version": 1, "season": "S23", "items": {"BV1abc:123:p01": item}, "weibo": {}}
    export = root / "review.json"
    export.write_text(json.dumps({"format": apply.REVIEW_FORMAT, "season": "S23", "games": [{
        "review_id": "BV1abc:123:p01", "bvid": "BV1abc", "cid": 123, "page": 1,
        "candidate_sha256": item["candidate_sha256"], "source_sha256": item["source_sha256"],
        "reviewed": reviewed, "note": note,
    }]}), encoding="utf-8")
    return root, state, export, candidate_path


def install_local_preflight_mocks(monkeypatch, state):
    monkeypatch.setattr(apply, "load_state", lambda root, season: state)
    import analyze_incremental, game_records, voting_records, media_ingest
    monkeypatch.setattr(analyze_incremental, "validate_candidate", lambda value, *a, **k: value)
    monkeypatch.setattr(game_records, "validate", lambda *a, **k: None)
    monkeypatch.setattr(voting_records, "validate", lambda *a, **k: None)
    import game_derivations
    monkeypatch.setattr(game_derivations, "derive_game", lambda dossier, voting, **kwargs: {
        "dossier": deepcopy(dossier), "voting": deepcopy(voting),
        "derivations": {"gaps": [], "issues": [], "changes": []},
    })
    monkeypatch.setattr(media_ingest, "validate_media", lambda path, bvid, page: {
        "manifest": {"bvid": bvid, "cid": 123, "page": page},
    })


def setup_v2_review(tmp_path):
    root, state, export, candidate_path = setup_review(tmp_path)
    value = candidate()
    value['dossier']['seats'] = [
        {'seat': 1, 'person_id': 'p1', 'name': '狼甲', 'role': '狼人', 'faction': 'werewolf'},
        {'seat': 2, 'person_id': 'p2', 'name': '混血乙', 'role': '混血儿', 'faction': 'good'},
    ]
    candidate_path.write_text(json.dumps(value), encoding='utf-8')
    item = state['items']['BV1abc:123:p01']
    item['candidate_sha256'] = digest(candidate_path)
    payload = json.loads(export.read_text(encoding='utf-8'))
    payload['format'] = apply.REVIEW_FORMAT_V2
    payload['games'][0]['candidate_sha256'] = item['candidate_sha256']
    payload['games'][0]['bluffs'] = [
        {'seat': 1, 'decision': 'yes', 'success': ''},
        {'seat': 2, 'decision': '', 'success': ''},
    ]
    export.write_text(json.dumps(payload), encoding='utf-8')
    return root, state, export, candidate_path, payload


def test_v2_choices_prepare_without_model_and_do_not_turn_blanks_into_no(tmp_path, monkeypatch):
    root, state, export, _, payload = setup_v2_review(tmp_path)
    install_local_preflight_mocks(monkeypatch, state)
    monkeypatch.setattr(apply, '_apply_note', lambda *a, **k: pytest.fail('model must not run'))

    _, plans = apply._prepare_export(export, 'S23', root=root, run_ai=False)

    record = plans[0]['review_record']
    assert record['bluffs_input'] == payload['games'][0]['bluffs']
    assert record['bluffs_review']['no_bluff'] is False
    assert [(row['seat'], row['decision'], row['success_selected'])
            for row in record['bluffs_review']['items']] == [(1, 'yes', False)]


@pytest.mark.parametrize('bad', [
    {'seat': 1, 'decision': 'no', 'success': 'success'},
    {'seat': True, 'decision': 'yes', 'success': ''},
    {'seat': 1, 'decision': [], 'success': ''},
    {'seat': 1, 'decision': 'yes', 'success': 'unknown'},
])
def test_v2_invalid_selection_rejected_before_any_application(tmp_path, monkeypatch, bad):
    root, state, export, _, payload = setup_v2_review(tmp_path)
    install_local_preflight_mocks(monkeypatch, state)
    payload['games'][0]['bluffs'][0] = bad
    export.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(apply.ReviewApplyError, match='悍跳选择'):
        apply._prepare_export(export, 'S23', root=root, run_ai=False)


def test_v2_blank_success_differs_from_explicit_uncertainty(tmp_path):
    from website.api import bluffs
    _, _, _, candidate_path, payload = setup_v2_review(tmp_path)
    value = json.loads(candidate_path.read_text(encoding='utf-8'))
    game = {**value['dossier'], 'id': value['dossier']['slug'],
            'source': {'bvid': 'BV1abc'}, 'voting': value['voting']}
    selection = payload['games'][0]
    plan = {'review_record': {'review_id': selection['review_id'], 'manual_sha256': 'a' * 64,
                            'note': '', 'bluffs_review': apply._selected_bluffs(selection, value, required=True)}}
    blank = apply._new_bluff_assessments(game, plan, bluffs)[0]
    assert blank['decision'] == 'yes' and 'manual_success' not in blank
    selection['bluffs'][0]['success'] = 'uncertain'
    plan['review_record']['bluffs_review'] = apply._selected_bluffs(selection, value, required=True)
    uncertain = apply._new_bluff_assessments(game, plan, bluffs)[0]
    assert 'manual_success' in uncertain and uncertain['manual_success'] is None


def test_v2_changed_choices_for_applied_game_require_revision(tmp_path, monkeypatch):
    root, state, export, candidate_path, payload = setup_v2_review(tmp_path)
    install_local_preflight_mocks(monkeypatch, state)
    folder = candidate_path.parent
    (folder / 'accepted_candidate.json').write_bytes(candidate_path.read_bytes())
    old = {**payload['games'][0], 'bluffs_input': deepcopy(payload['games'][0]['bluffs'])}
    old['bluffs_input'][0]['success'] = 'failure'
    (folder / 'accepted_review.json').write_text(json.dumps(old), encoding='utf-8')
    state['items']['BV1abc:123:p01']['phases'] = {'database': 'done'}
    with pytest.raises(apply.ReviewApplyError, match='正式修订流程'):
        apply._prepare_export(export, 'S23', root=root, run_ai=False)


def test_v2_blank_success_preserves_old_human_result_but_explicit_pending_revises(tmp_path, monkeypatch):
    from website.api import bluffs, publisher
    root, _, _, candidate_path, payload = setup_v2_review(tmp_path)
    value = json.loads(candidate_path.read_text(encoding='utf-8'))
    game = {**value['dossier'], 'id': value['dossier']['slug'],
            'source': {'bvid': 'BV1abc'}, 'voting': value['voting']}
    old = {'seat': 1, 'decision': 'yes', 'manual_success': True,
           'verification_status': 'user_confirmed', 'manual_note': '原人工结论'}
    asset = root / 'website/assets/bluffs/S23.json'
    asset.parent.mkdir(parents=True)
    asset.write_text(json.dumps({'schema_version': 1, 'season': 'S23', 'games': [{
        'game_id': game['id'], 'bvid': 'BV1abc', 'source_fingerprint': bluffs.source_fingerprint(game),
        'assessments': [old]}]}), encoding='utf-8')
    monkeypatch.setattr(publisher, 'load_publication', lambda *a: ([{
        'dossier': {}, 'voting': {}, 'endgame': {}, 'board': {}}], '', ''))
    monkeypatch.setattr(publisher, '_public_game', lambda *a, **k: game)
    monkeypatch.setattr(apply, 'save_state', lambda *a: None)
    selection = payload['games'][0]
    plan = {'game': selection, 'candidate': value, 'item': {}, 'review_record': {
        'review_id': selection['review_id'], 'manual_sha256': 'a' * 64, 'note': '',
        'bluffs_review': apply._selected_bluffs(selection, value, required=True)}}

    apply._merge_bluff_records(root, 'S23', [plan], {})
    assert json.loads(asset.read_text(encoding='utf-8'))['games'][0]['assessments'][0] == old

    selection['bluffs'][0]['success'] = 'uncertain'
    plan['review_record']['bluffs_review'] = apply._selected_bluffs(selection, value, required=True)
    apply._merge_bluff_records(root, 'S23', [plan], {})
    revised = json.loads(asset.read_text(encoding='utf-8'))['games'][0]['assessments'][0]
    assert revised['decision'] == 'yes' and revised['manual_success'] is None


def test_unreviewed_rows_are_ignored_without_needing_queue_membership(tmp_path, monkeypatch):
    root, state, export, _ = setup_review(tmp_path, reviewed=False)
    state["items"].clear()
    monkeypatch.setattr(apply, "load_state", lambda root, season: state)

    loaded, plans = apply._prepare_export(export, "S23", root=root, run_ai=False)

    assert loaded is state
    assert plans == []


def test_export_version_mismatch_blocks_before_import_preparation(tmp_path, monkeypatch):
    root, state, export, _ = setup_review(tmp_path)
    install_local_preflight_mocks(monkeypatch, state)
    payload = json.loads(export.read_text(encoding="utf-8"))
    payload["games"][0]["candidate_sha256"] = "f" * 64
    export.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(apply.ReviewApplyError, match="候选版本不匹配"):
        apply._prepare_export(export, "S23", root=root, run_ai=False)


def test_notes_apply_as_scoped_patches_and_blank_note_keeps_candidate(monkeypatch, tmp_path):
    import analyze_incremental, incremental_ai
    original = candidate()
    calls = []

    def fake_run_json(prompt, output, **kwargs):
        calls.append(prompt)
        return {"patches": [{"path": "/dossier/winner", "value": "good",
                             "note_quote": "确认好人胜", "reason": "按备注更正胜方"}],
                "unresolved": [],
                "bluffs": {"reviewed": False, "no_bluff": False, "items": []}}

    monkeypatch.setattr(incremental_ai, "run_json", fake_run_json)
    monkeypatch.setattr(analyze_incremental, "validate_candidate", lambda value, *a, **k: value)
    root = tmp_path
    (root / "data").mkdir()

    changed, patches, bluff_review, unresolved = apply._apply_note(
        original, "请确认好人胜", "BV1abc:123:p01", root=root)
    unchanged, no_patches, no_bluffs, no_unresolved = apply._apply_note(
        original, "   ", "BV1abc:123:p01", root=root)

    assert changed["dossier"]["winner"] == "good"
    assert patches[0]["note_quote"] == "确认好人胜"
    assert original["dossier"]["winner"] is None
    assert bluff_review == {"reviewed": False, "no_bluff": False, "items": []}
    assert unchanged == original
    assert no_patches == []
    assert no_bluffs == {"reviewed": False, "no_bluff": False, "items": []}
    assert unresolved == no_unresolved == []
    assert len(calls) == 1


def test_preview_shows_applied_changes_and_caches_only_local_preparation(tmp_path, monkeypatch):
    root, state, export, _ = setup_review(tmp_path, note="确认好人胜")
    install_local_preflight_mocks(monkeypatch, state)
    import analyze_incremental, incremental_ai

    calls = []

    def fake_run_json(prompt, output, **kwargs):
        calls.append(prompt)
        quote = "改判狼人胜" if "改判狼人胜" in prompt else "确认好人胜"
        return {"patches": [{"path": "/dossier/winner",
                             "value": "werewolf" if quote == "改判狼人胜" else "good",
                             "note_quote": quote, "reason": "备注明确胜方"}],
                "unresolved": [],
                "bluffs": {"reviewed": False, "no_bluff": False, "items": []}}

    monkeypatch.setattr(incremental_ai, "run_json", fake_run_json)
    monkeypatch.setattr(analyze_incremental, "validate_candidate", lambda value, *a, **k: value)

    report = apply.apply_review(export, season="S23", root=root, apply=False, run_ai=True)

    item = state["items"]["BV1abc:123:p01"]
    cached = json.loads((root / item["accepted_candidate_path"]).read_text(encoding="utf-8"))
    assert report["state"] == "prepared_cached"
    assert report["games"][0]["patches"][0]["value"] == "good"
    assert report["preview_path"] and (root / report["preview_path"]).is_file()
    assert cached["dossier"]["winner"] == "good"
    assert item["phases"].get("database") is None
    assert not (root / "data" / "games" / "S23" / "2026-10-01_g01_BV1abc").exists()

    payload = json.loads(export.read_text(encoding="utf-8"))
    payload["games"][0]["note"] = "改判狼人胜"
    export.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    updated = apply.apply_review(export, season="S23", root=root, apply=False, run_ai=True)
    cached = json.loads((root / item["accepted_candidate_path"]).read_text(encoding="utf-8"))
    accepted_review = json.loads((root / item["review_record_path"]).read_text(encoding="utf-8"))
    assert updated["games"][0]["patches"][0]["value"] == "werewolf"
    assert cached["dossier"]["winner"] == "werewolf"
    assert accepted_review["note"] == "改判狼人胜"
    assert len(calls) == 2


@pytest.mark.parametrize('decisions, expected', [
    ({1: 'yes'}, ['yes', 'no', 'no']),
    ({1: 'yes', 2: 'yes'}, ['yes', 'yes', 'no']),
    ({1: 'yes', 2: 'uncertain'}, ['yes', 'uncertain', 'no']),
    ({}, ['uncertain', 'uncertain', 'uncertain']),
])
def test_selected_wolf_completes_bluff_list_and_preserves_explicit_exceptions(decisions, expected):
    from website.api import bluffs

    game = {
        'id': 'new-game', 'season': 'S23', 'date': '2026-10-31',
        'source': {'bvid': 'BV1234567890'}, 'rounds': [], 'voting': {},
        'seats': [{'seat': n, 'person_id': str(n), 'name': f'选手{n}',
                   'role': '狼人', 'faction': 'werewolf'} for n in range(1, 4)],
    }
    plan = {'review_record': {
        'review_id': 'BV1234567890:123:p01', 'manual_sha256': 'a' * 64, 'note': '',
        'bluffs_review': {'reviewed': bool(decisions), 'no_bluff': False,
                         'items': [{'seat': seat, 'decision': decision, 'success': False,
                                    'note': f'{seat}号：{decision}'}
                                   for seat, decision in decisions.items()]},
    }}

    assessments = apply._new_bluff_assessments(game, plan, bluffs)
    payload = {'games': [{'game_id': game['id'], 'assessments': assessments}]}
    items = bluffs.review_items([game], payload)

    assert [item['decision'] for item in items] == expected
    assert [item['needs_review'] for item in items] == [value == 'uncertain' for value in expected]
    for assessment in assessments:
        if assessment['decision'] == 'no':
            assert assessment['verification_status'] == 'user_confirmed'
            assert assessment['evidence'][0]['source_sha256'] == 'a' * 64


def test_explicit_bluff_note_can_include_mixed_blood_with_bound_fingerprints():
    from website.api import bluffs

    game = {
        "id": "bili-BVnew-p01-g01", "season": "S24", "date": "2026-10-30",
        "source": {"bvid": "BVnew"}, "rounds": [],
        "voting": {"days": [], "ballots": [], "registrations": []},
        "seats": [
            {"seat": 1, "person_id": "p1", "name": "狼甲", "role": "狼人", "faction": "werewolf"},
            {"seat": 2, "person_id": "p2", "name": "混血乙", "role": "混血儿", "faction": "werewolf"},
            {"seat": 3, "person_id": "p3", "name": "好人丙", "role": "平民", "faction": "good"},
        ],
    }
    plan = {"game": {"bvid": "BVnew"}, "candidate": {"dossier": {"slug": game["id"]}},
            "review_record": {"review_id": "BVnew:123:p01", "manual_sha256": "a" * 64,
                              "note": "2号混血儿悍跳成功", "bluffs_review": {
                                  "reviewed": True, "no_bluff": False,
                                  "items": [{"seat": 2, "decision": "yes", "success": True,
                                             "note": "2号混血儿悍跳成功"}],
                              }}}

    rows = apply._new_bluff_assessments(game, plan, bluffs)

    assert [row["seat"] for row in rows] == [1, 2]
    assert rows[0]["decision"] == "uncertain"
    assert rows[0]["verification_status"] == "assistant_inferred"
    included = rows[1]
    assert included["decision"] == "yes"
    assert included["verification_status"] == "user_confirmed"
    assert included["manual_included"] is True
    assert included["manual_success"] is True
    assert included["claim_fingerprint"] == bluffs.claim_fingerprint(game, included)
    assert included["success_fingerprint"] == bluffs.success_fingerprint(
        game, 2, bluffs.assessment_success_day(included))


def test_explicit_negative_bluff_note_stays_no_and_does_not_create_nonphysical_row(monkeypatch, tmp_path):
    import incremental_ai
    from website.api import bluffs

    note = "6号没有悍跳，2号混血儿没有悍跳，10号悍跳成功"
    result = {"patches": [], "unresolved": [], "bluffs": {
        "reviewed": True, "no_bluff": False,
        "items": [
            {"seat": 6, "decision": "no", "success": None, "note": "6号没有悍跳"},
            {"seat": 2, "decision": "no", "success": None, "note": "2号混血儿没有悍跳"},
            {"seat": 10, "decision": "yes", "success": True, "note": "10号悍跳成功"},
        ],
    }}
    monkeypatch.setattr(incremental_ai, "run_json", lambda *args, **kwargs: result)
    _, _, bluff_review, unresolved = apply._apply_note(
        candidate(), note, "BVnew:123:p01", root=tmp_path)
    assert unresolved == []

    game = {
        "id": "bili-BVnew-p01-g01", "season": "S24", "date": "2026-10-30",
        "source": {"bvid": "BVnew"}, "rounds": [],
        "voting": {"days": [], "ballots": [], "registrations": []},
        "seats": [
            {"seat": 2, "person_id": "p2", "name": "混血乙", "role": "混血儿", "faction": "werewolf"},
            {"seat": 6, "person_id": "p6", "name": "狼甲", "role": "狼人", "faction": "werewolf"},
            {"seat": 10, "person_id": "p10", "name": "狼乙", "role": "狼人", "faction": "werewolf"},
        ],
    }
    plan = {"game": {"bvid": "BVnew"}, "candidate": {"dossier": {"slug": game["id"]}},
            "review_record": {"review_id": "BVnew:123:p01", "manual_sha256": "b" * 64,
                              "note": note, "bluffs_review": bluff_review}}
    rows = apply._new_bluff_assessments(game, plan, bluffs)
    by_seat = {row["seat"]: row for row in rows}
    assert by_seat[6]["decision"] == "no"
    assert by_seat[6]["verification_status"] == "user_confirmed"
    assert "manual_success" not in by_seat[6]
    assert by_seat[10]["decision"] == "yes"
    assert by_seat[10]["manual_success"] is True
    assert 2 not in by_seat


def test_bluff_merge_preserves_old_games_and_adds_unknown_new_seats(tmp_path, monkeypatch):
    root = tmp_path
    asset = root / "website" / "assets" / "bluffs" / "S24.json"
    asset.parent.mkdir(parents=True)
    old = {"game_id": "old-game", "bvid": "BVold", "source_fingerprint": "old-fp",
           "assessments": [{"seat": 1, "decision": "no", "verification_status": "user_confirmed"}]}
    asset.write_text(json.dumps({"schema_version": 1, "season": "S24",
                                 "inference_version": "old-version", "games": [old]}),
                     encoding="utf-8")
    game = {
        "id": "bili-BVnew-p01-g01", "season": "S24", "date": "2026-10-30",
        "source": {"bvid": "BVnew"}, "rounds": [],
        "voting": {"days": [], "ballots": [], "registrations": []},
        "seats": [
            {"seat": 1, "person_id": "p1", "name": "狼甲", "role": "狼人", "faction": "werewolf"},
            {"seat": 2, "person_id": "p2", "name": "混血乙", "role": "混血儿", "faction": "good"},
        ],
    }
    from website.api import publisher
    monkeypatch.setattr(publisher, "load_publication", lambda root, season: ([{
        "dossier": {}, "voting": {}, "endgame": {}, "audit": None, "board": {},
    }], "", ""))
    monkeypatch.setattr(publisher, "_public_game", lambda *a, **k: game)
    monkeypatch.setattr(apply, "save_state", lambda *a, **k: None)
    plan = {"game": {"bvid": "BVnew"}, "candidate": {"dossier": {"slug": game["id"]}},
            "item": {"phases": {}},
            "review_record": {"review_id": "BVnew:123:p01", "manual_sha256": "a" * 64,
                              "note": "2号混血儿悍跳成功", "bluffs_review": {"reviewed": True,
                                  "no_bluff": False, "items": [{"seat": 2, "decision": "yes", "success": True,
                                      "note": "2号混血儿悍跳成功"}]}}}

    apply._merge_bluff_records(root, "S24", [plan], {"season": "S24", "items": {}})

    merged = json.loads(asset.read_text(encoding="utf-8"))
    assert merged["inference_version"] == "old-version"
    assert next(row for row in merged["games"] if row["game_id"] == "old-game") == old
    new = next(row for row in merged["games"] if row["game_id"] == game["id"])
    assert [row["seat"] for row in new["assessments"]] == [1, 2]
    assert new["assessments"][0]["decision"] == "uncertain"
    assert new["assessments"][0]["verification_status"] == "assistant_inferred"
    assert new["assessments"][1]["manual_included"] is True
    assert new["assessments"][1]["verification_status"] == "user_confirmed"


def test_game_and_voting_imports_share_a_transaction_and_roll_back_together(monkeypatch, tmp_path):
    import database, game_records, voting_records

    class Connection:
        def __init__(self):
            self.rolled_back = False
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.rolled_back = exc_type is not None
            self.committed = exc_type is None

    conn = Connection()
    observed = []
    monkeypatch.setattr(database, "import_media", lambda *a, **k: {"registered": True})
    monkeypatch.setattr(database, "connect", lambda: conn)
    monkeypatch.setattr(game_records, "import_game", lambda value, **kwargs: observed.append(kwargs["conn"]))

    def fail_voting(value, **kwargs):
        observed.append(kwargs["conn"])
        raise RuntimeError("simulated voting failure")

    monkeypatch.setattr(voting_records, "import_voting", fail_voting)
    item = {"phases": {}}
    state = {"season": "S23", "items": {"x": item}}
    candidate_path = tmp_path / "candidate.json"
    source_path = tmp_path / "source.json"
    candidate_path.write_text("{}", encoding="utf-8")
    source_path.write_text("source", encoding="utf-8")
    plan = {"item": item, "game": {"review_id": "review-1", "bvid": "BV1abc", "page": 1,
                                    "candidate_sha256": digest(candidate_path),
                                    "source_sha256": digest(source_path)},
            "candidate_path": candidate_path, "source_path": source_path,
            "manifest": Path("manifest"),
            "prepared_formal": {"dossier": candidate()["dossier"],
            "voting": candidate()["voting"], "derivations": {}}}

    with pytest.raises(RuntimeError, match="simulated voting failure"):
        apply._import_database(plan, state, "S23", tmp_path)

    assert observed == [conn, conn]
    assert conn.rolled_back and not conn.committed
    assert item["phases"] == {}


def test_apply_writes_owned_formal_bundle_and_archived_review_after_db_success(tmp_path, monkeypatch):
    root, state, export, _ = setup_review(tmp_path)
    install_local_preflight_mocks(monkeypatch, state)
    import database, game_derivations, game_records, voting_records

    derived_inputs = []

    def derive(dossier, voting, **kwargs):
        derived_inputs.append((deepcopy(dossier), deepcopy(voting)))
        prepared_dossier = deepcopy(dossier)
        prepared_dossier["winner"] = "good"
        return {"dossier": prepared_dossier, "voting": deepcopy(voting),
                "derivations": {"gaps": [], "issues": [], "changes": [], "derived_for_test": True,
                                "input_hashes": {"endgame": game_derivations.fingerprint(
                                    kwargs["endgame"])}}}

    monkeypatch.setattr(game_derivations, "derive_game", derive)

    class Connection:
        def __init__(self):
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.committed = exc_type is None

    conn = Connection()
    imported = []
    monkeypatch.setattr(apply.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(database, "import_media", lambda *a, **k: {"registered": True})
    monkeypatch.setattr(database, "connect", lambda: conn)
    monkeypatch.setattr(game_records, "import_game", lambda value, **kwargs: imported.append(("game", value, kwargs)))
    monkeypatch.setattr(voting_records, "import_voting", lambda value, **kwargs: imported.append(("voting", value, kwargs)))
    monkeypatch.setattr(apply, "save_state", lambda *a, **k: None)

    report = apply.apply_review(export, season="S23", root=root, apply=True,
                                backup=True, run_ai=False)

    formal = root / "data" / "games" / "S23" / "2026-10-01_g01_BV1abc"
    sidecar = json.loads((formal / "incremental_review.json").read_text(encoding="utf-8"))
    assert report["state"] == "completed"
    assert [row[0] for row in imported] == ["game", "voting"]
    assert imported[0][1] == json.loads((formal / "dossier.json").read_text(encoding="utf-8"))
    assert imported[1][1] == json.loads((formal / "voting.json").read_text(encoding="utf-8"))
    assert imported[0][1]["winner"] == "good"
    assert imported[0][2]["conn"] is imported[1][2]["conn"] is conn
    assert imported[0][2]["derivations"]["derived_for_test"] is True
    assert derived_inputs[0][1] == candidate()["voting"]
    assert conn.committed
    assert sidecar["format"] == "masters-incremental-confirmed-v1"
    assert sidecar["reviewed"] is True
    assert sidecar["manual_sha256"] == digest(root / sidecar["manual_source_path"])
    assert sidecar["dossier_sha256"] == digest(formal / "dossier.json")
    assert sidecar["voting_sha256"] == digest(formal / "voting.json")
    assert (formal / "endgame.json").is_file()
    assert json.loads((formal / "rule_derivations.json").read_text(encoding="utf-8"))["derived_for_test"]

    monkeypatch.setattr(game_derivations, "apply_precomputed", lambda dossier, voting, derivations: {
        "dossier": {**deepcopy(dossier), "winner": "good"}, "voting": deepcopy(voting)})
    resumed = apply.apply_review(export, season="S23", root=root, apply=True,
                                 backup=True, run_ai=False)
    assert resumed["state"] == "completed"
    assert len(imported) == 2


def test_publish_resume_skips_database_and_leaves_other_games_untouched(tmp_path, monkeypatch):
    root = tmp_path
    source = root / "data" / "source.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({"source": {"bvid": "BV1abc", "cid": 123, "page": 1}}),
                      encoding="utf-8")
    entry = {"bvid": "BV1abc", "cid": 123, "page": 1, "labels": {"season": "S23"}}
    work = root / "data" / "extractions" / "S23" / "incremental" / "BV1abc_p01_cid123"
    work.mkdir(parents=True)
    candidate_path = work / "candidate.json"
    candidate_path.write_text(json.dumps(candidate()), encoding="utf-8")
    accepted_path = work / "accepted_candidate.json"
    accepted_path.write_text(json.dumps(candidate()), encoding="utf-8")
    accepted_formal_path = work / "accepted_formal.json"
    accepted_formal_path.write_text(json.dumps({"dossier": candidate()["dossier"],
        "voting": candidate()["voting"], "derivations": {"gaps": [], "issues": []}}),
        encoding="utf-8")
    manual_path = root / "data" / "reports" / "S23" / "incremental" / "reviews" / "manual.json"
    manual_path.parent.mkdir(parents=True)
    manual_path.write_text('{"original":true}', encoding="utf-8")
    record = {"review_id": "BV1abc:123:p01", "source_sha256": digest(source),
              "candidate_sha256": digest(candidate_path), "manual_source_path": manual_path.relative_to(root).as_posix(),
              "manual_sha256": digest(manual_path), "note": "", "patches": [],
              "bluffs_review": {"reviewed": False, "no_bluff": False, "items": []}}
    review_record_path = work / "accepted_review.json"
    review_record_path.write_text(json.dumps(record), encoding="utf-8")
    formal_other = root / "data" / "games" / "S23" / "other" / "dossier.json"
    formal_other.parent.mkdir(parents=True)
    formal_other.write_text('{"other":true}', encoding="utf-8")
    other_before = formal_other.read_bytes()
    target = {
        "entry": entry, "analysis": "ready", "source_path": "data/source.json",
        "source_sha256": digest(source), "candidate_sha256": digest(candidate_path),
        "accepted_candidate_path": accepted_path.relative_to(root).as_posix(),
        "accepted_candidate_sha256": digest(accepted_path),
        "accepted_formal_sha256": digest(accepted_formal_path),
        "review_record_path": review_record_path.relative_to(root).as_posix(),
        "formal_dir": "data/games/S23/2026-10-01_g01_BV1abc",
        "applied": True, "phases": {"database": "done", "formal": "done", "publish": "failed"},
    }
    other = {"entry": {"bvid": "BV1other", "cid": 9, "page": 1},
             "phases": {"database": "done", "formal": "done", "publish": "done", "verify": "done"}}
    state = {"schema_version": 1, "season": "S23",
             "items": {"BV1abc:123:p01": target, "BV1other:9:p01": other}, "weibo": {}}
    export = root / "review.json"
    export.write_text(json.dumps({"format": apply.REVIEW_FORMAT, "season": "S23", "games": []}),
                      encoding="utf-8")
    monkeypatch.setattr(apply, "load_state", lambda root, season: state)
    monkeypatch.setattr(apply, "save_state", lambda *a, **k: None)
    monkeypatch.setattr(apply, "_merge_bluff_records", lambda *a, **k: None)
    import workflow
    monkeypatch.setattr(workflow, "formal_seasons", lambda root: ["S23"])
    monkeypatch.setattr(workflow, "ensure_retained_seasons", lambda seasons: None)
    def stage_commands(stage, season, **kwargs):
        if stage == "publish":
            assert kwargs["photos"] is True
        return [[stage, kwargs.get("bvid", "")]]

    monkeypatch.setattr(workflow, "stage_commands", stage_commands)
    jobs = []
    monkeypatch.setattr(apply, "_run_jobs", lambda values, root: jobs.extend(values))

    report = apply.apply_review(export, season="S23", root=root, apply=True, publish=True,
                                backup=True, run_ai=False)

    assert report["state"] == "completed"
    assert target["phases"]["publish"] == "done"
    assert target["phases"]["verify"] == "done"
    assert other["phases"]["publish"] == "done"
    assert formal_other.read_bytes() == other_before
    assert jobs == [["publish", ""], ["verify", "BV1abc"]]
