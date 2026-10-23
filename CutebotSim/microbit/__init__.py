"""Simulated ``microbit`` module for running micro:bit MicroPython programs on a PC.

``from microbit import *`` works exactly as on the board.  Importing it opens
the Cutebot simulator window (or reuses the one already open).

On a real micro:bit this file is never used: the board has its own built-in
``microbit`` module, so the same program can be flashed unchanged.
"""

import time as _time

from cutebot_sim import runtime as _runtime_mod
from cutebot_sim.display import Display as _Display, Image
from cutebot_sim.robot import CUTEBOT_I2C_ADDR as _CUTEBOT_ADDR

_rt = _runtime_mod.get()

__all__ = [
    "Image", "display", "button_a", "button_b", "pin_logo", "pin_speaker",
    "i2c", "spi", "uart", "accelerometer", "compass", "microphone", "speaker",
    "sleep", "running_time", "temperature", "panic", "reset", "set_volume", "scale",
    "Sound", "SoundEvent", "audio",
] + [f"pin{n}" for n in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 19, 20)]


# --- time -------------------------------------------------------------------------
def sleep(ms):
    """Wait for ``ms`` milliseconds."""
    if ms < 0:
        raise ValueError("sleep length must be non-negative")
    _time.sleep(ms / 1000.0)


def running_time():
    """Milliseconds since the program started."""
    return int((_time.perf_counter() - _rt.t0) * 1000)


def temperature():
    """Temperature in degrees Celsius (set in the simulator's Sensors tab)."""
    return _rt.temperature()


def panic(n=0):
    display.show(Image.SAD)
    raise SystemExit(f"micro:bit panic({n})")


def reset():
    """Restart the program (like pressing the micro:bit's reset button)."""
    if _rt.shared is None:
        import os
        import sys

        os.execv(sys.executable, [sys.executable] + sys.argv)
    _rt.request_reset()


def scale(value, from_, to):
    """Convert ``value`` from the range ``from_`` (a tuple) to the range ``to``.
    Returns an int if ``to`` uses ints, else a float."""
    (a, b), (c, d) = from_, to
    result = c + (value - a) * (d - c) / (b - a)
    return int(round(result)) if isinstance(c, int) and isinstance(d, int) else result


def set_volume(v):
    """Speaker volume 0-255 (the simulator does not change the PC volume)."""
    if not 0 <= v <= 255:
        raise ValueError("volume must be 0..255")


# --- display ----------------------------------------------------------------------
display = _Display(_rt)


# --- buttons ----------------------------------------------------------------------
class _Button:
    def __init__(self, name):
        self._name = name
        self._presses = 0

    def _collect(self):
        self._presses += _rt.button_take_presses(self._name)

    def is_pressed(self):
        """True while the button is held down."""
        return _rt.button_down(self._name)

    def was_pressed(self):
        """True if the button was pressed since the last call (or since the start)."""
        self._collect()
        pressed = self._presses > 0
        self._presses = 0
        return pressed

    def get_presses(self):
        """Number of presses since the last call; resets the count."""
        self._collect()
        n, self._presses = self._presses, 0
        return n


button_a = _Button("a")
button_b = _Button("b")


# --- pins -------------------------------------------------------------------------
class _Pin:
    PULL_UP, PULL_DOWN, NO_PULL = 0, 1, 2

    def __init__(self, n):
        self._n = n
        self._out = 0
        self._pull = self.NO_PULL
        self._analog_period = 20

    def write_digital(self, value):
        self._out = 1 if value else 0
        if self._n == 8:
            _rt.robot.trigger_write(self._out)

    def read_digital(self):
        if self._n == 13:
            return _rt.robot.line_sensors()[0]
        if self._n == 14:
            return _rt.robot.line_sensors()[1]
        if self._n == 12:
            return _rt.robot.echo_read()
        return self._out

    def write_analog(self, value):
        if not 0 <= value <= 1023:
            raise ValueError("value must be between 0 and 1023")
        self._out = 1 if value > 0 else 0

    def read_analog(self):
        return 1023 * self.read_digital()

    def set_analog_period(self, period):
        self._analog_period = period

    def set_analog_period_microseconds(self, period):
        self._analog_period = period / 1000.0

    def get_analog_period_microseconds(self):
        return int(self._analog_period * 1000)

    def set_pull(self, value):
        self._pull = value

    def get_pull(self):
        return self._pull

    def get_mode(self):
        return "unused"

    def is_touched(self):
        return False

    def set_touch_mode(self, value):
        pass

    def __repr__(self):
        return f"<MicroBitPin pin{self._n}>"


for _n in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 19, 20):
    globals()[f"pin{_n}"] = _Pin(_n)
pin_logo = _Pin(-1)
pin_speaker = _Pin(-2)
_Pin.CAPACITIVE, _Pin.RESISTIVE = 0, 1


# --- I2C (the Cutebot sits at address 0x10) --------------------------------------------
class _I2C:
    def init(self, freq=100000, sda=None, scl=None):
        pass

    def scan(self):
        return [_CUTEBOT_ADDR]

    def write(self, addr, buf, repeat=False):
        if addr != _CUTEBOT_ADDR:
            raise OSError(19)  # ENODEV, as on the real board
        _rt.robot.i2c_write(bytes(buf))

    def read(self, addr, n, repeat=False):
        if addr != _CUTEBOT_ADDR:
            raise OSError(19)
        return bytes(n)


i2c = _I2C()


class _Stub:
    """Placeholder for hardware the simulator does not model yet."""

    def __init__(self, name, **values):
        self._name = name
        self._values = values

    def __getattr__(self, attr):
        if attr in self._values:
            v = self._values[attr]
            return v if callable(v) else (lambda *a, **k: v)
        return lambda *a, **k: None


spi = _Stub("spi")
uart = _Stub("uart", read=None, readline=None, any=False)
import math as _math  # noqa: E402
import threading as _threading  # noqa: E402

from cutebot_sim import sensors as _sensors  # noqa: E402


# --- accelerometer (tilt pad in the simulator's Sensors tab) -------------------------
class _Accelerometer:
    def get_x(self):
        """Acceleration along x (left/right tilt) in milli-g."""
        return _rt.accel()[0]

    def get_y(self):
        """Acceleration along y (logo up/down tilt) in milli-g."""
        return _rt.accel()[1]

    def get_z(self):
        """Acceleration along z (face up = -1024, face down = +1024) in milli-g."""
        return _rt.accel()[2]

    def get_values(self):
        """(x, y, z) in milli-g."""
        return tuple(_rt.accel())

    def get_strength(self):
        """Total acceleration in milli-g (about 1024 when still)."""
        x, y, z = _rt.accel()
        return int(round(_math.sqrt(x * x + y * y + z * z)))

    def current_gesture(self):
        """The current gesture: 'up', 'down', 'left', 'right', 'face up', 'face down',
        'freefall', '3g', '6g', '8g' or 'shake'."""
        return _rt.current_gesture()

    def is_gesture(self, name):
        """True if ``name`` is the current gesture."""
        _check_gesture(name)
        return _rt.current_gesture() == name

    def was_gesture(self, name):
        """True if ``name`` happened since the last call to was_gesture(name)."""
        _check_gesture(name)
        if name in _rt.gesture_flags:
            _rt.gesture_flags.discard(name)
            return True
        return False

    def get_gestures(self):
        """Gestures since the last call, oldest first (the list is then cleared)."""
        h = tuple(_rt.gesture_history)
        _rt.gesture_history.clear()
        return h

    def set_range(self, value):
        self._range = value


def _check_gesture(name):
    if name not in _sensors.GESTURES:
        raise ValueError(f"invalid gesture: {name!r}")


accelerometer = _Accelerometer()


# --- compass: the robot's heading in the arena (north = up) ---------------------------
class _Compass:
    def heading(self):
        """Direction the robot faces, 0-359 degrees clockwise from north (up in the arena)."""
        hdeg = _rt.robot.heading * 57.29577951308232       # internal: 0 = east, clockwise
        return int(round(hdeg + 90.0)) % 360

    def calibrate(self):
        pass

    def is_calibrated(self):
        return True

    def clear_calibration(self):
        pass

    def _field(self):
        h = _math.radians(self.heading())
        return (int(-30000 * _math.sin(h)), int(30000 * _math.cos(h)), -40000)

    def get_x(self):
        return self._field()[0]

    def get_y(self):
        return self._field()[1]

    def get_z(self):
        return self._field()[2]

    def get_field_strength(self):
        return 50000


compass = _Compass()


# --- microphone (V2): sound-level slider and Clap button in the Sensors tab -----------
class SoundEvent:
    """Microphone events: SoundEvent.LOUD and SoundEvent.QUIET."""

    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return f"SoundEvent('{self._name}')"


SoundEvent.LOUD = SoundEvent("loud")
SoundEvent.QUIET = SoundEvent("quiet")
_EVENTS = {"loud": SoundEvent.LOUD, "quiet": SoundEvent.QUIET}


class _Microphone:
    def sound_level(self):
        """Sound level 0 (silent) to 255 (very loud)."""
        return _rt.sound_level()

    def current_event(self):
        """SoundEvent.LOUD or SoundEvent.QUIET."""
        return _EVENTS[_rt.sound_event_now]

    def is_event(self, event):
        return self.current_event() is event

    def was_event(self, event):
        """True if ``event`` happened since the last call to was_event(event)."""
        if event._name in _rt.sound_flags:
            _rt.sound_flags.discard(event._name)
            return True
        return False

    def get_events(self):
        h = tuple(_EVENTS[n] for n in _rt.sound_history)
        _rt.sound_history.clear()
        return h

    def set_threshold(self, event, value):
        """Level (0-255) above which LOUD / below which QUIET is reported."""
        if event is SoundEvent.LOUD:
            _rt.loud_threshold = int(value)
        else:
            _rt.quiet_threshold = int(value)


microphone = _Microphone()


# --- speaker and sound expressions (V2) ----------------------------------------------
class _Speaker:
    def on(self):
        _rt.speaker_on = True

    def off(self):
        _rt.speaker_on = False

    def is_on(self):
        return _rt.speaker_on


speaker = _Speaker()


class Sound:
    """Built-in sound expressions (V2), used with audio.play(Sound.HAPPY)."""

    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return f"Sound.{self._name}"


for _sname in ("GIGGLE", "HAPPY", "HELLO", "MYSTERIOUS", "SAD", "SLIDE", "SOARING", "SPRING",
               "TWINKLE", "YAWN"):
    setattr(Sound, _sname, Sound(_sname))


class _Audio:
    """``audio.play(Sound.HAPPY)``: shown on the simulator's speaker indicator (about 1 s)."""

    def __init__(self):
        self._until = 0.0

    def play(self, source, wait=True, pin=None, return_pin=None):
        label = repr(source) if isinstance(source, Sound) else "audio"
        _rt.set_speaker(0, label)
        self._until = _time.perf_counter() + 1.0
        if wait:
            _time.sleep(1.0)
            _rt.set_speaker(0, "")
        else:
            _threading.Timer(1.0, lambda: _rt.set_speaker(0, "")).start()

    def is_playing(self):
        return _time.perf_counter() < self._until

    def stop(self):
        self._until = 0.0
        _rt.set_speaker(0, "")


audio = _Audio()


# MicroPython's ``time`` also has these; add them to PC Python's ``time`` so
# ``import time; time.sleep_ms(500)`` works in the simulator too.
from utime import sleep_ms as _sms, sleep_us as _sus, ticks_ms as _tms, ticks_us as _tus  # noqa: E402
from utime import ticks_add as _tadd, ticks_diff as _tdiff  # noqa: E402

for _k, _v in (("sleep_ms", _sms), ("sleep_us", _sus), ("ticks_ms", _tms), ("ticks_us", _tus),
               ("ticks_add", _tadd), ("ticks_diff", _tdiff)):
    if not hasattr(_time, _k):
        setattr(_time, _k, _v)
