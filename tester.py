# tester.py
# Pengujian Modbus ke satu target — tidak peduli Serial atau TCP/UDP.
#
# ModbusTester sekarang bekerja dengan Transport abstrak, bukan
# langsung dengan pyserial. Ini berarti kode yang sama bisa dipakai
# untuk RS-232, RS-485, Modbus TCP, maupun Modbus UDP.

import logging
import struct
import threading

from config    import INTER_FRAME_DELAY, SERIAL_TIMEOUT
from crc       import calculate_crc16, verify_crc
from transport import Transport


class ModbusTester:
    """
    Kirim frame Modbus ke satu transport dan proses responsnya.

    Tidak tahu dan tidak peduli apakah transportnya serial atau TCP —
    itu urusan kelas Transport. Tester hanya tahu "kirim ini, terima itu".

    Thread-safe: bisa dipakai dari banyak thread untuk slave ID berbeda
    pada transport yang sama (Lock ada di dalam Transport).

    Cara pakai:
        from transport import SerialTransport, SerialConfig
        cfg       = SerialConfig(port="COM3", baudrate=9600)
        transport = SerialTransport(cfg, logger)
        tester    = ModbusTester(transport, logger)
        if transport.open():
            result = tester.test_read_holding(slave_id=1)
            transport.close()
    """

    def __init__(self, transport: Transport, logger: logging.Logger):
        self.transport = transport
        self.logger    = logger

    # ------------------------------------------------------------------
    # Tes 1 — Read Holding Registers (FC=0x03)
    # ------------------------------------------------------------------

    def test_read_holding(self, slave_id: int) -> dict | None:
        """
        Coba baca 1 holding register (alamat 0) dari slave.
        Ini tes paling dasar — hampir semua perangkat Modbus support FC03.
        """
        frame = struct.pack(">BBHH", slave_id, 0x03, 0, 1)
        full  = frame + calculate_crc16(frame)
        label = f"FC03 SID={slave_id:03d}"
        resp  = self.transport.send_recv(full, label)

        if not resp or len(resp) < 5:
            return None

        crc_ok = verify_crc(resp)

        # Exception response (bit 7 FC di-set)
        if resp[0] == slave_id and resp[1] == (0x03 | 0x80):
            exc_code = resp[2] if len(resp) > 2 else 0xFF
            self.logger.warning(
                f"Exception dari SID={slave_id:03d} kode={exc_code:#04x} "
                f"CRC={'OK' if crc_ok else 'GAGAL'}"
            )
            return {
                "type": "FC03_EXCEPTION", "slave_id": slave_id, "fc": 0x03,
                "exception_code": exc_code, "crc_valid": crc_ok,
                "raw_response": resp.hex().upper(),
            }

        # Respons normal
        if resp[0] == slave_id and resp[1] == 0x03 and crc_ok:
            byte_count = resp[2]
            values = [
                struct.unpack(">H", resp[3 + i*2 : 5 + i*2])[0]
                for i in range(byte_count // 2)
                if 5 + i*2 <= len(resp) - 2
            ]
            self.logger.info(f"✅ Aktif SID={slave_id:03d} nilai={values}")
            return {
                "type": "FC03_OK", "slave_id": slave_id, "fc": 0x03,
                "register_values": values, "crc_valid": True,
                "raw_response": resp.hex().upper(),
            }

        self.logger.debug(
            f"Respons tidak dikenal SID={slave_id:03d} "
            f"CRC={'OK' if crc_ok else 'GAGAL'} raw={resp.hex().upper()}"
        )
        return None

    # ------------------------------------------------------------------
    # Tes 2 — Broadcast Assign ID (FC=0xE0)
    # ------------------------------------------------------------------

    def test_broadcast_e0(self, sub_func: str, padding: str) -> dict | None:
        """Broadcast FC=0xE0 dengan variasi sub_func dan padding."""
        try:
            raw = bytes.fromhex(f"00E0{sub_func}02{padding}")
        except ValueError as e:
            self.logger.error(f"Hex salah sub={sub_func!r} pad={padding!r}: {e}")
            return None

        full  = raw + calculate_crc16(raw)
        label = f"Broadcast E0 sub={sub_func} pad={padding!r}"
        resp  = self.transport.send_recv(full, label)

        if not resp:
            return None

        crc_ok = verify_crc(resp)
        self.logger.info(
            f"📡 Broadcast respons sub={sub_func} pad={padding!r} "
            f"CRC={'OK' if crc_ok else 'GAGAL'}"
        )
        return {
            "type": "BROADCAST_E0", "sub_func": sub_func, "padding": padding,
            "crc_valid": crc_ok, "raw_response": resp.hex().upper(),
        }

    # ------------------------------------------------------------------
    # Tes 3 — Function Code Lain
    # ------------------------------------------------------------------

    def test_fc(self, slave_id: int, fc: int) -> dict | None:
        """Tes function code FC ke slave_id."""
        frame = self._build_frame(slave_id, fc)
        if frame is None:
            return None

        full  = frame + calculate_crc16(frame)
        label = f"FC={fc:#04x} SID={slave_id:03d}"
        resp  = self.transport.send_recv(full, label)

        if not resp or len(resp) < 3:
            return None

        crc_ok   = verify_crc(resp)
        is_exc   = resp[1] == (fc | 0x80)
        exc_code = resp[2] if is_exc and len(resp) > 2 else None
        res_type = f"FC{fc:02X}_{'EXCEPTION' if is_exc else 'OK'}"

        self.logger.info(
            f"{'⚠' if is_exc else '✅'} {res_type} SID={slave_id:03d} "
            f"CRC={'OK' if crc_ok else 'GAGAL'}"
        )
        result = {
            "type": res_type, "slave_id": slave_id, "fc": fc,
            "is_exception": is_exc, "crc_valid": crc_ok,
            "raw_response": resp.hex().upper(),
        }
        if exc_code is not None:
            result["exception_code"] = exc_code
        return result

    @staticmethod
    def _build_frame(slave_id: int, fc: int) -> bytes | None:
        if fc in (0x01, 0x02, 0x03, 0x04):
            return struct.pack(">BBHH", slave_id, fc, 0, 1)
        if fc == 0x05:
            return struct.pack(">BBHH", slave_id, fc, 0, 0xFF00)
        if fc == 0x06:
            return struct.pack(">BBHH", slave_id, fc, 0, 0x0001)
        if fc == 0x0F:
            return struct.pack(">BBHHB", slave_id, fc, 0, 8, 1) + b"\xFF"
        if fc == 0x10:
            return struct.pack(">BBHHB", slave_id, fc, 0, 1, 2) + struct.pack(">H", 0x1234)
        return None
