import csv
import json
from pathlib import Path
import re
import shutil

from scripts import build_pending_slot_review as builder
from scripts.game_derivations import derive_game

ROOT = Path(__file__).resolve().parents[1]


def page_data(path, script_id):
    match = re.search(rf'<script id="{script_id}" type="application/json">(.*?)</script>',
                      path.read_text(encoding='utf-8'), re.S)
    return json.loads(match[1])


def test_rebuild_removes_applied_answers_but_keeps_hidden_evidence_questions_and_draft_chain(tmp_path, monkeypatch):
    report = json.loads((ROOT / 'data/reports/shared/日夜深度复核交付_20261030.json').read_text(encoding='utf-8'))
    ids = {'DN-146', 'DN-196', 'DN-160', 'DN-230', 'DN-072'}
    items = [item for item in report['items'] if item['编号'] in ids]
    manual, reports = tmp_path / 'data/manual_review', tmp_path / 'data/reports/shared'
    manual.mkdir(parents=True)
    reports.mkdir(parents=True)
    (reports / '日夜深度复核交付_20261030.json').write_text(json.dumps({'items': items}), encoding='utf-8')
    csv_path = manual / '日夜深度复核剩余待核_20261030.csv'
    with (ROOT / 'data/manual_review/日夜深度复核剩余待核_20261030.csv').open(encoding='utf-8-sig') as source:
        columns = csv.DictReader(source).fieldnames
    with csv_path.open('w', encoding='utf-8-sig', newline='') as destination:
        writer = csv.DictWriter(destination, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: item.get(column, '') for column in columns} for item in items)
    for item in items:
        folder = Path(item['档案文件']).parent
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
        for name in ['dossier.json', 'voting.json', 'rule_derivations.json']:
            shutil.copyfile(ROOT / folder / name, tmp_path / folder / name)
        if item['编号'] == 'DN-072':
            # This fixture represents the previously unconfirmed shot; the
            # production game has since received the user's final ruling.
            dossier = json.loads((tmp_path / folder / 'dossier.json').read_text(encoding='utf-8'))
            voting = json.loads((tmp_path / folder / 'voting.json').read_text(encoding='utf-8'))
            shot = next(e for e in dossier['rounds'][1]['day'] if e['slot'] == 'hunter_shot')
            shot.update(action='unknown', result='拍刀后猎人是否响应未说明')
            shot.pop('blocked_by_game_end', None)
            prepared = derive_game(dossier, voting)
            for name, value in [('dossier', dossier), ('rule_derivations', prepared['derivations'])]:
                (tmp_path / folder / (name + '.json')).write_text(json.dumps(value), encoding='utf-8')
    template = Path('scripts/templates/pending_slot_review.html')
    (tmp_path / template.parent).mkdir(parents=True)
    shutil.copyfile(ROOT / template, tmp_path / template)
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    monkeypatch.setattr(builder, 'MANUAL_REVIEW', manual)
    monkeypatch.setattr(builder, 'REPORT', reports)

    builder.main()
    output = manual / '日夜待核槽位人工复核_20261030.html'
    current = page_data(output, 'review-data')
    remaining = {q['id'] for g in current['games'] for q in g['questions']}
    assert remaining == {'DN-160', 'DN-230', 'DN-072'}
    assert set(current['review_notes']) == remaining
    assert '拍刀' in current['review_notes']['DN-072']
    with csv_path.open(encoding='utf-8-sig') as source:
        assert {row['编号'] for row in csv.DictReader(source)} == remaining
    archive = json.loads((manual / 'feedback/待核槽位已结清_20261102.json').read_text(encoding='utf-8'))
    assert {item['id'] for item in archive['items']} == {'DN-146', 'DN-196'}
    assert '首夜未知守护统一按空守处理' in output.read_text(encoding='utf-8')

    # An older draft can include both surviving questions and resolved answers.
    previous = {**current, 'source_fingerprint': 'previous-version'}
    html = output.read_text(encoding='utf-8')
    html = re.sub(r'(<script id="review-data" type="application/json">).*?(</script>)',
                  lambda m: m[1] + json.dumps(previous) + m[2], html, flags=re.S)
    old_chain = {'source_fingerprint': 'older-version', 'question_ids': sorted(ids)}
    html = re.sub(r'(<script id="draft-migration" type="application/json">).*?(</script>)',
                  lambda m: m[1] + json.dumps(old_chain) + m[2], html, flags=re.S)
    output.write_text(html, encoding='utf-8')
    builder.main()
    migration = page_data(output, 'draft-migration')
    assert migration['source_fingerprint'] == 'previous-version'
    assert set(migration['question_ids']) == remaining
    assert migration['previous'] == old_chain
    assert page_data(output, 'review-data') == current


def test_partially_recorded_check_is_still_reviewable():
    state = {'status': 'available', 'review_required': False}
    assert builder.needs_review({'action': 'check', 'targets': [2], 'result': None}, state)
    assert not builder.needs_review({'action': 'check', 'targets': [2], 'result': 'good'}, state)
