from microbit import *
import utime
import time

# Define the pins for the trigger and echo of the ultrasonic sensor
trigger_pin = pin8
echo_pin = pin12
echo_timeout_us = 5
distance_cm = 100

def get_distance():
    pulse_time = 0
    trigger_pin.write_digital(1)
    utime.sleep_us(10)
    trigger_pin.write_digital(0)

    # Wait until the echo pin is high
    while echo_pin.read_digital() == 0:
        pass

    if echo_pin.read_digital() == 1:
        start = utime.ticks_us()
        while echo_pin.read_digital() == 1:
            pass
        finish = utime.ticks_us()
        pulse_time = finish - start

    # To calculate the distance we get the pulse_time and divide it by 2
    # the sound speed on air (343.2 m/s), that It's equivalent to
    # 0.034320 cm/us
    distance = pulse_time * 0.034 / 2
    return round(distance)

while True:
    distance_cm = get_distance()
    sleep(100)
    print(distance_cm)