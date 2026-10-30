"""Display labels for the game's stored round and phase values."""

import re


def chinese(number):
    if type(number) is not int or number < 1 or number > 99:
        return str(number)
    digits = {
        1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
        6: "六", 7: "七", 8: "八", 9: "九",
    }
    if number <= 10:
        return digits.get(number, "十")
    tens, ones = divmod(number, 10)
    return ("" if tens == 1 else digits[tens]) + "十" + (digits[ones] if ones else "")


def phase_label(round_number, phase):
    if phase == "night":
        return "首夜" if round_number == 1 else "第" + chinese(round_number - 1) + "天夜晚"
    return "第" + chinese(round_number) + "天白天"


_TIME_LABEL = re.compile(r"第(?P<number>[0-9]+|[一二三四五六七八九十]+)(?P<phase>天白天|天夜晚|夜)")
_CHINESE_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                   "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _number_value(value):
    if value.isascii() and value.isdigit():
        return int(value)
    if "十" not in value:
        return int("".join(str(_CHINESE_DIGITS[digit]) for digit in value))
    tens, _, ones = value.partition("十")
    return (_CHINESE_DIGITS[tens] if tens else 1) * 10 + (_CHINESE_DIGITS[ones] if ones else 0)


def display_time_text(text):
    """Normalize legacy phase labels in generated display text, without changing evidence quotes."""
    if not isinstance(text, str):
        return text

    def replace(match):
        number = _number_value(match.group("number"))
        if number < 1:
            return match.group(0)
        phase = match.group("phase")
        if phase == "天白天":
            return phase_label(number, "day")
        if phase == "天夜晚":
            return phase_label(number + 1, "night")
        return phase_label(number, "night")

    return _TIME_LABEL.sub(replace, text).replace("开局首夜", "首夜").replace("开局夜晚", "首夜")
