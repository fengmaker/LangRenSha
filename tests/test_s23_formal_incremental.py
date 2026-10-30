import sys
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import import_s23_formal as formal
import s23_effective_game
import database


def _game(slug, bvid, board="board-a"):
    return {
        "slug": slug,
        "bvid": bvid,
        "candidate_path": f"data/games/S23/{slug}/dossier.candidate.json",
        "canonical_board": board,
        "storage_board": f"s23_{board}",
        "candidate_sha256": "a" * 64,
        "source_hashes": {"candidate": {"sha256": "a" * 64}},
        "normalization": {"unknown_count_before": 1},
    }


def _database_game(slug, bvid):
    game = _game(slug, bvid)
    game.update({
        "db_dossier": {"slug": slug, "board": "s23_board-a"},
        "voting": {"game_slug": slug, "ballots": [], "days": [], "registrations": []},
        "rule_derivations": {"version": 1},
        "supplemental": {"events": []}, "vote_control": {"controls": []},
        "endgame": {"phases": []},
        "formal_context": {"separate_review_context": {}, "terminal_observations": [],
                           "unpublished_terminal_checks": []},
        "media": {"external_key": f"{bvid}:cid", "audio_sha256": f"audio-{slug}"},
        "source_hashes": {"candidate": {"sha256": f"candidate-{slug}"}},
        "normalization": {"unknown_count_before": 1},
    })
    return game


class _FakeResult:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class _FakeTransaction:
    def __init__(self, audio_rows):
        self.audio_rows = audio_rows
        self.committed = False
        self.rolled_back = False
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.rolled_back = exc_type is not None
        self.committed = exc_type is None
        return False

    def execute(self, query, params=()):
        statement = " ".join(query.split())
        self.queries.append((statement, params))
        if "to_regclass" in statement:
            return _FakeResult({"name": "present"})
        if statement.startswith("SELECT id FROM seasons"):
            return _FakeResult({"id": "s23-id"})
        if "FROM sources s" in statement and "ANY(%s)" in statement:
            return _FakeResult(rows=self.audio_rows)
        if statement.startswith("SELECT id FROM games WHERE slug=%s"):
            return _FakeResult({"id": "game-" + params[0]})
        return _FakeResult()


def _install_fake_verify_database(monkeypatch, batch, tmp_path, *, receipts, fingerprints):
    transaction = _FakeTransaction([
        {"external_key": game["media"]["external_key"], "sha256": game["media"]["audio_sha256"]}
        for game in batch["games"]
    ])
    monkeypatch.setattr(database, "configuration", lambda: {"schema": "test_schema"})
    monkeypatch.setattr(formal, "connect", lambda _schema: transaction)
    monkeypatch.setattr(formal, "verify_prepared_files", lambda _batch: [])
    formal_hashes = {game["slug"]: {"dossier.json": "formal-" + game["slug"]}
                     for game in batch["games"]}
    monkeypatch.setattr(formal, "prepared_formal_hashes", lambda game: formal_hashes[game["slug"]])
    monkeypatch.setattr(formal, "db_season_fingerprint", lambda _conn, code: {"season": code})
    monkeypatch.setattr(formal, "sync_batch_templates", lambda _conn, games: None)
    monkeypatch.setattr(formal, "sha256_file", lambda _path: "source-hash")
    monkeypatch.setattr(formal, "ROOT", tmp_path)
    monkeypatch.setattr(formal, "REPORT_PATH", tmp_path / "data/reports/S23/progress.json")
    monkeypatch.setattr(formal, "RULES_PATH", tmp_path / "config/game_rules.json")
    auth_path = tmp_path / "data/extractions/S23/authorization.txt"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text("authorized", encoding="utf-8")
    monkeypatch.setattr(formal, "AUTHORIZATION_PATH", auth_path)

    def load_receipt(_conn, slug):
        value = receipts(slug) if callable(receipts) else receipts.get(slug)
        return value

    monkeypatch.setattr(formal, "load_game_receipt", load_receipt)
    monkeypatch.setattr(formal, "db_game_fingerprint",
                        lambda _conn, slug: fingerprints(slug) if callable(fingerprints) else fingerprints.get(slug))
    return transaction, formal_hashes


def _matching_receipt(game, formal_hashes, fingerprint):
    return {
        "season_code": "S23", "slug": game["slug"],
        "canonical_board_code": game["canonical_board"],
        "storage_board_code": game["storage_board"],
        "candidate_path": game["candidate_path"], "candidate_sha256": game["candidate_sha256"],
        "source_files": game["source_hashes"], "normalization": game["normalization"],
        "overall_batch_authorized": True,
        "field_confirmation": "not_claimed_by_batch_authorization",
        "formal_files": {**formal_hashes, "__database_content_sha256": fingerprint},
    }


def _import_batch(games):
    return {"games": games, "full_batch": False, "scope": {"scope_code": "fixture"},
            "progress": {"snapshot_id": "snapshot"}, "batch_key": "fixture-batch",
            "source_hashes": {"snapshot_report": "report", "formal_rules": "rules",
                              "authorization": "auth"}}


def _build_inputs(monkeypatch, candidates):
    monkeypatch.setattr(
        formal,
        "load_inputs",
        lambda *_args: (
            {"scope_code": "fixture", "season": "S23"},
            {"board_code_map": {"board-a": "s23_board-a", "board-b": "s23_board-b"}},
            {"snapshot_id": "snapshot", "candidate_dossiers": candidates},
            {},
            {},
        ),
    )
    def prepare(path, *_args, **_kwargs):
        bvid = formal.bvid_from_slug(path.parent.name)
        return _game(path.parent.name, bvid)

    monkeypatch.setattr(formal, "prepare_game", prepare)
    monkeypatch.setattr(formal, "load_current_games", lambda bvids: [
        {"entry": {"bvid": bvid, "output_dir": f"data/games/S23/2026-10-01_g01_{bvid}"}}
        for bvid in (bvids or [formal.bvid_from_slug(Path(path).parent.name) for path in candidates])
    ])
    monkeypatch.setattr(formal, "sha256_file", lambda _path: "c" * 64)


def test_materialize_skips_equal_formal_json_and_receipt_replacements(tmp_path, monkeypatch):
    monkeypatch.setattr(formal, "ROOT", tmp_path)
    game = _game("fixture", "BVfixture")
    game.update({
        "candidate_path": "data/candidate/candidate.json",
        "dossier": {"slug": "fixture", "rounds": []},
        "voting": {"ballots": [], "days": []}, "endgame": {"phases": []},
        "supplemental": {"observations": []}, "vote_control": {"controls": []},
        "formal_context": {"normalization": {"unknown_count_before": 1}},
        "rule_derivations": {"version": 1}, "media": {"audio_sha256": "b" * 64},
        "normalization": {"unknown_count_before": 1, "unknown_count_after": 2,
                          "unknown_count_after_derivation": 2, "filled_slots_as_unknown": []},
    })
    batch = {"scope": {"scope_code": "fixture"}, "progress": {"snapshot_id": "snapshot"},
             "batch_key": "fixture-batch", "board_counts": {"board": 1}, "games": [game],
             "source_hashes": {"formal_rules": "c" * 64}}

    first = formal.materialize(batch)
    folder = tmp_path / "data/candidate"
    outputs = [folder / name for name in (*formal.FORMAL_FILES[:-1], "formal_import_receipt.json")]
    mtimes = {path: path.stat().st_mtime_ns for path in outputs}
    report_path = tmp_path / "data/reports/S23/S23_正式入库预检.json"
    report_time_before = json.loads(report_path.read_text(encoding="utf-8"))["generated_at_utc"]
    original_replace = Path.replace
    replaced_formal_files = []

    def reject_formal_replace(path, target):
        if path.parent == folder:
            replaced_formal_files.append(path.name)
            raise AssertionError(f"unchanged formal output was replaced: {path.name}")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", reject_formal_replace)
    second = formal.materialize(batch)

    assert first["games_rewritten"] == 1
    assert second["games_rewritten"] == 0
    assert second["formal_files_rewritten"] == 0
    assert replaced_formal_files == []
    assert {path: path.stat().st_mtime_ns for path in outputs} == mtimes
    report_time_after = json.loads(report_path.read_text(encoding="utf-8"))["generated_at_utc"]
    assert report_time_after != report_time_before


def test_s23_report_records_measured_preparation_database_and_rewrite_metrics():
    game = _game("fixture", "BVfixture")
    game["normalization"].update({"unknown_count_after": 2, "unknown_count_after_derivation": 1,
                                  "filled_slots_as_unknown": []})
    batch = {"scope": {"scope_code": "fixture"}, "progress": {"snapshot_id": "snapshot"},
             "batch_key": "fixture-batch", "board_counts": {"board-a": 1}, "games": [game],
             "source_hashes": {}}

    report = formal.make_report(batch, "fixture", preparation_seconds=1.2345,
                                database_seconds=2.3456, formal_games_rewritten=1)

    assert report["timings_seconds"] == {"preparation": 1.234, "database": 2.346}
    assert report["formal_games_rewritten"] == 1


def test_build_batch_bvid_prepares_only_the_selected_game_without_full_batch_checks(monkeypatch):
    candidates = [
        "data/games/S23/2026-10-01_g01_BVselected/dossier.candidate.json",
        "data/games/S23/2026-10-02_g01_BVother/dossier.candidate.json",
    ]
    _build_inputs(monkeypatch, candidates)

    batch = formal.build_batch(bvids=["BVselected"])

    assert [game["bvid"] for game in batch["games"]] == ["BVselected"]
    assert batch["board_counts"] == {"board-a": 1}


def test_build_batch_rejects_unmatched_bvid(monkeypatch):
    _build_inputs(monkeypatch, ["data/games/S23/2026-10-01_g01_BVknown/dossier.candidate.json"])

    with pytest.raises(formal.ReviewError, match="BVID不在当前候选范围"):
        formal.build_batch(bvids=["BVmissing"])


def test_load_inputs_allows_a_targeted_candidate_without_a_full_75_game_snapshot(tmp_path, monkeypatch):
    auth = tmp_path / "authorization.txt"
    auth.write_text("OK，开始写入数据库，并上线到网站吧", encoding="utf-8")
    policy = tmp_path / "policy.txt"
    policy.write_text("eulogy scope note", encoding="utf-8")
    scope_path, rules_path, report_path = (tmp_path / name for name in ("scope.json", "rules.json", "report.json"))
    daily_path, audit_path = (tmp_path / name for name in ("daily.json", "audit.json"))
    progress = {"planned": 75, "snapshot_id": "snapshot",
                "candidate_dossiers": ["data/games/S23/day_g01_BVonly/dossier.candidate.json"],
                "missing_ai_reviews": []}
    paths = {
        scope_path: {"season": "S23", "authoritative_snapshot_id": "snapshot"},
        rules_path: {"season": "S23", "authoritative_snapshot_id": "snapshot",
                            "board_code_map": {name: name for name in (
                                "mechanical_wolf_seer", "mixed_blood", "guile_realm", "masquerade",
                                "treasure_master", "qingqiu_night", "magic_duel")}},
        report_path: progress,
        daily_path: {"snapshot_id": "snapshot"},
        audit_path: {"season": "S23", "planned": 75, "errors": []},
    }
    monkeypatch.setattr(formal, "SCOPE_PATH", scope_path)
    monkeypatch.setattr(formal, "RULES_PATH", rules_path)
    monkeypatch.setattr(formal, "REPORT_PATH", report_path)
    monkeypatch.setattr(formal, "DAILY_REPORT_PATH", daily_path)
    monkeypatch.setattr(formal, "AUDIT_REPORT_PATH", audit_path)
    monkeypatch.setattr(formal, "AUTHORIZATION_PATH", auth)
    monkeypatch.setattr(formal, "EULOGY_POLICY_PATH", policy)
    monkeypatch.setattr(formal, "read_json", lambda path: paths[path])
    monkeypatch.setattr(formal, "load_scope", lambda season, root: paths[scope_path])
    monkeypatch.setattr(formal, "load_formal_rules", lambda season, root: paths[rules_path])

    _scope, _rules, progress, _daily, _audit = formal.load_inputs(["BVonly"])

    assert progress["candidate_dossiers"] == ["data/games/S23/day_g01_BVonly/dossier.candidate.json"]
    progress["missing_ai_reviews"] = ["data/games/S23/BVother/ai_review.json"]
    formal.load_inputs(["BVonly"])
    progress["missing_ai_reviews"] = ["data/games/S23/BVonly/ai_review.json"]
    with pytest.raises(formal.ReviewError, match="候选报告仍缺AI复核文件"):
        formal.load_inputs(["BVonly"])
    progress["missing_ai_reviews"] = ["could-not-match-a-game"]
    with pytest.raises(formal.ReviewError, match="缺AI复核的报告条目无法匹配BVID"):
        formal.load_inputs(["BVonly"])


def test_database_receipt_requires_current_sources_outputs_and_game_fingerprint():
    game = _game("fixture", "BVfixture")
    receipt = {
        "batch_key": "prior-snapshot",
        "slug": game["slug"],
        "canonical_board_code": game["canonical_board"],
        "storage_board_code": game["storage_board"],
        "candidate_path": game["candidate_path"],
        "candidate_sha256": game["candidate_sha256"],
        "season_code": "S23",
        "source_files": game["source_hashes"],
        "formal_files": {"dossier.json": "b" * 64, "__database_content_sha256": "d" * 64},
        "normalization": game["normalization"],
        "overall_batch_authorized": True,
        "field_confirmation": "not_claimed_by_batch_authorization",
    }
    formal_hashes = {"dossier.json": "b" * 64}

    assert formal.database_receipt_matches(game, receipt, formal_hashes, "d" * 64)
    assert not formal.database_receipt_matches(game, receipt, formal_hashes, "e" * 64)
    changed_source = dict(receipt, source_files={"candidate": {"sha256": "f" * 64}})
    assert not formal.database_receipt_matches(game, changed_source, formal_hashes, "d" * 64)


def test_verify_database_skips_all_writes_when_selected_games_are_current(tmp_path, monkeypatch):
    game = _database_game("game-a", "BVgamea")
    batch = _import_batch([game])
    receipts = {}
    transaction, formal_hashes = _install_fake_verify_database(
        monkeypatch, batch, tmp_path, receipts=receipts, fingerprints={game["slug"]: "fingerprint-a"}
    )
    receipts[game["slug"]] = _matching_receipt(game, formal_hashes[game["slug"]], "fingerprint-a")
    imported = []
    syncs = []
    monkeypatch.setattr(formal.game_records, "import_game", lambda *args, **kwargs: imported.append(args[0]))
    monkeypatch.setattr(formal, "sync_batch_templates", lambda _conn, games: syncs.append(games))

    result = formal.verify_database(batch, write=True)

    assert result["no_changes"] is True
    assert result["database_write"] is False
    assert imported == []
    assert syncs == []
    assert transaction.committed is True
    assert transaction.rolled_back is False


def test_verify_database_writes_only_the_changed_game_once_with_batch_template_sync(tmp_path, monkeypatch):
    changed = _database_game("game-a", "BVgamea")
    unchanged = _database_game("game-b", "BVgameb")
    batch = _import_batch([changed, unchanged])
    receipts = {}
    imported = []
    fingerprints = {changed["slug"]: "fingerprint-a", unchanged["slug"]: "fingerprint-b"}
    transaction, formal_hashes = _install_fake_verify_database(
        monkeypatch, batch, tmp_path, receipts=receipts, fingerprints=fingerprints
    )
    receipts[unchanged["slug"]] = _matching_receipt(
        unchanged, formal_hashes[unchanged["slug"]], fingerprints[unchanged["slug"]]
    )

    def load_receipt(_conn, slug):
        if slug == changed["slug"] and changed["slug"] in imported:
            return _matching_receipt(changed, formal_hashes[changed["slug"]], fingerprints[changed["slug"]])
        return receipts.get(slug)

    monkeypatch.setattr(formal, "load_game_receipt", load_receipt)
    import_kwargs = []

    def import_game(value, **kwargs):
        imported.append(value["slug"])
        import_kwargs.append(kwargs)
        return {"slug": value["slug"]}

    monkeypatch.setattr(formal.game_records, "import_game", import_game)
    voting_imports = []
    monkeypatch.setattr(formal.voting_records, "import_voting",
                        lambda facts, **_kwargs: voting_imports.append(facts["game_slug"]))
    synced = []
    monkeypatch.setattr(formal, "sync_batch_templates",
                        lambda _conn, games: synced.append([game["slug"] for game in games]))

    result = formal.verify_database(batch, write=True)

    assert imported == [changed["slug"]]
    assert voting_imports == [changed["slug"]]
    assert synced == [[changed["slug"]]]
    assert result["games"] == 1
    assert result["games_unchanged"] == 1
    assert result["database_write_passes"] == 1
    assert len(import_kwargs) == 1
    assert import_kwargs[0]["sync_template"] is False
    assert transaction.committed is True
    assert transaction.rolled_back is False


def test_verify_database_rolls_back_selected_batch_when_second_import_fails(tmp_path, monkeypatch):
    first = _database_game("game-a", "BVgamea")
    second = _database_game("game-b", "BVgameb")
    batch = _import_batch([first, second])
    imported = []
    transaction, formal_hashes = _install_fake_verify_database(
        monkeypatch, batch, tmp_path, receipts={},
        fingerprints={first["slug"]: "fingerprint-a", second["slug"]: "fingerprint-b"}
    )
    synced = []
    monkeypatch.setattr(formal, "sync_batch_templates",
                        lambda _conn, games: synced.append([game["slug"] for game in games]))

    def load_receipt(_conn, slug):
        if slug in imported:
            game = first if slug == first["slug"] else second
            return _matching_receipt(game, formal_hashes[slug], "fingerprint-" + slug[-1])
        return None

    monkeypatch.setattr(formal, "load_game_receipt", load_receipt)
    monkeypatch.setattr(formal.voting_records, "import_voting", lambda *_args, **_kwargs: None)

    def import_game(value, **_kwargs):
        imported.append(value["slug"])
        if value["slug"] == second["slug"]:
            raise formal.ReviewError("synthetic second-game failure")

    monkeypatch.setattr(formal.game_records, "import_game", import_game)

    with pytest.raises(formal.ReviewError, match="synthetic second-game failure"):
        formal.verify_database(batch, write=True)

    assert synced == [[first["slug"], second["slug"]]]
    assert imported == [first["slug"], second["slug"]]
    assert transaction.rolled_back is True
    assert transaction.committed is False


def test_prepare_rejects_candidate_material_stale_against_effective_game(tmp_path, monkeypatch):
    candidate = tmp_path / "dossier.candidate.json"
    candidate.write_text('{"slug":"bili-BVfixture-p01-g01"}', encoding="utf-8")
    expected = {"dossier.candidate.json": {"slug": "bili-BVfixture-p01-g01"},
                "voting.candidate.json": {"game_slug": "bili-BVfixture-p01-g01"}}
    for filename, value in expected.items():
        candidate.with_name(filename).write_text(json.dumps(value), encoding="utf-8")
    effective = {"entry": {"bvid": "BVfixture"}}
    monkeypatch.setattr(s23_effective_game, "candidate_values", lambda _game: expected)

    formal.verify_candidate_is_current(candidate, effective)
    candidate.with_name("voting.candidate.json").write_text('{"game_slug":"stale"}', encoding="utf-8")

    with pytest.raises(formal.ReviewError, match="候选材料已过期.*build_s23_review.py --bvid BVfixture"):
        formal.verify_candidate_is_current(candidate, effective)


def test_daily_import_uses_one_pass_and_deep_acceptance_keeps_two(monkeypatch):
    calls = []

    formal.run_import_passes(lambda: calls.append("import"), lambda: "same", verify_idempotency=False)
    assert calls == ["import"]

    calls.clear()
    formal.run_import_passes(lambda: calls.append("import"), lambda: "same", verify_idempotency=True)
    assert calls == ["import", "import"]


def test_deep_acceptance_rejects_a_changed_second_pass_fingerprint():
    fingerprints = iter(("first", "second"))

    with pytest.raises(formal.ReviewError, match="幂等性检查失败"):
        formal.run_import_passes(lambda: None, lambda: next(fingerprints), verify_idempotency=True)


def test_cli_keeps_deep_idempotency_for_full_batches_only(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["import_s23_formal.py", "--import-db", "--bvid", "BVfixture",
                                       "--verify-idempotency"])

    with pytest.raises(SystemExit) as error:
        formal.main()

    assert error.value.code == 2


def test_batch_template_sync_deduplicates_same_board_and_version(monkeypatch):
    board = {"code": "s23_board-a", "name": "Board A", "seat_count": 12,
             "night_slots": [], "day_slots": []}
    game = {"db_dossier": {"board": board["code"]},
            "source_hashes": {"board_template:s23_board-a": {"sha256": "c" * 64}}}
    monkeypatch.setattr(formal.game_records, "template", lambda _code: board)
    sync = []
    monkeypatch.setattr(formal.game_records, "sync_board_template", lambda _conn, value: sync.append(value))

    formal.sync_batch_templates(object(), [game, game])

    assert sync == [board]


def test_batch_template_sync_rejects_two_versions_for_one_board(monkeypatch):
    board = {"code": "s23_board-a", "name": "Board A", "seat_count": 12,
             "night_slots": [], "day_slots": []}
    game = {"db_dossier": {"board": board["code"]},
            "source_hashes": {"board_template:s23_board-a": {"sha256": "c" * 64}}}
    other = {"db_dossier": {"board": board["code"]},
             "source_hashes": {"board_template:s23_board-a": {"sha256": "d" * 64}}}
    monkeypatch.setattr(formal.game_records, "template", lambda _code: board)

    with pytest.raises(formal.ReviewError, match="同批次版型模板版本不一致"):
        formal.sync_batch_templates(object(), [game, other])
