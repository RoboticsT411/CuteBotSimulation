"""Simulated MicroPython ``machine`` module (the parts used with the micro:bit)."""

import time as _time

import microbit as _mb


def time_pulse_us(pin, pulse_level, timeout_us=1_000_000):
    """Length of a pulse on ``pin`` in microseconds.

    Returns -2 if the pulse did not start within ``timeout_us``,
    -1 if it did not end within ``timeout_us``.
    """
    timeout = timeout_us / 1_000_000.0
    t = _time.perf_counter()
    while pin.read_digital() != pulse_level:
        if _time.perf_counter() - t > timeout:
            return -2
    start = _time.perf_counter()
    while pin.read_digital() == pulse_level:
        if _time.perf_counter() - start > timeout:
            return -1
    return int((_time.perf_counter() - start) * 1_000_000)


def reset():
    _mb.reset()


def freq():
    return 64_000_000


def unique_id():
    return b"\xc0\x7e\xb0\x70\x00\x00\x00\x01"


def disable_irq():
    return 0


def enable_irq(state=0):
    pass
