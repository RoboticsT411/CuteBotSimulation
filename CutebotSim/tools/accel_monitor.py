"""Live accelerometer monitor for the crash-detection experiment (runs on the PC).

Shows what examples/09_crash_debug.py sends from the REAL robot (USB serial), as a live graph.
(When you run a program in PyCharm with the simulator, its data appears in PyCharm's Run
window instead: the simulator never sends anything to a serial port.)
The top line always says where the data comes from: REAL ROBOT, SIMULATOR or DEMO.
  dx (sideways), dz (front/back), strength, the LIMIT line, and every CRASH with its letter.

Connect EITHER
  * the robot's micro:bit itself by USB (data comes from print), or
  * a second micro:bit running examples/09_radio_receiver.py (data comes by radio, so the
    robot can drive freely without a cable).

Needs pyserial:  python -m pip install pyserial
Run it:          python tools/accel_monitor.py          (or right-click -> Run in PyCharm)
Close the uploader's serial connection first: only one program can use the port at a time.
"""

import csv
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:                       # shown in the window instead of crashing
    serial = None

BG, PANEL, FIELD, TEXT, MUTED = "#1F2328", "#262B31", "#1B1F24", "#E6E8EA", "#9AA3AD"
C_X, C_Z, C_S, C_LIM, C_CRASH = "#F0883E", "#4FB3FF", "#E6E8EA", "#FF7B72", "#FFD33D"
MICROBIT_VID = 0x0D28
BAUD = 115200
SPAN_MS = 6000                            # graph width


def parse(line):
    """('data', t, dx, dz, s) / ('crash', t, dx, dz, s, letter) / ('limit', n) / ('end',) / None."""
    parts = line.strip().split(",")
    try:
        if parts[0] == "CRASH" and len(parts) >= 6:
            return ("crash", int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), parts[5])
        if parts[0] == "LIMIT" and len(parts) >= 2:
            return ("limit", int(parts[1]))
        if parts[0] == "END":
            return ("end",)
        if parts[0] == "SOURCE" and len(parts) >= 2:
            return ("source", parts[1])
        if parts[0] in ("START", "STOP") and len(parts) >= 2:
            return ("mark", int(parts[1]), parts[0])
        if parts[0] in ("MISSED", "FALSE") and len(parts) >= 5:
            return ("mistake", int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), parts[0])
        if len(parts) in (4, 5):
            vals = tuple(int(p) for p in parts)
            return ("data",) + vals[:4] + ((vals[4],) if len(vals) == 5 else (None,))
    except ValueError:
        pass
    return None


class Monitor:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.ser = None
        self.stop_reader = threading.Event()
        self.data = []                    # (t, dx, dz, s)
        self.crashes = []                 # (t, dx, dz, s, letter)
        self.marks = []                   # (t, "START"/"STOP")
        self.mistakes = []                # (t, dx, dz, s, "MISSED"/"FALSE")
        self.limit = 700
        self.runs = 0
        self.all_rows = []                # for CSV: run, t, dx, dz, s, event

        root.title("Crash monitor - accelerometer")
        root.configure(bg=BG)
        root.geometry("980x640")
        bar = tk.Frame(root, bg=PANEL)
        bar.pack(fill="x")
        tk.Label(bar, text="Port", bg=PANEL, fg=MUTED).pack(side="left", padx=(8, 2), pady=6)
        self.port = ttk.Combobox(bar, width=34, state="readonly")
        self.port.pack(side="left")
        self._btn(bar, "Refresh", self.refresh).pack(side="left", padx=4)
        self.conn_btn = self._btn(bar, "Connect", self.toggle)
        self.conn_btn.pack(side="left", padx=4)
        self._btn(bar, "Demo data", self.demo).pack(side="left", padx=4)
        self._btn(bar, "Clear", self.clear).pack(side="left", padx=4)
        self._btn(bar, "Save CSV", self.save).pack(side="left", padx=4)
        self.paused = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="Freeze graph", variable=self.paused, bg=PANEL, fg=TEXT,
                       selectcolor=FIELD, activebackground=PANEL).pack(side="left", padx=8)
        self.source = tk.Label(root, text="", bg=BG, fg=MUTED, anchor="w",
                               font=("Segoe UI", 14, "bold"))
        self.source.pack(fill="x", padx=8, pady=(6, 0))
        self.status = tk.Label(root, text="", bg=BG, fg=MUTED, anchor="w")
        self.status.pack(fill="x", padx=8, pady=(2, 0))
        self.src = "-"
        self.set_source("-")
        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=4)
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.log = tk.Listbox(root, height=7, bg=FIELD, fg=TEXT, relief="flat",
                              font=("Consolas", 9))
        self.log.pack(fill="x", padx=8, pady=(0, 8))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        self.tick()

    def _btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg="#33404D", fg=TEXT, relief="flat",
                         activebackground="#40505F", activeforeground=TEXT, padx=8)

    # --- serial ------------------------------------------------------------------------
    def refresh(self):
        if serial is None:
            self.status.configure(text="pyserial is not installed: python -m pip install pyserial",
                                  fg=C_LIM)
            return
        ports = list(list_ports.comports())
        names = [f"{p.device}  {p.description}" for p in ports]
        self.port["values"] = names
        mb = [n for p, n in zip(ports, names) if p.vid == MICROBIT_VID]
        if mb:
            self.port.set(mb[0])
        elif names:
            self.port.set(names[0])
        self.status.configure(text=f"{len(names)} port(s) found" + (" - micro:bit selected" if mb
                              else " - plug in the micro:bit and press Refresh"), fg=MUTED)

    def toggle(self):
        if self.ser is not None:
            self.disconnect()
            return
        if serial is None or not self.port.get():
            self.refresh()
            return
        dev = self.port.get().split()[0]
        try:
            self.ser = serial.Serial(dev, BAUD, timeout=0.2)
        except serial.SerialException as e:
            self.status.configure(text=f"Cannot open {dev}: {e}  (close the uploader's serial "
                                       "connection first)", fg=C_LIM)
            return
        self.stop_reader.clear()
        threading.Thread(target=self.reader, daemon=True).start()
        self.conn_btn.configure(text="Disconnect")
        self.set_source("REAL")
        self.status.configure(text=f"Connected to {dev}. Run the robot program.", fg="#3FB950")

    def disconnect(self):
        self.stop_reader.set()
        try:
            self.ser.close()
        except Exception:
            pass
        self.ser = None
        self.conn_btn.configure(text="Connect")
        self.status.configure(text="Disconnected", fg=MUTED)
        self.set_source("-")

    def reader(self):
        buf = b""
        while not self.stop_reader.is_set():
            try:
                chunk = self.ser.read(256)
            except Exception:
                self.q.put("__lost__")
                return
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.q.put(line.decode("utf-8", "replace").strip())

    def demo(self):
        """Fake run: driving with vibration, a false spike, then a real front crash."""
        import math
        import random

        def run():
            self.q.put("SOURCE,DEMO")
            self.q.put("LIMIT,700")
            for k in range(0, 4200, 20):
                if k == 1500:
                    dx, dz = 120, -760                 # a bump in the floor: false trigger
                elif 3000 <= k < 3100:
                    dz = int(1400 * math.exp(-(k - 3000) / 30.0)); dx = 90
                else:
                    dx, dz = random.randint(-90, 90), random.randint(-150, 150)
                s = int(math.hypot(dx, dz))
                self.q.put(f"{k},{dx},{dz},{s}")
                if k == 3000:
                    self.q.put(f"CRASH,{k},{dx},{dz},{s},F")
                time.sleep(0.02)
            self.q.put("END")
        threading.Thread(target=run, daemon=True).start()

    # --- data ---------------------------------------------------------------------------
    def tick(self):
        changed = False
        while True:
            try:
                line = self.q.get_nowait()
            except queue.Empty:
                break
            if line == "__lost__":
                self.disconnect()
                self.status.configure(text="Connection lost (cable unplugged?)", fg=C_LIM)
                continue
            self.add_log(line)
            p = parse(line)
            if p is None:
                continue
            changed = True
            if p[0] == "data":
                if self.data and p[1] < self.data[-1][0] - 100:
                    self.new_run()
                elif not self.data:
                    self.runs = max(self.runs, 1)
                self.data.append(p[1:])
                self.all_rows.append((self.runs, *p[1:5], p[5] if p[5] is not None else "", ""))
            elif p[0] == "crash":
                self.crashes.append(p[1:])
                self.all_rows.append((self.runs, *p[1:5], "", "CRASH " + p[5]))
            elif p[0] == "source":
                self.set_source(p[1])
            elif p[0] == "mistake":
                self.mistakes.append(p[1:])
                self.all_rows.append((self.runs, *p[1:5], "", p[5]))
            elif p[0] == "mark":
                self.marks.append(p[1:])
                self.all_rows.append((self.runs, p[1], "", "", "", "", p[2]))
            elif p[0] == "limit":
                self.limit = p[1]
            elif p[0] == "end":
                self.status.configure(text="Run finished. Freeze the graph or Save CSV to study it.",
                                      fg=MUTED)
        if changed and not self.paused.get():
            self.draw()
        self.root.after(40, self.tick)

    def set_source(self, src):
        """Show clearly where the data comes from."""
        self.src = src
        if src == "REAL":
            dev = getattr(self.ser, "port", "") if self.ser is not None else ""
            text, col = f"Data from: REAL ROBOT  (micro:bit on {dev or 'serial'})", "#3FB950"
        elif src == "SIMULATOR":
            text, col = "Data from: SIMULATOR (program run on the PC)", "#4FB3FF"
        elif src == "DEMO":
            text, col = "Data from: DEMO (made-up example, not a robot)", "#D29922"
        elif self.ser is not None:
            text, col = ("Data from: REAL ROBOT  (serial)  - press the micro:bit's reset button "
                         "to see its SOURCE line"), "#3FB950"
        else:
            text, col = "Data from: nothing yet - Connect to the robot's micro:bit (USB)", MUTED
        self.source.configure(text=text, fg=col)

    def new_run(self):
        self.runs += 1
        self.data, self.crashes, self.marks, self.mistakes = [], [], [], []

    def add_log(self, line):
        self.log.insert("end", line)
        if line.startswith("CRASH"):
            self.log.itemconfigure("end", foreground=C_CRASH)
        elif line.startswith(("MISSED", "FALSE")):
            self.log.itemconfigure("end", foreground="#F778BA")
        if self.log.size() > 400:
            self.log.delete(0, 99)
        self.log.see("end")

    def clear(self):
        self.data, self.crashes, self.marks, self.mistakes, self.all_rows = [], [], [], [], []
        self.log.delete(0, "end")
        self.draw()

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            initialfile=time.strftime("crash_%H%M%S.csv"),
                                            filetypes=[("CSV", "*.csv")])
        if path:
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["source", "run", "time_ms", "dx_mg", "dz_mg", "strength_mg", "shake_mg",
                            "event"])
                w.writerows((self.src,) + tuple(r) for r in self.all_rows)
            self.status.configure(text=f"Saved {len(self.all_rows)} rows to {path}", fg=MUTED)

    # --- graph --------------------------------------------------------------------------
    def draw(self):
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 150)
        left, right, top, bottom = 56, 12, 24, 22
        if not self.data:
            c.create_text(w / 2, h / 2, fill=MUTED, text="No data yet. Connect, then press the "
                          "micro:bit's reset button (or Demo data).")
            return
        t_end = self.data[-1][0]
        t0 = t_end - SPAN_MS
        pts = [d for d in self.data if d[0] >= t0]
        big = max([self.limit * 1.3] + [max(abs(d[1]), abs(d[2]), d[3]) for d in pts])
        lim = 500
        while lim < big:
            lim += 500
        X = lambda t: left + (t - t0) / SPAN_MS * (w - left - right)          # noqa: E731
        Y = lambda v: top + (lim - v) / (2 * lim) * (h - top - bottom)         # noqa: E731
        for v in range(-lim, lim + 1, 500):
            c.create_line(left, Y(v), w - right, Y(v), fill="#2C333B")
            c.create_text(left - 6, Y(v), text=str(v), fill=MUTED, anchor="e", font=("Segoe UI", 8))
        for v in (self.limit, -self.limit):
            c.create_line(left, Y(v), w - right, Y(v), fill=C_LIM, dash=(6, 4))
        c.create_text(w - right, Y(self.limit) - 8, text=f"LIMIT {self.limit}", fill=C_LIM,
                      anchor="e", font=("Segoe UI", 8))
        shake_pts = [(X(d[0]), Y(d[4])) for d in pts if len(d) > 4 and d[4] is not None]
        if len(shake_pts) >= 2:
            c.create_line(*[v for p in shake_pts for v in p], fill="#3FB950", width=1)
        for idx, col in ((3, C_S), (1, C_X), (2, C_Z)):
            if len(pts) >= 2:
                coords = []
                for d in pts:
                    coords.extend((X(d[0]), Y(d[idx])))
                c.create_line(*coords, fill=col, width=2 if idx != 3 else 1)
        for t, what in self.marks:
            if t >= t0:
                col = "#3FB950" if what == "START" else MUTED
                c.create_line(X(t), top, X(t), h - bottom, fill=col, dash=(3, 3))
                c.create_text(X(t) + 4, h - bottom - 4, text=what, fill=col, anchor="sw",
                              font=("Segoe UI", 8, "bold"))
        for t, dx, dz, s, what in self.mistakes:
            if t >= t0:
                col = "#F778BA" if what == "MISSED" else "#8B949E"
                c.create_line(X(t), top, X(t), h - bottom, fill=col, width=2, dash=(6, 3))
                note = (f"MISSED crash (biggest jolt {s} mg < LIMIT)" if what == "MISSED"
                        else f"FALSE crash ({s} mg, no real hit)")
                c.create_text(X(t) - 4, top + 18, text=note, fill=col, anchor="ne",
                              font=("Segoe UI", 9, "bold"))
        for t, dx, dz, s, letter in self.crashes:
            if t >= t0:
                c.create_line(X(t), top, X(t), h - bottom, fill=C_CRASH, width=2)
                c.create_text(X(t) + 4, top + 2, text=f"CRASH {letter}  ({s} mg)", fill=C_CRASH,
                              anchor="nw", font=("Segoe UI", 9, "bold"))
        for k in range(0, SPAN_MS + 1, 1000):
            c.create_text(X(t0 + k), h - 8, text=f"{int(round((t0 + k) / 1000)) + 0}s", fill=MUTED,
                          font=("Segoe UI", 8))
        c.create_text(left, 10, anchor="w", font=("Segoe UI", 9, "bold"), fill=TEXT,
                      text="mg   orange = dx (sideways)   blue = dz (front/back)   white = strength   "
                           "green = shake   red dashes = LIMIT / quiet level")

    def close(self):
        if self.ser is not None:
            self.disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    Monitor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
