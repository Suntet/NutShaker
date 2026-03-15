# export.py
# Simpan hasil scan ke file yang bisa dibuka di Excel, dibaca di teks editor,
# atau diproses oleh script lain.
#
# Tiga format sekaligus karena kebutuhan orang berbeda-beda:
#   CSV  — buka di Excel, Google Sheets, atau import ke database
#   JSON — proses lanjut dengan script Python/JS, format yang rapi
#   TXT  — laporan siap baca, plus log lengkap di bagian bawah

import csv
import json
import os
from collections import defaultdict
from datetime import datetime


def export_report(
    results:    list[dict],
    log_file:   str | None = None,
    output_dir: str | None = None,
) -> tuple[str, str, str]:
    """
    Ekspor hasil scan ke tiga file sekaligus.

    Semua file disimpan ke output_dir. Kalau tidak ditentukan,
    otomatis ke folder ~/Downloads supaya mudah ditemukan.

    Nama file memakai timestamp sesi scan supaya tidak saling timpa
    kalau kamu scan berkali-kali.

    Parameter:
        results    — List hasil dari ModbusScanner
        log_file   — Path file log yang akan dilampirkan ke TXT report
        output_dir — Folder tujuan (default: ~/Downloads)

    Mengembalikan tuple (csv_path, json_path, txt_path).
    """
    if output_dir is None:
        output_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(output_dir, exist_ok=True)

    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path  = os.path.join(output_dir, f"nutshaker_{ts}.csv")
    json_path = os.path.join(output_dir, f"nutshaker_{ts}.json")
    txt_path  = os.path.join(output_dir, f"nutshaker_{ts}_report.txt")

    _write_csv(results,  csv_path)
    _write_json(results, json_path)
    _write_txt(results,  txt_path, log_file)

    return csv_path, json_path, txt_path


def _write_csv(results: list[dict], path: str) -> None:
    """
    CSV dengan semua key sebagai kolom header.
    Key diurutkan alfabetis supaya konsisten antar sesi.
    Baris kosong dibuat kalau tidak ada hasil.
    """
    if not results:
        open(path, "w").close()
        return

    all_keys = sorted({key for row in results for key in row})
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


def _write_json(results: list[dict], path: str) -> None:
    """JSON dengan metadata di atas supaya konteks tidak hilang."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "tool":          "NutShaker",
            "version":       "2.0.0",
            "exported_at":   datetime.now().isoformat(timespec="seconds"),
            "total_results": len(results),
            "results":       results,
        }, f, indent=2, ensure_ascii=False)


def _write_txt(results: list[dict], path: str, log_file: str | None) -> None:
    """
    Laporan teks berformat yang enak dibaca manusia.
    Hasil dikelompokkan per port, dilengkapi detail per baris.
    Log lengkap (kalau ada) dilampirkan di bagian akhir.
    """
    # Kelompokkan hasil per port
    by_port: dict[str, list] = defaultdict(list)
    for r in results:
        by_port[r.get("port", "tidak diketahui")].append(r)

    with open(path, "w", encoding="utf-8") as f:
        # Header
        f.write("=" * 68 + "\n")
        f.write("  NUTSHAKER — LAPORAN HASIL SCAN\n")
        f.write(f"  Dibuat: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 68 + "\n\n")
        f.write(f"Total perangkat/respons ditemukan: {len(results)}\n\n")

        if not results:
            f.write("  Tidak ada perangkat yang merespons.\n")
            f.write("  Kemungkinan penyebab:\n")
            f.write("    - Tidak ada perangkat Modbus yang terhubung\n")
            f.write("    - Baudrate atau pengaturan serial tidak cocok\n")
            f.write("    - Kabel atau koneksi bermasalah\n")
        else:
            for port, port_results in sorted(by_port.items()):
                f.write(f"Port: {port}  ({len(port_results)} hasil)\n")
                f.write("─" * 68 + "\n")

                for r in port_results:
                    line = (
                        f"  Baud={str(r.get('baudrate', '?')):<7}  "
                        f"Tipe={str(r.get('type', '?')):<22}  "
                        f"SID={str(r.get('slave_id', '-')):<5}  "
                        f"CRC={'OK  ' if r.get('crc_valid') else 'FAIL'}  "
                    )
                    # Tambahkan detail sesuai tipe hasil
                    if "register_values" in r:
                        line += f"Nilai={r['register_values']}  "
                    if "exception_code" in r:
                        line += f"Exc={r['exception_code']:#04x}  "
                    if "sub_func" in r:
                        line += f"sub={r['sub_func']} pad={r.get('padding','')!r}  "
                    line += f"Raw={r.get('raw_response', '')}\n"
                    f.write(line)
                f.write("\n")

        # Lampiran log (opsional)
        if log_file and os.path.exists(log_file):
            f.write("\n" + "=" * 68 + "\n")
            f.write("  LOG LENGKAP (termasuk semua traffic TX/RX)\n")
            f.write("=" * 68 + "\n\n")
            with open(log_file, encoding="utf-8") as lf:
                f.write(lf.read())
