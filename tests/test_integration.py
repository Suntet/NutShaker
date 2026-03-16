# tests/test_integration.py
# ── End-to-End Integration Tests ────────────────────────────────────────────
#
# Tests the full pipeline from frame construction through to parsed result
# and export, without any real hardware.
#
# These tests catch regressions where individual units pass but the modules
# do not compose correctly together.

import csv
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from crc          import calculate_crc16, verify_crc
from ascii_codec  import encode_ascii_frame, decode_ascii_frame
from query        import FrameBuilder, ResponseParser, QuerySender, QueryResult, format_parsed
from export       import export_report
from transport    import SerialConfig, TcpConfig, Transport


# ── Helper ────────────────────────────────────────────────────────────────────

def build_valid_response(slave_id: int, fc: int, payload_data: bytes) -> bytes:
    payload = bytes([slave_id, fc]) + payload_data
    return payload + calculate_crc16(payload)


class _EchoTransport(Transport):
    """Transport that stores sent frames and returns pre-programmed responses."""

    def __init__(self):
        self._responses: list[bytes] = []
        self.sent: list[bytes]       = []
        self._open                   = False

    def queue_response(self, data: bytes):
        self._responses.append(data)

    def open(self) -> bool:
        self._open = True
        return True

    def close(self) -> None:
        self._open = False

    def is_open(self) -> bool:
        return self._open

    def send_recv(self, frame: bytes, label: str = "") -> bytes | None:
        self.sent.append(frame)
        return self._responses.pop(0) if self._responses else None


# ── Pipeline: FrameBuilder → Transport → ResponseParser → QueryResult ─────────

class TestFullQueryPipeline(unittest.TestCase):

    def _run_query(self, slave_id, fc, address, quantity, values, response_bytes):
        transport = _EchoTransport()
        transport.queue_response(response_bytes)
        sender = QuerySender(SerialConfig(port="COM1"))
        sender._transport = transport
        return sender.send(slave_id, fc, address, quantity, values)

    def test_fc03_full_pipeline(self):
        values = [111, 222, 333]
        data   = b"".join(struct.pack(">H", v) for v in values)
        resp   = build_valid_response(1, 0x03, bytes([len(data)]) + data)

        result = self._run_query(1, 0x03, 0, 3, [], resp)

        self.assertTrue(result.success)
        self.assertEqual(result.parsed["registers"], values)
        self.assertGreater(result.duration_ms, 0)

    def test_fc06_write_echo_pipeline(self):
        payload = bytes([0x00, 0x05, 0x04, 0xD2])   # addr=5, value=1234
        resp    = build_valid_response(1, 0x06, payload)

        result = self._run_query(1, 0x06, 5, 1, [1234], resp)

        self.assertFalse(result.parsed.get("is_exception", True))
        self.assertEqual(result.parsed["address"], 5)
        self.assertEqual(result.parsed["value"],   1234)

    def test_fc05_coil_on_pipeline(self):
        payload = bytes([0x00, 0x00, 0xFF, 0x00])   # addr=0, ON
        resp    = build_valid_response(1, 0x05, payload)

        result = self._run_query(1, 0x05, 0, 1, [1], resp)

        self.assertTrue(result.parsed.get("coil_on"))

    def test_exception_pipeline_marks_failure(self):
        payload = bytes([0x02])   # Illegal Data Address
        resp    = build_valid_response(1, 0x83, payload)   # FC03 exception

        result = self._run_query(1, 0x03, 0, 1, [], resp)

        self.assertFalse(result.success)
        self.assertTrue(result.parsed["is_exception"])
        self.assertEqual(result.parsed["exception_code"], 0x02)

    def test_no_response_pipeline(self):
        transport = _EchoTransport()   # no queued response
        sender = QuerySender(SerialConfig(port="COM1"))
        sender._transport = transport
        result = sender.send(1, 0x03)
        self.assertFalse(result.success)

    def test_corrupted_crc_pipeline(self):
        """A frame with bad CRC should parse but report crc_valid=False."""
        values = [100]
        data   = struct.pack(">H", 100)
        payload = bytes([1, 0x03, len(data)]) + data
        bad_resp = payload + bytes([0x00, 0x00])   # wrong CRC

        transport = _EchoTransport()
        transport.queue_response(bad_resp)
        sender = QuerySender(SerialConfig(port="COM1"))
        sender._transport = transport
        result = sender.send(1, 0x03)

        self.assertFalse(result.parsed.get("crc_valid", True))


# ── ASCII round-trip through full codec ───────────────────────────────────────

class TestAsciiPipelineIntegration(unittest.TestCase):

    def test_encode_decode_roundtrip_all_fcs(self):
        """For every FC, encode RTU → ASCII frame, decode back, check payload."""
        for fc in [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x0F, 0x10]:
            pdu   = bytes([fc, 0x00, 0x00, 0x00, 0x01])
            ascii_frame = encode_ascii_frame(1, pdu)
            recovered, ok = decode_ascii_frame(ascii_frame)
            self.assertTrue(ok,             f"LRC fail for FC={fc:#04x}")
            self.assertEqual(recovered[0], 1, f"slave_id lost for FC={fc:#04x}")
            self.assertEqual(recovered[1:], pdu, f"PDU lost for FC={fc:#04x}")

    def test_frame_integrity_after_encode_decode(self):
        pdu   = bytes([0x03, 0x00, 0x64, 0x00, 0x0A])
        ascii = encode_ascii_frame(7, pdu)
        data, ok = decode_ascii_frame(ascii)
        self.assertTrue(ok)
        # Slave ID and PDU must survive intact
        self.assertEqual(data[0],  7)
        self.assertEqual(data[1:], pdu)


# ── Full scan → export pipeline ───────────────────────────────────────────────

class TestScanExportPipeline(unittest.TestCase):

    MOCK_RESULTS = [
        {
            "port": "COM3", "baudrate": 9600, "type": "FC03_OK",
            "slave_id": 1, "fc": 3, "crc_valid": True,
            "register_values": [100, 200], "raw_response": "010304006400C8",
            "protocol": "serial", "mode": "RTU",
        },
        {
            "port": "COM3", "baudrate": 9600, "type": "FC03_OK",
            "slave_id": 5, "fc": 3, "crc_valid": True,
            "register_values": [0], "raw_response": "01030200004985",
            "protocol": "serial", "mode": "RTU",
        },
        {
            "host": "192.168.1.10", "tcp_port": 502, "type": "FC03_OK",
            "slave_id": 1, "fc": 3, "crc_valid": True,
            "register_values": [999], "raw_response": "010302027F",
            "protocol": "tcp", "unit_id": 1,
        },
    ]

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_export_preserves_all_results(self):
        csv_p, json_p, _ = export_report(self.MOCK_RESULTS, output_dir=self.tmpdir)
        with open(json_p) as f:
            data = json.load(f)
        self.assertEqual(data["total_results"], len(self.MOCK_RESULTS))

    def test_export_csv_all_rows_present(self):
        csv_p, _, _ = export_report(self.MOCK_RESULTS, output_dir=self.tmpdir)
        with open(csv_p) as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), len(self.MOCK_RESULTS))

    def test_export_tcp_result_in_json(self):
        _, json_p, _ = export_report(self.MOCK_RESULTS, output_dir=self.tmpdir)
        with open(json_p) as f:
            data = json.load(f)
        tcp_results = [r for r in data["results"] if r.get("protocol") == "tcp"]
        self.assertEqual(len(tcp_results), 1)
        self.assertEqual(tcp_results[0]["host"], "192.168.1.10")

    def test_format_parsed_output_is_human_readable(self):
        """format_parsed should always produce a non-empty readable string."""
        for result in self.MOCK_RESULTS:
            # Simulate what ResponseParser would produce
            registers = result.get("register_values", [])
            parsed = {
                "registers": registers,
                "registers_signed": [r if r < 0x8000 else r - 0x10000 for r in registers],
                "register_count": len(registers),
                "crc_valid": result["crc_valid"],
                "is_exception": False,
            }
            text = format_parsed(parsed)
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 0)
            for v in registers:
                self.assertIn(str(v), text)


# ── CRC properties ────────────────────────────────────────────────────────────

class TestCRCIntegrationProperties(unittest.TestCase):

    def test_crc_roundtrip_survives_all_slave_ids(self):
        for sid in range(0, 248):
            frame  = bytes([sid, 0x03, 0x00, 0x00, 0x00, 0x01])
            full   = frame + calculate_crc16(frame)
            self.assertTrue(verify_crc(full), f"CRC roundtrip failed for slave_id={sid}")

    def test_crc_detects_all_single_byte_changes_in_256_byte_frame(self):
        frame = bytes(range(256))
        crc   = calculate_crc16(frame)
        full  = frame + crc
        for i in range(len(frame)):
            corrupted    = bytearray(full)
            corrupted[i] ^= 0xFF
            self.assertFalse(
                verify_crc(bytes(corrupted)),
                f"CRC did not detect corruption at byte {i}"
            )

    def test_frame_builder_produces_crc_verifiable_frames(self):
        """Frames from FrameBuilder + CRC must always pass verify_crc."""
        test_cases = [
            dict(slave_id=1,   fc=0x03, address=0,    quantity=1),
            dict(slave_id=247, fc=0x01, address=0,    quantity=8),
            dict(slave_id=1,   fc=0x06, address=100,  values=[1234]),
            dict(slave_id=1,   fc=0x10, address=0,    values=[1,2,3,4,5]),
            dict(slave_id=1,   fc=0x0F, address=0,    values=[1,0,1,1,0,0,1,1]),
        ]
        for kw in test_cases:
            frame = FrameBuilder.build(**kw)
            full  = frame + calculate_crc16(frame)
            self.assertTrue(verify_crc(full), f"CRC failed for {kw}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
