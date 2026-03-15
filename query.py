# query.py
# Kirim satu query Modbus secara manual dan lihat hasilnya.
#
# QuerySender sekarang mendukung semua protokol:
#   Serial RTU/ASCII (RS-232/RS-422/RS-485)
#   Modbus TCP
#   Modbus over UDP
#
# Cara pakai:
#   sender = QuerySender.from_serial("COM3", 9600)
#   sender = QuerySender.from_tcp("192.168.1.100", 502)
#   result = sender.send(slave_id=1, fc=0x03, address=0, quantity=10)

import struct
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import serial

from config    import INTER_FRAME_DELAY, SERIAL_TIMEOUT, TCP_MODBUS_PORT
from crc       import calculate_crc16, verify_crc
from transport import (
    SerialConfig, TcpConfig, UdpConfig,
    SerialTransport, TcpTransport, UdpTransport,
    Transport, create_transport,
)


# ------------------------------------------------------------------
# Referensi Function Code
# ------------------------------------------------------------------

FC_INFO: dict[int, dict] = {
    0x01: {"name": "Read Coils",                    "type": "read",   "unit": "coil"},
    0x02: {"name": "Read Discrete Inputs",          "type": "read",   "unit": "input"},
    0x03: {"name": "Read Holding Registers",        "type": "read",   "unit": "register"},
    0x04: {"name": "Read Input Registers",          "type": "read",   "unit": "register"},
    0x05: {"name": "Write Single Coil",             "type": "write1", "unit": "coil"},
    0x06: {"name": "Write Single Register",         "type": "write1", "unit": "register"},
    0x0F: {"name": "Write Multiple Coils",          "type": "writem", "unit": "coil"},
    0x10: {"name": "Write Multiple Registers",      "type": "writem", "unit": "register"},
    0x11: {"name": "Report Slave ID",               "type": "diag",   "unit": None},
    0x17: {"name": "Read/Write Multiple Registers", "type": "rwm",    "unit": "register"},
}

EXCEPTION_CODES: dict[int, str] = {
    0x01: "Illegal Function",
    0x02: "Illegal Data Address",
    0x03: "Illegal Data Value",
    0x04: "Slave Device Failure",
    0x05: "Acknowledge",
    0x06: "Slave Device Busy",
    0x08: "Memory Parity Error",
    0x0A: "Gateway Path Unavailable",
    0x0B: "Gateway Target Failed to Respond",
}


# ------------------------------------------------------------------
# QueryResult
# ------------------------------------------------------------------

@dataclass
class QueryResult:
    success:     bool
    raw_tx:      str
    raw_rx:      str
    parsed:      dict[str, Any]
    error_msg:   str  = ""
    duration_ms: float = 0.0
    protocol:    str  = "serial"
    timestamp:   str  = field(
        default_factory=lambda: datetime.now().strftime("%H:%M:%S.%f")[:-3]
    )

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp, "success": self.success,
            "raw_tx": self.raw_tx, "raw_rx": self.raw_rx,
            "parsed": self.parsed, "error_msg": self.error_msg,
            "duration_ms": self.duration_ms, "protocol": self.protocol,
        }


# ------------------------------------------------------------------
# FrameBuilder
# ------------------------------------------------------------------

class FrameBuilder:
    @staticmethod
    def build(slave_id, fc, address=0, quantity=1, values=None) -> bytes:
        values = values or []
        if not (0 <= slave_id <= 247):
            raise ValueError(f"Slave ID harus 0–247, dapat: {slave_id}")
        if not (0 <= address <= 0xFFFF):
            raise ValueError(f"Alamat harus 0–65535, dapat: {address}")

        if fc in (0x01, 0x02, 0x03, 0x04):
            if not (1 <= quantity <= 2000):
                raise ValueError(f"Quantity harus 1–2000, dapat: {quantity}")
            return struct.pack(">BBHH", slave_id, fc, address, quantity)
        if fc == 0x05:
            return struct.pack(">BBHH", slave_id, fc, address,
                               0xFF00 if (values[0] if values else 1) else 0x0000)
        if fc == 0x06:
            val = values[0] if values else 0
            if not (0 <= val <= 0xFFFF):
                raise ValueError(f"Nilai harus 0–65535, dapat: {val}")
            return struct.pack(">BBHH", slave_id, fc, address, val)
        if fc == 0x0F:
            if not values: raise ValueError("Write Multiple Coils butuh nilai.")
            n = len(values)
            bc = (n + 7) // 8
            cb = bytearray(bc)
            for i, v in enumerate(values):
                if v: cb[i // 8] |= (1 << (i % 8))
            return struct.pack(">BBHHB", slave_id, fc, address, n, bc) + bytes(cb)
        if fc == 0x10:
            if not values: raise ValueError("Write Multiple Registers butuh nilai.")
            bc = len(values) * 2
            hdr = struct.pack(">BBHHB", slave_id, fc, address, len(values), bc)
            return hdr + b"".join(struct.pack(">H", v & 0xFFFF) for v in values)
        if fc == 0x11:
            return struct.pack(">BB", slave_id, fc)
        if fc == 0x17:
            if not values: raise ValueError("FC17 butuh nilai tulis.")
            wc = len(values)
            bc = wc * 2
            hdr = struct.pack(">BBHHHHB", slave_id, fc, address, quantity, address, wc, bc)
            return hdr + b"".join(struct.pack(">H", v & 0xFFFF) for v in values)
        raise ValueError(f"FC {fc:#04x} tidak didukung.")


# ------------------------------------------------------------------
# ResponseParser
# ------------------------------------------------------------------

class ResponseParser:
    @staticmethod
    def parse(fc: int, response: bytes) -> dict[str, Any]:
        if not response or len(response) < 3:
            return {"error": "Respons terlalu pendek"}

        result: dict[str, Any] = {
            "slave_id":  response[0],
            "fc_echo":   response[1],
            "crc_valid": verify_crc(response),
            "raw_bytes": len(response),
        }

        fc_byte = response[1]
        if fc_byte & 0x80:
            exc = response[2] if len(response) > 2 else 0xFF
            result.update({
                "is_exception": True,
                "original_fc":  fc_byte & 0x7F,
                "exception_code": exc,
                "exception_desc": EXCEPTION_CODES.get(exc, f"Kode tidak dikenal ({exc:#04x})"),
            })
            return result

        result["is_exception"] = False
        try:
            if fc in (0x01, 0x02):
                bc = response[2]
                coils = []
                for b in response[3: 3 + bc]:
                    for bit in range(8): coils.append(bool(b & (1 << bit)))
                result.update({"byte_count": bc, "coils": coils, "coil_count": len(coils)})

            elif fc in (0x03, 0x04):
                bc   = response[2]
                regs = [struct.unpack(">H", response[3+i*2:5+i*2])[0]
                        for i in range(bc//2) if 5+i*2 <= len(response)-2]
                result.update({
                    "byte_count": bc, "registers": regs,
                    "registers_signed": [r if r < 0x8000 else r-0x10000 for r in regs],
                    "register_count": len(regs),
                })

            elif fc == 0x05:
                addr, val = struct.unpack(">HH", response[2:6])
                result.update({"address": addr, "value": val, "coil_on": val == 0xFF00})

            elif fc == 0x06:
                addr, val = struct.unpack(">HH", response[2:6])
                result.update({
                    "address": addr, "value": val,
                    "value_signed": val if val < 0x8000 else val - 0x10000,
                })

            elif fc in (0x0F, 0x10):
                addr, qty = struct.unpack(">HH", response[2:6])
                result.update({"address": addr, "quantity_written": qty})

            elif fc == 0x11:
                bc = response[2]
                pl = response[3: 3 + bc]
                result.update({
                    "byte_count": bc,
                    "slave_id_reported": pl[0] if pl else None,
                    "run_status": pl[1] if len(pl) > 1 else None,
                    "additional_data": pl[2:].hex().upper() if len(pl) > 2 else "",
                })

            elif fc == 0x17:
                bc   = response[2]
                regs = [struct.unpack(">H", response[3+i*2:5+i*2])[0]
                        for i in range(bc//2) if 5+i*2 <= len(response)-2]
                result.update({"byte_count": bc, "registers": regs, "register_count": len(regs)})

        except (struct.error, IndexError) as e:
            result["parse_error"] = str(e)

        return result


# ------------------------------------------------------------------
# QuerySender
# ------------------------------------------------------------------

class QuerySender:
    """
    Kirim satu query Modbus via transport pilihan dan kembalikan hasilnya.

    Cara buat instance:
        # Serial RTU
        sender = QuerySender.from_serial("COM3", 9600)

        # Serial ASCII dengan konfigurasi lengkap
        sender = QuerySender.from_serial("COM3", 9600,
                     bytesize=7, parity="E", stopbits=1, mode="ASCII")

        # Modbus TCP
        sender = QuerySender.from_tcp("192.168.1.100", 502, unit_id=1)

        # Modbus UDP
        sender = QuerySender.from_udp("192.168.1.100", 502, unit_id=1)

        # Dari config object langsung
        sender = QuerySender(TcpConfig(host="192.168.1.100"))
    """

    def __init__(self, config, logger=None):
        import logging as _logging
        self._config    = config
        self._logger    = logger or _logging.getLogger("NutShaker.Query")
        self._transport = create_transport(config, self._logger)

    # Factory methods untuk kemudahan
    @classmethod
    def from_serial(cls, port, baudrate=9600, bytesize=8, parity="N",
                    stopbits=1, mode="RTU", dtr=False, rts=False, timeout=None, logger=None):
        cfg = SerialConfig(
            port=port, baudrate=baudrate,
            bytesize=bytesize, parity=parity, stopbits=stopbits,
            mode=mode, dtr=dtr, rts=rts,
            timeout=timeout or SERIAL_TIMEOUT,
        )
        return cls(cfg, logger)

    @classmethod
    def from_tcp(cls, host, port=TCP_MODBUS_PORT, unit_id=1, timeout=2.0, logger=None):
        return cls(TcpConfig(host=host, port=port, unit_id=unit_id, timeout=timeout), logger)

    @classmethod
    def from_udp(cls, host, port=TCP_MODBUS_PORT, unit_id=1, timeout=1.0, logger=None):
        return cls(UdpConfig(host=host, port=port, unit_id=unit_id, timeout=timeout), logger)

    @property
    def protocol_label(self) -> str:
        if isinstance(self._config, SerialConfig):
            return f"serial/{self._config.mode}"
        elif isinstance(self._config, TcpConfig):
            return "tcp"
        else:
            return "udp"

    # ------------------------------------------------------------------
    # API publik
    # ------------------------------------------------------------------

    def send(self, slave_id, fc, address=0, quantity=1, values=None) -> QueryResult:
        """Cara kirim terstruktur — parameter diurai, frame dibangun otomatis."""
        try:
            frame = FrameBuilder.build(slave_id, fc, address, quantity, values)
            full  = frame + calculate_crc16(frame)
        except ValueError as e:
            return QueryResult(
                success=False, raw_tx="", raw_rx="",
                parsed={}, error_msg=str(e),
                protocol=self.protocol_label,
            )
        return self._do_send(full, fc)

    def send_hex(self, hex_str: str, auto_crc: bool = True) -> QueryResult:
        """Kirim dari string hex. Spasi dan titik dua diabaikan."""
        clean = hex_str.replace(" ", "").replace(":", "").strip()
        try:
            frame = bytes.fromhex(clean)
        except ValueError as e:
            return QueryResult(
                success=False, raw_tx=hex_str, raw_rx="",
                parsed={}, error_msg=f"Hex tidak valid: {e}",
                protocol=self.protocol_label,
            )
        if auto_crc:
            frame = frame + calculate_crc16(frame)
        fc = frame[1] if len(frame) > 1 else 0
        return self._do_send(frame, fc)

    def send_raw(self, frame_with_crc: bytes) -> QueryResult:
        """Kirim bytes mentah tanpa modifikasi."""
        fc = frame_with_crc[1] if len(frame_with_crc) > 1 else 0
        return self._do_send(frame_with_crc, fc)

    def _do_send(self, frame: bytes, fc: int) -> QueryResult:
        raw_tx  = " ".join(f"{b:02X}" for b in frame)
        t_start = time.perf_counter()

        if not self._transport.open():
            return QueryResult(
                success=False, raw_tx=raw_tx, raw_rx="",
                parsed={}, error_msg="Gagal membuka transport.",
                protocol=self.protocol_label,
                duration_ms=(time.perf_counter() - t_start) * 1000,
            )

        try:
            resp = self._transport.send_recv(frame, f"FC={fc:#04x}")
        finally:
            self._transport.close()

        duration_ms = (time.perf_counter() - t_start) * 1000
        raw_rx      = " ".join(f"{b:02X}" for b in resp) if resp else ""

        if not resp:
            return QueryResult(
                success=False, raw_tx=raw_tx, raw_rx="",
                parsed={}, error_msg="Slave tidak merespons.",
                protocol=self.protocol_label, duration_ms=duration_ms,
            )

        parsed  = ResponseParser.parse(fc, resp)
        success = parsed.get("crc_valid", False) and not parsed.get("is_exception", False)
        return QueryResult(
            success=success, raw_tx=raw_tx, raw_rx=raw_rx,
            parsed=parsed, protocol=self.protocol_label, duration_ms=duration_ms,
        )


# ------------------------------------------------------------------
# Format ringkas untuk GUI
# ------------------------------------------------------------------

def format_parsed(parsed: dict) -> str:
    if not parsed:
        return "(kosong)"
    if parsed.get("is_exception"):
        return (f"EXCEPTION Code={parsed.get('exception_code','?'):#04x} "
                f"» {parsed.get('exception_desc','?')}")

    parts = []
    if "registers" in parsed:
        r = parsed["registers"]
        s = parsed.get("registers_signed", r)
        parts.append(f"Register({len(r)}): {r}  Signed:{s}")
    if "coils" in parsed:
        coils = ["ON" if c else "OFF" for c in parsed["coils"]]
        parts.append(f"Coil({len(coils)}): {coils}")
    if "value" in parsed and "coil_on" in parsed:
        parts.append(f"Coil@{parsed.get('address','?')}: {'ON' if parsed['coil_on'] else 'OFF'}")
    if "value" in parsed and "coil_on" not in parsed:
        parts.append(f"Reg@{parsed.get('address','?')}: {parsed['value']} (s:{parsed.get('value_signed','?')})")
    if "quantity_written" in parsed:
        parts.append(f"Tulis {parsed['quantity_written']} item@{parsed.get('address','?')}")
    if "slave_id_reported" in parsed:
        run = parsed.get("run_status")
        parts.append(f"SlaveID:{parsed['slave_id_reported']} Status:{'RUN' if run==0xFF else 'STOP'}")
    if "parse_error" in parsed:
        parts.append(f"⚠ {parsed['parse_error']}")
    if not parts:
        return f"CRC={'OK' if parsed.get('crc_valid') else 'GAGAL'} FC={parsed.get('fc_echo','?'):#04x}"

    crc = "✅ CRC OK" if parsed.get("crc_valid") else "❌ CRC GAGAL"
    return f"{crc}  |  " + "  |  ".join(parts)
