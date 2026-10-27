from copy import deepcopy
import hashlib
import json

import pytest

from scripts.s23_bluff_audit import AuditError,load_audits
from scripts.build_s23_bluff_publication import _evidence
from website.api.bluff_frames import public_image_url
from website.api import bluff_frames
from fastapi.testclient import TestClient
from website.api.app import app
from website.api.bluffs import review_items
from website.tests.test_bluffs import sample,review

BVID='BV1KfYE6HEDv'


def fixture(tmp_path):
    source=tmp_path/f'data/{BVID}.json'
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({'body':[{'from':1,'to':3,'content':'我是预言家，验12金水'}]},ensure_ascii=False),encoding='utf-8')
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    seat={'seat':10,'name':'狼甲','role':'狼人','faction':'werewolf'}
    game={'id':'game','source':{'bvid':BVID},'seats':[seat]}
    row={'seat':10,'name':'狼甲','physical_role':'狼人','decision':'yes','claimed_role':'预言家',
         'decision_note':'本人直接自称，与导播摘要交叉核对。','evidence':[{'kind':'transcript','source_path':f'data/{BVID}.json',
         'source_sha256':sha,'start_ms':1000,'end_ms':3000,'text':'我是预言家，验12金水'}]}
    audit={'game_id':'game','bvid':BVID,'source_path':f'data/{BVID}.json','source_sha256':sha,'assessments':[row]}
    part=tmp_path/'data/extractions/S23/bluff_review/parts/audit_a.json'
    part.parent.mkdir(parents=True)
    return [game],audit,part


def write(part,audit):
    part.write_text(json.dumps({'games':[audit]},ensure_ascii=False),encoding='utf-8')


def test_recheck_accepts_a_source_bound_self_claim(tmp_path):
    games,audit,part=fixture(tmp_path)
    write(part,audit)
    assert load_audits(tmp_path,games)['game']['assessments'][0]['decision']=='yes'


@pytest.mark.parametrize('mutation',['wrong_quote','wrong_time','wrong_hash','wrong_role','missing_wolf'])
def test_recheck_rejects_unverifiable_quotes_and_stale_identity(tmp_path,mutation):
    games,audit,part=fixture(tmp_path)
    row=audit['assessments'][0]
    evidence=row['evidence'][0]
    if mutation=='wrong_quote':evidence['text']='我是通灵师，验1女巫'
    if mutation=='wrong_time':evidence.update(start_ms=20000,end_ms=21000)
    if mutation=='wrong_hash':evidence['source_sha256']='0'*64
    if mutation=='wrong_role':row['physical_role']='机械狼'
    if mutation=='missing_wolf':audit['assessments']=[]
    write(part,audit)
    with pytest.raises(AuditError):load_audits(tmp_path,games)


def test_partial_recheck_is_inspectable_but_cannot_replace_the_full_release(tmp_path):
    games,audit,part=fixture(tmp_path)
    games.append({**deepcopy(games[0]),'id':'another-game'})
    write(part,audit)
    assert len(load_audits(tmp_path,games,require_complete=False))==1
    with pytest.raises(AuditError,match='尚未覆盖全部'):load_audits(tmp_path,games)


def test_only_digest_named_same_origin_screenshots_are_exposed():
    sha='a'*64
    rows=_evidence([{'kind':'video_frame','source_path':'private/frame.png','source_sha256':sha,'frame_time_ms':2000,'text':'验12金水'}])
    assert rows[0]['image_url']==f'/media/bluff-frames/S23/{sha}.png'
    assert 'private' not in json.dumps(rows)
    assert public_image_url(rows[0]['image_url'])==rows[0]['image_url']
    assert public_image_url('file:///D:/private/frame.png') is None
    assert public_image_url('/media/bluff-frames/S23/../../private.png') is None


def test_frame_endpoint_serves_only_manifest_listed_images(tmp_path,monkeypatch):
    assets=tmp_path/'assets'
    (assets/'S23').mkdir(parents=True)
    filename='a'*64+'.png'
    (assets/'S23'/filename).write_bytes(b'original-frame-bytes')
    unlisted='b'*64+'.png'
    (assets/'S23'/unlisted).write_bytes(b'private-unlisted-frame')
    manifest=tmp_path/'frames.json'
    manifest.write_text(json.dumps({'frames':{'S23':{filename:{'bvid':BVID}}}}),encoding='utf-8')
    monkeypatch.setattr(bluff_frames,'ASSETS',assets)
    monkeypatch.setattr(bluff_frames,'MANIFEST',manifest)
    bluff_frames.manifest.cache_clear()
    try:
        client=TestClient(app)
        response=client.get('/api/v1/bluff-frames/S23/'+filename)
        assert response.status_code==200 and response.content==b'original-frame-bytes'
        assert response.headers['content-type']=='image/png'
        assert response.headers['x-content-type-options']=='nosniff'
        assert client.get('/api/v1/bluff-frames/S23/'+unlisted).status_code==404
        assert client.get('/api/v1/bluff-frames/S22/'+filename).status_code==404
        assert bluff_frames.frame_path('S23','../../private.png') is None
    finally:
        bluff_frames.manifest.cache_clear()


def test_unfinished_assistant_work_is_not_sent_to_the_user():
    game=sample();payload=review(game)
    row=payload['games'][0]['assessments'][0]
    row.update(decision='uncertain',review_stage='assistant_pending',requires_user_review=False)
    item=review_items([game],payload)[0]
    assert item['needs_review'] and item['assistant_pending'] and not item['requires_user_review']
    row.update(review_stage='reviewed',requires_user_review=True)
    item=review_items([game],payload)[0]
    assert item['requires_user_review'] and not item['assistant_pending']


def test_known_late_claim_does_not_reuse_an_earlier_badge():
    game=sample(exile=2,badge=1);payload=review(game)
    row=payload['games'][0]['assessments'][0]
    row.update(claim_day='later',actual_claim_day=4,review_stage='reviewed',requires_user_review=False)
    item=review_items([game],payload)[0]
    assert item['decision']=='yes' and item['success'] is False
    assert not item['needs_review'] and not item['assistant_pending']


def test_supplementary_badge_loss_resolves_only_missing_result():
    game=sample(exile=None)
    game['rounds'][0]['day']=[]
    game['voting']['days'][0].update(sheriff='unknown',exile='interrupted_self_destruct')
    payload=review(game)
    assert review_items([game],payload)[0]['success'] is None
    payload['games'][0]['result_review']={'badge':'lost','note':'法官与复盘明确流徽',
                                          'evidence':[{'kind':'transcript','text':'本局游戏警徽流失','start_ms':2677070}]}
    assert review_items([game],payload)[0]['success'] is False
    elected=sample(exile=None,badge=1)
    elected_payload=review(elected)
    elected_payload['games'][0]['result_review']=payload['games'][0]['result_review']
    assert review_items([elected],elected_payload)[0]['success'] is True


def test_supplementary_result_requires_source_bound_evidence(tmp_path):
    games,audit,part=fixture(tmp_path)
    proof=deepcopy(audit['assessments'][0]['evidence'][0])
    proof['text']='本局游戏警徽流失'
    audit['result_review']={'badge':'lost','note':'补充流徽','evidence':[proof]}
    write(part,audit)
    with pytest.raises(AuditError,match='补充警徽结果'):
        load_audits(tmp_path,games)


def test_publishing_rejects_result_review_that_conflicts_with_formal_election():
    from website.api.bluff_store import _validate_review,BluffReviewError
    from website.tests.test_bluff_store import sample_game,sample_payload
    game=sample_game();game['season']='S23'
    payload=sample_payload(game);payload['season']='S23'
    payload['games'][0].update(coverage='first_day_video_and_transcript',
        result_review={'badge':'lost','note':'流徽','evidence':[{'kind':'transcript','text':'本局警徽流失'}]})
    with pytest.raises(BluffReviewError,match='冲突'):
        _validate_review([game],payload,'S23',1)
