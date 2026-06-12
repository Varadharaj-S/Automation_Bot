"""
fix_db.py — Run this once to add new columns to your existing database.
Usage: python fix_db.py
"""
import sqlite3

conn = sqlite3.connect("dsa_tracker.db")
cur  = conn.cursor()

cur.execute("PRAGMA table_info(users)")
columns = [col[1] for col in cur.fetchall()]

added = []

if "lc_session_cookie" not in columns:
    cur.execute("ALTER TABLE users ADD COLUMN lc_session_cookie TEXT DEFAULT ''")
    added.append("lc_session_cookie")

if "lc_csrf_token" not in columns:
    cur.execute("ALTER TABLE users ADD COLUMN lc_csrf_token TEXT DEFAULT ''")
    added.append("lc_csrf_token")

if "lc_password" not in columns:
    cur.execute("ALTER TABLE users ADD COLUMN lc_password TEXT DEFAULT ''")
    added.append("lc_password")

if "enabled_platforms" not in columns:
    cur.execute("ALTER TABLE users ADD COLUMN enabled_platforms TEXT DEFAULT '[\"Codeforces\",\"LeetCode\",\"AtCoder\"]'")
    added.append("enabled_platforms")

conn.commit()
conn.close()

if added:
    print(f"✅ Added columns: {', '.join(added)}")
else:
    print("⚡ All columns already exist — nothing to do.")
