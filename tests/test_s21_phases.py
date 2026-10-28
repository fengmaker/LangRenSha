"""Source, identity and ballot boundaries of the partial S21 phase import."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import s21_phase_review as phase


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(phase,'ROOT',tmp_path)
    b='BVphase'
    def save(path,obj):
        file=tmp_path/path;file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8')
    save(phase.INDEX,{'entries':[{'bvid':b,'cid':12,'page':1}]})
    raw=Path('data/raw/source.json');save(raw,{'original':'unaltered'})
    sha=hashlib.sha256((tmp_path/raw).read_bytes()).hexdigest()
    save(Path(f'data/extractions/S21/media_evidence/{b}/transcript.selected.json'),
         {'source_path':raw.as_posix(),'source_sha256':sha,'segments':[
             {'start_ms':1,'end_ms':2,'text':'首夜狼人击杀2号'},
             {'start_ms':3,'end_ms':4,'text':'1号投给2号'},
             {'start_ms':5,'end_ms':6,'text':'投票结束2号出局'},]})
    save(Path(f'data/extractions/S21/game_reviews/{b}/identity.reviewed.json'),
         {'bvid':b,'cid':12,'page':1,'seats':[{'seat':n,'name':str(n),'role':'狼人' if n==1 else '平民'} for n in range(1,13)]})
    spec={'bvid':b,'recap_spans':[[0,0]],'live_spans':[[1,2]],
          'events':[['night',1,'wolf_attack',None,[2],[0]]],
          'ballots':[{'day':1,'type':'exile','source':[1,2],'votes':[[1,2,[1]]],
                      'eligible_voters':[1],'eligibility_source':[1],'complete':True}]}
    return spec,tmp_path/raw


def test_literal_words_and_times_are_bound_not_generated(fixture):
    spec,_=fixture;value=phase.build(spec)
    assert value['events'][0]['evidence'][0]['quote']=='首夜狼人击杀2号'
    assert value['events'][0]['evidence'][0]['time_kind']=='evidence_location_not_actual_event_time'
    assert value['excluded_scope']==['bluffs','public_role_claims']


def test_changed_original_text_is_rejected(fixture):
    spec,path=fixture;path.write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='hash changed'):phase.build(spec)


def test_duplicate_or_conflicting_vote_is_rejected(fixture):
    spec,_=fixture;spec['ballots'][0]['votes'].append([1,3,[1]])
    with pytest.raises(ValueError,match='duplicate'):phase.build(spec)


def test_unknown_eligibility_does_not_become_complete(fixture):
    spec,_=fixture;spec['ballots'][0]['eligible_voters']=None
    with pytest.raises(ValueError,match='proven voter set'):phase.build(spec)


def test_bluff_fields_cannot_cross_scope(fixture):
    spec,_=fixture;spec['bluffs']=[{'fabricated':True}]
    with pytest.raises(ValueError,match='outside this stage'):phase.build(spec)


def test_pass_and_unknown_cannot_have_success_targets(fixture):
    spec,_=fixture;spec['events'][0].append({'state':'unknown'})
    with pytest.raises(ValueError,match='invent'):phase.build(spec)


@pytest.mark.parametrize('state', ['pass', 'unknown', 'forbidden', 'not_applicable'])
def test_unperformed_actions_cannot_have_actual_targets(fixture, state):
    spec, _ = fixture
    spec['events'][0][4] = []
    spec['events'][0].append({'state': state, 'actual_targets': [2]})
    with pytest.raises(ValueError, match='invent'):
        phase.build(spec)


def test_performed_actions_preserve_actual_targets(fixture):
    spec, _ = fixture
    spec['events'][0].append({'actual_targets': [2]})
    assert phase.build(spec)['events'][0]['actual_targets'] == [2]


def test_event_vote_and_gap_references_share_the_selected_source_hash(fixture):
    spec, _ = fixture
    spec['gaps'] = [{'field': 'unclear_result', 'reason': '待核', 'sources': [0]}]
    result = phase.build(spec)
    expected = phase.sha(result['source']['selected_path'])
    ballot = result['ballots'][0]
    references = [*result['events'][0]['evidence'], *ballot['evidence'],
                  *ballot['votes'][0]['evidence'], *ballot['eligibility_evidence'],
                  *result['coverage']['gaps'][0]['evidence']]
    assert result['source']['selected_sha256'] == expected
    assert all(reference['source_sha256'] == expected for reference in references)


def test_unresolved_gap_also_keeps_verbatim_same_media_evidence(fixture):
    spec,_=fixture
    spec['gaps']=[{'phase':'night','round':1,'field':'unclear_result',
                   'reason':'需要继续核实','sources':[0]}]
    gap=phase.build(spec)['coverage']['gaps'][0]
    assert gap['evidence'][0]['quote']=='首夜狼人击杀2号'
    assert 'BVphase' in gap['evidence'][0]['source_path']


def test_gap_with_invalid_source_index_is_rejected(fixture):
    spec,_=fixture
    spec['gaps']=[{'field':'unclear_result','reason':'invalid locator','sources':[999]}]
    with pytest.raises(ValueError,match='valid literal'):phase.build(spec)
