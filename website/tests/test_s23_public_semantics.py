from copy import deepcopy
from pathlib import Path

import pytest
from website.api import publisher

ROOT=Path(__file__).resolve().parents[2]


def public_variant():
    entries,_,_=publisher.load_publication(ROOT,'S22','BV1yt7v6QE3Q')
    item=deepcopy(entries[0])
    dossier=item['dossier']
    dossier['season']='S23'
    ids={s['name']:'person' for s in dossier['seats']}
    return item,ids


def render(item,ids):
    return publisher._public_game(item['dossier'],item['voting'],item['endgame'],item['audit'],item['board'],ids)


def test_terminal_night_keeps_only_observed_phases_and_explains_blocked_hunter():
    item,ids=public_variant()
    r=item['dossier']['rounds'][0]
    shot=next(e for e in r['day'] if e['slot']=='hunter_shot')
    shot.update(action='unavailable',blocked_by_game_end=True)
    item['dossier']['_publication_context']={'terminal_observation':{'round':r['number'],'phase':'night'}}
    before=deepcopy(item['dossier'])
    game=render(item,ids)
    assert game['rounds'][-1]['day']==[]
    assert game['round_count']==1
    assert any('最后一张神牌' in n for n in game['data_notes'])
    assert item['dossier']==before


def test_invalidated_knife_is_not_a_voluntary_pass_and_keeps_its_semantic_flag():
    item,ids=public_variant()
    knife=next(e for e in item['dossier']['rounds'][0]['night'] if e['slot']=='wolf_attack')
    knife.update(action='invalidated_by_dq',invalidated=True,actor=8,targets=[])
    game=render(item,ids)
    knife=next(e for e in game['rounds'][0]['night'] if e['slot']=='wolf_attack')
    assert knife['invalidated'] is True and knife['action']=='invalidated_by_dq'
    assert any('DQ出局单独记录' in n for n in game['data_notes'])


def test_public_notes_do_not_expose_local_provenance():
    item,ids=public_variant()
    item['dossier']['_publication_context']={'public_notes':['data/extractions/private.json']}
    with pytest.raises(publisher.PublishError,match='本地路径'):
        render(item,ids)
