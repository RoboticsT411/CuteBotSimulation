"""Sensor helpers shared by the program side and the window.

Accelerometer convention (as on the micro:bit, values in milli-g):
* lying flat, face up:            x = 0, y = 0, z = -1024
* tilted so the RIGHT edge is down: x > 0       ("right" gesture near +1024)
* tilted so the LOGO edge is down:  y > 0       ("down" gesture, logo pointing down)
* face down:                       z = +1024
"""

import math

GESTURES = ("up", "down", "left", "right", "face up", "face down", "freefall",
            "3g", "6g", "8g", "shake")
PULSE_GESTURES = ("shake", "freefall", "3g", "6g", "8g")
PULSE_S = 0.6                     # how long a shake/freefall pulse lasts


def accel_from_tilt(roll_deg, pitch_deg, face_down=False):
    """Accelerometer reading (mg) for a board tilted right by ``roll`` and with the
    logo edge tilted down by ``pitch`` (degrees, -90..90)."""
    r, p = math.radians(roll_deg), math.radians(pitch_deg)
    x = 1024.0 * math.sin(r)
    y = 1024.0 * math.sin(p) * math.cos(r)
    z = -1024.0 * math.cos(r) * math.cos(p)
    if face_down:
        z = -z
    return [x, y, z]


def gesture_from_accel(x, y, z):
    """The orientation gesture for a steady accelerometer reading ('' if in between)."""
    ax, ay, az = abs(x), abs(y), abs(z)
    strength = math.sqrt(x * x + y * y + z * z)
    if strength < 300:
        return "freefall"
    if az >= ax and az >= ay and az > 700:
        return "face up" if z < 0 else "face down"
    if ax >= ay and ax > 700:
        return "right" if x > 0 else "left"
    if ay > ax and ay > 700:
        return "down" if y > 0 else "up"
    return ""


# --- musical notes ------------------------------------------------------------------
_SEMITONES = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


class NoteParser:
    """Parses MicroPython music notes such as 'c4:4', 'f#', 'eb5:2', 'r:1'.
    Octave and duration carry over from the previous note, as on the micro:bit."""

    def __init__(self):
        self.octave = 4
        self.duration = 4

    def parse(self, note):
        """Returns (frequency_hz or 0 for a rest, duration_ticks, label)."""
        note = str(note).strip().lower()
        if ":" in note:
            note, dur = note.split(":", 1)
            try:
                self.duration = int(dur)
            except ValueError:
                pass
        if not note:
            return 0, self.duration, "rest"
        name = note[0]
        rest = note[1:]
        if name == "r":
            return 0, self.duration, "rest"
        if name not in _SEMITONES:
            raise ValueError(f"invalid note: {note!r}")
        semi = _SEMITONES[name]
        accidental = ""
        if rest[:1] == "#":
            semi += 1
            accidental, rest = "#", rest[1:]
        elif rest[:1] == "b" and len(rest) >= 1 and (len(rest) == 1 or rest[1:2].isdigit()):
            semi -= 1
            accidental, rest = "b", rest[1:]
        if rest[:1].isdigit():
            self.octave = int(rest[0])
        midi = 12 * (self.octave + 1) + semi
        freq = 440.0 * 2 ** ((midi - 69) / 12.0)
        return freq, self.duration, f"{name.upper()}{accidental}{self.octave}"
