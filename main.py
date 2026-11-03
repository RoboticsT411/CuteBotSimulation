from microbit import *

SPEED = 40
KP = 1.0            # motor speed change per degree off course (try 0.5-2)

def motors(left, right):
    for reg, v in ((0x01, left), (0x02, right)):
        v = max(-100, min(100, int(v)))
        i2c.write(0x10, bytearray([reg, 0x02 if v >= 0 else 0x01, abs(v), 0]))

if not compass.is_calibrated():
    compass.calibrate()             # tilt the micro:bit until the screen fills

display.show("B")
while not button_b.was_pressed():
    sleep(20)

target = compass.heading()          # keep the direction it faces now
display.show(Image.HAPPY)
while not button_a.was_pressed():   # A stops
    error = (compass.heading() - target + 180) % 360 - 180   # + = turned right
    c = KP * error
    motors(SPEED - c, SPEED + c)    # turned right -> speed up the right wheel
    sleep(20)
motors(0, 0)
display.show(Image.YES)