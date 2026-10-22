# Drive the Cutebot with the motor and headlight registers (Elecfreaks mapping).
# Try it on the "Empty arena" track.
from microbit import *

CAR = 0x10            # I2C address of the Cutebot controller
LEFT_MOTOR = 0x01
RIGHT_MOTOR = 0x02
LEFT_LIGHT = 0x04
RIGHT_LIGHT = 0x08


def motors(left, right):
    """Speeds -100..100. Positive = forward."""
    for reg, speed in ((LEFT_MOTOR, left), (RIGHT_MOTOR, right)):
        direction = 0x02 if speed >= 0 else 0x01
        i2c.write(CAR, bytearray([reg, direction, min(abs(speed), 100), 0]))


def lights(light, r, g, b):
    i2c.write(CAR, bytearray([light, r, g, b]))


lights(LEFT_LIGHT, 0, 0, 255)
lights(RIGHT_LIGHT, 0, 0, 255)

for side in range(4):          # drive a square
    display.show(side + 1)
    motors(40, 40)             # straight
    sleep(1500)
    motors(30, -30)            # spin right on the spot
    sleep(640)

motors(0, 0)
lights(LEFT_LIGHT, 0, 0, 0)
lights(RIGHT_LIGHT, 0, 0, 0)
display.show(Image.YES)
