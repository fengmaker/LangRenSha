-- 业务库只保存当前对局事实；处理/人工复核进度另见 data/reports/S22_对局批处理进度.json。
SET search_path TO jcms, public;

-- 全季每局的实际内容覆盖；known_events 不包含 unknown 固定槽位。
WITH seat_counts AS (
    SELECT game_id, count(*) AS seats, count(role) AS known_roles, count(person_id) AS named_seats
    FROM game_seats GROUP BY game_id
), event_counts AS (
    SELECT game_id, count(*) AS total_slots,
           count(*) FILTER (WHERE action <> 'unknown') AS known_events
    FROM game_event_records GROUP BY game_id
)
SELECT g.slug, d.event_date, d.game_number, b.name AS board, d.winning_faction,
       c.seats, c.known_roles, c.named_seats,
       coalesce(e.known_events, 0) AS known_events, coalesce(e.total_slots, 0) AS total_slots
FROM games g JOIN seasons s ON s.id=g.season_id
JOIN game_details d ON d.game_id=g.id JOIN board_templates b ON b.code=d.board_code
LEFT JOIN seat_counts c ON c.game_id=g.id LEFT JOIN event_counts e ON e.game_id=g.id
WHERE s.code='S22'
ORDER BY d.event_date, d.game_number NULLS LAST, g.slug;

-- 某局逐轮事件，目标按记录顺序展示；可替换下面的 slug。
SELECT e.round_number, e.phase, t.label, e.action, e.actor_seat, e.result_code,
       coalesce(array_agg(x.seat_number ORDER BY x.position)
           FILTER (WHERE x.seat_number IS NOT NULL), ARRAY[]::integer[]) AS targets
FROM game_event_records e JOIN games g ON g.id=e.game_id
JOIN board_event_slots t ON t.board_code=e.board_code AND t.phase=e.phase AND t.code=e.slot_code
LEFT JOIN game_event_targets x ON x.event_id=e.id
WHERE g.slug='bili-BV1iJVT6SEL2-p01-g01'
GROUP BY e.id, t.label, t.position
ORDER BY e.round_number, CASE e.phase WHEN 'night' THEN 0 ELSE 1 END, t.position;
