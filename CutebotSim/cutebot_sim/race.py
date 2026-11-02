"""Challenge mode (zones, timer, penalties, best times) and the student side of a
LAN competition.  Builds the window's "Race" tab.

Challenge mode
    Draw a start zone, checkpoints (taken in order) and a finish zone on the arena.
    With challenge mode on, the timer starts when your program starts (or at the
    teacher's GO in a competition) and stops when the robot reaches the finish after
    every checkpoint.  Each new bump into a wall, obstacle or robot adds a penalty.
    Moving the robot by hand during a run makes that run invalid.

Competition (LAN)
    Join the teacher's dashboard by IP address (or Find).  The teacher's course
    replaces yours (it is locked while you are connected), and only the teacher can
    start a race: "Get ready" restarts your program and makes it wait; "GO" starts
    everyone at the same moment.
"""

import json
import math
import time
import tkinter as tk
from tkinter import messagebox

from . import maps, net, robot as R, shared

PANEL_BG = "#262B31"
FIELD_BG = "#1B1F24"
TEXT = "#E6E8EA"
MUTED = "#9AA3AD"
ACCENT = "#4FB3FF"
OK = "#3FB950"
ERR = "#FF7B72"
WARN = "#D29922"

ZONE_STYLE = {"start": ("#2EA043", "START"), "check": ("#1F6FEB", "CP"),
              "finish": ("#DA3633", "FINISH")}
STATE_SEND_S = 0.1


def inside(zone, x, y):
    _k, x0, y0, x1, y1 = zone
    return x0 <= x <= x1 and y0 <= y <= y1


def fmt_time(t):
    return f"{t:.2f} s"


class Race:
    def __init__(self, app, f):
        self.app = app
        self.enabled = tk.BooleanVar(value=False)
        self.zone_kind = None
        self.state = "idle"          # idle, ready, armed, running, finished, dnf, invalid
        self.reason = ""
        self.t0 = 0.0
        self.t0_sim = 0.0
        self.result = None           # (time, penalty, total)
        self.cp = 0
        self.bumps0 = 0
        self.bumps = 0
        self.limit = 120.0
        self.penalty = 5.0
        self.best = {}               # course name -> [(total, time, bumps), ...]
        self._run_key = None
        self._still_since = None
        self._own_move = False
        self.countdown = None
        # LAN
        self.client = None
        self.my_id = None
        self.my_colour = None
        self.mode = "trial"
        self.race_id = None
        self.course = None           # teacher's layout (dict) while connected
        self._own_world = None
        self.others = {}             # id -> (name, colour, x, y, heading, status)  internal frame
        self._other_items = {}
        self._last_send = 0.0
        self._build(f)

    # =====================================================================================
    # UI
    # =====================================================================================
    def _build(self, f):
        a = self.app
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(6, 0))
        tk.Checkbutton(row, text="Challenge mode (timer, zones, score)", variable=self.enabled,
                       command=self._toggle, bg=PANEL_BG, fg=TEXT, selectcolor=FIELD_BG,
                       activebackground=PANEL_BG, activeforeground=TEXT,
                       font=("Segoe UI", 9, "bold")).pack(side="left")
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(3, 0))
        tk.Label(row, text="Draw zone:", bg=PANEL_BG, fg=MUTED).pack(side="left")
        for kind, label in (("start", "Start"), ("check", "Checkpoint"), ("finish", "Finish")):
            a._btn(row, label, lambda k=kind: self.start_zone_tool(k)).pack(side="left", padx=2)
        a._btn(row, "Clear", self.clear_zones).pack(side="left", padx=2)
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(3, 0))
        tk.Label(row, text="Time limit", bg=PANEL_BG, fg=MUTED).pack(side="left")
        self.limit_var = tk.StringVar(value="120")
        tk.Spinbox(row, from_=10, to=900, increment=10, width=4, textvariable=self.limit_var,
                   bg=FIELD_BG, fg=TEXT, buttonbackground="#33404D", relief="flat",
                   justify="right").pack(side="left", padx=2)
        tk.Label(row, text="s    Penalty per bump", bg=PANEL_BG, fg=MUTED).pack(side="left")
        self.pen_var = tk.StringVar(value="5")
        tk.Spinbox(row, from_=0, to=60, width=3, textvariable=self.pen_var, bg=FIELD_BG, fg=TEXT,
                   buttonbackground="#33404D", relief="flat", justify="right").pack(side="left", padx=2)
        tk.Label(row, text="s", bg=PANEL_BG, fg=MUTED).pack(side="left")
        self.status = tk.Label(f, text="", bg=PANEL_BG, fg=MUTED, font=("Consolas", 10, "bold"),
                               anchor="w", justify="left")
        self.status.pack(fill="x", padx=6, pady=(4, 0))
        self.best_list = tk.Listbox(f, height=2, bg=FIELD_BG, fg=TEXT, relief="flat",
                                    font=("Consolas", 9), activestyle="none")
        self.best_list.pack(fill="x", padx=6, pady=(2, 2))

        tk.Frame(f, bg="#3A424D", height=1).pack(fill="x", padx=6, pady=3)
        tk.Label(f, text="Competition on the local network", bg=PANEL_BG, fg=TEXT, anchor="w",
                 font=("Segoe UI", 9, "bold")).pack(fill="x", padx=6)
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(2, 0))
        tk.Label(row, text="Teacher's IP", bg=PANEL_BG, fg=MUTED, width=10, anchor="w").pack(side="left")
        self.ip = tk.Entry(row, width=15, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT, relief="flat")
        self.ip.pack(side="left", padx=4)
        a._btn(row, "Find", self.find).pack(side="left")
        row = tk.Frame(f, bg=PANEL_BG)
        row.pack(fill="x", padx=6, pady=(3, 0))
        tk.Label(row, text="Your name", bg=PANEL_BG, fg=MUTED, width=10, anchor="w").pack(side="left")
        self.name = tk.Entry(row, width=15, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT, relief="flat")
        self.name.pack(side="left", padx=4)
        self.join_btn = a._btn(row, "Join", self.join_or_leave)
        self.join_btn.pack(side="left")
        self.show_others = tk.BooleanVar(value=True)
        tk.Checkbutton(f, text="Show the other robots", variable=self.show_others,
                       command=self._redraw_others, bg=PANEL_BG, fg=TEXT, selectcolor=FIELD_BG,
                       activebackground=PANEL_BG, activeforeground=TEXT,
                       anchor="w").pack(fill="x", padx=6)
        self.net_msg = tk.Label(f, text="Not connected. Only the teacher's address is needed: "
                                        "the teacher's dashboard links everyone.",
                                bg=PANEL_BG, fg=MUTED, anchor="w", justify="left", wraplength=330)
        self.net_msg.pack(fill="x", padx=6)
        self.others_label = tk.Label(f, text="", bg=PANEL_BG, fg=TEXT, anchor="w", justify="left",
                                     wraplength=330)
        self.others_label.pack(fill="x", padx=6, pady=(2, 6))

    def settings(self):
        return {"challenge": bool(self.enabled.get()), "limit": self.limit_var.get(),
                "penalty": self.pen_var.get(), "teacher_ip": self.ip.get().strip(),
                "name": self.name.get().strip(),
                "best_times": {k: v[:5] for k, v in self.best.items()}}

    def load_settings(self, d):
        if not isinstance(d, dict):
            return
        self.enabled.set(bool(d.get("challenge", False)))
        self.limit_var.set(str(d.get("limit", "120")))
        self.pen_var.set(str(d.get("penalty", "5")))
        self.ip.delete(0, "end")
        self.ip.insert(0, str(d.get("teacher_ip", "")))
        self.name.delete(0, "end")
        self.name.insert(0, str(d.get("name", "")))
        bt = d.get("best_times", {})
        if isinstance(bt, dict):
            self.best = {str(k): [tuple(r) for r in v if len(r) == 3] for k, v in bt.items()
                         if isinstance(v, list)}
        self._show_best()

    def _toggle(self):
        if not self.enabled.get() and self.race_id is None:
            self.state = "idle"
        self.app._schedule_save()
        self.app._draw_map()

    def _numbers(self):
        try:
            self.limit = max(5.0, float(self.limit_var.get()))
        except ValueError:
            self.limit = 120.0
        try:
            self.penalty = max(0.0, float(self.pen_var.get()))
        except ValueError:
            self.penalty = 5.0

    # =====================================================================================
    # zones
    # =====================================================================================
    def start_zone_tool(self, kind):
        if self.locked():
            self.app.coord_label.configure(text="The course is set by the teacher")
            return
        self.zone_kind = kind
        self.app.mode.set("zone")
        self.app._on_mode()
        names = {"start": "start zone", "check": "checkpoint", "finish": "finish zone"}
        self.app.hint.configure(text=f"Drag a rectangle for the {names[kind]}.  "
                                     "Right-click a zone to delete it.  Esc = done.")

    def add_zone(self, kind, box):
        m = self.app.world
        if kind in ("start", "finish"):
            m.zones = [z for z in m.zones if z[0] != kind]
        m.zones.append((kind,) + tuple(box))
        self.app._world_changed()

    def delete_zone_at(self, x, y):
        m = self.app.world
        for i in range(len(m.zones) - 1, -1, -1):
            if inside(m.zones[i], x, y):
                del m.zones[i]
                self.app._world_changed()
                return True
        return False

    def clear_zones(self):
        if self.locked():
            return
        if self.app.world.zones and messagebox.askyesno("Clear zones", "Remove all zones?",
                                                        parent=self.app.root):
            self.app.world.zones = []
            self.app._world_changed()

    def checkpoints(self):
        return [z for z in self.app.world.zones if z[0] == "check"]

    def finish_zone(self):
        return next((z for z in self.app.world.zones if z[0] == "finish"), None)

    def draw_zones(self, c):
        a = self.app
        n = 0
        for z in a.world.zones:
            kind, x0, y0, x1, y1 = z
            colour, label = ZONE_STYLE[kind]
            p, q = a.w2s(x0, y0), a.w2s(x1, y1)
            if kind == "check":
                n += 1
                label = f"CP{n}"
                done = self.state in ("running", "finished") and n <= self.cp
                if done:
                    colour = "#3FB950"
            c.create_rectangle(*p, *q, fill=colour, stipple="gray25", outline=colour, width=2,
                               dash=(6, 3), tags="zones")
            if kind == "finish":                       # chequered flag strip
                k = max(4.0, (q[0] - p[0]) / 8)
                xs = p[0]
                i = 0
                while xs < q[0] - 0.5:
                    c.create_rectangle(xs, p[1], min(xs + k, q[0]), p[1] + 6,
                                       fill="#111111" if i % 2 else "#FFFFFF", outline="",
                                       tags="zones")
                    xs += k
                    i += 1
            c.create_text((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, text=label, fill=colour,
                          font=("Segoe UI", 9, "bold"), tags="zones")

    # =====================================================================================
    # the timer
    # =====================================================================================
    def active(self):
        return bool(self.enabled.get()) or self.race_id is not None

    def hand_moved(self):
        """The user dragged/placed the robot."""
        if self._own_move:
            return
        if self.state == "running":
            self._end("invalid", "robot moved by hand")

    def _start_attempt(self, now):
        self._numbers()
        self.state = "running"
        self.t0 = now
        self.t0_sim = 0.0 if self.race_id is None else self.app.sh.get("run_time")
        self.cp = 0
        self.bumps0 = self.app.sh.get("bumps")
        self.bumps = 0
        self.result = None
        self._still_since = None
        self.app._draw_map()

    def _elapsed(self, now):
        """Race time.  Practice runs use the simulated clock (slow motion and pause do not
        count); a teacher's race uses the real clock from GO."""
        if self.race_id is not None:
            return now - self.t0
        return max(0.0, self.app.sh.get("run_time") - self.t0_sim)

    def _end(self, state, reason=""):
        self.state = state
        self.reason = reason
        now = time.time()
        t = self._elapsed(now)
        pen = self.bumps * self.penalty
        self.result = (t, pen, t + pen)
        if state == "finished":
            course = self.app.world.name or "Custom"
            lst = self.best.setdefault(course, [])
            lst.append((round(t + pen, 2), round(t, 2), self.bumps))
            lst.sort()
            del lst[5:]
            self._show_best()
            self.app._schedule_save()
        if self.client is not None and self.race_id is not None:
            self.client.send({"t": "result", "race": self.race_id, "status": state,
                              "reason": reason, "time": round(t, 3), "penalty": pen,
                              "total": round(t + pen, 3), "cp": self.cp,
                              "bumps": self.bumps})
        self.app._draw_map()

    def _show_best(self):
        self.best_list.delete(0, "end")
        course = self.app.world.name or "Custom"
        rows = self.best.get(course, [])
        if not rows:
            self.best_list.insert("end", " Best times on this course will appear here")
            self.best_list.itemconfigure(0, foreground=MUTED)
        for i, (total, t, b) in enumerate(rows, 1):
            self.best_list.insert("end", f" {i}. {total:7.2f} s   ({t:.2f} s + {b} bump(s))")

    def frame(self, now, pose, has_prog, live, prog_state, wheel_v):
        """Called every frame by the window."""
        sh = self.app.sh
        self._net_frame(now, pose)
        if not self.active():
            self.status.configure(text="Challenge mode is off - no timer.", fg=MUTED)
            return
        key = (sh.get("owner_gen"), sh.get("run_seq"))
        new_run = key != self._run_key and has_prog
        if new_run:
            self._run_key = key
        if self.race_id is None and new_run and self.state != "armed":
            self._start_attempt(now)                   # practice: timer starts with the program
        x, y = pose[0], pose[1]
        if self.state == "running":
            b = sh.get("bumps")
            if b < self.bumps0:
                self.bumps0 = 0
            self.bumps = b - self.bumps0
            cps = self.checkpoints()
            if self.cp < len(cps) and inside(cps[self.cp], x, y):
                self.cp += 1
                self.app._draw_map()
            fin = self.finish_zone()
            if fin is not None and self.cp >= len(cps) and inside(fin, x, y):
                self._end("finished")
            elif self._elapsed(now) > self.limit:
                self._end("dnf", "time limit")
            elif prog_state in (shared.STATE_FINISHED, shared.STATE_ERROR) and has_prog:
                if max(abs(v) for v in wheel_v) < 0.2:
                    if self._still_since is None:
                        self._still_since = now
                    elif now - self._still_since > 1.0:
                        self._end("dnf", "program ended")
                else:
                    self._still_since = None
        self._show_status(now)

    def _show_status(self, now):
        cps = len(self.checkpoints())
        fin = self.finish_zone()
        if self.countdown is not None:
            text, colour = f"   {self.countdown} ...", WARN
        elif self.state == "armed":
            text, colour = "READY - run your program now.\nIt waits for the teacher's GO.", WARN
        elif self.state == "running":
            t = self._elapsed(now)
            text = (f"Time {t:7.2f} s   checkpoints {self.cp}/{cps}\n"
                    f"Bumps {self.bumps}  (+{self.bumps * self.penalty:g} s)")
            colour = OK
            if fin is None:
                text += "\nAdd a finish zone to stop the timer"
                colour = WARN
        elif self.state == "finished" and self.result:
            t, pen, total = self.result
            text = f"FINISHED  {total:.2f} s\n{t:.2f} s + {pen:g} s penalty"
            colour = ACCENT
        elif self.state in ("dnf", "invalid") and self.result:
            word = "NOT FINISHED" if self.state == "dnf" else "INVALID RUN"
            text = f"{word} ({self.reason})\ncheckpoints {self.cp}/{cps}   bumps {self.bumps}"
            colour = ERR
        else:
            text = ("Run your program to start the timer." if fin is not None else
                    "Draw a finish zone (and checkpoints),\nthen run your program.")
            colour = MUTED
        self.status.configure(text=text, fg=colour)

    # =====================================================================================
    # LAN
    # =====================================================================================
    def locked(self):
        return self.client is not None

    def find(self):
        self.net_msg.configure(text="Looking for the teacher's dashboard...", fg=MUTED)
        self.app.root.update_idletasks()
        found = net.discover()
        if not found:
            self.net_msg.configure(text="No dashboard found. Type the teacher's IP address "
                                        "(shown on the dashboard).", fg=ERR)
            return
        ip, name, _port = found[0]
        self.ip.delete(0, "end")
        self.ip.insert(0, ip)
        self.net_msg.configure(text=f"Found {name} at {ip}" +
                               (f" (+{len(found) - 1} more)" if len(found) > 1 else ""), fg=OK)

    def join_or_leave(self):
        if self.client is not None:
            self.leave("You left the competition.")
            return
        host = self.ip.get().strip()
        name = self.name.get().strip()
        if not host or not name:
            self.net_msg.configure(text="Enter the teacher's IP address and your name.", fg=ERR)
            return
        port = net.PORT
        if ":" in host:
            host, p = host.rsplit(":", 1)
            try:
                port = int(p)
            except ValueError:
                pass
        try:
            self.client = net.Client(host, name, port)
        except OSError as e:
            self.net_msg.configure(text=f"Could not connect: {e}", fg=ERR)
            return
        self.join_btn.configure(text="Leave")
        self.net_msg.configure(text="Connecting...", fg=MUTED)
        self.app._schedule_save()

    def leave(self, text, colour=MUTED):
        if self.client is not None:
            self.client.close()
        self.client = None
        self.my_id = None
        self.race_id = None
        self.countdown = None
        self.app.sh.set("hold", 0)
        self.app.sh.set("others_n", 0)
        self.others = {}
        self.others_label.configure(text="")
        self._redraw_others()
        if self._own_world is not None:
            self.app._set_world(self._own_world, "Your own course is back")
            self._own_world = None
            self.app._clear_trail()
        self.course = None
        if self.state == "armed":
            self.state = "idle"
        self.join_btn.configure(text="Join")
        self.net_msg.configure(text=text, fg=colour)

    def _apply_course(self, layout):
        if self._own_world is None:
            self._own_world = self.app.world.copy()
        self.course = layout
        world = maps.Map.from_layout(layout)
        self._own_move = True
        self.app._allow_world = True
        try:
            self.app._set_world(world, f"Teacher's course: {world.name}")
            self.app._clear_trail()
        finally:
            self._own_move = False
            self.app._allow_world = False
        self._show_best()

    def course_world(self):
        return maps.Map.from_layout(self.course) if self.course else None

    def _to_internal(self, ux, uy, ang):
        return ux, self.app.world.height - uy, -ang

    def _net_frame(self, now, pose):
        if self.client is None:
            return
        for msg in self.client.poll():
            self._handle(msg, now)
            if self.client is None:
                return
        if now - self._last_send >= STATE_SEND_S and self.my_id is not None:
            self._last_send = now
            ux, uy = self.app.to_user(pose[0], pose[1])
            self.client.send({"t": "state", "x": round(ux, 2), "y": round(uy, 2),
                              "angle": round(-pose[2], 1), "status": self.state,
                              "time": round(self._elapsed(now), 2) if self.state == "running" else None,
                              "cp": self.cp, "bumps": self.bumps})

    def _handle(self, m, now):
        t = m.get("t")
        a = self.app
        sh = a.sh
        if t == "_closed":
            self.leave("Lost the connection to the teacher.", ERR)
        elif t == "welcome":
            self.my_id = m.get("id")
            self.my_colour = m.get("colour")
            self.mode = m.get("mode", "trial")
            self.limit_var.set(str(m.get("limit", 120)))
            self.pen_var.set(str(m.get("penalty", 5)))
            if m.get("layout"):
                self._apply_course(m["layout"])
            self._show_mode()
        elif t == "layout":
            self._apply_course(m["layout"])
        elif t == "mode":
            self.mode = m.get("mode", "trial")
            if self.mode != "shared":
                sh.set("others_n", 0)
            self._show_mode()
            self._redraw_others()
        elif t == "arm":
            self.race_id = m.get("race")
            a._publish_sim_controls()                   # real speed, no pausing in a race
            self.limit_var.set(str(m.get("limit", 120)))
            self.pen_var.set(str(m.get("penalty", 5)))
            self.enabled.set(True)
            self.state = "armed"
            self.result = None
            self.cp = 0
            sh.set("hold", 1)
            if sh.get("owner_gen") > 0:
                sh.bump("reset_req")                    # restart the program so it waits
            start = m.get("start")
            self._own_move = True
            try:
                if start:
                    a._request_pose(*self._to_internal(*start))
                else:
                    a._reset_pose()
            finally:
                self._own_move = False
            a._clear_trail()
            self._run_key = (sh.get("owner_gen"), sh.get("run_seq"))
            a._draw_map()
        elif t == "count":
            self.countdown = m.get("n")
        elif t == "go":
            self.countdown = None
            sh.set("hold", 0)
            self.race_id = m.get("race", self.race_id)
            self._start_attempt(now)
            self._run_key = (sh.get("owner_gen"), sh.get("run_seq"))
        elif t == "stop":
            self.countdown = None
            sh.set("hold", 0)
            if self.state == "running":
                self._end("dnf", "stopped by the teacher")
            elif self.state == "armed":
                self.state = "idle"
            self.race_id = None
        elif t == "robots":
            self._update_others(m.get("list", []))
        elif t == "radio":
            try:
                data = bytes.fromhex(m.get("d", ""))
            except ValueError:
                return
            g, c = int(m.get("g", 0)), int(m.get("c", 7))
            a.radio_to_robot(data, g, c)
            from .panels import describe
            a._radio_note(f"from {m.get('name', '?')[:10]:<10} g{g:<3} ch{c:<2}  {describe(data)}",
                          ACCENT)

    def _show_mode(self):
        if self.client is None:
            return
        mode = ("Time trial: every robot drives its own copy of the course"
                if self.mode != "shared" else
                "Shared arena: all robots drive in the same arena, can bump into each other "
                "and talk by radio")
        self.net_msg.configure(text=f"Connected (robot {self.my_id}). {mode}.", fg=OK)

    def radio_out(self, data, group, channel):
        """The program sent a radio message: pass it to the other robots (shared arena)."""
        if self.client is not None and self.mode == "shared":
            self.client.send({"t": "radio", "g": group, "c": channel, "d": bytes(data).hex()})

    # --- other robots -------------------------------------------------------------------------
    def _update_others(self, rows):
        others = {}
        for row in rows:
            try:
                cid, name, colour, ux, uy, ang, status = row
            except (TypeError, ValueError):
                continue
            if cid == self.my_id:
                continue
            x, y, h = self._to_internal(ux, uy, ang)
            others[cid] = (str(name), colour, x, y, h, status)
        self.others = others
        names = sorted(o[0] for o in others.values())
        text = ("Also connected: " + ", ".join(names)) if names else "No other students yet."
        if self.others_label.cget("text") != text:
            self.others_label.configure(text=text)
        sh = self.app.sh
        if self.mode == "shared":
            vals = []
            for (_n, _c, x, y, h, _s) in list(others.values())[:shared.MAX_OTHERS]:
                vals.extend((x, y, h))
            if vals:
                sh.set("others", vals + [0.0] * (3 * shared.MAX_OTHERS - len(vals)))
            sh.set("others_n", len(vals) // 3)
        else:
            sh.set("others_n", 0)
        self._redraw_others()

    def _redraw_others(self):
        a = self.app
        c = a.canvas
        show = self.client is not None and (self.mode == "shared" or self.show_others.get())
        for cid in list(self._other_items):
            if not show or cid not in self.others:
                for it in self._other_items.pop(cid):
                    c.delete(it)
        if not show:
            return
        ghost = self.mode != "shared"
        for cid, (name, colour, x, y, h, status) in self.others.items():
            items = self._other_items.get(cid)
            if items is None or not all(c.type(i) for i in items):
                for it in items or ():
                    c.delete(it)
                items = self._other_items[cid] = make_robot_items(c, colour, name, ghost)
            label = name if status != "finished" else f"{name} \u2713"
            place_robot_items(c, items, a.w2s, x, y, h, label)

    def after_redraw(self):
        """The arena was redrawn (all canvas items deleted)."""
        self._other_items = {}
        self._redraw_others()


# --- drawing another robot (also used by the teacher's dashboard) ---------------------------
_SHAPE = R.robot_shape()


def make_robot_items(c, colour, name, ghost=False):
    kw = dict(stipple="gray50", dash=(4, 2)) if ghost else {}
    wheels = [c.create_polygon(0, 0, 0, 0, fill="#2B2B2B", outline="") for _ in _SHAPE["wheels"]]
    body = c.create_polygon(0, 0, 0, 0, fill=colour, outline="#111111", width=1, **kw)
    nose = c.create_line(0, 0, 0, 0, fill="#FFFFFF", width=2)
    label = c.create_text(0, 0, text=name, fill="#1F2328", font=("Segoe UI", 8, "bold"))
    return tuple(wheels) + (body, nose, label)


def place_robot_items(c, items, w2s, x, y, h, label_text):
    """Move a robot drawn by make_robot_items to x, y, heading (internal frame, degrees)."""
    hr = math.radians(h)
    ch, sn = math.cos(hr), math.sin(hr)

    def P(ahead, left):
        return w2s(x + ahead * ch + left * sn, y + ahead * sn - left * ch)

    def poly(pts):
        out = []
        for p in pts:
            out.extend(P(*p))
        return out

    nw = len(_SHAPE["wheels"])
    for it, wheel in zip(items[:nw], _SHAPE["wheels"]):
        c.coords(it, *poly(wheel))
    body, nose, label = items[nw:]
    c.coords(body, *poly(_SHAPE["body"]))
    c.coords(nose, *P(0, 0), *P(R.FRONT_CM, 0))
    lx, ly = P(0, 0)
    c.coords(label, lx, ly - R.ROBOT_LENGTH_CM * 0.75 * (w2s(1, 0)[0] - w2s(0, 0)[0]) - 6)
    c.itemconfigure(label, text=label_text)
