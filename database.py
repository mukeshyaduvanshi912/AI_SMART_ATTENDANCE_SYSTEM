"""
database.py
------------
Handles all SQLite database operations for the Face Recognition
Attendance System: user accounts (for login), registered people
(students/employees), attendance logs, and RFID card links.
"""

import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash

DB_PATH = "attendance.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't already exist, and auto-migrate older
    databases (missing check_in/check_out/rfid_tag columns) in place."""
    conn = get_connection()
    cur = conn.cursor()

    # Admin / operator login accounts (people who use the dashboard)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # People registered for face recognition (students / employees)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_code TEXT UNIQUE NOT NULL,   -- e.g. roll no / employee id
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Attendance records
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            check_in TEXT,
            FOREIGN KEY (person_id) REFERENCES people (id),
            UNIQUE(person_id, date)  -- one attendance row per person per day
        )
    """)

    # Simple key/value settings table (e.g. late-arrival cutoff time)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    conn.commit()

    # Self-migration: older databases may have a "time" column instead of
    # "check_in", and may be missing "check_out" entirely. Detect and fix.
    cur.execute("PRAGMA table_info(attendance)")
    attendance_columns = {row["name"] for row in cur.fetchall()}

    if "check_in" not in attendance_columns and "time" in attendance_columns:
        cur.execute("ALTER TABLE attendance RENAME COLUMN time TO check_in")
        conn.commit()
        cur.execute("PRAGMA table_info(attendance)")
        attendance_columns = {row["name"] for row in cur.fetchall()}
    elif "check_in" not in attendance_columns:
        cur.execute("ALTER TABLE attendance ADD COLUMN check_in TEXT")
        conn.commit()

    if "check_out" not in attendance_columns and "time_out" in attendance_columns:
        cur.execute("ALTER TABLE attendance RENAME COLUMN time_out TO check_out")
        conn.commit()
    elif "check_out" not in attendance_columns:
        cur.execute("ALTER TABLE attendance ADD COLUMN check_out TEXT")
        conn.commit()

    # Self-migration: add rfid_tag column so a person can optionally also
    # be checked in/out with an RFID card, alongside face recognition.
    cur.execute("PRAGMA table_info(people)")
    people_columns = {row["name"] for row in cur.fetchall()}
    if "rfid_tag" not in people_columns:
        cur.execute("ALTER TABLE people ADD COLUMN rfid_tag TEXT")
        conn.commit()
        # Enforce one card per person (allows multiple NULLs = unlinked)
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_people_rfid "
            "ON people(rfid_tag) WHERE rfid_tag IS NOT NULL"
        )
        conn.commit()

    # Default settings
    cur.execute("SELECT COUNT(*) as c FROM settings WHERE key = 'late_cutoff_time'")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("late_cutoff_time", "09:30"),
        )
        conn.commit()

    # Create a default admin account if none exists yet
    cur.execute("SELECT COUNT(*) as c FROM accounts")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO accounts (username, password_hash, created_at) VALUES (?, ?, ?)",
            ("admin", generate_password_hash("admin123"), datetime.now().isoformat()),
        )
        conn.commit()
        print("Default admin account created -> username: admin | password: admin123")

    conn.close()


# ---------------- People (registered faces) ----------------

def add_person(person_code, name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO people (person_code, name, created_at) VALUES (?, ?, ?)",
        (person_code, name, datetime.now().isoformat()),
    )
    conn.commit()
    person_id = cur.lastrowid
    conn.close()
    return person_id


def get_person_by_code(person_code):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM people WHERE person_code = ?", (person_code,))
    row = cur.fetchone()
    conn.close()
    return row


def get_person_by_id(person_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM people WHERE id = ?", (person_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_person_by_rfid(rfid_tag):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM people WHERE rfid_tag = ?", (rfid_tag,))
    row = cur.fetchone()
    conn.close()
    return row


def get_all_people():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM people ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    return rows


def update_person(person_id, name):
    """Update a person's display name (person_code is kept immutable
    since it's tied to their dataset folder on disk)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE people SET name = ? WHERE id = ?", (name, person_id))
    conn.commit()
    conn.close()


def assign_rfid(person_id, rfid_tag):
    """Links an RFID card to a person. Returns:
      "ok"            - linked successfully
      "already_taken" - this card is already linked to a different person
    Passing an empty rfid_tag clears the link for this person.
    """
    conn = get_connection()
    cur = conn.cursor()

    rfid_tag = rfid_tag.strip() or None

    if rfid_tag is not None:
        cur.execute(
            "SELECT id FROM people WHERE rfid_tag = ? AND id != ?",
            (rfid_tag, person_id),
        )
        if cur.fetchone():
            conn.close()
            return "already_taken"

    cur.execute("UPDATE people SET rfid_tag = ? WHERE id = ?", (rfid_tag, person_id))
    conn.commit()
    conn.close()
    return "ok"


def delete_person(person_id):
    """Delete a person and their attendance history from the database.
    Does NOT delete their dataset/ images or retrain the model — call
    that separately if you also want them removed from recognition."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM attendance WHERE person_id = ?", (person_id,))
    cur.execute("DELETE FROM people WHERE id = ?", (person_id,))
    conn.commit()
    conn.close()


# ---------------- Attendance ----------------

def mark_attendance(person_id):
    """Marks check-in if the person hasn't checked in today, or check-out
    if they've checked in but not out yet. Returns one of:
      "checked_in"   - first scan of the day, arrival time recorded
      "checked_out"  - second scan of the day, departure time recorded
      "already_done" - both check-in and check-out already recorded today
    """
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M:%S")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM attendance WHERE person_id = ? AND date = ?",
        (person_id, today),
    )
    row = cur.fetchone()

    if row is None:
        cur.execute(
            "INSERT INTO attendance (person_id, date, check_in) VALUES (?, ?, ?)",
            (person_id, today, now_time),
        )
        conn.commit()
        result = "checked_in"
    elif row["check_out"] is None:
        cur.execute(
            "UPDATE attendance SET check_out = ? WHERE id = ?",
            (now_time, row["id"]),
        )
        conn.commit()
        result = "checked_out"
    else:
        result = "already_done"

    conn.close()
    return result


def get_attendance_by_date(date_str=None):
    """Return attendance rows joined with person info for a given date
    (defaults to today)."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, p.person_code, p.name, a.date, a.check_in, a.check_out
        FROM attendance a
        JOIN people p ON a.person_id = p.id
        WHERE a.date = ?
        ORDER BY a.check_in
    """, (date_str,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_attendance():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, p.person_code, p.name, a.date, a.check_in, a.check_out
        FROM attendance a
        JOIN people p ON a.person_id = p.id
        ORDER BY a.date DESC, a.check_in DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_attendance_counts_last_n_days(n=7):
    """Returns a list of (date_str, count) for the last n days, oldest first,
    including days with zero attendance."""
    from datetime import timedelta
    today = datetime.now().date()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n - 1, -1, -1)]

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, COUNT(*) as c FROM attendance
        WHERE date >= ?
        GROUP BY date
    """, (dates[0],))
    counts = {row["date"]: row["c"] for row in cur.fetchall()}
    conn.close()

    return [(d, counts.get(d, 0)) for d in dates]


# ---------------- Settings ----------------

def get_setting(key, default=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, value))
    conn.commit()
    conn.close()


# ---------------- Accounts (dashboard login) ----------------

def get_account_by_username(username):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM accounts WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return row


if __name__ == "__main__":
    init_db()
    print("Database initialized at", DB_PATH)