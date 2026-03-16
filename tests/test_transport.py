# tests/test_transport.py
# ── Transport Layer ───────────────────────────────────────────────────────────
#
# Tests verify config objects, transport lifecycle, MBAP header construction,
# and correct handling of port/socket errors — all without real hardware.
#
# Strategy: mock the underlying I/O (serial.Serial, socket) and verify
# that the transport layer sends and receives bytes correctly.

import socket
import struct
import sys
import threading
import unittest
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from transport import (
    SerialConfig, TcpConfig, UdpConfig,
    SerialTransport, TcpTransport, UdpTransport,
    create_transport, BAUDRATE_PRIORITY, COMMON_SERIAL_CONFIGS,
)
from crc import calculate_crc16
import logging

NULL_LOGGER = logging.getLogger("test_null")
NULL_LOGGER.addHandler(logging.NullHandler())
NULL_LOGGER.propagate = False


# ── SerialConfig ──────────────────────────────────────────────────────────────

class TestSerialConfig(unittest.TestCase):

    def test_default_values(self):
        cfg = SerialConfig(port="COM1")
        self.assertEqual(cfg.baudrate,  9600)
        self.assertEqual(cfg.bytesize,  8)
        self.assertEqual(cfg.parity,    "N")
        self.assertEqual(cfg.stopbits,  1)
        self.assertEqual(cfg.mode,      "RTU")
        self.assertFalse(cfg.dtr)
        self.assertFalse(cfg.rts)

    def test_custom_values(self):
        cfg = SerialConfig(port="COM3", baudrate=19200, bytesize=7,
                           parity="E", stopbits=2, mode="ASCII")
        self.assertEqual(cfg.baudrate, 19200)
        self.assertEqual(cfg.bytesize, 7)
        self.assertEqual(cfg.parity,   "E")
        self.assertEqual(cfg.stopbits, 2)
        self.assertEqual(cfg.mode,     "ASCII")

    def test_label_contains_port(self):
        cfg = SerialConfig(port="COM5", baudrate=9600)
        self.assertIn("COM5", cfg.label())

    def test_label_contains_baudrate(self):
        cfg = SerialConfig(port="/dev/ttyUSB0", baudrate=115200)
        self.assertIn("115200", cfg.label())

    def test_label_contains_mode(self):
        for mode in ["RTU", "ASCII"]:
            cfg = SerialConfig(port="COM1", mode=mode)
            self.assertIn(mode, cfg.label())

    def test_all_parity_options_accepted(self):
        for p in ["N", "E", "O", "M", "S"]:
            cfg = SerialConfig(port="COM1", parity=p)
            self.assertEqual(cfg.parity, p)

    def test_all_stopbits_options_accepted(self):
        for s in [1, 1.5, 2]:
            cfg = SerialConfig(port="COM1", stopbits=s)
            self.assertEqual(cfg.stopbits, s)


class TestTcpConfig(unittest.TestCase):

    def test_defaults(self):
        cfg = TcpConfig()
        self.assertEqual(cfg.port,    502)
        self.assertEqual(cfg.unit_id, 1)
        self.assertIsInstance(cfg.timeout, float)

    def test_label_contains_host_and_port(self):
        cfg = TcpConfig(host="10.0.0.5", port=502, unit_id=3)
        label = cfg.label()
        self.assertIn("10.0.0.5", label)
        self.assertIn("502", label)
        self.assertIn("3", label)

    def test_custom_port(self):
        cfg = TcpConfig(host="192.168.1.1", port=5020)
        self.assertEqual(cfg.port, 5020)


class TestUdpConfig(unittest.TestCase):

    def test_defaults(self):
        cfg = UdpConfig()
        self.assertEqual(cfg.port,    502)
        self.assertEqual(cfg.unit_id, 1)

    def test_label_contains_udp(self):
        cfg = UdpConfig(host="192.168.1.1")
        self.assertIn("UDP", cfg.label())


class TestCreateTransport(unittest.TestCase):

    def test_serial_config_creates_serial_transport(self):
        cfg = SerialConfig(port="COM1")
        t   = create_transport(cfg)
        self.assertIsInstance(t, SerialTransport)

    def test_tcp_config_creates_tcp_transport(self):
        cfg = TcpConfig()
        t   = create_transport(cfg)
        self.assertIsInstance(t, TcpTransport)

    def test_udp_config_creates_udp_transport(self):
        cfg = UdpConfig()
        t   = create_transport(cfg)
        self.assertIsInstance(t, UdpTransport)

    def test_unknown_config_raises(self):
        with self.assertRaises(ValueError):
            create_transport("not a config")


# ── SerialTransport ───────────────────────────────────────────────────────────

class TestSerialTransportLifecycle(unittest.TestCase):

    def _make_transport(self, mode="RTU"):
        cfg = SerialConfig(port="COM1", baudrate=9600, mode=mode)
        return SerialTransport(cfg, NULL_LOGGER)

    def test_is_open_false_before_open(self):
        t = self._make_transport()
        self.assertFalse(t.is_open())

    def test_open_failure_returns_false(self):
        import serial as serial_mod
        serial_mod.Serial.side_effect = OSError("port busy")
        t = self._make_transport()
        result = t.open()
        self.assertFalse(result)
        serial_mod.Serial.side_effect = None

    def test_open_success_returns_true(self):
        import serial as serial_mod
        mock_port = mock.MagicMock()
        mock_port.is_open = True
        serial_mod.Serial.return_value = mock_port
        t = self._make_transport()
        result = t.open()
        self.assertTrue(result)

    def test_close_after_open(self):
        import serial as serial_mod
        mock_port = mock.MagicMock()
        mock_port.is_open = True
        serial_mod.Serial.return_value = mock_port
        t = self._make_transport()
        t.open()
        t.close()
        mock_port.close.assert_called_once()

    def test_close_when_not_open_is_safe(self):
        t = self._make_transport()
        t.close()   # must not raise

    def test_double_close_is_safe(self):
        import serial as serial_mod
        mock_port = mock.MagicMock()
        mock_port.is_open = True
        serial_mod.Serial.return_value = mock_port
        t = self._make_transport()
        t.open()
        t.close()
        t.close()   # second close must not raise

    def test_send_recv_without_open_returns_none(self):
        t = self._make_transport()
        result = t.send_recv(b"\x01\x03\x00\x00\x00\x01\x84\x0A")
        self.assertIsNone(result)

    def test_rtu_mode_sends_raw_bytes(self):
        import serial as serial_mod
        mock_port       = mock.MagicMock()
        mock_port.is_open = True
        mock_port.read.return_value = b"\x01\x03\x02\x00\x64\xB9\xAF"
        serial_mod.Serial.return_value = mock_port

        t = self._make_transport(mode="RTU")
        t.open()
        frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        resp  = t.send_recv(frame, "test")
        mock_port.write.assert_called_once_with(frame)
        self.assertEqual(resp, b"\x01\x03\x02\x00\x64\xB9\xAF")

    def test_no_response_returns_none(self):
        import serial as serial_mod
        mock_port       = mock.MagicMock()
        mock_port.is_open = True
        mock_port.read.return_value = b""   # no response
        serial_mod.Serial.return_value = mock_port

        t = self._make_transport()
        t.open()
        result = t.send_recv(b"\x01\x03\x00\x00\x00\x01\x84\x0A")
        self.assertIsNone(result)

    def test_dtr_set_when_configured(self):
        import serial as serial_mod
        mock_port       = mock.MagicMock()
        mock_port.is_open = True
        serial_mod.Serial.return_value = mock_port

        cfg = SerialConfig(port="COM1", dtr=True)
        t   = SerialTransport(cfg, NULL_LOGGER)
        t.open()
        self.assertEqual(mock_port.dtr, True)

    def test_rts_set_when_configured(self):
        import serial as serial_mod
        mock_port       = mock.MagicMock()
        mock_port.is_open = True
        serial_mod.Serial.return_value = mock_port

        cfg = SerialConfig(port="COM1", rts=True)
        t   = SerialTransport(cfg, NULL_LOGGER)
        t.open()
        self.assertEqual(mock_port.rts, True)


# ── TcpTransport ──────────────────────────────────────────────────────────────

class TestTcpTransportMBAPHeader(unittest.TestCase):
    """Verify MBAP header construction without a real TCP server."""

    def _make_transport(self, unit_id=1):
        cfg = TcpConfig(host="127.0.0.1", port=502, unit_id=unit_id)
        return TcpTransport(cfg, NULL_LOGGER)

    def test_wrap_tcp_strips_rtu_crc(self):
        """MBAP header should contain PDU (fc + data), not the CRC bytes."""
        t    = self._make_transport()
        rtu  = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        tcp  = t._wrap_tcp(rtu)
        # PDU starts at byte 7 (after MBAP header)
        pdu  = tcp[7:]
        self.assertEqual(pdu, bytes([0x03, 0x00, 0x00, 0x00, 0x01]))

    def test_wrap_tcp_protocol_id_is_zero(self):
        t   = self._make_transport()
        rtu = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        tcp = t._wrap_tcp(rtu)
        proto_id = struct.unpack(">H", tcp[2:4])[0]
        self.assertEqual(proto_id, 0)

    def test_wrap_tcp_length_field(self):
        t   = self._make_transport()
        rtu = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        tcp = t._wrap_tcp(rtu)
        length = struct.unpack(">H", tcp[4:6])[0]
        # length = 1 (unit_id) + 5 (pdu)
        self.assertEqual(length, 6)

    def test_wrap_tcp_unit_id_encoded(self):
        for uid in [1, 5, 247]:
            t   = self._make_transport(unit_id=uid)
            rtu = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
            tcp = t._wrap_tcp(rtu)
            self.assertEqual(tcp[6], uid)

    def test_transaction_id_increments(self):
        t   = self._make_transport()
        rtu = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        tcp1 = t._wrap_tcp(rtu)
        tcp2 = t._wrap_tcp(rtu)
        tid1 = struct.unpack(">H", tcp1[0:2])[0]
        tid2 = struct.unpack(">H", tcp2[0:2])[0]
        self.assertEqual(tid2, tid1 + 1)

    def test_transaction_id_wraps_at_65535(self):
        t             = self._make_transport()
        t._trans_id   = 0xFFFF
        rtu           = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        tcp           = t._wrap_tcp(rtu)
        tid           = struct.unpack(">H", tcp[0:2])[0]
        self.assertEqual(tid, 0)   # wrapped around

    def test_open_failure_returns_false(self):
        cfg = TcpConfig(host="0.0.0.0", port=1)   # invalid port
        t   = TcpTransport(cfg, NULL_LOGGER)
        with mock.patch("socket.socket") as mock_sock:
            mock_sock.return_value.connect.side_effect = OSError("refused")
            result = t.open()
        self.assertFalse(result)

    def test_is_open_false_before_open(self):
        t = self._make_transport()
        self.assertFalse(t.is_open())

    def test_is_open_true_after_mocked_open(self):
        t = self._make_transport()
        with mock.patch("socket.socket") as mock_sock:
            mock_sock.return_value.connect.return_value = None
            t.open()
        self.assertTrue(t.is_open())


# ── UdpTransport ──────────────────────────────────────────────────────────────

class TestUdpTransport(unittest.TestCase):

    def test_open_creates_socket(self):
        cfg = UdpConfig(host="192.168.1.1", port=502)
        t   = UdpTransport(cfg, NULL_LOGGER)
        with mock.patch("socket.socket") as mock_sock:
            mock_sock.return_value.settimeout.return_value = None
            result = t.open()
        self.assertTrue(result)

    def test_is_open_false_before_open(self):
        cfg = UdpConfig()
        t   = UdpTransport(cfg, NULL_LOGGER)
        self.assertFalse(t.is_open())

    def test_close_safe_before_open(self):
        cfg = UdpConfig()
        t   = UdpTransport(cfg, NULL_LOGGER)
        t.close()   # must not raise


# ── Reference data ────────────────────────────────────────────────────────────

class TestReferenceData(unittest.TestCase):

    def test_baudrate_priority_has_9600_first(self):
        self.assertEqual(BAUDRATE_PRIORITY[0], 9600)

    def test_baudrate_priority_no_duplicates(self):
        self.assertEqual(len(BAUDRATE_PRIORITY), len(set(BAUDRATE_PRIORITY)))

    def test_common_serial_configs_includes_8n1(self):
        self.assertIn((8, "N", 1), COMMON_SERIAL_CONFIGS)

    def test_common_serial_configs_includes_7e1(self):
        self.assertIn((7, "E", 1), COMMON_SERIAL_CONFIGS)

    def test_all_configs_have_valid_bytesize(self):
        for bytesize, _, _ in COMMON_SERIAL_CONFIGS:
            self.assertIn(bytesize, [7, 8])

    def test_all_configs_have_valid_parity(self):
        for _, parity, _ in COMMON_SERIAL_CONFIGS:
            self.assertIn(parity, ["N", "E", "O", "M", "S"])

    def test_all_configs_have_valid_stopbits(self):
        for _, _, stopbits in COMMON_SERIAL_CONFIGS:
            self.assertIn(stopbits, [1, 1.5, 2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
