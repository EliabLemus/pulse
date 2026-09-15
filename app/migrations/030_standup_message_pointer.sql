-- Track where each standup was published so edits update the original
-- message in place instead of posting another thread reply.
ALTER TABLE standups
    ADD COLUMN IF NOT EXISTS message_channel TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS message_ts TEXT NOT NULL DEFAULT '';
