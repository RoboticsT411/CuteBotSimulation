"""Local network (LAN) link between the teacher's dashboard and the students' simulators.

Standard library only.  Messages are JSON objects, one per line, over TCP.
The teacher's PC is the server; students' simulator windows connect to it.  A router
with no internet connection is enough: every PC just needs to be on the same network.

Teacher -> students
    welcome {id, name, colour, mode, layout, limit, penalty}
    layout  {layout}                course changed
    mode    {mode}                  "trial" (own copy of the course) or "shared" (one arena)
    arm     {race, limit, penalty, start}   get ready: programs wait for GO
    count   {n}                     3, 2, 1
    go      {race}
    stop    {race}
    robots  {list: [[id, name, colour, x, y, angle, status], ...]}
    radio   {from, name, g, c, d}   a radio message from another robot (shared arena)
Students -> teacher
    hello   {name, version}
    state   {x, y, angle, status, time, cp, bumps}
    result  {race, status, time, penalty, total, cp}
    radio   {g, c, d}               d = message bytes as hex
"""

import json
import queue
import socket
import threading

PORT = 47800
DISCOVERY_PORT = 47801
VERSION = 1
COLOURS = ["#E5534B", "#4FB3FF", "#3FB950", "#D29922", "#A371F7", "#F778BA", "#56D4DD",
           "#F0883E", "#8B949E", "#B4E06A", "#FF9E64", "#7AA2F7"]


def local_ips():
    """IP addresses of this PC that other PCs can use (best effort)."""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))          # no packet is sent; picks the LAN interface
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except OSError:
        pass
    ips.discard("127.0.0.1")
    return sorted(ips) or ["127.0.0.1"]


class _Conn:
    """One TCP connection: a reader thread puts decoded messages on a queue."""

    def __init__(self, sock, on_message, on_close):
        self.sock = sock
        self.on_message = on_message
        self.on_close = on_close
        self._lock = threading.Lock()
        self.closed = False
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=self._reader, daemon=True).start()

    def send(self, obj):
        if self.closed:
            return False
        data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self._lock:
                self.sock.sendall(data)
            return True
        except OSError:
            self.close()
            return False

    def _reader(self):
        buf = b""
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        try:
                            msg = json.loads(line.decode("utf-8"))
                        except ValueError:
                            continue
                        if isinstance(msg, dict):
                            self.on_message(self, msg)
        except OSError:
            pass
        self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass
        self.on_close(self)


# --- student side ------------------------------------------------------------------------
class Client:
    """Student's link to the teacher.  ``poll()`` returns new messages (call it from Tk)."""

    def __init__(self, host, name, port=PORT, timeout=4.0):
        self.inbox = queue.Queue()
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(None)
        self.conn = _Conn(sock, lambda c, m: self.inbox.put(m),
                          lambda c: self.inbox.put({"t": "_closed"}))
        self.conn.send({"t": "hello", "name": name, "version": VERSION})

    def send(self, obj):
        return self.conn.send(obj)

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.inbox.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        self.conn.close()

    @property
    def connected(self):
        return not self.conn.closed


def discover(timeout=1.2):
    """Find teacher dashboards on the network: [(ip, name, port), ...]."""
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.2)
        for _ in range(2):
            for target in ("255.255.255.255", "<broadcast>"):
                try:
                    s.sendto(b"CUTEBOT?", (target, DISCOVERY_PORT))
                except OSError:
                    pass
        import time
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, (ip, _p) = s.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            parts = data.decode("utf-8", "replace").split("|")
            if len(parts) >= 3 and parts[0] == "CUTEBOT":
                try:
                    found[ip] = (ip, parts[1], int(parts[2]))
                except ValueError:
                    pass
    finally:
        s.close()
    return list(found.values())


# --- teacher side ------------------------------------------------------------------------
class Server:
    """Accepts students.  Messages arrive in ``inbox`` as (client_id, message)."""

    def __init__(self, port=PORT, name="Teacher"):
        self.port = port
        self.name = name
        self.inbox = queue.Queue()
        self.clients = {}            # id -> _Conn
        self._next_id = 1
        self._lock = threading.Lock()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", port))
        self.sock.listen(64)
        threading.Thread(target=self._accept, daemon=True).start()
        threading.Thread(target=self._discovery, daemon=True).start()

    def _accept(self):
        while True:
            try:
                sock, addr = self.sock.accept()
            except OSError:
                return
            with self._lock:
                cid = self._next_id
                self._next_id += 1
            conn = _Conn(sock, lambda c, m, cid=cid: self.inbox.put((cid, m)),
                         lambda c, cid=cid: self._closed(cid))
            conn.addr = addr[0]
            with self._lock:
                self.clients[cid] = conn

    def _closed(self, cid):
        with self._lock:
            self.clients.pop(cid, None)
        self.inbox.put((cid, {"t": "_closed"}))

    def _discovery(self):
        try:
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            u.bind(("", DISCOVERY_PORT))
        except OSError:
            return
        while True:
            try:
                data, addr = u.recvfrom(256)
            except OSError:
                return
            if data.startswith(b"CUTEBOT?"):
                try:
                    u.sendto(f"CUTEBOT|{self.name}|{self.port}".encode("utf-8"), addr)
                except OSError:
                    pass

    def send(self, cid, obj):
        conn = self.clients.get(cid)
        return conn.send(obj) if conn is not None else False

    def broadcast(self, obj, exclude=None):
        with self._lock:
            conns = [(cid, c) for cid, c in self.clients.items() if cid != exclude]
        for _cid, c in conns:
            c.send(obj)

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.inbox.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
        for c in list(self.clients.values()):
            c.close()
