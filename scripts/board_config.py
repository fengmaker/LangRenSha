"""Load canonical board templates and their storage-code variants."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = Path("config/board_templates")


def _template_files(root: Path) -> list[Path]:
    return sorted((root / TEMPLATE_DIR).glob("*.json"))


def _locate(code: str, root: Path) -> tuple[Path, dict[str, Any], dict[str, Any] | None]:
    directory = root / TEMPLATE_DIR
    direct = directory / f"{code}.json"
    if direct.is_file():
        value = json.loads(direct.read_text(encoding="utf-8-sig"))
        if value.get("code") == code:
            return direct, value, None

    found: tuple[Path, dict[str, Any], dict[str, Any]] | None = None
    for path in _template_files(root):
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        variants = value.get("storage_variants", {})
        variant = variants.get(code) if isinstance(variants, dict) else None
        if variant is None:
            continue
        if found is not None:
            raise ValueError(f"Duplicate board template storage code: {code}")
        found = (path, value, variant)
    if found is None:
        raise FileNotFoundError(f"Board template not found: {code}")
    return found


def template_path(code: str, root: Path = ROOT) -> Path:
    """Return the canonical JSON path used by a canonical or storage code."""
    path, _template, _variant = _locate(code, Path(root))
    return path


def load_canonical_template(code: str, root: Path = ROOT) -> dict[str, Any]:
    """Return the shared board layout, independent of its storage variant."""
    _path, canonical, _variant = _locate(code, Path(root))
    return {key: deepcopy(value) for key, value in canonical.items() if key != "storage_variants"}


def load_template(code: str, root: Path = ROOT) -> dict[str, Any]:
    """Return the runtime template for a canonical or stored board code."""
    _path, canonical, variant = _locate(code, Path(root))
    result = {key: deepcopy(value) for key, value in canonical.items() if key != "storage_variants"}
    if variant is None:
        return result

    slot_codes = variant.get("slot_codes", {})
    slot_overrides = variant.get("slot_overrides", {})
    for key in variant.get("remove_fields", []):
        result.pop(key, None)
    for key, value in variant.items():
        if key not in {"slot_codes", "slot_overrides", "remove_fields"}:
            result[key] = deepcopy(value)

    for phase in ("night", "day"):
        slot_key = f"{phase}_slots"
        overrides = slot_overrides.get(phase, {}) if isinstance(slot_overrides, dict) else {}
        codes = slot_codes.get(phase) if isinstance(slot_codes, dict) else None
        if codes is None and not overrides:
            continue

        definitions = {slot["code"]: deepcopy(slot) for slot in result[slot_key]}
        for slot_code, patch in overrides.items():
            if slot_code in definitions:
                definitions[slot_code].update(deepcopy(patch))
            else:
                definitions[slot_code] = deepcopy(patch)
        ordered_codes = codes if codes is not None else [slot["code"] for slot in result[slot_key]]
        try:
            result[slot_key] = [definitions[slot_code] for slot_code in ordered_codes]
        except KeyError as error:
            raise ValueError(f"Unknown {phase} slot {error.args[0]!r} in board variant {code}") from error
    return result
