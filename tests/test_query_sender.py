# tests/test_query_sender.py
# ── QuerySender ──────────────────────────────────────────────────────────────
#
# Tests verify that QuerySender correctly:
#   - Builds and sends frames via the transport
#   - Parses responses into QueryResult
#   - Returns failure gracefully on invalid input or no response
#   - Factory methods create correctly configured instances

import struct
import sys
import unittest
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from query     import QuerySender, QueryResult, FrameBuilder, format_parsed
from transport import SerialConfig, TcpConfig, UdpConfig, Transport
from crc       import calculate_crc16
import logging

NULL_LOGGER = logging.getLogger("test_qs")
NULL_LOGGER.addHandler(logging.NullHandler())
NULL_LOGGER.propagate = False


def make_fc03_resp(slave_id: int, values: list[int]) -> bytes:
    data    = b"".join(struct.pack(">H", v) for v in values)
    payload = bytes([slave_id, 0x03, len(data)]) + data
    return payload + calculate_crc16(payload)


def make_exc_resp(slave_id: int, fc: int, code: int) -> bytes:
    payload = bytes([slave_id, fc | 0x80, code])
    return payload + calculate_crc16(payload)


class _MockTransport(Transport):
    """Controllable mock transport for testing QuerySender in isolation."""

    def __init__(self, response: bytes | None = None, open_ok: bool = True):
        self._response = response
        self._open_ok  = open_ok
        self.sent      = []
        self._is_open  = False

    def open(self) -> bool:
        self._is_open = self._open_ok
        return self._open_ok

    def close(self) -> None:
        self._is_open = False

    def is_open(self) -> bool:
        return self._is_open

    def send_recv(self, frame: bytes, label: str = "") -> bytes | None:
        self.sent.append(frame)
        return self._response


def _make_sender(response=None, open_ok=True):
    transport = _MockTransport(response=response, open_ok=open_ok)
    sender    = QuerySender(SerialConfig(port="COM1"), NULL_LOGGER)
    sender._transport = transport
    return sender, transport


class TestQuerySenderFactories(unittest.TestCase):

    def test_from_serial_creates_sender(self):
        s = QuerySender.from_serial("COM3", 9600)
        self.assertIsNotNone(s)

    def test_from_serial_protocol_label(self):
        s = QuerySender.from_serial("COM3", 9600, mode="RTU")
        self.assertIn("serial", s.protocol_label)

    def test_from_serial_ascii_mode_label(self):
        s = QuerySender.from_serial("COM3", 9600, mode="ASCII")
        self.assertIn("ASCII", s.protocol_label)

    def test_from_tcp_creates_sender(self):
        s = QuerySender.from_tcp("192.168.1.1", 502)
        self.assertIsNotNone(s)

    def test_from_tcp_protocol_label(self):
        s = QuerySender.from_tcp("192.168.1.1")
        self.assertEqual(s.protocol_label, "tcp")

    def test_from_udp_creates_sender(self):
        s = QuerySender.from_udp("192.168.1.1", 502)
        self.assertIsNotNone(s)

    def test_from_udp_protocol_label(self):
        s = QuerySender.from_udp("192.168.1.1")
        self.assertEqual(s.protocol_label, "udp")


class TestQuerySenderSend(unittest.TestCase):

    def test_send_fc03_success(self):
        resp = make_fc03_resp(1, [100, 200])
        sender, transport = _make_sender(response=resp)
        result = sender.send(slave_id=1, fc=0x03, address=0, quantity=2)
        self.assertTrue(result.success)

    def test_send_fc03_register_values_in_result(self):
        resp = make_fc03_resp(1, [100, 200])
        sender, _ = _make_sender(response=resp)
        result = sender.send(slave_id=1, fc=0x03, address=0, quantity=2)
        self.assertEqual(result.parsed.get("registers"), [100, 200])

    def test_send_returns_query_result(self):
        resp = make_fc03_resp(1, [42])
        sender, _ = _make_sender(response=resp)
        result = sender.send(1, 0x03)
        self.assertIsInstance(result, QueryResult)

    def test_send_raw_tx_is_hex_string(self):
        sender, _ = _make_sender(response=make_fc03_resp(1, [1]))
        result = sender.send(1, 0x03)
        self.assertIsInstance(result.raw_tx, str)
        # Should be space-separated hex bytes
        bytes.fromhex(result.raw_tx.replace(" ", ""))  # must parse without error

    def test_send_raw_rx_is_hex_string(self):
        sender, _ = _make_sender(response=make_fc03_resp(1, [1]))
        result = sender.send(1, 0x03)
        self.assertIsInstance(result.raw_rx, str)

    def test_send_no_response_returns_failure(self):
        sender, _ = _make_sender(response=None)
        result = sender.send(1, 0x03)
        self.assertFalse(result.success)
        self.assertIn("merespons", result.error_msg.lower())

    def test_send_transport_open_failure_returns_failure(self):
        sender, _ = _make_sender(response=None, open_ok=False)
        result = sender.send(1, 0x03)
        self.assertFalse(result.success)

    def test_send_exception_response_success_false(self):
        resp = make_exc_resp(1, 0x03, 0x02)
        sender, _ = _make_sender(response=resp)
        result = sender.send(1, 0x03)
        self.assertFalse(result.success)
        self.assertTrue(result.parsed.get("is_exception"))

    def test_send_invalid_slave_id_returns_failure(self):
        sender, _ = _make_sender()
        result = sender.send(slave_id=300, fc=0x03)  # > 247
        self.assertFalse(result.success)
        self.assertGreater(len(result.error_msg), 0)

    def test_send_invalid_fc_returns_failure(self):
        sender, _ = _make_sender()
        result = sender.send(slave_id=1, fc=0xFE)
        self.assertFalse(result.success)

    def test_send_duration_ms_non_negative(self):
        resp = make_fc03_resp(1, [1])
        sender, _ = _make_sender(response=resp)
        result = sender.send(1, 0x03)
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_send_timestamp_is_string(self):
        resp = make_fc03_resp(1, [1])
        sender, _ = _make_sender(response=resp)
        result = sender.send(1, 0x03)
        self.assertIsInstance(result.timestamp, str)
        self.assertGreater(len(result.timestamp), 0)

    def test_frame_actually_sent_to_transport(self):
        sender, transport = _make_sender(response=make_fc03_resp(1, [1]))
        sender.send(1, 0x03, address=0, quantity=1)
        self.assertEqual(len(transport.sent), 1)
        frame = transport.sent[0]
        self.assertEqual(frame[0], 1)   # slave ID
        self.assertEqual(frame[1], 3)   # FC03


class TestQuerySenderSendHex(unittest.TestCase):

    def test_send_hex_with_spaces(self):
        resp = make_fc03_resp(1, [100])
        sender, _ = _make_sender(response=resp)
        result = sender.send_hex("01 03 00 00 00 01")
        self.assertIsInstance(result, QueryResult)

    def test_send_hex_without_spaces(self):
        resp = make_fc03_resp(1, [100])
        sender, _ = _make_sender(response=resp)
        result = sender.send_hex("010300000001")
        self.assertIsInstance(result, QueryResult)

    def test_send_hex_with_colons(self):
        resp = make_fc03_resp(1, [100])
        sender, _ = _make_sender(response=resp)
        result = sender.send_hex("01:03:00:00:00:01")
        self.assertIsInstance(result, QueryResult)

    def test_send_hex_auto_crc_adds_crc(self):
        resp = make_fc03_resp(1, [100])
        sender, transport = _make_sender(response=resp)
        sender.send_hex("01 03 00 00 00 01", auto_crc=True)
        frame = transport.sent[0]
        from crc import verify_crc
        self.assertTrue(verify_crc(frame))

    def test_send_hex_no_auto_crc_sends_as_is(self):
        resp = make_fc03_resp(1, [100])
        sender, transport = _make_sender(response=resp)
        # Frame with pre-computed CRC
        sender.send_hex("01 03 00 00 00 01 84 0A", auto_crc=False)
        frame = transport.sent[0]
        self.assertEqual(frame, bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A]))

    def test_send_hex_invalid_returns_failure(self):
        sender, _ = _make_sender()
        result = sender.send_hex("ZZ XX YY")   # not valid hex
        self.assertFalse(result.success)
        self.assertIn("hex", result.error_msg.lower())

    def test_send_hex_empty_string_handled(self):
        sender, _ = _make_sender()
        result = sender.send_hex("")
        self.assertIsInstance(result, QueryResult)


class TestQuerySenderSendRaw(unittest.TestCase):

    def test_send_raw_bytes_passed_directly(self):
        resp = make_fc03_resp(1, [42])
        sender, transport = _make_sender(response=resp)
        frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        sender.send_raw(frame)
        self.assertEqual(transport.sent[0], frame)

    def test_send_raw_returns_query_result(self):
        resp   = make_fc03_resp(1, [42])
        sender, _ = _make_sender(response=resp)
        result = sender.send_raw(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A]))
        self.assertIsInstance(result, QueryResult)


class TestQueryResultDataclass(unittest.TestCase):

    def test_to_dict_has_required_keys(self):
        result = QueryResult(
            success=True, raw_tx="01 03", raw_rx="01 03 02 00 64",
            parsed={"registers": [100]}, duration_ms=12.5
        )
        d = result.to_dict()
        for key in ["timestamp", "success", "raw_tx", "raw_rx", "parsed",
                    "error_msg", "duration_ms", "protocol"]:
            self.assertIn(key, d)

    def test_default_error_msg_is_empty(self):
        result = QueryResult(success=True, raw_tx="", raw_rx="", parsed={})
        self.assertEqual(result.error_msg, "")

    def test_default_protocol_is_serial(self):
        result = QueryResult(success=True, raw_tx="", raw_rx="", parsed={})
        self.assertEqual(result.protocol, "serial")

    def test_timestamp_auto_filled(self):
        result = QueryResult(success=True, raw_tx="", raw_rx="", parsed={})
        self.assertGreater(len(result.timestamp), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
