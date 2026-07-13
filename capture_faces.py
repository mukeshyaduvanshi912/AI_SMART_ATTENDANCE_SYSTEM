"""
capture_faces.py
------------------
Captures face images from a webcam for a given person and stores them
in dataset/<person_code>_<name>/imgN.jpg for later training.

Run standalone:
    python capture_faces.py

Or import capture_faces(person_code, name) from app.py for a web-triggered flow.
"""

import cv2
import os

DATASET_DIR = "dataset"
FACE_CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
NUM_SAMPLES = 100  # number of face images to capture per person


def capture_faces(person_code, name, num_samples=NUM_SAMPLES, camera_index=0):
    """Opens the webcam, detects faces, and saves cropped grayscale
    face images to dataset/<person_code>_<name>/."""

    face_detector = cv2.CascadeClassifier(FACE_CASCADE_PATH)
    cam = cv2.VideoCapture(camera_index)

    if not cam.isOpened():
        raise RuntimeError("Could not open webcam. Check camera index / permissions.")

    person_dir = os.path.join(DATASET_DIR, f"{person_code}_{name}")
    os.makedirs(person_dir, exist_ok=True)

    count = 0
    print(f"[INFO] Capturing faces for {name} ({person_code}). Look at the camera...")

    while count < num_samples:
        ret, frame = cam.read()
        if not ret:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_detector.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5)

        for (x, y, w, h) in faces:
            count += 1
            face_img = gray[y:y + h, x:x + w]
            face_img = cv2.resize(face_img, (200, 200))
            img_path = os.path.join(person_dir, f"img_{count}.jpg")
            cv2.imwrite(img_path, face_img)

            # Draw rectangle for live preview
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, f"Samples: {count}/{num_samples}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            break  # only take one face per frame

        cv2.imshow("Capturing Faces - Press Q to quit early", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cam.release()
    cv2.destroyAllWindows()
    print(f"[INFO] Done. Captured {count} images for {name}.")
    return count


if __name__ == "__main__":
    p_code = input("Enter person ID / roll number / employee code: ").strip()
    p_name = input("Enter full name: ").strip()
    capture_faces(p_code, p_name)