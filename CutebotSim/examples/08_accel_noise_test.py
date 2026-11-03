# How much does the accelerometer move while the robot just drives (no crash)?
# Run it on the real robot with the serial monitor connected. Every half second it prints the
# biggest change in x and z. Set LIMIT in 07_crash_detect.py well above these numbers
# (about 1.5x the biggest), but below what you see when you bump it on purpose.
# Press A to stop.
from microbit import *


def motors(left, right):
    for reg, v in ((0x01, left), (0x02, right)):
        i2c.write(0x10, bytearray([reg, 0x02 if v >= 0 else 0x01, min(abs(v), 100), 0]))


sleep(500)
base_x = accelerometer.get_x()
base_z = accelerometer.get_z()
for s in range(0, 41, 5):           # soft start
    motors(s, s)
    sleep(40)

peak_x = peak_z = 0
t = running_time()
while not button_a.was_pressed():
    peak_x = max(peak_x, abs(accelerometer.get_x() - base_x))
    peak_z = max(peak_z, abs(accelerometer.get_z() - base_z))
    if running_time() - t >= 500:
        print("biggest change  x", peak_x, "  z", peak_z)
        peak_x = peak_z = 0
        t = running_time()
    sleep(5)
motors(0, 0)
