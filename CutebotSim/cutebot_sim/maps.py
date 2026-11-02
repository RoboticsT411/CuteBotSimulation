"""Arenas (tracks) for the simulator.  All units are centimetres.

Internal coordinates (used by the physics and drawing code):
    x to the right, y DOWN (screen frame), heading 0 = facing +x,
    positive heading = clockwise on screen.

Coordinates shown to users and stored in layout files (.json):
    origin at the bottom-left corner, x to the right, y UP,
    angle 0 = facing right, 90 = facing up (counter-clockwise).

A map has:
* the arena size (it is surrounded by walls),
* black lines for the line sensors: a list of polylines ("strokes"),
* rectangular obstacles (block the robot, seen by the ultrasonic sensor),
* a start pose.
"""

import math

DEFAULT_LINE_WIDTH_CM = 2.0  # black tape width
LINE_WIDTH_CM = DEFAULT_LINE_WIDTH_CM  # kept for older code
POINT_SPACING_CM = 0.5       # strokes are resampled to this spacing
_BUCKET_CM = 5.0             # spatial hash cell for line lookups
MIN_ARENA_CM, MAX_ARENA_CM = 30.0, 500.0


def catmull_rom(points, closed=True, samples_per_seg=24):
    """Smooth path through the control points."""
    pts = list(points)
    n = len(pts)
    out = []
    seg_count = n if closed else n - 1
    for i in range(seg_count):
        p0 = pts[(i - 1) % n] if closed or i > 0 else pts[0]
        p1 = pts[i % n]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if closed or i + 2 < n else pts[-1]
        for s in range(samples_per_seg):
            t = s / samples_per_seg
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                       + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                       + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    out.append(pts[0] if closed else pts[-1])
    return out


def densify(stroke, spacing=POINT_SPACING_CM):
    """Resample a polyline so consecutive points are at most ``spacing`` apart."""
    if len(stroke) < 2:
        return [tuple(p) for p in stroke]
    out = [tuple(stroke[0])]
    for (x0, y0), (x1, y1) in zip(stroke, stroke[1:]):
        d = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(math.ceil(d / (spacing * 1.1))))   # 10 % tolerance: saved files are rounded
        for k in range(1, n + 1):
            t = k / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out


def stroke_length(stroke):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(stroke, stroke[1:]))


class Map:
    def __init__(self, name, width, height, start, lines=(), obstacles=(),
                 line_width=DEFAULT_LINE_WIDTH_CM, colour="#ECEEEA"):
        self.name = name
        self.width = float(width)
        self.height = float(height)
        self.start = tuple(float(v) for v in start)       # (x, y, heading_deg) internal
        self.lines = [[(float(x), float(y)) for x, y in s] for s in lines if len(s) >= 2]
        self.obstacles = [tuple(float(v) for v in o) for o in obstacles]  # (x0, y0, x1, y1)
        self.line_width = float(line_width)
        self.colour = colour
        self.zones = []          # challenge zones: (kind, x0, y0, x1, y1), kind start/check/finish
        self._hash = None

    @property
    def line(self):
        """First stroke (compatibility with older code)."""
        return self.lines[0] if self.lines else []

    def copy(self):
        m = Map(self.name, self.width, self.height, self.start, self.lines, self.obstacles,
                self.line_width, self.colour)
        m.zones = list(self.zones)
        return m

    def invalidate(self):
        self._hash = None

    # --- line sensor lookup --------------------------------------------------------
    def _build_hash(self):
        h = {}
        r = self.line_width / 2.0
        for stroke in self.lines:
            for (x0, y0), (x1, y1) in zip(stroke, stroke[1:]):
                seg = (x0, y0, x1, y1)
                cx0 = int(math.floor((min(x0, x1) - r) / _BUCKET_CM))
                cx1 = int(math.floor((max(x0, x1) + r) / _BUCKET_CM))
                cy0 = int(math.floor((min(y0, y1) - r) / _BUCKET_CM))
                cy1 = int(math.floor((max(y0, y1) + r) / _BUCKET_CM))
                for cx in range(cx0, cx1 + 1):
                    for cy in range(cy0, cy1 + 1):
                        h.setdefault((cx, cy), []).append(seg)
        self._hash = h

    def is_black(self, x, y):
        """True if the point (cm, internal frame) is on a black line."""
        if not self.lines:
            return False
        if self._hash is None:
            self._build_hash()
        segs = self._hash.get((int(math.floor(x / _BUCKET_CM)), int(math.floor(y / _BUCKET_CM))))
        if not segs:
            return False
        r2 = (self.line_width / 2.0) ** 2
        for x0, y0, x1, y1 in segs:
            dx, dy = x1 - x0, y1 - y0
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / L2))
            px, py = x0 + t * dx - x, y0 + t * dy - y
            if px * px + py * py <= r2:
                return True
        return False

    # --- geometry used by sonar and collisions ------------------------------------------
    def solid_boxes(self):
        """Obstacles plus the four arena walls, as (x0, y0, x1, y1)."""
        t = 50.0
        w, h = self.width, self.height
        return self.obstacles + [(-t, -t, w + t, 0.0), (-t, h, w + t, h + t),
                                 (-t, 0.0, 0.0, h), (w, 0.0, w + t, h)]

    def raycast(self, x, y, heading_rad, max_cm=400.0, extra=()):
        """Distance (cm) from (x, y) along heading to the first solid box."""
        dx, dy = math.cos(heading_rad), math.sin(heading_rad)
        best = max_cm
        for x0, y0, x1, y1 in list(self.solid_boxes()) + list(extra):
            tmin, tmax = 0.0, best
            hit = True
            for p, d, lo, hi in ((x, dx, x0, x1), (y, dy, y0, y1)):
                if abs(d) < 1e-12:
                    if p < lo or p > hi:
                        hit = False
                        break
                else:
                    t1, t2 = (lo - p) / d, (hi - p) / d
                    if t1 > t2:
                        t1, t2 = t2, t1
                    tmin, tmax = max(tmin, t1), min(tmax, t2)
                    if tmin > tmax:
                        hit = False
                        break
            if hit and tmin < best:
                best = tmin
        return best

    # --- layout files (user frame: origin bottom-left, y up) ------------------------------
    def to_layout(self):
        H = self.height
        sx, sy, sh = self.start
        return {
            "format": "lsbu-cutebot-layout/1",
            "units": "cm; origin bottom-left; y up; angle 0 = right, 90 = up; obstacle x,y = bottom-left corner",
            "name": self.name,
            "arena": {"width": round(self.width, 2), "height": round(self.height, 2)},
            "line_width": round(self.line_width, 2),
            "start": {"x": round(sx, 2), "y": round(H - sy, 2), "angle": round(_wrap(-sh), 2)},
            "lines": [[[round(x, 2), round(H - y, 2)] for x, y in s] for s in self.lines],
            "obstacles": [{"x": round(x0, 2), "y": round(H - y1, 2),
                           "width": round(x1 - x0, 2), "height": round(y1 - y0, 2)}
                          for x0, y0, x1, y1 in self.obstacles],
            "zones": [{"type": k, "x": round(x0, 2), "y": round(H - y1, 2),
                       "width": round(x1 - x0, 2), "height": round(y1 - y0, 2)}
                      for k, x0, y0, x1, y1 in self.zones],
        }

    @classmethod
    def from_layout(cls, d):
        a = d.get("arena", {})
        W = _clamp(float(a.get("width", 100)), MIN_ARENA_CM, MAX_ARENA_CM)
        H = _clamp(float(a.get("height", 70)), MIN_ARENA_CM, MAX_ARENA_CM)
        st = d.get("start", {})
        start = (float(st.get("x", W / 2)), H - float(st.get("y", H / 2)), -float(st.get("angle", 0)))
        lines = []
        for s in d.get("lines", []):
            pts = s.get("points", []) if isinstance(s, dict) else s
            pts = [(float(p[0]), H - float(p[1])) for p in pts]
            if len(pts) >= 2:
                lines.append(densify(pts))
        obstacles = []
        for o in d.get("obstacles", []):
            x0, w, h = float(o["x"]), float(o["width"]), float(o["height"])
            y1 = H - float(o["y"])
            if w > 0 and h > 0:
                obstacles.append((x0, y1 - h, x0 + w, y1))
        m = cls(str(d.get("name", "Custom layout")), W, H, start, lines, obstacles,
                float(d.get("line_width", DEFAULT_LINE_WIDTH_CM)))
        for z in d.get("zones", []):
            try:
                kind = str(z["type"])
                x0, w, h = float(z["x"]), float(z["width"]), float(z["height"])
                y1 = H - float(z["y"])
            except (KeyError, TypeError, ValueError):
                continue
            if kind in ("start", "check", "finish") and w > 0 and h > 0:
                m.zones.append((kind, x0, y1 - h, x0 + w, y1))
        return m


def _wrap(a):
    return (a + 180.0) % 360.0 - 180.0


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------------
def _start_along(line, i):
    (x0, y0), (x1, y1) = line[i], line[i + 1]
    return (x0, y0, math.degrees(math.atan2(y1 - y0, x1 - x0)))


def _oval_track():
    w, h = 100.0, 70.0
    ctrl = [(15, h / 2 + 8), (15, h / 2 - 8), (25, 15), (w / 2, 19), (w - 25, 15),
            (w - 15, h / 2 - 8), (w - 15, h / 2 + 8), (w - 25, h - 15), (w / 2, h - 19),
            (25, h - 15)]
    line = densify(catmull_rom(ctrl, closed=True))
    i = min(range(len(line)), key=lambda k: abs(line[k][0] - 36) + abs(line[k][1] - 17))
    return Map("Line track (oval)", w, h, _start_along(line, i), lines=[line])


def _figure_eight():
    w, h = 110.0, 70.0
    cx, cy, a, b = w / 2, h / 2, 40.0, 24.0
    pts = []
    n = 400
    for k in range(n + 1):
        t = 2 * math.pi * k / n
        pts.append((cx + a * math.sin(t), cy + b * math.sin(t) * math.cos(t)))
    pts = densify(pts)
    return Map("Figure eight", w, h, _start_along(pts, len(pts) // 8), lines=[pts])


def _obstacles():
    w, h = 100.0, 70.0
    boxes = [(55, 10, 60, 30), (30, 45, 45, 50), (75, 40, 80, 62), (20, 15, 25, 25)]
    return Map("Obstacles (sonar)", w, h, (12, h / 2, 0.0), obstacles=boxes)


def _maze():
    # Serpentine maze for Lab 10: 30 cm corridors, 2 cm walls.  Start bottom-left facing up.
    w, h = 122.0, 90.0
    walls = [(30, 0, 32, 60), (61, 30, 63, 90), (92, 0, 94, 60)]
    return Map("Maze (Lab 10)", w, h, (15, h - 12, -90.0), obstacles=walls)


def _empty():
    return Map("Empty arena", 100.0, 70.0, (50.0, 35.0, 0.0))


MAP_FACTORIES = [_oval_track, _figure_eight, _obstacles, _maze, _empty]
MAP_NAMES = [f().name for f in MAP_FACTORIES]


def get_map(map_id):
    """A fresh copy of a preset arena."""
    map_id = map_id if 0 <= map_id < len(MAP_FACTORIES) else 0
    return MAP_FACTORIES[map_id]()
