"""
One-time migration: normalize ALL solved_date values in DB to DD-MM-YYYY.

Usage:
  python fix_date_formats.py          # dry-run (preview only, no changes)
  python fix_date_formats.py --apply  # actually update the DB
"""
import os
import sys
import psycopg2
from datetime import datetime

DRY_RUN = "--apply" not in sys.argv

DATABASE_URL = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

cursor.execute("SELECT id, solved_date FROM submissions WHERE solved_date IS NOT NULL AND solved_date != ''")
rows = cursor.fetchall()

fixed = 0
already_correct = 0
unrecognized = []

for row_id, raw_date in rows:
    normalized = None

    # YYYY-MM-DD → needs fixing
    try:
        normalized = datetime.strptime(raw_date.strip(), "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        pass

    # DD-MM-YYYY → already correct
    if normalized is None:
        try:
            datetime.strptime(raw_date.strip(), "%d-%m-%Y")
            already_correct += 1
            continue
        except ValueError:
            pass

    if normalized is None:
        unrecognized.append((row_id, raw_date))
        continue

    if DRY_RUN:
        print(f"  [DRY RUN] id={row_id}: '{raw_date}' → '{normalized}'")
    else:
        cursor.execute("UPDATE submissions SET solved_date = %s WHERE id = %s", (normalized, row_id))
    fixed += 1

if DRY_RUN:
    print(f"\n[DRY RUN] Would fix: {fixed} rows | Already correct: {already_correct} | Unrecognized: {len(unrecognized)}")
    print("No changes made. Run with --apply to actually update.")
else:
    conn.commit()
    print(f"Done. Fixed: {fixed} | Already correct: {already_correct} | Unrecognized: {len(unrecognized)}")

if unrecognized:
    print(f"\nUnrecognized formats (not touched):")
    for rid, rd in unrecognized[:10]:
        print(f"  id={rid}: '{rd}'")

conn.close()
