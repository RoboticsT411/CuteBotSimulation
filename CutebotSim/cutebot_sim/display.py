"""micro:bit ``Image`` and ``display`` (behaviour follows MicroPython on the micro:bit V2)."""

import threading
import time

from ._data import FONT, IMAGES


class Image:
    """A grid of LED brightness values 0..9."""

    def __init__(self, *args):
        self._readonly = False
        if not args:
            self._w, self._h = 5, 5
            self._px = bytearray(25)
        elif len(args) == 1 and isinstance(args[0], str):
            self._from_string(args[0])
        elif len(args) in (2, 3):
            w, h = int(args[0]), int(args[1])
            if w < 0 or h < 0:
                raise ValueError("image size must be non-negative")
            self._w, self._h = w, h
            if len(args) == 3:
                buf = bytes(args[2])
                if len(buf) != w * h:
                    raise ValueError("image data is incorrect size")
                for v in buf:
                    if v > 9:
                        raise ValueError("brightness out of bounds")
                self._px = bytearray(buf)
            else:
                self._px = bytearray(w * h)
        else:
            raise TypeError("Image(s) takes a string")

    def _from_string(self, s):
        rows = s.rstrip(":").split(":") if s else []
        if s and "\n" in s and ":" not in s:
            rows = [r for r in s.split("\n") if r]
        width = max((len(r) for r in rows), default=0)
        px = bytearray()
        for r in rows:
            for ch in r.ljust(width, "0"):
                if ch == " ":
                    ch = "0"
                if not ch.isdigit():
                    raise ValueError("unexpected character in Image definition")
                px.append(int(ch))
        self._w, self._h, self._px = width, len(rows), px

    @classmethod
    def _const(cls, pattern):
        img = cls(pattern)
        img._readonly = True
        return img

    # --- basic access ----------------------------------------------------------------
    def width(self):
        return self._w

    def height(self):
        return self._h

    def get_pixel(self, x, y):
        if not (0 <= x < self._w and 0 <= y < self._h):
            raise ValueError("index cannot be negative" if x < 0 or y < 0 else "index too large")
        return self._px[y * self._w + x]

    def set_pixel(self, x, y, value):
        self._check_writable()
        if not (0 <= x < self._w and 0 <= y < self._h):
            raise ValueError("index cannot be negative" if x < 0 or y < 0 else "index too large")
        if not 0 <= value <= 9:
            raise ValueError("brightness out of bounds")
        self._px[y * self._w + x] = value

    def fill(self, value):
        self._check_writable()
        if not 0 <= value <= 9:
            raise ValueError("brightness out of bounds")
        for i in range(len(self._px)):
            self._px[i] = value

    def _check_writable(self):
        if self._readonly:
            raise TypeError("image cannot be modified (try copying first)")

    def copy(self):
        return Image(self._w, self._h, bytes(self._px))

    def invert(self):
        return Image(self._w, self._h, bytes(9 - v for v in self._px))

    def crop(self, x, y, w, h):
        out = Image(w, h)
        for yy in range(h):
            for xx in range(w):
                sx, sy = x + xx, y + yy
                if 0 <= sx < self._w and 0 <= sy < self._h:
                    out._px[yy * w + xx] = self._px[sy * self._w + sx]
        return out

    def shift_left(self, n):
        return self.crop(n, 0, self._w, self._h)

    def shift_right(self, n):
        return self.crop(-n, 0, self._w, self._h)

    def shift_up(self, n):
        return self.crop(0, n, self._w, self._h)

    def shift_down(self, n):
        return self.crop(0, -n, self._w, self._h)

    def blit(self, src, x, y, w, h, xdest=0, ydest=0):
        self._check_writable()
        for yy in range(h):
            for xx in range(w):
                sx, sy, dx, dy = x + xx, y + yy, xdest + xx, ydest + yy
                if 0 <= dx < self._w and 0 <= dy < self._h:
                    v = src._px[sy * src._w + sx] if 0 <= sx < src._w and 0 <= sy < src._h else 0
                    self._px[dy * self._w + dx] = v

    # --- operators ------------------------------------------------------------------
    def __add__(self, other):
        if (self._w, self._h) != (other._w, other._h):
            raise ValueError("images must be the same size")
        return Image(self._w, self._h, bytes(min(9, a + b) for a, b in zip(self._px, other._px)))

    def __mul__(self, factor):
        if factor < 0:
            raise ValueError("brightness multiplier must not be negative")
        return Image(self._w, self._h, bytes(min(9, int(v * factor + 0.5)) for v in self._px))

    __rmul__ = __mul__

    def __truediv__(self, divisor):
        return self * (1.0 / divisor)

    def __eq__(self, other):
        return isinstance(other, Image) and (self._w, self._h, self._px) == (other._w, other._h, other._px)

    def __hash__(self):
        return hash((self._w, self._h, bytes(self._px)))

    def _rows(self):
        return ["".join(str(v) for v in self._px[r * self._w:(r + 1) * self._w]) for r in range(self._h)]

    def __repr__(self):
        return "Image('" + "".join(r + ":" for r in self._rows()) + "')"

    def __str__(self):
        return "Image(\n" + "".join(f"    '{r}:'\n" for r in self._rows()) + ")"


for _name, _pattern in IMAGES.items():
    setattr(Image, _name, Image._const(_pattern))
Image.ALL_CLOCKS = tuple(getattr(Image, f"CLOCK{h}") for h in (12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11))
Image.ALL_ARROWS = tuple(getattr(Image, f"ARROW_{d}") for d in ("N", "NE", "E", "SE", "S", "SW", "W", "NW"))


def _char_columns(ch):
    """Columns (5 values each, 0/9) of a character in the micro:bit font."""
    code = ord(ch)
    rows = FONT[code - 32] if 32 <= code < 127 else FONT[ord("?") - 32]
    return [[9 if rows[r] & (0x10 >> c) else 0 for r in range(5)] for c in range(5)]


def _char_image(ch):
    cols = _char_columns(ch)
    return Image(5, 5, bytes(cols[c][r] for r in range(5) for c in range(5)))


def _scroll_columns(text, monospace):
    cols = []
    for ch in text:
        cc = _char_columns(ch)
        if not monospace:
            used = [i for i, col in enumerate(cc) if any(col)]
            cc = cc[used[0]:used[-1] + 1] if used else cc[:3]  # a space is 3 columns wide
        cols.extend(cc)
        cols.append([0] * 5)  # one blank column between letters
    return cols


class Display:
    def __init__(self, runtime):
        self._rt = runtime
        self._buf = runtime.display_buf
        self._on = True
        self._anim = 0          # animation generation; a new show/scroll cancels the old one
        self._anim_lock = threading.Lock()

    # --- pixels ---------------------------------------------------------------------
    def set_pixel(self, x, y, value):
        if not (0 <= x < 5 and 0 <= y < 5):
            raise ValueError("index out of bounds")
        if not 0 <= value <= 9:
            raise ValueError("brightness out of bounds")
        self._buf[y * 5 + x] = value

    def get_pixel(self, x, y):
        if not (0 <= x < 5 and 0 <= y < 5):
            raise ValueError("index out of bounds")
        return self._buf[y * 5 + x]

    def clear(self):
        self._cancel()
        self._buf[:] = bytes(25)

    def _blit(self, img):
        for y in range(5):
            for x in range(5):
                self._buf[y * 5 + x] = img._px[y * img._w + x] if x < img._w and y < img._h else 0

    def on(self):
        self._on = True

    def off(self):
        self._on = False

    def is_on(self):
        return self._on

    def read_light_level(self):
        """Light level 0-255 (set in the simulator's Sensors tab)."""
        return self._rt.light_level()

    # --- animations -------------------------------------------------------------------
    def _cancel(self):
        with self._anim_lock:
            self._anim += 1
            return self._anim

    def _run(self, frames_fn, wait):
        token = self._cancel()

        def alive():
            return self._anim == token

        if wait:
            frames_fn(alive)
        else:
            threading.Thread(target=frames_fn, args=(alive,), daemon=True).start()

    def show(self, image, delay=400, *, wait=True, loop=False, clear=False):
        """Show an image, a number, a string (letter by letter) or a list of images."""
        if isinstance(image, Image):
            self._cancel()
            self._blit(image)
            if clear and wait:
                time.sleep(delay / 1000.0)
                self._buf[:] = bytes(25)
            return
        if isinstance(image, (int, float)):
            image = str(image)
        if isinstance(image, str):
            frames = [_char_image(c) for c in image]
            if len(frames) == 1 and not loop:
                self._cancel()
                self._blit(frames[0])
                if clear and wait:
                    time.sleep(delay / 1000.0)
                    self._buf[:] = bytes(25)
                return
        else:
            frames = list(image)  # any iterable of images / characters
            frames = [f if isinstance(f, Image) else _char_image(str(f)[0]) for f in frames]

        def play(alive):
            while True:
                for f in frames:
                    if not alive():
                        return
                    self._blit(f)
                    _sleep_while(alive, delay)
                if not loop:
                    break
            if clear and alive():
                self._buf[:] = bytes(25)

        self._run(play, wait)

    def scroll(self, text, delay=150, *, wait=True, loop=False, monospace=False):
        """Scroll text (or a number) from right to left."""
        cols = [[0] * 5] * 5 + _scroll_columns(str(text), monospace) + [[0] * 5] * 4

        def play(alive):
            while True:
                for start in range(len(cols) - 4):
                    if not alive():
                        return
                    window = cols[start:start + 5]
                    for y in range(5):
                        for x in range(5):
                            self._buf[y * 5 + x] = window[x][y]
                    _sleep_while(alive, delay)
                if not loop:
                    break

        self._run(play, wait)


def _sleep_while(alive, ms):
    from . import runtime

    rt = runtime._runtime
    clock = rt.now if rt is not None else time.perf_counter     # simulated time (slow motion)
    end = clock() + ms / 1000.0
    while alive():
        left = end - clock()
        if left <= 0:
            return
        time.sleep(min(left, 0.02))
