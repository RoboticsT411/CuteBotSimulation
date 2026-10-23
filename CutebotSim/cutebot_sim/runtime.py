"""Runs inside the student's program (started by ``import microbit``).

* finds the simulator window, or starts one,
* runs the robot physics in a background thread (so a breakpoint in the
  student's code pauses the robot too),
* publishes the robot/LED state for the window to draw,
* keeps the robot moving after the script ends, like the real Cutebot,
* restarts the program when the micro:bit's RESET button is pressed in the window
  (in the same process, so PyCharm's Run console and Stop button keep working).

Environment variables:
    CUTEBOT_SIM_HEADLESS=1   no window (used by automated tests)
    CUTEBOT_SIM_TRACE=path   write the robot pose to a CSV file
    CUTEBOT_SIM_MAP=n        preset track number to use in headless mode
    CUTEBOT_SIM_LAYOUT=file  layout .json to use in headless mode
    CUTEBOT_SIM_MOTOR_GAIN=l,r  motor mismatch in headless mode, e.g. 1.0,0.92
"""

import _thread
import atexit
import os
import runpy
import subprocess
import sys
import tempfile
import threading
import time
import traceback

from . import sensors, shared
from .robot import Cutebot

_orig_sleep = time.sleep      # the real time.sleep (time.sleep is patched for RESET)

PHYSICS_HZ = 200
GUI_START_TIMEOUT_S = 20.0
LOG_PATH = os.path.join(tempfile.gettempdir(), "cutebot_sim_window.log")


def _pid_alive(pid):
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)  # signal 0 only checks (POSIX); never call this on Windows
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Runtime:
    def __init__(self):
        self.t0 = time.perf_counter()
        self.headless = os.environ.get("CUTEBOT_SIM_HEADLESS") == "1"
        self.script = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else "<program>"
        self.script_path = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else None
        self.reset_pending = False
        self._reset_seen = 0
        self._user_code = True       # the student's code is running in the main thread
        # sensors (values come from the window; these are the defaults without it)
        self._pulse_seen = 0
        self._pulse = ("", 0.0)               # (gesture name, start time)
        self.gesture_now = "face up"
        self.gesture_history = []             # gestures since get_gestures()
        self.gesture_flags = set()            # gestures since was_gesture(name)
        self.sound_event_now = "quiet"
        self.sound_history = []
        self.sound_flags = set()
        self.loud_threshold = 128
        self.quiet_threshold = 64
        self.speaker_on = True
        self.robot = Cutebot()
        self.display_buf = bytearray(25)
        self.shared = None
        self.gen = 0
        self.btn_consumed = {"a": 0, "b": 0}
        self._last_pose_req = 0
        self._world_seq = 0
        self._gain_set = False
        self._error_text = None
        self._stop = False
        self._trace = None
        trace_path = os.environ.get("CUTEBOT_SIM_TRACE")
        if trace_path:
            self._trace = open(trace_path, "w", buffering=1)
            self._trace.write("t,x,y,heading_deg,motor_l,motor_r,line_l,line_r\n")

        if not self.headless:
            self._connect()
            if self.shared is not None:
                time.sleep = self.sleep          # interruptible by RESET (main thread only)
        elif os.environ.get("CUTEBOT_SIM_LAYOUT"):
            import json

            from . import maps

            with open(os.environ["CUTEBOT_SIM_LAYOUT"], encoding="utf-8") as fh:
                self.robot.set_map(maps.Map.from_layout(json.load(fh)), reset=True)
        elif os.environ.get("CUTEBOT_SIM_MAP"):
            from . import maps

            self.robot.set_map(maps.get_map(int(os.environ["CUTEBOT_SIM_MAP"])), reset=True)

        if os.environ.get("CUTEBOT_SIM_MOTOR_GAIN"):          # e.g. "1.0,0.92" (tests)
            self.robot.motor_gain = [float(v) for v in os.environ["CUTEBOT_SIM_MOTOR_GAIN"].split(",")]

        self._thread = threading.Thread(target=self._physics_loop, name="cutebot-physics", daemon=True)
        self._thread.start()

        self._prev_excepthook = sys.excepthook
        sys.excepthook = self._excepthook
        atexit.register(self._at_exit)

    # --- connecting to the window --------------------------------------------------
    def _gui_alive(self, s, wait=0.6):
        """True if the window behind ``s`` is updating."""
        if s.get("gui_closing"):
            return False
        if not _pid_alive(s.get("gui_pid")):
            return False
        t1 = s.get("gui_tick")
        deadline = time.time() + wait
        while time.time() < deadline:
            _orig_sleep(0.03)
            if s.get("gui_tick") != t1:
                return True
        return False

    def _connect(self):
        s = shared.Shared.attach()
        if s is not None and not self._gui_alive(s):
            s.close()
            s = None
        if s is None:
            s = self._launch_gui()
        if s is None:
            print("[cutebot-sim] The simulator window could not be started; running without it.\n"
                  f"[cutebot-sim] Details are in {LOG_PATH}", file=sys.stderr)
            return
        self.shared = s
        # Claim the simulator: like flashing a new program onto the micro:bit.
        s.bump("owner_gen")
        self.gen = s.get("owner_gen")
        s.set("owner_pid", os.getpid())
        s.set("prog_name", self.script)
        s.set("message", "")
        s.set("prog_state", shared.STATE_RUNNING)
        for _ in range(50):                  # the window may be mid-update
            if self._read_world(s, reset=True):
                break
            _orig_sleep(0.01)
        self._last_pose_req = s.get("pose_req_seq")
        self._reset_seen = s.get("reset_req")
        s.bump("run_seq")
        # Start where the user last placed the robot (drag/rotate), else at the track start.
        x, y, h = s.get("pose_req")
        if self._last_pose_req and x == x:
            self.robot.set_pose(x, y, h)
        self.btn_consumed = {"a": s.get("btn_a_count"), "b": s.get("btn_b_count")}
        self._publish()

    def _launch_gui(self):
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ)
        env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
        exe = sys.executable
        kwargs = {}
        if sys.platform == "win32":
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(pyw):
                exe = pyw
            # own process group, so the window survives PyCharm's Stop button
            kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                       | 0x01000000)  # CREATE_BREAKAWAY_FROM_JOB
        else:
            kwargs["start_new_session"] = True
        log = open(LOG_PATH, "a")
        cmd = [exe, "-m", "cutebot_sim.gui"]
        try:
            try:
                subprocess.Popen(cmd, env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                 cwd=pkg_root, **kwargs)
            except OSError:
                if sys.platform != "win32":
                    raise
                # breaking away from the job is not allowed here; start normally
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                subprocess.Popen(cmd, env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                 cwd=pkg_root, **kwargs)
        except Exception as e:  # pragma: no cover - reported to the user
            log.write(f"launch failed: {e!r}\n")
            return None
        deadline = time.time() + GUI_START_TIMEOUT_S
        while time.time() < deadline:
            _orig_sleep(0.1)
            s = shared.Shared.attach()
            if s is None:
                continue
            if s.get("gui_tick") > 0 and self._gui_alive(s, wait=1.0):
                return s
            s.close()
        return None

    # --- physics thread ----------------------------------------------------------------
    def _physics_loop(self):
        period = 1.0 / PHYSICS_HZ
        last = time.perf_counter()
        last_trace = 0.0
        while not self._stop:
            _orig_sleep(period)
            # While an ultrasonic echo pulse is being timed by the program (busy
            # loop on pin12), stay idle so we don't steal the GIL and spoil the
            # measurement.  The pulse is at most 38 ms, so the motion is unaffected.
            echo = self.robot._echo
            if echo is not None:
                wait = echo[1] - time.perf_counter() + 0.002
                if 0 < wait < 0.05:
                    _orig_sleep(wait)
            now = time.perf_counter()
            dt, last = now - last, now
            s = self.shared
            if s is not None:
                if not self._check_window(s):
                    return
                if s.get("world_seq") != self._world_seq:
                    self._read_world(s)
                self._update_sensors(s)
                rr = s.get("reset_req")
                if rr != self._reset_seen:
                    self._reset_seen = rr
                    self.request_reset()
                g = s.get("motor_gain")
                if g[0] >= 0 and g[1] >= 0 and (g[0] > 0 or g[1] > 0 or self._gain_set):
                    self.robot.motor_gain = g          # both 0 before the window sets it = ignore
                    self._gain_set = True
                req = s.get("pose_req_seq")
                if req != self._last_pose_req:
                    self._last_pose_req = req
                    x, y, h = s.get("pose_req")
                    if x != x:  # NaN -> back to the start position
                        self.robot.reset_to_start()
                    else:
                        self.robot.set_pose(x, y, h)
            self.robot.step(dt)
            if s is not None:
                self._publish()
            if self._trace is not None and now - last_trace >= 0.02:
                last_trace = now
                r = self.robot
                ll, lr = r.line_sensors()
                self._trace.write(f"{now - self.t0:.3f},{r.x:.2f},{r.y:.2f},"
                                  f"{(r.heading * 57.29578):.1f},{r.motor_cmd[0]:.0f},"
                                  f"{r.motor_cmd[1]:.0f},{ll},{lr}\n")

    def _read_world(self, s, reset=False):
        """Rebuild the arena from the window's world (arena size, lines, obstacles)."""
        got = shared.read_world(s)
        if got is None:
            return False
        self._world_seq, world = got
        self.robot.set_map(world, reset=reset)
        return True

    def _check_window(self, s):
        """Stop this program if the window was closed or another program took over."""
        if s.get("gui_closing"):
            self._quit("Simulator window closed - stopping the program.")
            return False
        if s.get("owner_gen") != self.gen:
            self._quit("Another program was started in the simulator - stopping this one.")
            return False
        return True

    def _quit(self, text):
        self._stop = True
        try:
            sys.stdout.flush()
        except Exception:
            pass
        print(f"\n[cutebot-sim] {text}", file=sys.stderr, flush=True)
        os._exit(0)

    def _publish(self):
        s, r = self.shared, self.robot
        if s is None or s.get("owner_gen") != self.gen:
            return
        with r.lock:
            s.set("pose", (r.x, r.y, r.heading * 57.29577951308232))
            s.set("motors", r.motor_cmd)
            s.set("wheel_v", r.wheel_v)
            s.set("line", r.line_sensors())
            s.set("lights", r.lights)
            s.set("neopixels", r.neopixels)
            s.set("sonar_active", 1 if r.sonar_active else 0)
            s.set("sonar_cm", r.sonar_distance())
        s.set("display", bytes(self.display_buf))
        s.bump("prog_tick")

    # --- buttons ---------------------------------------------------------------------
    def button_down(self, name):
        s = self.shared
        return bool(s.get(f"btn_{name}_down")) if s is not None else False

    def button_take_presses(self, name):
        """Presses since the last call (used by was_pressed / get_presses)."""
        s = self.shared
        if s is None:
            return 0
        total = s.get(f"btn_{name}_count")
        n = (total - self.btn_consumed[name]) & 0xFFFFFFFF
        self.btn_consumed[name] = total
        return n

    # --- sensors ---------------------------------------------------------------------------
    def accel(self):
        """Accelerometer x, y, z in mg (from the window's tilt pad)."""
        s = self.shared
        if s is None or not s.get("sensors_set"):
            x, y, z = 0.0, 0.0, -1024.0
        else:
            x, y, z = s.get("accel")
        name, t = self._pulse
        age = time.perf_counter() - t
        if name and age < sensors.PULSE_S:
            if name == "shake":                  # a big back-and-forth jolt
                k = 1 if int(age * 20) % 2 else -1
                x, y, z = x + k * 1800.0, y - k * 900.0, z
            elif name == "freefall":
                x, y, z = 0.0, 0.0, 0.0
            else:                                # 3g / 6g / 8g
                g = float(name[0]) * 1024.0
                x, y, z = x, y, -g
        return [int(round(x)), int(round(y)), int(round(z))]

    def current_gesture(self):
        name, t = self._pulse
        if name and time.perf_counter() - t < sensors.PULSE_S:
            return name
        return sensors.gesture_from_accel(*self.accel())

    def _add_gesture(self, g):
        if not g:
            return
        self.gesture_flags.add(g)
        self.gesture_history.append(g)
        del self.gesture_history[:-16]

    def sound_level(self):
        s = self.shared
        return s.get("mic_level") if s is not None else 0

    def temperature(self):
        s = self.shared
        return int(round(s.get("temp_c"))) if s is not None and s.get("sensors_set") else 21

    def light_level(self):
        s = self.shared
        return s.get("light") if s is not None and s.get("sensors_set") else 128

    def sound_output_enabled(self):
        s = self.shared
        return bool(s.get("sound_out")) if s is not None else False

    def set_speaker(self, freq, label):
        s = self.shared
        if s is not None and s.get("owner_gen") == self.gen:
            s.set("speaker_freq", float(freq))
            s.set("speaker_label", label)

    def _update_sensors(self, s):
        """Called from the physics loop: track gesture and sound events between reads."""
        seq = s.get("pulse_seq")
        if seq != self._pulse_seen:
            self._pulse_seen = seq
            name = s.get("pulse_name")
            if name in sensors.PULSE_GESTURES:
                self._pulse = (name, time.perf_counter())
                self._add_gesture(name)
        g = self.current_gesture()
        if g != self.gesture_now:
            self.gesture_now = g
            if g not in sensors.PULSE_GESTURES:
                self._add_gesture(g)
        level = s.get("mic_level")
        if self.sound_event_now != "loud" and level > self.loud_threshold:
            self.sound_event_now = "loud"
        elif self.sound_event_now != "quiet" and level < self.quiet_threshold:
            self.sound_event_now = "quiet"
        else:
            return
        ev = self.sound_event_now
        self.sound_flags.add(ev)
        self.sound_history.append(ev)
        del self.sound_history[:-16]

    # --- RESET -----------------------------------------------------------------------------
    def sleep(self, seconds):
        """time.sleep replacement: in the main thread it wakes up early when RESET is pressed."""
        if threading.current_thread() is not threading.main_thread():
            return _orig_sleep(seconds)
        end = time.perf_counter() + seconds
        while True:
            if self.reset_pending:
                raise KeyboardInterrupt("RESET")
            left = end - time.perf_counter()
            if left <= 0:
                return
            _orig_sleep(min(left, 0.02))

    def request_reset(self):
        """RESET button (or microbit.reset()): stop the motors and restart the program."""
        self.reset_pending = True
        with self.robot.lock:
            self.robot.motor_cmd = [0.0, 0.0]
        if threading.current_thread() is threading.main_thread():
            raise KeyboardInterrupt("RESET")
        if self._user_code:
            _thread.interrupt_main()            # stops a running loop like Ctrl+C

    def _soft_reset(self):
        """Put the micro:bit and the Cutebot back to power-on state (the robot stays where it is)."""
        self.reset_pending = False
        r = self.robot
        with r.lock:
            r.motor_cmd = [0.0, 0.0]
            r.wheel_v = [0.0, 0.0]
            r.lights = [0, 0, 0, 0, 0, 0]
            r.neopixels = [0, 0, 0, 0, 0, 0]
            r.sonar_active = False
            r._echo = None
            r._trigger_level = 0
        mb = sys.modules.get("microbit")
        if mb is not None:
            try:
                mb.display._cancel()
                mb.display._on = True
                mb.button_a._presses = 0
                mb.button_b._presses = 0
            except AttributeError:
                pass
        self.display_buf[:] = bytes(25)
        self.gesture_history, self.gesture_flags = [], set()
        self.sound_history, self.sound_flags = [], set()
        self.set_speaker(0, "")
        self.t0 = time.perf_counter()           # running_time() starts again from 0
        self._error_text = None
        s = self.shared
        if s is not None:
            self.btn_consumed = {"a": s.get("btn_a_count"), "b": s.get("btn_b_count")}
            s.set("message", "")
            s.set("prog_state", shared.STATE_RUNNING)
            s.bump("run_seq")
            self._publish()

    def _run_again(self):
        """Run the student's file again in this process (after RESET)."""
        self._soft_reset()
        print(f"\n[cutebot-sim] RESET - running {self.script} again\n", file=sys.stderr, flush=True)
        started = time.perf_counter()
        self._user_code = True
        try:
            runpy.run_path(self.script_path, run_name="__main__")
        except KeyboardInterrupt:
            if not self.reset_pending:
                if time.perf_counter() - started < 0.3:
                    self.reset_pending = True       # a late interrupt from the previous RESET
                else:
                    raise
        except SystemExit:
            pass
        except BaseException as e:               # show the error like Python would
            traceback.print_exc()
            self._error_text = "".join(traceback.format_exception_only(type(e), e)).strip()
        finally:
            self._user_code = False

    # --- ending the program -------------------------------------------------------------
    def _excepthook(self, etype, value, tb):
        if issubclass(etype, KeyboardInterrupt) and self.reset_pending:
            return                               # RESET: no traceback, the program restarts
        if not issubclass(etype, (KeyboardInterrupt, SystemExit)):
            self._error_text = "".join(traceback.format_exception_only(etype, value)).strip()
        self._prev_excepthook(etype, value, tb)

    def _show_finished(self):
        s = self.shared
        if self._error_text:
            s.set("message", self._error_text)
            s.set("prog_state", shared.STATE_ERROR)
        else:
            s.set("prog_state", shared.STATE_FINISHED)
        self._publish()

    def _wait_for_reset(self):
        """After the program ends the micro:bit keeps running (display, motors), like the
        real one: wait for RESET, a new Run, Stop, or the window being closed."""
        if any(abs(v) > 0 for v in self.robot.motor_cmd):
            print("\n[cutebot-sim] Your program has finished, but the motors are still on, so the "
                  "Cutebot keeps moving (the real robot does the same).", file=sys.stderr)
        else:
            print("\n[cutebot-sim] Your program has finished.", file=sys.stderr)
        print("[cutebot-sim] Press RESET on the simulator's micro:bit to run it again, "
              "or Stop in PyCharm to end.", file=sys.stderr, flush=True)
        while not self.reset_pending and not self._stop:
            _orig_sleep(0.05)
        return self.reset_pending

    def _at_exit(self):
        self._user_code = False
        s = self.shared
        if s is None or s.get("owner_gen") != self.gen or not self.script_path:
            self._stop = True
            return
        while not self._stop:
            try:
                if self.reset_pending:
                    self._run_again()
                    continue
                self._show_finished()
                if not self._wait_for_reset():
                    break
            except KeyboardInterrupt:
                if self.reset_pending:
                    continue
                break
        self._stop = True


_runtime = None
_lock = threading.Lock()


def get():
    global _runtime
    with _lock:
        if _runtime is None:
            _runtime = Runtime()
        return _runtime
