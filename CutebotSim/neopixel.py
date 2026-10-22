"""Simulated ``neopixel`` module.  NeoPixels on pin15 are the Cutebot's two bottom lights."""

import microbit as _mb


class NeoPixel:
    def __init__(self, pin, n, bpp=3):
        if bpp not in (3, 4):
            raise ValueError("bpp must be 3 or 4")
        self.pin, self.n, self.bpp = pin, n, bpp
        self._px = [(0,) * bpp for _ in range(n)]

    def __len__(self):
        return self.n

    def __getitem__(self, i):
        return self._px[i]

    def __setitem__(self, i, value):
        value = tuple(value)
        if len(value) != self.bpp:
            raise ValueError(f"expected a tuple of {self.bpp} values")
        for c in value:
            if not 0 <= c <= 255:
                raise ValueError("colour values must be 0..255")
        self._px[i] = value

    def fill(self, colour):
        for i in range(self.n):
            self[i] = colour

    def clear(self):
        self._px = [(0,) * self.bpp for _ in range(self.n)]
        self.show()

    def show(self):
        if self.pin is _mb.pin15:
            _mb._rt.robot.set_neopixels(self._px[:2])

    write = show
