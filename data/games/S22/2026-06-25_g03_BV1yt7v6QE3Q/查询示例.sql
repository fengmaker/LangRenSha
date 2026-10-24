SET search_path TO jcms, public;

-- Current game, without revision or review fields.
SELECT g.slug,s.code AS season,d.event_date,d.episode,d.day_in_episode,
       d.game_number,b.name AS board,d.winning_faction
FROM games g JOIN game_details d ON d.game_id=g.id
JOIN seasons s ON s.id=g.season_id JOIN board_templates b ON b.code=d.board_code
WHERE g.slug='bili-BV1yt7v6QE3Q-p01-g03';

-- Seats and shared people.
SELECT s.seat_number,p.name,s.role,s.faction,s.learning_target_seat,s.learned_role
FROM games g JOIN game_seats s ON s.game_id=g.id LEFT JOIN people p ON p.id=s.person_id
WHERE g.slug='bili-BV1yt7v6QE3Q-p01-g03' ORDER BY s.seat_number;

-- Commentators and referee use the same people table as the seats.
SELECT p.name,s.duty FROM games g JOIN game_staff s ON s.game_id=g.id
JOIN people p ON p.id=s.person_id
WHERE g.slug='bili-BV1yt7v6QE3Q-p01-g03' ORDER BY s.duty,s.position;

-- Fixed slots and structured values, in round/template order.
SELECT e.round_number,e.phase,b.label,e.action,
       e.actor_seat,actor.role AS actor_role,e.result_code,e.availability,
       e.random_point,e.speech_scope,e.start_seat,start.role AS start_role,e.direction,targets.seats AS targets,
       effects.items AS resolved_effects
FROM games g JOIN game_event_records e ON e.game_id=g.id
JOIN board_event_slots b ON b.board_code=e.board_code AND b.phase=e.phase AND b.code=e.slot_code
LEFT JOIN game_seats actor ON actor.game_id=e.game_id AND actor.seat_number=e.actor_seat
LEFT JOIN game_seats start ON start.game_id=e.game_id AND start.seat_number=e.start_seat
LEFT JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object('seat',t.seat_number,'role',s.role) ORDER BY t.position) AS seats
    FROM game_event_targets t JOIN game_seats s ON s.game_id=t.game_id AND s.seat_number=t.seat_number
    WHERE t.event_id=e.id
) targets ON true
LEFT JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object('kind',f.kind,'intended_target',f.intended_target,
        'dead_seat',f.dead_seat,'shield_actor',f.shield_actor) ORDER BY f.position) AS items
    FROM game_event_effects f WHERE f.event_id=e.id
) effects ON true
WHERE g.slug='bili-BV1yt7v6QE3Q-p01-g03'
ORDER BY e.round_number,CASE e.phase WHEN 'night' THEN 0 ELSE 1 END,b.position;

-- Source file registration.
SELECT f.file_role,a.kind,a.relative_path,a.byte_size,a.sha256
FROM games g JOIN game_files f ON f.game_id=g.id JOIN artifacts a ON a.id=f.artifact_id
WHERE g.slug='bili-BV1yt7v6QE3Q-p01-g03' ORDER BY f.file_role;
