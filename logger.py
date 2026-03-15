# logger.py
# Pengaturan sistem logging NutShaker.
#
# Setiap sesi scan punya file log sendiri di ~/Downloads supaya
# kamu bisa lihat ulang apa yang terjadi, termasuk semua byte
# mentah yang dikirim dan diterima (level DEBUG).

import logging
import os
from datetime import datetime

# Nama logger yang dipakai di seluruh aplikasi.
# Menggunakan satu nama terpusat supaya semua handler bisa dikontrol
# dari satu tempat.
LOGGER_NAME = "NutShaker"

# Format pesan log: waktu, level, lalu pesan.
LOG_FORMAT  = "%(asctime)s  [%(levelname)-8s]  %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_file: str | None = None) -> logging.Logger:
    """
    Buat dan kembalikan logger siap pakai.

    Selalu mencatat ke konsol (INFO ke atas).
    Kalau log_file diberikan, juga mencatat ke file (DEBUG ke atas —
    artinya semua traffic TX/RX hex juga tersimpan).

    Kalau file log gagal dibuat (misalnya tidak ada izin),
    aplikasi tetap berjalan, cuma tanpa pencatatan ke file.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()  # reset supaya tidak dobel kalau dipanggil ulang

    fmt = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATEFMT)

    # Handler ke konsol — hanya tampilkan INFO ke atas supaya tidak banjir
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # Handler ke file — simpan semua termasuk DEBUG (byte mentah TX/RX)
    if log_file:
        try:
            os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except OSError as e:
            logger.warning(f"Tidak bisa buat file log '{log_file}': {e}")
            logger.warning("Scan tetap berjalan, tapi log tidak tersimpan ke file.")

    return logger


def default_log_path() -> str:
    """
    Buat path default untuk file log di folder ~/Downloads.

    Format nama file: nutshaker_YYYYMMDD_HHMMSS.log
    Setiap sesi dapat file log sendiri supaya tidak saling timpa.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    return os.path.join(downloads, f"nutshaker_{timestamp}.log")
