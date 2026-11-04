import hashlib
import json
from pathlib import Path
import uuid

import pytest

from website.api.people import (
    PEOPLE_FILE,
    PERSON_NAMESPACE,
    PeopleRegistryError,
    load_people,
)


ACTIVE_PEOPLE_MAP_SHA256 = "efb644bcaab1e4b9fc613f3b6a2a6869cb7dfae87b968d06303f82e7bc8dfaee"


def _write_registry(tmp_path: Path, people: dict[str, str]) -> Path:
    path = tmp_path / "people.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "source_release_id": "test-release",
        "people": people,
    }), encoding="utf-8")
    return path


def test_bundled_mapping_matches_active_release_baseline():
    registry = load_people()
    payload = json.loads(PEOPLE_FILE.read_text(encoding="utf-8"))
    canonical_people = json.dumps(
        payload["people"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    assert PEOPLE_FILE.is_file()
    assert registry.source_release_id == "S21_S22_S23-dff4f1efc050a5d0-af68d320-p13-s2"
    assert registry.people_count == 90
    assert hashlib.sha256(canonical_people).hexdigest() == ACTIVE_PEOPLE_MAP_SHA256
    assert registry.id_for("牛肉干") == "e404d4f6-2613-4ca7-94e0-2b719287988f"


def test_bundled_mapping_ids_are_valid_and_unique():
    payload = json.loads(PEOPLE_FILE.read_text(encoding="utf-8"))
    ids = list(payload["people"].values())

    assert len(ids) == len(set(ids))
    assert all(str(uuid.UUID(person_id)) == person_id for person_id in ids)


def test_existing_id_wins_and_new_names_get_stable_uuid5(tmp_path: Path):
    known_id = "e404d4f6-2613-4ca7-94e0-2b719287988f"
    registry_path = _write_registry(tmp_path, {"牛肉干": known_id})
    registry = load_people(registry_path)

    assert registry.id_for("  牛肉干  ") == known_id
    expected = str(uuid.uuid5(PERSON_NAMESPACE, "new player"))
    assert registry.id_for("New Player") == expected
    assert load_people(registry_path).id_for("new player") == expected


def test_batch_digest_is_stable_and_changes_when_used_id_changes(tmp_path: Path):
    first = load_people(_write_registry(
        tmp_path, {"牛肉干": "e404d4f6-2613-4ca7-94e0-2b719287988f"}
    ))
    first_digest = first.ids_digest(["牛肉干", "New Player"])

    same_input = load_people(_write_registry(
        tmp_path, {"牛肉干": "e404d4f6-2613-4ca7-94e0-2b719287988f"}
    ))
    changed_mapping = load_people(_write_registry(
        tmp_path, {"牛肉干": "de234d4b-6452-4e74-a567-70231209f934"}
    ))

    assert first.ids_digest(["New Player", "牛肉干"]) == first_digest
    assert same_input.ids_digest(["牛肉干", "New Player"]) == first_digest
    assert changed_mapping.ids_digest(["牛肉干", "New Player"]) != first_digest


def test_duplicate_ids_are_rejected(tmp_path: Path):
    duplicate = "e404d4f6-2613-4ca7-94e0-2b719287988f"
    path = _write_registry(tmp_path, {"甲": duplicate, "乙": duplicate})

    with pytest.raises(PeopleRegistryError, match="ID 重复"):
        load_people(path)


def test_duplicate_json_fields_are_rejected(tmp_path: Path):
    path = tmp_path / "people.json"
    path.write_text(
        '{"schema_version":1,"source_release_id":"test","people":'
        '{"甲":"e404d4f6-2613-4ca7-94e0-2b719287988f",'
        '"甲":"de234d4b-6452-4e74-a567-70231209f934"}}',
        encoding="utf-8",
    )

    with pytest.raises(PeopleRegistryError, match="字段重复"):
        load_people(path)


@pytest.mark.parametrize("person_id", ["not-a-uuid", "E404D4F6-2613-4CA7-94E0-2B719287988F"])
def test_invalid_or_noncanonical_ids_are_rejected(tmp_path: Path, person_id: str):
    path = _write_registry(tmp_path, {"甲": person_id})

    with pytest.raises(PeopleRegistryError, match="UUID"):
        load_people(path)


def test_names_that_differ_only_by_casefold_are_rejected(tmp_path: Path):
    path = _write_registry(tmp_path, {
        "Player": "e404d4f6-2613-4ca7-94e0-2b719287988f",
        " player ": "de234d4b-6452-4e74-a567-70231209f934",
    })

    with pytest.raises(PeopleRegistryError, match="姓名规范化后重复"):
        load_people(path)


def test_unknown_schema_version_is_rejected(tmp_path: Path):
    path = _write_registry(tmp_path, {"甲": "e404d4f6-2613-4ca7-94e0-2b719287988f"})
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PeopleRegistryError, match="不支持"):
        load_people(path)
