"""Shared identity names for review pages, public games and player records."""

TREASURE_NAMES = {
    '毒师': '盗宝毒师', '蒙面人': '盗宝蒙面', '摄梦人': '盗宝摄梦',
    '通灵师': '盗宝通灵', '猎人': '盗宝猎人',
}


def treasure_god_card(game: dict, seat: int) -> str | None:
    """Use an observed choice or an explicitly named treasure identity."""
    choices = set()
    for round_ in game.get('rounds', []):
        for event in round_.get('night', []):
            if event.get('actor') != seat:
                continue
            text = str(event.get('result') or '')
            if (event.get('slot') in {'treasure_choice', 's21_treasure_action'}
                    and event.get('action') == 'choose'):
                choices.update(role for role in TREASURE_NAMES if role in text)
            elif event.get('slot') == 'treasure_alignment' and event.get('action') == 'wolf':
                choices.update(role for role, label in TREASURE_NAMES.items() if label in text)
    return choices.pop() if len(choices) == 1 else None


def role_label(game: dict, seat: dict) -> str | None:
    role = seat.get('role')
    if role != '盗宝大师':
        return role
    return TREASURE_NAMES.get(treasure_god_card(game, seat['seat']), role)
