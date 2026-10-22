"""Run this file ONCE (right-click > Run 'install_simulator').

It registers the simulator with the Python interpreter that runs it, so
``from microbit import *`` works from any folder (labs/, examples/, anywhere).
No internet connection or pip is needed: it writes a small .pth file into the
interpreter's site-packages pointing at this project folder.

Run it again if you create a new virtual environment or move the project.
To undo it, delete ``lsbu_cutebot_sim.pth`` from site-packages (path printed below).
"""

import os
import site
import sys
import sysconfig

PROJECT = os.path.dirname(os.path.abspath(__file__))
PTH_NAME = "lsbu_cutebot_sim.pth"


def target_dirs():
    yield sysconfig.get_paths()["purelib"]          # the venv / interpreter site-packages
    if site.ENABLE_USER_SITE:
        yield site.getusersitepackages()            # fallback if that is not writable


def main():
    for d in target_dirs():
        try:
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, PTH_NAME)
            with open(path, "w", encoding="utf-8") as f:
                # An "import" line in a .pth file is run at start-up.  It puts the
                # simulator FIRST on the module search path, so look-alike packages
                # installed with pip (e.g. "microbit-stubs", which contains empty
                # microbit/machine/neopixel modules) cannot hide it.
                f.write("import sys; _p = %r; sys.path.remove(_p) if _p in sys.path else None; "
                        "sys.path.insert(0, _p)\n" % PROJECT)
            break
        except OSError:
            continue
    else:
        print("Could not write to site-packages. Try running PyCharm normally (not from a "
              "read-only location) or ask IT.")
        sys.exit(1)

    print(f"Interpreter : {sys.executable}")
    print(f"Registered  : {PROJECT}")
    print(f"Written to  : {path}")

    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("\nWARNING: this Python has no Tkinter, so the simulator window cannot open.\n"
              "Reinstall Python from python.org with 'tcl/tk and IDLE' ticked.")
        sys.exit(1)

    # Check from a fresh interpreter that 'microbit' really is the simulator.
    import subprocess

    check = subprocess.run(
        [sys.executable, "-c", "import microbit, machine, neopixel, music, utime; "
         "print(microbit.__file__); print(machine.__file__); print(neopixel.__file__)"],
        capture_output=True, text=True, cwd=os.path.expanduser("~"),
        env=dict(os.environ, CUTEBOT_SIM_HEADLESS="1"))
    files = check.stdout.split()
    if check.returncode != 0 or not all(f.startswith(PROJECT) for f in files):
        print("\nWARNING: Python is not using the simulator's modules:")
        print("   " + "\n   ".join(files or [check.stderr.strip()]))
        sys.exit(1)

    others = [n for n in ("microbit-stubs", "microbit-dummy", "microbit")
              if _installed(n)]
    if others:
        print(f"\nNote: pip package(s) {', '.join(others)} are installed. The simulator "
              "takes priority, but you can remove them:  pip uninstall " + " ".join(others))

    print("\nDone. Any file with 'from microbit import *' will now open the simulator.")


def _installed(name):
    try:
        from importlib import metadata
        metadata.distribution(name)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
