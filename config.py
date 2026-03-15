# config.py
# Semua pengaturan default NutShaker ada di sini.
# Ubah nilai-nilai ini sesuai kebutuhan tanpa menyentuh kode lain.

# ------------------------------------------------------------------
# Pengaturan Serial — default untuk scan otomatis
# ------------------------------------------------------------------

DEFAULT_BAUDRATES  = [9600, 19200, 38400, 115200, 4800, 57600, 2400, 1200]
DEFAULT_SLAVE_IDS  = list(range(1, 248))
SERIAL_TIMEOUT     = 1.0
INTER_FRAME_DELAY  = 0.05
MAX_WORKERS        = 8

# ------------------------------------------------------------------
# Pengaturan TCP / UDP
# ------------------------------------------------------------------

TCP_MODBUS_PORT         = 502
TCP_TIMEOUT             = 2.0
UDP_TIMEOUT             = 1.0
DEFAULT_NETWORK_TIMEOUT = 0.5

# ------------------------------------------------------------------
# Konfigurasi serial umum — dicoba saat auto-detect
# Format: (bytesize, parity, stopbits)
# ------------------------------------------------------------------

COMMON_SERIAL_CONFIGS = [
    (8, "N", 1),   # 8N1 — standar Modbus RTU, ~90% perangkat
    (8, "E", 1),   # 8E1 — umum di meter listrik & perangkat Eropa
    (8, "N", 2),   # 8N2 — PLC Siemens, Mitsubishi tertentu
    (8, "O", 1),   # 8O1 — jarang
    (7, "E", 1),   # 7E1 — standar Modbus ASCII
    (7, "N", 2),   # 7N2 — sangat jarang
    (7, "O", 1),   # 7O1 — sangat jarang
]

BAUDRATE_PRIORITY = [9600, 19200, 38400, 115200, 4800, 57600, 2400, 1200]

# ------------------------------------------------------------------
# Scan Broadcast FC=0xE0
# ------------------------------------------------------------------

SUB_FUNCTIONS      = ["00", "01", "02", "03", "10", "11", "20", "30"]
PADDING_VARIANTS   = ["000000", "0000", "00", ""]
OTHER_FC           = [0x01, 0x02, 0x04, 0x05, 0x06, 0x0F, 0x10]
OTHER_FC_TEST_SIDS = [1, 2, 247]

# ------------------------------------------------------------------
# Referensi label untuk GUI
# ------------------------------------------------------------------

PARITY_OPTIONS = {
    "N": "None   — tidak ada bit paritas (paling umum)",
    "E": "Even   — paritas genap",
    "O": "Odd    — paritas ganjil",
    "M": "Mark   — bit paritas selalu 1",
    "S": "Space  — bit paritas selalu 0",
}

MODE_OPTIONS = {
    "RTU":   "RTU   — biner, CRC-16, efisien (standar)",
    "ASCII": "ASCII — hex-text, LRC, mudah di-debug",
}

STOPBITS_OPTIONS = {1: "1", 1.5: "1.5", 2: "2"}

# ------------------------------------------------------------------
# Tampilan GUI
# ------------------------------------------------------------------

COLOR = {
    "bg":        "#0D1117",
    "panel":     "#161B22",
    "entry_bg":  "#1C2128",
    "border":    "#30363D",
    "green":     "#3FB950",
    "green_dim": "#238636",
    "amber":     "#D29922",
    "red":       "#F85149",
    "blue":      "#58A6FF",
    "purple":    "#BC8CFF",
    "text":      "#E6EDF3",
    "text_dim":  "#8B949E",
}

FONT = {
    "mono":    ("Consolas", 9),
    "sans":    ("Segoe UI", 9),
    "heading": ("Segoe UI", 11, "bold"),
    "small":   ("Segoe UI", 8),
    "label":   ("Segoe UI", 7, "bold"),
}
