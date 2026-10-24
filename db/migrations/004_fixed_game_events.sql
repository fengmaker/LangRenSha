-- Current game model: shared people, files and fixed board/round event slots.
-- Earlier extraction/review tables remain historical and are not the write path.
CREATE TABLE people (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE CHECK (length(trim(name))>0)
);
INSERT INTO people(id,name) SELECT DISTINCT ON (display_name) id,display_name FROM players ORDER BY display_name,id;
CREATE TABLE person_aliases (
    alias text PRIMARY KEY CHECK (length(trim(alias))>0),
    person_id uuid NOT NULL REFERENCES people(id)
);
INSERT INTO person_aliases(alias,person_id) SELECT name,id FROM people;

CREATE TABLE board_templates (
    code text PRIMARY KEY,
    name text NOT NULL UNIQUE,
    seat_count integer NOT NULL CHECK(seat_count>0),
    role_counts jsonb NOT NULL,
    wake_order text[] NOT NULL
);
CREATE TABLE board_event_slots (
    board_code text NOT NULL REFERENCES board_templates(code),
    phase text NOT NULL CHECK(phase IN ('night','day')),
    code text NOT NULL,
    position integer NOT NULL CHECK(position>0),
    label text NOT NULL,
    actor_role text,
    allowed_actions text[] NOT NULL,
    PRIMARY KEY(board_code,phase,code),
    UNIQUE(board_code,phase,position)
);
CREATE TABLE game_details (
    game_id uuid PRIMARY KEY REFERENCES games(id),
    board_code text NOT NULL REFERENCES board_templates(code),
    event_date date NOT NULL,
    phase text NOT NULL,
    episode integer,
    day_in_episode integer,
    game_number integer NOT NULL CHECK(game_number>0),
    winning_faction text CHECK(winning_faction IN ('good','werewolf','draw')),
    UNIQUE(game_id,board_code)
);
CREATE TABLE game_staff (
    game_id uuid NOT NULL REFERENCES game_details(game_id),
    person_id uuid NOT NULL REFERENCES people(id),
    duty text NOT NULL CHECK(duty IN ('commentator','referee')),
    position integer NOT NULL CHECK(position>0),
    PRIMARY KEY(game_id,duty,position),
    UNIQUE(game_id,duty,person_id)
);
CREATE TABLE game_seats (
    game_id uuid NOT NULL REFERENCES game_details(game_id),
    seat_number integer NOT NULL CHECK(seat_number BETWEEN 1 AND 64),
    person_id uuid REFERENCES people(id),
    role text NOT NULL,
    faction text NOT NULL CHECK(faction IN ('good','werewolf')),
    learning_target_seat integer,
    learned_role text,
    PRIMARY KEY(game_id,seat_number),
    UNIQUE(game_id,person_id),
    FOREIGN KEY(game_id,learning_target_seat) REFERENCES game_seats(game_id,seat_number) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE game_files (
    game_id uuid NOT NULL REFERENCES game_details(game_id),
    file_role text NOT NULL CHECK(file_role IN ('audio','subtitle','transcript','metadata','manifest','schedule','introduction')),
    artifact_id uuid NOT NULL REFERENCES artifacts(id),
    PRIMARY KEY(game_id,file_role)
);
CREATE TABLE game_rounds (
    game_id uuid NOT NULL REFERENCES game_details(game_id),
    round_number integer NOT NULL CHECK(round_number>0),
    PRIMARY KEY(game_id,round_number)
);
CREATE TABLE game_event_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    round_number integer NOT NULL,
    board_code text NOT NULL,
    phase text NOT NULL,
    slot_code text NOT NULL,
    action text NOT NULL,
    actor_seat integer,
    result_code text,
    start_seat integer,
    direction text CHECK(direction IN ('forward','reverse')),
    UNIQUE(game_id,round_number,phase,slot_code),
    UNIQUE(id,game_id),
    FOREIGN KEY(game_id,round_number) REFERENCES game_rounds(game_id,round_number),
    FOREIGN KEY(game_id,board_code) REFERENCES game_details(game_id,board_code),
    FOREIGN KEY(board_code,phase,slot_code) REFERENCES board_event_slots(board_code,phase,code),
    FOREIGN KEY(game_id,actor_seat) REFERENCES game_seats(game_id,seat_number),
    FOREIGN KEY(game_id,start_seat) REFERENCES game_seats(game_id,seat_number)
);
CREATE TABLE game_event_targets (
    event_id uuid NOT NULL,
    game_id uuid NOT NULL,
    position integer NOT NULL CHECK(position>0),
    seat_number integer NOT NULL,
    PRIMARY KEY(event_id,position),
    UNIQUE(event_id,seat_number),
    FOREIGN KEY(event_id,game_id) REFERENCES game_event_records(id,game_id),
    FOREIGN KEY(game_id,seat_number) REFERENCES game_seats(game_id,seat_number)
);
CREATE TABLE game_event_votes (
    event_id uuid NOT NULL,
    game_id uuid NOT NULL,
    ballot_round integer NOT NULL CHECK(ballot_round>0),
    voter_seat integer NOT NULL,
    target_seat integer,
    abstained boolean NOT NULL DEFAULT false,
    PRIMARY KEY(event_id,ballot_round,voter_seat),
    CHECK ((abstained AND target_seat IS NULL) OR (NOT abstained AND target_seat IS NOT NULL)),
    FOREIGN KEY(event_id,game_id) REFERENCES game_event_records(id,game_id),
    FOREIGN KEY(game_id,voter_seat) REFERENCES game_seats(game_id,seat_number),
    FOREIGN KEY(game_id,target_seat) REFERENCES game_seats(game_id,seat_number)
);
CREATE FUNCTION check_board_event_action() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE allowed text[];
BEGIN
    SELECT allowed_actions INTO STRICT allowed FROM board_event_slots
      WHERE board_code=NEW.board_code AND phase=NEW.phase AND code=NEW.slot_code;
    IF NOT (NEW.action=ANY(allowed)) THEN RAISE EXCEPTION '事件动作不属于版型槽位'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER board_event_action_guard BEFORE INSERT OR UPDATE ON game_event_records
FOR EACH ROW EXECUTE FUNCTION check_board_event_action();
CREATE INDEX game_event_records_order_idx ON game_event_records(game_id,round_number,phase);
