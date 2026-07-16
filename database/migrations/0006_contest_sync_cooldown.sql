-- =============================================================================
-- DSA Tracker v4 — Migration 0006: contest sync retry cooldown
-- =============================================================================
-- Additive, idempotent. Without this, a contest that just failed a sync
-- attempt gets retried on literally the next scheduler tick (every 5 min,
-- or immediately on app restart during dev) — annoying when testing
-- against a contest that's genuinely unreachable (e.g. AtCoder contest
-- requiring sign-in). get_due_contests() now skips a contest for
-- Config.CONTEST_SYNC_INTERVAL_MINUTES after its last attempt.
-- =============================================================================

ALTER TABLE contest_events ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ;
