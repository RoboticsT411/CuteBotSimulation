# Crash detector with the micro:bit standing upright on the Cutebot (display facing forward).
# The robot drives until the accelerometer feels a bump, stops, and shows where it was hit:
#   F = front, B = back, L = left, R = right.
# In the simulator keep "micro:bit upright on the Cutebot" ticked (Sensors tab) and drive the
# robot into a wall or an obstacle.  On the real robot, tap it gently first to check the signs.
from microbit import *
import math


def motors(left, right):
    for reg, v in ((0x01, left), (0x02, right)):
        i2c.write(0x10, bytearray([reg, 0x02 if v >= 0 else 0x01, min(abs(v), 100), 0]))


accelerometer.set_range(8)          # measure up to 8 g so hard knocks are not cut off
sleep(500)
base_x = accelerometer.get_x()      # resting values (robot still, on level ground)
base_z = accelerometer.get_z()
LIMIT = 600                         # mg: bigger = only hard crashes. Tune it on your robot.

display.show(Image.HAPPY)
motors(40, 40)
while True:
    dx = accelerometer.get_x() - base_x     # + = hit from the LEFT,  - = from the RIGHT
    dz = accelerometer.get_z() - base_z     # + = hit from the FRONT, - = from BEHIND
    strength = math.sqrt(dx * dx + dz * dz)
    if strength > LIMIT:
        motors(0, 0)
        angle = math.degrees(math.atan2(dx, dz))     # 0 = straight ahead, + = to the left
        print("CRASH  x", dx, " z", dz, " strength", int(strength), " angle", int(angle))
        if abs(dz) >= abs(dx):
            display.show("F" if dz > 0 else "B")
        else:
            display.show("L" if dx > 0 else "R")
        break
    sleep(5)                        # check often: a bump only lasts a few milliseconds
