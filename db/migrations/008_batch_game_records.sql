-- Batch review records may preserve unknown seat details and match outcome.
ALTER TABLE game_details ALTER COLUMN game_number DROP NOT NULL;
ALTER TABLE game_details DROP CONSTRAINT IF EXISTS game_details_winning_faction_check;
ALTER TABLE game_details ADD CONSTRAINT game_details_winning_faction_check
    CHECK (winning_faction IS NULL OR winning_faction IN ('good','werewolf','third_party','draw'));

ALTER TABLE game_seats ALTER COLUMN role DROP NOT NULL;
ALTER TABLE game_seats ALTER COLUMN faction DROP NOT NULL;
ALTER TABLE game_seats DROP CONSTRAINT IF EXISTS game_seats_faction_check;
ALTER TABLE game_seats ADD CONSTRAINT game_seats_faction_check
    CHECK (faction IS NULL OR faction IN ('good','werewolf','third_party'));
