# Put this on a SECOND micro:bit plugged into the PC by USB.
# It receives the robot's radio messages (09_crash_debug.py) and prints them to serial,
# so tools/accel_monitor.py (or the uploader's serial monitor) can show them.
from microbit import *
import radio

radio.on()
radio.config(group=7, length=64)    # must match the robot
display.show(Image.YES)
while True:
    msg = radio.receive()
    if msg:
        print(msg)
        display.set_pixel(2, 2, 9 if display.get_pixel(2, 2) == 0 else 0)   # blink on data
    else:
        sleep(1)
