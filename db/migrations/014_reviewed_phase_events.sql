-- Day/night observations can be reviewed before a full S21 rules adaptation.
-- They do not create formal games, identities, bluff annotations or releases.
CREATE VIEW reviewed_phase_records AS
SELECT DISTINCT ON (source_id) id AS extraction_id,source_id,payload,created_at
FROM extraction_runs
WHERE method='s21_day_night_review_v1' AND verification_status='reviewed'
ORDER BY source_id,created_at DESC,id DESC;

CREATE VIEW reviewed_phase_events AS
SELECT r.extraction_id,r.source_id,r.payload->>'season' AS season,
    r.payload->>'bvid' AS bvid,(r.payload->>'cid')::bigint AS cid,
    (r.payload->>'page')::integer AS page,
    e.value->>'event_id' AS event_id,e.value->>'phase' AS phase,
    (e.value->>'round')::integer AS phase_round,e.value->>'action' AS action,
    (e.value->>'actor')::integer AS actor_seat,e.value->>'actor_physical_role' AS actor_physical_role,
    e.value->'targets' AS targets,e.value->'actual_targets' AS actual_targets,
    e.value->>'state' AS action_state,e.value->>'status' AS evidence_status,
    e.value->>'result' AS result,e.value->'details' AS details,
    e.value->>'note' AS note,e.value->'evidence' AS evidence,r.created_at AS recorded_at
FROM reviewed_phase_records r
CROSS JOIN LATERAL jsonb_array_elements(r.payload->'events') e(value);

CREATE VIEW reviewed_phase_ballots AS
SELECT r.extraction_id,r.source_id,r.payload->>'season' AS season,
    r.payload->>'bvid' AS bvid,(r.payload->>'cid')::bigint AS cid,
    (r.payload->>'page')::integer AS page,
    b.value->>'ballot_id' AS ballot_id,(b.value->>'day')::integer AS day_number,
    b.value->>'type' AS ballot_type,b.value->>'stage' AS stage,
    b.value->>'completeness' AS completeness,b.value AS ballot,r.created_at AS recorded_at
FROM reviewed_phase_records r
CROSS JOIN LATERAL jsonb_array_elements(r.payload->'ballots') b(value);
