"""
migrate_rfid.py
-----------------
One-time migration: adds the rfid_tag column to the people table.
Run once: python migrate_rfid.py
"""

import sqlite3

DB_PATH = "attendance.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("PRAGMA table_info(people)")
columns = [row[1] for row in cur.fetchall()]

if "rfid_tag" not in columns:
    cur.execute("ALTER TABLE people ADD COLUMN rfid_tag TEXT")
    print("Added rfid_tag column.")
else:
    print("rfid_tag column already exists, nothing to do.")

conn.commit()
conn.close()
print("Migration complete.")