# transport.py
# Lapisan transport — abstraksi "gimana cara kirim dan terima byte".
#
# Kenapa dipisah dari tester.py?
# Karena logika Modbus (buat frame, parse respons, hitung CRC) tidak
# peduli apakah datanya jalan lewat kabel serial atau jaringan TCP.
# Dengan abstraksi ini, kamu bisa ganti kabel RS-485 ke Ethernet
# tanpa mengubah satu baris pun di tester.py atau query.py.
#
# Transport yang tersedia:
#   SerialTransport  — RS-232 / RS-422 / RS-485 via pyserial
#                      Mode: RTU (biner) atau ASCII (text dengan LRC)
#   TcpTransport     — Modbus TCP via socket TCP (port default 502)
#   UdpTransport     — Modbus over UDP via socket UDP (port default 502)
#
# Semua transport punya interface yang sama:
#   open()        → bool
#   close()
#   send_recv()   → bytes | None
#   is_open()     → bool

import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Literal

import serial

from ascii_codec import encode_ascii_frame, decode_ascii_frame
from config      import SERIAL_TIMEOUT, INTER_FRAME_DELAY
from crc         import calculate_crc16


# ------------------------------------------------------------------
# Konfigurasi koneksi — bisa di-pass sebagai satu objek
# ------------------------------------------------------------------

@dataclass
class SerialConfig:
    """
    Semua parameter untuk koneksi serial (RS-232 / RS-422 / RS-485).

    Nilai default mengikuti standar Modbus RTU paling umum.
    Ubah sesuai spesifikasi perangkat yang kamu hubungkan.
    """
    port:       str                                    # "COM3", "/dev/ttyUSB0", dll.
    baudrate:   int   = 9600
    bytesize:   int   = 8                             # 7 atau 8 bit data
    parity:     str   = "N"                           # N=None E=Even O=Odd M=Mark S=Space
    stopbits:   float = 1                             # 1, 1.5, atau 2
    mode:       Literal["RTU", "ASCII"] = "RTU"      # protokol Modbus
    dtr:        bool  = False                         # aktifkan DTR (Data Terminal Ready)
    rts:        bool  = False                         # aktifkan RTS (Request To Send)
    timeout:    float = SERIAL_TIMEOUT

    def label(self) -> str:
        """Deskripsi singkat untuk logging."""
        parity_name = {"N":"None","E":"Even","O":"Odd","M":"Mark","S":"Space"}.get(self.parity, self.parity)
        return (f"{self.port} {self.baudrate},{self.bytesize},"
                f"{parity_name},{self.stopbits} [{self.mode}]")


@dataclass
class TcpConfig:
    """Parameter untuk Modbus TCP."""
    host:       str   = "192.168.1.1"
    port:       int   = 502               # port standar Modbus TCP
    timeout:    float = SERIAL_TIMEOUT
    unit_id:    int   = 1                 # Unit ID = slave ID untuk TCP

    def label(self) -> str:
        return f"{self.host}:{self.port} (Unit ID={self.unit_id})"


@dataclass
class UdpConfig:
    """Parameter untuk Modbus over UDP."""
    host:       str   = "192.168.1.1"
    port:       int   = 502
    timeout:    float = SERIAL_TIMEOUT
    unit_id:    int   = 1

    def label(self) -> str:
        return f"UDP {self.host}:{self.port} (Unit ID={self.unit_id})"


# ------------------------------------------------------------------
# Kelas dasar Transport
# ------------------------------------------------------------------

class Transport:
    """
    Interface dasar untuk semua jenis transport.

    Semua subclass harus implement: open(), close(), send_recv(), is_open().
    """

    def open(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def send_recv(self, frame: bytes, label: str = "") -> bytes | None:
        """
        Kirim frame, tunggu, kembalikan respons.
        Frame harus sudah lengkap (termasuk checksum jika diperlukan).
        """
        raise NotImplementedError

    def is_open(self) -> bool:
        raise NotImplementedError


# ------------------------------------------------------------------
# Serial Transport (RS-232 / RS-422 / RS-485)
# ------------------------------------------------------------------

class SerialTransport(Transport):
    """
    Transport via port serial fisik.

    Mendukung semua antarmuka serial standar:
      - RS-232: point-to-point, jarak pendek (~15m), full duplex
      - RS-422: point-to-point, jarak jauh (~1200m), full duplex
      - RS-485: multi-drop (sampai 32 perangkat), setengah duplex,
                yang paling umum di sistem industri

    Dari sisi software, RS-232 / RS-422 / RS-485 diperlakukan sama —
    perbedaannya ada di level hardware. Kamu cukup pilih port yang benar.

    Mode RTU: data biner, checksum CRC-16, efisien
    Mode ASCII: data dikodekan hex, checksum LRC, mudah di-debug
    """

    def __init__(self, config: SerialConfig, logger: logging.Logger | None = None):
        self.cfg    = config
        self.logger = logger or logging.getLogger("NutShaker.Serial")
        self._lock  = threading.Lock()
        self._port: serial.Serial | None = None

    def open(self) -> bool:
        self.close()
        try:
            self._port = serial.Serial(
                port     = self.cfg.port,
                baudrate = self.cfg.baudrate,
                bytesize = self.cfg.bytesize,
                parity   = self.cfg.parity,
                stopbits = self.cfg.stopbits,
                timeout  = self.cfg.timeout,
            )
            # DTR dan RTS untuk kontrol flow / RS-485 half-duplex switching
            if self.cfg.dtr:
                self._port.dtr = True
            if self.cfg.rts:
                self._port.rts = True

            self.logger.debug(f"Serial buka: {self.cfg.label()}")
            return True
        except serial.SerialException as e:
            self.logger.error(f"Gagal buka serial {self.cfg.label()}: {e}")
            return False

    def close(self) -> None:
        with self._lock:
            if self._port and self._port.is_open:
                self._port.close()
                self.logger.debug(f"Serial tutup: {self.cfg.label()}")
            self._port = None

    def is_open(self) -> bool:
        return bool(self._port and self._port.is_open)

    def send_recv(self, frame: bytes, label: str = "") -> bytes | None:
        """
        Untuk mode RTU: kirim frame apa adanya.
        Untuk mode ASCII: konversi ke format ASCII, kirim, decode respons.
        """
        with self._lock:
            if not self.is_open():
                return None
            try:
                if self.cfg.mode == "ASCII":
                    return self._send_recv_ascii(frame, label)
                else:
                    return self._send_recv_rtu(frame, label)
            except serial.SerialException as e:
                self.logger.error(f"Serial error [{label}]: {e}")
                return None

    def _send_recv_rtu(self, frame: bytes, label: str) -> bytes | None:
        """Kirim frame RTU biner, baca respons biner."""
        self._port.reset_input_buffer()
        self._port.write(frame)
        self.logger.debug(f"TX-RTU [{label:<40}]  {frame.hex(' ').upper()}")

        time.sleep(INTER_FRAME_DELAY)
        resp = self._port.read(256)

        if resp:
            self.logger.debug(f"RX-RTU [{label:<40}]  {resp.hex(' ').upper()}")
        else:
            self.logger.debug(f"RX-RTU [{label:<40}]  (tidak ada respons)")
        return resp or None

    def _send_recv_ascii(self, rtu_frame: bytes, label: str) -> bytes | None:
        """
        Konversi frame RTU ke ASCII, kirim, terima respons ASCII,
        decode balik ke format RTU supaya layer atas bisa parse seperti biasa.
        """
        # rtu_frame sudah ada CRC, kita butuh slave_id dan PDU saja
        slave_id = rtu_frame[0]
        pdu      = rtu_frame[1:-2]   # buang slave_id dan CRC

        ascii_frame = encode_ascii_frame(slave_id, pdu)
        self._port.reset_input_buffer()
        self._port.write(ascii_frame)
        self.logger.debug(
            f"TX-ASCII [{label:<40}]  {ascii_frame.decode('ascii', errors='replace').strip()}"
        )

        time.sleep(INTER_FRAME_DELAY)
        # Baca sampai CRLF atau timeout
        raw = b""
        deadline = time.time() + self.cfg.timeout
        while time.time() < deadline:
            chunk = self._port.read(128)
            raw  += chunk
            if b"\r\n" in raw:
                break

        if not raw:
            self.logger.debug(f"RX-ASCII [{label:<40}]  (tidak ada respons)")
            return None

        self.logger.debug(
            f"RX-ASCII [{label:<40}]  {raw.decode('ascii', errors='replace').strip()}"
        )

        # Decode ASCII → bytes, kembalikan dalam format yang mirip RTU
        # supaya ResponseParser di query.py bisa parse tanpa perubahan
        payload, lrc_ok = decode_ascii_frame(raw)
        if not payload:
            self.logger.warning(f"ASCII decode gagal [{label}]")
            return None

        # Tambahkan dummy CRC (FF FF) supaya verify_crc tidak crash —
        # validitas sudah dicek via LRC di atas
        if lrc_ok:
            return payload + b"\xff\xff"
        else:
            self.logger.warning(f"LRC tidak cocok [{label}]")
            return payload + b"\x00\x00"   # CRC salah → verify_crc akan False


# ------------------------------------------------------------------
# TCP Transport (Modbus TCP)
# ------------------------------------------------------------------

class TcpTransport(Transport):
    """
    Transport Modbus TCP via jaringan Ethernet atau WiFi.

    Modbus TCP membungkus PDU Modbus dalam header 7 byte (MBAP Header):
      [Transaction ID 2B][Protocol ID 2B=0x0000][Length 2B][Unit ID 1B]

    Tidak ada CRC di Modbus TCP — integritas data dijamin oleh TCP itu sendiri.

    Unit ID setara dengan slave ID di Modbus serial. Untuk gateway
    serial-ke-Ethernet, Unit ID menentukan perangkat mana yang dituju.

    Port default: 502 (IANA assigned untuk Modbus)
    """

    def __init__(self, config: TcpConfig, logger: logging.Logger | None = None):
        self.cfg        = config
        self.logger     = logger or logging.getLogger("NutShaker.TCP")
        self._sock: socket.socket | None = None
        self._lock      = threading.Lock()
        self._trans_id  = 0           # counter transaction ID, naik setiap request

    def open(self) -> bool:
        self.close()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.cfg.timeout)
            sock.connect((self.cfg.host, self.cfg.port))
            self._sock = sock
            self.logger.debug(f"TCP terhubung: {self.cfg.label()}")
            return True
        except (OSError, socket.timeout) as e:
            self.logger.error(f"Gagal TCP connect {self.cfg.label()}: {e}")
            return False

    def close(self) -> None:
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
                self.logger.debug(f"TCP tutup: {self.cfg.label()}")

    def is_open(self) -> bool:
        return self._sock is not None

    def send_recv(self, rtu_frame: bytes, label: str = "") -> bytes | None:
        """
        Kirim via Modbus TCP.

        rtu_frame boleh berupa frame RTU lengkap (dengan CRC) —
        kita akan strip CRC dan bungkus dengan MBAP header.
        Kalau frame sudah format TCP (ada MBAP header), kirim apa adanya.
        """
        with self._lock:
            if not self.is_open():
                return None
            try:
                tcp_frame = self._wrap_tcp(rtu_frame)
                self.logger.debug(f"TX-TCP [{label:<40}]  {tcp_frame.hex(' ').upper()}")

                self._sock.sendall(tcp_frame)
                resp = self._recv_tcp()

                if resp:
                    self.logger.debug(f"RX-TCP [{label:<40}]  {resp.hex(' ').upper()}")
                    # Kembalikan dalam format RTU-like (tanpa MBAP, tanpa CRC)
                    # tambahkan dummy CRC supaya kompatibel dengan parser
                    return resp + b"\xff\xff"
                else:
                    self.logger.debug(f"RX-TCP [{label:<40}]  (tidak ada respons)")
                    return None

            except (OSError, socket.timeout) as e:
                self.logger.error(f"TCP error [{label}]: {e}")
                self._sock = None   # koneksi mati, paksa reconnect berikutnya
                return None

    def _wrap_tcp(self, rtu_frame: bytes) -> bytes:
        """
        Bungkus PDU Modbus dengan MBAP header untuk TCP.

        MBAP Header format:
          [0:2]  Transaction Identifier — counter unik per request
          [2:4]  Protocol Identifier    — selalu 0x0000 untuk Modbus
          [4:6]  Length                 — jumlah byte berikutnya (unit_id + pdu)
          [6]    Unit Identifier        — slave ID / unit ID
        """
        self._trans_id = (self._trans_id + 1) & 0xFFFF

        # Ambil PDU saja dari frame RTU (buang slave_id dan CRC)
        if len(rtu_frame) >= 4:
            pdu = rtu_frame[1:-2]   # RTU: [slave_id][fc][data][CRC2]
        else:
            pdu = rtu_frame         # sudah dalam format PDU

        unit_id = self.cfg.unit_id
        length  = 1 + len(pdu)     # unit_id (1) + pdu

        header = struct.pack(">HHHB",
            self._trans_id,
            0x0000,                 # Protocol ID selalu 0
            length,
            unit_id,
        )
        return header + pdu

    def _recv_tcp(self) -> bytes | None:
        """
        Terima respons TCP dan strip MBAP header.
        Mengembalikan [unit_id][fc][data] tanpa MBAP.
        """
        try:
            # Baca header dulu (6 byte)
            header = b""
            while len(header) < 6:
                chunk = self._sock.recv(6 - len(header))
                if not chunk:
                    return None
                header += chunk

            # Byte 4-5 = length field (berisi panjang sisa data)
            length = struct.unpack(">H", header[4:6])[0]
            if length < 1 or length > 260:
                return None

            # Baca sisa data
            data = b""
            while len(data) < length:
                chunk = self._sock.recv(length - len(data))
                if not chunk:
                    return None
                data += chunk

            # data = [unit_id][fc][...]
            return data

        except (OSError, socket.timeout):
            return None


# ------------------------------------------------------------------
# UDP Transport (Modbus over UDP)
# ------------------------------------------------------------------

class UdpTransport(Transport):
    """
    Transport Modbus over UDP.

    Format frame sama persis dengan Modbus TCP (pakai MBAP header),
    bedanya protokol jaringan yang dipakai UDP bukan TCP.

    Kapan pakai UDP vs TCP?
    - UDP lebih cepat (tidak ada handshake), cocok untuk polling cepat
    - UDP tidak ada jaminan pengiriman — kalau paket hilang, hilang saja
    - TCP lebih andal, cocok untuk operasi write yang kritis
    - Beberapa perangkat embedded hanya support UDP untuk efisiensi memori
    """

    def __init__(self, config: UdpConfig, logger: logging.Logger | None = None):
        self.cfg    = config
        self.logger = logger or logging.getLogger("NutShaker.UDP")
        self._sock: socket.socket | None = None
        self._lock  = threading.Lock()
        self._trans_id = 0

    def open(self) -> bool:
        self.close()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.cfg.timeout)
            self._sock = sock
            self.logger.debug(f"UDP siap: {self.cfg.label()}")
            return True
        except OSError as e:
            self.logger.error(f"Gagal buat UDP socket {self.cfg.label()}: {e}")
            return False

    def close(self) -> None:
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None

    def is_open(self) -> bool:
        return self._sock is not None

    def send_recv(self, rtu_frame: bytes, label: str = "") -> bytes | None:
        with self._lock:
            if not self.is_open():
                return None
            try:
                self._trans_id = (self._trans_id + 1) & 0xFFFF

                # Bungkus dengan MBAP header (sama dengan TCP)
                if len(rtu_frame) >= 4:
                    pdu = rtu_frame[1:-2]
                else:
                    pdu = rtu_frame

                length = 1 + len(pdu)
                header = struct.pack(">HHHB",
                    self._trans_id, 0x0000, length, self.cfg.unit_id
                )
                udp_frame = header + pdu

                self.logger.debug(f"TX-UDP [{label:<40}]  {udp_frame.hex(' ').upper()}")
                self._sock.sendto(udp_frame, (self.cfg.host, self.cfg.port))

                resp_raw, _ = self._sock.recvfrom(512)
                if resp_raw and len(resp_raw) > 6:
                    resp = resp_raw[6:]   # buang MBAP header
                    self.logger.debug(f"RX-UDP [{label:<40}]  {resp_raw.hex(' ').upper()}")
                    return resp + b"\xff\xff"   # dummy CRC untuk kompatibilitas
                return None

            except socket.timeout:
                self.logger.debug(f"UDP timeout [{label}]")
                return None
            except OSError as e:
                self.logger.error(f"UDP error [{label}]: {e}")
                return None


# ------------------------------------------------------------------
# Factory — buat transport dari konfigurasi
# ------------------------------------------------------------------

def create_transport(
    config: SerialConfig | TcpConfig | UdpConfig,
    logger: logging.Logger | None = None,
) -> Transport:
    """
    Buat instance transport yang tepat berdasarkan tipe konfigurasi.

    Contoh:
        cfg = TcpConfig(host="192.168.1.100", port=502)
        transport = create_transport(cfg, logger)
        if transport.open():
            resp = transport.send_recv(frame, "test")
    """
    if isinstance(config, SerialConfig):
        return SerialTransport(config, logger)
    elif isinstance(config, TcpConfig):
        return TcpTransport(config, logger)
    elif isinstance(config, UdpConfig):
        return UdpTransport(config, logger)
    else:
        raise ValueError(f"Tipe konfigurasi tidak dikenal: {type(config)}")


# ------------------------------------------------------------------
# Baudrate optimizer — urutan coba yang paling efisien
# ------------------------------------------------------------------

# Baudrate yang paling umum di sistem industri, diurutkan dari
# yang paling sering ditemui ke yang paling jarang.
# Urutan ini menghemat waktu scan karena biasanya berhasil lebih awal.
BAUDRATE_PRIORITY = [
    9600,    # default Modbus RTU paling umum
    19200,   # banyak PLC modern
    38400,   # konverter USB-RS485 murah
    115200,  # perangkat baru, meter digital
    4800,    # sensor lama, flow meter
    57600,   # inverter, VFD
    2400,    # perangkat lama sekali
    1200,    # sangat jarang, hanya perangkat antik
]

# Konfigurasi serial yang paling umum di lapangan.
# Dicoba dari yang paling standar ke yang paling tidak umum.
COMMON_SERIAL_CONFIGS = [
    # (bytesize, parity, stopbits)  → deskripsi
    (8, "N", 1),   # 8N1 — standar Modbus RTU, paling umum
    (8, "E", 1),   # 8E1 — banyak perangkat Eropa
    (8, "N", 2),   # 8N2 — beberapa PLC Siemens, Omron
    (8, "O", 1),   # 8O1 — jarang tapi ada
    (7, "E", 1),   # 7E1 — Modbus ASCII standar
    (7, "N", 2),   # 7N2 — sangat jarang
    (7, "O", 1),   # 7O1 — sangat jarang
]
