from microbit import *
import math

def motors(left, right):
    for reg, v in ((0x01, left), (0x02, right)):
        i2c.write(0x10, bytearray([reg, 0x02 if v >= 0 else 0x01, min(abs(v), 100), 0]))

accelerometer.set_range(8)          # V2: measure up to 8 g so hard knocks are not cut off
sleep(500)
base_x = accelerometer.get_x()      # resting values (robot still, on flat ground)
base_z = accelerometer.get_z()
LIMIT = 1500                        # mg - try different values on your robot

motors(40, 40)
while True:
    dx = accelerometer.get_x() - base_x
    dz = accelerometer.get_z() - base_z
    if math.sqrt(dx * dx + dz * dz) > LIMIT:
        motors(0, 0)
        angle = math.degrees(math.atan2(dx, dz))     # 0 = along z, +/-90 = from the side
        print("CRASH  x", dx, " z", dz, " angle", int(angle))
        if abs(dz) > abs(dx):
            display.show(Image.ARROW_N if dz > 0 else Image.ARROW_S)
        else:
            display.show(Image.ARROW_E if dx > 0 else Image.ARROW_W)
        break
    sleep(5)                        # check often: a bump only lasts a few milliseconds