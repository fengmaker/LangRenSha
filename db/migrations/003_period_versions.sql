-- A corrected scoring rule gets a new period version; old published facts keep theirs.
ALTER TABLE scoring_periods ADD COLUMN version_no integer NOT NULL DEFAULT 1 CHECK (version_no>0);
ALTER TABLE scoring_periods DROP CONSTRAINT scoring_periods_season_id_phase_key;
ALTER TABLE scoring_periods ADD UNIQUE (season_id,phase,version_no);
