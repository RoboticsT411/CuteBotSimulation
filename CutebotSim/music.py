"""Simulated ``music`` module: no sound, but timing is kept so programs behave the same."""

import time as _time

_ticks, _bpm = 4, 120
_NAMES = ("DADADADUM ENTERTAINER PRELUDE ODE NYAN RINGTONE FUNK BLUES BIRTHDAY WEDDING "
          "FUNERAL PUNCHLINE PYTHON BADDY CHASE BA_DING WAWAWAWAA JUMP_UP JUMP_DOWN "
          "POWER_UP POWER_DOWN").split()
for _n in _NAMES:
    globals()[_n] = ["c4:4"]


def set_tempo(ticks=4, bpm=120):
    global _ticks, _bpm
    _ticks, _bpm = ticks, bpm


def get_tempo():
    return (_ticks, _bpm)


def play(music, pin=None, wait=True, loop=False):
    if isinstance(music, str):
        music = [music]
    if wait and not loop:
        beat = 60.0 / _bpm / _ticks
        total = 0.0
        for note in music:
            dur = note.split(":")[1] if ":" in note else "4"
            try:
                total += int(dur) * beat
            except ValueError:
                total += 4 * beat
        _time.sleep(total)


def pitch(frequency, duration=-1, pin=None, wait=True):
    if wait and duration > 0:
        _time.sleep(duration / 1000.0)


def stop(pin=None):
    pass


def reset():
    set_tempo()
