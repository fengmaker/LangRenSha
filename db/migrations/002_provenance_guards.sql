-- Versioned evidence must remain stable after ingestion/review.
CREATE FUNCTION reject_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '历史记录不可原地修改或删除；请追加新版本/事件';
END;
$$;
CREATE TRIGGER review_history_guard BEFORE UPDATE OR DELETE ON reviews
FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();
CREATE TRIGGER publication_history_guard BEFORE UPDATE OR DELETE ON publication_events
FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();
CREATE TRIGGER audit_history_guard BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();
CREATE TRIGGER segment_history_guard BEFORE UPDATE OR DELETE ON transcript_segments
FOR EACH ROW EXECUTE FUNCTION reject_history_mutation();

CREATE FUNCTION guard_extraction_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' OR (to_jsonb(NEW)-'verification_status') IS DISTINCT FROM (to_jsonb(OLD)-'verification_status') THEN
        RAISE EXCEPTION '提取原文不可修改；请追加提取版本';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER extraction_history_guard BEFORE UPDATE OR DELETE ON extraction_runs
FOR EACH ROW EXECUTE FUNCTION guard_extraction_history();
CREATE TRIGGER transcription_history_guard BEFORE UPDATE OR DELETE ON transcription_runs
FOR EACH ROW EXECUTE FUNCTION guard_extraction_history();
