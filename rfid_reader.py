"""
rfid_reader.py
----------------
Support for RFID-based attendance, marking arrival/departure the same
way face recognition does.

Most cheap USB RFID readers (125kHz EM-18 style, or any "USB HID" reader)
work as KEYBOARD EMULATORS: when you tap a card, the reader "types" the
card's ID followed by Enter into whatever text field currently has
focus. That means NO special driver or Python library is needed for
those — the browser-based /rfid page in this app already handles them:
it keeps a hidden input auto-focused and listens for Enter, then submits
the scanned ID to Flask automatically. Just open /rfid and start tapping
cards; the OS + browser do the rest.

This file adds an OPTIONAL second mode for SERIAL RFID readers (e.g. an
Arduino + RFID module sending the card ID over a COM port instead of
acting like a keyboard). This mode requires the `pyserial` package and a
known COM port, and is only used if you call read_from_serial() yourself
(e.g. from a custom script) — the web UI does not require it.
"""

import database as db
from voice_assistant import speak


def process_rfid_scan(rfid_tag):
    """Given a scanned RFID tag string, looks up the matching person and
    marks arrival/departure exactly like face recognition does.
    Returns (success: bool, message: str)."""

    rfid_tag = (rfid_tag or "").strip()
    if not rfid_tag:
        return False, "No card ID received."

    person = db.get_person_by_rfid(rfid_tag)
    if not person:
        speak("Card not recognized. Please register this card first.")
        return False, f"No one is registered with card '{rfid_tag}'."

    result = db.mark_attendance(person["id"])

    if result == "checked_in":
        speak(f"Welcome, {person['name']}. Arrival marked.")
        return True, f"Arrival marked for {person['name']}."
    elif result == "checked_out":
        speak(f"Goodbye, {person['name']}. Departure marked.")
        return True, f"Departure marked for {person['name']}."
    else:
        speak(f"{person['name']}, you have already checked in and out today.")
        return True, f"{person['name']} has already checked in and out today."


def read_from_serial(port, baudrate=9600, timeout=1):
    """OPTIONAL: continuously reads card IDs from a serial-connected RFID
    reader (e.g. Arduino) and processes each scan. Requires `pyserial`
    (pip install pyserial) - not part of the default requirements.txt
    since most readers don't need it.

    Run this as its own standalone script if you have this kind of
    hardware:
        python -c "from rfid_reader import read_from_serial; read_from_serial('COM3')"
    """
    try:
        import serial
    except ImportError:
        raise RuntimeError(
            "pyserial is not installed. Run: pip install pyserial"
        )

    print(f"[RFID] Listening on {port} at {baudrate} baud. Press Ctrl+C to stop.")
    with serial.Serial(port, baudrate, timeout=timeout) as ser:
        while True:
            line = ser.readline().decode(errors="ignore").strip()
            if line:
                success, message = process_rfid_scan(line)
                print(("[OK] " if success else "[FAIL] ") + message)


if __name__ == "__main__":
    tag = input("Simulate a card scan - enter card ID: ").strip()
    ok, msg = process_rfid_scan(tag)
    print(("[SUCCESS] " if ok else "[FAILED] ") + msg)
    