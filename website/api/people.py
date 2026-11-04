"""Stable public player identity mapping for website releases."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping
import uuid


PEOPLE_FILE = Path(__file__).resolve().parents[1] / "assets" / "people.json"
PERSON_NAMESPACE = uuid.UUID("5a1e9a41-663d-4dcc-9ce6-f5e75e9efb18")


class PeopleRegistryError(ValueError):
    """The versioned people mapping is missing or invalid."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PeopleRegistryError(f"选手映射 JSON 字段重复：{key}")
        result[key] = value
    return result


def _name_key(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise PeopleRegistryError("选手姓名必须是非空字符串")
    return name.strip().casefold()


@dataclass(frozen=True)
class PeopleRegistry:
    """Validated IDs from the checked-in mapping plus deterministic new IDs."""

    source_release_id: str
    _ids_by_name: Mapping[str, str]

    def id_for(self, name: str) -> str:
        key = _name_key(name)
        mapped = self._ids_by_name.get(key)
        if mapped is not None:
            return mapped
        return str(uuid.uuid5(PERSON_NAMESPACE, key))

    def ids_for(self, names: Iterable[str]) -> dict[str, str]:
        return {name: self.id_for(name) for name in names}

    def ids_digest(self, names: Iterable[str]) -> str:
        """Hash only the resolved names used by one publication batch."""
        resolved = self.ids_for(names)
        canonical = json.dumps(
            resolved, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @property
    def people_count(self) -> int:
        return len(self._ids_by_name)


def load_people(path: Path | None = None) -> PeopleRegistry:
    """Load and validate the single checked-in public identity mapping."""
    source = Path(path) if path is not None else PEOPLE_FILE
    try:
        raw = source.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_json_object)
    except OSError as exc:
        raise PeopleRegistryError(f"无法读取选手映射文件：{source}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PeopleRegistryError(f"选手映射不是有效 UTF-8 JSON：{source}") from exc

    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int:
        raise PeopleRegistryError("选手映射必须包含整数 schema_version")
    if payload["schema_version"] != 1:
        raise PeopleRegistryError("不支持的选手映射 schema_version")
    source_release_id = payload.get("source_release_id")
    if not isinstance(source_release_id, str) or not source_release_id.strip():
        raise PeopleRegistryError("选手映射缺少 source_release_id")
    people = payload.get("people")
    if not isinstance(people, dict) or not people:
        raise PeopleRegistryError("选手映射 people 必须是非空对象")

    ids_by_name: dict[str, str] = {}
    seen_ids: set[str] = set()
    for name, person_id in people.items():
        key = _name_key(name)
        if key in ids_by_name:
            raise PeopleRegistryError(f"选手姓名规范化后重复：{name}")
        if not isinstance(person_id, str):
            raise PeopleRegistryError(f"选手 ID 必须是 UUID 字符串：{name}")
        try:
            parsed_id = uuid.UUID(person_id)
        except (ValueError, AttributeError) as exc:
            raise PeopleRegistryError(f"选手 ID 不是有效 UUID：{name}") from exc
        if str(parsed_id) != person_id:
            raise PeopleRegistryError(f"选手 ID 必须使用小写标准 UUID 格式：{name}")
        if person_id in seen_ids:
            raise PeopleRegistryError(f"选手 ID 重复：{person_id}")
        ids_by_name[key] = person_id
        seen_ids.add(person_id)

    return PeopleRegistry(
        source_release_id=source_release_id,
        _ids_by_name=MappingProxyType(ids_by_name),
    )
