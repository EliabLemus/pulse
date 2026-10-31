-- Per-user Compass API keys (encrypted at rest) for impersonated comments,
-- plus the submitting user on each queued comment job so the worker can
-- resolve which credential should post it.

CREATE TABLE IF NOT EXISTS compass_user_api_keys (
    user_id       TEXT PRIMARY KEY,
    key_ciphertext TEXT NOT NULL,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active        BOOLEAN NOT NULL DEFAULT TRUE
);

ALTER TABLE compass_comment_jobs ADD COLUMN user_id TEXT;

UPDATE compass_comment_jobs jobs
SET user_id = standups.user_id
FROM standups
WHERE jobs.standup_id = standups.id AND jobs.user_id IS NULL;
