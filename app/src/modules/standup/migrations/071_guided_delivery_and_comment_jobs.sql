-- Durable guided channel delivery and Compass comment queue.
-- The Slack daemon only persists records. A host-invoked ephemeral worker,
-- which alone receives the Keychain credential, claims Compass jobs.

CREATE TABLE IF NOT EXISTS guided_standup_deliveries (
    standup_id    BIGINT PRIMARY KEY REFERENCES standups(id) ON DELETE CASCADE,
    team_id       TEXT NOT NULL REFERENCES installations(team_id) ON DELETE CASCADE,
    user_id       TEXT NOT NULL,
    schedule_id   INTEGER NOT NULL REFERENCES standup_schedules(id) ON DELETE RESTRICT,
    standup_date  DATE NOT NULL,
    channel_id    TEXT NOT NULL,
    channel_text  TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'pending'
                  CHECK (state IN ('pending', 'processing', 'delivered', 'unknown')),
    message_ts    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at    TIMESTAMPTZ,
    delivered_at  TIMESTAMPTZ,
    UNIQUE (team_id, user_id, schedule_id, standup_date)
);

CREATE TABLE IF NOT EXISTS compass_comment_jobs (
    id          BIGSERIAL PRIMARY KEY,
    standup_id  BIGINT NOT NULL REFERENCES standups(id) ON DELETE CASCADE,
    team_id     TEXT NOT NULL REFERENCES installations(team_id) ON DELETE CASCADE,
    ticket_key  TEXT NOT NULL,
    body        TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'pending'
                CHECK (state IN ('pending', 'processing', 'delivered', 'unknown', 'skipped')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at  TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    detail      TEXT,
    UNIQUE (standup_id, ticket_key)
);

CREATE INDEX IF NOT EXISTS idx_compass_comment_jobs_pending
    ON compass_comment_jobs (state, created_at)
    WHERE state = 'pending';
