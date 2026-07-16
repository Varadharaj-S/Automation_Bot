-- =============================================================================
-- DSA Tracker v4 — Contest Tracker, Migration 0005: automatic result sync
-- =============================================================================
-- Additive and idempotent, same pattern as 0001-0004. Adds what
-- contest/contest_sync.py needs to detect ended contests and sync them
-- exactly once, with retries and an audit trail (Phase 6 audit, Issues 1,
-- 7, 8).
-- =============================================================================

-- Issue 1: how the scheduler tells "already synced" from "needs syncing".
ALTER TABLE contest_events ADD COLUMN IF NOT EXISTS synced BOOLEAN DEFAULT FALSE;

-- Issue 8: dedupe contests by URL too, not just contest_code (a typo'd
-- code shouldn't let the same contest get created twice). Partial index —
-- ignores blank URLs, since contest_url is optional on the create form.
ALTER TABLE contest_events ADD COLUMN IF NOT EXISTS contest_url TEXT DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_contest_events_url_unique
    ON contest_events(contest_url) WHERE contest_url IS NOT NULL AND contest_url != '';

-- Issue 7: retry bookkeeping. sync_claimed_at is a short-lived lease so two
-- scheduler ticks (or a tick racing an admin's manual "Sync Now") never
-- process the same contest twice; contest_sync.py reclaims leases older
-- than 10 minutes in case a worker died mid-sync.
ALTER TABLE contest_events ADD COLUMN IF NOT EXISTS sync_attempts    INTEGER DEFAULT 0;
ALTER TABLE contest_events ADD COLUMN IF NOT EXISTS sync_claimed_at  TIMESTAMPTZ;
ALTER TABLE contest_events ADD COLUMN IF NOT EXISTS last_sync_error  TEXT DEFAULT '';

-- Issue 7: contest_sync_log — one row per sync attempt, so a failure is
-- visible (and debuggable) instead of a contest just silently staying
-- un-synced forever.
CREATE TABLE IF NOT EXISTS contest_sync_log (
    id           SERIAL PRIMARY KEY,
    contest_id   INTEGER     NOT NULL REFERENCES contest_events(id) ON DELETE CASCADE,
    status       TEXT        NOT NULL,   -- 'running' | 'success' | 'failed'
    retry_count  INTEGER     DEFAULT 0,
    last_error   TEXT        DEFAULT '',
    message      TEXT        DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_contest_sync_log_contest ON contest_sync_log(contest_id);
