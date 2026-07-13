"""
train_model.py
----------------
Reads all face images from dataset/<person_code>_<name>/ folders,
trains an OpenCV LBPH face recognizer, and saves:
  - trainer/trainer.yml       (the trained model)
  - trainer/labels.json       (maps numeric label -> person_code, name)

Run:
    python train_model.py
"""

import cv2
import os
import json
import numpy as np

DATASET_DIR = "dataset"
TRAINER_DIR = "trainer"
TRAINER_FILE = os.path.join(TRAINER_DIR, "trainer.yml")
LABELS_FILE = os.path.join(TRAINER_DIR, "labels.json")


def train_model():
    os.makedirs(TRAINER_DIR, exist_ok=True)

    recognizer = cv2.face.LBPHFaceRecognizer_create()

    face_samples = []
    ids = []
    label_map = {}   # numeric_id -> {"person_code":..., "name":...}
    next_label = 0

    if not os.path.exists(DATASET_DIR) or not os.listdir(DATASET_DIR):
        raise RuntimeError("No data found in dataset/. Run capture_faces.py first.")

    for folder_name in sorted(os.listdir(DATASET_DIR)):
        folder_path = os.path.join(DATASET_DIR, folder_name)
        if not os.path.isdir(folder_path):
            continue

        # folder_name format: "<person_code>_<name>"
        try:
            person_code, name = folder_name.split("_", 1)
        except ValueError:
            print(f"[WARN] Skipping folder with unexpected name: {folder_name}")
            continue

        label_map[next_label] = {"person_code": person_code, "name": name}

        for img_name in os.listdir(folder_path):
            img_path = os.path.join(folder_path, img_name)
            gray_img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
            if gray_img is None:
                continue
            face_samples.append(gray_img)
            ids.append(next_label)

        next_label += 1

    if not face_samples:
        raise RuntimeError("No valid face images found to train on.")

    print(f"[INFO] Training on {len(face_samples)} images across {next_label} people...")
    recognizer.train(face_samples, np.array(ids))
    recognizer.save(TRAINER_FILE)

    with open(LABELS_FILE, "w") as f:
        json.dump(label_map, f, indent=2)

    print(f"[INFO] Model saved to {TRAINER_FILE}")
    print(f"[INFO] Labels saved to {LABELS_FILE}")


if __name__ == "__main__":
    train_model()
