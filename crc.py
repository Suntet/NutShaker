# crc.py
# Perhitungan dan verifikasi CRC-16 untuk protokol Modbus RTU.
#
# Kenapa perlu CRC? Karena Modbus RTU berjalan di atas kabel fisik
# yang rentan noise. CRC memastikan data yang diterima tidak rusak
# di tengah jalan. Kalau CRC tidak cocok, frame diabaikan.

import struct


def calculate_crc16(data: bytes) -> bytes:
    """
    Hitung CRC-16 Modbus untuk sekumpulan byte data.

    Modbus RTU menggunakan CRC-16 dengan polynomial 0xA001
    (versi terbalik dari 0x8005) dan nilai awal 0xFFFF.
    Hasilnya 2 byte dalam urutan little-endian (LSB dulu).

    Contoh pemakaian:
        frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01])
        frame_lengkap = frame + calculate_crc16(frame)
        # → b'\\x01\\x03\\x00\\x00\\x00\\x01\\x84\\x0a'
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            # Geser kanan 1 bit. Kalau bit terbawah 1, XOR dengan polynomial.
            crc = (crc >> 1) ^ 0xA001 if crc & 0x0001 else crc >> 1
    return struct.pack("<H", crc)


def verify_crc(frame: bytes) -> bool:
    """
    Periksa apakah CRC di akhir frame sudah benar.

    Fungsi ini mengambil semua byte kecuali 2 terakhir,
    hitung CRC-nya, lalu bandingkan dengan 2 byte terakhir frame.

    Mengembalikan True kalau cocok (frame valid), False kalau tidak.
    Frame yang lebih pendek dari 3 byte langsung dianggap tidak valid.

    Contoh:
        # Frame respons FC03 yang valid
        verify_crc(bytes.fromhex("01 03 02 00 64 B9 AF".replace(" ","")))
        # → True
    """
    if len(frame) < 3:
        return False
    return calculate_crc16(frame[:-2]) == frame[-2:]
