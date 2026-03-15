# NutShaker 🔧

**Modbus RTU Scanner & Query Tool** — temukan perangkat Modbus di jaringan serial, uji function code, kirim query manual, dan ekspor laporan lengkap.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Apa Itu NutShaker?

Kalau kamu bekerja dengan perangkat industri, PLC, sensor, atau controller yang pakai protokol Modbus RTU, NutShaker bisa membantu:

- **Tidak tahu slave ID perangkatmu?** Scan otomatis 1–247.
- **Tidak tahu baudrate-nya?** Coba semua baudrate umum sekaligus.
- **Mau baca/tulis register?** Gunakan tab Query Manual.
- **Perlu dokumentasi hasil?** Export ke CSV, JSON, dan TXT.

---

## Tampilan

```
┌─ NutShaker ───────────────────────────────────────────────────┐
│ Sidebar          │ [Hasil Scan] [Query Manual] [Log]          │
│ ─ Port ────────  │                                            │
│ ☑ COM3           │  Port   Baud   Tipe          SID  Nilai   │
│ ─ Baudrate ───── │  COM3   9600   FC03_OK        1   [100]   │
│ ☑ 9600           │  COM3   9600   FC03_EXCEPTION  5   Exc=02  │
│ ☑ 19200          │                                            │
│ ─ Slave ID ───── │  ──────────────────────────────────────    │
│ Min: 1  Max: 247 │  Query Manual                              │
│                  │  Port: COM3  Baud: 9600  Slave: 1          │
│ [▶ Mulai Scan]   │  FC: 0x03 Read Holding  Alamat: 0  Qty: 5  │
│ [■ Stop]         │  [▶ Kirim]  hasil: Register(5): [1,2,3,4,5]│
│ [⬇ Export]       │                                            │
└──────────────────┴────────────────────────────────────────────┘
```

---

## Instalasi

**Persyaratan:** Python 3.10 atau lebih baru.

```bash
# 1. Clone atau download repository ini
git clone https://github.com/yourusername/nutshaker.git
cd nutshaker

# 2. Install dependensi (hanya satu!)
pip install pyserial

# 3. Jalankan
python nutshaker/
```

Tidak perlu virtual environment untuk penggunaan sederhana, tapi tentu saja dianjurkan untuk proyek yang lebih besar.

---

## Cara Menjalankan

Semua cara di bawah ini sama hasilnya — pakai yang paling nyaman:

```bash
python nutshaker/              # GUI (otomatis fallback ke CLI kalau tkinter tidak ada)
python nutshaker/ --cli        # Paksa mode terminal
python -m nutshaker            # Sama seperti baris pertama
python nutshaker/__main__.py   # Langsung dari file
```

> **Catatan nama folder:** Kamu bisa ganti nama folder `nutshaker` jadi apa saja (misalnya `NutShaker` atau `modbus_tool`) — aplikasinya tetap berjalan normal.

---

## Fitur

### 🔍 Scan Otomatis

Pindai semua perangkat Modbus yang terhubung dengan tiga jenis tes:

| Tes | Deskripsi | Slave yang Diuji |
|-----|-----------|-----------------|
| FC03 Read Holding Registers | Tes utama, hampir semua perangkat support ini | Semua 1–247 (paralel) |
| Broadcast FC=0xE0 (Assign ID) | Untuk perangkat dengan konfigurasi ID otomatis | Broadcast (addr 0) |
| Function Code Tambahan | FC01/02/04/05/06/0F/10 | Slave 1, 2, dan 247 |

### 📡 Query Manual

Kirim query Modbus interaktif dari tab "Query Manual":

- **Form terstruktur** — pilih FC dari dropdown, isi alamat dan quantity
- **Mode Raw Hex** — paste frame hex langsung, CRC bisa otomatis atau manual
- **Auto-repeat** — polling otomatis setiap N milidetik (cocok untuk monitoring)
- **Riwayat query** — semua query tersimpan dengan timestamp dan durasi round-trip

**Function code yang didukung di Query Manual:**

| FC | Nama | Keterangan |
|----|------|------------|
| 0x01 | Read Coils | Baca status coil (output digital) |
| 0x02 | Read Discrete Inputs | Baca input digital |
| 0x03 | Read Holding Registers | Baca register (paling umum) |
| 0x04 | Read Input Registers | Baca register read-only |
| 0x05 | Write Single Coil | Tulis satu coil ON/OFF |
| 0x06 | Write Single Register | Tulis satu register |
| 0x0F | Write Multiple Coils | Tulis banyak coil sekaligus |
| 0x10 | Write Multiple Registers | Tulis banyak register sekaligus |
| 0x11 | Report Slave ID | Minta informasi identitas slave |
| 0x17 | Read/Write Multiple Registers | Baca dan tulis bersamaan |

### 📋 Logging

Setiap sesi scan otomatis membuat file log di `~/Downloads`:

- **Level DEBUG** ke file — semua byte TX/RX dalam format hex tersimpan
- **Level INFO** ke konsol dan panel Log di GUI
- Pesan warning untuk exception response, error untuk kegagalan koneksi

### 📤 Export Laporan

Klik tombol **⬇ Export Laporan** atau jalankan dari CLI — tiga file langsung tersimpan ke `~/Downloads`:

| File | Format | Cocok Untuk |
|------|--------|-------------|
| `nutshaker_YYYYMMDD_HHMMSS.csv` | CSV | Excel, Google Sheets, database import |
| `nutshaker_YYYYMMDD_HHMMSS.json` | JSON | Scripting Python/JS, integrasi sistem |
| `nutshaker_YYYYMMDD_HHMMSS_report.txt` | Teks | Dokumentasi, laporan, arsip |

File TXT juga melampirkan isi log lengkap di bagian bawahnya.

---

## Struktur File

```
nutshaker/
├── __init__.py      # Versi dan metadata package
├── __main__.py      # Entry point — pilih GUI atau CLI otomatis
├── config.py        # Semua konstanta dan pengaturan default
├── crc.py           # Perhitungan CRC-16 Modbus RTU
├── logger.py        # Setup logging ke konsol dan file
├── tester.py        # Koneksi serial dan pengiriman frame Modbus
├── scanner.py       # Orkestrasi scan otomatis semua port × baudrate
├── query.py         # Query manual: FrameBuilder, ResponseParser, QuerySender
├── export.py        # Export hasil ke CSV, JSON, dan TXT
├── gui.py           # Antarmuka grafis tkinter
└── cli.py           # Mode terminal dengan Ctrl+C handler
```

---

## Konfigurasi

Edit `config.py` untuk menyesuaikan perilaku default:

```python
# Tambah baudrate tidak standar
DEFAULT_BAUDRATES = [9600, 38400, 115200, 250000]

# Scan hanya sebagian slave ID (lebih cepat)
DEFAULT_SLAVE_IDS = list(range(1, 32))

# Naikkan timeout kalau perangkat lambat
SERIAL_TIMEOUT = 2.0

# Lebih banyak thread = scan lebih cepat (tapi hati-hati beban CPU)
MAX_WORKERS = 16
```

---

## Contoh Pakai dari Script Python

Kamu bisa import modul NutShaker langsung ke script-mu:

```python
import sys
sys.path.insert(0, "/path/ke/nutshaker")

from query import QuerySender

sender = QuerySender("COM3", 9600)

# Baca 10 register mulai alamat 0 dari slave ID 1
result = sender.send(slave_id=1, fc=0x03, address=0, quantity=10)

if result.success:
    print(result.parsed["registers"])   # → [100, 200, 300, ...]
else:
    print(f"Gagal: {result.error_msg}")

# Kirim frame hex langsung
result = sender.send_hex("01 03 00 00 00 0A", auto_crc=True)
```

```python
from scanner import ModbusScanner
from logger  import setup_logging

logger  = setup_logging()
scanner = ModbusScanner(
    config={"ports": ["COM3"], "baudrates": [9600], "slave_ids": list(range(1, 10))},
    logger=logger,
    result_callback=lambda r: print(f"Ditemukan: {r}"),
)
results = scanner.scan()
```

---

## Troubleshooting

**`No module named 'serial'`**
```bash
pip install pyserial
```

**`Permission denied` di Linux/macOS**
```bash
sudo usermod -a -G dialout $USER   # Linux
# logout dan login kembali
```

**Port tidak muncul di daftar**
- Windows: buka Device Manager, cari "Ports (COM & LPT)"
- Linux: jalankan `ls /dev/ttyUSB* /dev/ttyS*`
- Pastikan kabel USB-to-serial sudah terinstall drivernya

**Tidak ada perangkat yang terdeteksi padahal sudah terhubung**
- Coba baudrate yang berbeda (perangkat industri sering pakai 19200 atau 38400)
- Periksa pengaturan parity (beberapa perangkat pakai Even parity)
- Pastikan GND kabel terhubung dengan benar

---

## Kontribusi

Pull request sangat disambut! Lihat [CONTRIBUTING.md](CONTRIBUTING.md) untuk panduan lengkapnya.

---

## Lisensi

MIT — bebas dipakai, dimodifikasi, dan didistribusikan. Lihat [LICENSE](LICENSE).
