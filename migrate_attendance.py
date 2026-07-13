"""
migrate_attendance.py
-----------------------
One-time migration: adds check_in/check_out columns to the attendance
table and copies the old "time" column into check_in.
Run once: python migrate_attendance.py
"""

import sqlite3

DB_PATH = "attendance.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("PRAGMA table_info(attendance)")
columns = [row[1] for row in cur.fetchall()]

if "check_in" not in columns:
    cur.execute("ALTER TABLE attendance ADD COLUMN check_in TEXT")
    print("Added check_in column.")

if "check_out" not in columns:
    cur.execute("ALTER TABLE attendance ADD COLUMN check_out TEXT")
    print("Added check_out column.")

if "time" in columns:
    cur.execute("UPDATE attendance SET check_in = time WHERE check_in IS NULL")
    print("Copied old 'time' values into check_in.")

conn.commit()
conn.close()
print("Migration complete.")