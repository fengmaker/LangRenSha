"""One read-only event and ballot sequence for review and game-detail pages."""
from __future__ import annotations

from copy import deepcopy
import re

from .board_config import load_canonical_template
from .game_inference import _actual_deaths, build_game_presentation, terminal_day_events, terminal_from_events
from .game_time import phase_label


_INACTIVE = {None, 'unavailable', 'not_applicable', 'not_held', 'forbidden', 'none'}
_UNKNOWN_IMPORTANT = {'guard', 'wolf_attack', 'witch_save', 'witch_poison', 'seer_check',
                      'mechanical_action', 'mechanical_day_skill', 'nine_tail_kill',
                      'puppet_select', 'puppet_skill_effect', 'night_deaths', 'exile_result'}


def _person(number: int | None, seats: dict) -> str:
    row = seats.get(number)
    return (f'{number}号{row.get("name") or "姓名未知"}（{row.get("role") or "身份未知"}）'
            if row else f'{number}号' if number is not None else '')


def _text(event: dict, seats: dict, title: str) -> str:
    actor = _person(event.get('actor'), seats)
    targets = '、'.join(_person(n, seats) for n in event.get('targets', []))
    slot, action = event['slot'], event.get('action')
    result = event.get('display_result') or event.get('result')
    result = {'good': '好人', 'werewolf': '狼人', 'wolf': '狼人'}.get(str(result), result)
    raw_result = event.get('result')
    effect = (raw_result.rstrip('。；') + '。' if isinstance(raw_result, str)
              and re.search(r'实际|反转|反向|失效|免疫|反弹|穿盾|判离', raw_result) else '')
    if slot == 'mixed_blood_model' and action == 'choose':
        return f'{actor}选择{targets}作为榜样。'
    if slot in {'mixed_blood_alignment', 'mixed_blood_victory'}:
        faction = '好人' if action == 'good' else '狼人'
        return f'{actor}本局跟随{faction}阵营。'
    if slot == 'sheriff_candidates':
        if action == 'continued':
            return '继续上一天中断的警长竞选。'
        return '上警：' + targets + '。'
    if slot == 'wolf_attack' and action == 'attack':
        return f'狼队选择击杀{targets}。' + effect
    if action == 'save':
        return f'{actor}使用解药，救起{targets}。'
    if action == 'poison':
        text = f'{actor}使用毒药，目标为{targets}。'
        if event.get('effects') and isinstance(result, str):
            text += result
        return text
    if action == 'check':
        return f'{actor}查验{targets}' + (f'，结果为{result}。' if result else '，查验结果待核。') + effect
    if action == 'guard':
        return f'{actor}守护{targets}。'
    if action == 'learn':
        return f'{actor}学习{targets}' + (f'，学习结果为{result}。' if result else '。')
    if slot == 'night_deaths':
        if action in {'peaceful', 'no_death'}:
            return '天亮，昨夜平安夜。'
        prefix = '本夜' if event.get('terminal') else '昨夜'
        return f'{prefix}出局：{targets}。' if targets else f'{prefix}出局情况待核。'
    if action == 'elected':
        return f'{targets or actor}当选警长。'
    if action == 'deferred':
        return '警长竞选中断，延期至次日继续。'
    if action == 'exile':
        count = re.search(r'(\d+(?:\.\d+)?)票', str(event.get('result') or ''))
        return f'{targets}被放逐' + (f'（{count[1]}票）。' if count else '。')
    if action == 'self_destruct':
        return f'{actor or targets}自爆。'
    if action == 'shoot':
        return f'{actor}开枪带走{targets}。'
    if action == 'transfer':
        return f'警徽{f"由{actor}" if actor else ""}移交给{targets}。'
    if action in {'badge_lost', 'destroy'}:
        return '警徽流失，本局不再进行警长竞选。' if action == 'badge_lost' else '警徽被撕毁。'
    if slot in {'hunter_shot', 'wolf_king_shot'}:
        return (f'{actor}本次出局不能开枪。' if action in {'unavailable', 'cannot_shoot'}
                else f'{actor}本次出局未开枪。' if action == 'pass'
                else f'{actor}本次出局的开枪情况待核。')
    if action == 'pass':
        return '狼队本夜空刀。' if slot == 'wolf_attack' else f'{actor or title}本轮未发动。'
    if action == 'unknown':
        return f'{actor or title}的具体情况待核。'
    if action == 'none' and slot == 'exile_result':
        return '两轮投票均平票，本日无人被放逐。'
    verbs = {'dream': '梦游', 'dance': '邀请共舞', 'give_mask': '给予面具', 'verify': '验证',
             'view': '查看', 'exchange': '交换', 'choose': '选择', 'disqualify': '被判离',
             'die': '出局', 'reveal': '翻牌', 'flip': '翻牌', 'carrying': '接过狼刀'}
    if action in verbs:
        return f'{actor or title}{verbs[action]}{targets}。' + effect
    return event.get('description') or f'{actor or title}：{str(result or action).rstrip("。；")}。'


def _vote_signature(votes: list[dict]) -> list[tuple]:
    return sorted((vote['voter'], vote.get('target')) for vote in votes)


def _recorded_ending(game: dict) -> dict | None:
    explicit = game.get('terminal_observation') or terminal_from_events(game)
    if explicit:
        return explicit
    endings = set()
    for row in game.get('rounds', []):
        for phase in ('night', 'day'):
            for event in row.get(phase, []):
                result = event.get('result')
                if not isinstance(result, str) or not re.search(r'游戏结束|对局结束|结算终局', result):
                    continue
                action, slot = event.get('action'), event.get('slot')
                if slot == 'night_deaths' and action in {'die', 'no_death', 'peaceful'}:
                    endings.add((row['number'], 'night'))
                elif phase == 'night' and (action not in {None, 'unknown', 'unavailable', 'not_applicable'} or '交牌' in result):
                    endings.add((row['number'], phase))
                elif phase == 'day' and (action in {'self_destruct', 'exile', 'surrender'} or '交牌' in result):
                    endings.add((row['number'], phase))
    if len(endings) > 1:
        raise ValueError('事件记录指向不同终局时点，需核对终局边界')
    if endings:
        number, phase = endings.pop()
        return {'round': number, 'phase': phase}
    return None


def _surrender(events: list[dict], seats: dict, winner: str | None, *, terminal: bool) -> tuple[int, dict] | None:
    for index, event in enumerate(events):
        actor = event.get('actor') if event.get('action') == 'surrender' else None
        recorded = event.get('action') == 'surrender'
        if terminal and not recorded:
            result = str(event.get('result') or '')
            match = re.search(r'(\d+)号(?:最后一张)?(?:狼人|机械狼|假面)?(?:选择|决定)?交牌', result)
            if match:
                actor, recorded = int(match[1]), True
            elif re.search(r'狼队(?:选择|决定)?交牌', result):
                recorded = True
        if recorded:
            # A result note can describe surrender after the phase's actual
            # exile or self-destruct, rather than an action at the archive slot.
            if event.get('action') != 'surrender' and event.get('slot') != 'wolf_attack':
                index = len(events)
            outcome = {'good': '好人阵营获胜。', 'werewolf': '狼人阵营获胜。'}.get(winner, '')
            return index, {'kind': 'event', 'slot': 'werewolf_surrender', 'title': '狼人交牌',
                           'text': f'{_person(actor, seats) or "狼人"}选择交牌，游戏结束。{outcome}',
                           'events': [{'slot': 'werewolf_surrender', 'action': 'surrender', 'actor': actor}]}
    return None


def build_game_timeline(game: dict, voting: dict | None = None) -> dict:
    """Project actual phases once; clients render the returned order verbatim.

    Accepts either a formal dossier plus voting or the public game dictionary.
    Archive slots and the existing rule projection are left unchanged.
    """
    source = deepcopy(game)
    source['voting'] = deepcopy(voting if voting is not None else game.get('voting', {}))
    if isinstance(source.get('board'), str):
        source['board'] = {'code': source['board']}
    context = source.get('_publication_context', {})
    if context.get('terminal_observation'):
        source['terminal_observation'] = deepcopy(context['terminal_observation'])
    terminal = _recorded_ending(source)
    if terminal:
        source['terminal_observation'] = terminal
    if terminal and terminal['phase'] == 'night' and not source.get('terminal_events'):
        ending_round = next(row for row in source.get('rounds', []) if row['number'] == terminal['round'])
        source['terminal_events'] = terminal_day_events(ending_round.get('day', []))
    presentation = build_game_presentation(source)
    template = load_canonical_template(source['board']['code'])
    definitions = {slot['code']: slot for phase in ('night', 'day') for slot in template[phase + '_slots']}
    seats = {row['seat']: row for row in source.get('seats', [])}
    roles = {}
    for row in seats.values():
        roles.setdefault(row.get('role'), []).append(row['seat'])
    original_rounds = {row['number']: row for row in source.get('rounds', [])}
    terminal = source.get('terminal_observation') or presentation.get('terminal')
    phases = []
    emitted_ballots = set()
    aligned = set()
    for row in presentation['rounds']:
        number = row['number']
        for phase in ('night', 'day'):
            is_terminal = bool(terminal and terminal['round'] == number and terminal['phase'] == phase)
            if terminal and (number > terminal['round'] or
                             number == terminal['round'] and terminal['phase'] == 'night' and phase == 'day'):
                continue
            original = original_rounds[number].get(phase, [])
            ending_events = (presentation.get('terminal') or {}).get('events', []) if is_terminal else []
            surrender = _surrender(original + ending_events, seats, source.get('winner'), terminal=is_terminal)
            events = deepcopy(row[phase])
            if is_terminal and not surrender:
                events += deepcopy((presentation.get('terminal') or {}).get('events', []))
            if phase == 'night':
                carrying = [e for e in events if e['slot'] == 'mechanical_knife_status' and e.get('action') == 'carrying']
                events = carrying + [e for e in events if e not in carrying]
            if phase == 'day':
                election_finished = any(
                    event.get('action') in {'elected', 'badge_lost'}
                    for earlier in source.get('rounds', []) if earlier['number'] < number
                    for event in earlier.get('day', [])
                    if event.get('slot') in {'sheriff_result', 'badge'})
                if election_finished:
                    events = [e for e in events if not (e['slot'] == 'sheriff_candidates' and e.get('action') == 'continued')]
                registration = next((r for r in source['voting'].get('registrations', []) if r['day'] == number), None)
                if registration and registration.get('on_police') is not None and number == 1:
                    events.insert(0, {'slot': 'sheriff_candidates', 'action': 'register',
                                      'targets': registration['on_police'], 'votes': []})
                # Some retained games have voting supplements without a typed
                # vote slot. Keep those real ballots at their result anchor.
                for kind, vote_slot, result_slot in [('sheriff', 'sheriff_vote', 'sheriff_result'),
                                                      ('exile', 'exile_vote', 'exile_result')]:
                    ballots = [b for b in source['voting'].get('ballots', []) if b['day'] == number and b['kind'] == kind]
                    if ballots and not any(e['slot'] == vote_slot for e in events):
                        votes = [{'round': b['number'], 'voter': v['voter'], 'target': v['target']}
                                 for b in ballots for v in b['votes']]
                        at = next((i for i, e in enumerate(events) if e['slot'] == result_slot), len(events))
                        events.insert(at, {'slot': vote_slot, 'action': 'vote', 'votes': votes})
                deferred = [e for e in events if e['slot'] == 'sheriff_result' and e.get('action') == 'deferred']
                if deferred and any(e.get('action') == 'self_destruct' for e in events):
                    events = [e for e in events if e not in deferred]
                    at = next(i + 1 for i, e in enumerate(events) if e.get('action') == 'self_destruct')
                    events[at:at] = deferred
            if surrender:
                stop_index, _ = surrender
                allowed = {e['slot'] for e in original[:stop_index]}
                if stop_index < len(original) and original[stop_index].get('action') not in _INACTIVE | {'unknown'}:
                    allowed.add(original[stop_index]['slot'])
                events = [e for e in events if e['slot'] in allowed]
                if is_terminal and phase == 'night':
                    events += [e for e in ending_events if e.get('action') not in _INACTIVE | {'unknown'}]

            # A player's alignment belongs beside their model choice, rather
            # than at the end of the archival night template.
            alignments = [e for e in events if e['slot'] == 'mixed_blood_alignment']
            if alignments:
                events = [e for e in events if e['slot'] != 'mixed_blood_alignment']
                at = next((i + 1 for i, e in enumerate(events) if e['slot'] == 'mixed_blood_model'), len(events))
                events[at:at] = alignments
            departures = _actual_deaths(original)
            items = []
            for event in events:
                slot, action = event['slot'], event.get('action')
                actor = event.get('actor')
                if actor is None:
                    candidates = roles.get(definitions.get(slot, {}).get('actor_role'), [])
                    if len(candidates) == 1:
                        actor = event['actor'] = candidates[0]
                title = event.get('slot_label') or definitions.get(slot, {}).get('label', slot)
                title = {'wolf_attack': '狼队击杀', 'mixed_blood_model': '混血儿选择榜样',
                         'dancer_dance': '舞者共舞'}.get(slot, title)
                if slot == 'sheriff_candidates' and action == 'continued':
                    title = '继续警长竞选'
                if slot in {'hunter_state', 'wolf_king_state', 'puppet_hunter_eligibility'}:
                    continue
                if slot == 'mixed_blood_model' and number != 1:
                    continue
                if slot in {'mixed_blood_alignment', 'mixed_blood_victory'}:
                    if action not in {'good', 'wolf'} or actor in aligned:
                        continue
                    aligned.add(actor)
                if slot == 'sheriff_candidates' and (number != 1 and action != 'continued' or action not in {'register', 'continued'}):
                    continue
                if slot == 'badge' and action not in {'transfer', 'destroy', 'badge_lost'}:
                    continue
                if slot in {'hunter_shot', 'wolf_king_shot'}:
                    if event.get('blocked_by_game_end') or action != 'shoot' and actor not in departures:
                        continue
                    title = '猎人技能' if slot == 'hunter_shot' and action != 'shoot' else title
                if slot.endswith('_vote'):
                    if action != 'vote':
                        continue
                    kind = 'sheriff' if slot == 'sheriff_vote' else 'exile'
                    candidates = [b for b in source['voting'].get('ballots', [])
                                  if b['day'] == number and b['kind'] == kind and b['id'] not in emitted_ballots]
                    vote_groups = {}
                    for vote in event.get('votes', []):
                        vote_groups.setdefault(vote.get('round', 1), []).append(vote)
                    selected = []
                    for group in vote_groups.values():
                        match = next((b for b in candidates if b not in selected
                                      and _vote_signature(b['votes']) == _vote_signature(group)), None)
                        if match is not None:
                            selected.append(match)
                    if not selected:
                        selected = candidates[:1]
                    for ballot in selected:
                        suffix = {'pk': ' · PK复投', 'revote': ' · 技能重投'}.get(ballot.get('stage'), '')
                        items.append({'kind': 'ballot', 'slot': slot, 'title': title + suffix,
                                      'ballot': deepcopy(ballot)})
                        emitted_ballots.add(ballot['id'])
                    continue
                double_tie = slot == 'exile_result' and action == 'none' and '平票' in str(event.get('result'))
                hunter_departure = slot in {'hunter_shot', 'wolf_king_shot'} and actor in departures
                if action in _INACTIVE and not double_tie and not hunter_departure:
                    continue
                if action == 'unknown' and slot not in _UNKNOWN_IMPORTANT and not hunter_departure:
                    continue
                item = {'kind': 'event', 'slot': slot, 'title': title,
                        'text': _text(event, seats, title), 'events': [event]}
                if slot in {'witch_save', 'witch_poison'}:
                    prior = next((i for i in items if i['slot'] == 'witch_medicine'
                                  and i['events'][0].get('actor') == actor), None)
                    if prior is not None:
                        prior['events'].append(event)
                        prior['text'] += '\n' + item['text']
                        continue
                    item['slot'], item['title'] = 'witch_medicine', '女巫用药'
                items.append(item)
            if surrender:
                items.append(surrender[1])
                is_terminal = True
            elif is_terminal:
                outcome = {'good': '好人阵营获胜。', 'werewolf': '狼人阵营获胜。', 'draw': '本局平局。'}.get(source.get('winner'))
                if outcome:
                    items.append({'kind': 'event', 'slot': 'game_result', 'title': '本局结果', 'text': outcome, 'events': []})
            if items:
                phases.append({'number': number, 'phase': phase, 'terminal': is_terminal,
                               'label': phase_label(number, phase) + (' · 游戏结束' if is_terminal else ''),
                               'items': items})
            if surrender:
                return {'phases': phases}
    return {'phases': phases}
