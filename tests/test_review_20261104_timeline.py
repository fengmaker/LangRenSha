"""Regressions exercised by the 2026-11-04 incremental source records."""
import json
from pathlib import Path

from scripts.game_timeline import build_game_timeline
from scripts.game_review_page import seat_html

ROOT = Path(__file__).resolve().parents[1]


def timeline(folder):
    c = json.loads((ROOT / 'data/extractions/S23/incremental' / folder / 'candidate.json').read_text(encoding='utf8'))
    return build_game_timeline({**c['dossier'], 'endgame': c.get('endgame', {})}, c['voting'])['phases']


def test_all_signup_badge_loss_precedes_night_death_announcement():
    phases = timeline('BV1zzxR6sEB6_p01_cid43331226914')
    first_day = next(p for p in phases if p['number'] == 1 and p['phase'] == 'day')
    slots = [i['slot'] for i in first_day['items']]
    assert slots.index('sheriff_candidates') < slots.index('badge') < slots.index('night_deaths')
    assert phases[-1]['label'] == '第四天白天 · 游戏结束'
    assert sum(i['slot'] == 'binding_victory' for p in phases for i in p['items']) == 1


def test_magician_unknown_remains_visible_and_guile_follows_prince_revote():
    phases = timeline('BV1zzxR6sEos_p01_cid43331356877')
    first_night = phases[0]['items']
    unknown = next(i for i in first_night if i['slot'] == 'magician_exchange')
    assert '待核' in unknown['text'] and '保留未知' in unknown['text']
    last = phases[-1]['items']
    slots = [i['slot'] for i in last]
    assert slots.index('exile_vote') < slots.index('sequential_prince_skill') < slots.index('extra_speech')
    assert slots.index('extra_speech') < slots.index('second_exile_vote') < slots.index('second_exile_result')
    assert slots.index('second_exile_result') < slots.index('guile_exchange_result') < slots.index('wolf_rush')
    assert '好人阵营获胜' in next(i['text'] for i in last if i['slot'] == 'final_adjudication')


def test_self_destruct_then_uncontested_election_then_deaths_and_correct_seer_title():
    phases = timeline('BV16zxR6sEKG_p01_cid43331489387')
    first_day = next(p for p in phases if p['number'] == 1 and p['phase'] == 'day')
    slots = [i['slot'] for i in first_day['items']]
    assert slots.index('self_destruct') < slots.index('sheriff_result') < slots.index('night_deaths')
    checks = [i for p in phases for i in p['items'] if i['slot'] == 'seer_check']
    assert checks and all(i['title'] == '通灵师查验' for i in checks)
    assert phases[-1]['label'] == '第三天夜晚 · 游戏结束'
    assert not any(i['slot'] == 'hunter_shot' for i in phases[-1]['items'])
    assert '3号豆腐' in next(i['text'] for i in phases[-1]['items'] if i['slot'] == 'night_deaths')


def test_mechanical_form_is_an_annotation_on_the_physical_card():
    dossier = {'seats': [{'seat': 1, 'name': '橘子', 'role': '机械狼', 'faction': 'werewolf',
                         'learning_target': 10, 'learned_role': '机械守卫'}], 'rounds': []}
    html = seat_html(dossier)
    assert '<td>机械狼<small>学习10号 · 机械守卫</small></td>' in html
