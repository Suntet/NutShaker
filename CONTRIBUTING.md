# Panduan Kontribusi

Hei, terima kasih sudah mau berkontribusi ke NutShaker! 🎉

Tidak perlu jadi ahli Modbus untuk berkontribusi. Laporan bug, perbaikan typo, dokumentasi yang lebih jelas, atau fitur baru — semua sama berharganya.

---

## Cara Paling Cepat untuk Mulai

```bash
# Fork dulu di GitHub, lalu:
git clone https://github.com/NAMAMU/nutshaker.git
cd nutshaker
pip install pyserial
python nutshaker/   # pastikan berjalan normal
```

---

## Melaporkan Bug

Sebelum buka issue baru, cek dulu apakah sudah ada yang melaporkan hal yang sama.

Kalau belum ada, buka issue baru dan sertakan:

1. **Apa yang terjadi** — pesan error lengkap, atau perilaku yang tidak diharapkan
2. **Langkah untuk mereproduksi** — sekecil mungkin, makin spesifik makin baik
3. **Yang kamu harapkan terjadi**
4. **Informasi sistem** — OS, versi Python (`python --version`), versi pyserial
5. **Log file** kalau ada (ada di `~/Downloads/nutshaker_*.log`)

---

## Mengusulkan Fitur Baru

Buka issue dengan label `enhancement` dan ceritakan:
- Masalah apa yang ingin kamu selesaikan
- Solusi yang kamu bayangkan
- Alternatif lain yang sudah kamu pertimbangkan

Tidak perlu format formal — tulis saja seperti ngobrol.

---

## Mengirim Pull Request

### Setup

```bash
git checkout -b nama-fitur-kamu
# contoh: git checkout -b tambah-fc-diagnostics
```

### Panduan Kode

Tidak ada aturan kaku, tapi ada beberapa hal yang perlu diperhatikan:

**Komentar harus seperti bicara ke manusia, bukan ke kompiler.**

```python
# Bagus ✅ — menjelaskan kenapa, bukan cuma apa
# Jeda kecil ini penting supaya slave punya waktu memproses
# sebelum kita mulai baca respons
time.sleep(INTER_FRAME_DELAY)

# Kurang bagus ❌ — hanya menduplikasi kode dalam bahasa Indonesia
# Tidur selama INTER_FRAME_DELAY detik
time.sleep(INTER_FRAME_DELAY)
```

**Setiap modul punya tanggung jawab yang jelas:**
- `config.py` — hanya konstanta, tidak ada logika
- `crc.py` — hanya CRC, tidak ada yang lain
- `tester.py` — hanya satu koneksi serial
- Kalau ragu taruh di mana, buka issue dulu

**Jangan hapus komentar yang sudah ada kecuali memang sudah salah.**

### Sebelum Submit

```bash
# Pastikan syntax valid
python -c "import ast; [ast.parse(open(f).read()) for f in ['nutshaker/config.py', 'nutshaker/crc.py', 'nutshaker/tester.py', 'nutshaker/scanner.py', 'nutshaker/query.py', 'nutshaker/export.py', 'nutshaker/cli.py', 'nutshaker/gui.py']]"

# Pastikan bisa dijalankan
python nutshaker/ --cli
```

### Tulis Deskripsi PR yang Jelas

Ceritakan:
- Apa yang berubah dan kenapa
- Cara test-nya
- Kalau ada breaking change, sebutkan

---

## Ide Kontribusi yang Bagus untuk Pemula

- Terjemahkan pesan error ke bahasa yang lebih jelas
- Tambahkan contoh pemakaian di docstring
- Perbaiki tanda baca atau ejaan di komentar
- Tambahkan FC yang belum didukung di `FrameBuilder`
- Tambahkan dukungan untuk format export baru (Excel langsung, SQLite, dll.)
- Perbaiki tampilan di OS tertentu (font, warna, ukuran)

---

## Pertanyaan?

Buka saja issue dengan label `question`. Tidak ada pertanyaan yang terlalu sederhana.
