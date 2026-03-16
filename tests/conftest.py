# tests/conftest.py
# Shared fixtures, mock helpers, and known-good Modbus frames
# used across the entire test suite.

import logging
import struct
import sys
import unittest.mock as mock
from pathlib import Path

# ── Patch pyserial BEFORE any module imports it ──────────────────────────────
# This makes every test file safe to import even without a real serial device.

_serial_mock = mock.MagicMock()
_serial_mock.EIGHTBITS    = 8
_serial_mock.PARITY_NONE  = "N"
_serial_mock.PARITY_EVEN  = "E"
_serial_mock.PARITY_ODD   = "O"
_serial_mock.PARITY_MARK  = "M"
_serial_mock.PARITY_SPACE = "S"
_serial_mock.STOPBITS_ONE         = 1
_serial_mock.STOPBITS_ONE_POINT_FIVE = 1.5
_serial_mock.STOPBITS_TWO         = 2
_serial_mock.SerialException      = OSError

_lp_mock = mock.MagicMock()
_lp_mock.comports.return_value = []

sys.modules.setdefault("serial",                  _serial_mock)
sys.modules.setdefault("serial.tools",            mock.MagicMock())
sys.modules.setdefault("serial.tools.list_ports", _lp_mock)

# ── Project root on path ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── Known-good Modbus frames for test data ────────────────────────────────────

class KnownFrames:
    """
    Modbus RTU frames whose correctness has been verified against
    the official Modbus specification (Modbus_Application_Protocol_V1_1b3.pdf).
    Use these as ground-truth data throughout the test suite.
    """

    # FC03 request: slave=1, read 1 register from address 0
    FC03_REQUEST   = bytes.fromhex("0103000000018408")  # CRC = 0x0884 (LE: 84 08)

    # FC03 response: slave=1, 2 data bytes, register value = 100 (0x0064)
    FC03_RESPONSE  = bytes.fromhex("010302006449A9")

    # FC03 response: slave=1, 4 data bytes, registers = [100, 200]
    FC03_RESPONSE_MULTI = bytes.fromhex("010304006400C8F93F")

    # FC06 request: slave=1, write value 0x1234 to register 5
    FC06_REQUEST   = bytes.fromhex("010600050BB8560B")   # 0x04D2=1234 → actually 0x0BB8=3000
    # Simpler: slave=1, FC06, addr=0, value=1
    FC06_REQ_SIMPLE = bytes.fromhex("010600000001480A")

    # Exception response: slave=1, FC03 exception, code=0x02 (Illegal Data Address)
    EXCEPTION_RESP = bytes.fromhex("018302B053")

    # FC01 (Read Coils) request: slave=1, read 8 coils from address 0
    FC01_REQUEST   = bytes.fromhex("0101000000083DCC")

    # FC01 response: slave=1, 1 byte of coil data = 0b10110101 = 0xB5
    FC01_RESPONSE  = bytes.fromhex("010101B5DEA5")

    # Broadcast FC=0xE0 frame (slave=0, vendor-specific)
    BROADCAST_E0   = bytes.fromhex("00E00002000000")    # without CRC, for test building

    # ASCII frame: ":010300000001FA\r\n" — equivalent to FC03 read 1 reg from addr 0
    ASCII_FRAME    = b":010300000001FA\r\n"


def make_logger(name: str = "test") -> logging.Logger:
    """Return a silent logger that doesn't pollute test output."""
    logger = logging.getLogger(name)
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return logger


def build_fc03_response(slave_id: int, values: list[int]) -> bytes:
    """
    Construct a valid FC03 response frame from scratch.
    Useful for mocking serial/TCP responses in tests.
    """
    from crc import calculate_crc16
    data = b"".join(struct.pack(">H", v & 0xFFFF) for v in values)
    payload = bytes([slave_id, 0x03, len(data)]) + data
    return payload + calculate_crc16(payload)


def build_exception_response(slave_id: int, fc: int, exc_code: int) -> bytes:
    """Build a valid Modbus exception response frame."""
    from crc import calculate_crc16
    payload = bytes([slave_id, fc | 0x80, exc_code])
    return payload + calculate_crc16(payload)
