-- Persist the exact Block Kit payload alongside the accessible text fallback.
-- Historical deliveries remain text-only when this column is NULL.

ALTER TABLE guided_standup_deliveries
    ADD COLUMN IF NOT EXISTS channel_blocks JSONB;
