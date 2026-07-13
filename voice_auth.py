"""
voice_auth.py
--------------
Builds and verifies voiceprints (speaker verification) using MFCC
features so that attendance can only be marked by the actual
registered person's voice, not just by speaking their name.

Enrollment is handled by enroll.py. This module just handles the
feature extraction + comparison math.
"""

import os
import numpy as np
import librosa

VOICEPRINT_DIR = "voiceprints"
SIMILARITY_THRESHOLD = 0.82  # tune this after testing (0.75-0.90 typical)


def _extract_features(wav_path):
    try:
        y, sr = librosa.load(wav_path, sr=16000)
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
        delta = librosa.feature.delta(mfcc)
        combined = np.vstack([mfcc, delta])
        return np.mean(combined, axis=1)
    except Exception as e:
        print("Feature extraction error:", e)
        return None


def save_voiceprint(person_code, wav_paths):
    """Averages features from multiple enrollment recordings into one
    voiceprint and saves it to voiceprints/<person_code>.npy.
    Returns True on success, False if no usable recordings were found."""
    features = [_extract_features(p) for p in wav_paths]
    features = [f for f in features if f is not None]

    if not features:
        print("Voiceprint save failed: no usable recordings.")
        return False

    voiceprint = np.mean(features, axis=0)
    os.makedirs(VOICEPRINT_DIR, exist_ok=True)
    np.save(os.path.join(VOICEPRINT_DIR, f"{person_code}.npy"), voiceprint)
    return True


def has_voiceprint(person_code):
    return os.path.exists(os.path.join(VOICEPRINT_DIR, f"{person_code}.npy"))


def delete_voiceprint(person_code):
    path = os.path.join(VOICEPRINT_DIR, f"{person_code}.npy")
    if os.path.exists(path):
        os.remove(path)


def verify_voice(person_code, wav_path):
    """Compares a freshly recorded clip against the stored voiceprint
    for person_code. Returns (is_match: bool, similarity: float)."""
    voiceprint_path = os.path.join(VOICEPRINT_DIR, f"{person_code}.npy")
    if not os.path.exists(voiceprint_path):
        return False, 0.0

    stored = np.load(voiceprint_path)
    current = _extract_features(wav_path)

    if current is None:
        return False, 0.0

    similarity = np.dot(stored, current) / (
        np.linalg.norm(stored) * np.linalg.norm(current)
    )
    return similarity >= SIMILARITY_THRESHOLD, float(similarity)