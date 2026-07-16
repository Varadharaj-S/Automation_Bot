-- =============================================================================
-- DSA Tracker v4 — Migration 0007: contest_problems + submissions.submitted_at
-- =============================================================================
-- Additive, idempotent, same pattern as the other migrations in this folder.
--
-- This is the schema half of switching contest result sync from "call the
-- platform's contest-standings API after the contest ends" to "read it
-- straight out of the submissions our own daily bot already collected."
-- See contest/contest_sync.py for the new logic and contest/contest_api.py's
-- module docstring for why the old approach was dropped.
--
-- 1. submissions.submitted_at — a real TIMESTAMP (no timezone, matching
--    contest_events.contest_date/start_time/end_time which are also plain
--    local values with no tz) capturing the exact moment a problem was
--    solved, not just the date. Without this, "was this solve inside the
--    17:10–19:10 contest window" isn't answerable from stored data — the
--    existing solved_date column is date-only. normal_sync.py now writes
--    this column too (existing rows are left NULL; only affects contests
--    synced after this migration + a fresh sync of the relevant students).
--
-- 2. contest_problems — one row per problem in a contest (e.g. ABC466_A,
--    ABC466_B, ...). contest_sync.py intersects each student's submissions
--    in the contest window against this list to get the solved count.
--    problem_code must be stored in the exact same format as
--    submissions.problem_id for that platform:
--      AtCoder:     "abc466_a"   (lowercase, matches the AtCoder task screen name)
--      Codeforces:  "2246-B"     ("{contestId}-{index}")
--      LeetCode:    "two-sum"    (the problem's URL slug)
--    contest_utils.normalize_problem_code() builds this from what an admin
--    types on the Create Contest form (e.g. just "A", "B", "C").
-- =============================================================================

ALTER TABLE submissions ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_sub_user_platform_time
    ON submissions(user_id, platform, submitted_at);

CREATE TABLE IF NOT EXISTS contest_problems (
    id           SERIAL PRIMARY KEY,
    contest_id   INTEGER NOT NULL REFERENCES contest_events(id) ON DELETE CASCADE,
    problem_code TEXT    NOT NULL,   -- matches submissions.problem_id format for this platform
    problem_name TEXT    DEFAULT '', -- whatever the admin typed (e.g. "A"), just for display
    problem_url  TEXT    DEFAULT '',
    UNIQUE (contest_id, problem_code)
);
CREATE INDEX IF NOT EXISTS idx_contest_problems_contest ON contest_problems(contest_id);
