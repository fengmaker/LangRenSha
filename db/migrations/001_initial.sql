-- Initial PostgreSQL schema. Applied inside the selected application schema.
CREATE TABLE seasons (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE players (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name text NOT NULL CHECK (length(trim(display_name)) > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE player_aliases (
    player_id uuid NOT NULL REFERENCES players(id),
    alias text NOT NULL,
    PRIMARY KEY (player_id, alias)
);
CREATE TABLE sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    platform text NOT NULL CHECK (platform IN ('bilibili','weibo','user_reported','other')),
    external_key text NOT NULL,
    url text,
    title text,
    author_id text,
    published_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    collected_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (platform, external_key)
);
CREATE TABLE artifacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES sources(id),
    kind text NOT NULL CHECK (kind IN ('metadata','manifest','audio','subtitle','asr','frame','candidate','weibo_json','image')),
    relative_path text NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, kind, sha256),
    UNIQUE (id, source_id)
);
CREATE TABLE rule_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    kind text NOT NULL CHECK (kind IN ('board','scoring')),
    season_id uuid REFERENCES seasons(id),
    source_id uuid REFERENCES sources(id),
    verified boolean NOT NULL DEFAULT false,
    definition jsonb NOT NULL
);
CREATE TABLE scoring_periods (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    season_id uuid NOT NULL REFERENCES seasons(id),
    phase text NOT NULL CHECK (phase IN ('regular','finals_week')),
    rule_version_id uuid REFERENCES rule_versions(id),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (season_id, phase)
);
CREATE TABLE transcription_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES sources(id),
    artifact_id uuid NOT NULL UNIQUE REFERENCES artifacts(id),
    engine text NOT NULL,
    model text NOT NULL,
    language text,
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    verification_status text NOT NULL DEFAULT 'unverified' CHECK (verification_status IN ('unverified','reviewed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, source_id),
    FOREIGN KEY (artifact_id,source_id) REFERENCES artifacts(id,source_id)
);
CREATE TABLE transcript_segments (
    run_id uuid NOT NULL REFERENCES transcription_runs(id),
    segment_index integer NOT NULL CHECK (segment_index >= 0),
    start_seconds numeric(12,3) NOT NULL CHECK (start_seconds >= 0),
    end_seconds numeric(12,3) NOT NULL,
    text text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, segment_index),
    CHECK (end_seconds >= start_seconds)
);
CREATE TABLE extraction_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES sources(id),
    transcription_run_id uuid REFERENCES transcription_runs(id),
    artifact_id uuid NOT NULL UNIQUE REFERENCES artifacts(id),
    method text NOT NULL,
    payload jsonb NOT NULL,
    verification_status text NOT NULL DEFAULT 'needs_review' CHECK (verification_status IN ('needs_review','reviewed','rejected')),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (artifact_id,source_id) REFERENCES artifacts(id,source_id),
    FOREIGN KEY (transcription_run_id,source_id) REFERENCES transcription_runs(id,source_id)
);
CREATE VIEW candidate_participants AS
SELECT e.id AS extraction_id, e.source_id, p.value AS candidate
FROM extraction_runs e
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(e.payload->'participant_candidates','[]'::jsonb)) p(value);

CREATE TABLE games (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE,
    season_id uuid REFERENCES seasons(id),
    primary_source_id uuid REFERENCES sources(id),
    published_revision_id uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE game_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL REFERENCES games(id),
    revision_no integer NOT NULL CHECK (revision_no > 0),
    review_state text NOT NULL DEFAULT 'draft' CHECK (review_state IN ('draft','submitted','approved','rejected')),
    from_extraction_id uuid REFERENCES extraction_runs(id),
    event_date date,
    phase text CHECK (phase IN ('showmatch','regular','finals_week','unknown')),
    game_number integer CHECK (game_number > 0),
    board_name text,
    board_rule_id uuid REFERENCES rule_versions(id),
    expected_seats integer CHECK (expected_seats BETWEEN 1 AND 64),
    is_extra_game boolean,
    scoring_eligible boolean,
    scoring_period_id uuid REFERENCES scoring_periods(id),
    scope_confirmed boolean NOT NULL DEFAULT false,
    match_status text NOT NULL DEFAULT 'unknown' CHECK (match_status IN ('unknown','completed','abandoned','void','cancelled')),
    winning_faction text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (game_id, revision_no),
    UNIQUE (game_id, id)
);
ALTER TABLE games ADD CONSTRAINT published_revision_belongs_to_game
FOREIGN KEY (id, published_revision_id) REFERENCES game_revisions(game_id,id);
CREATE TABLE game_participants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    revision_id uuid NOT NULL REFERENCES game_revisions(id),
    seat_number integer NOT NULL CHECK (seat_number BETWEEN 1 AND 64),
    player_id uuid REFERENCES players(id),
    nickname_as_broadcast text,
    role_code text,
    opening_faction text,
    settlement_faction text,
    personal_result text NOT NULL DEFAULT 'unknown' CHECK (personal_result IN ('unknown','win','loss','draw','no_result')),
    base_points numeric(8,2),
    adjustments numeric(8,2),
    official_points numeric(8,2),
    proposed jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (revision_id, seat_number),
    UNIQUE (revision_id, player_id),
    UNIQUE (id, revision_id)
);
CREATE TABLE evidence_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    revision_id uuid NOT NULL REFERENCES game_revisions(id),
    participant_id uuid,
    source_id uuid NOT NULL REFERENCES sources(id),
    artifact_id uuid REFERENCES artifacts(id),
    field_key text NOT NULL,
    locator text NOT NULL CHECK (length(trim(locator)) > 0),
    start_seconds numeric(12,3) CHECK (start_seconds >= 0),
    end_seconds numeric(12,3),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    FOREIGN KEY (artifact_id,source_id) REFERENCES artifacts(id,source_id),
    FOREIGN KEY (participant_id,revision_id) REFERENCES game_participants(id,revision_id),
    CHECK (end_seconds IS NULL OR (start_seconds IS NOT NULL AND end_seconds >= start_seconds))
);
CREATE TABLE reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    revision_id uuid NOT NULL REFERENCES game_revisions(id),
    reviewer text NOT NULL CHECK (length(trim(reviewer)) > 0),
    review_type text NOT NULL CHECK (review_type IN ('manual_single','manual_independent')),
    decision text NOT NULL CHECK (decision IN ('approved','rejected')),
    comment text NOT NULL,
    reviewed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE publication_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id uuid NOT NULL REFERENCES games(id),
    revision_id uuid NOT NULL REFERENCES game_revisions(id),
    action text NOT NULL CHECK (action IN ('publish','withdraw')),
    actor text NOT NULL CHECK (length(trim(actor)) > 0),
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action text NOT NULL,
    actor text NOT NULL,
    entity_id uuid,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX artifacts_source_idx ON artifacts(source_id);
CREATE INDEX sources_author_idx ON sources(platform,author_id,published_at);
CREATE INDEX revisions_game_idx ON game_revisions(game_id);
CREATE INDEX participants_player_idx ON game_participants(player_id);
CREATE INDEX evidence_revision_idx ON evidence_links(revision_id);

CREATE FUNCTION assert_revision_ready(target uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE r game_revisions%ROWTYPE; rule rule_versions%ROWTYPE; actual_count integer; key text;
BEGIN
    SELECT * INTO STRICT r FROM game_revisions WHERE id=target;
    IF r.event_date IS NULL OR r.phase IS NULL OR r.phase='unknown' OR r.game_number IS NULL
       OR NOT r.scope_confirmed OR r.match_status<>'completed' OR r.expected_seats IS NULL
       OR r.scoring_eligible IS NULL OR r.board_rule_id IS NULL OR NULLIF(trim(r.winning_faction),'') IS NULL THEN
        RAISE EXCEPTION '未完成赛事范围、阶段、规则、人数、结算或计分资格复核';
    END IF;
    SELECT * INTO STRICT rule FROM rule_versions WHERE id=r.board_rule_id;
    IF rule.kind<>'board' OR NOT rule.verified OR
       (rule.definition->>'participant_count')::integer IS DISTINCT FROM r.expected_seats THEN
        RAISE EXCEPTION '板子规则未核验或人数不一致';
    END IF;
    IF rule.season_id IS NOT NULL AND rule.season_id IS DISTINCT FROM (SELECT season_id FROM games WHERE id=r.game_id) THEN
        RAISE EXCEPTION '板子规则不属于该赛季';
    END IF;
    IF r.scoring_eligible AND (r.phase='showmatch' OR r.scoring_period_id IS NULL) THEN
        RAISE EXCEPTION '计分阶段缺失或表演赛错误计分';
    END IF;
    IF r.scoring_period_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM scoring_periods sp JOIN games g ON g.season_id=sp.season_id
        WHERE sp.id=r.scoring_period_id AND g.id=r.game_id AND sp.phase=r.phase
    ) THEN RAISE EXCEPTION '积分阶段与比赛赛季/阶段不一致'; END IF;
    IF r.scoring_eligible AND NOT EXISTS (
        SELECT 1 FROM scoring_periods sp JOIN rule_versions sr ON sr.id=sp.rule_version_id
        JOIN games g ON g.id=r.game_id
        WHERE sp.id=r.scoring_period_id AND sr.kind='scoring' AND sr.verified
          AND (sr.season_id IS NULL OR sr.season_id=g.season_id)
    ) THEN RAISE EXCEPTION '计分资格需要对应赛季已核验的计分规则'; END IF;
    SELECT count(*) INTO actual_count FROM game_participants WHERE revision_id=target;
    IF actual_count<>r.expected_seats OR EXISTS (
        SELECT 1 FROM game_participants p WHERE p.revision_id=target AND
        (p.seat_number>r.expected_seats OR p.player_id IS NULL OR NULLIF(trim(p.nickname_as_broadcast),'') IS NULL
         OR NULLIF(trim(p.role_code),'') IS NULL OR NULLIF(trim(p.opening_faction),'') IS NULL
         OR p.opening_faction='unknown' OR p.personal_result='unknown')
    ) THEN RAISE EXCEPTION '座次、选手、角色、阵营或个人结果未完整核验'; END IF;
    IF rule.definition->>'result_mode' NOT IN ('faction','explicit') OR rule.definition->>'result_mode' IS NULL THEN
        RAISE EXCEPTION '板子未定义已核验的结算方式';
    END IF;
    IF rule.definition->>'result_mode'='faction' AND EXISTS (
        SELECT 1 FROM game_participants p WHERE p.revision_id=target AND
        (p.settlement_faction IS NULL OR p.settlement_faction='unknown' OR
         p.personal_result IS DISTINCT FROM CASE WHEN p.settlement_faction=r.winning_faction THEN 'win' ELSE 'loss' END)
    ) THEN RAISE EXCEPTION '个人结果与结算阵营/胜方矛盾'; END IF;
    IF jsonb_typeof(rule.definition->'role_counts')<>'object' OR rule.definition->'role_counts' IS NULL THEN
        RAISE EXCEPTION '缺少已核验的板子角色配额';
    END IF;
    IF (SELECT COALESCE(sum(value::integer),0) FROM jsonb_each_text(rule.definition->'role_counts'))<>r.expected_seats
       OR EXISTS (
           SELECT 1 FROM jsonb_each_text(rule.definition->'role_counts') rc
           WHERE (SELECT count(*) FROM game_participants p WHERE p.revision_id=target AND p.role_code=rc.key)<>rc.value::integer
       ) OR EXISTS (
           SELECT 1 FROM game_participants p WHERE p.revision_id=target AND NOT (rule.definition->'role_counts' ? p.role_code)
       ) THEN RAISE EXCEPTION '角色数量与板子配置不一致'; END IF;
    FOREACH key IN ARRAY ARRAY['scope','roster','roles','results','rules','scoring'] LOOP
        IF NOT EXISTS(SELECT 1 FROM evidence_links WHERE revision_id=target AND field_key=key) THEN
            RAISE EXCEPTION '缺少 % 的证据',key;
        END IF;
    END LOOP;
END;
$$;

CREATE FUNCTION guard_revision_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.review_state IS DISTINCT FROM OLD.review_state AND
       (to_jsonb(NEW)-'review_state') IS DISTINCT FROM (to_jsonb(OLD)-'review_state') THEN
        RAISE EXCEPTION '保存草稿和提交/批准必须分开，确保审核指定快照';
    END IF;
    IF OLD.review_state<>'draft' AND
       (to_jsonb(NEW)-'review_state') IS DISTINCT FROM (to_jsonb(OLD)-'review_state') THEN
        RAISE EXCEPTION '已提交版本不能原地修改事实；请创建后继草稿';
    END IF;
    IF NEW.review_state IS DISTINCT FROM OLD.review_state THEN
        IF NOT ((OLD.review_state='draft' AND NEW.review_state='submitted') OR
                (OLD.review_state='submitted' AND NEW.review_state IN ('approved','rejected'))) THEN
            RAISE EXCEPTION '非法审核状态变化';
        END IF;
        IF NEW.review_state IN ('submitted','approved') THEN
            PERFORM assert_revision_ready(OLD.id);
        END IF;
        IF NEW.review_state='approved' AND NOT EXISTS (
            SELECT 1 FROM reviews WHERE revision_id=OLD.id AND decision='approved'
        ) THEN RAISE EXCEPTION '缺少人工审核记录'; END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER revision_change_guard BEFORE UPDATE ON game_revisions
FOR EACH ROW EXECUTE FUNCTION guard_revision_change();

CREATE FUNCTION guard_revision_origin() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.from_extraction_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM extraction_runs e JOIN games g ON g.primary_source_id=e.source_id
        WHERE e.id=NEW.from_extraction_id AND g.id=NEW.game_id
    ) THEN RAISE EXCEPTION '提取记录不属于本场主来源'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER revision_origin_guard BEFORE INSERT OR UPDATE ON game_revisions
FOR EACH ROW EXECUTE FUNCTION guard_revision_origin();

CREATE FUNCTION guard_verified_rule() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.verified THEN RAISE EXCEPTION '已核验规则不可原地改写或删除，请新增规则版本'; END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;
CREATE TRIGGER verified_rule_guard BEFORE UPDATE OR DELETE ON rule_versions
FOR EACH ROW EXECUTE FUNCTION guard_verified_rule();

CREATE FUNCTION guard_period_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS(SELECT 1 FROM game_revisions WHERE scoring_period_id=OLD.id AND review_state<>'draft') THEN
        RAISE EXCEPTION '已提交事实引用的积分阶段不可原地改写';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;
CREATE TRIGGER period_change_guard BEFORE UPDATE OR DELETE ON scoring_periods
FOR EACH ROW EXECUTE FUNCTION guard_period_change();

CREATE FUNCTION guard_game_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.season_id IS DISTINCT FROM OLD.season_id AND
       EXISTS(SELECT 1 FROM game_revisions WHERE game_id=OLD.id AND review_state<>'draft') THEN
        RAISE EXCEPTION '已有提交版本的比赛不能改写赛季';
    END IF;
    IF NEW.primary_source_id IS DISTINCT FROM OLD.primary_source_id AND
       EXISTS(SELECT 1 FROM game_revisions WHERE game_id=OLD.id) THEN
        RAISE EXCEPTION '已有版本的比赛主来源不可改写';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER game_identity_guard BEFORE UPDATE ON games
FOR EACH ROW EXECUTE FUNCTION guard_game_identity();

CREATE FUNCTION guard_child_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target uuid; state text;
BEGIN
    target := CASE WHEN TG_OP='DELETE' THEN OLD.revision_id ELSE NEW.revision_id END;
    IF TG_OP='UPDATE' AND NEW.revision_id<>OLD.revision_id THEN
        RAISE EXCEPTION '事实不能移动到其他版本';
    END IF;
    SELECT review_state INTO STRICT state FROM game_revisions WHERE id=target FOR UPDATE;
    IF state<>'draft' THEN RAISE EXCEPTION '已提交版本的事实和证据不能改动'; END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;
CREATE TRIGGER participant_change_guard BEFORE INSERT OR UPDATE OR DELETE ON game_participants
FOR EACH ROW EXECUTE FUNCTION guard_child_change();
CREATE TRIGGER evidence_change_guard BEFORE INSERT OR UPDATE OR DELETE ON evidence_links
FOR EACH ROW EXECUTE FUNCTION guard_child_change();

CREATE FUNCTION guard_publication() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE state text;
BEGIN
    IF NEW.published_revision_id IS NOT NULL AND
       (TG_OP='INSERT' OR NEW.published_revision_id IS DISTINCT FROM OLD.published_revision_id) THEN
        SELECT review_state INTO STRICT state FROM game_revisions WHERE id=NEW.published_revision_id FOR UPDATE;
        IF state<>'approved' THEN RAISE EXCEPTION '只能发布已批准版本'; END IF;
        PERFORM assert_revision_ready(NEW.published_revision_id);
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER publication_guard BEFORE INSERT OR UPDATE ON games
FOR EACH ROW EXECUTE FUNCTION guard_publication();

CREATE VIEW published_games AS
SELECT g.slug,g.season_id,g.primary_source_id,r.*
FROM games g JOIN game_revisions r ON r.id=g.published_revision_id;
CREATE VIEW player_basic_stats AS
SELECT p.player_id, count(*) AS appearances,
       count(*) FILTER (WHERE p.personal_result='win') AS wins,
       count(*) FILTER (WHERE p.personal_result='loss') AS losses,
       count(*) FILTER (WHERE p.personal_result='draw') AS draws,
       count(*) FILTER (WHERE p.personal_result='no_result') AS no_results,
       count(*) FILTER (WHERE p.personal_result IN ('win','loss')) AS decided_games,
       count(*) FILTER (WHERE p.personal_result='win')::numeric /
       NULLIF(count(*) FILTER (WHERE p.personal_result IN ('win','loss')),0) AS win_rate
FROM published_games g JOIN game_participants p ON p.revision_id=g.id
WHERE g.scope_confirmed AND g.scoring_eligible AND g.phase IN ('regular','finals_week') AND g.match_status='completed'
GROUP BY p.player_id;
