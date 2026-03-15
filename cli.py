# cli.py
# Mode terminal — jalankan NutShaker tanpa GUI.
# Berguna kalau kamu di server headless, ingin script otomasi,
# atau sekadar lebih suka terminal daripada klik-klik.

import os
import signal
import sys

import serial.tools.list_ports

from config  import DEFAULT_BAUDRATES, DEFAULT_SLAVE_IDS
from export  import export_report
from logger  import setup_logging, default_log_path
from scanner import ModbusScanner


def run_cli() -> None:
    """
    Scan semua port yang terdeteksi dengan semua baudrate default.

    Cara jalan:
        python NutShaker/ --cli

    Kamu bisa tekan Ctrl+C kapan saja — scan akan berhenti dengan bersih
    dan tetap mengekspor hasil yang sudah terkumpul sampai saat itu.
    """
    log_file = default_log_path()
    logger   = setup_logging(log_file)

    _print_banner(logger)

    # Cari port yang tersedia secara otomatis
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if not ports:
        logger.error(
            "Tidak ada port serial yang terdeteksi.\n"
            "Pastikan perangkat sudah terhubung dan driver sudah terinstall.\n"
            "Di Windows: cek Device Manager untuk nama port (COM3, COM4, dll.)\n"
            "Di Linux:   coba `ls /dev/ttyUSB*` atau `ls /dev/ttyS*`"
        )
        sys.exit(1)

    logger.info(f"Port ditemukan: {ports}")
    logger.info("Tekan Ctrl+C untuk berhenti kapan saja.\n")

    all_results: list[dict] = []
    last_progress_pct = -1  # supaya tidak print progres terlalu sering

    def on_progress(pct: float, done: int, total: int):
        nonlocal last_progress_pct
        # Print setiap 5% supaya tidak banjir tapi tetap informatif
        if int(pct / 5) > int(last_progress_pct / 5):
            logger.info(f"  Progres: {done}/{total} ({pct:.0f}%)")
            last_progress_pct = pct

    config = {
        "ports":          ports,
        "baudrates":      DEFAULT_BAUDRATES,
        "slave_ids":      DEFAULT_SLAVE_IDS,
        "test_broadcast": True,
        "test_other_fc":  True,
    }

    scanner = ModbusScanner(
        config            = config,
        logger            = logger,
        result_callback   = lambda r: all_results.append(r),
        progress_callback = on_progress,
    )

    # Tangani Ctrl+C supaya tidak kasih traceback yang menakutkan
    original_handler = signal.signal(signal.SIGINT, lambda s, f: (
        logger.warning("\nMenerima Ctrl+C — menghentikan scan..."),
        scanner.stop()
    ))

    try:
        scanner.scan()
    finally:
        signal.signal(signal.SIGINT, original_handler)

    # Export hasil
    if all_results:
        logger.info(f"\nDitemukan {len(all_results)} respons. Menyimpan laporan...")
        csv_p, json_p, txt_p = export_report(all_results, log_file)
        out_dir = os.path.dirname(csv_p)
        logger.info(f"\nLaporan tersimpan di: {out_dir}")
        logger.info(f"  • {os.path.basename(csv_p)}   ← buka di Excel")
        logger.info(f"  • {os.path.basename(json_p)}  ← untuk scripting")
        logger.info(f"  • {os.path.basename(txt_p)}   ← laporan teks lengkap")
        logger.info(f"  • {os.path.basename(log_file)} ← semua traffic TX/RX")
    else:
        logger.info(
            "\nTidak ada perangkat Modbus yang merespons.\n"
            "Tips: coba scan dengan range baudrate yang lebih spesifik,\n"
            "      atau periksa koneksi fisik perangkat."
        )

    logger.info("\nSelesai.")


def _print_banner(logger):
    logger.info("=" * 60)
    logger.info("  NutShaker v2.0 — Modbus RTU Scanner")
    logger.info("  https://github.com/yourusername/nutshaker")
    logger.info("=" * 60)
