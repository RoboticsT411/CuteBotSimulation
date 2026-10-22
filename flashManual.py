import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import string
import subprocess
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


# ============================================================
# COLORS
# ============================================================

BG = "#111827"
CARD = "#1F2937"
CARD_DARK = "#182230"
BORDER = "#374151"

TEXT = "#F9FAFB"
TEXT_SECONDARY = "#9CA3AF"

BLUE = "#3B82F6"
BLUE_HOVER = "#2563EB"

GREEN = "#22C55E"
RED = "#EF4444"
YELLOW = "#F59E0B"

INPUT_BG = "#111827"

COMBO_BG = "#243B53"
COMBO_BORDER = "#4B5563"
COMBO_TEXT = "#FFFFFF"

CONSOLE_BG = "#0B1220"
CONSOLE_TEXT = "#D1FAE5"


# ============================================================
# SERIAL SETTINGS
# ============================================================

SERIAL_BAUD = 115200


# ============================================================
# MICRO:BIT DRIVE DETECTION
# ============================================================

def list_microbit_drives():
    """Detect MICROBIT drives by signature files."""

    drives = []

    for letter in string.ascii_uppercase:

        root = f"{letter}:\\"

        if not os.path.exists(root):
            continue

        if (
            os.path.exists(
                os.path.join(root, "DETAILS.TXT")
            )
            or
            os.path.exists(
                os.path.join(root, "MICROBIT.HTM")
            )
        ):
            drives.append(root)

    return drives


def read_details_summary(drive_root: str) -> str:
    """Read useful information from DETAILS.TXT."""

    path = os.path.join(
        drive_root,
        "DETAILS.TXT"
    )

    if not os.path.exists(path):
        return ""

    try:

        with open(
            path,
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as file:

            lines = file.read().splitlines()

        wanted = []

        for key in (
            "Unique ID:",
            "Version:",
            "Board ID:",
            "Interface Version:",
            "Build:",
            "Device:"
        ):

            for line in lines:

                if line.startswith(key):

                    wanted.append(
                        line.strip()
                    )

                    break

        return " | ".join(
            wanted[:2]
        )

    except Exception:
        return ""


# ============================================================
# SERIAL PORT DETECTION
# ============================================================

def list_serial_ports():
    """
    Find available serial ports.

    Ports are sorted naturally:

        COM1
        COM2
        ...
        COM9
        COM10
        COM11

    micro:bit-like devices are placed near the top.
    """

    if list_ports is None:
        return []

    ports = []

    try:

        for port in list_ports.comports():

            description = (
                port.description or ""
            )

            manufacturer = (
                port.manufacturer or ""
            )

            text = (
                f"{description} "
                f"{manufacturer}"
            ).lower()

            priority = 0

            if "micro:bit" in text:
                priority = 100

            elif "daplink" in text:
                priority = 90

            elif "mbed" in text:
                priority = 80

            elif "cmsis" in text:
                priority = 70

            elif "arm" in text:
                priority = 60

            ports.append(
                (
                    priority,
                    port.device,
                    description
                )
            )

        def natural_port_number(item):

            device = item[1]

            digits = "".join(
                character
                for character in device
                if character.isdigit()
            )

            try:
                return int(digits)

            except ValueError:
                return 999999

        ports.sort(
            key=lambda item: (
                -item[0],
                natural_port_number(item),
                item[1]
            )
        )

        return ports

    except Exception:
        return []


# ============================================================
# UFLASH
# ============================================================

def uflash_flash_cli(
    py_path: str,
    microbit_drive: str
) -> str:
    """
    Flash a Python file to the selected micro:bit.

    Correct uflash syntax:

        python -m uflash main.py D:\\
    """

    py_path = os.path.abspath(
        py_path
    )

    if not py_path.lower().endswith(".py"):

        raise RuntimeError(
            "Selected file must end in .py"
        )

    if not os.path.isfile(py_path):

        raise RuntimeError(
            f"Python file not found:\n{py_path}"
        )

    drv = microbit_drive.strip()

    if not drv:

        raise RuntimeError(
            "No micro:bit drive was selected."
        )

    if not drv.endswith("\\"):

        drv += "\\"

    # --------------------------------------------------------
    # Check uflash
    # --------------------------------------------------------

    check_cmd = [
        sys.executable,
        "-c",
        "import uflash; print(uflash.__file__)"
    ]

    check = subprocess.run(
        check_cmd,
        capture_output=True,
        text=True
    )

    if check.returncode != 0:

        raise RuntimeError(
            "uflash is not installed in this Python environment.\n\n"
            f"Python:\n{sys.executable}\n\n"
            "Install it with:\n"
            f'"{sys.executable}" -m pip install uflash'
        )

    # --------------------------------------------------------
    # Flash
    # --------------------------------------------------------

    cmd = [
        sys.executable,
        "-m",
        "uflash",
        py_path,
        drv
    ]

    try:

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )

    except Exception as error:

        raise RuntimeError(
            f"Could not start uflash:\n{error}"
        )

    stdout = (
        result.stdout or ""
    ).strip()

    stderr = (
        result.stderr or ""
    ).strip()

    output = stdout

    if stderr:

        if output:
            output += "\n\n"

        output += stderr

    if result.returncode != 0:

        raise RuntimeError(
            output or
            "uflash failed with no output."
        )

    return output


# ============================================================
# APPLICATION
# ============================================================

class App(tk.Tk):

    def __init__(self):

        super().__init__()

        # ----------------------------------------------------
        # WINDOW
        # ----------------------------------------------------

        self.title(
            "micro:bit Flasher + REPL"
        )

        self.geometry(
            "920x760"
        )

        self.minsize(
            820,
            650
        )

        self.configure(
            bg=BG
        )

        self.center_window()

        # ----------------------------------------------------
        # VARIABLES
        # ----------------------------------------------------

        self.py_file = tk.StringVar(
            value=""
        )

        self.drive_choice = tk.StringVar(
            value=""
        )

        self.serial_choice = tk.StringVar(
            value=""
        )

        self.status = tk.StringVar(
            value="Ready"
        )

        self.serial_status = tk.StringVar(
            value="Disconnected"
        )

        self.uploading = False

        self.drive_map = {}

        self.serial_map = {}

        # ----------------------------------------------------
        # SERIAL STATE
        # ----------------------------------------------------

        self.serial_connection = None

        self.serial_thread = None

        self.serial_running = False

        self.serial_lock = threading.Lock()

        # ----------------------------------------------------
        # STYLE
        # ----------------------------------------------------

        self.setup_styles()

        # ----------------------------------------------------
        # BUILD UI
        # ----------------------------------------------------

        self.build_ui()

        # ----------------------------------------------------
        # INITIAL DEVICE DETECTION
        # ----------------------------------------------------

        self.refresh_drives()

        self.refresh_serial_ports()

        # ----------------------------------------------------
        # CLOSE
        # ----------------------------------------------------

        self.protocol(
            "WM_DELETE_WINDOW",
            self.on_close
        )


    # ========================================================
    # CENTER WINDOW
    # ========================================================

    def center_window(self):

        self.update_idletasks()

        width = 920
        height = 760

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        x = int(
            (screen_width - width) / 2
        )

        y = int(
            (screen_height - height) / 2
        )

        self.geometry(
            f"{width}x{height}+{x}+{y}"
        )


    # ========================================================
    # STYLES
    # ========================================================

    def setup_styles(self):

        style = ttk.Style(self)

        try:

            style.theme_use(
                "clam"
            )

        except Exception:
            pass

        # ----------------------------------------------------
        # GENERAL
        # ----------------------------------------------------

        style.configure(
            ".",
            background=BG,
            foreground=TEXT,
            font=(
                "Segoe UI",
                10
            )
        )

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        style.configure(
            "Title.TLabel",
            background=BG,
            foreground=TEXT,
            font=(
                "Segoe UI Semibold",
                22
            )
        )

        # ----------------------------------------------------
        # SUBTITLE
        # ----------------------------------------------------

        style.configure(
            "Subtitle.TLabel",
            background=BG,
            foreground=TEXT_SECONDARY,
            font=(
                "Segoe UI",
                10
            )
        )

        # ----------------------------------------------------
        # SECTION
        # ----------------------------------------------------

        style.configure(
            "Section.TLabel",
            background=CARD,
            foreground=TEXT,
            font=(
                "Segoe UI Semibold",
                11
            )
        )

        # ----------------------------------------------------
        # NORMAL
        # ----------------------------------------------------

        style.configure(
            "Normal.TLabel",
            background=CARD,
            foreground=TEXT_SECONDARY,
            font=(
                "Segoe UI",
                9
            )
        )

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        style.configure(
            "Status.TLabel",
            background=CARD_DARK,
            foreground=TEXT,
            font=(
                "Segoe UI Semibold",
                10
            )
        )

        # ----------------------------------------------------
        # ENTRY
        # ----------------------------------------------------

        style.configure(
            "Modern.TEntry",
            fieldbackground=INPUT_BG,
            background=INPUT_BG,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=9
        )

        # ----------------------------------------------------
        # COMBOBOX
        # ----------------------------------------------------

        style.configure(
            "Modern.TCombobox",
            fieldbackground=COMBO_BG,
            background=COMBO_BG,
            foreground=COMBO_TEXT,
            bordercolor=COMBO_BORDER,
            lightcolor=COMBO_BORDER,
            darkcolor=COMBO_BORDER,
            arrowcolor=COMBO_TEXT,
            padding=8
        )

        style.map(
            "Modern.TCombobox",

            fieldbackground=[
                (
                    "readonly",
                    COMBO_BG
                ),
                (
                    "disabled",
                    COMBO_BG
                )
            ],

            foreground=[
                (
                    "readonly",
                    COMBO_TEXT
                ),
                (
                    "disabled",
                    COMBO_TEXT
                )
            ],

            background=[
                (
                    "readonly",
                    COMBO_BG
                ),
                (
                    "disabled",
                    COMBO_BG
                )
            ],

            arrowcolor=[
                (
                    "readonly",
                    COMBO_TEXT
                ),
                (
                    "disabled",
                    COMBO_TEXT
                )
            ]
        )

        # ----------------------------------------------------
        # PRIMARY BUTTON
        # ----------------------------------------------------

        style.configure(
            "Primary.TButton",
            background=BLUE,
            foreground="white",
            borderwidth=0,
            padding=10,
            font=(
                "Segoe UI Semibold",
                10
            )
        )

        style.map(
            "Primary.TButton",

            background=[
                (
                    "active",
                    BLUE_HOVER
                ),
                (
                    "disabled",
                    "#374151"
                )
            ],

            foreground=[
                (
                    "disabled",
                    "#9CA3AF"
                )
            ]
        )

        # ----------------------------------------------------
        # SECONDARY BUTTON
        # ----------------------------------------------------

        style.configure(
            "Secondary.TButton",
            background="#374151",
            foreground=TEXT,
            borderwidth=0,
            padding=9,
            font=(
                "Segoe UI Semibold",
                9
            )
        )

        style.map(
            "Secondary.TButton",

            background=[
                (
                    "active",
                    "#4B5563"
                )
            ]
        )

        # ----------------------------------------------------
        # CONSOLE BUTTON
        # ----------------------------------------------------

        style.configure(
            "Console.TButton",
            background="#243B53",
            foreground=TEXT,
            borderwidth=0,
            padding=7,
            font=(
                "Segoe UI Semibold",
                9
            )
        )

        style.map(
            "Console.TButton",

            background=[
                (
                    "active",
                    "#315675"
                )
            ]
        )

        # ----------------------------------------------------
        # PROGRESS BAR
        # ----------------------------------------------------

        style.configure(
            "Modern.Horizontal.TProgressbar",
            troughcolor="#111827",
            background=BLUE,
            bordercolor="#111827",
            lightcolor=BLUE,
            darkcolor=BLUE,
            thickness=7
        )


    # ========================================================
    # BUILD UI
    # ========================================================

    def build_ui(self):

        main = tk.Frame(
            self,
            bg=BG
        )

        main.pack(
            fill="both",
            expand=True,
            padx=28,
            pady=24
        )

        # ====================================================
        # HEADER
        # ====================================================

        header = tk.Frame(
            main,
            bg=BG
        )

        header.pack(
            fill="x",
            pady=(0, 18)
        )

        logo = tk.Label(
            header,
            text="μ",
            bg=BLUE,
            fg="white",
            font=(
                "Segoe UI Semibold",
                22
            ),
            width=2,
            height=1
        )

        logo.pack(
            side="left",
            padx=(0, 14)
        )

        title_area = tk.Frame(
            header,
            bg=BG
        )

        title_area.pack(
            side="left"
        )

        ttk.Label(
            title_area,
            text="micro:bit Flasher + REPL",
            style="Title.TLabel"
        ).pack(
            anchor="w"
        )

        ttk.Label(
            title_area,
            text=(
                "Upload MicroPython programs and "
                "see their serial output"
            ),
            style="Subtitle.TLabel"
        ).pack(
            anchor="w",
            pady=(2, 0)
        )

        # ====================================================
        # PYTHON FILE CARD
        # ====================================================

        file_card = tk.Frame(
            main,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1
        )

        file_card.pack(
            fill="x",
            pady=(0, 12)
        )

        file_content = tk.Frame(
            file_card,
            bg=CARD
        )

        file_content.pack(
            fill="x",
            padx=18,
            pady=14
        )

        ttk.Label(
            file_content,
            text="Python program",
            style="Section.TLabel"
        ).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w"
        )

        ttk.Label(
            file_content,
            text=(
                "Select the .py file you want to upload."
            ),
            style="Normal.TLabel"
        ).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(2, 8)
        )

        file_content.columnconfigure(
            0,
            weight=1
        )

        self.file_entry = ttk.Entry(
            file_content,
            textvariable=self.py_file,
            style="Modern.TEntry"
        )

        self.file_entry.grid(
            row=2,
            column=0,
            sticky="ew",
            padx=(0, 10)
        )

        self.browse_btn = ttk.Button(
            file_content,
            text="Browse...",
            style="Secondary.TButton",
            command=self.browse
        )

        self.browse_btn.grid(
            row=2,
            column=1,
            sticky="e"
        )

        # ====================================================
        # DEVICE CARD
        # ====================================================

        device_card = tk.Frame(
            main,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1
        )

        device_card.pack(
            fill="x",
            pady=(0, 12)
        )

        device_content = tk.Frame(
            device_card,
            bg=CARD
        )

        device_content.pack(
            fill="x",
            padx=18,
            pady=14
        )

        ttk.Label(
            device_content,
            text="Target micro:bit",
            style="Section.TLabel"
        ).grid(
            row=0,
            column=0,
            columnspan=3,
            sticky="w"
        )

        ttk.Label(
            device_content,
            text="MICROBIT drive",
            style="Normal.TLabel"
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(8, 5)
        )

        ttk.Label(
            device_content,
            text="Serial port",
            style="Normal.TLabel"
        ).grid(
            row=1,
            column=1,
            sticky="w",
            pady=(8, 5)
        )

        device_content.columnconfigure(
            0,
            weight=1
        )

        device_content.columnconfigure(
            1,
            weight=1
        )

        # ----------------------------------------------------
        # DRIVE
        # ----------------------------------------------------

        self.combo = ttk.Combobox(
            device_content,
            textvariable=self.drive_choice,
            state="readonly",
            style="Modern.TCombobox"
        )

        self.combo.grid(
            row=2,
            column=0,
            sticky="ew",
            padx=(0, 10)
        )

        # ----------------------------------------------------
        # SERIAL PORT
        # ----------------------------------------------------

        self.serial_combo = ttk.Combobox(
            device_content,
            textvariable=self.serial_choice,
            state="readonly",
            style="Modern.TCombobox"
        )

        self.serial_combo.grid(
            row=2,
            column=1,
            sticky="ew",
            padx=(0, 10)
        )

        # ----------------------------------------------------
        # REFRESH
        # ----------------------------------------------------

        self.refresh_btn = ttk.Button(
            device_content,
            text="⟳  Refresh",
            style="Secondary.TButton",
            command=self.refresh_devices
        )

        self.refresh_btn.grid(
            row=2,
            column=2,
            sticky="e"
        )

        # ====================================================
        # SERIAL CONNECTION CONTROLS
        # ====================================================

        serial_controls = tk.Frame(
            device_card,
            bg=CARD
        )

        serial_controls.pack(
            fill="x",
            padx=18,
            pady=(0, 14)
        )

        self.connect_btn = ttk.Button(
            serial_controls,
            text="Connect",
            style="Primary.TButton",
            command=self.connect_serial
        )

        self.connect_btn.pack(
            side="left",
            padx=(0, 8)
        )

        self.disconnect_btn = ttk.Button(
            serial_controls,
            text="Disconnect",
            style="Secondary.TButton",
            command=self.disconnect_serial
        )

        self.disconnect_btn.pack(
            side="left"
        )

        serial_help = tk.Label(
            serial_controls,
            text=(
                "Select the serial port first, "
                "then click Connect."
            ),
            bg=CARD,
            fg=TEXT_SECONDARY,
            font=(
                "Segoe UI",
                9
            )
        )

        serial_help.pack(
            side="left",
            padx=(14, 0)
        )

        # ====================================================
        # UPLOAD
        # ====================================================

        action_frame = tk.Frame(
            main,
            bg=BG
        )

        action_frame.pack(
            fill="x",
            pady=(1, 10)
        )

        self.btn = ttk.Button(
            action_frame,
            text="Upload to micro:bit",
            style="Primary.TButton",
            command=self.upload
        )

        self.btn.pack(
            side="left"
        )

        # ====================================================
        # STATUS CARD
        # ====================================================

        status_card = tk.Frame(
            main,
            bg=CARD_DARK,
            highlightbackground=BORDER,
            highlightthickness=1
        )

        status_card.pack(
            fill="x",
            pady=(0, 12)
        )

        status_content = tk.Frame(
            status_card,
            bg=CARD_DARK
        )

        status_content.pack(
            fill="x",
            padx=16,
            pady=10
        )

        status_top = tk.Frame(
            status_content,
            bg=CARD_DARK
        )

        status_top.pack(
            fill="x"
        )

        ttk.Label(
            status_top,
            text="STATUS",
            style="Status.TLabel"
        ).pack(
            side="left"
        )

        self.status_label = tk.Label(
            status_top,
            textvariable=self.status,
            bg=CARD_DARK,
            fg=TEXT_SECONDARY,
            font=(
                "Segoe UI",
                9
            )
        )

        self.status_label.pack(
            side="right"
        )

        self.pbar = ttk.Progressbar(
            status_content,
            mode="indeterminate",
            style="Modern.Horizontal.TProgressbar"
        )

        self.pbar.pack(
            fill="x",
            pady=(8, 0)
        )

        # ====================================================
        # CONSOLE CARD
        # ====================================================

        console_card = tk.Frame(
            main,
            bg=CONSOLE_BG,
            highlightbackground=BORDER,
            highlightthickness=1
        )

        console_card.pack(
            fill="both",
            expand=True
        )

        # ----------------------------------------------------
        # Console header
        # ----------------------------------------------------

        console_top = tk.Frame(
            console_card,
            bg=CONSOLE_BG
        )

        console_top.pack(
            fill="x",
            padx=12,
            pady=(10, 7)
        )

        console_title = tk.Label(
            console_top,
            text="SERIAL CONSOLE / REPL",
            bg=CONSOLE_BG,
            fg=TEXT,
            font=(
                "Segoe UI Semibold",
                10
            )
        )

        console_title.pack(
            side="left"
        )

        self.serial_status_label = tk.Label(
            console_top,
            textvariable=self.serial_status,
            bg=CONSOLE_BG,
            fg=TEXT_SECONDARY,
            font=(
                "Segoe UI",
                9
            )
        )

        self.serial_status_label.pack(
            side="right"
        )

        # ----------------------------------------------------
        # Console text
        # ----------------------------------------------------

        text_frame = tk.Frame(
            console_card,
            bg=CONSOLE_BG
        )

        text_frame.pack(
            fill="both",
            expand=True,
            padx=12
        )

        self.console = tk.Text(
            text_frame,
            bg=CONSOLE_BG,
            fg=CONSOLE_TEXT,
            insertbackground=TEXT,
            selectbackground="#26415E",
            selectforeground=TEXT,
            relief="flat",
            borderwidth=0,
            font=(
                "Consolas",
                10
            ),
            wrap="word"
        )

        self.console.pack(
            side="left",
            fill="both",
            expand=True
        )

        console_scroll = ttk.Scrollbar(
            text_frame,
            orient="vertical",
            command=self.console.yview
        )

        console_scroll.pack(
            side="right",
            fill="y"
        )

        self.console.configure(
            yscrollcommand=console_scroll.set
        )

        # ----------------------------------------------------
        # Command input
        # ----------------------------------------------------

        command_frame = tk.Frame(
            console_card,
            bg=CONSOLE_BG
        )

        command_frame.pack(
            fill="x",
            padx=12,
            pady=(8, 10)
        )

        self.command_entry = tk.Entry(
            command_frame,
            bg="#111827",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=(
                "Consolas",
                10
            )
        )

        self.command_entry.pack(
            side="left",
            fill="x",
            expand=True,
            ipady=8,
            padx=(0, 8)
        )

        self.command_entry.bind(
            "<Return>",
            self.send_command_event
        )

        self.send_btn = ttk.Button(
            command_frame,
            text="Send",
            style="Console.TButton",
            command=self.send_command
        )

        self.send_btn.pack(
            side="right"
        )

        # ----------------------------------------------------
        # Console buttons
        # ----------------------------------------------------

        console_controls = tk.Frame(
            console_card,
            bg=CONSOLE_BG
        )

        console_controls.pack(
            fill="x",
            padx=12,
            pady=(0, 10)
        )

        ttk.Button(
            console_controls,
            text="Interrupt (Ctrl+C)",
            style="Console.TButton",
            command=self.interrupt_program
        ).pack(
            side="left",
            padx=(0, 6)
        )

        ttk.Button(
            console_controls,
            text="Enter REPL",
            style="Console.TButton",
            command=self.enter_repl
        ).pack(
            side="left",
            padx=(0, 6)
        )

        ttk.Button(
            console_controls,
            text="Soft Reset",
            style="Console.TButton",
            command=self.soft_reset
        ).pack(
            side="left",
            padx=(0, 6)
        )

        ttk.Button(
            console_controls,
            text="Clear",
            style="Console.TButton",
            command=self.clear_console
        ).pack(
            side="right"
        )

        # ====================================================
        # FOOTER
        # ====================================================

        footer = tk.Label(
            main,
            text=(
                "Ready • uflash uploader • "
                "MicroPython serial console"
            ),
            bg=BG,
            fg="#6B7280",
            font=(
                "Segoe UI",
                8
            )
        )

        footer.pack(
            anchor="w",
            pady=(8, 0)
        )


    # ========================================================
    # BROWSE
    # ========================================================

    def browse(self):

        path = filedialog.askopenfilename(
            title="Select Python program",
            filetypes=[
                (
                    "Python files",
                    "*.py"
                ),
                (
                    "All files",
                    "*.*"
                )
            ]
        )

        if path:

            self.py_file.set(
                os.path.abspath(path)
            )

            self.set_status(
                "Python file selected.",
                TEXT_SECONDARY
            )


    # ========================================================
    # REFRESH DEVICES
    # ========================================================

    def refresh_devices(self):

        self.refresh_drives()

        self.refresh_serial_ports()


    # ========================================================
    # REFRESH DRIVES
    # ========================================================

    def refresh_drives(self):

        drives = list_microbit_drives()

        self.drive_map = {}

        if not drives:

            self.combo["values"] = [
                "(No MICROBIT drive found)"
            ]

            self.drive_choice.set(
                "(No MICROBIT drive found)"
            )

            self.set_status(
                (
                    "No micro:bit detected. "
                    "Connect it and click Refresh."
                ),
                TEXT_SECONDARY
            )

            return

        labels = []

        for drive in drives:

            info = read_details_summary(
                drive
            )

            if info:

                label = (
                    f"{drive}   {info}"
                )

            else:

                label = drive

            labels.append(
                label
            )

            self.drive_map[
                label
            ] = drive

        self.combo["values"] = labels

        # Only choose a drive if the current selection
        # isn't still valid.

        current = self.drive_choice.get()

        if current not in labels:

            self.drive_choice.set(
                labels[0]
            )

        if len(drives) == 1:

            self.set_status(
                f"Micro:bit detected on {drives[0]}",
                GREEN
            )

        else:

            self.set_status(
                f"{len(drives)} micro:bit drives detected.",
                GREEN
            )


    # ========================================================
    # REFRESH SERIAL PORTS
    # ========================================================

    def refresh_serial_ports(self):

        if list_ports is None:

            self.serial_combo["values"] = [
                "pyserial not installed"
            ]

            self.serial_choice.set(
                "pyserial not installed"
            )

            self.set_serial_status(
                "pyserial not installed",
                RED
            )

            return

        ports = list_serial_ports()

        self.serial_map = {}

        if not ports:

            self.serial_combo["values"] = [
                "(No serial port found)"
            ]

            self.serial_choice.set(
                "(No serial port found)"
            )

            self.set_serial_status(
                "No serial port found",
                TEXT_SECONDARY
            )

            return

        labels = []

        for priority, device, description in ports:

            if description:

                label = (
                    f"{device}   {description}"
                )

            else:

                label = device

            labels.append(
                label
            )

            self.serial_map[
                label
            ] = device

        self.serial_combo["values"] = labels

        # IMPORTANT:
        # Preserve the user's selection if it still exists.

        current = self.serial_choice.get()

        if current not in labels:

            self.serial_choice.set(
                labels[0]
            )

        self.set_serial_status(
            f"{len(ports)} serial port(s) found",
            GREEN
        )


    # ========================================================
    # STATUS
    # ========================================================

    def set_status(
        self,
        text,
        color=TEXT_SECONDARY
    ):

        self.status.set(
            text
        )

        self.status_label.configure(
            fg=color
        )


    def set_serial_status(
        self,
        text,
        color=TEXT_SECONDARY
    ):

        self.serial_status.set(
            text
        )

        self.serial_status_label.configure(
            fg=color
        )


    # ========================================================
    # UPLOAD
    # ========================================================

    def upload(self):

        if self.uploading:
            return

        # ----------------------------------------------------
        # Validate Python file
        # ----------------------------------------------------

        py_path = self.py_file.get().strip()

        if not py_path:

            messagebox.showerror(
                "Missing file",
                "Please select a Python file first."
            )

            return

        py_path = os.path.abspath(
            py_path
        )

        if not py_path.lower().endswith(".py"):

            messagebox.showerror(
                "Invalid file",
                "Please select a .py Python file."
            )

            return

        if not os.path.isfile(py_path):

            messagebox.showerror(
                "File not found",
                f"Cannot find:\n{py_path}"
            )

            return

        # ----------------------------------------------------
        # Validate drive
        # ----------------------------------------------------

        choice = self.drive_choice.get().strip()

        if choice.startswith(
            "(No MICROBIT"
        ):

            messagebox.showerror(
                "No micro:bit",
                (
                    "No MICROBIT drive was detected.\n\n"
                    "Connect your micro:bit "
                    "and click Refresh."
                )
            )

            return

        drv = self.drive_map.get(
            choice
        )

        if not drv:

            messagebox.showerror(
                "Drive error",
                (
                    "The selected micro:bit drive "
                    "could not be found.\n\n"
                    "Click Refresh and try again."
                )
            )

            return

        # ----------------------------------------------------
        # Close serial connection before flashing
        #
        # IMPORTANT:
        # We do NOT change the selected COM port.
        # We also do NOT reconnect automatically.
        # ----------------------------------------------------

        if self.serial_connection:

            self.disconnect_serial(
                silent=True
            )

        # ----------------------------------------------------
        # Start upload
        # ----------------------------------------------------

        self.uploading = True

        self.btn.configure(
            state="disabled"
        )

        self.browse_btn.configure(
            state="disabled"
        )

        self.refresh_btn.configure(
            state="disabled"
        )

        self.connect_btn.configure(
            state="disabled"
        )

        self.disconnect_btn.configure(
            state="disabled"
        )

        self.pbar.start(
            10
        )

        self.set_status(
            (
                f"Uploading "
                f"{os.path.basename(py_path)} "
                f"to {drv}..."
            ),
            BLUE
        )

        threading.Thread(
            target=self._worker,
            args=(
                py_path,
                drv
            ),
            daemon=True
        ).start()


    # ========================================================
    # UPLOAD WORKER
    # ========================================================

    def _worker(
        self,
        py_path,
        drv
    ):

        try:

            output = uflash_flash_cli(
                py_path,
                drv
            )

            self.after(
                0,
                self._done_ok,
                output,
                drv
            )

        except Exception as error:

            self.after(
                0,
                self._done_err,
                str(error)
            )


    # ========================================================
    # UPLOAD SUCCESS
    # ========================================================

    def _done_ok(
        self,
        output,
        drv
    ):

        self.pbar.stop()

        self.uploading = False

        self.btn.configure(
            state="normal"
        )

        self.browse_btn.configure(
            state="normal"
        )

        self.refresh_btn.configure(
            state="normal"
        )

        self.connect_btn.configure(
            state="normal"
        )

        self.disconnect_btn.configure(
            state="normal"
        )

        self.set_status(
            f"Upload complete • {drv}",
            GREEN
        )

        if output:

            self.append_console(
                "\n[uflash]\n"
                + output
                + "\n"
            )

        self.append_console(
            "\n[Upload complete. "
            "Select your serial port and click Connect.]\n"
        )


    # ========================================================
    # UPLOAD ERROR
    # ========================================================

    def _done_err(
        self,
        error
    ):

        self.pbar.stop()

        self.uploading = False

        self.btn.configure(
            state="normal"
        )

        self.browse_btn.configure(
            state="normal"
        )

        self.refresh_btn.configure(
            state="normal"
        )

        self.connect_btn.configure(
            state="normal"
        )

        self.disconnect_btn.configure(
            state="normal"
        )

        self.set_status(
            "Upload failed.",
            RED
        )

        messagebox.showerror(
            "Upload failed",
            error
        )


    # ========================================================
    # CONNECT SERIAL
    # ========================================================

    def connect_serial(
        self,
        silent=False
    ):

        if serial is None:

            if not silent:

                messagebox.showerror(
                    "Missing pyserial",
                    (
                        "pyserial is not installed.\n\n"
                        "Install it with:\n\n"
                        f'"{sys.executable}" -m pip install pyserial'
                    )
                )

            return False

        # ----------------------------------------------------
        # READ EXACTLY WHAT THE USER SELECTED
        # ----------------------------------------------------

        choice = self.serial_choice.get().strip()

        port = self.serial_map.get(
            choice
        )

        # ----------------------------------------------------
        # Do NOT fall back to COM1 or another port.
        # ----------------------------------------------------

        if not port:

            if not silent:

                messagebox.showerror(
                    "Serial port",
                    (
                        "Please select a serial port "
                        "from the dropdown first."
                    )
                )

            return False

        # ----------------------------------------------------
        # Already connected to selected port
        # ----------------------------------------------------

        if (
            self.serial_connection
            and
            self.serial_connection.is_open
        ):

            current_port = (
                self.serial_connection.port
            )

            if current_port == port:

                self.set_serial_status(
                    f"Connected • {port}",
                    GREEN
                )

                return True

            # Different port: disconnect first.

            self.disconnect_serial(
                silent=True
            )

        # ----------------------------------------------------
        # Connect to EXACT selected port
        # ----------------------------------------------------

        try:

            connection = serial.Serial(
                port=port,
                baudrate=SERIAL_BAUD,
                timeout=0.2,
                write_timeout=1
            )

            self.serial_connection = connection

            self.serial_running = True

            self.serial_thread = threading.Thread(
                target=self._serial_reader,
                daemon=True
            )

            self.serial_thread.start()

            self.set_serial_status(
                f"Connected • {port}",
                GREEN
            )

            self.append_console(
                f"\n[Connected to {port} @ {SERIAL_BAUD}]\n"
            )

            return True

        except Exception as error:

            self.serial_connection = None

            self.serial_running = False

            self.set_serial_status(
                f"Failed to connect to {port}",
                RED
            )

            if not silent:

                messagebox.showerror(
                    "Serial connection failed",
                    (
                        f"Could not connect to {port}.\n\n"
                        f"{error}"
                    )
                )

            return False


    # ========================================================
    # DISCONNECT SERIAL
    # ========================================================

    def disconnect_serial(
        self,
        silent=False
    ):

        self.serial_running = False

        connection = self.serial_connection

        self.serial_connection = None

        if connection:

            try:
                connection.close()

            except Exception:
                pass

        self.set_serial_status(
            "Disconnected",
            TEXT_SECONDARY
        )

        if not silent:

            self.append_console(
                "\n[Serial disconnected]\n"
            )


    # ========================================================
    # SERIAL READER
    # ========================================================

    def _serial_reader(self):

        while self.serial_running:

            connection = self.serial_connection

            if connection is None:
                break

            try:

                if not connection.is_open:
                    break

                waiting = connection.in_waiting

                if waiting:

                    data = connection.read(
                        waiting
                    )

                    if data:

                        text = data.decode(
                            "utf-8",
                            errors="replace"
                        )

                        self.after(
                            0,
                            self.append_console,
                            text
                        )

                else:

                    time.sleep(
                        0.03
                    )

            except Exception as error:

                if self.serial_running:

                    self.after(
                        0,
                        self._serial_error,
                        str(error)
                    )

                break


    # ========================================================
    # SERIAL ERROR
    # ========================================================

    def _serial_error(
        self,
        error
    ):

        self.serial_running = False

        connection = self.serial_connection

        self.serial_connection = None

        if connection:

            try:
                connection.close()

            except Exception:
                pass

        self.set_serial_status(
            "Serial connection lost",
            RED
        )

        self.append_console(
            f"\n[Serial error: {error}]\n"
        )


    # ========================================================
    # CONSOLE
    # ========================================================

    def append_console(
        self,
        text
    ):

        try:

            self.console.insert(
                "end",
                text
            )

            self.console.see(
                "end"
            )

        except tk.TclError:
            pass


    # ========================================================
    # CLEAR CONSOLE
    # ========================================================

    def clear_console(self):

        self.console.delete(
            "1.0",
            "end"
        )


    # ========================================================
    # SEND BYTES
    # ========================================================

    def send_bytes(
        self,
        data
    ):

        connection = self.serial_connection

        if (
            connection is None
            or
            not connection.is_open
        ):

            messagebox.showwarning(
                "Not connected",
                (
                    "The serial console is not connected.\n\n"
                    "Select the correct COM port and "
                    "click Connect."
                )
            )

            return False

        try:

            with self.serial_lock:

                connection.write(
                    data
                )

                connection.flush()

            return True

        except Exception as error:

            self.append_console(
                f"\n[Send error: {error}]\n"
            )

            return False


    # ========================================================
    # SEND COMMAND
    # ========================================================

    def send_command_event(
        self,
        event
    ):

        self.send_command()

        return "break"


    def send_command(self):

        command = self.command_entry.get()

        if not command:
            return

        if (
            self.serial_connection is None
            or
            not self.serial_connection.is_open
        ):

            messagebox.showwarning(
                "Not connected",
                (
                    "Select the correct serial port "
                    "and click Connect first."
                )
            )

            return

        # Show command locally.

        self.append_console(
            f">>> {command}\n"
        )

        success = self.send_bytes(
            (
                command + "\r\n"
            ).encode(
                "utf-8"
            )
        )

        if success:

            self.command_entry.delete(
                0,
                "end"
            )


    # ========================================================
    # INTERRUPT PROGRAM
    # ========================================================

    def interrupt_program(self):

        if self.send_bytes(
            b"\x03"
        ):

            self.append_console(
                "\n[Ctrl+C sent]\n"
            )


    # ========================================================
    # ENTER REPL
    # ========================================================

    def enter_repl(self):

        if (
            self.serial_connection is None
            or
            not self.serial_connection.is_open
        ):

            messagebox.showwarning(
                "Not connected",
                (
                    "Select the correct serial port "
                    "and click Connect first."
                )
            )

            return

        self.append_console(
            "\n[Entering MicroPython REPL...]\n"
        )

        # Ctrl+C interrupts the running program.

        self.send_bytes(
            b"\x03"
        )

        time.sleep(
            0.15
        )

        # Another Ctrl+C makes sure the program is stopped.

        self.send_bytes(
            b"\x03"
        )

        time.sleep(
            0.15
        )

        # Enter.

        self.send_bytes(
            b"\r\n"
        )


    # ========================================================
    # SOFT RESET
    # ========================================================

    def soft_reset(self):

        if self.send_bytes(
            b"\x04"
        ):

            self.append_console(
                "\n[Soft reset requested]\n"
            )


    # ========================================================
    # CLOSE
    # ========================================================

    def on_close(self):

        self.serial_running = False

        connection = self.serial_connection

        self.serial_connection = None

        if connection:

            try:
                connection.close()

            except Exception:
                pass

        self.destroy()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    app = App()

    app.mainloop()
