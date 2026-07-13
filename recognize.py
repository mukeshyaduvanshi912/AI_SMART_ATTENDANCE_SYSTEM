"""
recognize.py
-------------
Opens the webcam, recognizes faces using the trained LBPH model,
and marks attendance in the database for recognized people.

Run standalone:
    python recognize.py

Or import run_recognition() from app.py for a web-triggered flow.
"""

import cv2
import os
import json
import time
import database as db
from voice_assistant import speak

TRAINER_FILE = os.path.join("trainer", "trainer.yml")
LABELS_FILE = os.path.join("trainer", "labels.json")
FACE_CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"

CONFIDENCE_THRESHOLD = 70  # LBPH: LOWER distance = more confident match. Tune as needed.
UNKNOWN_ANNOUNCE_COOLDOWN = 5     # seconds between "not recognized" announcements
NO_FACE_ANNOUNCE_COOLDOWN = 8     # seconds between "no face detected" announcements
NO_FACE_ANNOUNCE_AFTER = 4        # seconds of no face before the first announcement


def load_model():
    if not os.path.exists(TRAINER_FILE) or not os.path.exists(LABELS_FILE):
        raise RuntimeError("Model not found. Run train_model.py first.")

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read(TRAINER_FILE)

    with open(LABELS_FILE, "r") as f:
        raw_labels = json.load(f)
    # JSON keys are strings; convert back to int
    label_map = {int(k): v for k, v in raw_labels.items()}

    return recognizer, label_map


def check_duplicate_face(new_person_code, dataset_folder, match_ratio_cutoff=0.5):
    """Checks freshly captured face images against the CURRENTLY TRAINED
    model (i.e. everyone registered before this new person) to catch the
    same person trying to register twice under a different ID.

    Returns the existing person_code they match, or None if:
      - no model has been trained yet (nothing to compare against), or
      - the new images don't consistently match any existing person.

    Note: this only catches duplicates against people who were registered
    and included in the LAST training run. Always click "Train Model"
    after each registration so this check stays effective for the next one.
    """
    try:
        recognizer, label_map = load_model()
    except RuntimeError:
        return None  # first person ever, or model not trained yet - nothing to compare

    if not os.path.isdir(dataset_folder):
        return None

    votes = {}
    total_checked = 0

    for img_name in os.listdir(dataset_folder):
        img_path = os.path.join(dataset_folder, img_name)
        face_img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        if face_img is None:
            continue
        total_checked += 1

        label_id, confidence = recognizer.predict(face_img)
        if confidence < CONFIDENCE_THRESHOLD and label_id in label_map:
            existing_code = label_map[label_id]["person_code"]
            if existing_code != new_person_code:
                votes[existing_code] = votes.get(existing_code, 0) + 1

    if not votes or total_checked == 0:
        return None

    best_code, best_votes = max(votes.items(), key=lambda kv: kv[1])
    if (best_votes / total_checked) >= match_ratio_cutoff:
        return best_code

    return None


def run_recognition(camera_index=0, show_window=True):
    """Runs live recognition. Returns a list of (person_code, name) marked present
    during this session."""

    recognizer, label_map = load_model()
    face_detector = cv2.CascadeClassifier(FACE_CASCADE_PATH)
    cam = cv2.VideoCapture(camera_index)

    if not cam.isOpened():
        raise RuntimeError("Could not open webcam.")

    marked_this_session = set()
    last_unknown_announce = 0
    last_no_face_announce = 0
    no_face_since = None
    print("[INFO] Starting recognition. Press Q to quit.")

    while True:
        ret, frame = cam.read()
        if not ret:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_detector.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5)
        now = time.time()

        if len(faces) == 0:
            # Track how long we've gone without seeing any face at all
            if no_face_since is None:
                no_face_since = now
            elif (now - no_face_since > NO_FACE_ANNOUNCE_AFTER
                  and now - last_no_face_announce > NO_FACE_ANNOUNCE_COOLDOWN):
                speak("No face detected. Please face the camera.")
                last_no_face_announce = now
            status_text = "No face detected"
            status_color = (0, 165, 255)
        else:
            no_face_since = None
            status_text = "Scanning..."
            status_color = (255, 255, 255)

        for (x, y, w, h) in faces:
            face_img = cv2.resize(gray[y:y + h, x:x + w], (200, 200))
            label_id, confidence = recognizer.predict(face_img)

            if confidence < CONFIDENCE_THRESHOLD and label_id in label_map:
                person_code = label_map[label_id]["person_code"]
                name = label_map[label_id]["name"]
                display_text = f"{name} ({confidence:.0f})"
                color = (0, 255, 0)

                if person_code not in marked_this_session:
                    person = db.get_person_by_code(person_code)
                    if person:
                        result = db.mark_attendance(person["id"])
                        marked_this_session.add(person_code)
                        if result == "checked_in":
                            print(f"[ATTENDANCE] Arrival marked: {name} ({person_code})")
                            speak(f"Welcome, {name}. Arrival marked.")
                        elif result == "checked_out":
                            print(f"[ATTENDANCE] Departure marked: {name} ({person_code})")
                            speak(f"Goodbye, {name}. Departure marked.")
                        else:
                            print(f"[INFO] {name} already completed attendance today.")
                            speak(f"{name}, you have already checked in and out today.")
            else:
                display_text = "Unknown"
                color = (0, 0, 255)
                status_text = "Face not recognized"
                status_color = (0, 0, 255)

                if now - last_unknown_announce > UNKNOWN_ANNOUNCE_COOLDOWN:
                    speak("Face not recognized. Please try again or register first.")
                    last_unknown_announce = now

            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, display_text, (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        # Always-visible status banner so it's clear at a glance whether
        # the scanner is actively matching, failing to match, or seeing no one
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 34), (30, 30, 30), -1)
        cv2.putText(frame, status_text, (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)

        if show_window:
            cv2.imshow("Attendance - Press Q to quit", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cam.release()
    cv2.destroyAllWindows()
    return list(marked_this_session)


if __name__ == "__main__":
    run_recognition()