# Obstacle avoidance with the ultrasonic sensor (trigger pin8, echo pin12).
# Use the "Obstacles (sonar)" track.
from microbit import *
import machine
import utime

CAR = 0x10


def motors(left, right):
    for reg, speed in ((0x01, left), (0x02, right)):
        direction = 0x02 if speed >= 0 else 0x01
        i2c.write(CAR, bytearray([reg, direction, min(abs(speed), 100), 0]))


def distance_cm():
    pin8.write_digital(1)
    utime.sleep_us(10)
    pin8.write_digital(0)
    pulse = machine.time_pulse_us(pin12, 1, 25000)   # echo time in microseconds
    if pulse < 0:
        return 400                                   # nothing in range
    return pulse * 0.0343 / 2


while True:
    d = distance_cm()
    if d < 15:
        motors(-30, -30)          # back off
        sleep(300)
        motors(35, -35)           # turn right
        sleep(350)
    else:
        motors(40, 40)
    sleep(40)
