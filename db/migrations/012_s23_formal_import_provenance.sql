-- Replayable S23 formal imports: preserve batch authorization separately from
-- individual review decisions, and keep non-slot observations source-bound.
ALTER TABLE artifacts DROP CONSTRAINT IF EXISTS artifacts_kind_check;
ALTER TABLE artifacts ADD CONSTRAINT artifacts_kind_check
    CHECK (kind IN ('metadata','manifest','audio','subtitle','asr','frame','candidate','weibo_json','image','transcript'));

-- Some S23 actions record why an otherwise present role/action was unavailable.
-- The values remain typed and are scoped to the isolated S23 board namespace.
ALTER TABLE game_event_records DROP CONSTRAINT IF EXISTS game_event_records_availability_check;
ALTER TABLE game_event_records ADD CONSTRAINT game_event_records_availability_check
    CHECK(availability IN ('learning','locked','available','wrong_phase','no_skill','dead','poisoned','wolves_alive','unknown','spent','no_living_wolves','unavailable'));
ALTER TABLE game_event_records DROP CONSTRAINT IF EXISTS mechanical_availability_only;
ALTER TABLE game_event_records ADD CONSTRAINT availability_slot_scope
    CHECK(availability IS NULL OR slot_code IN ('mechanical_action','mechanical_day_skill') OR left(board_code,4)='s23_');

-- The S23 sidecar has one explicitly documented day with no exile vote phase.
ALTER TABLE game_voting_days DROP CONSTRAINT IF EXISTS game_voting_days_exile_status_check;
ALTER TABLE game_voting_days ADD CONSTRAINT game_voting_days_exile_status_check
    CHECK(exile_status IN ('recorded','unknown','interrupted_self_destruct','none'));

CREATE TABLE game_formal_import_batches (
    batch_key text PRIMARY KEY,
    season_id uuid NOT NULL REFERENCES seasons(id),
    scope_code text NOT NULL CHECK(scope_code='S23_regular_75'),
    snapshot_id text NOT NULL CHECK(snapshot_id ~ '^[0-9a-f]{64}$'),
    source_report_path text NOT NULL,
    source_report_sha256 text NOT NULL CHECK(source_report_sha256 ~ '^[0-9a-f]{64}$'),
    rules_path text NOT NULL,
    rules_sha256 text NOT NULL CHECK(rules_sha256 ~ '^[0-9a-f]{64}$'),
    authorization_path text NOT NULL,
    authorization_sha256 text NOT NULL CHECK(authorization_sha256 ~ '^[0-9a-f]{64}$'),
    authorization_text text NOT NULL,
    source_candidate_count integer NOT NULL CHECK(source_candidate_count=75),
    idempotency_note text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE game_formal_import_receipts (
    game_id uuid PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    batch_key text NOT NULL REFERENCES game_formal_import_batches(batch_key),
    slug text NOT NULL UNIQUE,
    canonical_board_code text NOT NULL,
    storage_board_code text NOT NULL,
    candidate_path text NOT NULL,
    candidate_sha256 text NOT NULL CHECK(candidate_sha256 ~ '^[0-9a-f]{64}$'),
    formal_files jsonb NOT NULL,
    source_files jsonb NOT NULL,
    normalization jsonb NOT NULL,
    overall_batch_authorized boolean NOT NULL DEFAULT true CHECK(overall_batch_authorized),
    field_confirmation text NOT NULL DEFAULT 'not_claimed_by_batch_authorization'
        CHECK(field_confirmation='not_claimed_by_batch_authorization'),
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX game_formal_import_receipts_batch_idx ON game_formal_import_receipts(batch_key);

CREATE TABLE game_formal_annotations (
    game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    annotation_key text NOT NULL,
    annotation_type text NOT NULL CHECK(annotation_type IN (
        'supplemental_observations','vote_control','endgame','review_context','bluff_review','terminal_observations'
    )),
    source_path text NOT NULL,
    source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(game_id, annotation_key)
);
