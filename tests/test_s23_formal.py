import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import import_s23_formal as formal


def test_confirmed_terminal_check_supersedes_historical_unobserved_note():
    batch = formal.build_batch(['BV1MheH6wEBb'])
    game = batch['games'][0]
    check = next(e for r in game['dossier']['rounds'] if r['number'] == 3
                 for e in r['night'] if e['slot'] == 'seer_check')
    assert (check['action'], check['targets'], check['result']) == ('check', [1], '好人')
    assert game['formal_context']['unpublished_terminal_checks'] == []
    assert game['formal_context']['public_notes'] == []


def _game():
    return {
        "slug": "fixture-s23", "bvid": "BVfixture", "candidate_path": "data/candidate/candidate.json",
        "candidate_sha256": "a" * 64, "canonical_board": "board", "storage_board": "board_db",
        "dossier": {"slug": "fixture-s23", "rounds": []}, "voting": {"ballots": [], "days": []},
        "endgame": {"phases": []}, "supplemental": {"observations": []},
        "vote_control": {"controls": []}, "formal_context": {"normalization": {
            "unknown_count_before": 3, "unknown_count_after": 4, "unknown_count_after_derivation": 2,
            "filled_slots_as_unknown": [],
        }}, "rule_derivations": {"version": 1, "changes": [{"path": ["dossier", "rounds"]}]},
        "normalization": {"unknown_count_before": 3, "unknown_count_after": 4,
                           "unknown_count_after_derivation": 2, "filled_slots_as_unknown": []},
        "source_hashes": {"candidate": {"sha256": "a" * 64}},
        "media": {"manifest_path": "data/manifest.json", "audio_sha256": "b" * 64},
    }


def test_rule_derivations_are_a_prepared_and_verified_formal_output(tmp_path, monkeypatch):
    monkeypatch.setattr(formal, "ROOT", tmp_path)
    game = _game()
    batch = {"scope": {"scope_code": "fixture"}, "progress": {"snapshot_id": "snapshot"},
             "batch_key": "fixture-batch", "board_counts": {"board": 1}, "games": [game],
             "source_hashes": {"formal_rules": "c" * 64}}

    result = formal.materialize(batch)
    folder = tmp_path / "data/candidate"
    assert (folder / "rule_derivations.json").is_file()
    assert formal.read_json(folder / "rule_derivations.json") == game["rule_derivations"]
    assert formal.verify_prepared_files(batch) == []
    assert "rule_derivations.json" in formal.FORMAL_FILES
    assert result["games"] == 1


def test_s23_report_keeps_normalized_and_derived_unknown_counts_separate():
    game = _game()
    batch = {"scope": {"scope_code": "fixture"}, "progress": {"snapshot_id": "snapshot"},
             "batch_key": "fixture-batch", "board_counts": {"board": 1}, "games": [game],
             "source_hashes": {"formal_rules": "c" * 64}}

    report = formal.make_report(batch, "prepared")
    assert report["unknown_events_after"] == 4
    assert report["unknown_events_after_derivation"] == 2


def test_partial_materialize_preserves_the_full_acceptance_report(tmp_path, monkeypatch):
    monkeypatch.setattr(formal, 'ROOT', tmp_path)
    report = tmp_path / 'data/reports/S23/S23_正式入库预检.json'
    report.parent.mkdir(parents=True)
    report.write_text('full acceptance', encoding='utf-8')
    game = _game()
    batch = {'scope': {'scope_code': 'fixture'}, 'progress': {'snapshot_id': 'snapshot'},
             'batch_key': 'fixture-batch', 'board_counts': {'board': 1}, 'games': [game],
             'source_hashes': {}, 'full_batch': False}
    result = formal.materialize(batch)
    assert result['report'].endswith('S23_局部正式入库预检.json')
    assert report.read_text(encoding='utf-8') == 'full acceptance'
