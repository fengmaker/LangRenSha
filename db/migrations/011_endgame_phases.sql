-- Explicit terminal phases are independent of ordinary nights and ballots.
-- Source quotes, review notes and hashes remain in the source-bound sidecars.
CREATE TABLE game_endgame_phases (
    game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    phase_number integer NOT NULL CHECK(phase_number > 0),
    kind text NOT NULL CHECK(kind IN ('wolf_rush')),
    day_number integer CHECK(day_number > 0),
    actor_seat integer CHECK(actor_seat BETWEEN 1 AND 12),
    declared_targets integer[] NOT NULL DEFAULT '{}',
    result text NOT NULL CHECK(result IN ('werewolf_win', 'good_win', 'unknown')),
    PRIMARY KEY(game_id, phase_number),
    CHECK(declared_targets <@ ARRAY[1,2,3,4,5,6,7,8,9,10,11,12]),
    CHECK(array_position(declared_targets, NULL) IS NULL)
);

CREATE VIEW current_game_endgame_phases AS
SELECT g.slug, d.event_date, d.game_number, p.phase_number, p.kind,
       p.day_number, p.actor_seat, p.declared_targets, p.result
FROM game_endgame_phases p
JOIN games g ON g.id = p.game_id
JOIN game_details d ON d.game_id = g.id;
