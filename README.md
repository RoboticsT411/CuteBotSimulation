# Cutebot Simulator for PyCharm

Write micro:bit **MicroPython** for the Elecfreaks **Cutebot** in PyCharm, press **Run**,
and watch the robot drive in a simulator window: no hardware needed. The same file can
then be flashed to a real Cutebot **without any changes**.

Made for the [LSBU MicroPython labs](https://github.com/LSBU-Electronics-Lab/MicroPython/wiki)
(T411 Robotics Laboratory, London South Bank University). All complete programs from
Labs 1–9 run unmodified; Lab 10 has a ready-made maze.

![Cutebot simulator window](Docs/window.png)

## Features

- Real micro:bit API: `from microbit import *` works exactly as on the board
  (display, buttons, pins, I2C, `utime`, `machine`, `neopixel`, `music`).
- Simulated Cutebot: motors, headlights, line sensors, ultrasonic sensor, NeoPixels,
  at the real robot's size (8.5 × 8.5 cm).
- Sensors: tilt the micro:bit, shake it, clap at the microphone, hear music, set temperature and light.
- Arena editor: set the size in cm, 1 cm grid, draw and erase black lines, add, move and resize
  obstacles, measure distances, save and share layouts as `.json` files.
- Motor mismatch: make one wheel weaker, like a real robot, and get a suggested speed
  correction to drive straight.
- Code view: highlights the line your program is running and lists the last motor commands.
- Pause, step one line at a time, slow motion, and automatic pauses when the motors change, a
  line sensor changes or the robot bumps into something.
- Live graphs of the line sensors, ultrasonic distance and motor speeds.
- Code checker: finds things that work on the PC but fail on the micro:bit, before you upload.
- Realistic mode: sensor noise, missed sonar echoes and a motor dead zone, like the real robot.
- Radio: the real `radio` module, with a console to send and receive messages.
- Challenge mode: start, checkpoint and finish zones, a timer, bump penalties and best times.
- LAN competitions: a teacher's dashboard starts races for the whole class (time trial or
  one shared arena with radio between robots), with a live leaderboard.
- Debugging: breakpoints pause the robot too, so you can inspect sensor values.
- RESET button on the simulated micro:bit restarts your program, like the real one.
- Built-in micro:bit reference: search any function (e.g. `display`, `motor`, `sleep`) and
  open its page in the official V2 documentation.
- Real hardware: upload the same file to a Cutebot with the micro:bit Flasher + REPL tool.
- Standard library only: nothing to `pip install`.

## What is simulated

| Hardware | How your code uses it | Notes |
|---|---|---|
| 5×5 LED display | `display.show / scroll / set_pixel`, `Image` | real micro:bit font and built-in images |
| Buttons A and B | `button_a.is_pressed()`, `was_pressed()`, `get_presses()` | click them or press the **A** / **B** keys |
| Motors | `i2c.write(0x10, bytearray([0x01 or 0x02, dir, speed, 0]))` | Elecfreaks mapping: **0x01 = left, 0x02 = right**; dir 0x02 = forward, 0x01 = backward; speed 0–100 (whole numbers) |
| Headlights | `i2c.write(0x10, bytearray([0x04 or 0x08, R, G, B]))` | 0x04 = left, 0x08 = right |
| Line sensors | `pin13` (left), `pin14` (right) `.read_digital()` | **0 over the black line, 1 over white** |
| Ultrasonic sensor | trigger `pin8`, echo `pin12`, or `machine.time_pulse_us` | measures to walls, obstacles and other robots; no reading closer than 2 cm (like the real HC-SR04) |
| NeoPixels | `neopixel.NeoPixel(pin15, 2)` | shown as underglow |
| Timing | `sleep`, `running_time`, `utime.*`, `time.sleep_ms` … | real time at 1x; follows pause and slow/fast motion |
| Accelerometer | `accelerometer.get_x/y/z()`, `current_gesture()`, `was_gesture('shake')`, `set_range(2/4/8)` | **Upright on the Cutebot** (default, as on the robot): y ≈ −1024 at rest, speeding up, braking and crashes show in z (front/back) and x (sideways), the tilt pad tilts the robot. Untick it for a micro:bit on its own (flat). Try `examples/07_crash_detect.py`. |
| Microphone (V2) | `microphone.sound_level()`, `was_event(SoundEvent.LOUD)` | level slider and **Clap** button |
| Speaker / music | `music.play(...)`, `music.pitch(...)`, `audio.play(Sound.HAPPY)` | note shown on screen; real beeps on Windows if enabled |
| Compass | `compass.heading()` | the robot's heading (north = top of the arena) |
| Temperature, light | `temperature()`, `display.read_light_level()` | sliders |
| Radio | `import radio`, `radio.on()`, `config(group=…)`, `send`, `receive`, `send_bytes`, `receive_full` | **Radio** window to send/receive; reaches other robots in a LAN shared arena |
| Bluetooth | | not simulated (not available in MicroPython on the micro:bit either) |

## Quick start

### 1. Install Python, PyCharm and Git

| Software | Download | Notes |
|---|---|---|
| **Python 3.9+** (required) | [python.org/downloads](https://www.python.org/downloads/) | PyCharm does **not** include Python. Windows: run the *Python install manager* and click **Install**. Linux: `sudo apt install python3 python3-venv python3-tk` |
| **PyCharm** | [jetbrains.com/pycharm/download](https://www.jetbrains.com/pycharm/download/) | One unified PyCharm; its free core features are all you need |
| **Git** (optional) | [git-scm.com/downloads](https://git-scm.com/downloads) | Needed to clone and to pull updates |

Check that Python includes Tkinter (the simulator window needs it):

```
python -c "import tkinter; print('Python and Tkinter OK')"
```

### 2. Get the project

Choose **one** option. Options A and C use Git, so you can download updates later with one
command (`git pull`); option B needs nothing extra.

**Option A – Clone in PyCharm (recommended)**

1. Open PyCharm. On the Welcome screen click **Clone Repository**
   (if a project is already open: **File → New → Project from Version Control**).
2. In **URL** paste: `https://github.com/RoboticsT411/CuteBotSimulation.git`
3. Choose a **Directory**, e.g. `C:\Users\<you>\PycharmProjects\CuteBotSimulation`.
4. Click **Clone**, then **Trust Project**.

**Option B – Download a ZIP (no Git needed)**

1. On the GitHub page click **Code → Download ZIP**.
2. Right-click the ZIP → **Extract All…**
3. In PyCharm: **File → Open…**, select the extracted folder, then **Trust Project**.

**Option C – Clone in a terminal**

1. Open a terminal (Windows: Start → *Terminal*) and go to the folder where you keep projects.
2. Run:
   ```
   git clone https://github.com/RoboticsT411/CuteBotSimulation.git
   ```
3. In PyCharm: **File → Open…**, select the new `CuteBotSimulation` folder, then **Trust Project**.

**Check before you continue:** in PyCharm's **Project** panel (left) you should see the
`CuteBotSimulation` folder with a **`CutebotSim`** folder inside it. The simulator files
(`install_simulator.py`, `microbit/`, `cutebot_sim/`, `labs/`, `examples/`) are in `CutebotSim`.

If the repository is private, Git asks you to sign in to GitHub the first time
(you need access from your lecturer).

### 3. Create the interpreter

PyCharm may offer to create a virtual environment when the project opens: accept it. Otherwise:

1. **File → Settings → Python → Python Interpreter**
   (macOS: **PyCharm → Settings**; older PyCharm versions: **Project: … → Python Interpreter**).
2. **Add Interpreter → Add Local Interpreter → Virtualenv Environment → New**.
3. Location: `venv` inside the project folder. Base interpreter: your Python 3. Click **OK**.
4. The bottom-right corner of PyCharm should now show this interpreter.

The simulator needs no packages, so don't install any here. In particular, never install
`microbit`, `microbit-stubs` or `microbit-dummy` (see the warning below). The only packages you
ever need are `uflash` and `pyserial`, and only for uploading to a real robot.

### 4. Run `install_simulator.py` once

1. In the **Project** panel, click the arrow next to the **`CutebotSim`** folder to expand it.
2. Right-click **`install_simulator.py`** (inside `CutebotSim`) → **Run 'install_simulator'**.

   > **If PyCharm asks for an environment** (a yellow bar at the top of the editor saying
   > *Create a virtual environment* / *Custom Environment*), do **not** create a new one:
   > click **Custom Environment** → **Select existing** → Type **Python** → click **…** and
   > choose `venv\Scripts\python.exe` inside your project folder (the `venv` created in step 3;
   > macOS/Linux: `venv/bin/python`) → **OK**. Then run `install_simulator.py` again.

3. The Run panel at the bottom should end with
   `Done. Any file with 'from microbit import *' will now open the simulator.`
   Check that its **Interpreter** line shows the `venv` you created in step 3.

This registers the simulator with your interpreter, so `from microbit import *` works from any
folder. It installs nothing and needs no internet. Run it again after creating a new virtual
environment or moving the project.

Optional, to stop PyCharm underlining `microbit` in red: right-click the **`CutebotSim`** folder →
**Mark Directory as → Sources Root**.

### 5. Run a program

Create a file in **`CutebotSim/labs`** (expand `CutebotSim`, right-click **labs** →
**New → Python File**, no spaces in the name):

```python
from microbit import *

while True:
    display.scroll("Hello, World!")
```

Right-click in the editor → **Run**. The simulator window opens. Try
`CutebotSim/examples/03_line_follow.py` to see the robot follow the line.

> **Never install `microbit`, `microbit-stubs` or `microbit-dummy`** with pip or PyCharm's
> package manager. They contain empty look-alike modules and programs would run without doing
> anything. Code completion already works from the simulator itself.

## Using the simulator

All sizes are in **cm**. The origin is the **bottom-left** corner; angle 0° faces right and
90° faces up. Hover the mouse to see coordinates. The grid has 1 cm squares with a bold line
every 10 cm, numbered along the edges (on very large arenas the small squares become 5 cm).

| Tool (keys 1–5) | What it does |
|---|---|
| 1 Move | Drag the robot or an obstacle. Drag an obstacle's **edge or corner to resize** it (whole cm). Click an obstacle (turns yellow) to see **green gap lines** from each side to the nearest wall or obstacle, in cm; **Delete** removes it. |
| 2 Draw line | Drag to draw black tape; **Shift** = straight line. Ends join automatically and loops close themselves. |
| 3 Erase | Drag over a line to rub it out; click an obstacle to delete it. |
| 4 Draw obstacle | Drag out a
