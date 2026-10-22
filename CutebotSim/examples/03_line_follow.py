# Line following with the two line sensors (pin13 = left, pin14 = right).
# A sensor reads 0 over the black line and 1 over white.
# Use the "Line track (oval)" or "Figure eight" track.
from microbit import *

CAR = 0x10


def motors(left, right):
    for reg, speed in ((0x01, left), (0x02, right)):
        direction = 0x02 if speed >= 0 else 0x01
        i2c.write(CAR, bytearray([reg, direction, min(abs(speed), 100), 0]))


while True:
    left = pin13.read_digital()
    right = pin14.read_digital()
    if left == 0 and right == 0:      # both on the line: go straight
        motors(30, 30)
        display.show(Image.ARROW_N)
    elif left == 0:                   # line is to the left: turn left
        motors(10, 45)
        display.show(Image.ARROW_W)
    elif right == 0:                  # line is to the right: turn right
        motors(45, 10)
        display.show(Image.ARROW_E)
    # both sensors off the line: keep doing the last thing
