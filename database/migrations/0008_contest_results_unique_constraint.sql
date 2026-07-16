-- =============================================================================
-- DSA Tracker v4 — Migration 0008: add missing UNIQUE constraint on
-- contest_results(contest_id, user_id)
-- =============================================================================
-- contest/contest_sync.py's sync_one_contest() writes results with:
--
--     INSERT INTO contest_results (contest_id, user_id, ...)
--     VALUES (...)
--     ON CONFLICT (contest_id, user_id) DO UPDATE SET ...
--
-- ...which requires a UNIQUE (or PRIMARY KEY) constraint on exactly
-- (contest_id, user_id) to exist. The live table only has plain
-- (non-unique) indexes on contest_id and user_id separately
-- (idx_contest_results_contest, idx_contest_results_user) — no unique
-- constraint on the pair — so every sync attempt fails with:
--   "there is no unique or exclusion constraint matching the ON CONFLICT
--    specification"
-- and the contest gets stuck retrying forever (see contest_sync.py's
-- MAX_SYNC_ATTEMPTS / cooldown logic).
--
-- This migration:
--   1. Removes any pre-existing duplicate (contest_id, user_id) rows,
--      keeping only the most recently updated one for each pair — safe to
--      run even though no sync has ever successfully written a row here
--      yet, in case any were inserted by hand or by an older code path.
--   2. Adds the UNIQUE constraint contest_sync.py's ON CONFLICT needs.
-- =============================================================================

-- Step 1: de-duplicate first (no-op if there are no duplicates).
DELETE FROM contest_results cr
USING contest_results cr2
WHERE cr.contest_id = cr2.contest_id
  AND cr.user_id = cr2.user_id
  AND cr.id < cr2.id;

-- Step 2: add the constraint contest_sync.py's ON CONFLICT relies on.
ALTER TABLE contest_results
    ADD CONSTRAINT contest_results_contest_id_user_id_key UNIQUE (contest_id, user_id);
