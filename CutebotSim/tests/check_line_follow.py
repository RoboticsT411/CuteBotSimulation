"""Run a line-following program headlessly and check it stays on the track.

Usage: python tests/check_line_follow.py path/to/program.py [seconds] [map_id]
"""
import csv, math, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from cutebot_sim import maps, robot as R  # noqa: E402

prog = os.path.abspath(sys.argv[1])
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 40
map_id = int(sys.argv[3]) if len(sys.argv) > 3 else 0
trace = os.path.join(tempfile.gettempdir(), "cutebot_trace.csv")
env = dict(os.environ, CUTEBOT_SIM_HEADLESS="1", CUTEBOT_SIM_TRACE=trace, PYTHONPATH=HERE, CUTEBOT_SIM_MAP=str(map_id))
try:
    subprocess.run([sys.executable, prog], env=env, timeout=secs, cwd=os.path.dirname(prog))
except subprocess.TimeoutExpired:
    pass

m = maps.get_map(map_id)
line = m.line
def dist_to_line(x, y):
    best = 1e9
    for (x0, y0), (x1, y1) in zip(line, line[1:]):
        dx, dy = x1 - x0, y1 - y0
        t = max(0, min(1, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy or 1)))
        best = min(best, math.hypot(x - x0 - t * dx, y - y0 - t * dy))
    return best
# cumulative arc-length position along the loop, to count laps
cum = [0.0]
for (x0, y0), (x1, y1) in zip(line, line[1:]):
    cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
total = cum[-1]
def arc_pos(x, y):
    i = min(range(len(line)), key=lambda k: (line[k][0] - x) ** 2 + (line[k][1] - y) ** 2)
    return cum[i]

rows = list(csv.DictReader(open(trace)))
worst, progress, prev = 0.0, 0.0, None
for r in rows:
    x, y, h = float(r["x"]), float(r["y"]), math.radians(float(r["heading_deg"]))
    sx, sy = x + R.LINE_SENSOR_AHEAD_CM * math.cos(h), y + R.LINE_SENSOR_AHEAD_CM * math.sin(h)
    worst = max(worst, dist_to_line(sx, sy))
    p = arc_pos(sx, sy)
    if prev is not None:
        d = (p - prev + total / 2) % total - total / 2
        progress += d
    prev = p
t = float(rows[-1]["t"])
print(f"samples={len(rows)} time={t:.1f}s  worst sensor-to-line distance={worst:.2f} cm  "
      f"laps={progress / total:+.2f}  (track {total:.0f} cm)")
