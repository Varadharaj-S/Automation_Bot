"""
services/incremental_sync/sheet_ops.py — append-only Sheet writes with
correct date-block merging.

Reuses normal_sync.get_sheet() as-is for opening/creating the per-user tab
(same header: DATE | PROGRAM TITLE | LINK | DIFFICULTY | PLATFORM | TOPIC |
COUNT) — that's pure infrastructure, not the sync logic itself, so reusing
it isn't "modifying normal_sync.py".

Bug fixed here vs. the current production merge (normal_sync.py's inline
regroup step): today, every row's COUNT cell is hardcoded to the literal
value 1, and merging cells A/G for a date block just makes that 1 the
visible value for the whole block — so a date with 3 problems solved shows
"1", not "3". This module writes the real per-block count into the
top-left cell before merging.

Sheet dates are kept in the SAME "%Y-%m-%d" format the sheet already uses
(this is independent of the DB's solved_date format, which is "%d-%m-%Y" —
see fetchers.py's module docstring on why those two are intentionally
different formats for different consumers).
"""

from datetime import datetime

from normal_sync import get_sheet  # reused as-is; not modified

DATE_COL = 1   # A
COUNT_COL = 7  # G


def get_or_create_user_sheet(username):
    return get_sheet(username)


def _sheet_date(item):
    return datetime.fromtimestamp(item["solved_epoch"]).strftime("%Y-%m-%d")


def _to_sheet_row(item):
    return [
        _sheet_date(item),
        f'=HYPERLINK("{item["problem_url"]}", "{item["problem_name"]}")',
        item.get("submission_url", item["problem_url"]),
        item["difficulty"],
        item["platform"],
        item["tags"],
        1,  # per-row placeholder; the block's top row gets overwritten with the real count below
    ]


def _effective_dates(all_values):
    """Returns a list index-aligned with all_values giving each row's
    *effective* date — the row's own DATE cell if non-blank, otherwise the
    nearest non-blank date above it.

    This exists because once a date-block is merged, Google Sheets only
    keeps the DATE value in the block's top-left cell — get_all_values()
    reads back '' for every other row in that merged block, even though on
    screen the whole block still visually shows that date. Without this,
    any check that compares a row's raw all_values[...][0] against a date
    string breaks as soon as that row is inside an already-merged block
    (see bottom_date / _find_block_start below — this was the bug behind
    same-day rows splitting into two blocks on a second auto-sync run the
    same day, instead of extending the first block)."""
    effective = [""]  # index 0 (header) unused for date comparisons
    current = ""
    for row in all_values[1:]:
        if row[0].strip():
            current = row[0].strip()
        effective.append(current)
    return effective


def _find_block_start(effective_dates, date_str):
    """Scans upward from the last row while the *effective* date matches
    (see _effective_dates); returns the 1-based sheet row number of the
    topmost row of that trailing block. effective_dates is index-aligned
    with all_values, so effective_dates[i] is sheet row (i+1)."""
    idx = len(effective_dates) - 1  # 0-based index of the last row
    while idx > 1 and effective_dates[idx - 1] == date_str:
        idx -= 1
    return idx + 1  # convert to 1-based sheet row number


def _remerge_block(sheet, start_row, end_row):
    count = end_row - start_row + 1
    a_range = f"A{start_row}:A{end_row}"
    g_range = f"G{start_row}:G{end_row}"

    # Write the real count into the block's top row BEFORE merging — a
    # merge keeps the top-left cell's value and hides the rest.
    sheet.update_cell(start_row, COUNT_COL, count)

    if count > 1:
        # Unmerge first: re-merging a range that overlaps an existing merge
        # errors on a real sheet. try/except covers "wasn't merged yet"
        # (brand new block) without a separate "is this already merged?"
        # round-trip call.
        for rng in (a_range, g_range):
            try:
                sheet.unmerge_cells(rng)
            except Exception:
                pass
        sheet.merge_cells(a_range)
        sheet.merge_cells(g_range)


def append_merged(sheet, items):
    """
    items: list of dicts from the fetchers (any mix of platforms/dates).
    Groups by date, processes oldest-to-newest, and for each date:
      - if it matches the sheet's current bottom-most date block, extends
        that block and updates its count
      - otherwise appends a new block at the bottom

    Returns {"appended": N, "blocks_extended": N, "blocks_created": N}.
    """
    stats = {"appended": 0, "blocks_extended": 0, "blocks_created": 0}
    if not items:
        return stats

    groups = {}
    for it in items:
        groups.setdefault(_sheet_date(it), []).append(it)

    for date_str in sorted(groups.keys()):  # "%Y-%m-%d" sorts chronologically as strings
        date_items = groups[date_str]
        all_values = sheet.get_all_values()
        has_data_rows = len(all_values) > 1
        effective_dates = _effective_dates(all_values)
        bottom_date = effective_dates[-1] if has_data_rows else None

        rows_to_append = [_to_sheet_row(it) for it in date_items]
        pre_append_row_count = len(all_values)

        if bottom_date == date_str:
            block_start = _find_block_start(effective_dates, date_str)
            sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
            new_last_row = pre_append_row_count + len(rows_to_append)
            _remerge_block(sheet, block_start, new_last_row)
            stats["blocks_extended"] += 1
        else:
            sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
            block_start = pre_append_row_count + 1
            new_last_row = pre_append_row_count + len(rows_to_append)
            _remerge_block(sheet, block_start, new_last_row)
            stats["blocks_created"] += 1

        stats["appended"] += len(rows_to_append)

    return stats
