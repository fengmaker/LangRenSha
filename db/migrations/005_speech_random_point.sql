-- Random point and the eligible speaking group are separate from the start seat.
ALTER TABLE game_event_records ADD COLUMN random_point integer CHECK(random_point BETWEEN 1 AND 64);
ALTER TABLE game_event_records ADD COLUMN speech_scope text CHECK(speech_scope IN ('sheriff','day'));
UPDATE game_event_records SET speech_scope='day' WHERE slot_code='speech_order' AND action='order';
ALTER TABLE game_event_records ADD CONSTRAINT speech_order_scope_present
    CHECK (slot_code<>'speech_order' OR action<>'order' OR speech_scope IS NOT NULL);
ALTER TABLE game_event_records ADD CONSTRAINT speech_fields_only_on_speech_slot
    CHECK (slot_code='speech_order' OR (random_point IS NULL AND speech_scope IS NULL));
