"""Simulated micro:bit ``radio`` module.

Works like the real one (same functions, groups, channels, queue and length limits).
Messages go through the simulator window:

* on your own: the window's Radio console shows what your program sends and lets you
  type messages to it (as if from another micro:bit);
* in a LAN shared arena: messages are passed to every other robot in the arena on the
  same channel and group.
"""

import microbit as _mb

_rt = _mb._rt

RATE_1MBIT = 0
RATE_2MBIT = 2
RATE_250KBIT = 1     # V1 only on the real micro:bit

_HEADER = b"\x01\x00\x01"          # what radio.send() puts in front of a string
_DEFAULTS = dict(length=32, queue=3, channel=7, power=6, address=0x75626974, group=0,
                 data_rate=RATE_1MBIT)
_cfg_extra = {"power": 6, "address": 0x75626974, "data_rate": RATE_1MBIT}


def _check_on():
    if not _rt.radio_cfg["on"]:
        raise ValueError("radio is not enabled")


def on():
    """Turn the radio on (it is off when the program starts)."""
    _rt.radio_cfg["on"] = True
    _rt.radio_status()


def off():
    """Turn the radio off (saves power on the real micro:bit)."""
    _rt.radio_cfg["on"] = False
    _rt.radio_queue.clear()
    _rt.radio_status()


def config(**kwargs):
    """Settings: length (1-251), queue, channel (0-83), power (0-7), address, group (0-255),
    data_rate.  Only robots on the same channel and group hear each other."""
    for key, value in kwargs.items():
        if key not in _DEFAULTS:
            raise TypeError(f"unexpected keyword argument '{key}'")
        if key == "length" and not 1 <= value <= 251:
            raise ValueError("value out of range for argument 'length'")
        if key == "channel" and not 0 <= value <= 83:
            raise ValueError("value out of range for argument 'channel'")
        if key == "group" and not 0 <= value <= 255:
            raise ValueError("value out of range for argument 'group'")
        if key == "power" and not 0 <= value <= 7:
            raise ValueError("value out of range for argument 'power'")
        if key in ("length", "queue", "channel", "group"):
            _rt.radio_cfg[key] = int(value)
        else:
            _cfg_extra[key] = value
    _rt.radio_status()


def reset():
    """Back to the default settings."""
    for key in ("length", "queue", "channel", "group"):
        _rt.radio_cfg[key] = _DEFAULTS[key]
    _cfg_extra.update(power=6, address=0x75626974, data_rate=RATE_1MBIT)
    _rt.radio_status()


def send_bytes(message):
    """Send bytes to every micro:bit on the same channel and group."""
    _check_on()
    data = bytes(message)[:_rt.radio_cfg["length"]]
    _rt.radio_send(data)


def send(message):
    """Send a string."""
    send_bytes(_HEADER + str(message).encode("utf-8"))


def _next():
    _check_on()
    _rt.radio_poll()
    with _rt._radio_lock:
        if not _rt.radio_queue:
            return None
        return _rt.radio_queue.pop(0)


def receive_bytes():
    """The next message as bytes, or None if nothing has arrived."""
    m = _next()
    return None if m is None else m[0]


def receive():
    """The next message as a string, or None if nothing has arrived."""
    m = _next()
    if m is None:
        return None
    data = m[0]
    if data[:3] != _HEADER:
        raise ValueError("received packet is not a string")
    try:
        return data[3:].decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("received packet is not a string")


def receive_bytes_into(buffer):
    """Copy the next message into ``buffer``; returns its length, or None."""
    m = _next()
    if m is None:
        return None
    n = min(len(buffer), len(m[0]))
    buffer[:n] = m[0][:n]
    return len(m[0])


def receive_full():
    """(message bytes, signal strength dBm, time in microseconds) or None."""
    return _next()
