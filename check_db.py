import sqlite3

conn = sqlite3.connect("dsa_tracker.db")

cur = conn.cursor()

cur.execute("""
SELECT id, username, lc_imported
FROM users
""")

for row in cur.fetchall():
    print(row)

conn.close()