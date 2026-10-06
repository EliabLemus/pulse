-- Read-only Compass sprint-task snapshots for the credentialless DSU daemon.
-- A host-invoked ephemeral worker owns the Compass credential and refreshes
-- this cache; the long-lived app only reads fresh rows before sending DMs.

CREATE TABLE IF NOT EXISTS compass_task_snapshots (
    team_id    TEXT NOT NULL REFERENCES installations(team_id) ON DELETE CASCADE,
    email      TEXT NOT NULL,
    tasks      JSONB NOT NULL DEFAULT '[]'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (team_id, email)
);

CREATE INDEX IF NOT EXISTS idx_compass_task_snapshots_fresh
    ON compass_task_snapshots (team_id, fetched_at);
