-- Confirmed S22 election flow: one postponement after day-one self-destruct.
ALTER TABLE game_voting_days DROP CONSTRAINT game_voting_days_sheriff_status_check;
ALTER TABLE game_voting_days ADD CONSTRAINT game_voting_days_sheriff_status_check
    CHECK(sheriff_status IN ('recorded','unknown','deferred','badge_lost','not_applicable'));
