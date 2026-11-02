"""Check a program for things that work in the simulator but not on the micro:bit.

Run it from PyCharm or a terminal:

    python -m cutebot_sim.checker labs/my_program.py

or press "Check for micro:bit" in the simulator's Code window.
"""

import ast
import os
import sys

# Modules built into MicroPython on the micro:bit V2.
MICROBIT_MODULES = {
    "microbit", "music", "neopixel", "radio", "speech", "audio", "machine", "utime", "time",
    "random", "math", "gc", "micropython", "os", "struct", "ustruct", "array", "sys", "power",
    "log", "collections", "ucollections", "love", "this", "antigravity",
}
UFLASH_LIMIT = 8188          # uflash refuses scripts bigger than this (bytes)

ERROR, WARNING, NOTE = "error", "warning", "note"


def _float_parts(node):
    """True if the expression can give a float (division, float literal, float(), round(x, n)).
    Anything wrapped in int(...) or round(x) is safe."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "int" or (node.func.id == "round" and len(node.args) == 1):
            return False
        if node.func.id == "float" or (node.func.id == "round" and len(node.args) == 2):
            return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, float):
        return True
    return any(_float_parts(c) for c in ast.iter_child_nodes(node))


def _const(node):
    return node.value if isinstance(node, ast.Constant) else None


class _Visitor(ast.NodeVisitor):
    def __init__(self):
        self.found = []

    def add(self, node, level, text):
        self.found.append((getattr(node, "lineno", 0), level, text))

    # --- imports ---------------------------------------------------------------------
    def _check_module(self, node, name):
        top = name.split(".")[0]
        if top not in MICROBIT_MODULES:
            self.add(node, ERROR, f"'{top}' does not exist on the micro:bit (it is only on your "
                                  "PC). Remove it before uploading.")

    def visit_Import(self, node):
        for a in node.names:
            self._check_module(node, a.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module and node.level == 0:
            self._check_module(node, node.module)
        self.generic_visit(node)

    # --- calls -----------------------------------------------------------------------
    def visit_Call(self, node):
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        if name == "bytearray" and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
            self._check_bytes(node, node.args[0].elts)
        if (name == "sleep" and isinstance(f, ast.Name) and len(node.args) == 1
                and isinstance(_const(node.args[0]), (int, float)) and 0 < _const(node.args[0]) < 10):
            self.add(node, NOTE, f"sleep({_const(node.args[0])}) waits {_const(node.args[0])} "
                                 "millisecond(s) - the micro:bit's sleep() is in ms "
                                 "(sleep(1000) = 1 second).")
        if name in ("scroll", "show") and isinstance(f, ast.Attribute) and node.args:
            text = _const(node.args[0])
            if isinstance(text, str) and any(ord(c) > 126 for c in text):
                self.add(node, WARNING, "The display only has ASCII letters: characters like "
                                        "é, ° or emoji show as '?'.")
        self.generic_visit(node)

    def _check_bytes(self, node, elts):
        for i, e in enumerate(elts):
            if _float_parts(e):
                self.add(node, ERROR, f"Value {i + 1} of this bytearray can be a decimal "
                                      "number. The micro:bit raises TypeError: use int(...) "
                                      "or int(round(...)).")
            v = _const(e)
            if isinstance(v, int) and not 0 <= v <= 255:
                self.add(node, ERROR, f"Value {i + 1} ({v}) does not fit in a byte (0-255).")
        if len(elts) >= 3:
            reg, speed = _const(elts[0]), _const(elts[2])
            if reg in (0x01, 0x02) and isinstance(speed, int) and speed > 100:
                self.add(node, WARNING, f"Motor speed {speed} is above 100 - "
                                        "Cutebot speeds go from 0 to 100.")

    # --- language features MicroPython does not have ------------------------------------
    def visit_Match(self, node):
        self.add(node, ERROR, "match/case is not supported by MicroPython - use if/elif.")
        self.generic_visit(node)


def check_source(source, filename="<program>"):
    """Returns a list of (line, level, text), sorted by line."""
    found = []
    try:
        tree = ast.parse(source, filename)
    except SyntaxError as e:
        return [(e.lineno or 0, ERROR, f"Syntax error: {e.msg}")]
    v = _Visitor()
    v.visit(tree)
    found.extend(v.found)
    size = len(source.encode("utf-8"))
    if size > UFLASH_LIMIT:
        found.append((0, WARNING, f"The file is {size} bytes; uflash only accepts up to "
                                  f"{UFLASH_LIMIT}. Remove long comments or unused code."))
    if "microbit" not in source:
        found.append((0, NOTE, "This file does not import microbit - is it the right file?"))
    if "\t" in source:
        found.append((0, NOTE, "The file contains tab characters; use 4 spaces to be safe."))
    order = {ERROR: 0, WARNING: 1, NOTE: 2}
    return sorted(set(found), key=lambda f: (f[0], order[f[1]]))


def check_file(path):
    with open(path, encoding="utf-8") as fh:
        return check_source(fh.read(), path)


def summary(found):
    errors = sum(1 for f in found if f[1] == ERROR)
    warnings = sum(1 for f in found if f[1] == WARNING)
    if not found:
        return "No problems found - ready to upload."
    if not errors:
        return f"{warnings} warning(s) - it should run on the micro:bit, but check them."
    return f"{errors} error(s) - fix these before uploading."


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: python -m cutebot_sim.checker my_program.py")
        return 2
    worst = 0
    for path in argv:
        found = check_file(path)
        print(f"{os.path.basename(path)}: {summary(found)}")
        for line, level, text in found:
            where = f"line {line}" if line else "file"
            print(f"  {where}: {level}: {text}")
        if any(f[1] == ERROR for f in found):
            worst = 1
    return worst


if __name__ == "__main__":
    sys.exit(main())
