"""
workers/report_worker.py — kicks off bot_sheet_sync.py as a subprocess for
a given user. Extracted from the /api/weekly_report route in app.py;
behavior unchanged (fire-and-forget subprocess, same as before).
"""

import subprocess


def run_weekly_report_for_user(user_id):
    subprocess.Popen(["python", "bot_sheet_sync.py", str(user_id)])
