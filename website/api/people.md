# Public player identity registry

`website/assets/people.json` is the versioned source of public player IDs. It was exported read-only from active release `S21_S22_S23-dff4f1efc050a5d0-af68d320-p13-s2` on 2026-11-04. The three season lists had 59, 62, and 63 entries; their union contains 90 names and 90 distinct UUIDs, with no cross-season name/ID conflicts.

The file has `schema_version`, `source_release_id`, and a `people` object from exact display name to canonical lowercase UUID. Keep existing entries unchanged; add a new name only when it first appears in public game input. Do not regenerate IDs from the current database. The loader rejects malformed UUIDs, duplicate IDs, and names that collide after trim and case-fold normalization.

`website.api.people.load_people()` loads the checked-in file. Pass an explicit `Path` when a build stages the file elsewhere. `PeopleRegistry.id_for(name)` returns the stored ID for an existing name, or a deterministic UUIDv5 using the historical website namespace and `name.strip().casefold()` for a new name. Thus local runs, CI, and empty-database rebuilds resolve the same names to the same IDs. `ids_for(names)` returns the mapping for a batch; `ids_digest(names)` hashes only those resolved name/ID rows in sorted canonical JSON. The publisher's shared `prepare_release` reads this mapping for preflight and publish, includes the resolved name/ID rows in the release source hash, and records them in the manifest. Only mappings used by the batch affect its release ID.

When changing the format or normalization behavior, bump `schema_version` and update the dedicated registry tests.
