"""Shared-memory link between the student's program and the simulator window.

Two processes are involved:

* the student's program (it imports ``microbit``), which owns the robot physics, and
* the simulator window (``python -m cutebot_sim.gui``), which only draws and
  reports button presses / mouse drags.

They talk through one small block of shared memory with fixed fields.  Each
field has a single writer, so no locking is needed.
"""

import os
import struct
import sys
from multiprocessing import shared_memory

# CUTEBOT_SIM_INSTANCE=name runs a separate simulator (window + program) on the same PC,
# e.g. to try a LAN competition with two robots on one computer.
SHM_NAME = None          # set below from the layout, so every version gets its own block
MAX_OBSTACLES = 40
MAX_LINE_FLOATS = 24000   # x, y pairs; (NaN, NaN) separates strokes
MAGIC = 0xC07EB070
MAX_OTHERS = 24           # other robots in a shared arena (LAN)
RADIO_SLOTS = 16          # radio messages buffered each way
RADIO_SLOT = 256          # bytes per message slot: len, group, channel, 0, payload (<= 251)
RADIO_MAX = 251
CMD_LOG = 32              # motor commands kept for the code view

# (name, struct code, count).  Writer in the comment: G = window, P = program.
_FIELDS = [
    ("magic", "I", 1),          # G
    ("gui_pid", "I", 1),        # G
    ("gui_tick", "I", 1),       # G  increments every frame while the window is alive
    ("gui_closing", "B", 1),    # G  1 = window closed by the user
    ("btn_a_down", "B", 1),     # G
    ("btn_b_down", "B", 1),     # G
    ("btn_a_count", "I", 1),    # G  total presses since the window opened
    ("btn_b_count", "I", 1),    # G
    ("pose_req_seq", "I", 1),   # G  bumped when the user drags/rotates/resets the robot
    ("pose_req", "f", 3),       # G  x, y (cm), heading (deg); NaN x = "go to start"
    ("reset_req", "I", 1),      # G  bumped by the micro:bit RESET button
    ("accel", "f", 3),          # G  accelerometer x, y, z (mg) from the tilt pad
    ("pulse_seq", "I", 1),      # G  bumped for a shake / freefall / 3g pulse
    ("pulse_name", "16s", 1),   # G  which pulse gesture
    ("mic_level", "B", 1),      # G  microphone sound level 0..255
    ("temp_c", "f", 1),         # G  temperature (deg C)
    ("light", "B", 1),          # G  light level 0..255
    ("sound_out", "B", 1),      # G  1 = play music on the PC speaker (Windows)
    ("sensors_set", "B", 1),    # G  1 once the window has written the values above
    ("motor_gain", "f", 2),     # G  simulated motor strength, left/right (1.0 = exact)
    ("world_seq", "I", 1),      # G  seqlock: odd while the window is writing the world
    ("arena", "f", 2),          # G  width, height (cm)
    ("line_width", "f", 1),     # G
    ("start", "f", 3),          # G  start pose (internal frame)
    ("obs_count", "H", 1),      # G
    ("obs", "f", 4 * 40),       # G  obstacles: x0, y0, x1, y1 (cm, internal frame)
    ("wline_n", "I", 1),        # G  number of floats used in "wline"
    ("wline", "f", 24000),      # G  world line strokes as x, y pairs, NaN pair between strokes
    ("realism", "B", 1),        # G  1 = realistic sensors and motors (noise, dead zone)
    ("dead_zone", "B", 1),      # G  motor speeds below this do not turn the wheel (realistic)
    ("hold", "B", 1),           # G  1 = a race is armed: programs wait for the teacher's GO
    ("others_n", "H", 1),       # G  other robots in a shared arena
    ("others", "f", 3 * 24),    # G  their x, y, heading (internal frame)
    ("rx_wr", "I", 1),          # G  radio messages written for the program (total)
    ("rx_msgs", "B", 16 * 256), # G  ring of RADIO_SLOTS slots
    ("sim_speed", "f", 1),      # G  simulation speed (1 = real time, 0.25 = slow motion)
    ("paused", "B", 1),         # G  1 = simulation paused
    ("step_seq", "I", 1),       # G  bumped by Step: run to the next line of the program
    ("pause_on", "B", 1),       # G  auto-pause: 1 = motor command, 2 = line sensor change, 4 = bump
    ("mounted", "B", 1),        # G  1 = micro:bit stands upright on the Cutebot (accel follows the robot)
    ("owner_gen", "I", 1),      # P  bumped by each new program run
    ("owner_pid", "I", 1),      # P
    ("prog_tick", "I", 1),      # P  increments while the program's physics runs
    ("prog_state", "B", 1),     # P  see STATE_*
    ("run_seq", "I", 1),        # P  bumped each time the program (re)starts after RESET
    ("speaker_freq", "f", 1),   # P  note being played (Hz, 0 = none)
    ("speaker_label", "32s", 1),  # P  what is being played (e.g. "C4" or "Sound.HAPPY")
    ("prog_name", "64s", 1),    # P  script file name
    ("message", "120s", 1),     # P  last error / status text
    ("pose", "f", 3),           # P  x, y (cm), heading (deg, 0 = facing right, 90 = facing down)
    ("motors", "f", 2),         # P  left, right (-100..100) as last written over I2C
    ("wheel_v", "f", 2),        # P  real wheel speeds, left/right (cm/s), after motor mismatch
    ("line", "B", 2),           # P  left, right line sensor (0 = black line, 1 = white)
    ("sonar_cm", "f", 1),       # P  distance ahead (cm)
    ("sonar_active", "B", 1),   # P  1 once the program has triggered the sonar
    ("display", "B", 25),       # P  LED brightness 0..9, row by row
    ("lights", "B", 6),         # P  headlights: left RGB, right RGB
    ("neopixels", "B", 6),      # P  bottom NeoPixels: left RGB, right RGB
    ("held", "B", 1),           # P  1 while the program waits for GO
    ("line_hold", "B", 1),      # P  1 while the program is stopped at a line (paused)
    ("auto_pause_seq", "I", 1), # P  bumped when the program paused itself (pause_on)
    ("auto_pause_why", "40s", 1),  # P  why: "motor command", "line sensor", "bump"
    ("run_time", "f", 1),       # P  simulated seconds since the program (re)started
    ("accel_now", "f", 3),      # P  accelerometer as the program sees it (mg), for the window
    ("bumps", "I", 1),          # P  collisions so far (each new contact counts once)
    ("trace_on", "B", 1),       # P  1 = cur_line is being updated (off while debugging)
    ("cur_line", "I", 1),       # P  line of the student's file being run (0 = none)
    ("prog_path", "260s", 1),   # P  full path of the student's file
    ("cmd_n", "I", 1),          # P  motor commands written so far
    ("cmd_log", "f", 5 * 32),   # P  ring of (time s, left, right, line, main line)
    ("radio_on", "B", 1),       # P
    ("radio_group", "B", 1),    # P
    ("radio_channel", "B", 1),  # P
    ("tx_wr", "I", 1),          # P  radio messages sent by the program (total)
    ("tx_msgs", "B", 16 * 256), # P  ring of RADIO_SLOTS slots
]

STATE_NONE, STATE_RUNNING, STATE_FINISHED, STATE_ERROR = 0, 1, 2, 3

_LAYOUT = {}
_off = 0
for _name, _code, _count in _FIELDS:
    _fmt = "<" + (_code if _code.endswith("s") else f"{_count}{_code}")
    _LAYOUT[_name] = (_off, _fmt, _count)
    _off += struct.calcsize(_fmt)
SIZE = _off

# The name includes a fingerprint of the field layout: a window and a program from different
# versions of the simulator never share a block (they would read each other's fields wrongly).
import zlib as _zlib  # noqa: E402

_FINGERPRINT = _zlib.crc32(repr(_FIELDS).encode()) & 0xFFFF
SHM_NAME = (f"lsbu_cutebot_sim_{_FINGERPRINT:04x}"
            + os.environ.get("CUTEBOT_SIM_INSTANCE", "")[:12])


class Shared:
    """Typed access to the shared block."""

    def __init__(self, shm):
        self.shm = shm
        self.buf = shm.buf

    # --- creation / attachment -------------------------------------------------
    @classmethod
    def create(cls):
        """Window side: create (or take over a stale) block."""
        try:
            shm = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=SIZE)
        except FileExistsError:
            # Leftover from a crashed window.
            if sys.platform == "win32":
                # Windows keeps the block while any program still has it open:
                # reuse it.
                shm = _attach_raw()
            else:
                old = _attach_raw()
                old.close()
                old.unlink()
                shm = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=SIZE)
        shm.buf[:SIZE] = bytes(SIZE)
        s = cls(shm)
        s.set("magic", MAGIC)
        return s

    @classmethod
    def attach(cls):
        """Program side: attach to the window's block, or return None."""
        try:
            shm = _attach_raw()
        except (FileNotFoundError, OSError, ValueError):
            return None
        if shm.size < SIZE:
            shm.close()
            return None
        s = cls(shm)
        if s.get("magic") != MAGIC:
            shm.close()
            return None
        return s

    def close(self):
        self.buf = None
        try:
            self.shm.close()
        except Exception:
            pass

    # --- field access ----------------------------------------------------------
    def get(self, name):
        off, fmt, count = _LAYOUT[name]
        vals = struct.unpack_from(fmt, self.buf, off)
        if fmt.endswith("s"):
            return vals[0].split(b"\0", 1)[0].decode("utf-8", "replace")
        return vals[0] if count == 1 else list(vals)

    def set(self, name, value):
        off, fmt, count = _LAYOUT[name]
        if fmt.endswith("s"):
            size = struct.calcsize(fmt)
            data = str(value).encode("utf-8")[: size - 1]
            struct.pack_into(fmt, self.buf, off, data)
        elif count == 1:
            struct.pack_into(fmt, self.buf, off, value)
        else:
            struct.pack_into(fmt, self.buf, off, *value)

    def get_slice(self, name, n):
        """First ``n`` values of an array field (faster than get() for big arrays)."""
        off, fmt, count = _LAYOUT[name]
        code = fmt[-1]
        n = max(0, min(n, count))
        return list(struct.unpack_from(f"<{n}{code}", self.buf, off))

    def raw(self, name):
        """(offset, size) of a field, for direct access to ``self.buf``."""
        off, fmt, _ = _LAYOUT[name]
        return off, struct.calcsize(fmt)

    # --- radio message rings (one writer, one reader each) ---------------------------
    def ring_put(self, ring, counter, data, group, channel):
        off, _ = self.raw(ring)
        n = self.get(counter)
        slot = off + (n % RADIO_SLOTS) * RADIO_SLOT
        data = bytes(data)[:RADIO_MAX]
        self.buf[slot:slot + 4] = bytes((len(data), group & 0xFF, channel & 0xFF, 0))
        self.buf[slot + 4:slot + 4 + len(data)] = data
        self.set(counter, (n + 1) & 0xFFFFFFFF)

    def ring_get(self, ring, counter, read_pos):
        """Messages after ``read_pos``: returns (new_read_pos, [(data, group, channel), ...])."""
        off, _ = self.raw(ring)
        wr = self.get(counter)
        if (wr - read_pos) & 0xFFFFFFFF > RADIO_SLOTS:
            read_pos = (wr - RADIO_SLOTS) & 0xFFFFFFFF        # lost the oldest ones
        out = []
        while read_pos != wr:
            slot = off + (read_pos % RADIO_SLOTS) * RADIO_SLOT
            n, group, channel = self.buf[slot], self.buf[slot + 1], self.buf[slot + 2]
            out.append((bytes(self.buf[slot + 4:slot + 4 + n]), group, channel))
            read_pos = (read_pos + 1) & 0xFFFFFFFF
        return read_pos, out

    def bump(self, name):
        self.set(name, (self.get(name) + 1) & 0xFFFFFFFF)


def _attach_raw():
    """Attach without letting Python's resource tracker delete the block when
    the program exits (the window owns it)."""
    if sys.version_info >= (3, 13):
        return shared_memory.SharedMemory(name=SHM_NAME, track=False)
    shm = shared_memory.SharedMemory(name=SHM_NAME)
    if sys.platform != "win32":
        try:
            from multiprocessing import resource_tracker

            resource_tracker.unregister(shm._name, "shared_memory")  # noqa: SLF001
        except Exception:
            pass
    return shm


# --- the world (arena, lines, obstacles) -------------------------------------------------
def write_world(s, m):
    """Window side: publish a maps.Map (seqlock: readers retry if it changes underneath)."""
    nan = float("nan")
    flat = []
    for stroke in m.lines:
        if flat:
            flat.extend((nan, nan))
        for x, y in stroke:
            flat.extend((x, y))
    if len(flat) > MAX_LINE_FLOATS:
        raise ValueError("line too long")
    obs = [v for b in m.obstacles[:MAX_OBSTACLES] for v in b]
    seq = s.get("world_seq")
    s.set("world_seq", (seq | 1) + (0 if seq & 1 else 0))     # make it odd: writing
    s.set("arena", (m.width, m.height))
    s.set("line_width", m.line_width)
    s.set("start", m.start)
    s.set("obs_count", len(obs) // 4)
    if obs:
        off, fmt, _ = _LAYOUT["obs"]
        struct.pack_into(f"<{len(obs)}f", s.buf, off, *obs)
    s.set("wline_n", len(flat))
    if flat:
        off, fmt, _ = _LAYOUT["wline"]
        struct.pack_into(f"<{len(flat)}f", s.buf, off, *flat)
    s.set("world_seq", (s.get("world_seq") + 1) & 0xFFFFFFFF)  # even again: done


def read_world(s):
    """Program side: returns (seq, maps.Map) or None if the window is mid-write / no world yet."""
    from . import maps

    seq = s.get("world_seq")
    if seq == 0 or seq & 1:
        return None
    w, h = s.get("arena")
    lw = s.get("line_width")
    start = s.get("start")
    n_obs = s.get("obs_count")
    obs = s.get_slice("obs", 4 * n_obs)
    flat = s.get_slice("wline", s.get("wline_n"))
    if s.get("world_seq") != seq:
        return None
    strokes, cur = [], []
    for i in range(0, len(flat) - 1, 2):
        x, y = flat[i], flat[i + 1]
        if x != x:
            if len(cur) >= 2:
                strokes.append(cur)
            cur = []
        else:
            cur.append((x, y))
    if len(cur) >= 2:
        strokes.append(cur)
    boxes = [tuple(obs[i * 4:i * 4 + 4]) for i in range(n_obs)]
    return seq, maps.Map("Custom", w, h, start, strokes, boxes, lw)

_names = [f[0] for f in _FIELDS]
assert len(_names) == len(set(_names)), "duplicate shared-memory field name"
