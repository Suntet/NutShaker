"""
gui.py — Antarmuka grafis (GUI) NutShaker berbasis tkinter.

Struktur UI:
  ┌─ Header ──────────────────────────────────────────────────┐
  │ NutShaker                          v2.0              │
  ├─ Sidebar ───────────┬─ Workspace ───────────────────────── ┤
  │ Port                │ [Tab: Hasil Scan] [Tab: Log]        │
  │ Baudrate            │  ┌─ Treeview / Log viewer ────────┐ │
  │ Slave ID Range      │  └───────────────────────────────┘  │
  │ Opsi Tes            │  Progress bar                       │
  │ ─────────────────── │                                     │
  │ Mulai / Stop        │                                     │
  │ Export / Bersihkan  │                                     │
  └─────────────────────┴─────────────────────────────────────┘
  ├─ Status bar ──────────────────────────────────────────────┤
"""

import logging
import os
import threading
import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from queue import Empty, Queue
from tkinter import messagebox

import serial.tools.list_ports

from config    import (DEFAULT_BAUDRATES, COLOR as C, FONT as F,
                       COMMON_SERIAL_CONFIGS, BAUDRATE_PRIORITY,
                       PARITY_OPTIONS, MODE_OPTIONS, STOPBITS_OPTIONS,
                       TCP_MODBUS_PORT)
from export    import export_report
from logger    import setup_logging, default_log_path
from scanner   import ModbusScanner
from query     import QuerySender, FrameBuilder, FC_INFO, format_parsed
from transport import SerialConfig, TcpConfig, UdpConfig


class ModbusScanGUI:
    """
    Antarmuka grafis lengkap NutShaker.

    Semua operasi scan berjalan di thread daemon terpisah.
    Komunikasi thread → GUI dilakukan via _gui_queue + polling root.after(40ms).
    """

    def __init__(self, root: tk.Tk):
        self.root         = root
        self._results:    list[dict]            = []
        self._scanner:    ModbusScanner | None  = None
        self._scan_thread: threading.Thread | None = None
        self._gui_queue:  Queue                 = Queue()

        # Logger + file log di Downloads
        self._log_file = default_log_path()
        self.logger    = setup_logging(self._log_file)

        self._setup_window()
        self._build_ui()
        self._refresh_ports()
        self._process_queue()   

    # ── Konfigurasi Jendela ───────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.root.title("NutShaker")
        self.root.geometry("1200x820")
        self.root.minsize(900, 620)
        self.root.configure(bg=C["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Bangun Seluruh UI ─────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_header()

        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_sidebar(body)
        self._build_workspace(body)
        self._build_statusbar()

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        hdr = tk.Frame(self.root, bg=C["panel"], height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(
            hdr, text="NutShaker",
            font=("Segoe UI", 14, "bold"), bg=C["panel"], fg=C["green"],
        ).pack(side="left", padx=18, pady=10)

        tk.Label(
            hdr, text="Modbus RTU Scanner  ·  v2.0",
            font=F["small"], bg=C["panel"], fg=C["text_dim"],
        ).pack(side="left", padx=4)

        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _build_sidebar(self, parent: tk.Frame) -> None:
        sb = tk.Frame(parent, bg=C["panel"], width=290)
        sb.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=8)
        sb.pack_propagate(False)

        # ── Protokol ──────────────────────────────────────────────────────────
        self._section_label(sb, "Protokol")
        self.protocol_var = tk.StringVar(value="serial")
        proto_frame = tk.Frame(sb, bg=C["panel"])
        proto_frame.pack(fill="x", padx=10, pady=(0, 4))
        for val, lbl, col in [
            ("serial", "Serial (RS-232/422/485)", C["green"]),
            ("tcp",    "Modbus TCP",               C["blue"]),
            ("udp",    "Modbus UDP",               C["purple"]),
        ]:
            tk.Radiobutton(
                proto_frame, text=lbl, variable=self.protocol_var, value=val,
                command=self._on_protocol_change,
                bg=C["panel"], fg=col, selectcolor=C["entry_bg"],
                activebackground=C["panel"], activeforeground=col,
                font=F["sans"], anchor="w",
            ).pack(fill="x")

        # ── Panel Serial ──────────────────────────────────────────────────────
        self.serial_panel = tk.Frame(sb, bg=C["panel"])
        self.serial_panel.pack(fill="x")

        self._section_label(self.serial_panel, "Port Serial")
        port_frame = tk.Frame(self.serial_panel, bg=C["panel"])
        port_frame.pack(fill="x", padx=10, pady=(0, 2))
        self.port_listbox = tk.Listbox(
            port_frame, bg=C["entry_bg"], fg=C["text"],
            selectbackground=C["green_dim"], font=F["mono"],
            height=3, bd=0,
            highlightthickness=1, highlightbackground=C["border"],
            highlightcolor=C["green"], selectmode="extended",
        )
        sb_scrollbar = tk.Scrollbar(port_frame, command=self.port_listbox.yview)
        sb_scrollbar.pack(side="right", fill="y")
        self.port_listbox.config(yscrollcommand=sb_scrollbar.set)
        self.port_listbox.pack(side="left", fill="both", expand=True)
        self._btn(self.serial_panel, "\u21bb  Refresh Port", self._refresh_ports, C["blue"]).pack(
            fill="x", padx=10, pady=2)

        self._section_label(self.serial_panel, "Baudrate")
        self.baud_vars: dict[int, tk.BooleanVar] = {}
        baud_frame = tk.Frame(self.serial_panel, bg=C["panel"])
        baud_frame.pack(fill="x", padx=10, pady=(0, 2))
        for idx, baud in enumerate(DEFAULT_BAUDRATES):
            var = tk.BooleanVar(value=(baud == 9600))
            self.baud_vars[baud] = var
            tk.Checkbutton(
                baud_frame, text=f"{baud:>7,}", variable=var,
                bg=C["panel"], fg=C["text"], selectcolor=C["entry_bg"],
                activebackground=C["panel"], activeforeground=C["green"],
                font=F["mono"], anchor="w",
            ).grid(row=idx // 2, column=idx % 2, sticky="w")

        # Mode RTU/ASCII, Bytesize, Parity, Stopbits
        self._section_label(self.serial_panel, "Parameter Serial")
        sp = tk.Frame(self.serial_panel, bg=C["panel"])
        sp.pack(fill="x", padx=10, pady=(0, 2))

        # Row 1: Mode + Bytesize
        r1 = tk.Frame(sp, bg=C["panel"])
        r1.pack(fill="x", pady=1)
        tk.Label(r1, text="Mode", font=F["small"], bg=C["panel"], fg=C["text_dim"]).pack(side="left")
        self.mode_var = ttk.Combobox(r1, width=8, font=F["mono"], state="readonly",
            values=["RTU", "ASCII"])
        self.mode_var.set("RTU")
        self.mode_var.pack(side="left", padx=(2, 8))
        tk.Label(r1, text="Bit", font=F["small"], bg=C["panel"], fg=C["text_dim"]).pack(side="left")
        self.bytesize_var = ttk.Combobox(r1, width=3, font=F["mono"], state="readonly",
            values=["8", "7"])
        self.bytesize_var.set("8")
        self.bytesize_var.pack(side="left", padx=2)

        # Row 2: Parity + Stopbits
        r2 = tk.Frame(sp, bg=C["panel"])
        r2.pack(fill="x", pady=1)
        tk.Label(r2, text="Parity", font=F["small"], bg=C["panel"], fg=C["text_dim"]).pack(side="left")
        self.parity_var = ttk.Combobox(r2, width=7, font=F["mono"], state="readonly",
            values=["N - None", "E - Even", "O - Odd", "M - Mark", "S - Space"])
        self.parity_var.set("N - None")
        self.parity_var.pack(side="left", padx=(2, 8))
        tk.Label(r2, text="Stop", font=F["small"], bg=C["panel"], fg=C["text_dim"]).pack(side="left")
        self.stopbits_var = ttk.Combobox(r2, width=4, font=F["mono"], state="readonly",
            values=["1", "1.5", "2"])
        self.stopbits_var.set("1")
        self.stopbits_var.pack(side="left", padx=2)

        # Row 3: DTR + RTS
        r3 = tk.Frame(sp, bg=C["panel"])
        r3.pack(fill="x", pady=1)
        self.dtr_var = tk.BooleanVar(value=False)
        self.rts_var = tk.BooleanVar(value=False)
        for text, var in [("DTR", self.dtr_var), ("RTS", self.rts_var)]:
            tk.Checkbutton(r3, text=text, variable=var,
                bg=C["panel"], fg=C["text_dim"], selectcolor=C["entry_bg"],
                activebackground=C["panel"], activeforeground=C["green"],
                font=F["sans"]).pack(side="left", padx=(0, 8))

        # ── Panel TCP/UDP ──────────────────────────────────────────────────────
        self.network_panel = tk.Frame(sb, bg=C["panel"])
        # (tidak di-pack dulu — muncul saat pilih TCP/UDP)

        self._section_label(self.network_panel, "Target Jaringan")
        np = tk.Frame(self.network_panel, bg=C["panel"])
        np.pack(fill="x", padx=10, pady=(0, 4))

        for row_data in [
            ("Host / IP", "tcp_host",    "192.168.1.1",  20),
            ("Port",      "tcp_port_e",  "502",           6),
            ("Unit ID",   "tcp_unit_e",  "1",             6),
        ]:
            lbl, attr, default, width = row_data
            rw = tk.Frame(np, bg=C["panel"])
            rw.pack(fill="x", pady=1)
            tk.Label(rw, text=lbl, font=F["small"], bg=C["panel"],
                     fg=C["text_dim"], width=8, anchor="w").pack(side="left")
            e = self._entry(rw, default, width=width)
            e.pack(side="left", padx=2)
            setattr(self, attr, e)

        # Scan range jaringan
        rnet = tk.Frame(np, bg=C["panel"])
        rnet.pack(fill="x", pady=1)
        tk.Label(rnet, text="Range", font=F["small"], bg=C["panel"],
                 fg=C["text_dim"], width=8, anchor="w").pack(side="left")
        self.net_range = self._entry(rnet, "192.168.1.1/24", width=18)
        self.net_range.pack(side="left", padx=2)

        self.scan_range_var = tk.BooleanVar(value=False)
        tk.Checkbutton(np, text="Scan seluruh subnet",
            variable=self.scan_range_var,
            bg=C["panel"], fg=C["amber"], selectcolor=C["entry_bg"],
            activebackground=C["panel"], activeforeground=C["amber"],
            font=F["sans"]).pack(anchor="w")

        # ── Slave ID (shared) ──────────────────────────────────────────────────
        self._section_label(sb, "Slave / Unit ID Range")
        sid_row = tk.Frame(sb, bg=C["panel"])
        sid_row.pack(fill="x", padx=10, pady=(0, 4))
        for lbl, default, attr in [("Min:", "1", "sid_min"), ("Max:", "247", "sid_max")]:
            tk.Label(sid_row, text=lbl, bg=C["panel"], fg=C["text_dim"],
                     font=F["sans"]).pack(side="left")
            entry = self._entry(sid_row, default, width=5)
            entry.pack(side="left", padx=4)
            setattr(self, attr, entry)

        # ── Opsi ──────────────────────────────────────────────────────────────
        self._section_label(sb, "Opsi Pengujian")
        self.opt_broadcast = tk.BooleanVar(value=True)
        self.opt_other_fc  = tk.BooleanVar(value=True)
        self.opt_autodetect = tk.BooleanVar(value=False)
        for text, var, col in [
            ("Broadcast FC=0xE0 (Assign ID)",          self.opt_broadcast,  C["text"]),
            ("Function Code Lain (FC01/02/04–10)",     self.opt_other_fc,   C["text"]),
            ("Auto-detect konfigurasi serial (lambat)", self.opt_autodetect, C["amber"]),
        ]:
            tk.Checkbutton(sb, text=text, variable=var,
                bg=C["panel"], fg=col, selectcolor=C["entry_bg"],
                activebackground=C["panel"], activeforeground=C["green"],
                font=F["sans"], anchor="w").pack(fill="x", padx=10, pady=1)

        # ── Tombol aksi ───────────────────────────────────────────────────────
        tk.Frame(sb, bg=C["border"], height=1).pack(fill="x", padx=10, pady=8)

        self.btn_scan   = self._btn(sb, "\u25b6  Mulai Scan",     self._start_scan,  C["green"])
        self.btn_stop   = self._btn(sb, "\u25a0  Stop",           self._stop_scan,   C["red"])
        self.btn_export = self._btn(sb, "\u2b07  Export Laporan", self._export,      C["amber"])
        btn_clear       = self._btn(sb, "\U0001f5d1  Bersihkan",  self._clear_all)

        for btn in (self.btn_scan, self.btn_stop, self.btn_export, btn_clear):
            btn.pack(fill="x", padx=10, pady=3)

        self.btn_stop.config(state="disabled")
        self.btn_export.config(state="disabled")

    def _on_protocol_change(self) -> None:
        """Tampilkan panel yang relevan saat protokol berubah."""
        proto = self.protocol_var.get()
        if proto == "serial":
            self.network_panel.pack_forget()
            self.serial_panel.pack(fill="x", before=self._find_section_after_proto())
        else:
            self.serial_panel.pack_forget()
            self.network_panel.pack(fill="x", before=self._find_section_after_proto())

    def _find_section_after_proto(self) -> tk.Widget | None:
        """Kembalikan widget pembatas setelah panel protokol."""
        # Fallback — pack di posisi default
        return None


    # ── Workspace (tab + progress) ────────────────────────────────────────────

    def _build_workspace(self, parent: tk.Frame) -> None:
        ws = tk.Frame(parent, bg=C["bg"])
        ws.grid(row=0, column=1, sticky="nsew", pady=8)
        ws.rowconfigure(0, weight=1)
        ws.columnconfigure(0, weight=1)

        self._configure_ttk_styles()

        notebook = ttk.Notebook(ws, style="Custom.TNotebook")
        notebook.grid(row=0, column=0, sticky="nsew", pady=(0, 6))

        results_tab = tk.Frame(notebook, bg=C["bg"])
        notebook.add(results_tab, text="  Hasil Scan  ")
        self._build_results_table(results_tab)

        query_tab = tk.Frame(notebook, bg=C["bg"])
        notebook.add(query_tab, text="  Query Manual  ")
        self._build_query_tab(query_tab)

        log_tab = tk.Frame(notebook, bg=C["bg"])
        notebook.add(log_tab, text="  Log  ")
        self._build_log_view(log_tab)

        # Progress
        prog = tk.Frame(ws, bg=C["bg"])
        prog.grid(row=1, column=0, sticky="ew")

        self.progress_label = tk.Label(
            prog, text="Siap.", font=F["mono"], bg=C["bg"], fg=C["text_dim"], anchor="w"
        )
        self.progress_label.pack(fill="x", pady=(0, 2))

        self.progressbar = ttk.Progressbar(
            prog, style="Green.Horizontal.TProgressbar",
            orient="horizontal", mode="determinate", maximum=100,
        )
        self.progressbar.pack(fill="x")

    def _configure_ttk_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Custom.TNotebook",         background=C["bg"],    borderwidth=0)
        style.configure("Custom.TNotebook.Tab",     background=C["panel"], foreground=C["text_dim"],
                         padding=[14, 6], font=F["sans"])
        style.map("Custom.TNotebook.Tab",
                  background=[("selected", C["bg"])],
                  foreground=[("selected", C["green"])])

        style.configure("Results.Treeview",
                         background=C["entry_bg"], foreground=C["text"],
                         fieldbackground=C["entry_bg"], borderwidth=0,
                         rowheight=22, font=F["mono"])
        style.configure("Results.Treeview.Heading",
                         background=C["panel"], foreground=C["text_dim"],
                         font=("Segoe UI", 9, "bold"), borderwidth=0)
        style.map("Results.Treeview", background=[("selected", C["green_dim"])])

        style.configure("Green.Horizontal.TProgressbar",
                         troughcolor=C["panel"], background=C["green"],
                         thickness=10, borderwidth=0)

    # ── Tabel Hasil ───────────────────────────────────────────────────────────

    def _build_results_table(self, parent: tk.Frame) -> None:
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        columns = ("Port", "Baud", "Tipe", "Slave ID", "FC", "CRC", "Detail", "Raw (hex)")
        widths  = [80,     70,     170,    70,          60,   50,    200,      260]

        frame = tk.Frame(parent, bg=C["bg"])
        frame.grid(row=0, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            frame, columns=columns, show="headings", style="Results.Treeview"
        )
        for col, w in zip(columns, widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, minwidth=40, anchor="w")

        vsb = tk.Scrollbar(frame, orient="vertical",   command=self.tree.yview)
        hsb = tk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.tree.tag_configure("ok",        foreground=C["green"])
        self.tree.tag_configure("exception", foreground=C["amber"])
        self.tree.tag_configure("broadcast", foreground=C["blue"])

    # ── Log Viewer ────────────────────────────────────────────────────────────

    # ── Query Manual Tab ─────────────────────────────────────────────────────

    def _build_query_tab(self, parent: tk.Frame) -> None:
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        self._query_history: list = []
        self._repeat_after_id = None

        # Form
        form = tk.Frame(parent, bg=C["panel"])
        form.grid(row=0, column=0, sticky="ew")

        # Row 0: Protokol
        r0 = tk.Frame(form, bg=C["panel"])
        r0.pack(fill="x", padx=10, pady=(8, 2))
        self._qlabel(r0, "Protokol")
        self.q_proto_var = tk.StringVar(value="serial")
        for val, lbl, col in [("serial","Serial","#3FB950"),("tcp","TCP","#58A6FF"),("udp","UDP","#BC8CFF")]:
            tk.Radiobutton(
                r0, text=lbl, variable=self.q_proto_var, value=val,
                bg=C["panel"], fg=col, selectcolor=C["entry_bg"],
                activebackground=C["panel"], activeforeground=col,
                font=F["sans"],
            ).pack(side="left", padx=(0, 8))

        # Row 0b: Mode, Bytesize (serial params dalam query tab)
        r0b = tk.Frame(form, bg=C["panel"])
        r0b.pack(fill="x", padx=10, pady=(0, 4))
        self._qlabel(r0b, "Mode")
        self.q_mode_var = ttk.Combobox(r0b, width=7, font=F["mono"], state="readonly",
            values=["RTU","ASCII"])
        self.q_mode_var.set("RTU")
        self.q_mode_var.pack(side="left", padx=(0,8))
        self._qlabel(r0b, "Bit")
        self.q_bytesize_var = ttk.Combobox(r0b, width=3, font=F["mono"], state="readonly",
            values=["8","7"])
        self.q_bytesize_var.set("8")
        self.q_bytesize_var.pack(side="left", padx=(0,8))
        self._qlabel(r0b, "Stop")
        self.q_stopbits_var = ttk.Combobox(r0b, width=4, font=F["mono"], state="readonly",
            values=["1","1.5","2"])
        self.q_stopbits_var.set("1")
        self.q_stopbits_var.pack(side="left", padx=(0,8))

        # Row 1: Port, Baud, Parity, Timeout
        r1 = tk.Frame(form, bg=C["panel"])
        r1.pack(fill="x", padx=10, pady=(2, 4))
        self._qlabel(r1, "Port")
        self.q_port = ttk.Combobox(r1, width=12, font=F["mono"], state="readonly")
        self.q_port.pack(side="left", padx=(0, 10))
        self._qlabel(r1, "Baudrate")
        self.q_baud = ttk.Combobox(r1, width=8, font=F["mono"], state="readonly",
            values=["1200","2400","4800","9600","19200","38400","57600","115200"])
        self.q_baud.set("9600")
        self.q_baud.pack(side="left", padx=(0, 10))
        self._qlabel(r1, "Parity")
        self.q_parity = ttk.Combobox(r1, width=10, font=F["mono"], state="readonly",
            values=["None (N)","Even (E)","Odd (O)","Mark (M)","Space (S)"])
        self.q_parity.set("None (N)")
        self.q_parity.pack(side="left", padx=(0, 10))
        # TCP/UDP fields (host, port, unit ID)
        self._qlabel(r1, "Host")
        self.q_host = self._qentry(r1, "192.168.1.1", width=14)
        self.q_host.pack(side="left", padx=(0, 4))
        self._qlabel(r1, "Port")
        self.q_net_port = self._qentry(r1, "502", width=5)
        self.q_net_port.pack(side="left", padx=(0, 4))
        self._qlabel(r1, "Unit ID")
        self.q_unit_id = self._qentry(r1, "1", width=4)
        self.q_unit_id.pack(side="left", padx=(0, 8))
        self._qlabel(r1, "Timeout (s)")
        self.q_timeout = self._qentry(r1, "1.0", width=5)
        self.q_timeout.pack(side="left", padx=(0, 6))
        tk.Button(r1, text="\u21bb", command=self._refresh_query_ports,
            bg=C["entry_bg"], fg=C["blue"], relief="flat", font=F["mono"],
            cursor="hand2", padx=6).pack(side="left")

        # Row 2: Slave ID, FC, Address, Qty
        r2 = tk.Frame(form, bg=C["panel"])
        r2.pack(fill="x", padx=10, pady=4)
        self._qlabel(r2, "Slave ID")
        self.q_slave = self._qentry(r2, "1", width=5)
        self.q_slave.pack(side="left", padx=(0, 10))
        self._qlabel(r2, "Function Code")
        fc_options = [f"{fc:#04x}  {info['name']}" for fc, info in FC_INFO.items()]
        self.q_fc = ttk.Combobox(r2, width=32, font=F["mono"], state="readonly",
            values=fc_options)
        self.q_fc.set(fc_options[2])
        self.q_fc.pack(side="left", padx=(0, 10))
        self.q_fc.bind("<<ComboboxSelected>>", self._on_fc_change)
        self._qlabel(r2, "Alamat")
        self.q_addr = self._qentry(r2, "0", width=7)
        self.q_addr.pack(side="left", padx=(0, 10))
        self._qlabel(r2, "Qty")
        self.q_qty = self._qentry(r2, "1", width=7)
        self.q_qty.pack(side="left", padx=(0, 6))
        self.q_qty_hint = tk.Label(r2, text="(jumlah register)",
            font=F["small"], bg=C["panel"], fg=C["text_dim"])
        self.q_qty_hint.pack(side="left")

        # Row 3: Values
        r3 = tk.Frame(form, bg=C["panel"])
        r3.pack(fill="x", padx=10, pady=4)
        self._qlabel(r3, "Nilai (write)")
        self.q_values = self._qentry(r3, "", width=34)
        self.q_values.pack(side="left", padx=(0, 6))
        tk.Label(r3, text="misal: 100 200  atau  0x0064 0x00C8",
            font=F["small"], bg=C["panel"], fg=C["text_dim"]).pack(side="left")

        # Row 4: Raw hex
        r4 = tk.Frame(form, bg=C["panel"])
        r4.pack(fill="x", padx=10, pady=(0, 4))
        self.q_raw_mode = tk.BooleanVar(value=False)
        tk.Checkbutton(r4, text="Mode Raw Hex  (abaikan form di atas, kirim frame langsung)",
            variable=self.q_raw_mode, command=self._on_raw_mode_toggle,
            bg=C["panel"], fg=C["text"], selectcolor=C["entry_bg"],
            activebackground=C["panel"], activeforeground=C["green"],
            font=F["sans"]).pack(side="left")
        self._qlabel(r4, "  Frame:")
        self.q_raw_hex = self._qentry(r4, "01 03 00 00 00 01", width=40)
        self.q_raw_hex.pack(side="left", padx=(0, 8))
        self.q_auto_crc = tk.BooleanVar(value=True)
        tk.Checkbutton(r4, text="Auto CRC",
            variable=self.q_auto_crc,
            bg=C["panel"], fg=C["text_dim"], selectcolor=C["entry_bg"],
            activebackground=C["panel"], activeforeground=C["green"],
            font=F["sans"]).pack(side="left")

        # Row 5: Send + repeat
        r5 = tk.Frame(form, bg=C["panel"])
        r5.pack(fill="x", padx=10, pady=(4, 8))
        self.btn_query_send = tk.Button(r5, text="\u25b6  Kirim Query",
            command=self._send_query,
            bg=C["green_dim"], fg=C["text"], activebackground=C["green"],
            font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
            padx=14, pady=6)
        self.btn_query_send.pack(side="left", padx=(0, 10))
        self._qlabel(r5, "Auto-repeat setiap")
        self.q_repeat_ms = self._qentry(r5, "1000", width=6)
        self.q_repeat_ms.pack(side="left", padx=(0, 4))
        tk.Label(r5, text="ms", font=F["sans"], bg=C["panel"], fg=C["text_dim"]).pack(side="left", padx=(0,8))
        self.q_repeat_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r5, text="Aktifkan", variable=self.q_repeat_var,
            command=self._on_repeat_toggle,
            bg=C["panel"], fg=C["amber"], selectcolor=C["entry_bg"],
            activebackground=C["panel"], activeforeground=C["amber"],
            font=F["sans"]).pack(side="left", padx=(0,16))
        tk.Button(r5, text="Hapus Riwayat", command=self._clear_query_history,
            bg=C["entry_bg"], fg=C["text_dim"], activebackground="#2D333B",
            font=F["sans"], relief="flat", cursor="hand2",
            padx=10, pady=5).pack(side="left")
        tk.Frame(form, bg=C["border"], height=1).pack(fill="x", padx=10)

        # Riwayat treeview
        hist = tk.Frame(parent, bg=C["bg"])
        hist.grid(row=1, column=0, sticky="nsew")
        hist.rowconfigure(1, weight=1)
        hist.columnconfigure(0, weight=1)

        tk.Label(hist, text="  Riwayat Query", font=("Segoe UI", 9, "bold"),
            bg="#0A0E14", fg=C["text_dim"], anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=4)

        hist_cols = ("#", "Waktu", "Port", "Baud", "Status", "TX (hex)", "RX (hex)", "Parse", "ms")
        hist_widths = [36, 82, 80, 60, 72, 200, 200, 360, 55]
        self.q_tree = ttk.Treeview(hist, columns=hist_cols, show="headings",
            style="Results.Treeview", selectmode="browse")
        for col, w in zip(hist_cols, hist_widths):
            self.q_tree.heading(col, text=col)
            self.q_tree.column(col, width=w, minwidth=30, anchor="w")
        q_vsb = tk.Scrollbar(hist, orient="vertical",   command=self.q_tree.yview)
        q_hsb = tk.Scrollbar(hist, orient="horizontal", command=self.q_tree.xview)
        self.q_tree.configure(yscrollcommand=q_vsb.set, xscrollcommand=q_hsb.set)
        self.q_tree.grid(row=1, column=0, sticky="nsew")
        q_vsb.grid(row=1, column=1, sticky="ns")
        q_hsb.grid(row=2, column=0, sticky="ew")
        self.q_tree.tag_configure("ok",  foreground=C["green"])
        self.q_tree.tag_configure("err", foreground=C["red"])
        self.q_tree.tag_configure("exc", foreground=C["amber"])
        self.q_tree.bind("<<TreeviewSelect>>", self._on_query_select)

        # Detail bar
        dbar = tk.Frame(parent, bg="#0A0E14")
        dbar.grid(row=2, column=0, sticky="ew")
        tk.Label(dbar, text="  Detail:", font=F["small"],
            bg="#0A0E14", fg=C["text_dim"]).pack(side="left", pady=2)
        self.q_detail_var = tk.StringVar(value="Pilih baris untuk detail lengkap")
        tk.Label(dbar, textvariable=self.q_detail_var, font=F["mono"],
            bg="#0A0E14", fg=C["text"], anchor="w", wraplength=1000
        ).pack(side="left", fill="x", expand=True, padx=4)

        self._refresh_query_ports()

    # ── Query helpers ─────────────────────────────────────────────────────────

    def _qlabel(self, parent: tk.Widget, text: str) -> tk.Label:
        lbl = tk.Label(parent, text=text, font=F["small"], bg=C["panel"], fg=C["text_dim"])
        lbl.pack(side="left", padx=(0, 4))
        return lbl

    def _qentry(self, parent: tk.Widget, default: str, **kw) -> tk.Entry:
        e = tk.Entry(parent, bg=C["entry_bg"], fg=C["text"],
            insertbackground=C["green"], relief="flat",
            highlightthickness=1, highlightbackground=C["border"],
            highlightcolor=C["green"], font=F["mono"], **kw)
        e.insert(0, default)
        return e

    def _refresh_query_ports(self) -> None:
        import serial.tools.list_ports as lp
        ports = [p.device for p in lp.comports()]
        self.q_port["values"] = ports
        if ports:
            self.q_port.set(ports[0])
        self._on_query_proto_change()

    def _on_query_proto_change(self) -> None:
        """Tampil/sembunyikan field sesuai protokol query."""
        proto = getattr(self, "q_proto_var", None)
        if proto is None:
            return
        p = proto.get()
        serial_fields  = getattr(self, "_q_serial_fields",  [])
        network_fields = getattr(self, "_q_network_fields", [])
        for w in serial_fields:
            w.pack(side="left", padx=(0, 6)) if p == "serial" else w.pack_forget()
        for w in network_fields:
            w.pack(side="left", padx=(0, 6)) if p != "serial" else w.pack_forget()

    def _on_fc_change(self, _event=None) -> None:
        fc_str = self.q_fc.get()
        fc_val = int(fc_str[:4], 16) if fc_str else 0x03
        info   = FC_INFO.get(fc_val, {})
        hints  = {
            "read":   f"(jumlah {info.get('unit','item')})",
            "write1": f"(nilai {info.get('unit','item')})",
            "writem": "(jumlah item)",
            "diag":   "(tidak dipakai)",
            "rwm":    "(jumlah read)",
        }
        self.q_qty_hint.config(text=hints.get(info.get("type",""), ""))

    def _on_raw_mode_toggle(self) -> None:
        self.q_raw_hex.config(state="normal" if self.q_raw_mode.get() else "disabled")

    def _on_repeat_toggle(self) -> None:
        if self.q_repeat_var.get():
            self._schedule_repeat()
        elif self._repeat_after_id:
            self.root.after_cancel(self._repeat_after_id)
            self._repeat_after_id = None

    def _schedule_repeat(self) -> None:
        if not self.q_repeat_var.get():
            return
        self._send_query()
        try:
            ms = max(100, int(self.q_repeat_ms.get()))
        except ValueError:
            ms = 1000
        self._repeat_after_id = self.root.after(ms, self._schedule_repeat)

    def _on_query_select(self, _event=None) -> None:
        sel = self.q_tree.selection()
        if not sel:
            return
        try:
            result = self._query_history[int(self.q_tree.item(sel[0], "values")[0]) - 1]
            self.q_detail_var.set(
                f"TX: {result.raw_tx}  |  RX: {result.raw_rx}  |  "
                f"{result.error_msg or 'OK'}  |  {format_parsed(result.parsed)}"
            )
        except (ValueError, IndexError):
            pass

    def _send_query(self) -> None:
        try:
            timeout = float(self.q_timeout.get())
        except ValueError:
            messagebox.showerror("Input", "Timeout harus angka.")
            return

        parity_map = {"None (N)": "N", "Even (E)": "E", "Odd (O)": "O",
                      "Mark (M)": "M", "Space (S)": "S"}

        # Pilih transport sesuai protokol yang dipilih di Query tab
        proto = getattr(self, "q_proto_var", None)
        proto = proto.get() if proto else "serial"

        try:
            if proto == "serial":
                port = self.q_port.get().strip()
                if not port:
                    messagebox.showwarning("Port", "Pilih port serial.")
                    return
                baud     = int(self.q_baud.get())
                parity   = parity_map.get(self.q_parity.get(), "N")
                mode_q   = getattr(self, "q_mode_var", None)
                mode_val = mode_q.get() if mode_q else "RTU"
                by_q     = getattr(self, "q_bytesize_var", None)
                st_q     = getattr(self, "q_stopbits_var", None)
                bytesize = int(by_q.get()) if by_q else 8
                stopbits = float(st_q.get()) if st_q else 1.0
                sender = QuerySender.from_serial(
                    port, baud, bytesize=bytesize, parity=parity,
                    stopbits=stopbits, mode=mode_val, timeout=timeout,
                )
            elif proto == "tcp":
                host = getattr(self, "q_host", None)
                pn   = getattr(self, "q_net_port", None)
                uid  = getattr(self, "q_unit_id", None)
                host = host.get().strip() if host else "127.0.0.1"
                pn   = int(pn.get()) if pn else 502
                uid  = int(uid.get()) if uid else 1
                sender = QuerySender.from_tcp(host, pn, uid, timeout=timeout)
            else:   # udp
                host = getattr(self, "q_host", None)
                pn   = getattr(self, "q_net_port", None)
                uid  = getattr(self, "q_unit_id", None)
                host = host.get().strip() if host else "127.0.0.1"
                pn   = int(pn.get()) if pn else 502
                uid  = int(uid.get()) if uid else 1
                sender = QuerySender.from_udp(host, pn, uid, timeout=timeout)
        except ValueError as e:
            messagebox.showerror("Input", str(e))
            return

        self.btn_query_send.config(state="disabled", text="Mengirim\u2026")

        def _do():
            try:
                if self.q_raw_mode.get():
                    result = sender.send_hex(
                        self.q_raw_hex.get(), auto_crc=self.q_auto_crc.get()
                    )
                else:
                    slave_id = int(self.q_slave.get())
                    fc       = int(self.q_fc.get()[:4], 16)
                    address  = int(self.q_addr.get(), 0)
                    qty      = int(self.q_qty.get(), 0)
                    raw_vals = self.q_values.get().strip()
                    values   = [int(v, 0) for v in raw_vals.split()] if raw_vals else []
                    result   = sender.send(slave_id, fc, address, qty, values)
            except Exception as e:
                from query import QueryResult
                result = QueryResult(
                    success=False, raw_tx="", raw_rx="",
                    parsed={}, error_msg=str(e),
                )
            self._gui_queue.put(lambda r=result: self._add_query_result(r))

        threading.Thread(target=_do, daemon=True).start()

    def _add_query_result(self, result) -> None:
        self.btn_query_send.config(state="normal", text="\u25b6  Kirim Query")
        self._query_history.append(result)
        idx = len(self._query_history)
        parsed_str = format_parsed(result.parsed) if result.parsed else result.error_msg
        if not result.success and result.error_msg and not result.parsed:
            status, tag = "ERROR", "err"
        elif result.parsed.get("is_exception"):
            status, tag = "EXCEPTION", "exc"
        else:
            status, tag = "OK", "ok"
        self.q_tree.insert("", "end", values=(
            idx, result.timestamp, self.q_port.get(), self.q_baud.get(),
            status, result.raw_tx, result.raw_rx, parsed_str,
            f"{result.duration_ms:.1f}",
        ), tags=(tag,))
        children = self.q_tree.get_children()
        if children:
            last = children[-1]
            self.q_tree.see(last)
            self.q_tree.selection_set(last)
            self._on_query_select()

    def _clear_query_history(self) -> None:
        self._query_history.clear()
        self.q_tree.delete(*self.q_tree.get_children())
        self.q_detail_var.set("Riwayat dibersihkan.")

    def _build_log_view(self, parent: tk.Frame) -> None:
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            parent, bg="#0A0E14", fg=C["text_dim"],
            font=F["mono"], wrap="none",
            insertbackground=C["green"], bd=0, state="disabled",
        )
        vsb = tk.Scrollbar(parent, command=self.log_text.yview)
        hsb = tk.Scrollbar(parent, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.log_text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.log_text.tag_config("INFO",    foreground=C["text"])
        self.log_text.tag_config("DEBUG",   foreground=C["text_dim"])
        self.log_text.tag_config("WARNING", foreground=C["amber"])
        self.log_text.tag_config("ERROR",   foreground=C["red"])
        self.log_text.tag_config("ok",      foreground=C["green"])
        self.log_text.tag_config("bcast",   foreground=C["blue"])

    # ── Status Bar ────────────────────────────────────────────────────────────

    def _build_statusbar(self) -> None:
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x", side="bottom")
        bar = tk.Frame(self.root, bg=C["panel"], height=26)
        bar.pack(fill="x", side="bottom")

        self.status_left = tk.Label(
            bar, text="Siap.", font=F["small"], bg=C["panel"], fg=C["text_dim"], anchor="w",
        )
        self.status_left.pack(side="left", padx=10)

        self.status_right = tk.Label(
            bar, text="", font=F["small"], bg=C["panel"], fg=C["text_dim"], anchor="e",
        )
        self.status_right.pack(side="right", padx=10)

    # ── Widget Helper ─────────────────────────────────────────────────────────

    def _section_label(self, parent: tk.Widget, title: str) -> None:
        f = tk.Frame(parent, bg=C["panel"])
        f.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(f, text=title.upper(), font=F["label"],
                 bg=C["panel"], fg=C["text_dim"]).pack(side="left")
        tk.Frame(f, bg=C["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(6, 0)
        )

    def _btn(self, parent: tk.Widget, text: str, cmd, color: str = "") -> tk.Button:
        return tk.Button(
            parent, text=text, command=cmd,
            bg=C["entry_bg"], fg=color or C["text_dim"],
            activebackground="#2D333B", activeforeground=color or C["text_dim"],
            font=F["sans"], relief="flat", cursor="hand2", pady=5,
        )

    def _entry(self, parent: tk.Widget, default: str, **kw) -> tk.Entry:
        e = tk.Entry(
            parent, bg=C["entry_bg"], fg=C["text"],
            insertbackground=C["green"], relief="flat",
            highlightthickness=1, highlightbackground=C["border"],
            highlightcolor=C["green"], font=F["mono"], **kw,
        )
        e.insert(0, default)
        return e

    # ── Aksi Sidebar ─────────────────────────────────────────────────────────

    def _refresh_ports(self) -> None:
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_listbox.delete(0, tk.END)
        for p in ports:
            self.port_listbox.insert(tk.END, p)
        if not ports:
            self.port_listbox.insert(tk.END, "(tidak ada port)")
        self._log_gui(
            f"Port serial terdeteksi: {ports or ['—']}", "INFO"
        )

    def _start_scan(self) -> None:
        # Validasi Slave ID range (shared semua protokol)
        try:
            sid_min = int(self.sid_min.get())
            sid_max = int(self.sid_max.get())
            assert 1 <= sid_min <= sid_max <= 247
        except (ValueError, AssertionError):
            messagebox.showerror("Slave ID", "Range harus 1–247, min ≤ max.")
            return

        proto = self.protocol_var.get()

        # Bangun config berdasarkan protokol yang dipilih
        config = self._build_scan_config(proto, sid_min, sid_max)
        if config is None:
            return   # error sudah ditampilkan di _build_scan_config

        # Reset UI
        self._results.clear()
        self.tree.delete(*self.tree.get_children())
        self._clear_log_widget()
        self.btn_scan.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_export.config(state="disabled")
        self.progressbar["value"] = 0
        self._set_status(f"Scanning [{proto.upper()}] …")

        self._attach_gui_log_handler()

        self._scanner = ModbusScanner(
            config=config, logger=self.logger,
            result_callback=self._on_result,
            progress_callback=self._on_progress,
            done_callback=self._on_done,
        )
        threading.Thread(target=self._scanner.scan, daemon=True).start()

    def _build_scan_config(self, proto: str, sid_min: int, sid_max: int) -> dict | None:
        slave_ids = list(range(sid_min, sid_max + 1))
        base = {
            "protocol":       proto,
            "slave_ids":      slave_ids,
            "test_broadcast": self.opt_broadcast.get(),
            "test_other_fc":  self.opt_other_fc.get(),
        }

        if proto == "serial":
            indices = self.port_listbox.curselection()
            if not indices:
                messagebox.showwarning("Port", "Pilih minimal satu port serial!")
                return None
            ports = [self.port_listbox.get(i) for i in indices]
            if "(tidak ada port)" in ports:
                messagebox.showerror("Error", "Tidak ada port serial yang tersedia.")
                return None
            baudrates = [b for b, v in self.baud_vars.items() if v.get()]
            if not baudrates:
                messagebox.showwarning("Baudrate", "Pilih minimal satu baudrate!")
                return None

            parity = self.parity_var.get()[0]   # ambil huruf pertama "N - None" → "N"
            mode   = self.mode_var.get()
            try:
                bytesize = int(self.bytesize_var.get())
                stopbits = float(self.stopbits_var.get())
            except ValueError:
                messagebox.showerror("Parameter", "Bytesize dan stopbits tidak valid.")
                return None

            if self.opt_autodetect.get():
                # Auto-detect: coba semua kombinasi serial config
                from config import COMMON_SERIAL_CONFIGS
                serial_cfgs = COMMON_SERIAL_CONFIGS
            else:
                serial_cfgs = [(bytesize, parity, stopbits)]

            base.update({
                "ports":          ports,
                "baudrates":      sorted(baudrates),
                "serial_configs": serial_cfgs,
                "mode":           mode,
                "dtr":            self.dtr_var.get(),
                "rts":            self.rts_var.get(),
            })

        else:  # TCP atau UDP
            if self.scan_range_var.get():
                hosts = self.net_range.get().strip()
            else:
                hosts = self.tcp_host.get().strip()
            if not hosts:
                messagebox.showwarning("Host", "Masukkan alamat IP atau subnet!")
                return None
            try:
                port_num = int(self.tcp_port_e.get())
                unit_id  = int(self.tcp_unit_e.get())
            except ValueError:
                messagebox.showerror("Port/Unit ID", "Port dan Unit ID harus angka.")
                return None
            base.update({
                "hosts":    hosts,
                "tcp_port": port_num,
                "unit_ids": list(range(1, unit_id + 1)),
            })

        return base

    def _stop_scan(self) -> None:
        if self._scanner:
            self._scanner.stop()
            self._log_gui("⛔ Permintaan stop dikirim …", "WARNING")
        self.btn_stop.config(state="disabled")

    def _export(self) -> None:
        if not self._results:
            messagebox.showinfo("Export", "Belum ada hasil untuk diekspor.")
            return
        try:
            csv_p, json_p, txt_p = export_report(self._results, self._log_file)
            out_dir = os.path.dirname(csv_p)
            messagebox.showinfo(
                "Export Berhasil",
                f"Laporan tersimpan di:\n{out_dir}\n\n"
                f"  📄 {os.path.basename(csv_p)}\n"
                f"  📄 {os.path.basename(json_p)}\n"
                f"  📄 {os.path.basename(txt_p)}"
            )
            self._log_gui(f"✅ Export → {out_dir}", "INFO")
        except Exception as e:
            messagebox.showerror("Export Gagal", str(e))
            self.logger.error(f"Export gagal: {e}", exc_info=True)

    def _clear_all(self) -> None:
        self._results.clear()
        self.tree.delete(*self.tree.get_children())
        self._clear_log_widget()
        self.progressbar["value"] = 0
        self.progress_label.config(text="")
        self.btn_export.config(state="disabled")
        self._set_status("Siap.")

    # ── Callback dari Scanner ─────────────────────────────────────────────────

    def _on_result(self, result: dict) -> None:
        """Dipanggil dari scan thread — post ke GUI queue."""
        self._gui_queue.put(lambda r=result: self._add_result_row(r))

    def _on_progress(self, pct: float, done: int, total: int) -> None:
        self._gui_queue.put(lambda p=pct, d=done, t=total: (
            self.progressbar.__setitem__("value", p),
            self.progress_label.config(text=f"Progres: {d}/{t}  ({p:.1f}%)")
        ))

    def _on_done(self, results: list[dict]) -> None:
        self._results = results
        def _finish():
            self.progressbar["value"] = 100
            self.progress_label.config(text="Selesai.")
            self.btn_scan.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.btn_export.config(state="normal" if results else "disabled")
            self._set_status(
                f"✨ Selesai — {len(results)} hasil",
                right=f"Log: {self._log_file}"
            )
            self._detach_gui_log_handler()
        self._gui_queue.put(_finish)

    # ── Update Widget ─────────────────────────────────────────────────────────

    def _add_result_row(self, r: dict) -> None:
        rtype  = r.get("type", "?")
        sid    = str(r.get("slave_id", "—"))
        fc_val = r.get("fc")
        fc_str = f"{fc_val:#04x}" if fc_val is not None else "—"
        crc    = "OK" if r.get("crc_valid") else "FAIL"

        if "register_values" in r:
            detail = f"Nilai={r['register_values']}"
        elif "exception_code" in r:
            detail = f"Exc={r['exception_code']:#04x}"
        elif r.get("sub_func"):
            detail = f"sub={r['sub_func']} pad={r.get('padding', '')!r}"
        else:
            detail = "—"

        tag = "exception" if "EXCEPTION" in rtype else ("broadcast" if "BROADCAST" in rtype else "ok")

        self.tree.insert("", "end", values=(
            r.get("port", "?"), r.get("baudrate", "?"),
            rtype, sid, fc_str, crc, detail,
            r.get("raw_response", ""),
        ), tags=(tag,))

        children = self.tree.get_children()
        if children:
            self.tree.see(children[-1])

        self.status_right.config(text=f"{len(self.tree.get_children())} hasil")

    def _set_status(self, left: str = "", right: str = "") -> None:
        self.status_left.config(text=left)
        if right:
            self.status_right.config(text=right)

    # ── Logging ke GUI ────────────────────────────────────────────────────────

    class _GuiLogHandler(logging.Handler):
        """Handler logging yang mengirim pesan ke GUI queue."""

        def __init__(self, callback):
            super().__init__()
            self._cb = callback

        def emit(self, record: logging.LogRecord) -> None:
            try:
                msg = self.format(record)
                self._cb(msg, record.levelname)
            except Exception:
                self.handleError(record)

    def _attach_gui_log_handler(self) -> None:
        handler = self._GuiLogHandler(
            lambda msg, lvl: self._gui_queue.put(
                lambda m=msg, l=lvl: self._log_gui(m, l)
            )
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  [%(levelname)-8s]  %(message)s",
            datefmt="%H:%M:%S",
        ))
        handler.setLevel(logging.DEBUG)
        handler.name = "_gui_handler"
        self.logger.addHandler(handler)
        self._gui_handler = handler

    def _detach_gui_log_handler(self) -> None:
        if hasattr(self, "_gui_handler"):
            self.logger.removeHandler(self._gui_handler)
            del self._gui_handler

    def _log_gui(self, msg: str, level: str = "INFO") -> None:
        tag = level
        if "✅" in msg or "AKTIF" in msg:
            tag = "ok"
        elif "📡" in msg or "BCAST" in msg:
            tag = "bcast"
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n", tag)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log_widget(self) -> None:
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    # ── Polling Loop ──────────────────────────────────────────────────────────

    def _process_queue(self) -> None:
        """Proses semua task di GUI queue. Dipanggil setiap 40ms via root.after."""
        try:
            while True:
                task = self._gui_queue.get_nowait()
                task()
        except Empty:
            pass
        self.root.after(40, self._process_queue)

    # ── Tutup Aplikasi ────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._scanner:
            self._scanner.stop()
        self.root.destroy()
