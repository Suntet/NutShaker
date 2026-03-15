# ascii_codec.py
# Modbus ASCII berbeda dari Modbus RTU dalam tiga hal:
#
#   1. Frame diawali karakter ':'  dan diakhiri CR+LF
#   2. Setiap byte data dikodekan jadi 2 karakter hex ASCII
#      (contoh: byte 0x01 → karakter '0' dan '1')
#   3. Checksum pakai LRC (Longitudinal Redundancy Check),
#      bukan CRC-16 seperti RTU
#
# Kelebihan ASCII: lebih mudah di-debug secara visual (bisa dibaca
# langsung di terminal). Kelemahannya: overhead dua kali lipat
# karena setiap byte jadi dua karakter.
#
# Contoh frame RTU untuk "baca register 0 dari slave 1":
#   01 03 00 00 00 01 [CRC2]
#
# Frame ASCII yang setara:
#   :0103000000016E\r\n
#   (titik dua)(hex data)(LRC)(CR)(LF)


def lrc(data: bytes) -> int:
    """
    Hitung LRC (Longitudinal Redundancy Check) untuk Modbus ASCII.

    Caranya sederhana: jumlahkan semua byte, ambil modulo 256,
    lalu ambil komplemen dua (twos complement).

    Hasilnya adalah satu byte yang kalau ditambahkan ke semua byte data
    akan menghasilkan total 0x00 — itulah cara slave memverifikasi frame.
    """
    total = sum(data) & 0xFF
    return (~total + 1) & 0xFF


def encode_ascii_frame(slave_id: int, pdu: bytes) -> bytes:
    """
    Bungkus PDU Modbus menjadi frame ASCII siap kirim.

    PDU (Protocol Data Unit) adalah fungsi code + data, tanpa slave ID.
    Fungsi ini menambahkan slave ID di depan, hitung LRC, lalu
    format semuanya jadi string ASCII dengan ':' dan CRLF.

    Parameter:
        slave_id — alamat slave (0–247)
        pdu      — function code + data, tanpa slave ID dan tanpa checksum

    Contoh:
        encode_ascii_frame(1, bytes([0x03, 0x00, 0x00, 0x00, 0x01]))
        # → b':0103000000016E\\r\\n'
    """
    payload    = bytes([slave_id]) + pdu
    checksum   = lrc(payload)
    hex_body   = payload.hex().upper() + f"{checksum:02X}"
    return b":" + hex_body.encode("ascii") + b"\r\n"


def decode_ascii_frame(raw: bytes) -> tuple[bytes, bool]:
    """
    Decode frame ASCII yang diterima dari slave.

    Mengembalikan tuple (data_bytes, lrc_valid) di mana:
        data_bytes — isi frame dalam bytes (termasuk slave ID, tanpa LRC)
        lrc_valid  — True kalau checksum cocok

    Kalau format frame tidak valid (tidak diawali ':', tidak ada CRLF,
    atau panjang hex ganjil), mengembalikan (b'', False).
    """
    try:
        # Cari batas frame
        text = raw.decode("ascii", errors="replace").strip()
        if not text.startswith(":"):
            return b"", False

        body = text[1:]           # buang ':'
        body = body.rstrip("\r\n")

        if len(body) < 2 or len(body) % 2 != 0:
            return b"", False

        all_bytes  = bytes.fromhex(body)
        payload    = all_bytes[:-1]   # semua kecuali byte LRC terakhir
        recv_lrc   = all_bytes[-1]
        calc_lrc   = lrc(payload)

        return payload, (recv_lrc == calc_lrc)

    except (ValueError, UnicodeDecodeError):
        return b"", False


def rtu_to_ascii_pdu(rtu_frame: bytes) -> tuple[int, bytes]:
    """
    Ambil slave_id dan PDU dari frame RTU (tanpa konversi format).

    Berguna kalau kamu punya frame RTU dan ingin kirim ulang via ASCII mode.
    Mengembalikan (slave_id, pdu) di mana pdu = fc + data (tanpa CRC).
    """
    if len(rtu_frame) < 4:
        raise ValueError("Frame RTU terlalu pendek")
    slave_id = rtu_frame[0]
    pdu      = rtu_frame[1:-2]   # buang slave_id (depan) dan CRC (belakang)
    return slave_id, pdu
