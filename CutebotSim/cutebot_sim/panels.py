"""Extra windows of the simulator: Code view and live sensor Graphs."""

import collections
import os
import time
import tkinter as tk

from . import checker, robot as R, shared

BG = "#1F2328"
PANEL_BG = "#262B31"
FIELD_BG = "#1B1F24"
TEXT = "#E6E8EA"
MUTED = "#9AA3AD"
ACCENT = "#4FB3FF"
OK = "#3FB950"
ERR = "#FF7B72"
WARN = "#D29922"
LEFT_C = "#4FB3FF"
RIGHT_C = "#F0883E"


def _btn(parent, text, cmd):
    return tk.Button(parent, text=text, command=cmd, bg="#33404D", fg=TEXT,
                     activebackground="#40505F", activeforeground=TEXT, relief="flat",
                     padx=8, pady=2)


# =========================================================================================
# Code window: which line is running, last motor commands, micro:bit checker
# =========================================================================================
class CodeWindow:
    def __init__(self, root, app=None):
        self.app = app
        top = self.top = tk.Toplevel(root)
        top.title("Code - which line is running")
        top.configure(bg=PANEL_BG)
        top.geometry("760x640")
        top.minsize(520, 420)

        self.status = tk.Label(top, text="", bg=PANEL_BG, fg=TEXT, font=("Segoe UI", 10, "bold"),
                               anchor="w")
        self.status.pack(fill="x", padx=8, pady=(8, 2))
        bar = tk.Frame(top, bg=PANEL_BG)
        bar.pack(fill="x", padx=8, pady=(0, 4))
        if app is not None:
            self.pause_btn = _btn(bar, "Pause (Space)", app.toggle_pause)
            self.pause_btn.pack(side="left")
            self.step_btn = _btn(bar, "Step (N)", app.step)
            self.step_btn.pack(side="left", padx=4)
        _btn(bar, "Check for micro:bit", self.run_check).pack(side="left", padx=(12, 0))
        self.follow = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="Follow the running line", variable=self.follow, bg=PANEL_BG,
                       fg=TEXT, selectcolor=FIELD_BG, activebackground=PANEL_BG,
                       activeforeground=TEXT).pack(side="right")
        top.bind("<space>", lambda e: app.toggle_pause() if app is not None else None)
        top.bind("<KeyPress-n>", lambda e: app.step() if app is not None else None)

        pane = tk.PanedWindow(top, orient="vertical", bg=PANEL_BG, sashwidth=6, bd=0)
        pane.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        code_f = tk.Frame(pane, bg=PANEL_BG)
        self.text = tk.Text(code_f, bg=FIELD_BG, fg=TEXT, font=("Consolas", 10), wrap="none",
                            relief="flat", insertbackground=TEXT, padx=4)
        sb = tk.Scrollbar(code_f, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("num", foreground="#6B737D")
        self.text.tag_configure("cur", background="#5A4A12")
        self.text.tag_configure("error", background="#4A1F1F")
        self.text.tag_configure("warning", background="#3D3418")
        self.text.tag_configure("note", background="#1E3247")
        self.text.tag_raise("cur")
        pane.add(code_f, minsize=160, stretch="always")

        low = tk.Frame(pane, bg=PANEL_BG)
        tk.Label(low, text="Messages (click to go to the line)", bg=PANEL_BG, fg=MUTED,
                 anchor="w").pack(fill="x")
        self.checks = tk.Listbox(low, height=5, bg=FIELD_BG, fg=TEXT, relief="flat",
                                 font=("Consolas", 9), activestyle="none")
        self.checks.pack(fill="x")
        self.checks.bind("<<ListboxSelect>>", self._goto_check)
        tk.Label(low, text="Last motor commands (newest at the bottom)", bg=PANEL_BG, fg=MUTED,
                 anchor="w").pack(fill="x", pady=(6, 0))
        self.cmds = tk.Listbox(low, height=8, bg=FIELD_BG, fg=TEXT, relief="flat",
                               font=("Consolas", 9), activestyle="none")
        self.cmds.pack(fill="both", expand=True)
        self.cmds.bind("<<ListboxSelect>>", self._goto_cmd)
        pane.add(low, minsize=150)

        self.path = None
        self.mtime = None
        self.line = 0
        self.cmd_n = None
        self.run_seq = None
        self.check_lines = []
        self.cmd_lines = []

    def alive(self):
        try:
            return bool(self.top.winfo_exists())
        except tk.TclError:
            return False

    def lift(self):
        self.top.deiconify()
        self.top.lift()

    # --- file --------------------------------------------------------------------------
    def _load(self, path):
        self.path = path
        try:
            self.mtime = os.path.getmtime(path)
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except OSError:
            src = ""
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        lines = src.split("\n")
        width = len(str(len(lines)))
        for i, ln in enumerate(lines, 1):
            t.insert("end", f"{i:>{width}}  ", "num")
            t.insert("end", ln + ("\n" if i < len(lines) else ""))
        t.configure(state="disabled")
        self.top.title(f"Code - {os.path.basename(path)}")
        self.line = 0
        self.checks.delete(0, "end")
        self.check_lines = []

    def _show_line(self, n):
        t = self.text
        t.tag_remove("cur", "1.0", "end")
        if n > 0:
            t.tag_add("cur", f"{n}.0", f"{n}.end+1c")
            if self.follow.get():
                t.see(f"{n}.0")

    # --- checker --------------------------------------------------------------------------
    def run_check(self):
        if not self.path:
            self.status.configure(text="Run a program first", fg=ERR)
            return
        self._load(self.path)
        found = checker.check_file(self.path)
        t = self.text
        for tag in ("error", "warning", "note"):
            t.tag_remove(tag, "1.0", "end")
        self.checks.delete(0, "end")
        self.check_lines = []
        colours = {"error": ERR, "warning": WARN, "note": ACCENT}
        self.checks.insert("end", checker.summary(found))
        self.checks.itemconfigure(0, foreground=OK if not found else
                                  ERR if any(f[1] == "error" for f in found) else WARN)
        self.check_lines.append(0)
        for line, level, msg in found:
            where = f"line {line:>3}" if line else "file    "
            self.checks.insert("end", f"{where}  {level:7}  {msg}")
            self.checks.itemconfigure("end", foreground=colours[level])
            self.check_lines.append(line)
            if line:
                t.tag_add(level, f"{line}.0", f"{line}.end+1c")

    def _goto_check(self, _e):
        sel = self.checks.curselection()
        if sel and self.check_lines[sel[0]]:
            self.follow.set(False)
            self.text.see(f"{self.check_lines[sel[0]]}.0")

    def _goto_cmd(self, _e):
        sel = self.cmds.curselection()
        if sel and sel[0] < len(self.cmd_lines) and self.cmd_lines[sel[0]]:
            self.follow.set(False)
            self.text.see(f"{self.cmd_lines[sel[0]]}.0")

    # --- every frame ------------------------------------------------------------------
    def update(self, sh, has_prog, live):
        if not has_prog:
            self.status.configure(text="Waiting for a program...", fg=MUTED)
            return
        path = sh.get("prog_path")
        if path and path != self.path:
            self._load(path)
        elif path and self.mtime is not None:
            try:
                if os.path.getmtime(path) != self.mtime:
                    self._load(path)                 # the file was edited
            except OSError:
                pass
        state = sh.get("prog_state")
        line = sh.get("cur_line")
        if self.app is not None:
            self.pause_btn.configure(text="Resume (Space)" if sh.get("paused") else "Pause (Space)")
        if not sh.get("trace_on"):
            self.status.configure(text="Line view is off while the debugger is attached "
                                       "(use breakpoints instead)", fg=WARN)
            line = 0
        elif sh.get("paused") and state == shared.STATE_RUNNING:
            why = self.app.pause_reason if self.app is not None else ""
            self.status.configure(text=f"PAUSED at line {line}" + (f" - {why}" if why else "")
                                       + "   Step = next line", fg=WARN)
        elif sh.get("held"):
            self.status.configure(text="Waiting for the teacher's GO", fg=WARN)
        elif state == shared.STATE_RUNNING and live:
            self.status.configure(text=f"Running line {line}" if line else "Running", fg=OK)
        elif state == shared.STATE_RUNNING:
            self.status.configure(text=f"Paused at line {line}" if line else "Paused", fg=WARN)
        elif state == shared.STATE_ERROR:
            self.status.configure(text="Stopped with an error (see PyCharm's Run window)", fg=ERR)
        else:
            self.status.configure(text="Finished", fg=ACCENT)
        if line != self.line:
            self.line = line
            self._show_line(line)
        rs = sh.get("run_seq")
        n = sh.get("cmd_n")
        if n != self.cmd_n or rs != self.run_seq:
            self.cmd_n, self.run_seq = n, rs
            self._show_cmds(sh, n)

    def _show_cmds(self, sh, n):
        off, _ = sh.raw("cmd_log")
        first = max(0, n - shared.CMD_LOG)
        rows, lines = [], []
        for k in range(first, n):
            t, l, r, ln, mln = shared.struct.unpack_from("<5f", sh.buf,
                                                         off + (k % shared.CMD_LOG) * 20)
            ln, mln = int(ln), int(mln)
            where = f"line {ln:>3}" + (f" (called from line {mln})" if mln and mln != ln else "")
            rows.append(f"{t:8.2f} s   motors  L {l:+4.0f}   R {r:+4.0f}   {where}")
            lines.append(mln or ln)
        self.cmds.delete(0, "end")
        for row in rows:
            self.cmds.insert("end", row)
        self.cmd_lines = lines
        self.cmds.see("end")


# =========================================================================================
# Graphs window: line sensors, sonar and motors over time
# =========================================================================================
class GraphWindow:
    SPANS = (5, 10, 30)

    def __init__(self, root):
        top = self.top = tk.Toplevel(root)
        top.title("Sensor graphs")
        top.configure(bg=PANEL_BG)
        top.geometry("820x600")
        top.minsize(520, 400)
        bar = tk.Frame(top, bg=PANEL_BG)
        bar.pack(fill="x", padx=8, pady=6)
        self.span = tk.IntVar(value=10)
        tk.Label(bar, text="Show the last", bg=PANEL_BG, fg=MUTED).pack(side="left")
        for s in self.SPANS:
            tk.Radiobutton(bar, text=f"{s} s", value=s, variable=self.span, indicatoron=0,
                           bg="#2D333B", fg=TEXT, selectcolor="#1F6FEB", relief="flat",
                           padx=8, command=self._redraw).pack(side="left", padx=2)
        self.paused = False
        self.pause_btn = _btn(bar, "Pause", self.toggle_pause)
        self.pause_btn.pack(side="right")
        _btn(bar, "Clear", self.clear).pack(side="right", padx=6)
        self.canvas = tk.Canvas(top, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.data = collections.deque(maxlen=60 * 35)    # (t, ll, lr, sonar|None, ml, mr, wl, wr)
        self._last_draw = 0.0
        self._t_pause = None
        self.run_seq = None

    def alive(self):
        try:
            return bool(self.top.winfo_exists())
        except tk.TclError:
            return False

    def lift(self):
        self.top.deiconify()
        self.top.lift()

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.configure(text="Resume" if self.paused else "Pause")
        self._redraw()

    def clear(self):
        self.data.clear()
        self._redraw()

    def update(self, sh, live):
        rs = sh.get("run_seq")
        if rs != self.run_seq:
            self.run_seq = rs
            self.data.clear()                       # a new run starts a new graph
        if live and not self.paused:
            now = sh.get("run_time")                # simulated time: pause / slow motion safe
            if self.data and now <= self.data[-1][0]:
                return                              # paused: nothing new
            ll, lr = sh.get("line")
            sonar = sh.get("sonar_cm") if sh.get("sonar_active") else None
            if sonar is not None and (sonar < R.SONAR_MIN_CM or sonar >= R.SONAR_MAX_CM):
                sonar = -1.0                         # no reading
            ml, mr = sh.get("motors")
            wl, wr = sh.get("wheel_v")
            pct = 100.0 / R.CM_PER_S_AT_100
            self.data.append((now, ll, lr, sonar, ml, mr, wl * pct, wr * pct))
            wall = time.time()
            if wall - self._last_draw > 0.05:
                self._last_draw = wall
                self._redraw()

    # --- drawing ------------------------------------------------------------------------
    def _redraw(self):
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 200)
        left, right, gap = 58, 14, 26
        ph = (h - 3 * gap - 34) / 3.0
        span = self.span.get()
        t_end = max(float(span), self.data[-1][0]) if self.data else float(span)
        t0 = t_end - span
        pts = [d for d in self.data if d[0] >= t0 - 0.1]
        x_of = lambda t: left + (t - t0) / span * (w - left - right)       # noqa: E731

        def panel(i, title, lo, hi, ticks, unit=""):
            y0 = gap + i * (ph + gap)
            y1 = y0 + ph
            c.create_rectangle(left, y0, w - right, y1, outline="#3A424D", fill="#20262C")
            c.create_text(left, y0 - 4, text=title, anchor="sw", fill=TEXT, font=("Segoe UI", 9, "bold"))
            for v in ticks:
                yy = y1 - (v - lo) / (hi - lo) * ph
                c.create_line(left, yy, w - right, yy, fill="#2C333B")
                c.create_text(left - 6, yy, text=f"{v:g}{unit}", anchor="e", fill=MUTED,
                              font=("Segoe UI", 8))
            return lambda v: y1 - (max(lo, min(hi, v)) - lo) / (hi - lo) * ph

        def trace(points, colour, dash=None, step=False):
            for seg in points:
                if len(seg) < 2:
                    continue
                coords = []
                for k, (x, y) in enumerate(seg):
                    if step and k:
                        coords.extend((x, coords[-1]))
                    coords.extend((x, y))
                c.create_line(*coords, fill=colour, width=2, dash=dash)

        # 1. line sensors: left in the upper band, right in the lower band
        yl = panel(0, "Line sensors   (0 = black line, 1 = white)", 0, 1, ())
        y0 = gap
        for label, band, colour, idx in (("L", 0.0, LEFT_C, 1), ("R", 0.5, RIGHT_C, 2)):
            top_y = y0 + band * ph + 6
            bot_y = y0 + (band + 0.5) * ph - 6
            c.create_text(left - 6, (top_y + bot_y) / 2, text=label, fill=colour, anchor="e",
                          font=("Segoe UI", 9, "bold"))
            c.create_text(left + 4, top_y, text="1", fill=MUTED, anchor="nw", font=("Segoe UI", 7))
            c.create_text(left + 4, bot_y, text="0", fill=MUTED, anchor="sw", font=("Segoe UI", 7))
            seg = [(x_of(d[0]), bot_y if d[idx] == 0 else top_y) for d in pts]
            trace([seg], colour, step=True)
        del yl

        # 2. sonar
        vals = [d[3] for d in pts if d[3] is not None and d[3] >= 0]
        hi = 50
        while vals and max(vals) > hi and hi < 400:
            hi *= 2
        ys = panel(1, "Ultrasonic distance (cm)   gaps = no reading", 0, hi,
                   [hi * k / 4 for k in range(5)])
        segs, cur = [], []
        for d in pts:
            if d[3] is None or d[3] < 0:
                if cur:
                    segs.append(cur)
                cur = []
            else:
                cur.append((x_of(d[0]), ys(d[3])))
        segs.append(cur)
        trace(segs, "#A371F7")
        if not any(d[3] is not None for d in pts):
            c.create_text(w / 2, gap + ph + gap + ph / 2, text="(the program has not used the sonar)",
                          fill=MUTED, font=("Segoe UI", 9))

        # 3. motors: code (solid) and real wheel speed (dashed)
        ym = panel(2, "Motors (%):  solid = speed in your code,  dashed = real wheel speed",
                   -100, 100, (-100, -50, 0, 50, 100))
        for idx, colour, dash in ((4, LEFT_C, None), (5, RIGHT_C, None), (6, LEFT_C, (4, 3)),
                                  (7, RIGHT_C, (4, 3))):
            trace([[(x_of(d[0]), ym(d[idx])) for d in pts]], colour, dash=dash,
                  step=idx in (4, 5))
        # time axis + legend
        yb = h - 10
        for k in range(span + 1):
            if span > 10 and k % 5:
                continue
            x = x_of(t0 + k)
            c.create_text(x, yb, text=f"{t0 + k:.0f}s", fill=MUTED, font=("Segoe UI", 8))
        c.create_text(w - right, 8, anchor="ne", fill=MUTED, font=("Segoe UI", 8),
                      text="blue = left wheel/sensor   orange = right" +
                           ("   (paused)" if self.paused else ""))


# =========================================================================================
# Radio console: see what the program sends, send messages to it
# =========================================================================================
HEADER = b"\x01\x00\x01"


def describe(data):
    """A radio message as text: strings from radio.send() in quotes, otherwise bytes."""
    if data[:3] == HEADER:
        try:
            return repr(data[3:].decode("utf-8"))
        except UnicodeDecodeError:
            pass
    return repr(bytes(data))


class RadioWindow:
    def __init__(self, root, send_cb):
        self.send_cb = send_cb
        top = self.top = tk.Toplevel(root)
        top.title("Radio console")
        top.configure(bg=PANEL_BG)
        top.geometry("600x460")
        top.minsize(460, 320)
        self.status = tk.Label(top, text="", bg=PANEL_BG, fg=TEXT, anchor="w",
                               font=("Segoe UI", 10, "bold"))
        self.status.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(top, text="Messages your program sends (radio.send / send_bytes) and messages "
                           "it receives.", bg=PANEL_BG, fg=MUTED, anchor="w").pack(fill="x", padx=8)
        self.log = tk.Listbox(top, bg=FIELD_BG, fg=TEXT, relief="flat", font=("Consolas", 9),
                              activestyle="none")
        self.log.pack(fill="both", expand=True, padx=8, pady=4)
        f = tk.Frame(top, bg=PANEL_BG)
        f.pack(fill="x", padx=8, pady=(2, 8))
        tk.Label(f, text="Send to the robot:", bg=PANEL_BG, fg=MUTED).grid(row=0, column=0, sticky="w")
        self.entry = tk.Entry(f, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
                              font=("Consolas", 10))
        self.entry.grid(row=0, column=1, columnspan=5, sticky="we", padx=6)
        self.entry.bind("<Return>", lambda e: self._send())
        _btn(f, "Send", self._send).grid(row=0, column=6)
        self.as_bytes = tk.BooleanVar(value=False)
        tk.Checkbutton(f, text="as bytes", variable=self.as_bytes, bg=PANEL_BG,
                       fg=TEXT, selectcolor=FIELD_BG, activebackground=PANEL_BG,
                       activeforeground=TEXT).grid(row=1, column=1, sticky="w", pady=(4, 0))
        tk.Label(f, text="group", bg=PANEL_BG, fg=MUTED).grid(row=1, column=2, sticky="e")
        self.group = tk.Spinbox(f, from_=0, to=255, width=4, bg=FIELD_BG, fg=TEXT,
                                buttonbackground="#33404D", relief="flat")
        self.group.grid(row=1, column=3, sticky="w")
        tk.Label(f, text="channel", bg=PANEL_BG, fg=MUTED).grid(row=1, column=4, sticky="e")
        self.channel = tk.Spinbox(f, from_=0, to=83, width=4, bg=FIELD_BG, fg=TEXT,
                                  buttonbackground="#33404D", relief="flat")
        self.channel.grid(row=1, column=5, sticky="w")
        self._set_spin(self.group, 0)
        self._set_spin(self.channel, 7)
        self.match = tk.BooleanVar(value=True)
        tk.Checkbutton(f, text="same as the robot", variable=self.match, bg=PANEL_BG, fg=TEXT,
                       selectcolor=FIELD_BG, activebackground=PANEL_BG,
                       activeforeground=TEXT).grid(row=1, column=6, sticky="w", pady=(4, 0))
        f.columnconfigure(1, weight=1)
        self.msg = tk.Label(top, text="", bg=PANEL_BG, fg=ERR, anchor="w")
        self.msg.pack(fill="x", padx=8, pady=(0, 6))

    @staticmethod
    def _set_spin(sp, v):
        sp.delete(0, "end")
        sp.insert(0, str(v))

    def alive(self):
        try:
            return bool(self.top.winfo_exists())
        except tk.TclError:
            return False

    def lift(self):
        self.top.deiconify()
        self.top.lift()

    def add(self, text, colour=TEXT):
        self.log.insert("end", text)
        self.log.itemconfigure("end", foreground=colour)
        if self.log.size() > 500:
            self.log.delete(0, 99)
        self.log.see("end")

    def _send(self):
        raw = self.entry.get()
        try:
            group, channel = int(self.group.get()), int(self.channel.get())
            if not (0 <= group <= 255 and 0 <= channel <= 83):
                raise ValueError
        except ValueError:
            self.msg.configure(text="group 0-255, channel 0-83")
            return
        if self.as_bytes.get():
            try:
                data = bytes(int(v, 0) for v in raw.replace(",", " ").split())
            except ValueError:
                self.msg.configure(text="bytes: numbers 0-255 separated by commas")
                return
        else:
            data = HEADER + raw.encode("utf-8")
        self.msg.configure(text="")
        self.send_cb(data, group, channel)
        self.add(f"to robot   g{group:<3} ch{channel:<2}  {describe(data)}", ACCENT)

    def update(self, sh, has_prog):
        on = has_prog and sh.get("radio_on")
        g, ch = sh.get("radio_group"), sh.get("radio_channel")
        if on:
            self.status.configure(text=f"Robot radio ON   group {g}   channel {ch}", fg=OK)
            if self.match.get():
                if self.group.get() != str(g):
                    self._set_spin(self.group, g)
                if self.channel.get() != str(ch):
                    self._set_spin(self.channel, ch)
        else:
            self.status.configure(text="Robot radio is off (radio.on() turns it on)", fg=MUTED)
