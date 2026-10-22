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
- Arena editor: set the size in cm, draw and erase black lines, add and move obstacles,
  save and share layouts as `.json` files.
- Motor mismatch: make one wheel weaker, like a real robot, and get a suggested speed
  correction to drive straight.
- Debugging: breakpoints pause the robot too, so you can inspect sensor values.
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
| Ultrasonic sensor | trigger `pin8`, echo `pin12`, or `machine.time_pulse_us` | measures to walls and obstacles |
| NeoPixels | `neopixel.NeoPixel(pin15, 2)` | shown as underglow |
| Timing | `sleep`, `running_time`, `utime.*`, `time.sleep_ms` … | real time |
| Accelerometer, compass, sound, radio | | placeholders only |

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
90° faces up. Hover the mouse to see coordinates.

| Tool (keys 1–4) | What it does |
|---|---|
| 1 Move | Drag the robot or an obstacle. Click an obstacle (turns yellow) and press **Delete** to remove it. |
| 2 Draw line | Drag to draw black tape; **Shift** = straight line. Ends join automatically and loops close themselves. |
| 3 Erase | Drag over a line to rub it out; click an obstacle to delete it. |
| 4 Draw obstacle | Drag out a rectangle. |

Q / E or the mouse wheel rotate the robot 15° (Shift: 1°). Right-click deletes an obstacle.

| Tab | Use it to |
|---|---|
| **Robot** | Place the robot at an exact x, y, angle; **Set start here** sets the start position. |
| **Motors** | Simulate motor mismatch; path trail, straightness read-out and correction hint. |
| **Obstacles** | Add obstacles by corner and size; list and delete them. |
| **Arena** | Arena size (30–500 cm) and tape width, presets (oval, figure eight, obstacles, Lab 10 maze, empty), **Save / Open layout**. |

- The window stays open between runs. Running again is like re-flashing the micro:bit:
  the new program takes over and the robot returns to its start.
- If a program ends with the motors on, the robot keeps moving, as on the real Cutebot.
  Press **Stop** or close the window.
- The arena is saved automatically and reopens next time. Example layouts are in `layouts/`.

### Driving straight: motor mismatch

Real motors are never identical, so `motors(25, 25)` usually drifts. In the **Motors** tab set,
for example, left 100 % and right 92 %: your code is unchanged, but the right wheel turns 8 %
slower. After a run at one constant speed the tab shows the drift and suggests a correction,
e.g. `motors(25, 27)` or `motors(23, 25)`, calculated only from the measured distance and turn,
exactly as you would with a real robot. **Random hidden** sets a secret mismatch as an exercise.

Speeds are whole numbers: the Cutebot receives each speed as one byte, so `25.5` raises
`TypeError` on the micro:bit and in the simulator. Use `int(round(speed))`.

## Hardware support: uploading to a real Cutebot

The same `.py` file that runs in the simulator runs on the real robot. The micro:bit has its
own built-in `microbit` module, so the simulator files are not used there. To upload, use the
**micro:bit Flasher + REPL** program
([`MicrobitUploader.py`](https://github.com/mjtroniks/Microbit/blob/main/MicrobitUploader.py)):
it flashes your file with `uflash` and shows the robot's `print()` output over USB.

![micro:bit Flasher + REPL](Docs/uploader.png)

*Example screen (values shown for illustration).*

### 1. Install the tools (once)

Open PyCharm's **Terminal** (it uses the project's virtual environment) and run:

```
python -m pip install uflash pyserial
```

On the university network, if pip fails with a certificate error (`SSL: CERTIFICATE_VERIFY_FAILED`), use:

```
python -m pip install uflash pyserial --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

`uflash` and `pyserial` do not contain a `microbit` module, so they do not affect the simulator.

### 2. Get the uploader and the lab material

```
git clone https://github.com/mjtroniks/Microbit.git
git clone https://github.com/LSBU-Electronics-Lab/MicroPython.git
```

The first contains `MicrobitUploader.py`; the second contains the lab programs
(instructions in the [lab wiki](https://github.com/LSBU-Electronics-Lab/MicroPython/wiki)).
Without Git, use **Code → Download ZIP** on each GitHub page.

### 3. Upload a program

1. Put the robot on its **stand** so it cannot drive off the bench, and check the
   ultrasonic sensor is plugged into **SR04** (not I2C).
2. Connect the micro:bit by USB. It appears as a drive called **MICROBIT**.
3. Start the uploader from the same Terminal: `python Microbit/MicrobitUploader.py`
   (adjust the path to where you cloned it).
4. **Browse…** to your `.py` file, check the **MICROBIT drive** (click **Refresh** if it is
   empty) and click **Upload to micro:bit**. The orange LED on the back flashes; when it
   stops, the program starts.
5. To see `print()` output: choose the **Serial port** (usually *mbed Serial Port* /
   *USB Serial Device*, e.g. `COM5`) and click **Connect**. **Interrupt (Ctrl+C)** stops the
   program, **Enter REPL** gives a `>>>` prompt, **Soft Reset** restarts it.

Notes:
- The uploader finds the micro:bit by drive letter, so it works on **Windows**.
- `uflash` must be installed in the same Python that runs the uploader; if it says
  *"uflash is not installed"*, it prints the exact install command for that Python.
- The serial connection is closed automatically before each upload; connect again afterwards.
- `uflash` puts its own MicroPython on the micro:bit (for the V2 an early 2.0 release). If a
  newer MicroPython feature is missing, flash from [python.microbit.org](https://python.microbit.org)
  or with PyCharm's MicroPython plugin instead.
- Robot drifting to one side? Measure it, then use the simulator's **Motors** tab to find
  corrected speeds (see above).

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'microbit'` | Run `install_simulator.py` with the same interpreter PyCharm uses. |
| Program finishes instantly, no window | A look-alike package is installed: `pip uninstall microbit microbit-stubs microbit-dummy`, then run `install_simulator.py` again. |
| Red underline under `microbit` but it runs | Right-click the project folder → **Mark Directory as → Sources Root**, or **File → Invalidate Caches**. |
| No simulator window | Python lacks Tkinter: reinstall from python.org. See `cutebot_sim_window.log` in your temp folder. |
| `TypeError` on motor speeds | Use whole numbers 0–100. |
| Uploader: "No MICROBIT drive found" | Use a data USB cable, reconnect the micro:bit, click **Refresh**. The drive must show **MICROBIT** in File Explorer. |
| Uploader: "pyserial not installed" / "uflash is not installed" | Run `python -m pip install uflash pyserial` with the Python that starts the uploader. |
| Uploader: cannot connect to COM port | Close other programs using the port (PyCharm's MicroPython REPL, another uploader window) and try again. |
| Strange import errors | Don't name your files `microbit.py`, `machine.py`, `utime.py` or `neopixel.py`. |

## Command line

```
python examples/03_line_follow.py      # run a program with the simulator window
python -m cutebot_sim.gui              # open the window on its own
python tests/smoke_test.py             # self-check, no window
```

## Robot size and calibration

The robot's geometry is set by a few measurements at the top of `cutebot_sim/robot.py`
(overall length and width, wheel size, axle position, line-sensor position and spacing).
The drawing, wheel spacing, sensors and collisions are calculated from them. Measure your
Cutebot and change them to match it; top speed and motor response can be tuned there too.

## Project structure

```
install_simulator.py   run once per virtual environment
microbit/              the simulated micro:bit module
utime.py machine.py neopixel.py music.py
cutebot_sim/
    robot.py           Cutebot model and physics (geometry settings at the top)
    maps.py            arenas, presets and layout files
    display.py         Image and display
    runtime.py         connects your program to the window, runs the physics
    gui.py             the simulator window (Tkinter)
    shared.py          shared-memory link between program and window
    _data.py           micro:bit font and images
labs/                  your programs
examples/              example programs
layouts/               example arena layouts (.json)
tests/                 self-checks
docs/                  images for this README
```

## How it works

Importing `microbit` starts a physics thread inside your program and connects to the
simulator window, which runs as a separate process; they share the robot's state through a
small block of shared memory. Because the physics runs inside your program, a breakpoint
pauses the robot as well. The window owns the arena (size, lines, obstacles) and sends any
change to the running program immediately.

## Credits

- micro:bit font from Lancaster University [codal-core](https://github.com/lancaster-university/codal-core) (MIT).
- Built-in images from [micropython-microbit-v2](https://github.com/microbit-foundation/micropython-microbit-v2) by Damien P. George (MIT).

Both are included in `cutebot_sim/_data.py` with their licence notices.
