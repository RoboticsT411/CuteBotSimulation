"""Quick reference for the micro:bit MicroPython API and the Cutebot, shown in the
simulator's Help window.  Summaries are written for students; every entry links to
the official micro:bit MicroPython **V2** documentation (or the LSBU lab wiki for
the Cutebot) for the full details.

Fields: name, signature, summary, example, sim (simulator support), url, keywords.
"""

DOCS = "https://microbit-micropython.readthedocs.io/en/v2-docs/"
WIKI = "https://github.com/LSBU-Electronics-Lab/MicroPython/wiki/"
DOCS_HOME = DOCS + "microbit_micropython_api.html"

YES, PART, NO = "Simulated", "Partly simulated", "Not simulated"


def _e(name, signature, summary, example, sim, url, keywords=""):
    return {"name": name, "signature": signature, "summary": summary, "example": example,
            "sim": sim, "url": url, "keywords": keywords}


ENTRIES = [
    # ---------------------------------------------------------------- basics
    _e("from microbit import *", "from microbit import *",
       "Put this at the top of every program. It gives you display, Image, buttons, pins, "
       "i2c, sleep and the rest of the micro:bit functions.",
       "from microbit import *\n\ndisplay.scroll('Hi')",
       YES, DOCS + "microbit.html", "import start begin module"),
    _e("sleep", "sleep(ms)",
       "Wait for a number of milliseconds (1000 ms = 1 second). The program pauses; motors keep "
       "turning at their current speed.",
       "display.show(Image.HAPPY)\nsleep(1000)\ndisplay.clear()",
       YES, DOCS + "microbit.html#microbit.sleep", "wait delay pause time ms"),
    _e("running_time", "running_time()",
       "Milliseconds since the micro:bit started (or since RESET). Useful for timing without "
       "stopping the program.",
       "start = running_time()\n# ... do something ...\nprint(running_time() - start, 'ms')",
       YES, DOCS + "microbit.html#microbit.running_time", "time timer clock millis"),
    _e("temperature", "temperature()",
       "Temperature in degrees Celsius, measured by the processor (roughly room temperature).",
       "display.scroll(temperature())",
       YES + " (Sensors tab slider)", DOCS + "microbit.html#microbit.temperature", "temp celsius sensor"),
    _e("scale", "scale(value, from_, to)",
       "Convert a number from one range to another, e.g. a sensor reading 0-1023 to a speed "
       "0-100. Returns a whole number if the target range uses whole numbers.",
       "speed = scale(512, from_=(0, 1023), to=(0, 100))   # 50",
       YES, DOCS + "microbit.html#microbit.scale", "map range convert"),
    _e("reset", "reset()",
       "Restart the program from the beginning, like pressing the RESET button.",
       "if button_a.was_pressed():\n    reset()",
       YES, DOCS + "microbit.html#microbit.reset", "restart reboot"),
    _e("panic", "panic(n)",
       "Stop the program and show a sad face with an error code. Used for serious errors.",
       "panic(42)",
       PART, DOCS + "microbit.html#microbit.panic", "error stop"),
    _e("print", "print(value, ...)",
       "Send text to the computer. In the simulator it appears in PyCharm's Run window; on the "
       "robot it is sent over USB (see it with the uploader's serial console).",
       "print('distance:', 42)",
       YES, DOCS + "tutorials/hello.html", "output console serial debug log"),

    # ---------------------------------------------------------------- display
    _e("display.show", "display.show(value, delay=400, *, wait=True, loop=False, clear=False)",
       "Show an Image, a number, a letter or a list of images on the 5x5 LEDs. A string or list is "
       "shown one item at a time, delay ms each.",
       "display.show(Image.HEART)\ndisplay.show(7)\ndisplay.show('ABC', delay=500)",
       YES, DOCS + "display.html#microbit.display.show", "led screen image number text"),
    _e("display.scroll", "display.scroll(text, delay=150, *, wait=True, loop=False, monospace=False)",
       "Scroll text (or a number) across the LEDs from right to left. delay is ms per step; "
       "wait=False lets the program continue while it scrolls.",
       "display.scroll('Hello LSBU')\ndisplay.scroll(3.5, delay=100)",
       YES, DOCS + "display.html#microbit.display.scroll", "text message led string"),
    _e("display.clear", "display.clear()",
       "Turn all 25 LEDs off.",
       "display.clear()",
       YES, DOCS + "display.html#microbit.display.clear", "off blank led"),
    _e("display.set_pixel", "display.set_pixel(x, y, value)",
       "Set one LED. x is the column 0-4 (left to right), y the row 0-4 (top to bottom), "
       "value the brightness 0 (off) to 9 (brightest).",
       "display.set_pixel(2, 2, 9)   # centre LED fully on",
       YES, DOCS + "display.html#microbit.display.set_pixel", "led pixel brightness dot"),
    _e("display.get_pixel", "display.get_pixel(x, y)",
       "Brightness (0-9) of one LED.",
       "if display.get_pixel(0, 0) == 0:\n    display.set_pixel(0, 0, 9)",
       YES, DOCS + "display.html#microbit.display.get_pixel", "led pixel read"),
    _e("display.on / off / is_on", "display.on()   display.off()   display.is_on()",
       "Switch the LED display on or off (off frees some pins for other uses).",
       "display.off()\nprint(display.is_on())   # False",
       PART, DOCS + "display.html#microbit.display.off", "led enable disable"),
    _e("display.read_light_level", "display.read_light_level()",
       "Light level 0-255 measured with the LEDs.",
       "if display.read_light_level() < 50:\n    print('dark')",
       YES + " (Sensors tab slider)", DOCS + "display.html#microbit.display.read_light_level",
       "light sensor brightness dark"),

    # ---------------------------------------------------------------- images
    _e("Image(...)", "Image('09090:99999:99999:09990:00900')   Image(width, height)",
       "Make your own picture: 5 rows separated by ':', one digit 0-9 per LED for its brightness.",
       "boat = Image('05050:05050:05050:99999:09990')\ndisplay.show(boat)",
       YES, DOCS + "image.html#microbit.Image", "picture custom draw sprite"),
    _e("Image.HEART (built-in images)", "Image.HEART  Image.HAPPY  Image.SAD  Image.YES  Image.NO ...",
       "Ready-made pictures: HEART, HEART_SMALL, HAPPY, SMILE, SAD, CONFUSED, ANGRY, ASLEEP, "
       "SURPRISED, SILLY, FABULOUS, MEH, YES, NO, ARROW_N ... ARROW_NW, CLOCK1 ... CLOCK12, "
       "TRIANGLE, CHESSBOARD, DIAMOND, SQUARE, RABBIT, COW, MUSIC_CROTCHET, PACMAN, TARGET, "
       "TSHIRT, DUCK, HOUSE, TORTOISE, BUTTERFLY, GHOST, SWORD, GIRAFFE, SKULL, UMBRELLA, SNAKE "
       "and more. Image.ALL_CLOCKS and Image.ALL_ARROWS are lists for animations.",
       "display.show(Image.HAPPY)\ndisplay.show(Image.ALL_CLOCKS, delay=100)",
       YES, DOCS + "image.html#attributes", "picture icon smiley arrow clock list"),
    _e("Image methods", "img.set_pixel(x, y, v)  img.get_pixel(x, y)  img.width()  img.height()\n"
       "img.shift_left(n)  img.shift_right(n)  img.shift_up(n)  img.shift_down(n)\n"
       "img.crop(x, y, w, h)  img.copy()  img.invert()  img.fill(v)",
       "Change or move an image. Built-in images are read-only: copy() them first. shift_* "
       "return a new, moved image (useful for animations).",
       "img = Image.HEART.copy()\nimg.set_pixel(0, 0, 9)\ndisplay.show(img.shift_left(1))",
       YES, DOCS + "image.html", "picture edit move animate"),
    _e("Image + and *", "img1 + img2      img * 0.5",
       "Add two images (brightness adds up, max 9) or multiply an image's brightness.",
       "display.show(Image.HEART * 0.3)",
       YES, DOCS + "image.html", "brightness combine"),

    # ---------------------------------------------------------------- buttons
    _e("button_a.is_pressed", "button_a.is_pressed()   button_b.is_pressed()",
       "True while the button is being held down. In the simulator click A/B or hold the A/B keys.",
       "while True:\n    if button_a.is_pressed():\n        display.show(Image.HAPPY)\n"
       "    else:\n        display.clear()",
       YES, DOCS + "button.html#Button.is_pressed", "button input press hold key"),
    _e("button_a.was_pressed", "button_a.was_pressed()",
       "True if the button was pressed since the last time you asked (it remembers a quick press "
       "even while the program was busy).",
       "while True:\n    if button_b.was_pressed():\n        display.scroll('B')\n    sleep(100)",
       YES, DOCS + "button.html#Button.was_pressed", "button click event"),
    _e("button_a.get_presses", "button_a.get_presses()",
       "Number of presses since the last call; the count then goes back to 0.",
       "sleep(3000)\ndisplay.show(button_a.get_presses())",
       YES, DOCS + "button.html#Button.get_presses", "button count clicks"),

    # ---------------------------------------------------------------- pins
    _e("pin.read_digital", "pin13.read_digital()",
       "Read a pin as 0 or 1. On the Cutebot pin13/pin14 are the line sensors (0 = black line).",
       "left = pin13.read_digital()\nright = pin14.read_digital()",
       YES, DOCS + "pin.html#microbit.MicroBitDigitalPin.read_digital", "input digital pin sensor"),
    _e("pin.write_digital", "pin8.write_digital(value)",
       "Set a pin to 0 (off, 0 V) or 1 (on, 3 V). On the Cutebot pin8 triggers the ultrasonic sensor.",
       "pin8.write_digital(1)\npin8.write_digital(0)",
       YES, DOCS + "pin.html#microbit.MicroBitDigitalPin.write_digital", "output digital pin led"),
    _e("pin.read_analog", "pin0.read_analog()",
       "Read the voltage on a pin as a number 0 (0 V) to 1023 (3 V).",
       "value = pin0.read_analog()",
       PART, DOCS + "pin.html#microbit.MicroBitAnalogDigitalPin.read_analog", "analog voltage adc"),
    _e("pin.write_analog", "pin0.write_analog(value)",
       "Output a PWM signal 0-1023 (0 = always off, 1023 = always on), e.g. for LED brightness.",
       "pin0.write_analog(511)   # half brightness",
       PART, DOCS + "pin.html#microbit.MicroBitDigitalPin.write_analog", "pwm analog output"),
    _e("pin_logo.is_touched", "pin_logo.is_touched()   pin0.is_touched()",
       "True while the gold logo (or a pin) is touched.",
       "if pin_logo.is_touched():\n    display.show(Image.HEART)",
       NO, DOCS + "pin.html#microbit.MicroBitTouchPin.is_touched", "touch logo capacitive"),

    # ---------------------------------------------------------------- i2c
    _e("i2c.write", "i2c.write(addr, buf, repeat=False)",
       "Send bytes to a device on the I2C bus. The Cutebot's motor/light controller is at address "
       "0x10. buf is a bytearray of whole numbers 0-255.",
       "i2c.write(0x10, bytearray([0x01, 0x02, 25, 0]))   # left motor forward 25 %",
       YES + " (Cutebot at 0x10)", DOCS + "i2c.html#microbit.i2c.write", "bus bytes send cutebot"),
    _e("i2c.read", "i2c.read(addr, n, repeat=False)",
       "Read n bytes from a device on the I2C bus.",
       "data = i2c.read(0x10, 2)",
       PART + " (returns zeros)", DOCS + "i2c.html#microbit.i2c.read", "bus bytes receive"),
    _e("i2c.scan", "i2c.scan()",
       "List of the addresses of the devices connected to the I2C bus.",
       "print(i2c.scan())   # [16] = 0x10, the Cutebot",
       YES, DOCS + "i2c.html#microbit.i2c.scan", "bus devices find"),

    # ---------------------------------------------------------------- time
    _e("utime.sleep_ms / sleep_us", "utime.sleep_ms(ms)   utime.sleep_us(us)   utime.sleep(s)",
       "Wait in milliseconds, microseconds or seconds (import utime first).",
       "import utime\nutime.sleep_us(10)   # 10 microseconds",
       YES, DOCS + "utime.html#utime.sleep_ms", "wait delay microseconds"),
    _e("utime.ticks_ms / ticks_us", "utime.ticks_ms()   utime.ticks_us()",
       "A counter in ms or µs, for measuring how long something takes. Use ticks_diff to subtract.",
       "import utime\nt = utime.ticks_us()",
       YES, DOCS + "utime.html#utime.ticks_ms", "timer clock measure"),
    _e("utime.ticks_diff", "utime.ticks_diff(end, start)",
       "Time between two ticks values (handles the counter wrapping round).",
       "import utime\nstart = utime.ticks_ms()\nsleep(50)\nprint(utime.ticks_diff(utime.ticks_ms(), start))",
       YES, DOCS + "utime.html#utime.ticks_diff", "elapsed duration"),
    _e("machine.time_pulse_us", "machine.time_pulse_us(pin, level, timeout_us=1000000)",
       "Length of a pulse on a pin in microseconds; -2 if it never started, -1 if it never ended. "
       "Used to read the ultrasonic sensor's echo.",
       "import machine\nt = machine.time_pulse_us(pin12, 1, 25000)",
       YES, DOCS + "machine.html#machine.time_pulse_us", "pulse echo ultrasonic timing"),

    # ---------------------------------------------------------------- other modules
    _e("neopixel.NeoPixel", "np = neopixel.NeoPixel(pin, n)\nnp[i] = (r, g, b)   np.show()   np.clear()",
       "Control colour LEDs. Set each with (red, green, blue) 0-255, then show(). The Cutebot "
       "has 2 under the robot on pin15.",
       "import neopixel\nnp = neopixel.NeoPixel(pin15, 2)\nnp[0] = (255, 0, 0)\nnp[1] = (0, 0, 255)\nnp.show()",
       YES + " (Cutebot pin15)", DOCS + "neopixel.html#neopixel.NeoPixel", "rgb led colour color lights"),
    _e("music.play / pitch", "music.play(music.NYAN)   music.pitch(440, 500)",
       "Play notes ('c4:4' = note C, octave 4, 4 ticks; 'r:2' = rest) or a frequency in Hz. "
       "The simulator shows each note on the speaker indicator (Sensors tab); tick 'Play sounds "
       "on this PC' to hear them on Windows. Built-in melodies (music.NYAN ...) play a placeholder tune.",
       "import music\nmusic.play(['c4:4', 'e', 'g:8'])\nmusic.pitch(440, 500)",
       YES, DOCS + "music.html#music.play", "sound tune note buzzer speaker melody"),
    _e("accelerometer.get_x / y / z", "accelerometer.get_x()  get_y()  get_z()  get_values()",
       "Tilt in milli-g: x = left/right (right edge down = +), y = logo edge down = +, z = -1024 "
       "when lying flat face up. In the simulator, drag the dot on the tilt pad (Sensors tab).",
       "while True:\n    x = accelerometer.get_x()\n    if x > 300:\n        display.show(Image.ARROW_E)\n"
       "    elif x < -300:\n        display.show(Image.ARROW_W)\n    else:\n        display.clear()\n    sleep(100)",
       YES + " (Sensors tab tilt pad)", DOCS + "accelerometer.html#microbit.accelerometer.get_x",
       "tilt accelerometer motion angle level"),
    _e("accelerometer gestures", "accelerometer.current_gesture()  is_gesture(name)  was_gesture(name)",
       "Gestures: 'up', 'down', 'left', 'right', 'face up', 'face down', 'freefall', '3g', '6g', "
       "'8g', 'shake'. was_gesture remembers a gesture since you last asked. Use the Sensors tab "
       "buttons (Shake, Face down, Logo up) or tilt pad.",
       "while True:\n    if accelerometer.was_gesture('shake'):\n        display.show(Image.SURPRISED)\n    sleep(100)",
       YES + " (Sensors tab)", DOCS + "accelerometer.html#microbit.accelerometer.was_gesture",
       "shake gesture face up down freefall"),
    _e("compass", "compass.heading()   compass.calibrate()",
       "Direction in degrees clockwise from north (0-359). In the simulator north is the top of "
       "the arena, so it gives the robot's heading.",
       "display.scroll(compass.heading())",
       YES + " (robot heading)", DOCS + "compass.html#microbit.compass.heading", "direction north magnetometer heading"),
    _e("microphone", "microphone.sound_level()  microphone.was_event(SoundEvent.LOUD)",
       "Sound level 0-255 and LOUD/QUIET events (micro:bit V2). In the simulator use the "
       "Microphone slider and the Clap button (Sensors tab).",
       "while True:\n    if microphone.was_event(SoundEvent.LOUD):\n        display.show(Image.HEART)\n"
       "    sleep(100)",
       YES + " (Sensors tab)", DOCS + "microphone.html", "sound clap noise level loud quiet mic"),
    _e("audio.play(Sound.HAPPY)", "audio.play(Sound.GIGGLE / HAPPY / HELLO / SAD / TWINKLE ...)",
       "Play a built-in sound expression on the V2 speaker. The simulator shows its name on the "
       "speaker indicator (no real sound).",
       "audio.play(Sound.HAPPY)",
       PART + " (indicator only)", DOCS + "audio.html", "sound expression speaker giggle"),
    _e("radio", "import radio\nradio.on()   radio.send('hi')   radio.receive()",
       "Send short messages between micro:bits.",
       "import radio\nradio.on()\nradio.config(group=7)\nradio.send('go')",
       NO + " (module not available)", DOCS + "radio.html", "wireless message send receive"),
    _e("random", "import random\nrandom.randint(a, b)   random.choice(list)",
       "Random numbers: randint gives a whole number from a to b; choice picks an item.",
       "import random\ndisplay.show(random.randint(1, 6))",
       YES, DOCS + "random.html", "dice chance"),

    # ---------------------------------------------------------------- Cutebot
    _e("Cutebot: motors", "i2c.write(0x10, bytearray([motor, direction, speed, 0]))",
       "motor 0x01 = LEFT, 0x02 = RIGHT (Elecfreaks). direction 0x02 = forward, 0x01 = backward. "
       "speed is a whole number 0-100 (no decimals: use int(round(x))).",
       "def motors(left, right):\n    for reg, v in ((0x01, left), (0x02, right)):\n"
       "        i2c.write(0x10, bytearray([reg, 0x02 if v >= 0 else 0x01, min(abs(v), 100), 0]))\n\n"
       "motors(25, 25)",
       YES, WIKI + "LAB-7-Motor-Control", "cutebot motor speed drive wheel forward backward"),
    _e("Cutebot: headlights", "i2c.write(0x10, bytearray([light, R, G, B]))",
       "light 0x04 = left, 0x08 = right headlight; R, G, B are 0-255.",
       "i2c.write(0x10, bytearray([0x04, 0, 0, 255]))   # left light blue",
       YES, WIKI + "LAB-5-Set-Car-Lights", "cutebot light led rgb headlight"),
    _e("Cutebot: line sensors", "pin13.read_digital()   pin14.read_digital()",
       "Left (pin13) and right (pin14) line sensors under the front: 0 = over the black line, "
       "1 = over white.",
       "if pin13.read_digital() == 0 and pin14.read_digital() == 0:\n    print('on the line')",
       YES, WIKI + "LAB-8-Line-Tracking", "cutebot line follow track sensor black"),
    _e("Cutebot: ultrasonic distance", "trigger pin8, echo pin12",
       "Send a 10 µs pulse on pin8, then time the echo on pin12. distance (cm) = echo time (µs) "
       "x 0.0343 / 2. Plug the sensor into the SR04 socket.",
       "import machine, utime\npin8.write_digital(1)\nutime.sleep_us(10)\npin8.write_digital(0)\n"
       "t = machine.time_pulse_us(pin12, 1, 25000)\nprint(t * 0.0343 / 2, 'cm')",
       YES, WIKI + "LAB-6-Distance-Sensors", "cutebot sonar ultrasonic distance obstacle echo"),
    _e("Cutebot: bottom NeoPixels", "neopixel.NeoPixel(pin15, 2)",
       "Two colour LEDs under the robot: index 0 = left, 1 = right.",
       "import neopixel\nnp = neopixel.NeoPixel(pin15, 2)\nnp[0] = (0, 255, 0)\nnp.show()",
       YES, WIKI + "LAB-9-Neopixel", "cutebot neopixel rgb underglow"),
]


def search(text):
    """Entries matching ``text`` (all words must appear), best matches first."""
    words = text.lower().split()
    if not words:
        return list(ENTRIES)
    scored = []
    for e in ENTRIES:
        name = e["name"].lower()
        hay = " ".join((name, e["signature"].lower(), e["summary"].lower(), e["keywords"].lower()))
        if all(w in hay for w in words):
            score = sum(3 if w in name else 2 if w in e["keywords"].lower() else 1 for w in words)
            scored.append((-score, ENTRIES.index(e), e))
    return [e for _, _, e in sorted(scored, key=lambda t: (t[0], t[1]))]
