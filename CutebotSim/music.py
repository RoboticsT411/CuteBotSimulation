"""Simulated ``music`` module.

Notes are parsed like on the micro:bit ('c4:4', 'f#', 'eb5:2', 'r:1' = rest;
octave and duration carry over).  Each note is shown on the simulator's speaker
indicator and takes the right amount of time.  On Windows, tick "Play sounds on this
PC" in the Sensors tab to hear the notes through the PC speaker.

The built-in melody names (music.NYAN, music.ENTERTAINER, ...) exist so programs run,
but the simulator plays short placeholder tunes, not the real melodies.
"""

import sys as _sys
import threading as _threading
import time as _time

from cutebot_sim.sensors import NoteParser as _NoteParser

_ticks, _bpm = 4, 120
_stop = _threading.Event()
_lock = _threading.Lock()

# Placeholder tunes (simple sequences, not the real melodies).
_UP = ["c4:2", "e", "g", "c5:4"]
_DOWN = ["c5:2", "g4", "e", "c:4"]
_TUNE = ["c4:2", "d", "e", "g", "e", "d", "c:4"]
_PLACEHOLDERS = {
    "JUMP_UP": ["c5:1", "g5"], "JUMP_DOWN": ["g5:1", "c5"], "POWER_UP": _UP, "POWER_DOWN": _DOWN,
    "BA_DING": ["b5:1", "e6:3"], "WAWAWAWAA": ["e3:3", "r:1", "d#", "r", "d", "r", "c#:8"],
    "PUNCHLINE": ["c4:3", "g3:1", "f#", "g", "g#:3", "g", "r", "b", "c4"],
    "PYTHON": _TUNE, "BADDY": ["c3:3", "r", "d:2", "d#", "r", "c"], "CHASE": ["a4:1", "b", "c5", "b4"] * 2,
    "RINGTONE": ["c4:1", "d", "e:2", "g", "d:1", "e", "f:2", "a", "e:1", "f", "g:2", "b", "c5:4"],
}
for _n in ("DADADADUM ENTERTAINER PRELUDE ODE NYAN FUNK BLUES BIRTHDAY WEDDING FUNERAL").split():
    _PLACEHOLDERS[_n] = _TUNE
for _n, _notes in _PLACEHOLDERS.items():
    globals()[_n] = list(_notes)


def _rt():
    import microbit

    return microbit._rt


def set_tempo(ticks=4, bpm=120):
    """Set the length of a tick: ``bpm`` beats per minute, ``ticks`` ticks per beat."""
    global _ticks, _bpm
    _ticks, _bpm = ticks, bpm


def get_tempo():
    return (_ticks, _bpm)


def _sound(freq, ms, label):
    """Show the note and wait ``ms`` (beep on Windows if enabled)."""
    rt = _rt()
    rt.set_speaker(freq, label)
    played = False
    if freq >= 37 and ms > 0 and _sys.platform == "win32" and rt.sound_output_enabled() and rt.speaker_on:
        try:
            import winsound

            winsound.Beep(int(min(freq, 32767)), int(ms))
            played = True
        except Exception:
            played = False
    if not played:
        end = _time.perf_counter() + ms / 1000.0
        while not _stop.is_set():
            left = end - _time.perf_counter()
            if left <= 0:
                break
            _time.sleep(min(left, 0.02))
    rt.set_speaker(0, "")


def _play_notes(notes, loop):
    parser = _NoteParser()
    tick_ms = 60000.0 / _bpm / _ticks
    while True:
        for note in notes:
            if _stop.is_set():
                return
            freq, dur, label = parser.parse(note)
            _sound(freq, dur * tick_ms, label if freq else "rest")
        if not loop or _stop.is_set():
            return


def play(music, pin=None, wait=True, loop=False):
    """Play a note ('c4:4'), a list of notes, or a built-in melody."""
    if isinstance(music, str):
        music = [music]
    notes = list(music)
    _NoteParser().parse(notes[0]) if notes else None      # raise ValueError early for bad notes
    _stop.clear()
    if wait and not loop:
        _play_notes(notes, False)
    else:
        _threading.Thread(target=_play_notes, args=(notes, loop), daemon=True).start()
        if wait:
            while not _stop.is_set():
                _time.sleep(0.05)


def pitch(frequency, duration=-1, pin=None, wait=True):
    """Play a frequency in Hz for ``duration`` ms (-1 = until music.stop())."""
    _stop.clear()
    label = f"{int(frequency)} Hz"
    if duration < 0:
        _rt().set_speaker(frequency, label)
        return
    if wait:
        _sound(frequency, duration, label)
    else:
        _threading.Thread(target=_sound, args=(frequency, duration, label), daemon=True).start()


def stop(pin=None):
    """Stop any music that is playing."""
    _stop.set()
    _rt().set_speaker(0, "")


def reset():
    set_tempo()
