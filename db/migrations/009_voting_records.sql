-- Whole-transcript ballot supplements. Evidence remains in files, not business tables.
CREATE TABLE game_sheriff_registrations (
    game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    registration_key text NOT NULL,
    day_number integer CHECK(day_number>0),
    seat_number integer NOT NULL CHECK(seat_number BETWEEN 1 AND 12),
    registered boolean NOT NULL,
    PRIMARY KEY(game_id,registration_key,seat_number)
);
CREATE TABLE game_ballots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    ballot_key text NOT NULL,
    day_number integer CHECK(day_number>0),
    kind text NOT NULL CHECK(kind IN ('sheriff','exile','unknown')),
    ballot_number integer NOT NULL CHECK(ballot_number>0),
    stage text NOT NULL CHECK(stage IN ('initial','pk','revote','unknown')),
    status text NOT NULL CHECK(status IN ('partial','complete')),
    candidates integer[],
    eligible_voters integer[],
    tied_candidates integer[] NOT NULL DEFAULT '{}',
    winner_seat integer CHECK(winner_seat BETWEEN 1 AND 12),
    UNIQUE(game_id,ballot_key),
    CHECK(status <> 'complete' OR eligible_voters IS NOT NULL)
);
CREATE TABLE game_ballot_choices (
    ballot_id uuid NOT NULL REFERENCES game_ballots(id) ON DELETE CASCADE,
    voter_seat integer NOT NULL CHECK(voter_seat BETWEEN 1 AND 12),
    target_seat integer CHECK(target_seat BETWEEN 1 AND 12),
    state text NOT NULL CHECK(state IN ('cast','abstained')),
    PRIMARY KEY(ballot_id,voter_seat),
    CHECK((state='cast' AND target_seat IS NOT NULL) OR (state='abstained' AND target_seat IS NULL))
);
CREATE TABLE game_voting_days (
    game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    day_number integer NOT NULL CHECK(day_number>0),
    sheriff_status text NOT NULL CHECK(sheriff_status IN ('recorded','unknown')),
    exile_status text NOT NULL CHECK(exile_status IN ('recorded','unknown','interrupted_self_destruct')),
    PRIMARY KEY(game_id,day_number)
);
CREATE INDEX game_ballots_day_idx ON game_ballots(game_id,day_number,kind,ballot_number);
CREATE VIEW current_game_votes AS
SELECT g.slug,d.event_date,d.game_number,b.day_number,b.kind,b.ballot_number,b.stage,b.status,
       v.voter_seat,v.target_seat,v.state,b.candidates,b.eligible_voters,b.tied_candidates,b.winner_seat
FROM game_ballot_choices v JOIN game_ballots b ON b.id=v.ballot_id
JOIN games g ON g.id=b.game_id JOIN game_details d ON d.game_id=g.id;
