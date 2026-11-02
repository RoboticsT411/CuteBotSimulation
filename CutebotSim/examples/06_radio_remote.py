# Radio remote control. The robot listens on group 1 and drives on commands:
#   F = forward, B = backward, L = left, R = right, S = stop
# In the simulator open "Radio" (toolbar), type F and press Send.
# On real hardware a second micro:bit can send them with radio.send("F").
from microbit import *
import radio


def motors(left, right):
    for reg, v in ((0x01, left), (0x02, right)):
        i2c.write(0x10, bytearray([reg, 0x02 if v >= 0 else 0x01, min(abs(v), 100), 0]))


radio.on()
radio.config(group=1)
moves = {"F": (40, 40), "B": (-30, -30), "L": (-20, 20), "R": (20, -20), "S": (0, 0)}
display.show(Image.HAPPY)
while True:
    msg = radio.receive()
    if msg in moves:
        motors(*moves[msg])
        display.show(msg)
        radio.send("ok " + msg)        # reply, so the sender knows it arrived
    sleep(20)
