-- A resolved effect must belong to the chosen target of its source action.
ALTER TABLE game_event_effects ADD CONSTRAINT effect_target_is_chosen
    FOREIGN KEY(event_id,intended_target) REFERENCES game_event_targets(event_id,seat_number)
    DEFERRABLE INITIALLY DEFERRED;

-- Deferred because witch poison precedes the mechanical guard in the fixed slots.
CREATE FUNCTION check_effect_shield_links() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE affected_game uuid; effect record;
BEGIN
    affected_game=COALESCE(NEW.game_id,OLD.game_id);
    FOR effect IN SELECT f.*,e.round_number,e.slot_code,e.actor_seat,e.action
        FROM game_event_effects f JOIN game_event_records e ON e.id=f.event_id
        WHERE f.game_id=affected_game AND f.kind IN ('poison_reflected','shield_bypassed') LOOP
        IF effect.kind='poison_reflected' THEN
            IF effect.slot_code<>'witch_poison' OR NOT EXISTS (
                SELECT 1 FROM game_event_records guard
                JOIN game_event_targets target ON target.event_id=guard.id
                JOIN game_seats actor ON actor.game_id=guard.game_id AND actor.seat_number=guard.actor_seat
                JOIN game_seats witch ON witch.game_id=guard.game_id AND witch.seat_number=effect.actor_seat
                WHERE guard.game_id=affected_game AND guard.round_number=effect.round_number
                  AND guard.slot_code='mechanical_action' AND guard.phase='night' AND guard.action='guard'
                  AND guard.actor_seat=effect.shield_actor AND target.seat_number=effect.intended_target
                  AND actor.role='机械狼' AND actor.learned_role='机械守卫' AND witch.role='女巫'
            ) THEN RAISE EXCEPTION '毒药反弹必须对应本夜机械守卫的实际守护目标'; END IF;
        ELSIF effect.slot_code<>'mechanical_action' OR effect.action<>'attack' OR NOT EXISTS (
            SELECT 1 FROM game_event_records guard
            JOIN game_event_targets target ON target.event_id=guard.id
            JOIN game_seats actor ON actor.game_id=guard.game_id AND actor.seat_number=effect.actor_seat
            JOIN game_seats protector ON protector.game_id=guard.game_id AND protector.seat_number=guard.actor_seat
            WHERE guard.game_id=affected_game AND guard.round_number=effect.round_number
              AND guard.slot_code='guard' AND guard.phase='night' AND guard.action='guard'
              AND guard.actor_seat=effect.shield_actor AND target.seat_number=effect.intended_target
              AND actor.role='机械狼' AND actor.learned_role='机械双刀狼' AND protector.role='守卫'
        ) THEN RAISE EXCEPTION '穿盾必须对应机械双刀技能刀与本夜守卫的实际盾'; END IF;
    END LOOP;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER effect_shield_links AFTER INSERT OR UPDATE ON game_event_effects
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_effect_shield_links();
CREATE CONSTRAINT TRIGGER event_shield_links AFTER UPDATE OR DELETE ON game_event_records
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_effect_shield_links();
CREATE CONSTRAINT TRIGGER target_shield_links AFTER UPDATE OR DELETE ON game_event_targets
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_effect_shield_links();
CREATE CONSTRAINT TRIGGER seat_shield_links AFTER UPDATE OR DELETE ON game_seats
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_effect_shield_links();
