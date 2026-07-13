"""
enroll.py
----------
Records a few short voice samples from a person and saves an averaged
voiceprint for them, using the same microphone + TTS setup as
voice_assistant.py.

Used by app.py's /people/<id>/enroll-voice route: when the operator
clicks "Enroll Voice" in the dashboard, this opens the local microphone
right there on the server machine and records a few samples on the spot
(same local-kiosk model as recognize.py opening the local webcam).

Can also be run directly for manual testing:
    py -3.11 enroll.py
"""

import os
import tempfile

import speech_recognition as sr

import database as db
import voice_auth
from voice_assistant import speak

NUM_SAMPLES = 3
RECORD_TIMEOUT = 5
PHRASE_TIME_LIMIT = 6


def _record_sample(recognizer, mic, sample_num, total):
    speak(f"Recording sample {sample_num} of {total}. Please speak now.")
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.6)
        try:
            audio = recognizer.listen(
                source, timeout=RECORD_TIMEOUT, phrase_time_limit=PHRASE_TIME_LIMIT
            )
        except sr.WaitTimeoutError:
            print("No speech detected, try again.")
            return None

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    os.close(tmp_fd)
    with open(tmp_path, "wb") as f:
        f.write(audio.get_wav_data())

    return tmp_path


def enroll_voice(person_code, num_samples=NUM_SAMPLES):
    """Records num_samples short clips from the local microphone and saves
    an averaged voiceprint for person_code. Returns the number of samples
    successfully recorded and saved (0 if enrollment failed entirely).
    Raises RuntimeError if the microphone can't be accessed, so callers
    (e.g. the Flask route) can show a clear error message."""

    recognizer = sr.Recognizer()
    try:
        mic = sr.Microphone()
    except Exception as e:
        raise RuntimeError(f"Could not access microphone: {e}")

    wav_paths = []
    attempt = 0

    while len(wav_paths) < num_samples and attempt < num_samples * 2:
        attempt += 1
        path = _record_sample(recognizer, mic, len(wav_paths) + 1, num_samples)
        if path:
            wav_paths.append(path)

    if not wav_paths:
        speak("No usable recordings were captured. Enrollment failed.")
        return 0

    success = voice_auth.save_voiceprint(person_code, wav_paths)

    for path in wav_paths:
        try:
            os.remove(path)
        except OSError:
            pass

    if success:
        speak("Voice enrollment complete.")
        print(f"Voiceprint saved for {person_code} ({len(wav_paths)} samples).")
        return len(wav_paths)
    else:
        speak("Voice enrollment failed.")
        return 0


if __name__ == "__main__":
    people = db.get_all_people()
    if not people:
        print("No one is registered yet. Please register people before enrolling voices.")
    else:
        print("Registered people:")
        for p in people:
            print(f"  {p['person_code']} - {p['name']}")

        code = input("\nEnter the person_code to enroll: ").strip()
        matching = [p for p in people if p["person_code"] == code]

        if not matching:
            print(f"No registered person found with person_code '{code}'.")
        else:
            person = matching[0]
            print(f"Enrolling voice for {person['name']} ({code}).")
            count = enroll_voice(code)
            print(f"Recorded {count} sample(s).")