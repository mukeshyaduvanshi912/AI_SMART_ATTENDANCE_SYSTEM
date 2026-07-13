"""
voice_assistant.py
--------------------
Adds voice capabilities to the attendance system:

1. speak(text)              - text-to-speech announcement (used by recognize.py
                               to greet people by name when the camera recognizes them)
2. run_voice_attendance()   - a microphone-based fallback: the assistant asks
                               "Please say your name or ID", listens, matches
                               what it heard against registered people, and
                               marks attendance by voice alone (no camera needed).

Uses:
    pyttsx3          - offline text-to-speech (works without internet)
    SpeechRecognition - microphone capture + speech-to-text
                        (uses Google's free Web Speech API, so this part
                        needs an internet connection)
"""

import difflib
import os
import tempfile
import pyttsx3
import speech_recognition as sr

import database as db
import voice_auth

MAX_LISTEN_ATTEMPTS = 3
MATCH_CONFIDENCE_CUTOFF = 0.6  # 0-1, how close a spoken name must be to count as a match


def speak(text):
    """Speaks text out loud. Safe to call even if no speakers are present
    (falls back to silently printing)."""
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", 175)
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as e:
        print(f"[VOICE] (TTS unavailable: {e}) {text}")


def _listen_once(recognizer, mic, timeout=5, phrase_time_limit=6):
    """Captures one utterance from the microphone and returns
    (recognized_text, audio_data), or (None, None) if nothing usable
    was heard. audio_data is kept so the same clip can also be checked
    against a stored voiceprint, without asking the person to repeat themselves."""
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.6)
        try:
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        except sr.WaitTimeoutError:
            return None, None

    try:
        text = recognizer.recognize_google(audio)
        return text.strip(), audio
    except sr.UnknownValueError:
        return None, audio
    except sr.RequestError as e:
        print(f"[VOICE] Speech recognition service error: {e}")
        return None, audio


def _find_best_match(spoken_text, people):
    """Matches spoken text against registered people by name or by
    person_code (spelled out or spoken as a code). Returns the best
    matching person row, or None if nothing is close enough."""
    if not spoken_text:
        return None

    spoken_lower = spoken_text.lower()

    # 1. Exact or near-exact person_code match (e.g. "EMP101")
    for p in people:
        if p["person_code"].lower() in spoken_lower or spoken_lower in p["person_code"].lower():
            return p

    # 2. Fuzzy match on name
    names = [p["name"].lower() for p in people]
    matches = difflib.get_close_matches(spoken_lower, names, n=1, cutoff=MATCH_CONFIDENCE_CUTOFF)
    if matches:
        matched_name = matches[0]
        for p in people:
            if p["name"].lower() == matched_name:
                return p

    return None


def run_voice_attendance():
    """Runs an interactive voice session: greets the user, listens for a
    name/ID, marks attendance if matched, and reports the outcome.
    Returns (success: bool, message: str)."""

    people = db.get_all_people()
    if not people:
        message = "No one is registered yet. Please register people before using voice attendance."
        speak(message)
        return False, message

    recognizer = sr.Recognizer()
    try:
        mic = sr.Microphone()
    except Exception as e:
        message = f"Could not access microphone: {e}"
        speak("I could not access the microphone.")
        return False, message

    speak("Please say your full name or your ID to mark attendance.")

    for attempt in range(1, MAX_LISTEN_ATTEMPTS + 1):
        spoken_text, audio = _listen_once(recognizer, mic)

        if not spoken_text:
            if attempt < MAX_LISTEN_ATTEMPTS:
                speak("Sorry, I didn't catch that. Please try again.")
            continue

        person = _find_best_match(spoken_text, people)

        if not person:
            if attempt < MAX_LISTEN_ATTEMPTS:
                speak(f"I heard '{spoken_text}', but couldn't match anyone. Please try again.")
            continue

        # If this person has an enrolled voiceprint, verify the CURRENT
        # speaker actually sounds like them - not just that they said the
        # right name. This is what stops someone else marking them present
        # by simply saying their name.
        if voice_auth.has_voiceprint(person["person_code"]):
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
            os.close(tmp_fd)
            try:
                with open(tmp_path, "wb") as f:
                    f.write(audio.get_wav_data())
                is_match, similarity = voice_auth.verify_voice(person["person_code"], tmp_path)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

            if not is_match:
                print(f"[VOICE] Voice mismatch for {person['name']} (similarity {similarity:.2f})")
                speak(f"That doesn't sound like {person['name']}. Attendance not marked.")
                return False, f"Voice did not match {person['name']}'s enrolled voiceprint."

        result = db.mark_attendance(person["id"])
        if result == "checked_in":
            message = f"Arrival marked for {person['name']}."
            speak(f"Welcome, {person['name']}. Your arrival has been marked.")
        elif result == "checked_out":
            message = f"Departure marked for {person['name']}."
            speak(f"Goodbye, {person['name']}. Your departure has been marked.")
        else:
            message = f"{person['name']} has already checked in and out today."
            speak(f"{person['name']}, you have already checked in and out today.")
        return True, message

    message = "Could not recognize a registered name or ID after several attempts."
    speak("Sorry, I could not recognize a registered name or ID. Please try again later.")
    return False, message


if __name__ == "__main__":
    ok, msg = run_voice_attendance()
    print(("[SUCCESS] " if ok else "[FAILED] ") + msg)