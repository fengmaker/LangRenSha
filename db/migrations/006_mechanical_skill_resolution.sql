-- Mechanical skill timing and resolved effects are separate from chosen targets.
ALTER TABLE game_event_records ADD COLUMN availability text
    CHECK(availability IN ('learning','locked','available','wrong_phase','no_skill','dead','poisoned','wolves_alive','unknown'));
ALTER TABLE game_event_records ADD CONSTRAINT mechanical_availability_only
    CHECK(availability IS NULL OR slot_code IN ('mechanical_action','mechanical_day_skill'));

CREATE TABLE game_event_effects (
    event_id uuid NOT NULL,
    game_id uuid NOT NULL,
    position integer NOT NULL CHECK(position>0),
    kind text NOT NULL CHECK(kind IN ('poison_death','poison_reflected','poison_unresolved','shield_bypassed')),
    intended_target integer NOT NULL,
    dead_seat integer,
    shield_actor integer,
    PRIMARY KEY(event_id,position),
    FOREIGN KEY(event_id,game_id) REFERENCES game_event_records(id,game_id),
    FOREIGN KEY(game_id,intended_target) REFERENCES game_seats(game_id,seat_number),
    FOREIGN KEY(game_id,dead_seat) REFERENCES game_seats(game_id,seat_number),
    FOREIGN KEY(game_id,shield_actor) REFERENCES game_seats(game_id,seat_number),
    CHECK((kind='poison_death' AND dead_seat IS NOT NULL AND dead_seat=intended_target AND shield_actor IS NULL)
       OR (kind='poison_reflected' AND dead_seat IS NOT NULL AND shield_actor IS NOT NULL)
       OR (kind='poison_unresolved' AND dead_seat IS NULL AND shield_actor IS NULL)
       OR (kind='shield_bypassed' AND dead_seat IS NULL AND shield_actor IS NOT NULL))
);

CREATE FUNCTION check_resolved_event_effect() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE event_actor integer; event_action text;
BEGIN
    SELECT actor_seat,action INTO STRICT event_actor,event_action FROM game_event_records
      WHERE id=NEW.event_id AND game_id=NEW.game_id;
    IF NEW.kind IN ('poison_death','poison_reflected','poison_unresolved') AND event_action<>'poison' THEN
        RAISE EXCEPTION '毒药结算必须关联用毒事件';
    END IF;
    IF NEW.kind='poison_reflected' AND NEW.dead_seat IS DISTINCT FROM event_actor THEN
        RAISE EXCEPTION '毒药反弹时死亡者必须是用毒者';
    END IF;
    IF NEW.kind='shield_bypassed' AND event_action<>'attack' THEN
        RAISE EXCEPTION '穿盾结算必须关联技能刀事件';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER resolved_event_effect_guard BEFORE INSERT OR UPDATE ON game_event_effects
FOR EACH ROW EXECUTE FUNCTION check_resolved_event_effect();
