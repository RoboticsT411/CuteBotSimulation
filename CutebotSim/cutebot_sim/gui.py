"""The simulator window.  Started automatically by ``import microbit``;
you can also open it yourself with ``python -m cutebot_sim.gui``.

The window owns the "world" (arena size, black lines, obstacles, start pose)
and lets the user edit it; the running program receives the world through
shared memory and simulates the robot in it.  One window is reused for every
run (like re-flashing the same micro:bit).

Coordinates shown to the user: origin bottom-left, y up, angle 0 = right,
90 = up.  Internally (maps.py) y points down.
"""

import json
import math
import os
import random
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import maps, robot as R, shared

FRAME_MS = 16
PANEL_W = 340
BG = "#1F2328"
PANEL_BG = "#262B31"
FIELD_BG = "#1B1F24"
TEXT = "#E6E8EA"
MUTED = "#9AA3AD"
ACCENT = "#4FB3FF"
OK = "#3FB950"
ERR = "#FF7B72"
LED_OFF = "#3A1414"
OBST_FILL = "#B5834F"
OBST_EDGE = "#6E4A27"
STALE_S = 0.6

ERASER_CM = 2.5          # eraser radius
JOIN_CM = 3.0            # a new stroke joins an existing line end closer than this
ROBOT_GRAB_CM = 6.0

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTOSAVE_FILE = os.path.join(PROJECT_DIR, "sim_layout.json")
LAYOUT_DIR = os.path.join(PROJECT_DIR, "layouts")

MODES = [("move", "Move", "1"), ("draw", "Draw line", "2"), ("erase", "Erase", "3"),
         ("box", "Draw obstacle", "4")]
MODE_HINT = {
    "move": "Drag the robot or an obstacle.  Click an obstacle then press Delete to remove it.",
    "draw": "Drag to draw a line.  Hold Shift for a straight line.  Ends join automatically.",
    "erase": "Drag over a line to erase it.  Click an obstacle to delete it.",
    "box": "Drag a rectangle to create an obstacle.",
}
HELP = ("Keys 1-4: tools   Q/E or wheel: rotate 15° (Shift 1°)\n"
        "A/B: micro:bit buttons   Delete key / right-click: delete obstacle")


def _rgb(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def _mix(c, bg=(40, 40, 40), k=1.0):
    return tuple(int(bg[i] + (c[i] - bg[i]) * k) for i in range(3))


def _wrap(a):
    return (a + 180.0) % 360.0 - 180.0


def _is_closed(stroke):
    return len(stroke) > 2 and math.hypot(stroke[0][0] - stroke[-1][0],
                                          stroke[0][1] - stroke[-1][1]) < 0.01


def _smooth(pts, passes=2, k=2):
    """Moving-average smoothing of a freehand stroke (ends fixed)."""
    if len(pts) < 2 * k + 2:
        return pts
    for _ in range(passes):
        out = [pts[0]]
        for i in range(1, len(pts) - 1):
            lo, hi = max(0, i - k), min(len(pts), i + k + 1)
            n = hi - lo
            out.append((sum(p[0] for p in pts[lo:hi]) / n, sum(p[1] for p in pts[lo:hi]) / n))
        out.append(pts[-1])
        pts = out
    return pts


class SimWindow:
    def __init__(self, root, sh):
        self.root = root
        self.sh = sh
        self.world = self._load_autosave() or maps.get_map(0)
        self.layout_path = None
        self.scale = 6.0
        self.ox = self.oy = 20.0
        self.drag = None                 # current mouse action
        self.last_prog_tick = None
        self.last_prog_change = 0.0
        self.keys_down = set()
        self._preview_pose = None
        self._preview_t = 0.0
        self._robot_items = None
        self._hover_items = None
        self._marker = None
        self._save_job = None
        self.motor_gain = [1.0, 1.0]
        self.gain_hidden = False
        self.trail = []                  # list of segments, each a list of (x, y) internal
        self._trail_items = []
        self.show_trail = None           # tk.BooleanVar, created with the Motors tab
        self._run_gen = None
        self._run_start = None           # pose where the straightness measurement starts
        self._load_sim_settings()

        root.title("Cutebot simulator - LSBU")
        root.configure(bg=BG)
        root.geometry("1200x780")
        root.minsize(900, 600)

        # --- left: toolbar + canvas ---------------------------------------------------
        left = tk.Frame(root, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        bar = tk.Frame(left, bg=BG)
        bar.pack(fill="x", padx=10, pady=(8, 0))
        self.mode = tk.StringVar(value="move")
        for key, label, num in MODES:
            tk.Radiobutton(bar, text=f"{num}  {label}", value=key, variable=self.mode,
                           indicatoron=0, command=self._on_mode, bg="#2D333B", fg=TEXT,
                           selectcolor="#1F6FEB", activebackground="#3A424D",
                           activeforeground=TEXT, relief="flat", padx=10, pady=4,
                           bd=0, highlightthickness=0).pack(side="left", padx=(0, 4))
        self.coord_label = tk.Label(bar, text="", bg=BG, fg=TEXT, font=("Consolas", 11, "bold"))
        self.coord_label.pack(side="right")
        self.hint = tk.Label(left, text=MODE_HINT["move"], bg=BG, fg=MUTED, anchor="w",
                             font=("Segoe UI", 9))
        self.hint.pack(fill="x", padx=12, pady=(4, 0))

        self.canvas = tk.Canvas(left, bg=BG, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        # --- right: micro:bit + readouts + tabs ------------------------------------------
        panel = tk.Frame(root, bg=PANEL_BG, width=PANEL_W)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)

        self.board = tk.Canvas(panel, width=PANEL_W - 20, height=180, bg=PANEL_BG,
                               highlightthickness=0)
        self.board.pack(padx=10, pady=(10, 2))
        self._build_board()

        self.status = tk.Label(panel, text="", bg=PANEL_BG, fg=MUTED,
                               font=("Segoe UI", 11, "bold"), wraplength=PANEL_W - 24,
                               justify="left", anchor="w")
        self.status.pack(fill="x", padx=12, pady=(2, 0))
        self.message = tk.Label(panel, text="", bg=PANEL_BG, fg=ERR, font=("Consolas", 9),
                                wraplength=PANEL_W - 24, justify="left", anchor="w")
        self.message.pack(fill="x", padx=12)
        self.readout = tk.Label(panel, text="", bg=PANEL_BG, fg=TEXT, font=("Consolas", 10),
                                justify="left", anchor="w")
        self.readout.pack(fill="x", padx=12, pady=(4, 6))

        self.tabs = ttk.Notebook(panel)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self._build_robot_tab()
        self._build_motor_tab()
        self._build_obstacle_tab()
        self._build_arena_tab()

        tk.Label(panel, text=HELP, bg=PANEL_BG, fg=MUTED, justify="left", anchor="w",
                 font=("Segoe UI", 8)).pack(fill="x", padx=10, pady=(0, 8))

        # --- events -----------------------------------------------------------------------
        c = self.canvas
        c.bind("<Configure>", lambda e: self._draw_map())
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<ButtonPress-3>", self._on_right_click)
        c.bind("<Motion>", self._on_hover)
        c.bind("<Leave>", lambda e: self._hide_hover())
        c.bind("<MouseWheel>", lambda e: self._rotate_ccw(self._step(e) * (1 if e.delta > 0 else -1)))
        c.bind("<Button-4>", lambda e: self._rotate_ccw(self._step(e)))
        c.bind("<Button-5>", lambda e: self._rotate_ccw(-self._step(e)))
        root.bind("<KeyPress>", self._on_key_down)
        root.bind("<KeyRelease>", self._on_key_up)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._world_changed(save=False)
        self._publish_gain()
        self._tick()

    # =====================================================================================
    # coordinates
    # =====================================================================================
    def _fit(self):
        cw = max(self.canvas.winfo_width(), 100)
        ch = max(self.canvas.winfo_height(), 100)
        m = self.world
        self.scale = min((cw - 50) / m.width, (ch - 50) / m.height)
        self.ox = (cw - m.width * self.scale) / 2
        self.oy = (ch - m.height * self.scale) / 2 - 6

    def w2s(self, x, y):
        return self.ox + x * self.scale, self.oy + y * self.scale

    def s2w(self, sx, sy):
        return (sx - self.ox) / self.scale, (sy - self.oy) / self.scale

    def to_user(self, x, y):
        return x, self.world.height - y

    def from_user(self, ux, uy):
        return ux, self.world.height - uy

    def _clamp_in(self, x, y):
        return (min(max(x, 0.0), self.world.width), min(max(y, 0.0), self.world.height))

    # =====================================================================================
    # micro:bit board
    # =====================================================================================
    def _build_board(self):
        b = self.board
        w = PANEL_W - 20
        b.create_rectangle(4, 4, w - 4, 176, fill="#111418", outline="#3C444D", width=2)
        b.create_text(w / 2, 18, text="micro:bit", fill=MUTED, font=("Segoe UI", 10, "bold"))
        self.leds = []
        size, gap = 19, 10
        gx = (w - (5 * size + 4 * gap)) / 2
        gy = 34
        for y in range(5):
            for x in range(5):
                x0 = gx + x * (size + gap)
                y0 = gy + y * (size + gap)
                self.leds.append(b.create_rectangle(x0, y0, x0 + size * 0.55, y0 + size,
                                                    fill=LED_OFF, outline=""))
        self.btn_items = {}
        for name, cx in (("a", 34), ("b", w - 34)):
            oval = b.create_oval(cx - 16, 76, cx + 16, 108, fill="#2B2F35", outline="#5B6670", width=2)
            b.create_text(cx, 122, text=name.upper(), fill=TEXT, font=("Segoe UI", 11, "bold"))
            self.btn_items[name] = oval
            b.tag_bind(oval, "<ButtonPress-1>", lambda e, n=name: self._button(n, True))
            b.tag_bind(oval, "<ButtonRelease-1>", lambda e, n=name: self._button(n, False))

    def _button(self, name, down):
        key = f"btn_{name}_down"
        was = self.sh.get(key)
        self.sh.set(key, 1 if down else 0)
        if down and not was:
            self.sh.bump(f"btn_{name}_count")
        self.board.itemconfigure(self.btn_items[name], fill="#4A5561" if down else "#2B2F35")

    # =====================================================================================
    # small widget helpers
    # =====================================================================================
    @staticmethod
    def _set_entry(entry, value):
        entry.delete(0, "end")
        entry.insert(0, str(value))

    @staticmethod
    def _num(entry, name):
        try:
            return float(entry.get().strip().replace(",", "."))
        except ValueError:
            raise ValueError(f"{name}: enter a number")

    def _field(self, parent, label, row, col, store, key):
        tk.Label(parent, text=label, bg=PANEL_BG, fg=MUTED).grid(row=row, column=col, sticky="e",
                                                                 padx=(4, 2), pady=3)
        e = tk.Entry(parent, width=7, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT,
                     relief="flat", justify="right")
        e.grid(row=row, column=col + 1, sticky="w", pady=3)
        store[key] = e
        return e

    def _btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg="#33404D", fg=TEXT,
                         activebackground="#40505F", activeforeground=TEXT, relief="flat",
                         padx=6, pady=2)

    def _tab(self, title):
        f = tk.Frame(self.tabs, bg=PANEL_BG)
        self.tabs.add(f, text=f"  {title}  ")
        return f

    def _typing(self):
        try:
            w = self.root.focus_get()
        except (KeyError, tk.TclError):
            return False
        return isinstance(w, (tk.Entry, ttk.Entry))

    # =====================================================================================
    # Robot tab
    # =====================================================================================
    def _build_robot_tab(self):
        f = self._tab("Robot")
        tk.Label(f, text="Position (cm) and angle (°)", bg=PANEL_BG, fg=MUTED,
                 anchor="w").pack(fill="x", padx=6, pady=(8, 0))
        grid = tk.Frame(f, bg=PANEL_BG)
        grid.pack(fill="x", padx=2)
        self.pose_entries = {}
        self._field(grid, "x", 0, 0, self.pose_entries, "x")
        self._field(grid, "y", 0, 2, self.pose_entries, "y")
        self._field(grid, "angle", 1, 0, self.pose_entries, "a")
        self._btn(grid, "Place robot", self._apply_pose).grid(row=1, column=2, columnspan=2,
                                                               sticky="we", padx=(6, 0))
        for e in self.pose_entries.values():
            e.bind("<Return>", lambda _e: self._apply_pose())

        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(6, 2))
        tk.Label(row, text="Face", bg=PANEL_BG, fg=MUTED).pack(side="left")
        for txt, deg in (("0° →", 0), ("90° ↑", 90), ("180° ←", 180),
                         ("270° ↓", 270)):
            self._btn(row, txt, lambda d=deg: self._face(d)).pack(side="left", padx=2)

        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(8, 2))
        self._btn(row, "Reset to start", self._reset_pose).pack(side="left", fill="x", expand=True)
        self._btn(row, "Set start here", self._set_start).pack(side="left", fill="x", expand=True,
                                                               padx=(6, 0))
        self.robot_msg = tk.Label(f, text="", bg=PANEL_BG, fg=MUTED, anchor="w", justify="left",
                                  wraplength=PANEL_W - 40)
        self.robot_msg.pack(fill="x", padx=6, pady=(6, 0))

    def _apply_pose(self):
        try:
            ux = self._num(self.pose_entries["x"], "x")
            uy = self._num(self.pose_entries["y"], "y")
            a = self._num(self.pose_entries["a"], "angle")
        except ValueError as e:
            self.robot_msg.configure(text=str(e), fg=ERR)
            return
        m = self.world
        if not (0 <= ux <= m.width and 0 <= uy <= m.height):
            self.robot_msg.configure(text=f"x must be 0..{m.width:g}, y 0..{m.height:g}", fg=ERR)
            return
        self.robot_msg.configure(text="")
        x, y = self.from_user(ux, uy)
        self._request_pose(x, y, -a)
        self.root.focus_set()

    def _face(self, deg):
        x, y, _ = self._current_pose()
        self._request_pose(x, y, -deg)

    def _set_start(self):
        self.world.start = tuple(self._current_pose())
        x, y = self.to_user(*self.world.start[:2])
        self.robot_msg.configure(text=f"Start set to x {x:.1f}, y {y:.1f}, "
                                      f"angle {_wrap(-self.world.start[2]):.0f}°", fg=OK)
        self._world_changed(redraw=False)

    # =====================================================================================
    # Obstacles tab
    # =====================================================================================
    def _build_obstacle_tab(self):
        f = self._tab("Obstacles")
        tk.Label(f, text="Bottom-left corner (x, y) and size, all in cm", bg=PANEL_BG, fg=MUTED,
                 anchor="w").pack(fill="x", padx=6, pady=(8, 0))
        grid = tk.Frame(f, bg=PANEL_BG)
        grid.pack(fill="x", padx=2)
        self.obs_entries = {}
        self._field(grid, "x", 0, 0, self.obs_entries, "x")
        self._field(grid, "y", 0, 2, self.obs_entries, "y")
        self._field(grid, "width", 1, 0, self.obs_entries, "w")
        self._field(grid, "height", 1, 2, self.obs_entries, "h")
        self._set_entry(self.obs_entries["w"], 10)
        self._set_entry(self.obs_entries["h"], 5)
        self._btn(grid, "Add", self._add_obstacle_from_fields).grid(row=0, column=4, rowspan=2,
                                                                    sticky="ns", padx=(8, 0), pady=3)
        for e in self.obs_entries.values():
            e.bind("<Return>", lambda _e: self._add_obstacle_from_fields())

        self.obs_list = tk.Listbox(f, height=6, bg=FIELD_BG, fg=TEXT, relief="flat",
                                   selectbackground="#40505F", font=("Consolas", 9),
                                   activestyle="none", exportselection=False)
        self.obs_list.pack(fill="both", expand=True, padx=6, pady=(4, 2))
        self.obs_list.bind("<<ListboxSelect>>", lambda e: self._draw_map())
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=2)
        self._btn(row, "Delete selected", self._remove_selected).pack(side="left")
        self._btn(row, "Clear all", self._clear_obstacles).pack(side="left", padx=6)
        self.obs_msg = tk.Label(f, text="Or use tool 4 to drag out an obstacle,\n"
                                        "and tool 1 to move one.",
                                bg=PANEL_BG, fg=MUTED, anchor="w", justify="left")
        self.obs_msg.pack(fill="x", padx=6, pady=(0, 4))

    def _add_obstacle_from_fields(self):
        try:
            ux = self._num(self.obs_entries["x"], "x")
            uy = self._num(self.obs_entries["y"], "y")
            w = self._num(self.obs_entries["w"], "width")
            h = self._num(self.obs_entries["h"], "height")
        except ValueError as e:
            self.obs_msg.configure(text=str(e), fg=ERR)
            return
        x0, y1 = self.from_user(ux, uy)
        self._add_obstacle((x0, y1 - h, x0 + w, y1))
        self.root.focus_set()

    def _add_obstacle(self, box):
        m = self.world
        x0, y0, x1, y1 = box
        if x1 - x0 < 0.5 or y1 - y0 < 0.5:
            self.obs_msg.configure(text="Width and height must be at least 0.5 cm", fg=ERR)
            return False
        if x1 <= 0 or y1 <= 0 or x0 >= m.width or y0 >= m.height:
            self.obs_msg.configure(text="That obstacle is outside the arena", fg=ERR)
            return False
        if len(m.obstacles) >= shared.MAX_OBSTACLES:
            self.obs_msg.configure(text=f"Maximum {shared.MAX_OBSTACLES} obstacles", fg=ERR)
            return False
        box = (max(0.0, x0), max(0.0, y0), min(m.width, x1), min(m.height, y1))
        m.obstacles.append(box)
        self.obs_msg.configure(text=f"Added obstacle {len(m.obstacles)}: "
                                    f"{box[2] - box[0]:g} x {box[3] - box[1]:g} cm", fg=OK)
        self._world_changed()
        return True

    def _remove_selected(self):
        sel = self.obs_list.curselection()
        if sel:
            self._delete_obstacle(sel[0])
        else:
            self.obs_msg.configure(text="Select an obstacle first (click it in the list or on "
                                        "the arena)", fg=ERR)

    def _delete_obstacle(self, i):
        if 0 <= i < len(self.world.obstacles):
            del self.world.obstacles[i]
            self.obs_list.selection_clear(0, "end")
            self.obs_msg.configure(text=f"Deleted obstacle {i + 1}", fg=OK)
            self._world_changed()

    def _clear_obstacles(self):
        if self.world.obstacles and messagebox.askyesno("Clear obstacles",
                                                        "Remove all obstacles?", parent=self.root):
            self.world.obstacles = []
            self._world_changed()

    def _obstacle_at(self, x, y, tol=0.3):
        obs = self.world.obstacles
        for i in range(len(obs) - 1, -1, -1):
            x0, y0, x1, y1 = obs[i]
            if x0 - tol <= x <= x1 + tol and y0 - tol <= y <= y1 + tol:
                return i
        return None

    def _refresh_obstacle_list(self):
        sel = self.obs_list.curselection()
        self.obs_list.delete(0, "end")
        for i, (x0, y0, x1, y1) in enumerate(self.world.obstacles):
            ux, uy = self.to_user(x0, y1)
            self.obs_list.insert("end", f"{i + 1:2d}  x {ux:6.1f}  y {uy:6.1f}   "
                                        f"{x1 - x0:g} x {y1 - y0:g} cm")
        if sel and sel[0] < self.obs_list.size():
            self.obs_list.selection_set(sel[0])

    # =====================================================================================
    # Arena tab
    # =====================================================================================
    def _build_arena_tab(self):
        f = self._tab("Arena")
        tk.Label(f, text="Arena size (cm)", bg=PANEL_BG, fg=MUTED, anchor="w").pack(
            fill="x", padx=6, pady=(8, 0))
        grid = tk.Frame(f, bg=PANEL_BG)
        grid.pack(fill="x", padx=2)
        self.arena_entries = {}
        self._field(grid, "width", 0, 0, self.arena_entries, "w")
        self._field(grid, "height", 0, 2, self.arena_entries, "h")
        self._field(grid, "line width", 1, 0, self.arena_entries, "lw")
        self._btn(grid, "Apply", self._apply_arena).grid(row=1, column=2, columnspan=2,
                                                         sticky="we", padx=(6, 0))
        for e in self.arena_entries.values():
            e.bind("<Return>", lambda _e: self._apply_arena())

        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(10, 2))
        tk.Label(row, text="Preset", bg=PANEL_BG, fg=MUTED).pack(side="left")
        self.preset_var = tk.StringVar(value=maps.MAP_NAMES[0])
        ttk.Combobox(row, textvariable=self.preset_var, values=maps.MAP_NAMES, state="readonly",
                     width=20).pack(side="left", padx=6)
        self._btn(row, "Load", self._load_preset).pack(side="left")

        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(10, 2))
        self._btn(row, "Clear all lines", self._clear_lines).pack(side="left", fill="x", expand=True)
        self._btn(row, "Empty arena", self._new_empty).pack(side="left", fill="x", expand=True,
                                                            padx=(6, 0))
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(6, 2))
        self._btn(row, "Save layout...", self._save_layout).pack(side="left", fill="x", expand=True)
        self._btn(row, "Open layout...", self._open_layout).pack(side="left", fill="x", expand=True,
                                                                 padx=(6, 0))
        self.arena_msg = tk.Label(f, text="", bg=PANEL_BG, fg=MUTED, anchor="w", justify="left",
                                  wraplength=PANEL_W - 40)
        self.arena_msg.pack(fill="x", padx=6, pady=(6, 0))

    def _fill_arena_fields(self):
        m = self.world
        self._set_entry(self.arena_entries["w"], f"{m.width:g}")
        self._set_entry(self.arena_entries["h"], f"{m.height:g}")
        self._set_entry(self.arena_entries["lw"], f"{m.line_width:g}")

    def _apply_arena(self):
        try:
            w = self._num(self.arena_entries["w"], "width")
            h = self._num(self.arena_entries["h"], "height")
            lw = self._num(self.arena_entries["lw"], "line width")
        except ValueError as e:
            self.arena_msg.configure(text=str(e), fg=ERR)
            return
        lo, hi = maps.MIN_ARENA_CM, maps.MAX_ARENA_CM
        if not (lo <= w <= hi and lo <= h <= hi):
            self.arena_msg.configure(text=f"Width and height must be {lo:g}..{hi:g} cm", fg=ERR)
            return
        if not 0.5 <= lw <= 10:
            self.arena_msg.configure(text="Line width must be 0.5..10 cm", fg=ERR)
            return
        m = self.world
        dh = h - m.height              # keep everything anchored to the bottom-left corner
        pose = self._current_pose()
        m.lines = [[(x, y + dh) for x, y in s] for s in m.lines]
        boxes = []
        for x0, y0, x1, y1 in m.obstacles:
            b = (x0, y0 + dh, min(x1, w), min(y1 + dh, h))
            b = (b[0], max(0.0, b[1]), b[2], b[3])
            if b[2] - b[0] >= 0.5 and b[3] - b[1] >= 0.5:
                boxes.append(b)
        m.obstacles = boxes
        sx, sy, sh = m.start
        m.width, m.height, m.line_width = w, h, lw
        m.start = (min(sx, w), min(max(sy + dh, 0.0), h), sh)
        px, py = self._clamp_in(pose[0], pose[1] + dh)
        self._request_pose(px, py, pose[2])
        self.arena_msg.configure(text=f"Arena is now {w:g} x {h:g} cm", fg=OK)
        self._world_changed()
        self.root.focus_set()

    def _confirm_replace(self, what):
        m = self.world
        if not (m.lines or m.obstacles):
            return True
        return messagebox.askyesno(what, "This replaces the current lines and obstacles.\n"
                                         "Save your layout first if you want to keep it.\n\n"
                                         "Continue?", parent=self.root)

    def _set_world(self, world, msg):
        self.world = world
        self._fill_arena_fields()
        self.arena_msg.configure(text=msg, fg=OK)
        self._world_changed()      # publish the new world first,
        self._reset_pose()         # then ask the program to move to its start

    def _load_preset(self):
        name = self.preset_var.get()
        if name in maps.MAP_NAMES and self._confirm_replace("Load preset"):
            self.layout_path = None
            self._set_world(maps.get_map(maps.MAP_NAMES.index(name)), f"Loaded preset: {name}")

    def _new_empty(self):
        if self._confirm_replace("Empty arena"):
            m = self.world
            self._set_world(maps.Map("Empty arena", m.width, m.height,
                                     (m.width / 2, m.height / 2, 0.0), line_width=m.line_width),
                            "Empty arena - draw a line with tool 2")

    def _clear_lines(self):
        if self.world.lines and messagebox.askyesno("Clear lines", "Remove all black lines?",
                                                    parent=self.root):
            self.world.lines = []
            self._world_changed()

    def _save_layout(self):
        os.makedirs(LAYOUT_DIR, exist_ok=True)
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save layout", defaultextension=".json",
            initialdir=os.path.dirname(self.layout_path) if self.layout_path else LAYOUT_DIR,
            initialfile=os.path.basename(self.layout_path) if self.layout_path else "my_track.json",
            filetypes=[("Cutebot layout", "*.json")])
        if not path:
            return
        self.world.name = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self._layout_with_settings(), fh, indent=1)
        except OSError as e:
            self.arena_msg.configure(text=f"Could not save: {e}", fg=ERR)
            return
        self.layout_path = path
        self.arena_msg.configure(text=f"Saved {os.path.basename(path)}", fg=OK)

    def _open_layout(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="Open layout",
            initialdir=LAYOUT_DIR if os.path.isdir(LAYOUT_DIR) else PROJECT_DIR,
            filetypes=[("Cutebot layout", "*.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            world = maps.Map.from_layout(data)
        except (OSError, ValueError, KeyError, TypeError) as e:
            self.arena_msg.configure(text=f"Not a valid layout file: {e}", fg=ERR)
            return
        self.layout_path = path
        if isinstance(data.get("simulator"), dict):
            self._apply_sim_settings(data["simulator"])
        self._set_world(world, f"Opened {os.path.basename(path)}")

    # =====================================================================================
    # world publishing / saving
    # =====================================================================================
    def _world_changed(self, redraw=True, save=True):
        self.world.invalidate()
        try:
            shared.write_world(self.sh, self.world)
        except ValueError:
            # too many line points: drop the newest stroke
            if self.world.lines:
                self.world.lines.pop()
            self.arena_msg.configure(text="The line is too long - stroke not added.", fg=ERR)
            shared.write_world(self.sh, self.world)
        self._refresh_obstacle_list()
        if redraw:
            self._draw_map()
        if save:
            if self._save_job is not None:
                self.root.after_cancel(self._save_job)
            self._save_job = self.root.after(700, self._autosave)

    def _autosave(self):
        self._save_job = None
        try:
            tmp = AUTOSAVE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._layout_with_settings(), fh)
            os.replace(tmp, AUTOSAVE_FILE)
        except OSError:
            pass

    @staticmethod
    def _load_autosave():
        try:
            with open(AUTOSAVE_FILE, encoding="utf-8") as fh:
                return maps.Map.from_layout(json.load(fh))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    # =====================================================================================
    # drawing
    # =====================================================================================
    def _draw_map(self):
        c = self.canvas
        c.delete("all")
        self._robot_items = None
        self._hover_items = None
        self._marker = None
        self._fit()
        m, s = self.world, self.scale
        x0, y0 = self.w2s(0, 0)
        x1, y1 = self.w2s(m.width, m.height)
        c.create_rectangle(x0 - 6, y0 - 6, x1 + 6, y1 + 6, fill="#5A4632", outline="")
        c.create_rectangle(x0, y0, x1, y1, fill=m.colour, outline="")
        step = 10 if m.width <= 250 and m.height <= 250 else 20
        for gx in range(step, int(m.width) + 1, step):
            if gx < m.width:
                sx, _ = self.w2s(gx, 0)
                c.create_line(sx, y0, sx, y1, fill="#DCDFDA")
        for gy in range(step, int(m.height) + 1, step):
            if gy < m.height:
                _, sy = self.w2s(0, m.height - gy)
                c.create_line(x0, sy, x1, sy, fill="#DCDFDA")
        lw = max(1, m.line_width * s)
        for stroke in m.lines:
            pts = []
            for px, py in stroke:
                pts.extend(self.w2s(px, py))
            c.create_line(*pts, fill="#202020", width=lw, capstyle="round", joinstyle="round")
        sel = self.obs_list.curselection()
        for i, (bx0, by0, bx1, by1) in enumerate(m.obstacles):
            a, b = self.w2s(bx0, by0)
            cc, d = self.w2s(bx1, by1)
            selected = sel and sel[0] == i
            c.create_rectangle(a, b, cc, d, fill=OBST_FILL, outline="#FFD33D" if selected else OBST_EDGE,
                               width=3 if selected else 2)
            if min(cc - a, d - b) > 16:
                c.create_text((a + cc) / 2, (b + d) / 2, fill="#FFFFFF",
                              font=("Segoe UI", 8, "bold"), text=f"{i + 1}")
        # start marker
        sx, sy = self.w2s(*m.start[:2])
        c.create_oval(sx - 4, sy - 4, sx + 4, sy + 4, outline="#1F6FEB", width=2)
        # axes at the origin (bottom-left)
        c.create_line(x0, y1, x0 + 34, y1, fill="#C0392B", width=2, arrow="last")
        c.create_line(x0, y1, x0, y1 - 34, fill="#27AE60", width=2, arrow="last")
        c.create_text(x0 + 40, y1 - 2, text="x", fill="#C0392B", anchor="w",
                      font=("Segoe UI", 9, "bold"))
        c.create_text(x0 + 4, y1 - 42, text="y", fill="#27AE60", anchor="w",
                      font=("Segoe UI", 9, "bold"))
        c.create_text(x0, y1 + 16, anchor="w", fill=MUTED, font=("Segoe UI", 9),
                      text=f"{m.width:g} x {m.height:g} cm   grid {step} cm   origin bottom-left"
                           f"   start = blue circle")
        self._trail_items = []
        self._draw_trail(full=True)

    def _make_robot_items(self):
        c = self.canvas
        it = {}
        it["ray"] = c.create_line(0, 0, 0, 0, fill=ACCENT, dash=(4, 3), width=1, state="hidden")
        it["ray_txt"] = c.create_text(0, 0, text="", fill="#1C5F8F", font=("Segoe UI", 9, "bold"),
                                      state="hidden")
        it["neo"] = [c.create_oval(0, 0, 0, 0, fill="", outline="") for _ in range(2)]
        it["wheels"] = [c.create_polygon(0, 0, 0, 0, fill="#151515", outline="") for _ in range(2)]
        it["body"] = c.create_polygon(0, 0, 0, 0, fill="#2A2E33", outline="#0E0F10", width=2)
        it["board"] = c.create_polygon(0, 0, 0, 0, fill="#1B1E22", outline="#55606A")
        it["lights"] = [c.create_oval(0, 0, 0, 0, fill="#555", outline="#111") for _ in range(2)]
        it["sensors"] = [c.create_oval(0, 0, 0, 0, fill="#999", outline="#111") for _ in range(2)]
        it["sonar"] = c.create_polygon(0, 0, 0, 0, fill="#C9CED3", outline="#555")
        self._robot_items = it

    def _update_robot(self, pose, lights, neo, line, sonar_cm, sonar_active):
        if self._robot_items is None:
            self._make_robot_items()
        c, it, s = self.canvas, self._robot_items, self.scale
        x, y, hdeg = pose
        h = math.radians(hdeg)
        ch, shh = math.cos(h), math.sin(h)

        def P(ahead, left):
            return self.w2s(x + ahead * ch + left * shh, y + ahead * shh - left * ch)

        def poly(pts):
            out = []
            for a, l in pts:
                out.extend(P(a, l))
            return out

        shape = R.robot_shape()
        c.coords(it["body"], *poly(shape["body"]))
        c.coords(it["board"], *poly(shape["board"]))
        for i in range(2):
            c.coords(it["wheels"][i], *poly(shape["wheels"][i]))
        c.coords(it["sonar"], *poly(shape["sonar"]))
        r = shape["light_r"] * s
        gr = shape["glow_r"] * s
        for i in range(2):
            lx, ly = P(*shape["lights"][i])
            c.coords(it["lights"][i], lx - r, ly - r, lx + r, ly + r)
            rgb = lights[i * 3:i * 3 + 3]
            c.itemconfigure(it["lights"][i], fill=_rgb(*rgb) if any(rgb) else "#4A4F55")
            nx, ny = P(*shape["neopixels"][i])
            glow = neo[i * 3:i * 3 + 3]
            c.coords(it["neo"][i], nx - gr, ny - gr, nx + gr, ny + gr)
            c.itemconfigure(it["neo"][i],
                            fill=_rgb(*_mix(glow, (236, 238, 234), 0.55)) if any(glow) else "")
        g = R.LINE_SENSOR_GAP_CM / 2
        sr = shape["sensor_r"] * s
        for i, side in enumerate((1, -1)):
            sx, sy = P(R.LINE_SENSOR_AHEAD_CM, side * g)
            c.coords(it["sensors"][i], sx - sr, sy - sr, sx + sr, sy + sr)
            c.itemconfigure(it["sensors"][i], fill="#2F8CFF" if line[i] == 0 else "#B8BEC4")
        if sonar_active:
            a = P(R.SONAR_AHEAD_CM, 0)
            b = P(R.SONAR_AHEAD_CM + min(sonar_cm, R.SONAR_MAX_CM), 0)
            c.coords(it["ray"], *a, *b)
            c.coords(it["ray_txt"], (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 10)
            c.itemconfigure(it["ray_txt"], text=f"{sonar_cm:.0f} cm", state="normal")
            c.itemconfigure(it["ray"], state="normal")
        else:
            c.itemconfigure(it["ray"], state="hidden")
            c.itemconfigure(it["ray_txt"], state="hidden")
        for item in (it["ray"], it["ray_txt"], *it["neo"], *it["wheels"], it["body"], it["board"],
                     *it["lights"], *it["sensors"], it["sonar"]):
            c.tag_raise(item)
        if self._hover_items:
            for item in self._hover_items:
                c.tag_raise(item)

    # =====================================================================================
    # hover read-out
    # =====================================================================================
    def _on_hover(self, e):
        wx, wy = self.s2w(e.x, e.y)
        m = self.world
        inside = 0 <= wx <= m.width and 0 <= wy <= m.height
        if not inside:
            self._hide_hover()
            return
        ux, uy = self.to_user(wx, wy)
        text = f"x {ux:5.1f}  y {uy:5.1f} cm"
        self.coord_label.configure(text=text)
        c = self.canvas
        if self._hover_items is None:
            bg = c.create_rectangle(0, 0, 0, 0, fill="#FFFFFF", outline="#8A939C")
            txt = c.create_text(0, 0, text="", fill="#1F2328", anchor="nw", font=("Consolas", 9))
            ring = c.create_oval(0, 0, 0, 0, outline="#E5534B", width=2, state="hidden")
            self._hover_items = (bg, txt, ring)
        bg, txt, ring = self._hover_items
        tx, ty = e.x + 14, e.y + 14
        if tx + 130 > c.winfo_width():
            tx = e.x - 140
        if ty + 20 > c.winfo_height():
            ty = e.y - 30
        c.itemconfigure(txt, text=f"{ux:.1f}, {uy:.1f}", state="normal")
        c.coords(txt, tx + 4, ty + 2)
        bx = c.bbox(txt)
        if bx:
            c.coords(bg, bx[0] - 3, bx[1] - 1, bx[2] + 3, bx[3] + 1)
        c.itemconfigure(bg, state="normal")
        if self.mode.get() == "erase":
            r = ERASER_CM * self.scale
            c.coords(ring, e.x - r, e.y - r, e.x + r, e.y + r)
            c.itemconfigure(ring, state="normal")
        else:
            c.itemconfigure(ring, state="hidden")
        for item in self._hover_items:
            c.tag_raise(item)
        if self.mode.get() == "move" and self.drag is None:
            x, y, _ = self._current_pose()
            grab = math.hypot(wx - x, wy - y) < ROBOT_GRAB_CM or self._obstacle_at(wx, wy) is not None
            c.configure(cursor="fleur" if grab else "crosshair")

    def _hide_hover(self):
        self.coord_label.configure(text="")
        if self._hover_items:
            for item in self._hover_items:
                self.canvas.itemconfigure(item, state="hidden")

    def _mark(self, wx, wy):
        if self._marker:
            for it in self._marker:
                self.canvas.delete(it)
        sx, sy = self.w2s(wx, wy)
        self._marker = (self.canvas.create_line(sx - 7, sy, sx + 7, sy, fill="#E5534B", width=2),
                        self.canvas.create_line(sx, sy - 7, sx, sy + 7, fill="#E5534B", width=2))

    # =====================================================================================
    # mouse tools
    # =====================================================================================
    def _on_mode(self):
        self.drag = None
        mode = self.mode.get()
        self.hint.configure(text=MODE_HINT[mode])
        self.canvas.configure(cursor={"draw": "pencil", "erase": "circle", "box": "tcross"}
                              .get(mode, "crosshair"))
        self.root.focus_set()

    def _on_press(self, e):
        self.root.focus_set()
        wx, wy = self.s2w(e.x, e.y)
        mode = self.mode.get()
        shift = bool(e.state & 0x0001)
        if mode == "move":
            x, y, h = self._current_pose()
            if math.hypot(wx - x, wy - y) < ROBOT_GRAB_CM:
                self.drag = ("robot", wx - x, wy - y, h)
                return
            i = self._obstacle_at(wx, wy)
            if i is not None:
                x0, y0, _, _ = self.world.obstacles[i]
                self.drag = ("obstacle", i, wx - x0, wy - y0)
                self.obs_list.selection_clear(0, "end")
                self.obs_list.selection_set(i)
                self._draw_map()
                return
            if 0 <= wx <= self.world.width and 0 <= wy <= self.world.height:
                ux, uy = self.to_user(wx, wy)
                self._set_entry(self.obs_entries["x"], round(ux))
                self._set_entry(self.obs_entries["y"], round(uy))
                self._mark(wx, wy)
        elif mode == "draw":
            p = self._clamp_in(wx, wy)
            sx, sy = self.w2s(*p)
            item = self.canvas.create_line(sx, sy, sx, sy, fill="#3A3A3A",
                                           width=max(1, self.world.line_width * self.scale),
                                           capstyle="round", joinstyle="round")
            self.drag = ("draw", [p], item, shift)
        elif mode == "erase":
            i = self._obstacle_at(wx, wy)
            if i is not None:
                self._delete_obstacle(i)
                return
            self.drag = ("erase",)
            self._erase_at(wx, wy)
        elif mode == "box":
            p = self._snap_user(*self._clamp_in(wx, wy))
            sx, sy = self.w2s(*p)
            item = self.canvas.create_rectangle(sx, sy, sx, sy, fill=OBST_FILL, outline=OBST_EDGE,
                                                width=2, stipple="gray50")
            self.drag = ("box", p, item)

    def _on_drag(self, e):
        self._on_hover(e)
        if self.drag is None:
            return
        wx, wy = self.s2w(e.x, e.y)
        kind = self.drag[0]
        if kind == "robot":
            _, dx, dy, h = self.drag
            x, y = self._clamp_in(wx - dx, wy - dy)
            self._request_pose(x, y, h)
        elif kind == "obstacle":
            _, i, dx, dy = self.drag
            m = self.world
            x0, y0, x1, y1 = m.obstacles[i]
            w, h = x1 - x0, y1 - y0
            nx0 = min(max(wx - dx, 0.0), m.width - w)
            ny0 = min(max(wy - dy, 0.0), m.height - h)
            # snap the bottom-left corner to whole centimetres (user frame)
            ux, uy = self.to_user(nx0, ny0 + h)
            ux, uy = round(ux), round(uy)
            nx0, ny1 = self.from_user(ux, uy)
            nx0 = min(max(nx0, 0.0), m.width - w)
            ny1 = min(max(ny1, h), m.height)
            m.obstacles[i] = (nx0, ny1 - h, nx0 + w, ny1)
            self.coord_label.configure(text=f"Obstacle {i + 1}: x {ux:g}  y {uy:g}   {w:g} x {h:g} cm")
            self._world_changed()
        elif kind == "draw":
            _, pts, item, straight = self.drag
            p = self._clamp_in(wx, wy)
            if straight or (e.state & 0x0001 and len(pts) == 1):
                self.drag = ("draw", [pts[0], p], item, True)
                a, b = self.w2s(*pts[0]), self.w2s(*p)
                self.canvas.coords(item, *a, *b)
                L = math.hypot(p[0] - pts[0][0], p[1] - pts[0][1])
                self.coord_label.configure(text=f"Straight line {L:.1f} cm")
            elif math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) >= maps.POINT_SPACING_CM:
                pts.append(p)
                coords = []
                for q in pts:
                    coords.extend(self.w2s(*q))
                self.canvas.coords(item, *coords)
        elif kind == "erase":
            self._erase_at(wx, wy)
        elif kind == "box":
            _, p0, item = self.drag
            p1 = self._snap_user(*self._clamp_in(wx, wy))
            a, b = self.w2s(*p0), self.w2s(*p1)
            self.canvas.coords(item, *a, *b)
            self.coord_label.configure(text=f"Obstacle {abs(p1[0] - p0[0]):g} x {abs(p1[1] - p0[1]):g} cm")

    def _on_release(self, e):
        drag, self.drag = self.drag, None
        if drag is None:
            return
        kind = drag[0]
        if kind == "draw":
            _, pts, item, straight = drag
            self.canvas.delete(item)
            if len(pts) >= 2 and maps.stroke_length(pts) >= 1.0:
                stroke = maps.densify(pts if straight else _smooth(pts))
                self._add_stroke(stroke)
        elif kind == "box":
            _, p0, item = drag
            self.canvas.delete(item)
            p1 = self._snap_user(*self._clamp_in(*self.s2w(e.x, e.y)))
            box = (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))
            if box[2] - box[0] >= 1 and box[3] - box[1] >= 1:
                self._add_obstacle(box)
        elif kind == "erase":
            self._world_changed()
        elif kind == "obstacle":
            self._world_changed()

    def _snap_user(self, x, y):
        ux, uy = self.to_user(x, y)
        return self.from_user(round(ux), round(uy))

    def _on_right_click(self, e):
        wx, wy = self.s2w(e.x, e.y)
        i = self._obstacle_at(wx, wy)
        if i is not None:
            self._delete_obstacle(i)

    # --- line strokes ----------------------------------------------------------------------
    def _join_cm(self):
        """Snap distance for joining/closing lines: at least 3 cm or 40 screen pixels."""
        return max(JOIN_CM, 40.0 / max(self.scale, 0.1))

    def _add_stroke(self, stroke):
        lines = self.world.lines
        join = self._join_cm()
        # join to existing open line ends
        for _ in range(2):
            joined = False
            for j, other in enumerate(lines):
                if _is_closed(other):
                    continue
                a0, a1, b0, b1 = stroke[0], stroke[-1], other[0], other[-1]

                def near(p, q):
                    return math.hypot(p[0] - q[0], p[1] - q[1]) <= join

                if near(a0, b1):
                    stroke = other + maps.densify([b1, a0])[1:-1] + stroke
                elif near(a1, b0):
                    stroke = stroke + maps.densify([a1, b0])[1:-1] + other
                elif near(a0, b0):
                    stroke = list(reversed(other)) + maps.densify([b0, a0])[1:-1] + stroke
                elif near(a1, b1):
                    stroke = stroke + maps.densify([a1, b1])[1:-1] + list(reversed(other))
                else:
                    continue
                del lines[j]
                joined = True
                break
            if not joined:
                break
        # close the loop if the ends meet
        if (not _is_closed(stroke) and maps.stroke_length(stroke) > 20
                and math.hypot(stroke[0][0] - stroke[-1][0], stroke[0][1] - stroke[-1][1]) <= join):
            stroke = stroke + maps.densify([stroke[-1], stroke[0]])[1:]
        lines.append(stroke)
        self._world_changed()

    def _erase_at(self, wx, wy):
        r2 = ERASER_CM ** 2
        new_lines, changed = [], False
        for stroke in self.world.lines:
            xs = [p[0] for p in stroke]
            ys = [p[1] for p in stroke]
            if (wx < min(xs) - ERASER_CM or wx > max(xs) + ERASER_CM
                    or wy < min(ys) - ERASER_CM or wy > max(ys) + ERASER_CM):
                new_lines.append(stroke)
                continue
            keep = [(p[0] - wx) ** 2 + (p[1] - wy) ** 2 > r2 for p in stroke]
            if all(keep):
                new_lines.append(stroke)
                continue
            changed = True
            runs, cur = [], []
            for p, k in zip(stroke, keep):
                if k:
                    cur.append(p)
                elif cur:
                    runs.append(cur)
                    cur = []
            if cur:
                runs.append(cur)
            if _is_closed(stroke) and keep[0] and keep[-1] and len(runs) > 1:
                runs[0] = runs[-1] + runs[0][1:]
                runs.pop()
            new_lines.extend(run for run in runs if len(run) >= 2)
        if changed:
            self.world.lines = new_lines
            self._world_changed(save=False)

    # =====================================================================================
    # robot pose
    # =====================================================================================
    def _program_live(self):
        return (self.sh.get("owner_gen") > 0
                and time.time() - self.last_prog_change < STALE_S)

    def _current_pose(self):
        if self._preview_pose is not None:
            return self._preview_pose
        if self.sh.get("owner_gen") > 0:
            return tuple(self.sh.get("pose"))
        return tuple(self.world.start)

    def _request_pose(self, x, y, h):
        self.sh.set("pose_req", (x, y, h))
        self.sh.bump("pose_req_seq")
        self._preview_pose = (x, y, h)
        self._preview_t = time.time()

    def _reset_pose(self):
        self.sh.set("pose_req", (float("nan"), 0.0, 0.0))
        self.sh.bump("pose_req_seq")
        self._preview_pose = tuple(self.world.start)
        self._preview_t = time.time()

    def _rotate_ccw(self, deg):
        x, y, h = self._current_pose()
        self._request_pose(x, y, h - deg)

    @staticmethod
    def _step(e):
        return 1 if (getattr(e, "state", 0) & 0x0001) else 15

    # =====================================================================================
    # keyboard
    # =====================================================================================
    def _on_key_down(self, e):
        if self._typing():
            return
        k = (e.keysym or "").lower()
        if k in ("a", "b"):
            if k not in self.keys_down:
                self.keys_down.add(k)
                self._button(k, True)
        elif k in ("q", "e"):
            self._rotate_ccw(self._step(e) * (1 if k == "q" else -1))
        elif k in ("1", "2", "3", "4"):
            self.mode.set(MODES[int(k) - 1][0])
            self._on_mode()
        elif k in ("delete", "backspace"):
            sel = self.obs_list.curselection()
            if sel:
                self._delete_obstacle(sel[0])
        elif k == "escape":
            self.mode.set("move")
            self._on_mode()
            self._draw_map()

    def _on_key_up(self, e):
        k = (e.keysym or "").lower()
        if k in ("a", "b") and k in self.keys_down:
            self.keys_down.discard(k)
            self._button(k, False)

    def _on_close(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
            self._autosave()
        self.sh.set("gui_closing", 1)
        self.root.after(250, self.root.destroy)

    # =====================================================================================
    # Motors tab: simulated motor mismatch, path trail and straightness read-out
    # =====================================================================================
    def _build_motor_tab(self):
        f = self._tab("Motors")
        tk.Label(f, text="Motor strength, % (simulation only - your code\n"
                         "is not changed). 100 = exact; 92 = 8 % slower.",
                 bg=PANEL_BG, fg=MUTED, anchor="w", justify="left").pack(fill="x", padx=6, pady=(8, 0))
        grid = tk.Frame(f, bg=PANEL_BG)
        grid.pack(fill="x", padx=2)
        self.gain_entries = {}
        self._field(grid, "left %", 0, 0, self.gain_entries, "l")
        self._field(grid, "right %", 0, 2, self.gain_entries, "r")
        self._btn(grid, "Apply", self._apply_gain).grid(row=0, column=4, padx=(8, 0))
        for e in self.gain_entries.values():
            e.bind("<Return>", lambda _e: self._apply_gain())
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(4, 2))
        self._btn(row, "Exact (100/100)", self._reset_gain).pack(side="left")
        self._btn(row, "Random hidden", self._random_gain).pack(side="left", padx=4)
        self._btn(row, "Reveal", self._reveal_gain).pack(side="left")
        self.gain_msg = tk.Label(f, text="", bg=PANEL_BG, fg=MUTED, anchor="w", justify="left",
                                 wraplength=PANEL_W - 40)
        self.gain_msg.pack(fill="x", padx=6, pady=(2, 6))

        tk.Frame(f, bg="#3A424D", height=1).pack(fill="x", padx=6, pady=4)
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6)
        self.show_trail = tk.BooleanVar(value=True)
        tk.Checkbutton(row, text="Show path trail", variable=self.show_trail,
                       command=lambda: self._draw_trail(full=True), bg=PANEL_BG, fg=TEXT,
                       selectcolor=FIELD_BG, activebackground=PANEL_BG,
                       activeforeground=TEXT).pack(side="left")
        self._btn(row, "Clear trail / restart measure", self._clear_trail).pack(side="left", padx=6)
        self.drift_label = tk.Label(f, text="", bg=PANEL_BG, fg=TEXT, font=("Consolas", 10),
                                    anchor="w", justify="left")
        self.drift_label.pack(fill="x", padx=6, pady=(6, 2))
        self._show_gain()

    def _show_gain(self):
        if self.gain_hidden:
            for e in self.gain_entries.values():
                self._set_entry(e, "?")
            self.gain_msg.configure(text="A hidden mismatch is active. Make the robot drive "
                                         "straight by changing the speeds in your code.", fg=ACCENT)
        else:
            self._set_entry(self.gain_entries["l"], f"{self.motor_gain[0] * 100:g}")
            self._set_entry(self.gain_entries["r"], f"{self.motor_gain[1] * 100:g}")
            if self.motor_gain == [1.0, 1.0]:
                self.gain_msg.configure(text="Motors are exact (no mismatch).", fg=MUTED)
            else:
                self.gain_msg.configure(
                    text=f"Code speed 25 gives left {25 * self.motor_gain[0]:.1f}, "
                         f"right {25 * self.motor_gain[1]:.1f}", fg=OK)

    def _publish_gain(self):
        self.sh.set("motor_gain", self.motor_gain)

    def _apply_gain(self):
        try:
            l = self._num(self.gain_entries["l"], "left %")
            r = self._num(self.gain_entries["r"], "right %")
        except ValueError as e:
            self.gain_msg.configure(text=str(e) + " (or press Reveal first)", fg=ERR)
            return
        if not (50 <= l <= 150 and 50 <= r <= 150):
            self.gain_msg.configure(text="Use values between 50 and 150 %", fg=ERR)
            return
        self.motor_gain = [l / 100.0, r / 100.0]
        self.gain_hidden = False
        self._gain_changed()
        self.root.focus_set()

    def _reset_gain(self):
        self.motor_gain = [1.0, 1.0]
        self.gain_hidden = False
        self._gain_changed()

    def _random_gain(self):
        weak = random.choice((0, 1))
        g = [1.0, 1.0]
        g[weak] = round(random.uniform(0.85, 0.97), 3)
        self.motor_gain = g
        self.gain_hidden = True
        self._gain_changed()

    def _reveal_gain(self):
        self.gain_hidden = False
        self._show_gain()
        self._schedule_save()

    def _gain_changed(self):
        self._publish_gain()
        self._show_gain()
        self._clear_trail()
        self._schedule_save()

    def _schedule_save(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(700, self._autosave)

    # --- settings stored with layouts ----------------------------------------------------
    def _layout_with_settings(self):
        d = self.world.to_layout()
        d["simulator"] = {"motor_strength_percent": [round(self.motor_gain[0] * 100, 2),
                                                     round(self.motor_gain[1] * 100, 2)],
                          "mismatch_hidden": self.gain_hidden}
        return d

    def _apply_sim_settings(self, sim):
        try:
            l, r = (float(v) for v in sim.get("motor_strength_percent", [100, 100]))
            if 50 <= l <= 150 and 50 <= r <= 150:
                self.motor_gain = [l / 100.0, r / 100.0]
            self.gain_hidden = bool(sim.get("mismatch_hidden", False))
        except (TypeError, ValueError):
            return
        if hasattr(self, "gain_entries"):
            self._publish_gain()
            self._show_gain()

    def _load_sim_settings(self):
        try:
            with open(AUTOSAVE_FILE, encoding="utf-8") as fh:
                sim = json.load(fh).get("simulator")
        except (OSError, ValueError, AttributeError):
            return
        if isinstance(sim, dict):
            self._apply_sim_settings(sim)

    # --- path trail and straightness ------------------------------------------------------
    def _clear_trail(self):
        self.trail = []
        self._run_start = None
        self._draw_trail(full=True)

    def _update_trail(self, has_prog, live, pose, motors=(0.0, 0.0)):
        gen = self.sh.get("owner_gen")
        if gen != self._run_gen:                 # a new program run starts a new trail
            self._run_gen = gen
            self.trail = []
            self._run_start = None
            self._draw_trail(full=True)
        if not (has_prog and live) or self._preview_pose is not None or self.drag is not None:
            if self.trail and self.trail[-1]:
                self.trail.append([])            # break the line when the robot is moved by hand
            self._run_start = None if self._preview_pose is not None else self._run_start
        else:
            x, y = pose[0], pose[1]
            if self._run_start is None:
                self._run_start = tuple(pose)
                self._run_last = tuple(pose)
                self._run_dist = 0.0         # signed distance driven along the heading (cm)
                self._run_turn = 0.0         # heading change, degrees, + = clockwise on screen
                self._run_cmds = set()
            lx, ly, lh = self._run_last
            hm = math.radians((lh + pose[2]) / 2.0 if abs(_wrap(pose[2] - lh)) < 90 else lh)
            self._run_dist += (x - lx) * math.cos(hm) + (y - ly) * math.sin(hm)
            self._run_turn += _wrap(pose[2] - lh)
            self._run_last = tuple(pose)
            if any(abs(m) > 0 for m in motors):
                self._run_cmds.add((int(round(motors[0])), int(round(motors[1]))))
            if not self.trail:
                self.trail.append([])
            seg = self.trail[-1]
            if not seg or math.hypot(x - seg[-1][0], y - seg[-1][1]) >= 0.4:
                seg.append((x, y))
                if len(seg) > 6000:
                    del seg[:1000]
                self._draw_trail()
        self._update_drift(pose)

    def _draw_trail(self, full=False):
        c = self.canvas
        if full:
            for it in self._trail_items:
                c.delete(it)
            self._trail_items = []
        if self.show_trail is None or not self.show_trail.get():
            for it in self._trail_items:
                c.delete(it)
            self._trail_items = []
            return
        segs = [sg for sg in self.trail if len(sg) >= 2]
        while len(self._trail_items) < len(segs):
            self._trail_items.append(c.create_line(0, 0, 0, 0, fill="#E5534B", width=2,
                                                   capstyle="round", joinstyle="round"))
        for item, sg in zip(self._trail_items, segs):
            pts = []
            for px, py in sg:
                pts.extend(self.w2s(px, py))
            c.coords(item, *pts)
        if self._robot_items:
            for it in self._robot_items.values():
                for x in (it if isinstance(it, list) else [it]):
                    c.tag_raise(x)

    def _update_drift(self, pose):
        st = self._run_start
        if st is None:
            self.drift_label.configure(text="Straightness: run a program to measure.")
            return
        h0 = math.radians(st[2])
        dx, dy = pose[0] - st[0], pose[1] - st[1]
        fwd = dx * math.cos(h0) + dy * math.sin(h0)
        side = -dx * math.sin(h0) + dy * math.cos(h0)    # internal frame: + = to the right
        turn = _wrap(-(pose[2] - st[2]))                  # user frame: + = turned left
        drift = "left" if side < 0 else "right"
        self.drift_label.configure(text=(
            f"Since start of run:\n"
            f"  forward  {fwd:6.1f} cm\n"
            f"  sideways {abs(side):6.1f} cm to the {drift}\n"
            f"  turned   {turn:+6.1f}\u00b0  (+ = left)\n\n" + self._correction_hint()))

    def _correction_hint(self):
        """Suggest wheel speeds that would drive straight, worked out only from the
        measured run (distance and turn), as you would do with a real robot."""
        cmds = getattr(self, "_run_cmds", set())
        if not cmds:
            return "Correction: drive with one constant speed\n(e.g. motors(25, 25)) to get a hint."
        if len(cmds) > 1:
            return "Correction: the speeds changed during the run.\nFor a hint, drive with one constant speed."
        lc, rc = next(iter(cmds))
        if lc == 0 or rc == 0 or (lc > 0) != (rc > 0):
            return "Correction: both wheels must drive the same\nway (e.g. motors(25, 25))."
        s = self._run_dist
        if abs(s) < 10:
            return "Correction: drive at least 10 cm for a hint."
        theta = math.radians(self._run_turn)                 # + = turned right on screen
        sl = s + theta * R.WHEEL_TRACK_CM / 2.0               # distance each wheel travelled
        sr = s - theta * R.WHEEL_TRACK_CM / 2.0
        if sl * sr <= 0:
            return "Correction: the robot spun too much to estimate."
        if abs(self._run_turn) < 0.5:
            return f"Correction: none needed - motors({lc}, {rc})\ndrives straight."
        # wheel speed = command x strength, so strength ratio = (sl/lc) / (sr/rc)
        new_r = sl * rc / sr          # right command that matches the left wheel
        new_l = sr * lc / sl          # or: left command that matches the right wheel
        options = []
        if abs(new_r) <= 100:
            options.append(f"motors({lc}, {int(round(new_r))})   right {rc} -> {new_r:.1f}")
        if abs(new_l) <= 100:
            options.append(f"motors({int(round(new_l))}, {rc})   left {lc} -> {new_l:.1f}")
        weak = "right" if abs(sl) > abs(sr) else "left"
        ratio = min(abs(sl), abs(sr)) / max(abs(sl), abs(sr)) * 100
        return (f"Correction: {weak} wheel is ~{ratio:.0f} % of the other.\n"
                f"To go straight try:\n  " + "\n  ".join(options))

    # =====================================================================================
    # frame loop
    # =====================================================================================
    def _tick(self):
        try:
            self._frame()
        finally:
            self.root.after(FRAME_MS, self._tick)

    def _frame(self):
        sh = self.sh
        sh.bump("gui_tick")
        now = time.time()
        has_prog = sh.get("owner_gen") > 0

        tick = sh.get("prog_tick")
        if tick != self.last_prog_tick:
            self.last_prog_tick = tick
            self.last_prog_change = now
        live = has_prog and now - self.last_prog_change < STALE_S

        # A pose set by the user is shown until the program has applied it.
        if live and self._preview_pose is not None and self.drag is None:
            px, py, ph = sh.get("pose")
            qx, qy, qh = self._preview_pose
            applied = abs(px - qx) < 0.05 and abs(py - qy) < 0.05 and abs(_wrap(ph - qh)) < 0.1
            if applied or now - self._preview_t > 0.4:
                self._preview_pose = None
        if self._preview_pose is not None:
            pose = self._preview_pose
        elif has_prog:
            pose = tuple(sh.get("pose"))
        else:
            pose = tuple(self.world.start)

        motors = sh.get("motors") if has_prog else [0.0, 0.0]
        line = sh.get("line") if has_prog else [1, 1]
        self._update_robot(pose, sh.get("lights"), sh.get("neopixels"), line,
                           sh.get("sonar_cm"), sh.get("sonar_active") and has_prog)

        for i, v in enumerate(sh.get("display")):
            col = LED_OFF if v == 0 else _rgb(*_mix((255, 40, 30), (58, 20, 20), 0.25 + 0.75 * v / 9))
            self.board.itemconfigure(self.leds[i], fill=col)

        name = sh.get("prog_name")
        state = sh.get("prog_state")
        if not has_prog:
            text, colour = "Waiting for a program...\nRun a .py file that imports microbit.", MUTED
        elif state == shared.STATE_RUNNING and live:
            text, colour = f"Running  {name}", OK
        elif state == shared.STATE_RUNNING:
            text, colour = (f"Paused or stopped  {name}\n(breakpoint in the debugger, "
                            "or Stop was pressed)"), "#D29922"
        elif state == shared.STATE_FINISHED:
            extra = "  - motors still on" if live and any(abs(m) > 0 for m in motors) else ""
            text, colour = f"Finished  {name}{extra}", ACCENT
        else:
            text, colour = f"Error in  {name}", ERR
        self.status.configure(text=text, fg=colour)
        self.message.configure(text=sh.get("message") if state == shared.STATE_ERROR else "")

        self._update_trail(has_prog, live, pose, motors)
        g = self.motor_gain
        actual = ""
        if (g[0] != 1.0 or g[1] != 1.0) and not self.gain_hidden and any(motors):
            actual = f"\n  actual   L {motors[0] * g[0]:+5.1f} %   R {motors[1] * g[1]:+5.1f} %"
        x, y = self.to_user(pose[0], pose[1])
        a = _wrap(-pose[2])
        sonar = f"{sh.get('sonar_cm'):5.1f} cm" if sh.get("sonar_active") and has_prog else "  (not used)"
        self.readout.configure(text=(
            f"Motors     L {motors[0]:+5.0f} %   R {motors[1]:+5.0f} %{actual}\n"
            f"Line       L {line[0]}   R {line[1]}   (0 = black)\n"
            f"Sonar     {sonar}\n"
            f"Position   x {x:5.1f}  y {y:5.1f} cm\n"
            f"Angle      {a:6.1f}°  (0 = right, 90 = up)"))
        if not self._typing():
            self._set_entry(self.pose_entries["x"], f"{x:.1f}")
            self._set_entry(self.pose_entries["y"], f"{y:.1f}")
            self._set_entry(self.pose_entries["a"], f"{a:.0f}")
            if not hasattr(self, "_arena_filled"):
                self._arena_filled = True
                self._fill_arena_fields()


def main():
    existing = shared.Shared.attach()
    if existing is not None:
        # Another window may already be open: if it is alive, just leave.
        from .runtime import _pid_alive

        t1 = existing.get("gui_tick")
        time.sleep(0.5)
        if (_pid_alive(existing.get("gui_pid")) and existing.get("gui_tick") != t1
                and not existing.get("gui_closing")):
            existing.close()
            return
        existing.close()
    sh = shared.Shared.create()
    sh.set("gui_pid", os.getpid())
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "clam" in style.theme_names() and sys.platform != "win32":
            style.theme_use("clam")
    except tk.TclError:
        pass
    SimWindow(root, sh)
    try:
        root.mainloop()
    finally:
        sh.set("gui_closing", 1)
        time.sleep(0.1)
        shm = sh.shm
        sh.close()
        try:
            shm.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    main()
