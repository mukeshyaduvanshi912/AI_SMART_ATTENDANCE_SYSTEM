"""
app.py
-------
Main Flask application for the AI Smart Attendance System.

Routes:
    /login          - login page for dashboard access
    /logout         - log out
    /               - home / index page
    /register       - register a new person + capture face samples
    /train          - (re)train the recognition model
    /recognize      - run live recognition & mark attendance
    /attendance     - view today's attendance
    /dashboard      - overview: people count, attendance history
    /people         - manage registered people (rename, delete, link RFID, enroll voice)
    /rfid           - RFID card scan page
    /settings       - configure late-arrival cutoff

NOTE: This app opens the machine's LOCAL webcam (the one attached to the
server/computer running Flask) via OpenCV — it is designed to run on a
single local machine (e.g. a front-desk kiosk PC), not to access a
remote visitor's browser camera. For browser-camera capture you would
additionally need getUserMedia + image upload endpoints.
"""

import csv
import io
import shutil
import os

from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify, Response
)
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import check_password_hash

import database as db
import voice_auth
from capture_faces import capture_faces
from train_model import train_model
from recognize import run_recognition, check_duplicate_face
from voice_assistant import run_voice_attendance
from rfid_reader import process_rfid_scan
from enroll import enroll_voice

app = Flask(__name__)
app.secret_key = "change-this-secret-key-in-production"

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class Account(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.username = row["username"]


@login_manager.user_loader
def load_user(user_id):
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM accounts WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return Account(row) if row else None


def annotate_late(records):
    """Attach an `is_late` flag to each attendance record dict based on
    the configured late_cutoff_time setting (default 09:30).
    Late is judged against check_in time; records with no check_in yet
    are not marked late."""
    cutoff = db.get_setting("late_cutoff_time", "09:30")
    enriched = []
    for r in records:
        r = dict(r)
        r["is_late"] = bool(r.get("check_in")) and r["check_in"] > f"{cutoff}:00"
        enriched.append(r)
    return enriched


# ---------------- Auth ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        account_row = db.get_account_by_username(username)
        if account_row and check_password_hash(account_row["password_hash"], password):
            login_user(Account(account_row))
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ---------------- Core pages ----------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
@login_required
def register():
    if request.method == "POST":
        person_code = request.form.get("person_code", "").strip()
        name = request.form.get("name", "").strip()

        if not person_code or not name:
            flash("Person code and name are required.", "error")
            return redirect(url_for("register"))

        if db.get_person_by_code(person_code):
            flash("A person with that code is already registered.", "error")
            return redirect(url_for("register"))

        try:
            # Opens the local webcam and captures ~100 face samples
            num_captured = capture_faces(person_code, name)
            folder = os.path.join("dataset", f"{person_code}_{name}")

            # Check this face isn't already registered under a different ID
            duplicate_code = check_duplicate_face(person_code, folder)
            if duplicate_code:
                existing = db.get_person_by_code(duplicate_code)
                shutil.rmtree(folder, ignore_errors=True)
                existing_label = existing["name"] if existing else duplicate_code
                flash(f"This face is already registered as {existing_label} "
                      f"({duplicate_code}). Registration cancelled — each person "
                      f"can only be registered once.", "error")
                return redirect(url_for("register"))

            db.add_person(person_code, name)
            flash(f"Captured {num_captured} images for {name}. "
                  f"Now click 'Train Model' before recognizing.", "success")
        except Exception as e:
            flash(f"Error capturing faces: {e}", "error")

        return redirect(url_for("register"))

    return render_template("register.html")


@app.route("/train", methods=["POST"])
@login_required
def train():
    try:
        train_model()
        flash("Model trained successfully.", "success")
    except Exception as e:
        flash(f"Training failed: {e}", "error")
    return redirect(url_for("dashboard"))


@app.route("/recognize", methods=["GET", "POST"])
@login_required
def recognize():
    marked = []
    if request.method == "POST":
        try:
            marked = run_recognition()
            flash(f"Recognition session ended. Marked {len(marked)} people present.", "success")
        except Exception as e:
            flash(f"Recognition failed: {e}", "error")
    records = annotate_late(db.get_attendance_by_date())
    return render_template("attendance.html", marked=marked, records=records)


@app.route("/attendance")
@login_required
def attendance():
    date_filter = request.args.get("date")
    records = db.get_attendance_by_date(date_filter) if date_filter else db.get_all_attendance()
    records = annotate_late(records)
    return render_template("attendance.html", records=records, marked=[], date_filter=date_filter or "")


@app.route("/voice-attendance", methods=["POST"])
@login_required
def voice_attendance():
    try:
        success, message = run_voice_attendance()
        flash(message, "success" if success else "error")
    except Exception as e:
        flash(f"Voice attendance failed: {e}", "error")

    records = annotate_late(db.get_attendance_by_date())
    return render_template("attendance.html", marked=[], records=records, date_filter="")


@app.route("/attendance/export")
@login_required
def export_attendance_csv():
    """Downloads all attendance records (or a filtered date) as a CSV file."""
    date_filter = request.args.get("date")
    records = db.get_attendance_by_date(date_filter) if date_filter else db.get_all_attendance()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Person Code", "Name", "Date", "Arrival", "Departure"])
    for r in records:
        writer.writerow([
            r["person_code"], r["name"], r["date"],
            r["check_in"] or "", r["check_out"] or ""
        ])

    filename = f"attendance_{date_filter or 'all'}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/dashboard")
@login_required
def dashboard():
    people = db.get_all_people()
    todays_attendance = annotate_late(db.get_attendance_by_date())
    trend = db.get_attendance_counts_last_n_days(7)
    return render_template(
        "dashboard.html",
        people_count=len(people),
        people=people,
        todays_attendance=todays_attendance,
        trend_labels=[d for d, _ in trend],
        trend_values=[c for _, c in trend],
        late_cutoff=db.get_setting("late_cutoff_time", "09:30"),
    )


@app.route("/people")
@login_required
def people():
    return render_template("people.html", people=db.get_all_people())


@app.route("/people/<int:person_id>/edit", methods=["POST"])
@login_required
def edit_person(person_id):
    new_name = request.form.get("name", "").strip()
    if not new_name:
        flash("Name cannot be empty.", "error")
    else:
        db.update_person(person_id, new_name)
        flash("Name updated.", "success")
    return redirect(url_for("people"))


@app.route("/people/<int:person_id>/delete", methods=["POST"])
@login_required
def delete_person(person_id):
    person = db.get_person_by_id(person_id)
    if not person:
        flash("Person not found.", "error")
        return redirect(url_for("people"))

    # Remove their captured face images too, so retraining excludes them
    folder = os.path.join("dataset", f"{person['person_code']}_{person['name']}")
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)

    # Remove their voiceprint too, if one was enrolled
    voice_auth.delete_voiceprint(person["person_code"])

    db.delete_person(person_id)
    flash(f"Removed {person['name']}. Click 'Train Model' to update the recognizer.", "success")
    return redirect(url_for("people"))


@app.route("/people/<int:person_id>/assign-rfid", methods=["POST"])
@login_required
def assign_rfid(person_id):
    rfid_tag = request.form.get("rfid_tag", "").strip()
    person = db.get_person_by_id(person_id)
    if not person:
        flash("Person not found.", "error")
        return redirect(url_for("people"))

    result = db.assign_rfid(person_id, rfid_tag)
    if result == "already_taken":
        flash("That card is already linked to a different person.", "error")
    elif rfid_tag:
        flash(f"Linked card to {person['name']}.", "success")
    else:
        flash(f"Removed card link for {person['name']}.", "success")

    return redirect(url_for("people"))


@app.route("/people/<int:person_id>/enroll-voice", methods=["POST"])
@login_required
def enroll_voice_route(person_id):
    person = db.get_person_by_id(person_id)
    if not person:
        flash("Person not found.", "error")
        return redirect(url_for("people"))

    try:
        count = enroll_voice(person["person_code"])
        flash(f"Voiceprint saved for {person['name']} ({count} samples recorded). "
              f"Voice attendance will now verify it's actually them speaking.", "success")
    except Exception as e:
        flash(f"Voice enrollment failed: {e}", "error")

    return redirect(url_for("people"))


@app.route("/rfid")
@login_required
def rfid_scan_page():
    return render_template("rfid.html")


@app.route("/rfid/scan", methods=["POST"])
@login_required
def rfid_scan():
    rfid_tag = request.form.get("rfid_tag", "").strip()
    success, message = process_rfid_scan(rfid_tag)
    return jsonify({"success": success, "message": message})


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        cutoff = request.form.get("late_cutoff_time", "").strip()
        db.set_setting("late_cutoff_time", cutoff or "09:30")
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html", late_cutoff=db.get_setting("late_cutoff_time", "09:30"))


# ---------------- JSON API (optional, handy for AJAX/testing) ----------------

@app.route("/api/attendance/today")
@login_required
def api_attendance_today():
    records = db.get_attendance_by_date()
    return jsonify([dict(r) for r in records])


if __name__ == "__main__":
    db.init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)