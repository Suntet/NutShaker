# Changelog

Semua perubahan penting pada NutShaker dicatat di sini.

Format mengikuti [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.0.0] — 2024

Versi besar pertama dengan GUI dan query manual.

### Ditambahkan
- GUI berbasis tkinter dengan tema gelap terinspirasi GitHub
- Tab **Query Manual** — kirim query Modbus interaktif dengan form atau raw hex
- Auto-repeat query dengan interval yang bisa diatur (untuk monitoring)
- Riwayat query dengan timestamp dan durasi round-trip
- Parse respons otomatis — register, coil, exception, report slave ID
- Export laporan ke tiga format: CSV, JSON, dan TXT
- Logging detail ke file di `~/Downloads` — semua traffic TX/RX tersimpan
- Support function code: FC01 02 03 04 05 06 0F 10 11 17
- Scan broadcast FC=0xE0 dengan variasi sub-function dan padding
- Thread pool untuk scan FC03 paralel (lebih cepat ~8x)
- Stop event — scan bisa dihentikan kapan saja tanpa crash
- Mode CLI dengan Ctrl+C handler yang bersih
- Fallback otomatis ke CLI kalau tkinter tidak tersedia

### Diperbaiki
- Serial port sekarang dibuka sekali per sesi baudrate, bukan per frame (jauh lebih efisien)
- Semua respons diverifikasi CRC sebelum diproses
- Exception response tetap dicatat (bukan diabaikan)
- Frame builder untuk FC0F dan FC10 yang sebelumnya crash
- Import path bekerja di semua cara menjalankan dan nama folder apapun

### Diubah
- Struktur kode dipecah jadi modul terpisah yang fokus
- Komentar ditulis ulang dengan bahasa yang lebih manusiawi

---

## [1.0.0] — Versi Awal

Versi script tunggal dengan fungsionalitas dasar:
- Scan FC03 ke semua slave ID
- Tes broadcast FC=0xE0
- Output ke konsol
