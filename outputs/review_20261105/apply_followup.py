"""Apply the user's two explicit follow-up corrections using existing importers."""
from copy import deepcopy
from pathlib import Path
import json
import shutil
import subprocess
import sys

ROOT = Path('D:/langrensha')
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]
import apply_incremental_review as app
from incremental_common import load_state, save_state, work_dir, write_json
from game_derivations import derive_game
from game_records import import_game, validate as validate_game
from voting_records import import_voting, validate as validate_voting
from endgame_records import import_endgame, validate as validate_endgame
from database import connect
from psycopg.types.json import Jsonb

feedback = ROOT / 'data/manual_review/feedback'
original = feedback / 'S23_逐局复核意见_20261105_20261104.json'
review_path = feedback / 'S23_逐局复核意见_20261105_补充修订.json'
revision_path = feedback / 'S23_备注结构化修订_20261105.json'
payload = json.loads(original.read_text(encoding='utf-8'))
state = load_state(ROOT, 'S23')
specs = {
    'BV1zzxR6sEos': (0, 4, '第二局魔术师首夜行动 空过的'),
    'BV16zxR6sEKG': (2, 6, '那就第二天夜晚空过，无所谓了'),
}
revisions = {'format': app.NOTE_REVISIONS_FORMAT, 'season': 'S23', 'games': []}
plans = []
archive_root = ROOT / 'data/reports/S23/incremental/revisions/20261105_before_followup'
for game in payload['games']:
    if game['bvid'] not in specs:
        continue
    ri, ei, note = specs[game['bvid']]
    game['note'] = note
    key, item, entry, candidate_path, source_path = app._state_item(state, game, ROOT, 'S23')
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    app._verify_disk_identity(game, item, entry, candidate, candidate_path, source_path, 'S23')
    folder = work_dir(ROOT, 'S23', entry)
    prior = json.loads((folder / 'accepted_review.json').read_text(encoding='utf-8'))
    prefix = f'/dossier/rounds/{ri}/night/{ei}'
    revision = {
        'review_id': game['review_id'], 'candidate_sha256': game['candidate_sha256'],
        'source_sha256': game['source_sha256'], 'note': note,
        'patches': [
            {'path': prefix + '/action', 'value': 'pass', 'note_quote': note, 'reason': '用户明确确认空过。'},
            {'path': prefix + '/result', 'value': None, 'note_quote': note, 'reason': '清除已被用户确认解决的未知说明。'},
        ],
        'unresolved': [], 'bluffs': {'reviewed': False, 'no_bluff': False, 'items': []},
        'previous_review_path': (archive_root / game['bvid'] / 'accepted_review.json').relative_to(ROOT).as_posix(),
        'previous_manual_source_path': prior['manual_source_path'],
        'previous_manual_sha256': prior['manual_sha256'],
        'conversation_context': (
            '第三局第二天夜晚刀5号通灵师，3号猎人仍存活；用户在澄清后确认该夜机械守卫空过。'
            '第三天夜晚刀3号最后一神后立即结束，后续守护和猎枪均无窗口。'
            if game['bvid'] == 'BV16zxR6sEKG' else '用户补充确认第二局首夜9号魔术师空过。'
        ),
    }
    accepted, patches, _, unresolved = app._apply_note_result(candidate, note, game['review_id'], revision)
    assert not unresolved
    accepted['issues'] = []  # Each candidate had exactly the now-resolved action gap.
    endgame = deepcopy(accepted.get('endgame', {'schema_version': 1, 'game_slug': accepted['dossier']['slug'], 'phases': []}))
    derived = derive_game(accepted['dossier'], accepted['voting'], endgame=endgame)
    prepared = {**derived, 'endgame': endgame}
    assert not prepared['derivations']['issues'], prepared['derivations']['issues']
    validate_game(prepared['dossier'], check_files=True, allow_incomplete=True)
    validate_voting(prepared['voting'])
    validate_endgame(endgame)
    revisions['games'].append(revision)
    plans.append({'key': key, 'game': game, 'item': item, 'entry': entry, 'folder': folder,
                  'candidate_path': candidate_path, 'source_path': source_path,
                  'candidate': accepted, 'prepared_formal': prepared, 'revision': revision,
                  'prior': prior, 'patches': patches, 'formal_dir': ROOT / item['formal_dir']})

write_json(review_path, payload)
write_json(revision_path, revisions)
write_json(ROOT / 'data/reports/S23/incremental/20261105_followup_preview.json', revisions)
subprocess.run([sys.executable, str(ROOT / 'scripts/backup_database.py')], cwd=ROOT, check=True)
manual_sha = app.sha256_file(review_path)
manual_archive = ROOT / f'data/reports/S23/incremental/reviews/{manual_sha}.json'
manual_archive.parent.mkdir(parents=True, exist_ok=True)
manual_archive.write_bytes(review_path.read_bytes())
receipts = []
for plan in plans:
    game, item, folder, prepared = plan['game'], plan['item'], plan['folder'], plan['prepared_formal']
    archive = archive_root / game['bvid']
    archive.mkdir(parents=True, exist_ok=False)
    for name in ['accepted_candidate.json', 'accepted_review.json', 'accepted_formal.json']:
        shutil.copyfile(folder / name, archive / name)
    shutil.copytree(plan['formal_dir'], archive / 'formal')
    record = app._review_record(plan['candidate'], plan['entry'], game, game['note'], plan['patches'],
                                manual_archive.relative_to(ROOT).as_posix(), manual_sha,
                                plan['prior']['bluffs_review'])
    record['note_revision'] = plan['revision']
    record['dossier_sha256'] = app._json_sha256(prepared['dossier'])
    record['voting_sha256'] = app._json_sha256(prepared['voting'])
    with connect() as conn:
        game_receipt = import_game(prepared['dossier'], allow_incomplete=True, conn=conn,
                                   derivations=prepared['derivations'])
        voting_receipt = import_voting(prepared['voting'], conn=conn)
        endgame_receipt = import_endgame(prepared['endgame'], conn=conn)
        conn.execute('''INSERT INTO game_formal_annotations
            (game_id,annotation_key,annotation_type,source_path,source_sha256,payload)
            VALUES(%s,%s,'review_context',%s,%s,%s)
            ON CONFLICT(game_id,annotation_key) DO UPDATE SET source_path=EXCLUDED.source_path,
            source_sha256=EXCLUDED.source_sha256,payload=EXCLUDED.payload,recorded_at=now()''',
            (game_receipt['game_id'], 'user-followup-20261105', revision_path.relative_to(ROOT).as_posix(),
             app.sha256_file(revision_path), Jsonb(plan['revision'])))
    outputs = {'dossier.json': prepared['dossier'], 'voting.json': prepared['voting'],
               'endgame.json': prepared['endgame'], 'rule_derivations.json': prepared['derivations'],
               'incremental_review.json': record}
    for name, value in outputs.items():
        write_json(plan['formal_dir'] / name, value)
    write_json(folder / 'accepted_candidate.json', plan['candidate'])
    write_json(folder / 'accepted_review.json', record)
    write_json(folder / 'accepted_formal.json', prepared)
    item['accepted_candidate_sha256'] = app.sha256_file(folder / 'accepted_candidate.json')
    item['accepted_formal_sha256'] = app.sha256_file(folder / 'accepted_formal.json')
    item['formal_files'] = {name: app.sha256_file(plan['formal_dir'] / name) for name in outputs}
    item['database_receipt'].update(game=game_receipt, voting=voting_receipt, endgame=endgame_receipt)
    item['phases']['publish'] = 'pending'
    item['phases']['verify'] = 'pending'
    item['followup_revision_path'] = revision_path.relative_to(ROOT).as_posix()
    receipts.append({'bvid': game['bvid'], 'game': game_receipt, 'voting': voting_receipt,
                     'endgame': endgame_receipt, 'note': game['note']})
    save_state(ROOT, 'S23', state)
report = {'state': 'completed', 'review': review_path.relative_to(ROOT).as_posix(),
          'revision': revision_path.relative_to(ROOT).as_posix(), 'games': receipts}
write_json(ROOT / 'data/reports/S23/incremental/20261105_followup_receipt.json', report)
print(json.dumps(report, ensure_ascii=False, indent=2))
