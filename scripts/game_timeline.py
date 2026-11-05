"""One read-only event and ballot sequence for review and game-detail pages."""
from __future__ import annotations

from copy import deepcopy
import re

from .board_config import load_canonical_template
from .game_inference import _actual_deaths, build_game_presentation, terminal_from_events
from .game_time import phase_label
from .role_constraints import family, puppet_target


_INACTIVE = {None, 'unavailable', 'not_applicable', 'not_held', 'forbidden', 'none', 'no_skill'}
_UNKNOWN_IMPORTANT = {'guard', 'wolf_attack', 'witch_save', 'witch_poison', 'seer_check',
                      'magician_exchange',
                      'mechanical_action', 'mechanical_day_skill', 'nine_tail_kill',
                      'puppet_select', 'puppet_skill_effect', 'night_deaths', 'exile_result',
                      'masquerade_attack', 'wolf_girl_confession', 'troublemaker_action'}
_COMMON_TITLES = {
    'guard': '守卫守护', 'wolf_attack': '狼队击杀',
    'witch_save': '女巫解药', 'witch_poison': '女巫毒药', 'seer_check': '预言家查验',
    'sheriff_candidates': '上警名单', 'sheriff_vote': '警长投票',
    'sheriff_result': '警长结果', 'night_deaths': '夜间出局',
    'badge': '警徽', 'self_destruct': '狼人自爆',
    'wolf_girl_confession': '狼女孩表白', 'troublemaker_action': '捣蛋鬼行动',
    'game_end': '对局结束',
    'exile_vote': '放逐投票', 'exile_result': '放逐结果',
    'magician_exchange': '魔术师交换', 'magic_duel_magician_swap': '魔术师交换',
    'sorcerer_exchange': '狼术师交换', 'magic_duel_wolf_sorcerer_swap': '狼术师交换',
    'warden_trade_targets': '典狱长选择交易对象', 'trade_decisions': '双方交易选择',
    'trade_resolution': '交易结算', 'wolf_rush': '狼人拍刀',
    'whiteze_clear': '白泽清除标记', 'whiteze_clear_mark': '白泽清除标记',
    'nine_tail_hunt': '九尾狐猎杀', 'nine_tail_skill': '九尾狐猎杀',
}


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
    puppet_note = event.get('puppet_note', '')
    failed = bool(re.search(r'failed|fail|失败|失效|未生效|未成功', str(result or '') + puppet_note, re.I))
    raw_result = event.get('result')
    effect = (raw_result.rstrip('。；') + '。' if isinstance(raw_result, str)
              and re.search(r'实际|反转|反向|失效|免疫|反弹|穿盾|判离', raw_result) else '')
    if puppet_note and '傀儡' not in effect:
        effect += puppet_note
    if slot == 'mixed_blood_model' and action == 'choose':
        return f'{actor}选择{targets}作为榜样。'
    if slot == 'puppet_select' and action == 'select':
        return f'狼队指定{targets}成为傀儡，个人胜利阵营为狼人，底牌不变。'
    if slot in {'mixed_blood_alignment', 'mixed_blood_victory'}:
        faction = '好人' if action == 'good' else '狼人'
        return f'{actor}本局跟随{faction}阵营。'
    if slot == 'sheriff_candidates':
        if action == 'continued':
            return '继续上一天中断的警长竞选。'
        text = ('本轮候选：' if event.get('candidate_stage') == 'remaining' else '上警：') + targets + '。'
        if event.get('off_police') is not None:
            text += '\n警下：' + ('、'.join(_person(n, seats) for n in event['off_police']) or '无人') + '。'
        return text
    if slot == 'wolf_rush':
        subject = actor or '狼人'
        text = f'{subject}发动拍刀' + (f'，目标集合为{targets}。' if targets else '，目标待核。')
        if result in {'werewolf_win', 'good_win', 'draw'}:
            return text + '法官确认本次拍刀后游戏结束。'
        if isinstance(result, str) and re.search(r'游戏结束|对局结束', result):
            return text + result.rstrip('。；') + '。'
        return text + '拍刀结算待核。'
    if slot == 'warden_trade_targets' and action == 'select_pair':
        text = f'{actor or "典狱长"}选择{targets}进行交易。'
        return text + (str(result).rstrip('。；') + '。' if result else '')
    if slot == 'trade_decisions' and action in {'trade', 'betray', 'trade_betray', 'betray_trade'}:
        choices = {'trade': ('交易', '交易'), 'betray': ('背叛', '背叛'),
                   'trade_betray': ('交易', '背叛'), 'betray_trade': ('背叛', '交易')}[action]
        return '；'.join(f'{_person(n, seats)}选择{choice}'
                        for n, choice in zip(event.get('targets', []), choices)) + '。'
    if slot == 'trade_resolution':
        outcome = result or '本次交易的具体结算待核'
        return (f'结算对象：{targets}。' if targets else '') + str(outcome).rstrip('。；') + '。'
    if slot in {'whiteze_clear', 'whiteze_clear_mark'} and action in {'clear', 'clear_mark'}:
        outcome = '清除成功' if result == 'cleared' else result or '清除结果待核'
        return f'{actor}尝试清除{targets}身上的标记；{str(outcome).rstrip("。；")}。'
    if slot in {'nine_tail_hunt', 'nine_tail_skill'} and action in {'hunt', 'attempt'}:
        outcome = '技能发动成功' if result == 'successful' else result or '猎杀结算待核'
        return f'{actor}发动猎杀时刻，目标为{targets}；{str(outcome).rstrip("。；")}。'
    if slot == 'nine_tail_kill' and action == 'kill':
        return f'{actor}选择击杀{targets}。' + effect
    if slot == 'wolf_attack' and action == 'attack':
        subject = actor if seats.get(event.get('actor'), {}).get('role') == '机械狼' else '狼队'
        return f'{subject}选择击杀{targets}。' + effect
    if slot == 'wolf_girl_confession' and action == 'confess':
        outcome = f'；{str(result).rstrip("。；")}' if result else '；表白结算待核'
        return f'{actor}向{targets}表白{outcome}。'
    if slot == 'troublemaker_action':
        if action == 'trouble':
            outcome = f'；{str(result).rstrip("。；")}' if result else ''
            return f'{actor}对{targets}发动捣蛋{outcome}。'
        if action == 'pass':
            return f'{actor}本夜空过。'
        if action == 'unknown':
            return f'{actor or title}本夜的捣蛋情况待核。'
    if slot == 'masquerade_attack':
        if event.get('invalidated'):
            return (f'{actor}原选择击杀{targets}，但因被判离，本夜狼刀失效。' if targets
                    else f'{actor}因被判离，本夜狼刀失效。')
        if action == 'attack':
            return f'{actor}选择击杀{targets}。' + effect
    if slot == 'masquerade_knife_status':
        return f'普通狼人已全部出局，{actor}接过狼刀。'
    if action == 'save':
        if failed:
            return f'{actor}尝试使用解药救起{targets}，但未生效。' + effect
        return f'{actor}使用解药，救起{targets}。'
    if action == 'poison':
        if failed:
            return f'{actor}尝试对{targets}使用毒药，但未生效。' + effect
        text = f'{actor}使用毒药，目标为{targets}。'
        if effect:
            text += effect
        elif event.get('effects') and isinstance(result, str):
            text += result
        return text
    if action == 'check':
        return f'{actor}查验{targets}' + (f'，结果为{result}。' if result else '，查验结果待核。') + effect
    if action == 'guard':
        return f'{actor}守护{targets}。' + effect
    if action == 'learn':
        return f'{actor}学习{targets}' + (f'，学习结果为{result}。' if result else '。')
    if slot == 'night_deaths':
        if action in {'peaceful', 'no_death'}:
            return '本夜为平安夜。' if event.get('terminal') else '天亮，昨夜平安夜。'
        prefix = '本夜' if event.get('terminal') else '昨夜'
        return f'{prefix}出局：{targets}。' if targets else f'{prefix}出局情况待核。'
    if action == 'elected':
        return f'{targets or actor}{"自动" if "自动当选" in str(result) else ""}当选警长。'
    if action == 'deferred':
        return '警长竞选中断，延期至次日继续。'
    if action == 'exile':
        count = re.search(r'(\d+(?:\.\d+)?)票', str(event.get('result') or ''))
        return f'{targets}被放逐' + (f'（{count[1]}票）。' if count else '。')
    if action == 'self_destruct':
        return f'{actor or targets}自爆。'
    if action == 'shoot':
        if puppet_note:
            return f'{actor}尝试开枪指向{targets}，技能未生效。' + puppet_note
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
        if slot == 'guard':
            return f'{actor}本夜空守。'
        return '狼队本夜空刀。' if slot == 'wolf_attack' else f'{actor or title}本轮未发动。'
    if action == 'unknown':
        detail = str(result).rstrip('。；') + '。' if result and re.search(r'[\u4e00-\u9fff]', str(result)) else ''
        return f'{actor or title}的具体情况待核。' + detail
    if action == 'none' and slot == 'exile_result':
        return '两轮投票均平票，本日无人被放逐。'
    if slot == 'treasure_choice' and action == 'choose' and result:
        return f'{actor}本夜选择{result}身份。'
    if slot == 's21_treasure_action' and action == 'choose' and result:
        return str(result).rstrip('。；') + '。'
    verbs = {'dream': '梦游', 'dance': '邀请共舞', 'give_mask': '给予面具', 'verify': '验证',
             'view': '查看', 'exchange': '交换', 'choose': '选择', 'disqualify': '被判离',
             'die': '出局', 'reveal': '翻牌', 'flip': '翻牌', 'carrying': '接过狼刀',
             'mark': '标记', 'swap': '交换'}
    if action in verbs:
        if slot == 'masquerade_verify' and action == 'verify' and result:
            return f'{actor or title}验证{targets}；{str(result).rstrip("。；")}。' + effect
        return f'{actor or title}{verbs[action]}{targets}。' + effect
    if result:
        return f'{actor or title}：{str(result).rstrip("。；")}。'
    return event.get('description') or f'{actor or title}：{str(action).rstrip("。；")}。'


def _vote_signature(votes: list[dict]) -> list[tuple]:
    return sorted((vote['voter'], vote.get('target')) for vote in votes)


def _order_death_skills(events: list[dict]) -> list[dict]:
    """Attach a death skill to its actual departure, including shot chains."""
    after = {}
    attached = set()
    for skill in events:
        if skill['slot'] not in {'hunter_shot', 'wolf_king_shot'} or skill.get('actor') is None:
            continue
        anchor = next((e for e in events if e is not skill
                       and skill['actor'] in _actual_deaths([e])), None)
        if anchor is not None:
            after.setdefault(id(anchor), []).append(skill)
            attached.add(id(skill))
    ordered = []

    def append(event):
        ordered.append(event)
        for skill in after.get(id(event), []):
            append(skill)

    for event in events:
        if id(event) not in attached:
            append(event)
    return ordered


def _order_badges(events: list[dict]) -> list[dict]:
    """Place each badge change after its departure and death-skill chain."""
    for badge in [e for e in events if e['slot'] == 'badge']:
        actor = badge.get('actor')
        anchor = next((e for e in events if e is not badge and actor is not None
                       and actor in _actual_deaths([e])), None)
        if anchor is None and badge.get('action') == 'badge_lost':
            anchor = next((e for e in events if e.get('action') == 'self_destruct'), None)
        if anchor is None:
            continue
        events.remove(badge)
        at = events.index(anchor) + 1
        while at < len(events) and events[at]['slot'] in {'hunter_shot', 'wolf_king_shot', 'badge'}:
            at += 1
        events.insert(at, badge)
    return events


def _merge_endgame(game: dict) -> None:
    """Fold recorded rushes into their day without adopting review candidates."""
    for row in game.get('rounds', []):
        for event in row.get('day', []):
            if event['slot'] == 'wolf_shot' and event.get('action') == 'shoot':
                event.update(slot='wolf_rush', action='rush')
    endgame = game.get('endgame', {})
    # Older public snapshots discarded review status. Keep their separate card
    # until republished, rather than promote a possibly unreviewed candidate.
    if (endgame.get('review_status') == 'ai_candidate_awaiting_user'
            or 'release_id' in game and 'review_status' not in endgame):
        return
    unmatched = [e for row in game.get('rounds', []) for e in row.get('day', [])
                 if e['slot'] == 'wolf_rush']
    for phase in endgame.get('phases', []):
        if phase.get('kind') != 'wolf_rush':
            continue
        row = next((r for r in game.get('rounds', []) if r['number'] == phase.get('day')), None)
        if row is None:
            continue
        targets = phase.get('declared_targets', [])
        existing = next((e for e in row['day'] if e['slot'] == 'wolf_rush'
                         and any(e is candidate for candidate in unmatched)
                         and set(e.get('targets', [])) == set(targets)
                         and (e.get('actor') is None or phase.get('actor') is None
                              or e['actor'] == phase['actor'])), None)
        if existing is not None:
            unmatched = [e for e in unmatched if e is not existing]
            if existing.get('actor') is None:
                existing['actor'] = phase.get('actor')
            if existing.get('result') in {None, 'unknown'}:
                existing['result'] = phase.get('result')
            continue
        row['day'].append({'slot': 'wolf_rush', 'action': 'rush', 'actor': phase.get('actor'),
                           'targets': deepcopy(targets), 'result': phase.get('result')})


def _masquerade_knife(events: list[dict], roles: dict, template: dict, departed: set[int]) -> list[dict]:
    masks, wolves = roles.get('假面', []), set(roles.get('狼人', []))
    if (template.get('code') != 'masquerade' or len(masks) != 1 or masks[0] in departed
            or len(wolves) != template.get('role_counts', {}).get('狼人') or not wolves <= departed):
        return events
    actor = masks[0]
    attack = next((e for e in events if e['slot'] == 'wolf_attack'), None)
    if attack is None or attack.get('action') == 'surrender':
        return events
    attack.update(slot='masquerade_attack', actor=actor, slot_label='假面击杀')
    events = [e for e in events if e is not attack]
    verification = next((e for e in events if e['slot'] == 'masquerade_verify'
                         and re.search(r'假面.{0,4}判离', str(e.get('result') or ''))), None)
    if verification is not None:
        attack.update(action='unavailable', invalidated=True)
        events.insert(events.index(verification) + 1, attack)
    else:
        events.insert(0, attack)
    events.insert(0, {'slot': 'masquerade_knife_status', 'slot_label': '假面接刀',
                      'action': 'carrying', 'actor': actor, 'inferred': True})
    return events


def _recorded_ending(game: dict) -> dict | None:
    board = game.get('board')
    board_family = family(board.get('code') if isinstance(board, dict) else board)
    explicit = game.get('terminal_observation') or terminal_from_events(game)
    if explicit:
        return explicit
    endings = set()
    for row in game.get('rounds', []):
        for phase in ('night', 'day'):
            for event in row.get(phase, []):
                action, slot = event.get('action'), event.get('slot')
                if (board_family in {'wolf_girl', 'troublemaker'}
                        and slot == 'game_end' and action in {'end', 'surrender'}):
                    endings.add((row['number'], phase))
                result = event.get('result')
                if not isinstance(result, str) or not re.search(r'游戏结束|对局结束|结算终局', result):
                    continue
                if slot == 'night_deaths' and action in {'die', 'no_death', 'peaceful'}:
                    endings.add((row['number'], 'night'))
                elif phase == 'night' and (action not in {None, 'unknown', 'unavailable', 'not_applicable'} or '交牌' in result):
                    endings.add((row['number'], phase))
                elif phase == 'day' and (action in {'self_destruct', 'exile', 'surrender', 'rush'} or '交牌' in result):
                    endings.add((row['number'], phase))
    endgame = game.get('endgame', {})
    if (endgame.get('review_status') != 'ai_candidate_awaiting_user'
            and ('release_id' not in game or 'review_status' in endgame)):
        for phase in endgame.get('phases', []):
            if (phase.get('kind') != 'wolf_rush'
                    or phase.get('result') not in {'werewolf_win', 'good_win', 'draw'}):
                continue
            day = phase.get('day')
            # A recorded endgame may establish the winner without locating the
            # exact day. Preserve that unknown instead of inventing a boundary.
            if day is None:
                continue
            if type(day) is not int or day < 1:
                raise ValueError('记录的拍刀游戏日不合法')
            endings.add((day, 'day'))
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
    puppet = puppet_target(source)
    for seat in source.get('seats', []):
        if seat['seat'] == puppet:
            seat['faction'] = 'werewolf'
    context = source.get('_publication_context', {})
    for item in context.get('supplemental_events', []):
        row = next((r for r in source.get('rounds', []) if r['number'] == item['round']), None)
        if row is not None and item['event'] not in row[item['phase']]:
            row[item['phase']].append(deepcopy(item['event']))
    if context.get('terminal_observation'):
        source['terminal_observation'] = deepcopy(context['terminal_observation'])
    _merge_endgame(source)
    terminal = _recorded_ending(source)
    if terminal:
        source['terminal_observation'] = terminal
    seats = {row['seat']: row for row in source.get('seats', [])}
    # Trim the copied source before projection. A later occurrence of the same
    # slot must not survive merely because that slot occurred before surrender.
    for row in source.get('rounds', []):
        for phase in ('night', 'day'):
            ending = _surrender(row.get(phase, []), seats, source.get('winner'), terminal=bool(
                terminal and terminal['round'] == row['number'] and terminal['phase'] == phase))
            if ending and ending[0] < len(row[phase]):
                row[phase] = row[phase][:ending[0] + 1]
    presentation = build_game_presentation(source)
    template = load_canonical_template(source['board']['code'])
    definitions = {slot['code']: slot for phase in ('night', 'day') for slot in template[phase + '_slots']}
    roles = {}
    for row in seats.values():
        roles.setdefault(row.get('role'), []).append(row['seat'])
    original_rounds = {row['number']: row for row in source.get('rounds', [])}
    terminal = source.get('terminal_observation') or presentation.get('terminal')
    phases = []
    emitted_ballots = set()
    aligned = set()
    departed = set()
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
            for event in events:
                if event.get('actor') is None:
                    candidates = roles.get(definitions.get(event['slot'], {}).get('actor_role'), [])
                    if len(candidates) == 1:
                        event['actor'] = candidates[0]
            if surrender:
                stop_index, _ = surrender
                allowed = {e['slot'] for e in original[:stop_index]}
                if stop_index < len(original) and original[stop_index].get('action') not in _INACTIVE | {'unknown'}:
                    allowed.add(original[stop_index]['slot'])
                events = [e for e in events if e['slot'] in allowed]
                if is_terminal and phase == 'night':
                    events += [e for e in ending_events if e.get('action') not in _INACTIVE | {'unknown'}]
            if is_terminal and phase == 'night':
                end_markers = [e for e in events if e.get('slot') == 'game_end' and e.get('action') == 'end']
                if end_markers:
                    events = [e for e in events if e not in end_markers] + end_markers
            if phase == 'night':
                carrying = [e for e in events if e['slot'] == 'mechanical_knife_status' and e.get('action') == 'carrying']
                if carrying:
                    for event in events:
                        if event['slot'] == 'wolf_attack':
                            event['actor'] = carrying[0]['actor']
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
                    has_candidates = any(e['slot'] == 'sheriff_candidates' and e.get('action') == 'register'
                                         for e in events)
                    for event in events:
                        if event['slot'] == 'sheriff_candidates' and event.get('action') == 'register':
                            event['candidate_stage'] = 'remaining'
                    events.insert(0, {'slot': 'sheriff_candidates', 'action': 'register',
                                      'candidate_stage': 'initial' if has_candidates else None,
                                      'targets': registration['on_police'],
                                      'off_police': registration.get('off_police'), 'votes': []})
                # Some retained games have voting supplements without a typed
                # vote slot. Keep those real ballots at their result anchor.
                for kind, vote_slot, result_slot in [('sheriff', 'sheriff_vote', 'sheriff_result'),
                                                      ('exile', 'exile_vote', 'exile_result')]:
                    ballots = [b for b in source['voting'].get('ballots', []) if b['day'] == number and b['kind'] == kind]
                    result_event = next((e for e in events if e['slot'] == result_slot), None)
                    if ballots and not any(e['slot'] == vote_slot for e in events) and (not surrender or result_event):
                        votes = [{'round': b['number'], 'voter': v['voter'], 'target': v['target']}
                                 for b in ballots for v in b['votes']]
                        at = next((i for i, e in enumerate(events) if e['slot'] == result_slot), len(events))
                        events.insert(at, {'slot': vote_slot, 'action': 'vote', 'votes': votes})
                    vote_events = [e for e in events if e['slot'] == vote_slot and e.get('action') == 'vote']
                    if (result_event and vote_events
                            and events.index(result_event) < events.index(vote_events[-1])):
                        events.remove(result_event)
                        events.insert(events.index(vote_events[-1]) + 1, result_event)
                deferred = [e for e in events if e['slot'] == 'sheriff_result' and e.get('action') == 'deferred']
                if deferred and any(e.get('action') == 'self_destruct' for e in events):
                    events = [e for e in events if e not in deferred]
                    at = next(i + 1 for i, e in enumerate(events) if e.get('action') == 'self_destruct')
                    events[at:at] = deferred
                for election in [e for e in events if e['slot'] == 'sheriff_result'
                                 and e.get('action') == 'elected'
                                 and re.search(r'自爆后.*自动当选', str(e.get('result') or ''))]:
                    boom = next((e for e in events if e.get('action') == 'self_destruct'), None)
                    if boom is not None:
                        events.remove(election)
                        events.insert(events.index(boom) + 1, election)
                # All-player signup loses the badge before the night-death
                # announcement; no election or self-destruct causes this loss.
                if registration and registration.get('off_police') == []:
                    for badge in [e for e in events if e['slot'] == 'badge' and e.get('action') == 'badge_lost']:
                        events.remove(badge)
                        at = max(i for i, e in enumerate(events) if e['slot'] == 'sheriff_candidates') + 1
                        events.insert(at, badge)
                # The fixed morning slot can precede the actual announcement.
                # Move it only when this game's source explicitly records that timing.
                for death in [e for e in events if e['slot'] == 'night_deaths'
                              and re.search(r'自爆后公布', str(e.get('result') or ''))]:
                    boom = next((e for e in events if e.get('action') == 'self_destruct'), None)
                    if boom is not None:
                        events.remove(death)
                        at = events.index(boom) + 1
                        while at < len(events) and events[at]['slot'] in {'badge', 'sheriff_result'}:
                            at += 1
                        events.insert(at, death)
                # Guile redirection resolves the final exile, including a
                # prince revote. It cannot precede the reveal and revote.
                final_exile = next((e for e in reversed(events) if e['slot'] in {'exile_result', 'second_exile_result'}
                                    and e.get('action') == 'exile'), None)
                if final_exile:
                    for effect in [e for e in events if e['slot'] == 'guile_exchange_result' and e.get('action') == 'apply']:
                        events.remove(effect)
                        events.insert(events.index(final_exile) + 1, effect)
            if phase == 'night':
                events = _masquerade_knife(events, roles, template, departed)
            else:
                events = _order_badges(_order_death_skills(events))

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
                if slot == 'puppet_skill_effect':
                    continue
                if action == 'surrender':
                    continue  # Emitted once as the phase-ending surrender item.
                actor = event.get('actor')
                if puppet is not None and actor == puppet and slot in {'seer_check', 'witch_save', 'witch_poison', 'guard', 'hunter_shot'} and action in {'check', 'save', 'poison', 'guard', 'shoot'}:
                    role = seats[puppet].get('role')
                    recorded_effect = any(e['slot'] == 'puppet_skill_effect'
                                          and e.get('action') == 'skill_disabled'
                                          and re.search('失效|未生效|failed', str(e.get('result') or ''), re.I)
                                          for e in original)
                    if number > 1 or recorded_effect or re.search('反转|相反|失效|未生效|failed', str(event.get('result') or ''), re.I):
                        note = ('傀儡预言家的查验反馈与正常结果相反。' if role == '预言家' else
                                f'{_person(puppet, seats)}为傀儡，本次技能失效。')
                        event['puppet_note'] = note
                title = _COMMON_TITLES.get(slot) or event.get('slot_label') or definitions.get(slot, {}).get('label', slot)
                title = {'wolf_attack': '机械狼击杀' if seats.get(actor, {}).get('role') == '机械狼' else '狼队击杀',
                         'seer_check': '通灵师查验' if seats.get(actor, {}).get('role') == '通灵师' else '预言家查验',
                         'mixed_blood_model': '混血儿选择榜样',
                         'dancer_dance': '舞者共舞'}.get(slot, title)
                if slot == 'sheriff_candidates' and action == 'continued':
                    title = '继续警长竞选'
                elif slot == 'sheriff_candidates' and event.get('candidate_stage') == 'remaining':
                    title = '退水后候选'
                elif slot == 'sheriff_candidates' and event.get('candidate_stage') == 'initial':
                    title = '首次上警'
                if slot in {'speech_order', 'hunter_state', 'wolf_king_state', 'puppet_hunter_eligibility'}:
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
                double_tie = slot == 'exile_result' and action == 'none' and (
                    event.get('result') == 'double_tie' or '平票' in str(event.get('result')))
                hunter_departure = slot in {'hunter_shot', 'wolf_king_shot'} and actor in departures
                if action in _INACTIVE and not double_tie and not hunter_departure and not event.get('invalidated'):
                    continue
                if action == 'unknown' and slot not in _UNKNOWN_IMPORTANT and not hunter_departure:
                    continue
                item = {'kind': 'event', 'slot': slot, 'title': title,
                        'text': _text(event, seats, title), 'events': [event]}
                if slot == 'witch_poison' and seats.get(actor, {}).get('role') == '毒师':
                    item['title'] = '毒师毒药'
                elif slot in {'witch_save', 'witch_poison'}:
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
        departed.update(_actual_deaths(original_rounds[number].get('night', []) +
                                      original_rounds[number].get('day', []) + row['night'] + row['day']))
    return {'phases': phases}
