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

from . import maps, panels, race as race_mod, reference, robot as R, sensors, shared

FRAME_MS = 16
SLIDER_MIN, SLIDER_MAX = 50.0, 150.0     # motor strength sliders (type 0-200 in the box)
PANEL_W = 372
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

TREAD_MARKS = 4          # tread lines drawn on each wheel
ERASER_CM = 2.5          # eraser radius
JOIN_CM = 3.0            # a new stroke joins an existing line end closer than this
ROBOT_GRAB_CM = 6.0

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTOSAVE_FILE = os.path.join(PROJECT_DIR, "sim_layout.json")
LAYOUT_DIR = os.path.join(PROJECT_DIR, "layouts")

MODES = [("move", "Move", "1"), ("draw", "Draw line", "2"), ("erase", "Erase", "3"),
         ("box", "Draw obstacle", "4"), ("measure", "Measure", "5")]
MODE_HINT = {
    "move": "Drag the robot or an obstacle; drag an edge/corner to resize.  "
            "Ctrl+C / Ctrl+V copy-paste, Ctrl+D duplicate, Delete removes.",
    "draw": "Drag to draw a line.  Hold Shift for a straight line.  Ends join automatically.",
    "erase": "Drag over a line to erase it.  Click an obstacle to delete it.",
    "box": "Drag a rectangle to create an obstacle.",
    "measure": "Drag to measure.  Snaps to walls, obstacle edges/corners, robot centre.  "
               "Shift = straight.  Esc clears.",
    "zone": "Drag a rectangle for the zone.  Right-click a zone to delete it.  Esc = done.",
}
HELP = ("Keys 1-5 tools   Q/E, wheel: rotate 15° (Shift 1°)   R: RESET\n"
        "A/B micro:bit buttons   Delete, right-click: delete obstacle\n"
        "Ctrl+C / V copy-paste   Ctrl+X cut   Ctrl+D duplicate   F1 help")


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
        self._saved_realism = (False, R.DEFAULT_DEAD_ZONE)
        self._saved_race = None
        self._saved_mounted = True
        self._allow_world = False
        self.trail = []                  # list of segments, each a list of (x, y) internal
        self._trail_items = []
        self.show_trail = None           # tk.BooleanVar, created with the Motors tab
        self._run_gen = None
        self._run_start = None           # pose where the straightness measurement starts
        self.measure_pts = None          # (p0, p1) of the measure tool, internal frame
        self.clipboard = None            # (width, height) of a copied obstacle
        self._paste_from = None          # where the last copy/paste was (internal frame box)
        self._mouse_w = None             # mouse position over the arena (internal frame)
        self._gain_updating = False
        self._load_sim_settings()

        root.title("Cutebot simulator - LSBU")
        root.configure(bg=BG)
        root.geometry("1200x780")
        root.minsize(900, 600)

        # --- left: toolbar + canvas ---------------------------------------------------
        left = tk.Frame(root, bg=BG)
        bar = tk.Frame(left, bg=BG)
        bar.pack(fill="x", padx=10, pady=(8, 0))
        self.mode = tk.StringVar(value="move")
        for key, label, num in MODES:
            tk.Radiobutton(bar, text=f"{num}  {label}", value=key, variable=self.mode,
                           indicatoron=0, command=self._on_mode, bg="#2D333B", fg=TEXT,
                           selectcolor="#1F6FEB", activebackground="#3A424D",
                           activeforeground=TEXT, relief="flat", padx=10, pady=4,
                           bd=0, highlightthickness=0).pack(side="left", padx=(0, 4))
        for text, cmd in (("? Help", self.open_help), ("Radio", self.open_radio),
                          ("Graphs", self.open_graphs), ("Code", self.open_code)):
            tk.Button(bar, text=text, command=cmd, bg="#2D333B", fg=TEXT,
                      activebackground="#3A424D", activeforeground=TEXT, relief="flat", padx=9,
                      pady=4, bd=0, highlightthickness=0).pack(side="right", padx=(4, 0))
        row2 = tk.Frame(left, bg=BG)
        row2.pack(fill="x", padx=12, pady=(4, 0))
        self.coord_label = tk.Label(row2, text="", bg=BG, fg=TEXT, font=("Consolas", 10, "bold"))
        self.coord_label.pack(side="right")
        self.hint = tk.Label(row2, text=MODE_HINT["move"], bg=BG, fg=MUTED, anchor="w",
                             font=("Segoe UI", 9), width=1)
        self.hint.pack(side="left", fill="x", expand=True)

        # simulation controls: pause, step, slow motion, pause when ...
        ctl = tk.Frame(left, bg=BG)
        ctl.pack(fill="x", padx=10, pady=(4, 0))
        self.pause_btn = tk.Button(ctl, text="Pause (Space)", width=13, command=self.toggle_pause,
                                   bg="#2D333B", fg=TEXT, activebackground="#3A424D",
                                   activeforeground=TEXT, relief="flat", bd=0, pady=3)
        self.pause_btn.pack(side="left")
        self.step_btn = tk.Button(ctl, text="Step (N)", command=self.step, bg="#2D333B", fg=TEXT,
                                  activebackground="#3A424D", activeforeground=TEXT, relief="flat",
                                  bd=0, padx=8, pady=3)
        self.step_btn.pack(side="left", padx=(4, 10))
        tk.Label(ctl, text="Speed", bg=BG, fg=MUTED).pack(side="left")
        self.speed_var = tk.DoubleVar(value=1.0)
        for value, text in ((0.1, "0.1x"), (0.25, "0.25x"), (0.5, "0.5x"), (1.0, "1x"), (2.0, "2x"),
                            (4.0, "4x")):
            tk.Radiobutton(ctl, text=text, value=value, variable=self.speed_var, indicatoron=0,
                           command=self._sim_ui_changed, bg="#2D333B", fg=TEXT,
                           selectcolor="#1F6FEB", activebackground="#3A424D", activeforeground=TEXT,
                           relief="flat", bd=0, padx=7, pady=3).pack(side="left", padx=1)
        self.pause_on_btn = tk.Menubutton(ctl, text="Pause on \u25be", bg="#2D333B", fg=TEXT,
                                          activebackground="#3A424D", activeforeground=TEXT,
                                          relief="flat", bd=0, padx=8, pady=3)
        self.pause_on_btn.pack(side="left", padx=(10, 0))
        menu = tk.Menu(self.pause_on_btn, tearoff=0)
        self.pause_on_btn.configure(menu=menu)
        self.pause_on_vars = []
        for bit, text in ((1, "motor speeds change"), (2, "a line sensor changes"),
                          (4, "the robot bumps into something")):
            v = tk.BooleanVar(value=False)
            menu.add_checkbutton(label=text, variable=v, command=self._sim_ui_changed)
            self.pause_on_vars.append((bit, v))
        self.paused = False
        self.pause_reason = ""
        self._auto_seen = 0

        self.canvas = tk.Canvas(left, bg=BG, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        # --- right: micro:bit + readouts + tabs ------------------------------------------
        panel = tk.Frame(root, bg=PANEL_BG, width=PANEL_W)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)
        left.pack(side="left", fill="both", expand=True)     # after the panel: panel keeps its width

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
        self._build_sensor_tab()
        self.race = race_mod.Race(self, self._tab("Race"))
        self.race.load_settings(self._saved_race)

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
        root.bind("<F1>", lambda e: self.open_help())
        self._help = None
        self._code_win = self._graph_win = self._radio_win = None
        self._tx_pos = 0
        self.radio_log = []              # recent radio messages for the console
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._world_changed(save=False)
        self._publish_gain()
        self._publish_realism()
        self._publish_sensors()
        self._publish_sim_controls()
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
        # RESET button (top right of the board): restarts the running program
        rx0, ry0, rx1, ry1 = w - 62, 9, w - 12, 29
        self.reset_btn = b.create_rectangle(rx0, ry0, rx1, ry1, fill="#3A2A2A", outline="#8B4A4A",
                                            width=1)
        reset_txt = b.create_text((rx0 + rx1) / 2, (ry0 + ry1) / 2, text="RESET", fill="#F2B8B5",
                                  font=("Segoe UI", 8, "bold"))
        for item in (self.reset_btn, reset_txt):
            b.tag_bind(item, "<ButtonPress-1>", lambda e: self._press_reset(True))
            b.tag_bind(item, "<ButtonRelease-1>", lambda e: self._press_reset(False))
            b.tag_bind(item, "<Enter>", lambda e: b.configure(cursor="hand2"))
            b.tag_bind(item, "<Leave>", lambda e: b.configure(cursor=""))
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

    def _press_reset(self, down):
        """RESET restarts the program (like the micro:bit's reset button)."""
        self.board.itemconfigure(self.reset_btn, fill="#6B2E2E" if down else "#3A2A2A")
        if down:
            if self.sh.get("owner_gen") == 0:
                return
            self.sh.bump("reset_req")

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
        """A tab whose content scrolls when it does not fit (large fonts, small screens)."""
        outer = tk.Frame(self.tabs, bg=PANEL_BG)
        self.tabs.add(outer, text=f" {title} ")
        canvas = tk.Canvas(outer, bg=PANEL_BG, highlightthickness=0, bd=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=PANEL_BG)
        win = canvas.create_window(0, 0, window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)

        def fit(_e=None):
            canvas.itemconfigure(win, width=canvas.winfo_width())
            h = inner.winfo_reqheight()
            canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), h))
            need = h > canvas.winfo_height() + 1
            if need and not sb.winfo_ismapped():
                sb.pack(side="right", fill="y", before=canvas)
            elif not need and sb.winfo_ismapped():
                sb.pack_forget()
                canvas.yview_moveto(0)

        def wheel(e):
            if not sb.winfo_ismapped():
                return
            up = getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4
            canvas.yview_scroll(-2 if up else 2, "units")

        def enter(_e):
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.root.bind_all(ev, wheel)

        def leave(_e):
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.root.unbind_all(ev)

        inner.bind("<Configure>", fit)
        canvas.bind("<Configure>", fit)
        outer.bind("<Enter>", enter)
        outer.bind("<Leave>", leave)
        return inner

    def _typing(self):
        try:
            w = self.root.focus_get()
        except (KeyError, tk.TclError):
            return False
        return isinstance(w, (tk.Entry, ttk.Entry, tk.Spinbox))

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
        self._btn(grid, "Add new", self._add_obstacle_from_fields).grid(row=0, column=4, sticky="we",
                                                                        padx=(8, 0), pady=2)
        self._btn(grid, "Update selected", self._update_selected).grid(row=1, column=4, sticky="we",
                                                                       padx=(8, 0), pady=2)
        for e in self.obs_entries.values():
            e.bind("<Return>", lambda _e: self._add_obstacle_from_fields())

        self.obs_list = tk.Listbox(f, height=6, bg=FIELD_BG, fg=TEXT, relief="flat",
                                   selectbackground="#40505F", font=("Consolas", 9),
                                   activestyle="none", exportselection=False)
        self.obs_list.pack(fill="both", expand=True, padx=6, pady=(4, 2))
        self.obs_list.bind("<<ListboxSelect>>", lambda e: self._on_obs_select())
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=2)
        self._btn(row, "Delete selected", self._remove_selected).pack(side="left")
        self._btn(row, "Clear all", self._clear_obstacles).pack(side="left", padx=6)
        self.obs_msg = tk.Label(f, text="Tool 4 draws an obstacle. Tool 1 moves it, or drag\n"
                                        "its edge/corner to resize. Green lines = gaps (cm).",
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

    def _on_obs_select(self, redraw=True):
        """Show the selected obstacle's corner and size in the fields."""
        sel = self.obs_list.curselection()
        if sel and sel[0] < len(self.world.obstacles):
            x0, y0, x1, y1 = self.world.obstacles[sel[0]]
            ux, uy = self.to_user(x0, y1)
            for k, v in (("x", ux), ("y", uy), ("w", x1 - x0), ("h", y1 - y0)):
                self._set_entry(self.obs_entries[k], self._fmt_cm(v))
        if redraw:
            self._draw_map()

    def _update_selected(self):
        sel = self.obs_list.curselection()
        if not sel:
            self.obs_msg.configure(text="Select an obstacle first (in the list or on the arena)",
                                   fg=ERR)
            return
        try:
            ux = self._num(self.obs_entries["x"], "x")
            uy = self._num(self.obs_entries["y"], "y")
            w = self._num(self.obs_entries["w"], "width")
            h = self._num(self.obs_entries["h"], "height")
        except ValueError as e:
            self.obs_msg.configure(text=str(e), fg=ERR)
            return
        m = self.world
        if w < 0.5 or h < 0.5:
            self.obs_msg.configure(text="Width and height must be at least 0.5 cm", fg=ERR)
            return
        x0, y1 = self.from_user(ux, uy)
        box = (max(0.0, x0), max(0.0, y1 - h), min(m.width, x0 + w), min(m.height, y1))
        if box[2] - box[0] < 0.5 or box[3] - box[1] < 0.5:
            self.obs_msg.configure(text="That obstacle is outside the arena", fg=ERR)
            return
        i = sel[0]
        m.obstacles[i] = box
        self.obs_msg.configure(text=f"Updated obstacle {i + 1}: "
                                    f"{box[2] - box[0]:g} x {box[3] - box[1]:g} cm", fg=OK)
        self._world_changed()
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
        m.zones = [(k, x0, max(0.0, y0 + dh), min(x1, w), min(y1 + dh, h))
                   for k, x0, y0, x1, y1 in m.zones]
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
        r = getattr(self, "race", None)
        if r is not None and r.locked() and not self._allow_world:
            cw = r.course_world()                 # the teacher's course cannot be edited
            if cw is not None:
                cw.start = self.world.start
                self.world = cw
                self.coord_label.configure(text="The course is set by the teacher")
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
        # grid: fine lines every 1 cm (5 cm if the arena is too big to see them),
        # strong lines every 10 cm, numbers along the edges
        minor = 1 if s >= 3 else 5 if s * 5 >= 5 else 0
        major = 10
        if minor:
            for gx in range(minor, int(m.width) + 1, minor):
                if gx < m.width and gx % major:
                    sx, _ = self.w2s(gx, 0)
                    c.create_line(sx, y0, sx, y1, fill="#DADDD8" if gx % 5 else "#CDD1CB")
            for gy in range(minor, int(m.height) + 1, minor):
                if gy < m.height and gy % major:
                    _, sy = self.w2s(0, m.height - gy)
                    c.create_line(x0, sy, x1, sy, fill="#DADDD8" if gy % 5 else "#CDD1CB")
        label_every = next(n for n in (10, 20, 50, 100, 200) if n * s >= 28)
        for gx in range(major, int(m.width) + 1, major):
            sx, _ = self.w2s(gx, 0)
            if gx < m.width:
                c.create_line(sx, y0, sx, y1, fill="#AEB4AC")
            if gx % label_every == 0:
                c.create_text(sx, y0 - 8, text=str(gx), fill=MUTED, font=("Segoe UI", 7), anchor="s")
        for gy in range(major, int(m.height) + 1, major):
            _, sy = self.w2s(0, m.height - gy)
            if gy < m.height:
                c.create_line(x0, sy, x1, sy, fill="#AEB4AC")
            if gy % label_every == 0:
                c.create_text(x0 - 8, sy, text=str(gy), fill=MUTED, font=("Segoe UI", 7), anchor="e")
        step = minor or major
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
        # axes at the origin (bottom-left)
        c.create_line(x0, y1, x0 + 34, y1, fill="#C0392B", width=2, arrow="last")
        c.create_line(x0, y1, x0, y1 - 34, fill="#27AE60", width=2, arrow="last")
        c.create_text(x0 + 40, y1 - 2, text="x", fill="#C0392B", anchor="w",
                      font=("Segoe UI", 9, "bold"))
        c.create_text(x0 + 4, y1 - 42, text="y", fill="#27AE60", anchor="w",
                      font=("Segoe UI", 9, "bold"))
        c.create_text(x0, y1 + 16, anchor="w", fill=MUTED, font=("Segoe UI", 9),
                      text=f"{m.width:g} x {m.height:g} cm   small squares {step} cm, "
                           f"bold lines every {major} cm   origin bottom-left")
        if hasattr(self, "race"):
            self.race.draw_zones(c)
        if sel and sel[0] < len(m.obstacles):
            self._draw_gaps(sel[0])
        self._draw_measure()
        self._trail_items = []
        self._draw_trail(full=True)
        if hasattr(self, "race"):
            self.race.after_redraw()

    def _make_robot_items(self):
        c = self.canvas
        it = {}
        it["ray"] = c.create_line(0, 0, 0, 0, fill=ACCENT, dash=(4, 3), width=1, state="hidden")
        it["ray_txt"] = c.create_text(0, 0, text="", fill="#1C5F8F", font=("Segoe UI", 9, "bold"),
                                      state="hidden")
        it["neo"] = [c.create_oval(0, 0, 0, 0, fill="", outline="") for _ in range(2)]
        it["wheels"] = [c.create_polygon(0, 0, 0, 0, fill="#151515", outline="") for _ in range(2)]
        # tread marks that scroll at each wheel's real speed
        it["treads"] = [[c.create_line(0, 0, 0, 0, fill="#6B7280", width=2) for _ in range(TREAD_MARKS)]
                        for _ in range(2)]
        it["body"] = c.create_polygon(0, 0, 0, 0, fill="#2A2E33", outline="#0E0F10", width=2)
        it["board"] = c.create_polygon(0, 0, 0, 0, fill="#1B1E22", outline="#55606A")
        it["lights"] = [c.create_oval(0, 0, 0, 0, fill="#555", outline="#111") for _ in range(2)]
        it["sensors"] = [c.create_oval(0, 0, 0, 0, fill="#999", outline="#111") for _ in range(2)]
        it["sonar"] = c.create_polygon(0, 0, 0, 0, fill="#C9CED3", outline="#555")
        self._robot_items = it

    def _update_robot(self, pose, lights, neo, line, sonar_cm, sonar_active, tread=(0.0, 0.0)):
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
        r_wheel = R.WHEEL_DIAMETER_CM / 2.0
        spacing = 2 * r_wheel / TREAD_MARKS
        for i in range(2):
            c.coords(it["wheels"][i], *poly(shape["wheels"][i]))
            inner, outer = shape["wheels"][i][0][1], shape["wheels"][i][2][1]
            for k, line_item in enumerate(it["treads"][i]):
                a = -r_wheel + (k * spacing + tread[i]) % (2 * r_wheel)
                c.coords(line_item, *P(a, inner), *P(a, outer))
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
        for item in (it["ray"], it["ray_txt"], *it["neo"], *it["wheels"], *it["treads"][0],
                     *it["treads"][1], it["body"], it["board"],
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
            self._mouse_w = None
            self._hide_hover()
            return
        self._mouse_w = (wx, wy)
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
            handle = self._resize_handle(e.x, e.y)
            if handle and math.hypot(wx - x, wy - y) >= ROBOT_GRAB_CM:
                c.configure(cursor=self.RESIZE_CURSOR[handle[1]])
            else:
                grab = (math.hypot(wx - x, wy - y) < ROBOT_GRAB_CM
                        or self._obstacle_at(wx, wy) is not None)
                c.configure(cursor="fleur" if grab else "crosshair")

    def _hide_hover(self):
        self._mouse_w = None
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
    # measuring: measure tool, gaps around the selected obstacle, resize handles
    # =====================================================================================
    @staticmethod
    def _fmt_cm(v):
        t = f"{v:.1f}"
        return t[:-2] if t.endswith(".0") else t

    def _label(self, sx, sy, text, fg="#0B4F8A", tag="measure", side=None):
        """A small white label.  ``side`` = (nx, ny): place it beside the point in that
        direction (so it does not cover a line) instead of centred on it."""
        c = self.canvas
        t = c.create_text(sx, sy, text=text, fill=fg, font=("Segoe UI", 8, "bold"), tags=tag)
        bx = c.bbox(t)
        if bx and side is not None:
            nx, ny = side
            w, h = bx[2] - bx[0], bx[3] - bx[1]
            d = 5 + abs(nx) * w / 2 + abs(ny) * h / 2       # clear of the line
            c.move(t, nx * d, ny * d)
            bx = c.bbox(t)
        if bx:
            r = c.create_rectangle(bx[0] - 3, bx[1] - 1, bx[2] + 3, bx[3] + 1, fill="#FFFFFF",
                                   outline="#8FB8DE", tags=tag)
            c.tag_lower(r, t)

    def _dim_line(self, p, q, text, colour="#1F6FEB", tag="measure", dash=(4, 2)):
        a, b = self.w2s(*p), self.w2s(*q)
        self.canvas.create_line(*a, *b, fill=colour, width=2, arrow="both", arrowshape=(7, 8, 3),
                                dash=dash, tags=tag)
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length                     # perpendicular to the line
        if ny > 0.01 or (abs(ny) <= 0.01 and nx < 0):
            nx, ny = -nx, -ny                                  # above the line, or to its right
        self._label((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, text, tag=tag, side=(nx, ny))

    def _draw_gaps(self, i):
        """Distances from each side of obstacle ``i`` to the nearest wall or obstacle."""
        m = self.world
        x0, y0, x1, y1 = m.obstacles[i]
        others = [o for j, o in enumerate(m.obstacles) if j != i]

        def overlap(a0, a1, b0, b1):
            return min(a1, b1) - max(a0, b0) > 1e-6

        def mid(a0, a1, b0, b1):
            return (max(a0, b0) + min(a1, b1)) / 2

        eps = 1e-6
        # (gap, start point, end point) for left, right, top, bottom (internal frame)
        left = [(x0 - o[2], mid(y0, y1, o[1], o[3])) for o in others
                if o[2] <= x0 + eps and overlap(y0, y1, o[1], o[3])]
        g, yy = min(left) if left else (x0, (y0 + y1) / 2)
        sides = [(g, (x0 - g, yy), (x0, yy))]
        right = [(o[0] - x1, mid(y0, y1, o[1], o[3])) for o in others
                 if o[0] >= x1 - eps and overlap(y0, y1, o[1], o[3])]
        g, yy = min(right) if right else (m.width - x1, (y0 + y1) / 2)
        sides.append((g, (x1, yy), (x1 + g, yy)))
        up = [(y0 - o[3], mid(x0, x1, o[0], o[2])) for o in others
              if o[3] <= y0 + eps and overlap(x0, x1, o[0], o[2])]
        g, xx = min(up) if up else (y0, (x0 + x1) / 2)
        sides.append((g, (xx, y0 - g), (xx, y0)))
        down = [(o[1] - y1, mid(x0, x1, o[0], o[2])) for o in others
                if o[1] >= y1 - eps and overlap(x0, x1, o[0], o[2])]
        g, xx = min(down) if down else (m.height - y1, (x0 + x1) / 2)
        sides.append((g, (xx, y1), (xx, y1 + g)))
        for g, p, q in sides:
            if g > 0.05:
                self._dim_line(p, q, self._fmt_cm(g), colour="#2E7D32", tag="gaps", dash=())

    def _draw_measure(self):
        self.canvas.delete("measure")
        if not self.measure_pts:
            return
        p, q = self.measure_pts
        (ux0, uy0), (ux1, uy1) = self.to_user(*p), self.to_user(*q)
        dx, dy = ux1 - ux0, uy1 - uy0
        dist = math.hypot(dx, dy)
        if dist < 0.05:
            return
        c = self.canvas
        if abs(dx) > 0.5 and abs(dy) > 0.5:      # the two legs, for x / y distances
            corner = self.w2s(q[0], p[1])
            c.create_line(*self.w2s(*p), *corner, *self.w2s(*q), fill="#7FA7D6", dash=(2, 3),
                          tags="measure")
        for pt in (p, q):
            sx, sy = self.w2s(*pt)
            c.create_oval(sx - 3, sy - 3, sx + 3, sy + 3, fill="#1F6FEB", outline="", tags="measure")
        text = f"{self._fmt_cm(dist)} cm"
        if abs(dx) >= 0.5 and abs(dy) >= 0.5:
            ang = math.degrees(math.atan2(dy, dx))
            text += f"\ndx {self._fmt_cm(abs(dx))}  dy {self._fmt_cm(abs(dy))}  {ang:.0f}\u00b0"
        self._dim_line(p, q, text)

    def _measure_snap(self, wx, wy):
        """Snap to robot centre / obstacle corners, then to walls and obstacle edges."""
        m = self.world
        tol = 8.0 / max(self.scale, 0.1)
        rx, ry, _ = self._current_pose()
        points = [(rx, ry)] + [(x, y) for (x0, y0, x1, y1) in m.obstacles
                               for x in (x0, x1) for y in (y0, y1)]
        best = min(points, key=lambda pt: math.hypot(pt[0] - wx, pt[1] - wy))
        if math.hypot(best[0] - wx, best[1] - wy) <= tol:
            return best
        xs, ys = [0.0, m.width], [0.0, m.height]
        for x0, y0, x1, y1 in m.obstacles:
            if y0 - tol <= wy <= y1 + tol:
                xs += [x0, x1]
            if x0 - tol <= wx <= x1 + tol:
                ys += [y0, y1]
        bx = min(xs, key=lambda v: abs(v - wx))
        by = min(ys, key=lambda v: abs(v - wy))
        if abs(bx - wx) <= tol:
            wx = bx
        if abs(by - wy) <= tol:
            wy = by
        return self._clamp_in(wx, wy)

    def _resize_handle(self, sx, sy):
        """(obstacle index, sides) if the screen point is on an obstacle edge/corner."""
        obs = self.world.obstacles
        sel = self.obs_list.curselection()
        order = list(range(len(obs) - 1, -1, -1))
        if sel and sel[0] < len(obs):
            order.remove(sel[0])
            order.insert(0, sel[0])               # the selected obstacle wins
        for i in order:
            a, b = self.w2s(obs[i][0], obs[i][1])
            cc, d = self.w2s(obs[i][2], obs[i][3])
            tx = min(6.0, (cc - a) / 4)           # small obstacles: mostly outside the edge
            ty = min(6.0, (d - b) / 4)
            if not (a - 6 <= sx <= cc + 6 and b - 6 <= sy <= d + 6):
                continue
            sides = ""
            if abs(sx - a) <= max(tx, 3) and sx <= a + tx:
                sides += "l"
            elif abs(sx - cc) <= max(tx, 3) and sx >= cc - tx:
                sides += "r"
            if abs(sy - b) <= max(ty, 3) and sy <= b + ty:
                sides += "t"
            elif abs(sy - d) <= max(ty, 3) and sy >= d - ty:
                sides += "b"
            if sides:
                return i, sides
        return None

    RESIZE_CURSOR = {"l": "sb_h_double_arrow", "r": "sb_h_double_arrow",
                     "t": "sb_v_double_arrow", "b": "sb_v_double_arrow",
                     "lt": "top_left_corner", "rb": "bottom_right_corner",
                     "rt": "top_right_corner", "lb": "bottom_left_corner"}

    # =====================================================================================
    # mouse tools
    # =====================================================================================
    def _on_mode(self):
        self.drag = None
        mode = self.mode.get()
        if mode != "zone" and hasattr(self, "race"):
            self.race.zone_kind = None
        self.hint.configure(text=MODE_HINT[mode])
        self.canvas.configure(cursor={"draw": "pencil", "erase": "circle", "box": "tcross",
                                      "zone": "tcross"}
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
            handle = self._resize_handle(e.x, e.y)
            if handle:
                i, sides = handle
                self.drag = ("resize", i, sides)
                self.obs_list.selection_clear(0, "end")
                self.obs_list.selection_set(i)
                self._on_obs_select()
                return
            i = self._obstacle_at(wx, wy)
            if i is not None:
                x0, y0, _, _ = self.world.obstacles[i]
                self.drag = ("obstacle", i, wx - x0, wy - y0)
                self.obs_list.selection_clear(0, "end")
                self.obs_list.selection_set(i)
                self._on_obs_select()
                return
            if 0 <= wx <= self.world.width and 0 <= wy <= self.world.height:
                if self.obs_list.curselection():
                    self.obs_list.selection_clear(0, "end")
                    self._draw_map()
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
        elif mode == "zone":
            p = self._snap_user(*self._clamp_in(wx, wy))
            sx, sy = self.w2s(*p)
            colour = race_mod.ZONE_STYLE[self.race.zone_kind or "check"][0]
            item = self.canvas.create_rectangle(sx, sy, sx, sy, outline=colour, width=2,
                                                dash=(6, 3), fill=colour, stipple="gray25")
            self.drag = ("zone", p, item)
        elif mode == "measure":
            p = self._measure_snap(wx, wy)
            self.measure_pts = (p, p)
            self.drag = ("measure", p)
            self._draw_measure()

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
        elif kind == "measure":
            p0 = self.drag[1]
            if e.state & 0x0001:                  # Shift: straight across or straight up
                if abs(wx - p0[0]) >= abs(wy - p0[1]):
                    wy = p0[1]
                else:
                    wx = p0[0]
                p1 = self._clamp_in(wx, wy)
                snapped = self._measure_snap(*p1)
                p1 = (snapped[0], p0[1]) if p1[1] == p0[1] else (p0[0], snapped[1])
            else:
                p1 = self._measure_snap(wx, wy)
            self.measure_pts = (p0, p1)
            (a, b), (cx, cy) = self.to_user(*p0), self.to_user(*p1)
            self.coord_label.configure(text=f"Distance {math.hypot(cx - a, cy - b):.1f} cm")
            self._draw_measure()
        elif kind == "resize":
            _, i, sides = self.drag
            m = self.world
            x0, y0, x1, y1 = m.obstacles[i]
            ux, uy = self.to_user(*self._clamp_in(wx, wy))
            nx, ny = self.from_user(round(ux), round(uy))       # whole centimetres
            if "l" in sides:
                x0 = min(nx, x1 - 1.0)
            if "r" in sides:
                x1 = max(nx, x0 + 1.0)
            if "t" in sides:
                y0 = min(ny, y1 - 1.0)
            if "b" in sides:
                y1 = max(ny, y0 + 1.0)
            m.obstacles[i] = (max(0.0, x0), max(0.0, y0), min(m.width, x1), min(m.height, y1))
            self.coord_label.configure(text=f"Obstacle {i + 1}: {x1 - x0:g} x {y1 - y0:g} cm")
            self._world_changed()
            self._on_obs_select(redraw=False)
        elif kind in ("box", "zone"):
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
        elif kind == "zone":
            _, p0, item = drag
            self.canvas.delete(item)
            p1 = self._snap_user(*self._clamp_in(*self.s2w(e.x, e.y)))
            box = (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))
            if box[2] - box[0] >= 2 and box[3] - box[1] >= 2 and self.race.zone_kind:
                self.race.add_zone(self.race.zone_kind, box)
        elif kind == "erase":
            self._world_changed()
        elif kind in ("obstacle", "resize"):
            self._world_changed()
            self._on_obs_select(redraw=False)

    def _snap_user(self, x, y):
        ux, uy = self.to_user(x, y)
        return self.from_user(round(ux), round(uy))

    def _on_right_click(self, e):
        if self.mode.get() == "zone":
            if not self.race.locked():
                self.race.delete_zone_at(*self.s2w(e.x, e.y))
            return
        if self.mode.get() == "measure":
            self.measure_pts = None
            self._draw_measure()
            return
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
    # copy / paste obstacles (Ctrl+C, Ctrl+X, Ctrl+V, Ctrl+D)
    # =====================================================================================
    def _selected_obstacle(self):
        sel = self.obs_list.curselection()
        if sel and sel[0] < len(self.world.obstacles):
            return sel[0]
        self.obs_msg.configure(text="Click an obstacle first (tool 1), then Ctrl+C", fg=ERR)
        self.coord_label.configure(text="Select an obstacle first")
        return None

    def _copy_obstacle(self):
        i = self._selected_obstacle()
        if i is None:
            return False
        x0, y0, x1, y1 = self.world.obstacles[i]
        self.clipboard = (x1 - x0, y1 - y0)
        self._paste_from = (x0, y0, x1, y1)
        msg = f"Copied obstacle {i + 1} ({x1 - x0:g} x {y1 - y0:g} cm) - Ctrl+V to paste"
        self.obs_msg.configure(text=msg, fg=OK)
        self.coord_label.configure(text=f"Copied {x1 - x0:g} x {y1 - y0:g} cm")
        return True

    def _cut_obstacle(self):
        i = self.obs_list.curselection()
        if self._copy_obstacle():
            self._delete_obstacle(i[0])
            self._paste_from = None               # paste at the mouse (or where it was)

    def _paste_obstacle(self):
        if not self.clipboard:
            self.coord_label.configure(text="Nothing copied - select an obstacle, Ctrl+C")
            return
        w, h = self.clipboard
        m = self.world
        if self._mouse_w is not None:
            # centre the copy on the mouse
            cx, cy = self._mouse_w
            x0, y0 = cx - w / 2, cy - h / 2
        elif self._paste_from is not None:
            # next to the last one: 2 cm right and 2 cm down
            x0, y0 = self._paste_from[0] + 2, self._paste_from[1] + 2
        else:
            x0, y0 = (m.width - w) / 2, (m.height - h) / 2
        # whole centimetres, inside the arena
        ux, uy = self.to_user(x0, y0 + h)
        x0, y1 = self.from_user(round(ux), round(uy))
        x0 = min(max(x0, 0.0), max(m.width - w, 0.0))
        y1 = min(max(y1, h), m.height)
        box = (x0, y1 - h, x0 + w, y1)
        if self._add_obstacle(box):
            i = len(m.obstacles) - 1
            self._paste_from = m.obstacles[i]
            self.obs_list.selection_clear(0, "end")
            self.obs_list.selection_set(i)
            self._on_obs_select()
            ux, uy = self.to_user(box[0], box[3])
            self.coord_label.configure(text=f"Pasted obstacle {i + 1} at x {ux:g}  y {uy:g}")

    def _duplicate_obstacle(self):
        if self._copy_obstacle():
            mouse, self._mouse_w = self._mouse_w, None      # always next to the original
            self._paste_obstacle()
            self._mouse_w = mouse

    # =====================================================================================
    # robot pose
    # =====================================================================================
    def _program_live(self):
        return (self.sh.get("owner_gen") > 0
                and time.time() - self.last_prog_change < STALE_S)

    def _current_pose(self):
        if self._preview_pose is not None:
            return self._preview_pose
        if getattr(self, "_published", False):
            return tuple(self.sh.get("pose"))
        return tuple(self.world.start)

    def _request_pose(self, x, y, h):
        if hasattr(self, "race"):
            self.race.hand_moved()
        self.sh.set("pose_req", (x, y, h))
        self.sh.bump("pose_req_seq")
        self._preview_pose = (x, y, h)
        self._preview_t = time.time()

    def _reset_pose(self):
        if hasattr(self, "race"):
            self.race.hand_moved()
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
        if e.state & 0x0004:                      # Ctrl: copy / cut / paste / duplicate obstacles
            {"c": self._copy_obstacle, "x": self._cut_obstacle, "v": self._paste_obstacle,
             "d": self._duplicate_obstacle}.get(k, lambda: None)()
            return
        if k in ("a", "b"):
            if k not in self.keys_down:
                self.keys_down.add(k)
                self._button(k, True)
        elif k == "r":
            self._press_reset(True)
            self.root.after(120, lambda: self._press_reset(False))
        elif k == "space":
            self.toggle_pause()
        elif k == "n":
            self.step()
        elif k in ("q", "e"):
            self._rotate_ccw(self._step(e) * (1 if k == "q" else -1))
        elif k in ("1", "2", "3", "4", "5"):
            self.mode.set(MODES[int(k) - 1][0])
            self._on_mode()
        elif k in ("delete", "backspace"):
            sel = self.obs_list.curselection()
            if sel:
                self._delete_obstacle(sel[0])
        elif k == "escape":
            self.measure_pts = None
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
        tk.Label(f, text="Wheel strength %  (100 = exact, 92 = 8 % slower)",
                 bg=PANEL_BG, fg=MUTED, anchor="w", justify="left").pack(fill="x", padx=6, pady=(6, 0))
        grid = tk.Frame(f, bg=PANEL_BG)
        grid.pack(fill="x", padx=2, pady=(2, 0))
        self.gain_entries, self.gain_scales, self.gain_vars = {}, {}, {}
        for row_i, (key, name) in enumerate((("l", "Left"), ("r", "Right"))):
            tk.Label(grid, text=name, bg=PANEL_BG, fg=MUTED, width=5, anchor="e").grid(
                row=row_i, column=0, padx=(4, 2))
            var = tk.DoubleVar(value=100.0)
            minus = tk.Button(grid, text="\u2212", width=2, command=lambda k=key: self._nudge_gain(k, -0.5),
                              repeatdelay=400, repeatinterval=80, bg="#33404D", fg=TEXT, relief="flat",
                              activebackground="#40505F", activeforeground=TEXT, padx=0, pady=0)
            minus.grid(row=row_i, column=1, padx=(0, 2))
            sc = tk.Scale(grid, from_=SLIDER_MIN, to=SLIDER_MAX, resolution=0.1, orient="horizontal",
                          variable=var, showvalue=0, length=150, sliderlength=12, bigincrement=1,
                          bg=PANEL_BG, fg=TEXT, troughcolor=FIELD_BG, highlightthickness=0, bd=0,
                          activebackground=ACCENT,
                          command=lambda _v, k=key: self._on_gain_slider(k))
            sc.grid(row=row_i, column=2, sticky="we", pady=4)
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                sc.bind(ev, lambda e, k=key: self._wheel_gain(k, e))
            plus = tk.Button(grid, text="+", width=2, command=lambda k=key: self._nudge_gain(k, 0.5),
                             repeatdelay=400, repeatinterval=80, bg="#33404D", fg=TEXT, relief="flat",
                             activebackground="#40505F", activeforeground=TEXT, padx=0, pady=0)
            plus.grid(row=row_i, column=3, padx=(2, 0))
            e = tk.Entry(grid, width=6, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT,
                         relief="flat", justify="right")
            e.grid(row=row_i, column=4, padx=(6, 0))
            tk.Label(grid, text="%", bg=PANEL_BG, fg=MUTED).grid(row=row_i, column=5, sticky="w")
            e.bind("<Return>", lambda _e: self._apply_gain())
            self.gain_entries[key], self.gain_scales[key], self.gain_vars[key] = e, sc, var
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(4, 2))
        self._btn(row, "Exact (100/100)", self._reset_gain).pack(side="left")
        self._btn(row, "Random hidden", self._random_gain).pack(side="left", padx=4)
        self._btn(row, "Reveal", self._reveal_gain).pack(side="left")
        # code speed -> the speeds that would drive straight with these motors
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(2, 0))
        tk.Label(row, text="Speed in your code", bg=PANEL_BG, fg=MUTED).pack(side="left")
        self.base_speed = tk.StringVar(value="30")
        sp = tk.Spinbox(row, from_=1, to=100, increment=5, width=4, textvariable=self.base_speed,
                        command=self._show_gain_msg, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT,
                        buttonbackground="#33404D", relief="flat", justify="right")
        sp.pack(side="left", padx=4)
        sp.bind("<KeyRelease>", lambda _e: self._show_gain_msg())
        self.copy_btn = self._btn(row, "Copy", self._copy_suggestion)
        self.copy_btn.pack(side="right")
        self._suggestion = ""
        self.gain_msg = tk.Label(f, text="", bg=PANEL_BG, fg=MUTED, anchor="w", justify="left",
                                 font=("Consolas", 10, "bold"), wraplength=PANEL_W - 30)
        self.gain_msg.pack(fill="x", padx=6, pady=(2, 2))

        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6)
        self.realistic = tk.BooleanVar(value=self._saved_realism[0])
        tk.Checkbutton(row, text="Realistic   dead zone",
                       variable=self.realistic, command=self._publish_realism, bg=PANEL_BG,
                       fg=TEXT, selectcolor=FIELD_BG, activebackground=PANEL_BG,
                       activeforeground=TEXT).pack(side="left")
        self.dead_zone = tk.StringVar(value=str(self._saved_realism[1]))
        sp = tk.Spinbox(row, from_=0, to=40, width=3, textvariable=self.dead_zone,
                        command=self._publish_realism, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT,
                        buttonbackground="#33404D", relief="flat", justify="right")
        sp.pack(side="left", padx=2)
        sp.bind("<KeyRelease>", lambda _e: self._publish_realism())

        tk.Frame(f, bg="#3A424D", height=1).pack(fill="x", padx=6, pady=3)
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6)
        self.show_trail = tk.BooleanVar(value=True)
        tk.Checkbutton(row, text="Show path trail", variable=self.show_trail,
                       command=lambda: self._draw_trail(full=True), bg=PANEL_BG, fg=TEXT,
                       selectcolor=FIELD_BG, activebackground=PANEL_BG,
                       activeforeground=TEXT).pack(side="left")
        self._btn(row, "Clear trail", self._clear_trail).pack(side="left", padx=6)
        self.drift_label = tk.Label(f, text="", bg=PANEL_BG, fg=TEXT, font=("Consolas", 9),
                                    anchor="w", justify="left", wraplength=PANEL_W - 30)
        self.drift_label.pack(fill="x", padx=6, pady=(4, 2))
        self._show_gain()

    def _show_gain(self):
        self._gain_updating = True
        try:
            for i, k in enumerate(("l", "r")):
                if self.gain_hidden:
                    self.gain_vars[k].set(100.0)
                    self.gain_scales[k].configure(state="disabled")
                else:
                    self.gain_scales[k].configure(state="normal")
                    self.gain_vars[k].set(min(SLIDER_MAX, max(SLIDER_MIN, self.motor_gain[i] * 100)))
        finally:
            self._gain_updating = False
        if self.gain_hidden:
            for e in self.gain_entries.values():
                self._set_entry(e, "?")
        else:
            self._set_entry(self.gain_entries["l"], f"{self.motor_gain[0] * 100:g}")
            self._set_entry(self.gain_entries["r"], f"{self.motor_gain[1] * 100:g}")
        self._show_gain_msg()

    def _on_gain_slider(self, key):
        """Slider moved: change that wheel's strength immediately, keep the trail so the
        change in path can be seen, and restart the straightness measurement."""
        if self._gain_updating or self.gain_hidden:
            return
        v = round(float(self.gain_vars[key].get()), 1)
        i = 0 if key == "l" else 1
        if abs(self.motor_gain[i] * 100 - v) < 0.051:      # unchanged (or just redisplayed)
            return
        cur = self.motor_gain[i] * 100
        if (cur < SLIDER_MIN and v == SLIDER_MIN) or (cur > SLIDER_MAX and v == SLIDER_MAX):
            return                                         # typed value beyond the slider's range
        self._set_gain_value(i, key, v)

    def _set_gain_value(self, i, key, v):
        v = round(min(200.0, max(0.0, v)), 1)
        self.motor_gain[i] = v / 100.0
        self._publish_gain()
        self._set_entry(self.gain_entries[key], f"{v:g}")
        self._show_gain_msg()
        self._run_start = None
        self._schedule_save()

    @staticmethod
    def _drift_cm_per_m(rel):
        """Sideways drift (cm) after driving 1 m with a relative wheel-speed error ``rel``."""
        return abs(rel) * 100.0 ** 2 / (2.0 * R.WHEEL_TRACK_CM)

    def _pair_error(self, left, right):
        """Relative speed difference (left - right) of the real wheels for motors(left, right)."""
        vl, vr = left * self.motor_gain[0], right * self.motor_gain[1]
        return 0.0 if vl + vr == 0 else (vl - vr) / ((vl + vr) / 2.0)

    def _describe_pair(self, left, right):
        rel = self._pair_error(left, right)
        d = self._drift_cm_per_m(rel)
        if d < 0.5:
            return f"motors({left}, {right})  straight"
        side = "left" if rel < 0 else "right"           # weaker left wheel -> turns left
        amount = f"~{d:.0f} cm" if d < 60 else "a lot"
        return f"motors({left}, {right})  drifts {amount} {side} per metre"

    def _straight_pairs(self, base):
        """Whole-number motors(left, right) that drive (nearly) straight, best first."""
        gl, gr = self.motor_gain
        if gl <= 0 or gr <= 0:
            return []
        if abs(gl - gr) < 1e-9:
            return [(base, base)]
        if gl > gr:                                   # right is weaker: raise right or lower left
            pairs = [(base, round(base * gl / gr)), (round(base * gr / gl), base)]
        else:
            pairs = [(round(base * gr / gl), base), (base, round(base * gl / gr))]
        pairs = [p for p in pairs if 1 <= p[0] <= 100 and 1 <= p[1] <= 100]
        return sorted(pairs, key=lambda p: abs(self._pair_error(*p)))

    def _straight_speeds(self, base):
        """Short text for the Motors tab: the speeds to put in the code."""
        pairs = self._straight_pairs(base)
        if not pairs:
            return "A wheel at 0 % cannot be corrected.", ""
        if self.motor_gain[0] == self.motor_gain[1]:
            return f"Use motors({base}, {base})  - no change needed", f"motors({base}, {base})"
        text = "Use " + "   or ".join(f"motors({l}, {r})" for l, r in pairs)
        return text, f"motors({pairs[0][0]}, {pairs[0][1]})"

    def _nudge_gain(self, key, step):
        """- / + buttons: change one wheel by a small step."""
        if self.gain_hidden:
            return
        i = 0 if key == "l" else 1
        v = self.motor_gain[i] * 100 + step
        self._gain_updating = True
        try:
            self.gain_vars[key].set(min(SLIDER_MAX, max(SLIDER_MIN, v)))
        finally:
            self._gain_updating = False
        self._set_gain_value(i, key, v)

    def _wheel_gain(self, key, e):
        up = getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4
        step = 0.1 if (e.state & 0x0001) else 0.5
        self._nudge_gain(key, step if up else -step)
        return "break"

    def _show_gain_msg(self):
        if not hasattr(self, "copy_btn"):
            return
        if self.gain_hidden:
            self._suggestion = ""
            self.copy_btn.configure(state="disabled")
            self.gain_msg.configure(text="Hidden mismatch: find the speeds yourself.", fg=ACCENT)
            return
        try:
            base = int(float(self.base_speed.get()))
        except ValueError:
            base = 0
        if not 1 <= base <= 100:
            self._suggestion = ""
            self.copy_btn.configure(state="disabled")
            self.gain_msg.configure(text="Code speed: a whole number 1-100", fg=ERR)
            return
        text, self._suggestion = self._straight_speeds(base)
        self.copy_btn.configure(state="normal" if self._suggestion else "disabled")
        self.gain_msg.configure(text=text, fg=MUTED if self.motor_gain == [1.0, 1.0] else OK)

    def _copy_suggestion(self):
        if self._suggestion:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._suggestion)
            self.coord_label.configure(text=f"Copied {self._suggestion}")

    def _publish_realism(self):
        try:
            dz = max(0, min(40, int(float(self.dead_zone.get()))))
        except ValueError:
            dz = R.DEFAULT_DEAD_ZONE
        self.sh.set("dead_zone", dz)
        self.sh.set("realism", 1 if self.realistic.get() else 0)
        self._saved_realism = (bool(self.realistic.get()), dz)
        self._schedule_save()

    def _publish_gain(self):
        self.sh.set("motor_gain", self.motor_gain)

    def _apply_gain(self):
        try:
            l = self._num(self.gain_entries["l"], "left %")
            r = self._num(self.gain_entries["r"], "right %")
        except ValueError as e:
            self.gain_msg.configure(text=str(e) + " (or press Reveal first)", fg=ERR)
            return
        if not (0 <= l <= 200 and 0 <= r <= 200):
            self.gain_msg.configure(text="Use values between 0 and 200 % (0 = wheel does not turn)",
                                    fg=ERR)
            return
        self.motor_gain = [l / 100.0, r / 100.0]
        self.gain_hidden = False
        self._publish_gain()
        self._show_gain()
        self._run_start = None
        self._schedule_save()
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
                          "mismatch_hidden": self.gain_hidden,
                          "realistic": self._saved_realism[0],
                          "dead_zone": self._saved_realism[1]}
        if hasattr(self, "race"):
            d["simulator"]["race"] = self.race.settings()
        if hasattr(self, "mounted"):
            d["simulator"]["mounted"] = bool(self.mounted.get())
        return d

    def _apply_sim_settings(self, sim):
        try:
            l, r = (float(v) for v in sim.get("motor_strength_percent", [100, 100]))
            if 0 <= l <= 200 and 0 <= r <= 200:
                self.motor_gain = [l / 100.0, r / 100.0]
            self.gain_hidden = bool(sim.get("mismatch_hidden", False))
            self._saved_realism = (bool(sim.get("realistic", False)),
                                   int(sim.get("dead_zone", R.DEFAULT_DEAD_ZONE)))
            self._saved_race = sim.get("race")
            self._saved_mounted = bool(sim.get("mounted", True))
        except (TypeError, ValueError):
            return
        if hasattr(self, "realistic"):
            self.realistic.set(self._saved_realism[0])
            self.dead_zone.set(str(self._saved_realism[1]))
            self._publish_realism()
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
        gen = (self.sh.get("owner_gen"), self.sh.get("run_seq"))
        if gen != self._run_gen:                 # a new run (or RESET) starts a new trail
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
            if seg and math.hypot(x - seg[-1][0], y - seg[-1][1]) > 5.0:
                # The robot cannot move 5 cm in one frame: it was placed by hand or a
                # new run started.  Start a new piece of trail instead of joining them.
                seg = []
                self.trail.append(seg)
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
            f"This run: {fwd:.0f} cm forward, drifted {abs(side):.1f} cm {drift}\n"
            + self._correction_hint()))

    def _correction_hint(self):
        """Suggest wheel speeds that would drive straight, worked out only from the
        measured run (distance and turn), as you would do with a real robot."""
        cmds = getattr(self, "_run_cmds", set())
        if not cmds:
            return "Drive at one constant speed for a correction."
        if len(cmds) > 1:
            return "Speeds changed during the run - drive at one\nconstant speed for a correction."
        lc, rc = next(iter(cmds))
        if lc == 0 or rc == 0 or (lc > 0) != (rc > 0):
            return "Drive both wheels forward for a correction."
        s = self._run_dist
        if abs(s) < 10:
            return "Drive at least 10 cm for a correction."
        theta = math.radians(self._run_turn)                 # + = turned right on screen
        sl = s + theta * R.WHEEL_TRACK_CM / 2.0               # distance each wheel travelled
        sr = s - theta * R.WHEEL_TRACK_CM / 2.0
        if sl * sr <= 0:
            return "The robot spun too much to work out a correction."
        if abs(self._run_turn) < 0.5:
            return f"Straight - keep motors({lc}, {rc})"
        # wheel speed = command x strength, so the measured wheel distances give the fix
        pairs = [(lc, round(sl * rc / sr)), (round(sr * lc / sl), rc)]
        pairs = [p for p in pairs if 1 <= abs(p[0]) <= 100 and 1 <= abs(p[1]) <= 100]
        if not pairs:
            return "Too big a difference to correct at this speed."
        return "Measured fix: " + "   or ".join(f"motors({l}, {r})" for l, r in pairs)

    # =====================================================================================
    # Sensors tab: accelerometer (tilt pad), microphone, speaker, temperature, light
    # =====================================================================================
    PAD = 116

    def _build_sensor_tab(self):
        f = self._tab("Sensors")
        self.tilt = [0.0, 0.0]          # roll (right edge down +), pitch (logo edge down +), deg
        self.face_down = False

        self.mounted = tk.BooleanVar(value=self._saved_mounted)
        tk.Checkbutton(f, text="micro:bit upright on the Cutebot (as on the robot)",
                       variable=self.mounted, command=self._mount_changed, bg=PANEL_BG, fg=TEXT,
                       selectcolor=FIELD_BG, activebackground=PANEL_BG,
                       activeforeground=TEXT, anchor="w").pack(fill="x", padx=4, pady=(4, 0))
        self.pad_hint = tk.Label(f, text="", bg=PANEL_BG, fg=MUTED, anchor="w", justify="left")
        self.pad_hint.pack(fill="x", padx=6, pady=(0, 2))
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6)
        P = self.PAD
        pad = self.pad = tk.Canvas(row, width=P, height=P, bg=FIELD_BG, highlightthickness=1,
                                   highlightbackground="#3A424D", cursor="hand2")
        pad.pack(side="left")
        pad.create_rectangle(8, 8, P - 8, P - 8, outline="#3A424D")
        pad.create_line(P / 2, 8, P / 2, P - 8, fill="#2A3038")
        pad.create_line(8, P / 2, P - 8, P / 2, fill="#2A3038")
        self.pad_top = pad.create_text(P / 2, 15, text="front", fill=MUTED, font=("Segoe UI", 7))
        self.pad_dot = pad.create_oval(0, 0, 0, 0, fill="#1F6FEB", outline="#9CDCFE")
        for ev in ("<ButtonPress-1>", "<B1-Motion>"):
            pad.bind(ev, self._on_pad)
        pad.bind("<Double-Button-1>", lambda e: self._set_tilt(0, 0, False))

        btns = tk.Frame(row, bg=PANEL_BG)
        btns.pack(side="left", fill="y", padx=(8, 0))
        self.tilt_btns = {}
        for text, cmd in (("Flat", lambda: self._set_tilt(0, 0, False)),
                          ("Face down", lambda: self._set_tilt(0, 0, True)),
                          ("Logo up", lambda: self._set_tilt(0, -90, False)),
                          ("Shake", lambda: self._pulse("shake")),
                          ("Freefall", lambda: self._pulse("freefall"))):
            b = self._btn(btns, text, cmd)
            b.pack(fill="x", pady=1)
            self.tilt_btns[text] = b
        self.accel_label = tk.Label(f, text="", bg=PANEL_BG, fg=TEXT, font=("Consolas", 9),
                                    anchor="w", justify="left")
        self.accel_label.pack(fill="x", padx=6, pady=(2, 4))

        tk.Frame(f, bg="#3A424D", height=1).pack(fill="x", padx=6, pady=2)
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6)
        tk.Label(row, text="Microphone", bg=PANEL_BG, fg=MUTED).pack(side="left")
        self.mic_var = tk.IntVar(value=0)
        tk.Scale(row, from_=0, to=255, orient="horizontal", variable=self.mic_var, length=140,
                 showvalue=True, bg=PANEL_BG, fg=TEXT, troughcolor=FIELD_BG, highlightthickness=0,
                 bd=0, command=lambda v: self._publish_sensors()).pack(side="left", padx=4)
        self._btn(row, "Clap", self._clap).pack(side="left")

        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(2, 0))
        self.speaker_label = tk.Label(row, text="\u266a  silent", bg=PANEL_BG, fg=MUTED,
                                      font=("Segoe UI", 10, "bold"), anchor="w", width=14)
        self.speaker_label.pack(side="left")
        self.sound_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="Play sounds on this PC", variable=self.sound_var,
                       command=self._publish_sensors, bg=PANEL_BG, fg=TEXT, selectcolor=FIELD_BG,
                       activebackground=PANEL_BG, activeforeground=TEXT).pack(side="left")

        tk.Frame(f, bg="#3A424D", height=1).pack(fill="x", padx=6, pady=3)
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6)
        self.temp_var = tk.IntVar(value=21)
        self.light_var = tk.IntVar(value=128)
        for label, var, lo, hi in (("Temp \u00b0C", self.temp_var, -10, 50),
                                   ("Light", self.light_var, 0, 255)):
            tk.Label(row, text=label, bg=PANEL_BG, fg=MUTED).pack(side="left")
            tk.Scale(row, from_=lo, to=hi, orient="horizontal", variable=var, length=88,
                     showvalue=True, bg=PANEL_BG, fg=TEXT, troughcolor=FIELD_BG,
                     highlightthickness=0, bd=0,
                     command=lambda v: self._publish_sensors()).pack(side="left", padx=(2, 6))
        self._mic_clap_until = 0.0
        self._mount_changed()

    def _on_pad(self, e):
        P = self.PAD
        r = (P - 16) / 2.0
        dx = max(-1.0, min(1.0, (e.x - P / 2) / r))
        dy = max(-1.0, min(1.0, (e.y - P / 2) / r))
        self._set_tilt(dx * 90.0, -dy * 90.0, False)

    def _mount_changed(self):
        mounted = self.mounted.get()
        self.pad.itemconfigure(self.pad_top, text="front" if mounted else "logo")
        self.pad_hint.configure(text=("Tilt the robot (a slope): drag the dot. Speeding up,\n"
                                      "braking and bumps show in z and x.") if mounted else
                                "Tilt the micro:bit: drag the dot (it rolls downhill)")
        self.tilt_btns["Flat"].configure(text="Level" if mounted else "Flat")
        for name in ("Face down", "Logo up"):
            self.tilt_btns[name].configure(state="disabled" if mounted else "normal")
        if mounted:
            self.face_down = False
        self._draw_pad()
        self._publish_sensors()
        if self._save_job is not None or hasattr(self, "race"):
            self._schedule_save()

    def _gravity(self):
        if self.mounted.get():
            from .robot import DISPLAY_FACES_FORWARD
            return sensors.accel_mounted(self.tilt[0], self.tilt[1], DISPLAY_FACES_FORWARD)
        return sensors.accel_from_tilt(self.tilt[0], self.tilt[1], self.face_down)

    def _set_tilt(self, roll, pitch, face_down):
        self.tilt = [roll, pitch]
        self.face_down = face_down
        self._draw_pad()
        self._publish_sensors()

    def _draw_pad(self):
        P = self.PAD
        r = (P - 16) / 2.0
        cx = P / 2 + self.tilt[0] / 90.0 * r
        cy = P / 2 - self.tilt[1] / 90.0 * r
        d = 7
        self.pad.coords(self.pad_dot, cx - d, cy - d, cx + d, cy + d)
        self.pad.itemconfigure(self.pad_dot, fill="#8B4A4A" if self.face_down else "#1F6FEB")
        x, y, z = self._gravity()
        g = sensors.gesture_from_accel(x, y, z) or "-"
        self.accel_label.configure(text=f"x {x:+6.0f}  y {y:+6.0f}  z {z:+6.0f} mg\n"
                                        f"gesture: {g}" + ("   (face down)" if self.face_down else ""))

    def _update_accel_label(self, published):
        """Show the live reading (with the robot's motion) while a program runs."""
        if not published or not hasattr(self, "accel_label"):
            return
        x, y, z = self.sh.get("accel_now")
        g = sensors.gesture_from_accel(x, y, z) or "-"
        text = f"x {x:+6.0f}  y {y:+6.0f}  z {z:+6.0f} mg\ngesture: {g}"
        if self.accel_label.cget("text") != text:
            self.accel_label.configure(text=text)

    def _pulse(self, name):
        self.sh.set("pulse_name", name)
        self.sh.bump("pulse_seq")
        self.accel_label.configure(text=self.accel_label.cget("text").split("\n")[0]
                                   + f"\ngesture: {name}!")
        self.root.after(700, self._draw_pad)

    def _clap(self):
        self._mic_clap_until = time.time() + 0.35
        self._publish_sensors()
        self.root.after(400, self._publish_sensors)

    def _publish_sensors(self):
        sh = self.sh
        sh.set("accel", self._gravity())
        sh.set("mounted", 1 if self.mounted.get() else 0)
        level = 255 if time.time() < self._mic_clap_until else int(self.mic_var.get())
        sh.set("mic_level", level)
        sh.set("temp_c", float(self.temp_var.get()))
        sh.set("light", int(self.light_var.get()))
        sh.set("sound_out", 1 if self.sound_var.get() else 0)
        sh.set("sensors_set", 1)

    def _update_speaker(self, published):
        label = self.sh.get("speaker_label") if published else ""
        freq = self.sh.get("speaker_freq") if published else 0.0
        if label and label != "rest":
            text = f"\u266a  {label}" + (f"  {freq:.0f} Hz" if freq and "Hz" not in label else "")
            self.speaker_label.configure(text=text, fg="#3FB950")
        else:
            self.speaker_label.configure(text="\u266a  silent", fg=MUTED)

    # =====================================================================================
    # micro:bit reference (Help window)
    # =====================================================================================
    # --- pause, step, slow motion -------------------------------------------------------------
    def _sim_controls_locked(self):
        r = getattr(self, "race", None)
        return r is not None and r.race_id is not None      # not during a teacher's race

    def _publish_sim_controls(self):
        if self._sim_controls_locked():
            self.speed_var.set(1.0)
            self.paused = False
        self.sh.set("sim_speed", float(self.speed_var.get()))
        self.sh.set("paused", 1 if self.paused else 0)
        self.sh.set("pause_on", sum(bit for bit, v in self.pause_on_vars if v.get()))
        self.pause_btn.configure(text="Resume (Space)" if self.paused else "Pause (Space)",
                                 bg="#9E6A03" if self.paused else "#2D333B")
        on = [n for (bit, v), n in zip(self.pause_on_vars, ("motors", "line", "bump")) if v.get()]
        self.pause_on_btn.configure(text=("Pause on: " + ", ".join(on) + " \u25be") if on
                                    else "Pause on \u25be", bg="#1F6FEB" if on else "#2D333B")

    def _sim_ui_changed(self):
        self._publish_sim_controls()
        self.root.focus_set()                  # so Space / N keep working

    def toggle_pause(self):
        if self._sim_controls_locked():
            self.coord_label.configure(text="No pausing during a race")
            return
        self.paused = not self.paused
        if not self.paused:
            self.pause_reason = ""
        self._sim_ui_changed()

    def step(self):
        """Run the program to its next line, then pause again."""
        if self._sim_controls_locked():
            return
        if not self.paused:
            self.paused = True
            self.pause_reason = ""
            self._publish_sim_controls()
            return
        self.sh.bump("step_seq")

    def _sim_frame(self):
        rs = (self.sh.get("owner_gen"), self.sh.get("run_seq"))
        if rs != getattr(self, "_pause_run", None):
            self._pause_run = rs
            self.pause_reason = ""                 # a new run: the old reason no longer applies
        seq = self.sh.get("auto_pause_seq")
        if seq != self._auto_seen:
            self._auto_seen = seq
            if seq and not self.paused and not self._sim_controls_locked():
                self.paused = True                     # the program paused itself
                self.pause_reason = self.sh.get("auto_pause_why")
                self._publish_sim_controls()
                self.open_code()

    # --- extra windows ---------------------------------------------------------------------
    def open_code(self):
        if self._code_win is not None and self._code_win.alive():
            self._code_win.lift()
        else:
            self._code_win = panels.CodeWindow(self.root, self)

    def open_graphs(self):
        if self._graph_win is not None and self._graph_win.alive():
            self._graph_win.lift()
        else:
            self._graph_win = panels.GraphWindow(self.root)

    def open_radio(self):
        if self._radio_win is not None and self._radio_win.alive():
            self._radio_win.lift()
        else:
            self._radio_win = panels.RadioWindow(self.root, self.radio_to_robot)
            for text, colour in self.radio_log[-200:]:
                self._radio_win.add(text, colour)

    # --- radio -----------------------------------------------------------------------------
    def radio_to_robot(self, data, group, channel):
        """A message for the program (from the console or another robot)."""
        self.sh.ring_put("rx_msgs", "rx_wr", data, group, channel)

    def _radio_note(self, text, colour):
        self.radio_log.append((text, colour))
        del self.radio_log[:-300]
        if self._radio_win is not None and self._radio_win.alive():
            self._radio_win.add(text, colour)

    def _radio_frame(self, has_prog):
        """Collect what the program sent; pass it on to the other robots (LAN)."""
        if not has_prog:
            self._tx_pos = self.sh.get("tx_wr")
            return
        self._tx_pos, msgs = self.sh.ring_get("tx_msgs", "tx_wr", self._tx_pos)
        for data, group, channel in msgs:
            self._radio_note(f"from robot g{group:<3} ch{channel:<2}  {panels.describe(data)}", panels.OK)
            self.radio_sent(data, group, channel)

    def radio_sent(self, data, group, channel):
        """The program sent a radio message: pass it on to the LAN (shared arena)."""
        self.race.radio_out(data, group, channel)

    def open_help(self, query=""):
        if self._help is not None and self._help.top.winfo_exists():
            self._help.top.deiconify()
            self._help.top.lift()
            self._help.entry.focus_set()
            return
        self._help = HelpWindow(self.root)

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
        gen = sh.get("owner_gen")
        if gen != getattr(self, "_seen_gen", None):
            # A new program has claimed the simulator. Its position is only valid
            # once it has published at least once (until then the shared block still
            # holds old or empty values such as x = 0, y = 0).
            self._seen_gen = gen
            self._gen_tick = tick
            self.last_prog_tick = tick
        if tick != self.last_prog_tick:
            self.last_prog_tick = tick
            self.last_prog_change = now
        published = has_prog and tick != self._gen_tick
        self._published = published
        live = published and now - self.last_prog_change < STALE_S

        # A pose set by the user is shown until the program has applied it.
        if live and self._preview_pose is not None and self.drag is None:
            px, py, ph = sh.get("pose")
            qx, qy, qh = self._preview_pose
            applied = abs(px - qx) < 0.05 and abs(py - qy) < 0.05 and abs(_wrap(ph - qh)) < 0.1
            if applied or now - self._preview_t > 0.4:
                self._preview_pose = None
        if self._preview_pose is not None:
            pose = self._preview_pose
        elif published:
            pose = tuple(sh.get("pose"))
        else:
            pose = tuple(self.world.start)

        motors = sh.get("motors") if published else [0.0, 0.0]
        wheel_v = sh.get("wheel_v") if published else [0.0, 0.0]
        dt = min(0.1, now - getattr(self, "_last_frame_t", now))
        self._last_frame_t = now
        tp = getattr(self, "_tread_pos", [0.0, 0.0])
        self._tread_pos = [tp[0] + wheel_v[0] * dt, tp[1] + wheel_v[1] * dt]
        line = sh.get("line") if published else [1, 1]
        self._update_robot(pose, sh.get("lights"), sh.get("neopixels"), line,
                           sh.get("sonar_cm"), sh.get("sonar_active") and published, self._tread_pos)

        for i, v in enumerate(sh.get("display")):
            col = LED_OFF if v == 0 else _rgb(*_mix((255, 40, 30), (58, 20, 20), 0.25 + 0.75 * v / 9))
            self.board.itemconfigure(self.leds[i], fill=col)

        name = sh.get("prog_name")
        state = sh.get("prog_state")
        if not has_prog:
            text, colour = "Waiting for a program...\nRun a .py file that imports microbit.", MUTED
        elif state == shared.STATE_RUNNING and self.paused:
            why = f" - {self.pause_reason}" if self.pause_reason else ""
            text, colour = (f"PAUSED at line {sh.get('cur_line')}{why}\n"
                            "Space = resume, N = step one line"), "#D29922"
        elif state == shared.STATE_RUNNING and live:
            speed = self.speed_var.get()
            text = f"Running  {name}" + (f"   (speed {speed:g}x)" if speed != 1 else "")
            colour = OK
        elif state == shared.STATE_RUNNING:
            text, colour = (f"Paused or stopped  {name}\n(breakpoint in the debugger, "
                            "or Stop was pressed)"), "#D29922"
        elif state == shared.STATE_FINISHED:
            extra = "  - motors still on" if live and any(abs(m) > 0 for m in motors) else ""
            text, colour = f"Finished  {name}{extra}\nPress RESET (or R) to run it again", ACCENT
            if not live:
                text = f"Finished  {name}"
        else:
            text, colour = f"Error in  {name}" + ("\nFix it, or press RESET to run again" if live else ""), ERR
        self.status.configure(text=text, fg=colour)
        self.message.configure(text=sh.get("message") if state == shared.STATE_ERROR else "")

        self._update_trail(has_prog, live, pose, motors)
        self._radio_frame(has_prog)
        self._sim_frame()
        self.race.frame(now, pose, has_prog, live, state, wheel_v)
        for win in (self._code_win, self._graph_win, self._radio_win):
            if win is not None and win.alive():
                if win is self._code_win:
                    win.update(sh, has_prog, live)
                elif win is self._graph_win:
                    win.update(sh, live)
                else:
                    win.update(sh, has_prog)
        pct = 100.0 / R.CM_PER_S_AT_100
        wheels = f"Wheels     L {wheel_v[0] * pct:+5.1f} %   R {wheel_v[1] * pct:+5.1f} %   (real)\n"
        if self.gain_hidden:
            wheels = "Wheels     hidden mismatch (Motors tab)\n"
        self._update_speaker(published)
        self._update_accel_label(live)
        x, y = self.to_user(pose[0], pose[1])
        a = _wrap(-pose[2])
        if sh.get("sonar_active") and published:
            d = sh.get("sonar_cm")
            sonar = (" < 2 cm: no reading" if d < R.SONAR_MIN_CM else
                     " nothing in range" if d >= R.SONAR_MAX_CM else f"{d:5.1f} cm")
        else:
            sonar = "  (not used)"
        self.readout.configure(text=(
            f"Motors     L {motors[0]:+5.0f} %   R {motors[1]:+5.0f} %   (code)\n"
            f"{wheels}"
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


class HelpWindow:
    """Searchable quick reference for the micro:bit API and the Cutebot."""

    def __init__(self, root):
        import webbrowser

        self._web = webbrowser
        top = self.top = tk.Toplevel(root)
        top.title("micro:bit MicroPython reference")
        top.configure(bg=PANEL_BG)
        top.geometry("900x560")
        top.minsize(640, 380)

        head = tk.Frame(top, bg=PANEL_BG)
        head.pack(fill="x", padx=12, pady=(12, 6))
        tk.Label(head, text="Search", bg=PANEL_BG, fg=MUTED).pack(side="left")
        self.query = tk.StringVar()
        self.entry = tk.Entry(head, textvariable=self.query, bg=FIELD_BG, fg=TEXT,
                              insertbackground=TEXT, relief="flat", font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True, padx=8, ipady=4)
        self.query.trace_add("write", lambda *a: self._filter())
        tk.Label(head, text="e.g. display, button, motor, line, sleep", bg=PANEL_BG,
                 fg=MUTED).pack(side="left")

        body = tk.Frame(top, bg=PANEL_BG)
        body.pack(fill="both", expand=True, padx=12)
        self.listbox = tk.Listbox(body, width=30, bg=FIELD_BG, fg=TEXT, relief="flat",
                                  selectbackground="#1F6FEB", font=("Consolas", 10),
                                  activestyle="none", exportselection=False)
        self.listbox.pack(side="left", fill="y")
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._show_selected())
        right = tk.Frame(body, bg=PANEL_BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.text = tk.Text(right, bg=FIELD_BG, fg=TEXT, relief="flat", wrap="word",
                            font=("Segoe UI", 10), padx=12, pady=10, cursor="arrow")
        self.text.pack(fill="both", expand=True)
        t = self.text
        t.tag_configure("title", font=("Segoe UI", 14, "bold"), foreground="#FFFFFF")
        t.tag_configure("sig", font=("Consolas", 10), foreground="#9CDCFE")
        t.tag_configure("yes", foreground=OK, font=("Segoe UI", 9, "bold"))
        t.tag_configure("part", foreground="#D29922", font=("Segoe UI", 9, "bold"))
        t.tag_configure("no", foreground=ERR, font=("Segoe UI", 9, "bold"))
        t.tag_configure("head", font=("Segoe UI", 10, "bold"), foreground=MUTED)
        t.tag_configure("code", font=("Consolas", 10), background="#14181D", foreground="#D7E3EF",
                        lmargin1=8, lmargin2=8)

        btns = tk.Frame(right, bg=PANEL_BG)
        btns.pack(fill="x", pady=8)

        def mk(text, cmd):
            return tk.Button(btns, text=text, command=cmd, bg="#33404D", fg=TEXT,
                             activebackground="#40505F", activeforeground=TEXT, relief="flat",
                             padx=10, pady=3)

        mk("Copy example", self._copy).pack(side="left")
        mk("Open full documentation (V2)", self._open_doc).pack(side="left", padx=6)
        mk("All micro:bit docs", lambda: self._web.open(reference.DOCS_HOME)).pack(side="right")
        self.msg = tk.Label(right, text="", bg=PANEL_BG, fg=MUTED, anchor="w")
        self.msg.pack(fill="x")

        self.results = []
        self._filter()
        self.entry.focus_set()
        top.bind("<Escape>", lambda e: top.destroy())

    def _filter(self):
        self.results = reference.search(self.query.get())
        self.listbox.delete(0, "end")
        for e in self.results:
            self.listbox.insert("end", e["name"])
        if self.results:
            self.listbox.selection_set(0)
            self._show(self.results[0])
        else:
            self._show(None)

    def _show_selected(self):
        sel = self.listbox.curselection()
        if sel:
            self._show(self.results[sel[0]])

    def _show(self, e):
        self.current = e
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if e is None:
            t.insert("end", "Nothing found.\n\n", "title")
            t.insert("end", "Try another word, or press 'All micro:bit docs'.")
        else:
            sim = e["sim"]
            tag = "yes" if sim.startswith(reference.YES) else "no" if sim.startswith(reference.NO) else "part"
            t.insert("end", e["name"] + "\n", "title")
            t.insert("end", e["signature"] + "\n\n", "sig")
            t.insert("end", "In the simulator: " + sim + "\n\n", tag)
            t.insert("end", e["summary"] + "\n\n")
            t.insert("end", "Example\n", "head")
            t.insert("end", e["example"] + "\n", "code")
        t.configure(state="disabled")
        self.msg.configure(text="")

    def _copy(self):
        if self.current:
            self.top.clipboard_clear()
            self.top.clipboard_append(self.current["example"])
            self.msg.configure(text="Example copied - paste it into PyCharm.", fg=OK)

    def _open_doc(self):
        if self.current:
            self._web.open(self.current["url"])
            self.msg.configure(text="Opened in your web browser.", fg=OK)


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
