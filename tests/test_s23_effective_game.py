"""Audit and candidate assembly must inspect the same accepted corrections."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import audit_s23_review as audit_module
import s23_effective_game as effective
import check_s23_game as local_check
import build_s23_review as builder
from s23_schema import normalize as normalize_schema


def save(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return path


@pytest.fixture
def reviewed_game(tmp_path, monkeypatch):
    source = save(tmp_path, 'data/source.json', {'segments': [
        {'start_ms': 0, 'end_ms': 1000, 'text': '已核原文'}]})
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    entry = {'bvid': 'BVfixture', 'index': 0, 'source_path': 'data/source.json',
             'source_sha256': source_hash, 'date': '2026-09-08', 'game_number': 1,
             'board': 'qingqiu_night', 'board_name': '青丘夜影', 'phase': 'regular',
             'audio_path': '', 'frame': {'frame_path': ''}}
    roles = ['狼人'] * 3 + ['九尾狐', '预言家', '女巫', '守卫', '白泽'] + ['平民'] * 4
    dossier = {'slug': 'bili-BVfixture-p01-g01', 'season': 'S23', 'phase': 'regular',
               'board': 'qingqiu_night', 'date': entry['date'], 'game_number': 1,
               'winner': None, 'roster': [], 'commentators': [], 'referee': None,
               'seats': [{'seat': n, 'name': str(n), 'role': role, 'faction': None}
                         for n, role in enumerate(roles, 1)], 'rounds': [], 'files': []}
    review = {'bvid': entry['bvid'], 'source_sha256': source_hash, 'decisions': [],
              'human_questions': [], 'coverage': {key: True for key in
              ['recap_read', 'voting_checked', 'bluff_checked', 'frame_checked']}}
    folder = 'data/extractions/S23/game_reviews/BVfixture/'
    save(tmp_path, folder + 'dossier.reviewed.json', dossier)
    save(tmp_path, folder + 'voting.reviewed.json', {'game_slug': dossier['slug'], 'ballots': [], 'days': []})
    save(tmp_path, folder + 'ai_review.json', review)
    corrected = deepcopy(dossier)
    corrected['winner'] = 'good'
    save(tmp_path, folder + 'primary_review.json', {'bvid': entry['bvid'], 'source_sha256': source_hash,
         'patches': [{'target': 'dossier', 'value': corrected}]})
    save(tmp_path, 'data/reports/S23/S23_逐局复核计划.json', {'entries': [entry]})
    aliases = tmp_path / 'data/weibo/2026-05-26_2026-10-20/参赛名单/人名去重_照片映射.csv'
    aliases.parent.mkdir(parents=True)
    aliases.write_text('赛季,原人工确认状态,去重后姓名,原图名字,复核行名字\n', encoding='utf-8-sig')
    monkeypatch.setattr(audit_module, 'ROOT', tmp_path)
    monkeypatch.setattr(audit_module, 'BASE', tmp_path / 'data/extractions/S23/game_reviews')
    monkeypatch.setattr(effective, 'ROOT', tmp_path)
    # file_url captured EXPORT as a default argument at import time.
    monkeypatch.setattr(effective.file_url, '__defaults__', (tmp_path / 'data/exports',))
    monkeypatch.setattr(local_check, 'ROOT', tmp_path)
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    return tmp_path, entry


def test_audit_does_not_repeat_a_problem_fixed_by_primary_patch(reviewed_game):
    result = audit_module.audit()
    assert not [item for item in result['warnings'] if item['code'] == 'winner_unknown']


def test_audit_detects_a_conflict_introduced_by_an_accepted_patch(reviewed_game):
    root, entry = reviewed_game
    path = root / 'data/extractions/S23/game_reviews/BVfixture/primary_review.json'
    primary = json.loads(path.read_text(encoding='utf-8'))
    primary['patches'][0]['value']['seats'][0]['seat'] = 13
    save(root, path.relative_to(root), primary)
    result = audit_module.audit(write_report=False)
    assert 'seat_set' in [item['code'] for item in result['errors']]


def test_partial_check_is_read_only_and_exposes_formal_value_differences(reviewed_game):
    root, entry = reviewed_game
    game = effective.load_effective_game(entry['bvid'])
    current = deepcopy(game['dossier'])
    current['winner'] = 'werewolf'
    save(root, game['entry']['output_dir'] + '/dossier.json', current)
    files_before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = local_check.check_game(entry['bvid'], checks=['structure'], fields=['winner'])
    assert result['checked_games'] == 1
    assert result['formal_database_writes'] is False
    assert [(r['field'], r['before'], r['after']) for r in result['changes']] == [
        ('dossier.winner', 'werewolf', 'good')]
    assert files_before == {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_single_game_ignores_unrelated_missing_review_files_and_parses_source_once(reviewed_game, monkeypatch):
    root, entry = reviewed_game
    other = {**entry, 'bvid': 'BVunrelated', 'date': '2026-09-09', 'source_path': 'data/missing.json'}
    save(root, 'data/reports/S23/S23_逐局复核计划.json', {'entries': [entry, other]})
    real_segments = effective.segments
    reads = []
    def count(path):
        reads.append(path)
        return real_segments(path)
    monkeypatch.setattr(effective, 'segments', count)
    monkeypatch.setattr(audit_module, 'segments', lambda path: pytest.fail('source cache should be reused'))
    result = local_check.check_game(entry['bvid'], checks=['structure', 'evidence'])
    assert result['valid']
    assert reads == [root / entry['source_path']]
    assert result['dependency_bvids'] == []


def test_single_build_writes_only_candidate_files_and_preserves_full_report(reviewed_game):
    root, entry = reviewed_game
    full = save(root, 'data/reports/S23/S23_逐局复核进度.json', {'snapshot_id': 'keep'})
    before = full.read_bytes()
    result = builder.build_one(entry['bvid'])
    assert result['mode'] == 'partial'
    assert full.read_bytes() == before
    assert (root / result['candidate_dossiers'][0]).is_file()
    assert not (root / 'data/exports').exists()


def test_evidence_scope_does_not_read_unrelated_quotes(reviewed_game):
    root, entry = reviewed_game
    path = root / 'data/extractions/S23/game_reviews/BVfixture/ai_review.json'
    review = json.loads(path.read_text(encoding='utf-8'))
    review['decisions'] = [
        {'field': 'winner', 'evidence': [{'source_path': 'data/source.json', 'quote': '已核原文',
                                        'start_ms': 0, 'end_ms': 1000}]},
        {'field': 'seats[1].name', 'evidence': [{'source_path': 'data/missing.json', 'quote': '其他'}]}]
    save(root, path.relative_to(root), review)
    result = local_check.check_game(entry['bvid'], checks=['evidence'], fields=['winner'])
    assert result['valid']
    assert len(result['evidence']) == 1
    assert result['errors'] == []
    assert local_check.review_context({'decisions': [{'field': 'seats.names', 'evidence': []}]},
                                      ['seats[7].name']) == [{'field': 'seats.names', 'evidence': []}]


def test_current_candidate_rejects_upstream_changes(reviewed_game):
    root, entry = reviewed_game
    save(root, 'data/extractions/S23/game_reviews/BVfixture/daily_audit.json', {
        'bvid': entry['bvid'], 'source_sha256': entry['source_sha256'],
        'recap_window': {'start_ms': 0, 'end_ms': 1000}})
    result = builder.build_one(entry['bvid'], require_complete=True)
    candidate = root / result['candidate_dossiers'][0]
    effective.verify_current_candidate(candidate)
    path = root / 'data/extractions/S23/game_reviews/BVfixture/primary_review.json'
    primary = json.loads(path.read_text(encoding='utf-8'))
    primary['patches'][0]['value']['winner'] = 'werewolf'
    save(root, path.relative_to(root), primary)
    with pytest.raises(ValueError, match='候选材料已过期'):
        effective.verify_current_candidate(candidate)


def test_name_dependency_uses_reviewed_date_without_parsing_peer_transcript(reviewed_game, monkeypatch):
    root, entry = reviewed_game
    folder = 'data/extractions/S23/game_reviews/BVfixture/'
    primary = json.loads((root / (folder + 'primary_review.json')).read_text(encoding='utf-8'))
    peer_dossier = deepcopy(primary['patches'][0]['value'])
    primary['patches'][0]['value']['seats'][1]['name'] = None
    save(root, folder + 'primary_review.json', primary)
    peer = {**entry, 'bvid': 'BVpeer', 'index': 1, 'date': '2026-09-09',
            'game_number': 2, 'source_path': 'data/peer.json'}
    save(root, 'data/peer.json', json.loads((root / 'data/source.json').read_text(encoding='utf-8')))
    peer_dossier.update(slug='bili-BVpeer-p01-g02', game_number=2)
    peer_folder = 'data/extractions/S23/game_reviews/BVpeer/'
    save(root, peer_folder + 'dossier.reviewed.json', peer_dossier)
    save(root, peer_folder + 'voting.reviewed.json', {'game_slug': peer_dossier['slug'], 'days': [], 'ballots': []})
    review = json.loads((root / (folder + 'ai_review.json')).read_text(encoding='utf-8'))
    save(root, peer_folder + 'ai_review.json', {**review, 'bvid': peer['bvid']})
    save(root, 'data/reports/S23/S23_逐局复核计划.json', {'entries': [entry, peer]})
    parse = effective.segments
    calls = []
    def count(path):
        calls.append(path)
        return parse(path)
    monkeypatch.setattr(effective, 'segments', count)
    local = effective.load_effective_games([entry['bvid']])
    assert local['dependency_bvids'] == ['BVpeer']
    assert local['games'][0]['dossier']['seats'][1]['name'] == '2'
    assert calls == [root / 'data/source.json']
    full = effective.load_effective_games()
    assert effective.candidate_values(local['games'][0]) == effective.candidate_values(full['games'][0])
    save(root, 'data/peer.json', {'segments': []})
    with pytest.raises(ValueError, match='姓名复用依赖来源已变化'):
        effective.load_effective_games([entry['bvid']])


def test_ballot_order_changes_are_reported_because_final_result_fallback_uses_the_last_ballot():
    ballots = [{'id': 'initial', 'winner': None}, {'id': 'pk', 'winner': 8}]
    differences = local_check.field_differences(ballots, ballots[::-1], 'voting.ballots')
    assert differences == [{'field': 'voting.ballots.order', 'before': ['initial', 'pk'],
                            'after': ['pk', 'initial'], 'change': 'reordered'}]


def test_s23_explicit_new_board_facts_are_not_rewritten_by_the_legacy_slot_projection():
    dossier = {'board': 'qingqiu_night', 'seats': [{'seat': 1, 'role': '九尾狐'}],
               'rounds': [{'number': 1, 'night': [
                   {'slot': 'nine_tail_mark', 'actor': 1, 'action': 'mark', 'targets': [10]}],
                   'day': []}]}
    expected = deepcopy(dossier)
    projected, extra, notes, _ = normalize_schema(dossier)
    assert projected == expected
    assert extra == [] and notes == []
