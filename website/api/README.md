# Masters website API

Run the API from the repository root with `uvicorn website.api.app:app --host 127.0.0.1 --port 8000`.
The deployed API needs this package and `DATABASE_URL`; it reads only the `masters_web` schema.
For local development without `DATABASE_URL`, it reuses the repository's existing `scripts.database`
connection configuration. API requests run in PostgreSQL read-only transactions.

Publish the selected season with `python -m website.api.publish --season S22`. The publisher creates
an immutable release in the separate `masters_web` schema and switches its active pointer in the same
transaction. It does not run the JCMS migrations. The optional `--root` argument or
`MASTERS_SOURCE_ROOT` environment variable points at a read-only source root containing `data/games`,
`data/extractions`, and the required `config` files.

`--check` validates and counts the selected source without writing. `--sample BV1yt7v6QE3Q` selects
only that in-scope video. `--list` prints the current in-scope **source game list**; it does not list
published releases. Use `GET /api/v1/releases` for release history. `--activate RELEASE` switches to
an existing immutable release. The publication format and statistics versions are part of each
release ID and manifest, so a changed public mapping can create a new batch without rewriting old data.

The snapshot allowlist excludes local paths, transcript text, credentials, and review evidence.
It retains source hashes, selected voting rule applications, and per-vote abstention basis.

Publish the separate bluff review records with `python -m website.api.publish_bluffs --season S22`;
add `--check` for a read-only preflight. The publication binds the full reviewed season to the active
game release, checks every source fingerprint and actor identity, stores immutable review versions
and per-wolf decisions, then atomically changes the review pointer. Repeating the same input is
idempotent. The leaderboard, player detail and review endpoints read these database records;
`website/assets/bluffs/S22.json` is publication input rather than a runtime data source.

Player analytics are computed from the active immutable snapshots. `GET /api/v1/players`
and `/api/v1/players/{id}` accept `season=S22` and return full-season metrics including finals week; legacy player `phase` queries are ignored.
`GET /api/v1/leaderboard` accepts `season` and `phase=all|finals_week` and keeps
a full-season points ranking and a finals-week-only championship ranking. Non-point metrics on both boards remain full-season. Legacy leaderboard `phase=regular` is an alias for `all`. Responses carry a separate `analytics_version`.
Win points are +1.5 for wolves and +1 for good players; every loss is -1. A mixed-blood
player with a missing faction inherits the faction of the recorded exemplar. Ratios
include numerator, denominator, excluded count, and supporting game IDs; no samples
produce a null rate rather than zero.

`player_photos.json` maps reviewed names to season-specific image hashes. Deploy
`website/assets/player-photos` with the API. `GET /api/v1/photos/{season}/{filename}`
serves only manifest-listed images; the Next.js `/media/player-photos` route proxies
them on the website origin. The public manifest contains no source filesystem paths.
