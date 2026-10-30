"""Compatibility facade for shared game inference.

The presentation rules live in :mod:`scripts.game_inference` so upstream
publishers can use the same projection before persistence.
"""

from scripts import game_inference as _game_inference

# Preserve every name formerly defined or imported by this module, including
# private helpers used by tests and downstream compatibility callers.
for _name, _value in vars(_game_inference).items():
    if not (_name.startswith("__") and _name.endswith("__")):
        globals()[_name] = _value

del _game_inference, _name, _value
