"""Simulated MicroPython ``utime`` module."""

import time as _time

_T0 = _time.perf_counter()
_TICKS_PERIOD = 1 << 30   # MicroPython ticks wrap around at 2**30


def sleep(seconds):
    _time.sleep(seconds)


def sleep_ms(ms):
    _time.sleep(ms / 1000.0)


def sleep_us(us):
    end = _time.perf_counter() + us / 1_000_000.0
    if us > 2000:
        _time.sleep(us / 1_000_000.0 - 0.001)
    while _time.perf_counter() < end:  # busy-wait for short delays, as on the board
        pass


def ticks_ms():
    return int((_time.perf_counter() - _T0) * 1000) % _TICKS_PERIOD


def ticks_us():
    return int((_time.perf_counter() - _T0) * 1_000_000) % _TICKS_PERIOD


def ticks_add(ticks, delta):
    return (ticks + delta) % _TICKS_PERIOD


def ticks_diff(end, start):
    d = (end - start) % _TICKS_PERIOD
    return d - _TICKS_PERIOD if d >= _TICKS_PERIOD // 2 else d


def time():
    return _time.time()
