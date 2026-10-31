from scripts.game_time import display_time_text
from website.api.publisher import _display_inference_notes, _public_endgame, _rounds


def test_round_description_uses_day_relative_chinese_label():
    board = {"night_slots": [{"code": "guard", "label": "守护"}], "day_slots": []}
    dossier = {"rounds": [{"number": 2, "night": [{"slot": "guard", "action": "pass"}], "day": []}]}
    assert _rounds(dossier, board)[0]["night"][0]["description"].startswith("第一天夜晚，")


def test_generated_inference_and_endgame_notes_are_normalized_in_public_projection():
    presentation = {"rounds": [{"night": [{"inference_note": "同一女巫第4夜才使用这瓶毒药。"}], "day": []}]}
    assert _display_inference_notes(presentation)["rounds"][0]["night"][0]["inference_note"] == \
        "同一女巫第三天夜晚才使用这瓶毒药。"
    endgame = {"phases": [{"kind": "wolf_rush", "note": "第三天自爆后进入第四夜。"}]}
    assert _public_endgame(endgame)["phases"][0]["note"] == "第三天自爆后进入第三天夜晚。"


def test_generated_note_normalizer_leaves_nontext_values_unchanged():
    assert display_time_text(None) is None


def test_internal_import_placeholder_is_not_published_as_an_endgame_note():
    internal = 'S21 primary-reviewed endgame attack; unspecified settlement remains unknown.'
    source = {'phases': [{'kind': 'wolf_rush', 'declared_targets': [3],
                         'result': 'unknown', 'note': internal}]}
    public = _public_endgame(source)['phases'][0]
    assert not public.get('note')
    assert public['declared_targets'] == [3] and public['result'] == 'unknown'
    assert source['phases'][0]['note'] == internal
