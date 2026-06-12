# fix_dates.py
import sqlite3
from datetime import datetime

conn = sqlite3.connect("dsa_tracker.db")
cursor = conn.cursor()

rows = cursor.execute("SELECT id, solved_date FROM submissions").fetchall()

for r in rows:
    old = r[1]
    try:
        new = datetime.strptime(old, "%d-%m-%Y").strftime("%Y-%m-%d")
        cursor.execute("UPDATE submissions SET solved_date=? WHERE id=?", (new, r[0]))
    except:
        pass

conn.commit()
conn.close()

print("✅ Dates fixed")