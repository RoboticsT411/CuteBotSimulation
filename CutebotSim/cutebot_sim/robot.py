"""Model of the Elecfreaks Cutebot and its physics.

Hardware behaviour reproduced (what the LSBU labs use):

* I2C device at address 0x10 (the Cutebot's motor/light controller)
    [0x01, dir, speed, 0]  -> LEFT motor   (Elecfreaks mapping)
    [0x02, dir, speed, 0]  -> RIGHT motor
        dir 0x02 = forward, 0x01 = backward, speed 0..100 (%)
    [0x04, R, G, B]        -> left headlight
    [0x08, R, G, B]        -> right headlight
* pin13 / pin14 -> left / right line sensor, read_digital() is 0 over the
  black line and 1 over white (this is what Lab 8's code expects).
* pin8 (trigger) / pin12 (echo) -> HC-SR04 style ultrasonic sensor.
* pin15 -> the two NeoPixels under the robot.

The robot's size is set by the measurements in the "robot geometry" block
below (default: 8.5 x 8.5 cm, like the real Cutebot).  Speed and motor response
are approximations; change them if you calibrate against a real Cutebot.
"""

import math
import threading
import time

from . import maps

CUTEBOT_I2C_ADDR = 0x10

# --- robot geometry (cm) ------------------------------------------------------------
# Measure your Cutebot and change these numbers; everything else (physics,
# sensors, collisions and the drawing) is derived from them.
# Positions "ahead" are measured from the wheel axle, forwards positive.
ROBOT_LENGTH_CM = 8.5        # overall: rear edge to the front of the ultrasonic sensor
ROBOT_WIDTH_CM = 8.5         # overall: outside of left wheel to outside of right wheel
WHEEL_DIAMETER_CM = 4.2
WHEEL_WIDTH_CM = 1.2
AXLE_FROM_REAR_CM = 3.3      # rear edge of the robot to the wheel axle
LINE_SENSOR_AHEAD_CM = 3.8   # line sensors: distance in front of the axle
LINE_SENSOR_GAP_CM = 1.6     # distance between left and right line sensor
SONAR_DEPTH_CM = 0.8         # how far the ultrasonic module sticks out at the front

# derived
WHEEL_TRACK_CM = ROBOT_WIDTH_CM - WHEEL_WIDTH_CM           # wheel centre to wheel centre
REAR_CM = -AXLE_FROM_REAR_CM
FRONT_CM = ROBOT_LENGTH_CM - AXLE_FROM_REAR_CM
SONAR_AHEAD_CM = FRONT_CM                                  # where the sound leaves the sensor
BODY_CENTRE_AHEAD_CM = (REAR_CM + FRONT_CM) / 2.0          # collision circle centre
BODY_RADIUS_CM = 0.53 * max(ROBOT_LENGTH_CM, ROBOT_WIDTH_CM)  # collision radius

# --- motion (cm, s) -----------------------------------------------------------------
CM_PER_S_AT_100 = 30.0       # top speed at 100 %
MOTOR_TAU_S = 0.08           # motor response time constant (inertia)


def robot_shape():
    """Outline of the robot for drawing, in robot coordinates (ahead, left), cm."""
    half_w = ROBOT_WIDTH_CM / 2.0
    chassis_w = half_w - WHEEL_WIDTH_CM - 0.1               # chassis half width (between wheels)
    body_front = FRONT_CM - SONAR_DEPTH_CM
    ch = min(1.2, chassis_w * 0.4)                          # chamfer on the front corners
    r_wheel = WHEEL_DIAMETER_CM / 2.0
    board_len = min(5.2, ROBOT_LENGTH_CM * 0.55)
    board_w = min(4.2, chassis_w * 2 * 0.8) / 2.0
    b0 = REAR_CM + 0.6
    return {
        "body": [(REAR_CM, chassis_w), (body_front - ch, chassis_w), (body_front, chassis_w - ch),
                 (body_front, -(chassis_w - ch)), (body_front - ch, -chassis_w),
                 (REAR_CM, -chassis_w)],
        "wheels": [[(-r_wheel, side * (chassis_w + 0.1)), (r_wheel, side * (chassis_w + 0.1)),
                    (r_wheel, side * half_w), (-r_wheel, side * half_w)] for side in (1, -1)],
        "sonar": [(body_front, chassis_w * 0.8), (FRONT_CM, chassis_w * 0.8),
                  (FRONT_CM, -chassis_w * 0.8), (body_front, -chassis_w * 0.8)],
        "board": [(b0, board_w), (b0 + board_len, board_w), (b0 + board_len, -board_w),
                  (b0, -board_w)],
        "lights": [(body_front - 0.5, side * (chassis_w - 0.6)) for side in (1, -1)],
        "light_r": 0.55,
        "neopixels": [(REAR_CM + 1.2, side * 1.6) for side in (1, -1)],
        "glow_r": 2.4,
        "sensor_r": 0.4,
    }


SPEED_OF_SOUND_CM_PER_S = 34320.0
SONAR_MAX_CM = 400.0
SONAR_MIN_CM = 2.0


class Cutebot:
    def __init__(self, world=None):
        self.lock = threading.RLock()
        self.map = world if world is not None else maps.get_map(0)
        self.motor_cmd = [0.0, 0.0]      # % as last written over I2C
        self.motor_gain = [1.0, 1.0]     # simulated motor mismatch (1.0 = exact)
        self.wheel_v = [0.0, 0.0]        # actual wheel speeds, cm/s
        self.lights = [0, 0, 0, 0, 0, 0]
        self.neopixels = [0, 0, 0, 0, 0, 0]
        self.sonar_active = False
        self._echo = None                # (t_start, t_end) of the current echo pulse
        self._echo_seen = None           # the pulse the program has already seen go high
        self._trigger_level = 0
        self.x = self.y = self.heading = 0.0
        self.reset_to_start()

    # --- pose -------------------------------------------------------------------
    def reset_to_start(self):
        with self.lock:
            x, y, h = self.map.start
            self.set_pose(x, y, h)

    def set_pose(self, x, y, heading_deg):
        with self.lock:
            self.x, self.y = float(x), float(y)
            self.heading = math.radians(heading_deg)
            self.wheel_v = [0.0, 0.0]

    def set_map(self, world, reset=False):
        with self.lock:
            self.map = world
            if reset:
                self.reset_to_start()
            else:
                self._collide()

    def _local(self, ahead, left):
        """World position of a point given in robot coordinates."""
        c, s = math.cos(self.heading), math.sin(self.heading)
        # left of the robot is (sin h, -cos h) because y points down
        return (self.x + ahead * c + left * s, self.y + ahead * s - left * c)

    # --- physics -----------------------------------------------------------------
    def step(self, dt):
        dt = max(0.0, min(dt, 0.05))
        if dt == 0.0:
            return
        with self.lock:
            k = min(1.0, dt / MOTOR_TAU_S)
            for i in (0, 1):
                target = self.motor_cmd[i] / 100.0 * CM_PER_S_AT_100 * self.motor_gain[i]
                self.wheel_v[i] += (target - self.wheel_v[i]) * k
            vl, vr = self.wheel_v
            v = (vl + vr) / 2.0
            # y points down, so a faster right wheel turns the robot left (heading decreases)
            w = (vl - vr) / WHEEL_TRACK_CM
            h_mid = self.heading + w * dt / 2.0
            self.x += v * math.cos(h_mid) * dt
            self.y += v * math.sin(h_mid) * dt
            self.heading = (self.heading + w * dt + math.pi) % (2 * math.pi) - math.pi
            self._collide()

    def _collide(self):
        r = BODY_RADIUS_CM
        for _ in range(3):
            cx, cy = self._local(BODY_CENTRE_AHEAD_CM, 0.0)
            moved = False
            for x0, y0, x1, y1 in self.map.solid_boxes():
                px = min(max(cx, x0), x1)
                py = min(max(cy, y0), y1)
                dx, dy = cx - px, cy - py
                d2 = dx * dx + dy * dy
                if d2 < r * r:
                    if d2 > 1e-12:
                        d = math.sqrt(d2)
                        push = r - d
                        self.x += dx / d * push
                        self.y += dy / d * push
                    else:  # centre inside the box: push out along the shortest side
                        opts = [(cx - x0, -1, 0), (x1 - cx, 1, 0), (cy - y0, 0, -1), (y1 - cy, 0, 1)]
                        dist, sx, sy = min(opts)
                        self.x += sx * (dist + r)
                        self.y += sy * (dist + r)
                    moved = True
            if not moved:
                break

    # --- sensors -----------------------------------------------------------------
    def line_sensor_positions(self):
        g = LINE_SENSOR_GAP_CM / 2.0
        return (self._local(LINE_SENSOR_AHEAD_CM, g), self._local(LINE_SENSOR_AHEAD_CM, -g))

    def line_sensors(self):
        """(left, right) digital values: 0 = over the black line, 1 = white."""
        with self.lock:
            (lx, ly), (rx, ry) = self.line_sensor_positions()
            return (0 if self.map.is_black(lx, ly) else 1,
                    0 if self.map.is_black(rx, ry) else 1)

    def sonar_distance(self):
        with self.lock:
            sx, sy = self._local(SONAR_AHEAD_CM, 0.0)
            d = self.map.raycast(sx, sy, self.heading, SONAR_MAX_CM)
            return max(SONAR_MIN_CM, d)

    # --- ultrasonic sensor on pins 8 / 12 ---------------------------------------------
    def trigger_write(self, level):
        """pin8.write_digital(level): a falling edge starts a measurement."""
        level = 1 if level else 0
        if self._trigger_level == 1 and level == 0:
            self.sonar_active = True
            d = self.sonar_distance()
            now = time.perf_counter()
            start = now + 0.0005              # the module sends its 40 kHz burst first
            width = 0.038 if d >= SONAR_MAX_CM else 2.0 * d / SPEED_OF_SOUND_CM_PER_S
            self._echo = (start, start + width)
        self._trigger_level = level

    def echo_read(self):
        """pin12.read_digital(): 1 while the echo pulse is high.

        The pulse length is counted from the moment the program first sees the
        pin go high, so a delay on the PC before that (thread switching) does not
        add to the measured distance.
        """
        echo = self._echo
        if echo is None:
            return 0
        now = time.perf_counter()
        start, end = echo
        if now < start:
            return 0
        if self._echo_seen is not echo:
            # first time the program sees it high: the pulse starts now
            echo = (now, now + (end - start))
            self._echo = self._echo_seen = echo
            return 1
        return 1 if now < echo[1] else 0

    # --- I2C ----------------------------------------------------------------------------
    def i2c_write(self, data):
        data = bytes(data)
        if not data:
            return
        reg = data[0]
        with self.lock:
            if reg in (0x01, 0x02) and len(data) >= 3:
                direction, speed = data[1], min(int(data[2]), 100)
                value = float(speed) if direction == 0x02 else -float(speed) if direction == 0x01 else 0.0
                self.motor_cmd[0 if reg == 0x01 else 1] = value
            elif reg in (0x04, 0x08) and len(data) >= 4:
                base = 0 if reg == 0x04 else 3
                self.lights[base:base + 3] = list(data[1:4])
            # other registers (servos, version, ...) are ignored

    def set_neopixels(self, pixels):
        with self.lock:
            flat = []
            for p in list(pixels)[:2]:
                flat.extend(int(max(0, min(255, c))) for c in tuple(p)[:3])
            flat.extend([0] * (6 - len(flat)))
            self.neopixels = flat
