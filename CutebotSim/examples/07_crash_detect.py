# Crash detector with the micro:bit standing upright on the Cutebot (display facing forward).
#
# A driving Cutebot SHAKES: the micro:bit rocks in its slot, so the readings jump around by
# hundreds of mg.  When it hits something it stalls against it and the shaking STOPS.
# So the robot knows it has crashed when the motors are on but the shaking has stopped.
# It then shows where it was hit, from the biggest jolt just before:
#   F = front, B = back, L = left side, R = right side, S = stalled (no clear jolt).
# (Measured on a real Cutebot: driving shake > 180 mg, stalled < 20 mg.)
# Press B to drive, B again after a crash for another run.
# For the data behind it, see 09_crash_debug.py and tools/accel_monitor.py.
from microbit import *

SPEED = 40
QUIET = 50                  # mg: average shake below this = not moving
QUIET_SAMPLES = 10          # 10 samples x 20 ms = quiet for 0.2 s


def motors(left, right):
    for reg, v in ((0x01, left), (0x02, right)):
        i2c.write(0x10, bytearray([reg, 0x02 if v >= 0 else 0x01, min(abs(v), 100), 0]))


def drive_until_crash():
    base_x, base_z = accelerometer.get_x(), accelerometer.get_z()
    display.show(Image.HAPPY)
    for s in range(0, SPEED + 1, 5):        # soft start
        motors(s, s)
        sleep(40)
    start = running_time()
    shakes = []                             # how much the reading changed, every 20 ms
    jolts = []                              # (dx, dz) every 20 ms, last 0.5 s
    last = (0, 0)
    moved = False
    while True:
        dx = accelerometer.get_x() - base_x
        dz = accelerometer.get_z() - base_z
        shakes.append(abs(dx - last[0]) + abs(dz - last[1]))
        jolts.append((dx, dz))
        last = (dx, dz)
        shakes = shakes[-QUIET_SAMPLES:]
        jolts = jolts[-35:]
        if len(shakes) == QUIET_SAMPLES:
            level = sum(shakes) / QUIET_SAMPLES
            if level > 3 * QUIET:
                moved = True                # it really is driving
            if level < QUIET and (moved or running_time() - start > 1500):
                motors(0, 0)
                before = jolts[:-QUIET_SAMPLES]   # the jolt happened just before the quiet
                hx, hz = max(before or [(0, 0)], key=lambda j: abs(j[0]) + abs(j[1]))
                if abs(hx) + abs(hz) < 150:
                    return "S"
                if abs(hz) >= abs(hx):
                    return "F" if hz > 0 else "B"
                return "L" if hx > 0 else "R"
        sleep(20)


motors(0, 0)
display.show("B")
while True:
    if button_b.was_pressed():
        letter = drive_until_crash()
        display.show(letter)
        print("CRASH", letter)
    sleep(50)
