-- Optional post-start reminder and close-window behavior for a schedule.
-- Empty values preserve upstream behavior.
ALTER TABLE standup_schedules
    ADD COLUMN IF NOT EXISTS pending_reminder_times TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS window_end TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS missing_mention TEXT NOT NULL DEFAULT '';
