# Crash detector for the Cutebot (micro:bit standing upright, display facing forward),
# with a data stream for debugging.
#
# How it knows it crashed: a driving Cutebot SHAKES (the micro:bit rocks in its slot, by
# hundreds of mg).  When it hits something it stalls against it and the shaking STOPS.
# So: motors on + no shaking for 0.2 s = crash.  The direction comes from the biggest jolt
# just before it went quiet:  F = front, B = back, L = left side, R = right side,
# S = stalled with no clear jolt (it pushed slowly into something).
# (A single big reading is NOT used: on the real robot normal driving gives those too.)
#
#   1. Upload, connect the serial monitor (tools/accel_monitor.py), press the reset button.
#   2. Press B: the robot drives.  It stops and shows the letter when it crashes.
#   3. Press B again for another run.
#   Button A marks mistakes in the log:
#     * it HIT something but kept the happy face  -> A:  MISSED  (shows ?)
#     * it stopped with a letter but hit NOTHING  -> A:  FALSE   (shows X)
#
# On the REAL robot, every 20 ms it sends:  time_ms,dx,dz,strength,shake
# Events: SOURCE, START, CRASH,time,dx,dz,strength,letter, MISSED, FALSE.
# Over USB serial (print) and by radio (RADIO = True, for 09_radio_receiver.py).
from microbit import *
import math
import microbit
import radio

# Only the simulator's microbit module has "_rt"; anything else is the real micro:bit.
SOURCE = "SIMULATOR" if hasattr(microbit, "_rt") else "REAL"
STREAM = SOURCE == "REAL"          # the simulator has its own Graphs window

RADIO = True
SPEED = 40
QUIET = 50                          # mg: shake below this = not moving (real robot: driving >180, stalled <20)
QUIET_MS = 200                      # ...for this long = crash


def motors(left, right):
    for reg, v in ((0x01, left), (0x02, right)):
        i2c.write(0x10, bytearray([reg, 0x02 if v >= 0 else 0x01, min(abs(v), 100), 0]))


def send(line):
    print(line)
    if RADIO:
        radio.send(line)


if RADIO:
    radio.on()
    radio.config(group=7, length=64)
try:
    accelerometer.set_range(8)      # newer MicroPython: measure up to 8 g
except AttributeError:
    pass                            # older MicroPython (e.g. from uflash): stays at 2 g

motors(0, 0)
send("SOURCE,%s" % SOURCE)
send("LIMIT,%d" % QUIET)
send("READY (%s) - press B to drive" % SOURCE)
display.show("B")

t0 = running_time()
base_x = accelerometer.get_x()
base_z = accelerometer.get_z()
driving = False
drive_start = 0
moved = False                       # has it been shaking (= moving) since the start?
peak = (0, 0, 0)                    # biggest reading in the current 20 ms: dx, dz, strength
last = (0, 0)                       # dx, dz of the previous 20 ms sample
shakes = []                         # shake of the last samples (20 ms each)
recent = []                         # (time, dx, dz, strength) of the last 3 s, per 20 ms
last_crash = None
last_sent = 0

while True:
    now = running_time() - t0
    dx = accelerometer.get_x() - base_x
    dz = accelerometer.get_z() - base_z
    strength = int(math.sqrt(dx * dx + dz * dz))
    if strength >= peak[2]:
        peak = (dx, dz, strength)

    if button_b.was_pressed() and not driving:
        base_x = accelerometer.get_x()      # resting values, robot still
        base_z = accelerometer.get_z()
        send("SOURCE,%s" % SOURCE)
        send("START,%d" % now)
        display.show(Image.HAPPY)
        for s in range(0, SPEED + 1, 5):    # soft start
            motors(s, s)
            sleep(40)
        driving, moved, last_crash = True, False, None
        shakes = []
        drive_start = running_time() - t0

    if button_a.was_pressed():
        big = max(recent, key=lambda r: r[3]) if recent else (now, 0, 0, 0)
        if driving:                         # it hit something and did not notice
            motors(0, 0)
            driving = False
            send("MISSED,%d,%d,%d,%d" % (now, big[1], big[2], big[3]))
            display.show("?")
        elif last_crash is not None:        # it stopped, but there was no crash
            send("FALSE,%d,%d,%d,%d" % last_crash)
            last_crash = None
            display.show("X")

    if now - last_sent >= 20:               # every 20 ms
        shake = abs(dx - last[0]) + abs(dz - last[1])
        last = (dx, dz)
        shakes.append(shake)
        if len(shakes) > QUIET_MS // 20:
            shakes.pop(0)
        recent.append((now, peak[0], peak[1], peak[2]))
        if len(recent) > 150:
            recent.pop(0)
        if STREAM:
            send("%d,%d,%d,%d,%d" % (now, peak[0], peak[1], peak[2], shake))
        peak = (0, 0, 0)
        last_sent = now

        if driving and len(shakes) == QUIET_MS // 20:
            level = sum(shakes) // len(shakes)
            if level > 3 * QUIET:
                moved = True
            stalled = level < QUIET and (moved or now - drive_start > 1500)
            if stalled:
                motors(0, 0)
                driving = False
                # direction: the biggest jolt in the 0.5 s before it went quiet
                window = [r for r in recent if now - 700 <= r[0] <= now - QUIET_MS]
                hit = max(window, key=lambda r: r[3]) if window else (now, 0, 0, 0)
                if hit[3] < 150:
                    letter = "S"            # stalled, no clear jolt (pushed slowly into it)
                elif abs(hit[2]) >= abs(hit[1]):
                    letter = "F" if hit[2] > 0 else "B"
                else:
                    letter = "L" if hit[1] > 0 else "R"
                display.show(letter)
                send("CRASH,%d,%d,%d,%d,%s" % (hit[0], hit[1], hit[2], hit[3], letter))
                last_crash = (hit[0], hit[1], hit[2], hit[3])
    sleep(2)
