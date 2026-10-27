-- Identity-only reviews are source-bound observations, independent of full
-- game imports, board rules, game events, results and publication.
CREATE VIEW reviewed_identity_seats AS
WITH latest AS (
    SELECT DISTINCT ON (source_id) id,source_id,payload,created_at
    FROM extraction_runs
    WHERE method='visual_identity_only_v1' AND verification_status='reviewed'
    ORDER BY source_id,created_at DESC,id DESC
)
SELECT e.id AS extraction_id,e.source_id,e.payload->>'season' AS season,
    e.payload->>'bvid' AS bvid,(e.payload->>'cid')::bigint AS cid,
    (e.payload->>'page')::integer AS page,
    (p.value->>'seat')::integer AS seat_number,
    p.value->>'name' AS name,p.value->>'display_name' AS display_name,
    p.value->>'role' AS role,p.value->'evidence' AS evidence,
    e.payload->'review' AS review,e.created_at AS recorded_at
FROM latest e
CROSS JOIN LATERAL jsonb_array_elements(e.payload->'seats') p(value);
