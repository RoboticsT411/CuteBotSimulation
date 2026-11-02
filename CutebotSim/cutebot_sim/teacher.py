"""Teacher's dashboard for LAN competitions.

Run it on the teacher's PC (in PyCharm, or a terminal):

    python -m cutebot_sim.teacher

Students join from the "Race" tab of their simulator with the IP address shown at
the top of the dashboard.  Only the dashboard can start a race.

Modes
    Time trial    every student drives their own copy of the course (robots do not
                  meet); students can choose to see the other robots as ghosts.
    Shared arena  all robots are in the same arena: they see and bump into each
                  other, and radio messages reach every robot on the same group/channel.
"""

import csv
import json
import math
import os
import socket
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import maps, net, robot as R

BG = "#1F2328"
PANEL_BG = "#262B31"
FIELD_BG = "#1B1F24"
TEXT = "#E6E8EA"
MUTED = "#9AA3AD"
ACCENT = "#4FB3FF"
OK = "#3FB950"
ERR = "#FF7B72"
WARN = "#D29922"
PANEL_W = 420
ZONE_COLOURS = {"start": "#2EA043", "check": "#1F6FEB", "finish": "#DA3633"}
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Student:
    def __init__(self, cid, name, colour, addr):
        self.id = cid
        self.name = name
        self.colour = colour
        self.addr = addr
        self.pose = None             # user frame x, y, angle
        self.status = "joined"
        self.time = None
        self.cp = 0
        self.bumps = 0
        self.best = None             # (total, time, penalty)
        self.last = ""
        self.tries = 0
        self.results = []            # (race, status, time, penalty, total)
        self.connected = True


class Dashboard:
    def __init__(self, root, port=net.PORT):
        self.root = root
        self.port = port
        try:
            self.server = net.Server(port, name=f"Cutebot dashboard ({socket.gethostname()})")
        except OSError as e:
            messagebox.showerror("Dashboard", f"Cannot listen on port {port}:\n{e}\n\n"
                                 "Is another dashboard already running?")
            root.destroy()
            raise SystemExit(1)
        self.students = {}           # id -> Student (kept after they leave, for results)
        self.world = maps.get_map(0)
        self.layout = self.world.to_layout()
        self.mode = tk.StringVar(value="trial")
        self.limit = tk.StringVar(value="120")
        self.penalty = tk.StringVar(value="5")
        self.race_id = 0
        self.race_state = "idle"     # idle, armed, counting, running
        self.t_go = 0.0
        self._last_robots = 0.0
        self._last_table = 0.0
        self._robot_items = {}

        root.title("Cutebot competition - teacher's dashboard")
        root.configure(bg=BG)
        root.geometry("1280x800")
        root.minsize(1000, 640)
        panel = tk.Frame(root, bg=PANEL_BG, width=PANEL_W)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)
        left = tk.Frame(root, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        self.banner = tk.Label(left, text="", bg=BG, fg=TEXT, font=("Segoe UI", 20, "bold"))
        self.banner.pack(fill="x", pady=(8, 0))
        self.canvas = tk.Canvas(left, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self._build_panel(panel)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._tick()

    # =====================================================================================
    # panel
    # =====================================================================================
    def _btn(self, parent, text, cmd, **kw):
        return tk.Button(parent, text=text, command=cmd, bg=kw.pop("bg", "#33404D"), fg=TEXT,
                         activebackground="#40505F", activeforeground=TEXT, relief="flat",
                         padx=8, pady=3, **kw)

    def _label(self, parent, text, **kw):
        return tk.Label(parent, text=text, bg=PANEL_BG, fg=kw.pop("fg", MUTED), anchor="w",
                        justify="left", **kw)

    def _build_panel(self, p):
        ips = net.local_ips()
        self._label(p, "Students join with (Race tab -> Teacher IP):").pack(fill="x", padx=10,
                                                                           pady=(10, 0))
        self._label(p, "   ".join(ips) + ("" if self.port == net.PORT else f"  port {self.port}"),
                    fg=ACCENT, font=("Consolas", 16, "bold")).pack(fill="x", padx=10)
        self._label(p, "(or they press Find)").pack(fill="x", padx=10)

        sep = lambda: tk.Frame(p, bg="#3A424D", height=1).pack(fill="x", padx=10, pady=6)  # noqa: E731
        sep()
        row = tk.Frame(p, bg=PANEL_BG)
        row.pack(fill="x", padx=10)
        self._label(row, "Course").pack(side="left")
        self.course_label = self._label(row, "", fg=TEXT, font=("Segoe UI", 10, "bold"))
        self.course_label.pack(side="left", padx=6)
        row = tk.Frame(p, bg=PANEL_BG)
        row.pack(fill="x", padx=10, pady=(4, 0))
        self._btn(row, "Open layout...", self.open_layout).pack(side="left")
        self.preset = ttk.Combobox(row, values=maps.MAP_NAMES, state="readonly", width=18)
        self.preset.pack(side="left", padx=6)
        self.preset.bind("<<ComboboxSelected>>", lambda e: self.use_preset())
        self._label(p, "Tip: design the course in the simulator (draw start, checkpoints\n"
                       "and finish in its Race tab), save the layout, open it here.",
                    font=("Segoe UI", 8)).pack(fill="x", padx=10, pady=(2, 0))
        sep()
        row = tk.Frame(p, bg=PANEL_BG)
        row.pack(fill="x", padx=10)
        self._label(row, "Mode").pack(side="left")
        for value, text in (("trial", "Time trial"), ("shared", "Shared arena")):
            tk.Radiobutton(row, text=text, value=value, variable=self.mode, command=self._mode_changed,
                           bg=PANEL_BG, fg=TEXT, selectcolor=FIELD_BG, activebackground=PANEL_BG,
                           activeforeground=TEXT).pack(side="left", padx=4)
        row = tk.Frame(p, bg=PANEL_BG)
        row.pack(fill="x", padx=10, pady=(4, 0))
        self._label(row, "Time limit").pack(side="left")
        tk.Spinbox(row, from_=10, to=900, increment=10, width=5, textvariable=self.limit,
                   bg=FIELD_BG, fg=TEXT, buttonbackground="#33404D", relief="flat").pack(side="left", padx=4)
        self._label(row, "s     Penalty per bump").pack(side="left")
        tk.Spinbox(row, from_=0, to=60, width=4, textvariable=self.penalty, bg=FIELD_BG, fg=TEXT,
                   buttonbackground="#33404D", relief="flat").pack(side="left", padx=4)
        self._label(row, "s").pack(side="left")
        sep()
        row = tk.Frame(p, bg=PANEL_BG)
        row.pack(fill="x", padx=10)
        self.ready_btn = self._btn(row, "1  Get ready", self.get_ready, bg="#1F6FEB")
        self.ready_btn.pack(side="left", fill="x", expand=True)
        self.go_btn = self._btn(row, "2  GO!", self.go, bg="#2EA043")
        self.go_btn.pack(side="left", fill="x", expand=True, padx=6)
        self._btn(row, "Stop", self.stop, bg="#DA3633").pack(side="left", fill="x", expand=True)
        self.race_label = self._label(p, "No race yet", fg=TEXT, font=("Segoe UI", 10, "bold"))
        self.race_label.pack(fill="x", padx=10, pady=(4, 0))
        sep()
        self._label(p, "Leaderboard (best total = time + penalties)").pack(fill="x", padx=10)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Board.Treeview", background=FIELD_BG, fieldbackground=FIELD_BG,
                        foreground=TEXT, rowheight=22, borderwidth=0)
        style.configure("Board.Treeview.Heading", background="#33404D", foreground=TEXT)
        cols = ("rank", "name", "best", "now", "tries")
        self.table = ttk.Treeview(p, columns=cols, show="headings", height=10, style="Board.Treeview")
        for col, text, wdt in (("rank", "#", 30), ("name", "Name", 110), ("best", "Best", 80),
                               ("now", "Now / last", 120), ("tries", "Runs", 46)):
            self.table.heading(col, text=text)
            self.table.column(col, width=wdt, anchor="w" if col in ("name", "now") else "center")
        self.table.pack(fill="both", expand=True, padx=10, pady=(2, 4))
        row = tk.Frame(p, bg=PANEL_BG)
        row.pack(fill="x", padx=10)
        self._btn(row, "Save results (CSV)", self.save_csv).pack(side="left")
        self._btn(row, "Reset scores", self.reset_scores).pack(side="left", padx=6)
        self.log = tk.Listbox(p, height=6, bg=FIELD_BG, fg=MUTED, relief="flat",
                              font=("Consolas", 9), activestyle="none")
        self.log.pack(fill="x", padx=10, pady=(6, 10))
        self._set_course(self.world.to_layout())

    def note(self, text):
        self.log.insert("end", time.strftime("%H:%M:%S ") + text)
        if self.log.size() > 200:
            self.log.delete(0, 49)
        self.log.see("end")

    # =====================================================================================
    # course and mode
    # =====================================================================================
    def _set_course(self, layout):
        self.layout = layout
        self.world = maps.Map.from_layout(layout)
        self.course_label.configure(text=self.world.name)
        self.server.broadcast({"t": "layout", "layout": layout})
        self.draw()

    def open_layout(self):
        if self.race_state != "idle":
            messagebox.showinfo("Course", "Stop the race first.", parent=self.root)
            return
        path = filedialog.askopenfilename(parent=self.root, title="Open a course layout",
                                          initialdir=os.path.join(PROJECT_DIR, "layouts"),
                                          filetypes=[("Layout", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                layout = json.load(fh)
            maps.Map.from_layout(layout)
        except (OSError, ValueError, KeyError, TypeError) as e:
            messagebox.showerror("Course", f"Could not open that layout:\n{e}", parent=self.root)
            return
        if not layout.get("name") or layout.get("name") == "Custom layout":
            layout["name"] = os.path.splitext(os.path.basename(path))[0]
        self._set_course(layout)
        self.note(f"course: {layout['name']}")

    def use_preset(self):
        if self.race_state != "idle":
            return
        name = self.preset.get()
        if name in maps.MAP_NAMES:
            m = maps.get_map(maps.MAP_NAMES.index(name))
            self._set_course(m.to_layout())
            self.note(f"course: {m.name}")

    def _mode_changed(self):
        if self.race_state != "idle":
            messagebox.showinfo("Mode", "The mode changes after this race.", parent=self.root)
        self.server.broadcast({"t": "mode", "mode": self.mode.get()})
        self.note(f"mode: {self.mode.get()}")
        self.draw()

    def _numbers(self):
        try:
            limit = max(5.0, float(self.limit.get()))
        except ValueError:
            limit = 120.0
        try:
            pen = max(0.0, float(self.penalty.get()))
        except ValueError:
            pen = 5.0
        return limit, pen

    # =====================================================================================
    # races
    # =====================================================================================
    def _start_slots(self, n):
        """Start positions (user frame) for a shared arena: spread out so robots don't overlap."""
        W, H = self.world.width, self.world.height
        sx, sy, sh = self.world.start
        angle = -sh
        start = next((z for z in self.world.zones if z[0] == "start"), None)
        gap = R.ROBOT_LENGTH_CM + 4.0
        slots = []
        if start is not None:
            _k, x0, y0, x1, y1 = start
            cols = max(1, int((x1 - x0) // gap))
            rows = max(1, int((y1 - y0) // gap))
            for i in range(n):
                cx = x0 + gap / 2 + (i % cols) * gap
                cy = y0 + gap / 2 + ((i // cols) % rows) * gap
                slots.append((min(cx, x1), H - min(cy, y1), angle))
        else:
            # along the line through the start, sideways to the start heading
            hr = math.radians(sh)
            px, py = -math.sin(hr), math.cos(hr)
            for i in range(n):
                k = (i + 1) // 2 * (1 if i % 2 else -1)
                x = min(max(sx + px * k * gap, 5.0), W - 5.0)
                y = min(max(sy + py * k * gap, 5.0), H - 5.0)
                slots.append((x, H - y, angle))
        return [(round(x, 2), round(y, 2), round(a, 1)) for x, y, a in slots]

    def _arm_message(self, slot=None):
        limit, pen = self._numbers()
        m = {"t": "arm", "race": self.race_id, "limit": limit, "penalty": pen}
        if slot is not None:
            m["start"] = slot
        return m

    def get_ready(self):
        if self.race_state in ("counting", "running"):
            messagebox.showinfo("Race", "A race is running - press Stop first.", parent=self.root)
            return
        live = [s for s in self.students.values() if s.connected]
        if not live:
            messagebox.showinfo("Race", "No students are connected yet.", parent=self.root)
            return
        self.race_id += 1
        self.race_state = "armed"
        slots = self._start_slots(len(live)) if self.mode.get() == "shared" else [None] * len(live)
        for s, slot in zip(live, slots):
            s.status = "armed"
            s.time = None
            s.cp = 0
            self.server.send(s.id, self._arm_message(slot))
        self.banner.configure(text=f"Race {self.race_id}: get ready - run your programs", fg=WARN)
        self.note(f"race {self.race_id}: armed ({len(live)} robots)")

    def go(self):
        if self.race_state != "armed":
            messagebox.showinfo("Race", "Press 'Get ready' first.", parent=self.root)
            return
        self.race_state = "counting"
        for k, n in enumerate((3, 2, 1)):
            self.root.after(k * 1000, lambda n=n: self._count(n))
        self.root.after(3000, self._go_now)

    def _count(self, n):
        if self.race_state != "counting":
            return
        self.server.broadcast({"t": "count", "n": n})
        self.banner.configure(text=f"{n}", fg=WARN)

    def _go_now(self):
        if self.race_state != "counting":
            return
        self.race_state = "running"
        self.t_go = time.time()
        self.server.broadcast({"t": "go", "race": self.race_id})
        self.banner.configure(text="GO!", fg=OK)
        self.note(f"race {self.race_id}: GO")

    def stop(self):
        if self.race_state == "idle":
            return
        self.server.broadcast({"t": "stop", "race": self.race_id})
        self.race_state = "idle"
        self.banner.configure(text=f"Race {self.race_id} stopped", fg=MUTED)
        self.note(f"race {self.race_id}: stopped")

    # =====================================================================================
    # messages from students
    # =====================================================================================
    def _handle(self, cid, m):
        t = m.get("t")
        s = self.students.get(cid)
        if t == "hello":
            name = str(m.get("name", "student"))[:20] or "student"
            if any(o.name == name and o.connected for o in self.students.values()):
                name = f"{name} ({cid})"
            colour = net.COLOURS[(cid - 1) % len(net.COLOURS)]
            addr = getattr(self.server.clients.get(cid), "addr", "?")
            s = self.students[cid] = Student(cid, name, colour, addr)
            limit, pen = self._numbers()
            self.server.send(cid, {"t": "welcome", "id": cid, "name": name, "colour": colour,
                                   "mode": self.mode.get(), "layout": self.layout,
                                   "limit": limit, "penalty": pen})
            if self.race_state == "armed":
                slot = None
                if self.mode.get() == "shared":
                    n = sum(1 for o in self.students.values() if o.connected)
                    slot = self._start_slots(n)[-1]
                self.server.send(cid, self._arm_message(slot))
                s.status = "armed"
            self.note(f"{name} joined from {addr}")
        elif s is None:
            return
        elif t == "_closed":
            s.connected = False
            s.status = "left"
            s.pose = None
            self.note(f"{s.name} left")
        elif t == "state":
            try:
                s.pose = (float(m["x"]), float(m["y"]), float(m["angle"]))
            except (KeyError, TypeError, ValueError):
                pass
            st = m.get("status", "")
            if st in ("running", "armed", "finished", "dnf", "invalid", "idle"):
                if not (s.status in ("finished", "dnf", "invalid") and st == "idle"):
                    s.status = st
            s.time = m.get("time")
            s.cp = m.get("cp", 0)
            s.bumps = m.get("bumps", 0)
        elif t == "result":
            if m.get("race") != self.race_id:
                return
            st = m.get("status")
            total, tt, pen = m.get("total", 0.0), m.get("time", 0.0), m.get("penalty", 0.0)
            s.tries += 1
            s.results.append((self.race_id, st, tt, pen, total))
            s.status = st
            if st == "finished":
                s.last = f"{total:.2f} s"
                if s.best is None or total < s.best[0]:
                    s.best = (total, tt, pen)
                self.note(f"{s.name}: {total:.2f} s ({tt:.2f} + {pen:g})")
            else:
                s.last = "not finished" if st == "dnf" else "invalid"
                self.note(f"{s.name}: {s.last} ({m.get('reason', '')})")
        elif t == "radio" and self.mode.get() == "shared":
            out = {"t": "radio", "from": cid, "name": s.name, "g": m.get("g", 0),
                   "c": m.get("c", 7), "d": m.get("d", "")}
            self.server.broadcast(out, exclude=cid)

    # =====================================================================================
    # every 50 ms
    # =====================================================================================
    def _tick(self):
        for cid, m in self.server.poll():
            self._handle(cid, m)
        now = time.time()
        if now - self._last_robots >= 0.1:
            self._last_robots = now
            rows = [[s.id, s.name, s.colour, s.pose[0], s.pose[1], s.pose[2], s.status]
                    for s in self.students.values() if s.connected and s.pose is not None]
            self.server.broadcast({"t": "robots", "list": rows})
            self._draw_robots()
        if now - self._last_table >= 0.25:
            self._last_table = now
            self._update_table(now)
        self.root.after(50, self._tick)

    def _update_table(self, now):
        rows = sorted(self.students.values(),
                      key=lambda s: (s.best is None, s.best[0] if s.best else 0, s.name.lower()))
        self.table.delete(*self.table.get_children())
        rank = 0
        for s in rows:
            if s.best is not None:
                rank += 1
            if not s.connected:
                now_txt = "left"
            elif s.status == "running" and s.time is not None:
                now_txt = f"running {s.time:.1f} s  CP{s.cp}"
            elif s.status == "armed":
                now_txt = "ready"
            else:
                now_txt = s.last or s.status
            self.table.insert("", "end", values=(rank if s.best else "", s.name,
                                                 f"{s.best[0]:.2f}" if s.best else "-",
                                                 now_txt, s.tries))
        live = [s for s in self.students.values() if s.connected]
        if self.race_state == "running":
            done = sum(1 for s in live if s.status in ("finished", "dnf", "invalid"))
            limit, _pen = self._numbers()
            self.race_label.configure(text=f"Race {self.race_id} running  {now - self.t_go:5.1f} s   "
                                           f"{done}/{len(live)} done   (limit {limit:g} s)")
            if live and done == len(live):
                self.race_state = "idle"
                self.banner.configure(text=f"Race {self.race_id} finished", fg=ACCENT)
                self.note(f"race {self.race_id}: everyone done")
        elif self.race_state == "armed":
            ready = sum(1 for s in live if s.status == "armed")
            self.race_label.configure(text=f"Race {self.race_id} armed - {ready}/{len(live)} ready.  "
                                           "Press GO!")
        else:
            self.race_label.configure(text=f"{len(live)} student(s) connected.  "
                                           f"Mode: {'shared arena' if self.mode.get() == 'shared' else 'time trial'}")

    # =====================================================================================
    # drawing
    # =====================================================================================
    def _fit(self):
        c = self.canvas
        cw, ch = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        m = self.world
        self.scale = min((cw - 40) / m.width, (ch - 40) / m.height)
        self.ox = (cw - m.width * self.scale) / 2
        self.oy = (ch - m.height * self.scale) / 2

    def w2s(self, x, y):
        return self.ox + x * self.scale, self.oy + y * self.scale

    def draw(self):
        c = self.canvas
        c.delete("all")
        self._robot_items = {}
        self._fit()
        m, s = self.world, self.scale
        x0, y0 = self.w2s(0, 0)
        x1, y1 = self.w2s(m.width, m.height)
        c.create_rectangle(x0 - 6, y0 - 6, x1 + 6, y1 + 6, fill="#5A4632", outline="")
        c.create_rectangle(x0, y0, x1, y1, fill=m.colour, outline="")
        for g in range(10, int(m.width), 10):
            c.create_line(*self.w2s(g, 0), *self.w2s(g, m.height), fill="#D5D9D2")
        for g in range(10, int(m.height), 10):
            c.create_line(*self.w2s(0, m.height - g), *self.w2s(m.width, m.height - g), fill="#D5D9D2")
        for stroke in m.lines:
            pts = []
            for px, py in stroke:
                pts.extend(self.w2s(px, py))
            c.create_line(*pts, fill="#202020", width=max(1, m.line_width * s), capstyle="round",
                          joinstyle="round")
        for bx0, by0, bx1, by1 in m.obstacles:
            c.create_rectangle(*self.w2s(bx0, by0), *self.w2s(bx1, by1), fill="#B5834F",
                               outline="#6E4A27", width=2)
        n = 0
        for kind, zx0, zy0, zx1, zy1 in m.zones:
            col = ZONE_COLOURS[kind]
            label = {"start": "START", "finish": "FINISH"}.get(kind)
            if kind == "check":
                n += 1
                label = f"CP{n}"
            p, q = self.w2s(zx0, zy0), self.w2s(zx1, zy1)
            c.create_rectangle(*p, *q, outline=col, width=2, dash=(6, 3), fill=col, stipple="gray25")
            c.create_text((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, text=label, fill=col,
                          font=("Segoe UI", 10, "bold"))
        c.create_text(x0, y1 + 14, anchor="w", fill=MUTED, font=("Segoe UI", 9),
                      text=f"{m.name}   {m.width:g} x {m.height:g} cm")
        self._draw_robots()

    def _draw_robots(self):
        from .race import make_robot_items, place_robot_items

        c = self.canvas
        if not hasattr(self, "scale"):
            return
        H = self.world.height
        seen = set()
        for s in self.students.values():
            if not s.connected or s.pose is None:
                continue
            seen.add(s.id)
            items = self._robot_items.get(s.id)
            if items is None:
                items = self._robot_items[s.id] = make_robot_items(c, s.colour, s.name)
            ux, uy, ang = s.pose
            extra = {"finished": " \u2713", "dnf": " \u2717", "invalid": " \u2717"}.get(s.status, "")
            place_robot_items(c, items, self.w2s, ux, H - uy, -ang, s.name + extra)
        for cid in list(self._robot_items):
            if cid not in seen:
                for it in self._robot_items.pop(cid):
                    c.delete(it)

    # =====================================================================================
    # results
    # =====================================================================================
    def save_csv(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="Save results",
                                            defaultextension=".csv",
                                            initialfile=time.strftime("results_%Y-%m-%d_%H%M.csv"),
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["name", "best_total_s", "best_time_s", "best_penalty_s", "runs",
                        "race", "status", "time_s", "penalty_s", "total_s"])
            for s in sorted(self.students.values(), key=lambda s: s.name.lower()):
                best = s.best or ("", "", "")
                if not s.results:
                    w.writerow([s.name, *best, s.tries, "", "", "", "", ""])
                for r in s.results:
                    w.writerow([s.name, *best, s.tries, *r])
        self.note(f"results saved to {os.path.basename(path)}")

    def reset_scores(self):
        if not messagebox.askyesno("Reset", "Clear all results and best times?", parent=self.root):
            return
        for s in self.students.values():
            s.best, s.last, s.tries, s.results = None, "", 0, []
        self.students = {cid: s for cid, s in self.students.items() if s.connected}
        self.note("scores reset")

    def _close(self):
        if self.race_state != "idle":
            self.stop()
        self.server.close()
        self.root.after(150, self.root.destroy)


def main():
    port = net.PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    root = tk.Tk()
    Dashboard(root, port)
    root.mainloop()


if __name__ == "__main__":
    main()
