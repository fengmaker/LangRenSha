CREATE SCHEMA IF NOT EXISTS masters_web;
SET search_path TO masters_web, public;

CREATE TABLE IF NOT EXISTS releases (
    id text PRIMARY KEY,
    published_at timestamptz NOT NULL DEFAULT now(),
    season text NOT NULL,
    game_count integer NOT NULL CHECK (game_count >= 0),
    source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    rules_hash text NOT NULL CHECK (rules_hash ~ '^[0-9a-f]{64}$'),
    manifest jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS active_release (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    release_id text NOT NULL REFERENCES releases(id)
);

CREATE TABLE IF NOT EXISTS games (
    release_id text NOT NULL REFERENCES releases(id),
    id text NOT NULL,
    season text NOT NULL,
    event_date date NOT NULL,
    phase text NOT NULL,
    game_number integer,
    board_code text NOT NULL,
    board_name text NOT NULL,
    winner text,
    bvid text NOT NULL,
    search_text text NOT NULL,
    ballot_count integer NOT NULL CHECK (ballot_count >= 0),
    vote_count integer NOT NULL CHECK (vote_count >= 0),
    round_count integer NOT NULL CHECK (round_count >= 0),
    snapshot jsonb NOT NULL,
    PRIMARY KEY (release_id, id)
);
CREATE INDEX IF NOT EXISTS games_release_date_idx ON games(release_id, event_date DESC, id);
CREATE INDEX IF NOT EXISTS games_release_season_idx ON games(release_id, season, phase, board_code);
CREATE INDEX IF NOT EXISTS games_release_search_idx ON games(release_id, search_text);

CREATE TABLE IF NOT EXISTS players (
    release_id text NOT NULL REFERENCES releases(id),
    id text NOT NULL,
    name text NOT NULL,
    appearances integer NOT NULL CHECK (appearances >= 0),
    roles jsonb NOT NULL,
    PRIMARY KEY (release_id, id)
);
CREATE INDEX IF NOT EXISTS players_release_name_idx ON players(release_id, lower(name));

CREATE TABLE IF NOT EXISTS game_players (
    release_id text NOT NULL,
    game_id text NOT NULL,
    person_id text NOT NULL,
    name text NOT NULL,
    seat integer NOT NULL,
    role text,
    faction text,
    PRIMARY KEY (release_id, game_id, person_id),
    UNIQUE (release_id, game_id, seat),
    FOREIGN KEY (release_id, game_id) REFERENCES games(release_id, id),
    FOREIGN KEY (release_id, person_id) REFERENCES players(release_id, id)
);
ALTER TABLE game_players ALTER COLUMN faction DROP NOT NULL;
ALTER TABLE game_players ALTER COLUMN role DROP NOT NULL;
CREATE INDEX IF NOT EXISTS game_players_release_person_idx ON game_players(release_id, person_id, game_id);

-- Bluff reviews are immutable versions attached to one immutable game release.
CREATE UNIQUE INDEX IF NOT EXISTS game_players_release_game_seat_person_uidx
    ON game_players(release_id, game_id, seat, person_id);

CREATE TABLE IF NOT EXISTS bluff_review_publications (
    id text PRIMARY KEY,
    release_id text NOT NULL REFERENCES releases(id),
    season text NOT NULL,
    inference_version text NOT NULL,
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    published_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, release_id),
    UNIQUE (id, release_id, season)
);
CREATE INDEX IF NOT EXISTS bluff_review_publications_release_idx
    ON bluff_review_publications(release_id, season, published_at DESC);

CREATE TABLE IF NOT EXISTS active_bluff_reviews (
    release_id text NOT NULL REFERENCES releases(id),
    season text NOT NULL,
    publication_id text NOT NULL,
    PRIMARY KEY (release_id, season),
    FOREIGN KEY (publication_id, release_id, season)
        REFERENCES bluff_review_publications(id, release_id, season)
);

CREATE TABLE IF NOT EXISTS bluff_review_items (
    publication_id text NOT NULL,
    release_id text NOT NULL,
    game_id text NOT NULL,
    seat integer NOT NULL CHECK (seat > 0),
    player_id text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('yes', 'no', 'uncertain')),
    success boolean,
    verification_status text NOT NULL,
    needs_review boolean NOT NULL,
    record jsonb NOT NULL,
    PRIMARY KEY (publication_id, game_id, seat),
    CHECK (decision = 'yes' OR success IS NULL),
    FOREIGN KEY (publication_id, release_id)
        REFERENCES bluff_review_publications(id, release_id),
    FOREIGN KEY (release_id, game_id) REFERENCES games(release_id, id),
    FOREIGN KEY (release_id, player_id) REFERENCES players(release_id, id),
    FOREIGN KEY (release_id, game_id, seat, player_id)
        REFERENCES game_players(release_id, game_id, seat, person_id)
);
CREATE INDEX IF NOT EXISTS bluff_review_items_player_idx
    ON bluff_review_items(release_id, player_id, publication_id);

CREATE OR REPLACE VIEW bluff_player_stats AS
SELECT
    p.release_id,
    p.id AS player_id,
    p.name,
    (abr.publication_id IS NOT NULL) AS review_published,
    count(i.seat) FILTER (WHERE i.decision = 'yes')::integer AS bluff_count,
    CASE WHEN abr.publication_id IS NULL THEN false
         ELSE coalesce(bool_and(i.decision <> 'uncertain') FILTER (WHERE i.seat IS NOT NULL), true)
    END AS bluff_count_complete,
    count(i.seat) FILTER (WHERE i.decision = 'uncertain')::integer AS bluff_pending_games,
    count(i.seat) FILTER (WHERE i.needs_review)::integer AS bluff_review_count,
    count(i.seat) FILTER (WHERE i.decision = 'yes' AND i.success IS TRUE)::integer
        AS bluff_success_count,
    count(i.seat) FILTER (WHERE i.decision = 'yes' AND i.success IS NOT NULL)::integer
        AS bluff_success_denominator,
    count(i.seat) FILTER (WHERE i.decision = 'uncertain'
                          OR (i.decision = 'yes' AND i.success IS NULL))::integer
        AS bluff_success_excluded,
    count(i.seat) FILTER (WHERE i.decision = 'yes' AND i.success IS TRUE)::numeric
        / nullif(count(i.seat) FILTER (WHERE i.decision = 'yes' AND i.success IS NOT NULL), 0)
        AS bluff_success_rate
FROM active_release ar
JOIN releases r ON r.id = ar.release_id
JOIN players p ON p.release_id = r.id
LEFT JOIN active_bluff_reviews abr
    ON abr.release_id = r.id AND abr.season = r.season
LEFT JOIN bluff_review_items i
    ON i.publication_id = abr.publication_id
    AND i.release_id = p.release_id
    AND i.player_id = p.id
GROUP BY p.release_id, p.id, p.name, abr.publication_id;
