"""Quick self-check of the simulated micro:bit API (no window needed).

Run from the project folder:  python tests/smoke_test.py
"""
import os
import sys

os.environ["CUTEBOT_SIM_HEADLESS"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from microbit import *  # noqa: E402,F403
import machine  # noqa: E402
import neopixel  # noqa: E402
import utime  # noqa: E402
from cutebot_sim import runtime  # noqa: E402

rt = runtime.get()
ok = 0


def check(cond, what):
    global ok
    if not cond:
        raise AssertionError(what)
    ok += 1


check(Image("00300:" "03630:" "36963:" "03630:" "00300").get_pixel(2, 2) == 9, "Image from string")
display.show(Image.HAPPY)
check(display.get_pixel(1, 1) == 9, "display.show(Image)")
display.show(7)
check([display.get_pixel(x, 0) for x in range(5)] == [9] * 5, "display.show(int) uses the font")
try:
    Image.HEART.set_pixel(0, 0, 9)
    check(False, "built-in images are read-only")
except TypeError:
    ok += 1
try:
    i2c.write(0x20, b"\x00")
    check(False, "unknown I2C address raises OSError")
except OSError:
    ok += 1

# motors: Elecfreaks mapping 0x01 = left, 0x02 = right
i2c.write(0x10, bytearray([0x01, 0x02, 50, 0]))
i2c.write(0x10, bytearray([0x02, 0x01, 20, 0]))
check(rt.robot.motor_cmd == [50.0, -20.0], "motor registers")
i2c.write(0x10, bytearray([0x04, 255, 0, 0]))
check(rt.robot.lights[:3] == [255, 0, 0], "headlight register")
x0 = rt.robot.x
i2c.write(0x10, bytearray([0x02, 0x02, 50, 0]))
sleep(500)
check(rt.robot.x != x0, "robot moves")
i2c.write(0x10, bytearray([0x01, 0x02, 0, 0]))
i2c.write(0x10, bytearray([0x02, 0x02, 0, 0]))

rt.robot.reset_to_start()
check(pin13.read_digital() in (0, 1) and pin14.read_digital() in (0, 1), "line sensors")

pin8.write_digital(1)
utime.sleep_us(10)
pin8.write_digital(0)
t = machine.time_pulse_us(pin12, 1, 25000)
expected = rt.robot.sonar_distance()
check(abs(t * 0.0343 / 2 - expected) < 3, "sonar echo timing")

np = neopixel.NeoPixel(pin15, 2)
np[0] = (255, 0, 0)
np.show()
check(rt.robot.neopixels[:3] == [255, 0, 0], "NeoPixels on pin15")

print(f"OK - {ok} checks passed")
