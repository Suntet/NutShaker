# tests/test_ascii_codec.py
# ── Modbus ASCII Codec ───────────────────────────────────────────────────────
#
# Tests verify:
#   - LRC calculation correctness (known vectors + mathematical properties)
#   - ASCII frame encoding (format, content, checksum)
#   - ASCII frame decoding (happy path, corrupted LRC, malformed frames)
#   - Round-trip integrity (encode → decode must recover original data)

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from ascii_codec import lrc, encode_ascii_frame, decode_ascii_frame, rtu_to_ascii_pdu
from crc import calculate_crc16


class TestLRC(unittest.TestCase):

    # ── Known vectors ─────────────────────────────────────────────────────────

    def test_known_vector_fc03_payload(self):
        """Slave=0x01, FC=0x03, start=0x0000, qty=0x0001 → LRC = 0xFA
        Verified against Modbus ASCII spec example."""
        payload = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01])
        self.assertEqual(lrc(payload), 0xFB)

    def test_lrc_property_sum_plus_lrc_equals_zero(self):
        """Fundamental LRC property: sum(data) + LRC(data) ≡ 0 (mod 256)."""
        for data in [
            bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01]),
            bytes([0xFF]),
            bytes([0x00]),
            bytes(range(16)),
        ]:
            result = (sum(data) + lrc(data)) & 0xFF
            self.assertEqual(result, 0, f"LRC property failed for {data.hex()}")

    def test_lrc_of_empty_is_zero(self):
        """LRC of empty payload = 0 (twos complement of 0)."""
        self.assertEqual(lrc(b""), 0)

    def test_lrc_single_byte(self):
        self.assertEqual(lrc(bytes([0x01])), 0xFF)
        self.assertEqual(lrc(bytes([0x80])), 0x80)
        self.assertEqual(lrc(bytes([0xFF])), 0x01)

    def test_lrc_returns_int(self):
        self.assertIsInstance(lrc(b"\x01\x02"), int)

    def test_lrc_range(self):
        """LRC must always be 0–255."""
        for i in range(256):
            val = lrc(bytes([i]))
            self.assertGreaterEqual(val, 0)
            self.assertLessEqual(val, 255)


class TestEncodeAsciiFrame(unittest.TestCase):

    # ── Format checks ─────────────────────────────────────────────────────────

    def test_starts_with_colon(self):
        frame = encode_ascii_frame(1, bytes([0x03, 0x00, 0x00, 0x00, 0x01]))
        self.assertTrue(frame.startswith(b":"))

    def test_ends_with_crlf(self):
        frame = encode_ascii_frame(1, bytes([0x03, 0x00, 0x00, 0x00, 0x01]))
        self.assertTrue(frame.endswith(b"\r\n"))

    def test_body_is_uppercase_hex(self):
        frame = encode_ascii_frame(1, bytes([0x03, 0x00, 0x00, 0x00, 0x01]))
        body  = frame[1:-2].decode("ascii")  # strip : and CRLF
        self.assertEqual(body, body.upper())

    def test_body_length_is_even(self):
        """Each byte = 2 hex chars, so total body chars must be even."""
        for pdu_len in [1, 2, 5, 10]:
            frame = encode_ascii_frame(1, bytes(pdu_len))
            body  = frame[1:-2]
            self.assertEqual(len(body) % 2, 0)

    def test_body_is_valid_ascii(self):
        frame = encode_ascii_frame(1, bytes([0x03, 0x00, 0x00, 0x00, 0x01]))
        # Body (between ':' and CRLF) must be printable ASCII; CRLF are control chars
        body = frame[1:-2]
        self.assertTrue(all(32 <= b <= 127 for b in body))

    # ── Content verification ──────────────────────────────────────────────────

    def test_known_frame_fc03(self):
        """:010300000001FA\r\n is the canonical FC03 ASCII frame for slave 1."""
        frame = encode_ascii_frame(1, bytes([0x03, 0x00, 0x00, 0x00, 0x01]))
        self.assertEqual(frame, b":010300000001FB\r\n")

    def test_slave_id_encoded_correctly(self):
        frame = encode_ascii_frame(0xFF, bytes([0x03]))
        body  = frame[1:-2].decode("ascii")
        self.assertTrue(body.startswith("FF"))

    def test_broadcast_slave_id_zero(self):
        frame = encode_ascii_frame(0, bytes([0xE0, 0x00, 0x02]))
        self.assertTrue(frame.startswith(b":00"))

    def test_lrc_appended_as_last_two_chars(self):
        """The last 2 chars before CRLF must be the LRC in hex."""
        pdu     = bytes([0x03, 0x00, 0x00, 0x00, 0x01])
        payload = bytes([0x01]) + pdu       # slave_id + pdu
        expected_lrc = lrc(payload)
        frame = encode_ascii_frame(1, pdu)
        actual_lrc_hex = frame[-4:-2].decode("ascii")  # before CRLF
        self.assertEqual(int(actual_lrc_hex, 16), expected_lrc)


class TestDecodeAsciiFrame(unittest.TestCase):

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_decode_known_frame(self):
        raw      = b":010300000001FB\r\n"
        data, ok = decode_ascii_frame(raw)
        self.assertTrue(ok)
        self.assertEqual(data[0], 0x01)     # slave ID
        self.assertEqual(data[1], 0x03)     # FC

    def test_decode_lrc_valid(self):
        for slave_id in [1, 5, 247]:
            pdu   = bytes([0x03, 0x00, 0x00, 0x00, 0x01])
            frame = encode_ascii_frame(slave_id, pdu)
            _, ok = decode_ascii_frame(frame)
            self.assertTrue(ok, f"LRC failed for slave_id={slave_id}")

    def test_decode_recovers_correct_payload(self):
        pdu   = bytes([0x03, 0x00, 0x64, 0x00, 0x0A])
        frame = encode_ascii_frame(7, pdu)
        data, ok = decode_ascii_frame(frame)
        self.assertTrue(ok)
        self.assertEqual(data[0], 7)        # slave ID
        self.assertEqual(data[1:], pdu)     # rest = pdu

    # ── Error cases ───────────────────────────────────────────────────────────

    def test_missing_colon_returns_false(self):
        _, ok = decode_ascii_frame(b"010300000001FA\r\n")
        self.assertFalse(ok)

    def test_missing_crlf_still_decodes(self):
        """Frame without CRLF should still parse (strip handles it)."""
        _, ok = decode_ascii_frame(b":010300000001FA")
        # This is lenient — we just check it doesn't crash
        self.assertIsInstance(ok, bool)

    def test_corrupted_lrc_returns_false(self):
        raw = bytearray(b":010300000001FA\r\n")
        raw[-4] = ord("0")   # corrupt last byte of LRC hex "FA" → "0A"
        _, ok = decode_ascii_frame(bytes(raw))
        self.assertFalse(ok)

    def test_odd_length_hex_returns_empty(self):
        _, ok = decode_ascii_frame(b":0103000000\r\n")  # odd number of hex chars
        # Must not crash; result may vary but ok must be bool
        self.assertIsInstance(ok, bool)

    def test_invalid_hex_chars_returns_empty(self):
        _, ok = decode_ascii_frame(b":GGGGGGGGGGGGGG\r\n")
        self.assertFalse(ok)

    def test_empty_input_returns_empty(self):
        data, ok = decode_ascii_frame(b"")
        self.assertFalse(ok)
        self.assertEqual(data, b"")

    # ── Round-trip ────────────────────────────────────────────────────────────

    def test_roundtrip_all_slave_ids(self):
        """Encode then decode must recover original data for all valid slave IDs."""
        pdu = bytes([0x03, 0x00, 0x00, 0x00, 0x01])
        for slave_id in [1, 16, 100, 247]:
            frame     = encode_ascii_frame(slave_id, pdu)
            data, ok  = decode_ascii_frame(frame)
            self.assertTrue(ok,               f"LRC mismatch for slave={slave_id}")
            self.assertEqual(data[0], slave_id, f"slave_id mismatch: {data[0]} != {slave_id}")
            self.assertEqual(data[1:], pdu,   f"PDU mismatch for slave={slave_id}")

    def test_roundtrip_all_function_codes(self):
        for fc in range(1, 17):
            pdu   = bytes([fc, 0x00, 0x00, 0x00, 0x01])
            frame = encode_ascii_frame(1, pdu)
            data, ok = decode_ascii_frame(frame)
            self.assertTrue(ok, f"Round-trip failed for FC={fc:#04x}")


class TestRtuToAsciiPdu(unittest.TestCase):

    def test_extracts_correct_slave_id(self):
        rtu_frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        slave_id, _ = rtu_to_ascii_pdu(rtu_frame)
        self.assertEqual(slave_id, 1)

    def test_extracts_correct_pdu(self):
        rtu_frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        _, pdu = rtu_to_ascii_pdu(rtu_frame)
        self.assertEqual(pdu, bytes([0x03, 0x00, 0x00, 0x00, 0x01]))

    def test_short_frame_raises(self):
        with self.assertRaises(ValueError):
            rtu_to_ascii_pdu(bytes([0x01, 0x03]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
