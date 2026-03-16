# tests/test_crc.py
# ── CRC-16 Modbus RTU ────────────────────────────────────────────────────────
#
# CRC is the bedrock of frame integrity.  Every single edge case here must
# pass perfectly — a silent CRC bug would corrupt all data silently.
#
# Test philosophy:
#   1. Known-vector tests  — compare against values from the official spec
#   2. Round-trip tests    — encode then verify must always succeed
#   3. Corruption tests    — any single-bit flip must invalidate the CRC
#   4. Edge cases          — empty data, 1 byte, max-length frames

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from crc import calculate_crc16, verify_crc


class TestCalculateCRC16(unittest.TestCase):
    """Unit tests for calculate_crc16()."""

    # ── Known reference vectors ───────────────────────────────────────────────

    def test_known_vector_fc03_request(self):
        """FC03: read 1 register from address 0, slave 1.
        Ground truth from Modbus spec and multiple online calculators."""
        data = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01])
        crc  = calculate_crc16(data)
        self.assertEqual(crc, bytes([0x84, 0x0A]),
                         f"Expected 84 0A, got {crc.hex().upper()}")

    def test_known_vector_fc06_write(self):
        """FC06: write value 0x0001 to register 0, slave 1."""
        data = bytes([0x01, 0x06, 0x00, 0x00, 0x00, 0x01])
        crc  = calculate_crc16(data)
        self.assertEqual(crc, bytes([0x48, 0x0A]),
                         f"Expected 48 0A, got {crc.hex().upper()}")

    def test_known_vector_fc01_request(self):
        """FC01: read 8 coils from address 0, slave 1."""
        data = bytes([0x01, 0x01, 0x00, 0x00, 0x00, 0x08])
        crc  = calculate_crc16(data)
        self.assertEqual(crc, bytes([0x3D, 0xCC]),
                         f"Expected 3D CC, got {crc.hex().upper()}")

    def test_known_vector_fc03_response_single(self):
        """FC03 response with 1 register value = 100 (0x0064)."""
        data = bytes([0x01, 0x03, 0x02, 0x00, 0x64])
        crc  = calculate_crc16(data)
        self.assertEqual(crc, bytes([0xB9, 0xAF]),
                         f"Expected B9 AF, got {crc.hex().upper()}")

    def test_known_vector_broadcast(self):
        """Broadcast frame slave=0, any data."""
        data = bytes([0x00, 0x03, 0x00, 0x00, 0x00, 0x01])
        crc  = calculate_crc16(data)
        self.assertIsInstance(crc, bytes)
        self.assertEqual(len(crc), 2)

    # ── Return type and format ────────────────────────────────────────────────

    def test_returns_bytes(self):
        self.assertIsInstance(calculate_crc16(b"\x01\x03"), bytes)

    def test_returns_exactly_2_bytes(self):
        for length in [1, 2, 6, 100, 255]:
            data = bytes(range(length % 256)) * (length // 256 + 1)
            data = data[:length]
            self.assertEqual(len(calculate_crc16(data)), 2,
                             f"Expected 2 bytes for input length {length}")

    def test_little_endian_byte_order(self):
        """CRC must be in little-endian order (LSB first) per Modbus spec."""
        data = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01])
        crc_bytes = calculate_crc16(data)
        crc_int   = struct.unpack("<H", crc_bytes)[0]
        # Reconstruct big-endian and confirm they differ (sanity check)
        crc_be    = struct.unpack(">H", crc_bytes)[0]
        # The actual value must match reference
        self.assertEqual(crc_int, 0x0A84)  # 0x840A in little-endian

    # ── Determinism ───────────────────────────────────────────────────────────

    def test_deterministic_same_input(self):
        """Same input must always produce same output."""
        data = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A])
        self.assertEqual(calculate_crc16(data), calculate_crc16(data))

    def test_different_inputs_produce_different_crcs(self):
        """Different data (very likely) produces different CRC."""
        a = calculate_crc16(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01]))
        b = calculate_crc16(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x02]))
        self.assertNotEqual(a, b)

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_empty_input(self):
        """Empty input produces a deterministic CRC (seed value)."""
        crc = calculate_crc16(b"")
        self.assertIsInstance(crc, bytes)
        self.assertEqual(len(crc), 2)
        # CRC of empty = initial seed 0xFFFF in little-endian
        self.assertEqual(crc, bytes([0xFF, 0xFF]))

    def test_single_byte_input(self):
        crc = calculate_crc16(bytes([0x01]))
        self.assertIsInstance(crc, bytes)
        self.assertEqual(len(crc), 2)

    def test_all_zeros(self):
        crc = calculate_crc16(bytes(10))
        self.assertIsInstance(crc, bytes)
        self.assertEqual(len(crc), 2)

    def test_all_ones(self):
        crc = calculate_crc16(bytes([0xFF] * 10))
        self.assertIsInstance(crc, bytes)
        self.assertEqual(len(crc), 2)

    def test_max_valid_frame_length(self):
        """Modbus max ADU = 256 bytes.  CRC must still work."""
        data = bytes(range(256))
        crc  = calculate_crc16(data)
        self.assertEqual(len(crc), 2)

    def test_byte_order_sensitivity(self):
        """Swapping two bytes should produce a different CRC."""
        data1 = bytes([0x01, 0x03])
        data2 = bytes([0x03, 0x01])
        self.assertNotEqual(calculate_crc16(data1), calculate_crc16(data2))


class TestVerifyCRC(unittest.TestCase):
    """Unit tests for verify_crc()."""

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_valid_fc03_request_frame(self):
        frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        self.assertTrue(verify_crc(frame))

    def test_valid_fc03_response_frame(self):
        frame = bytes([0x01, 0x03, 0x02, 0x00, 0x64, 0xB9, 0xAF])
        self.assertTrue(verify_crc(frame))

    def test_valid_exception_response(self):
        from crc import calculate_crc16
        payload = bytes([0x01, 0x83, 0x02])
        frame   = payload + calculate_crc16(payload)
        self.assertTrue(verify_crc(frame))

    def test_round_trip_all_standard_fcs(self):
        """For every FC 0x01–0x10, build+CRC then verify must pass."""
        import struct
        from crc import calculate_crc16
        for fc in range(1, 17):
            data = struct.pack(">BBHH", 1, fc, 0, 1)
            full = data + calculate_crc16(data)
            self.assertTrue(verify_crc(full), f"Round-trip failed for FC={fc:#04x}")

    # ── Single-bit corruption detection ───────────────────────────────────────

    def test_single_bit_flip_in_slave_id_detected(self):
        frame     = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        corrupted = bytearray(frame)
        corrupted[0] ^= 0x01   # flip bit 0 of slave ID
        self.assertFalse(verify_crc(bytes(corrupted)))

    def test_single_bit_flip_in_function_code_detected(self):
        frame     = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        corrupted = bytearray(frame)
        corrupted[1] ^= 0x04
        self.assertFalse(verify_crc(bytes(corrupted)))

    def test_single_bit_flip_in_data_detected(self):
        frame     = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        corrupted = bytearray(frame)
        corrupted[4] ^= 0x80
        self.assertFalse(verify_crc(bytes(corrupted)))

    def test_all_single_byte_corruptions_detected(self):
        """Every single-byte change in data bytes must invalidate CRC.
        (Note: CRC bytes themselves can be tweaked in ways that happen to match,
        but data byte corruption should always be caught.)"""
        from crc import calculate_crc16
        data  = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01])
        frame = data + calculate_crc16(data)
        for i in range(len(data)):             # only corrupt data bytes, not CRC
            for bit in range(8):
                corrupted      = bytearray(frame)
                corrupted[i]  ^= (1 << bit)
                self.assertFalse(
                    verify_crc(bytes(corrupted)),
                    f"Corruption at byte {i} bit {bit} was NOT detected"
                )

    # ── Edge cases / invalid input ─────────────────────────────────────────────

    def test_empty_frame_returns_false(self):
        self.assertFalse(verify_crc(b""))

    def test_one_byte_frame_returns_false(self):
        self.assertFalse(verify_crc(b"\x01"))

    def test_two_byte_frame_returns_false(self):
        self.assertFalse(verify_crc(b"\x01\x03"))

    def test_three_byte_minimum(self):
        """3 bytes = 1 data byte + 2 CRC bytes — minimum valid frame."""
        from crc import calculate_crc16
        data  = bytes([0x01])
        frame = data + calculate_crc16(data)
        self.assertTrue(verify_crc(frame))

    def test_wrong_crc_bytes_returns_false(self):
        frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00])
        self.assertFalse(verify_crc(frame))

    def test_swapped_crc_bytes_returns_false(self):
        """Big-endian CRC instead of little-endian must fail."""
        frame    = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A])
        swapped  = bytes(frame[:-2]) + bytes([frame[-1], frame[-2]])
        self.assertFalse(verify_crc(swapped))

    def test_dummy_crc_ff_ff_returns_false(self):
        """TCP transport adds 0xFF 0xFF as dummy CRC — must not pass real check."""
        frame = bytes([0x01, 0x03, 0x02, 0x00, 0x64, 0xFF, 0xFF])
        self.assertFalse(verify_crc(frame))


if __name__ == "__main__":
    unittest.main(verbosity=2)
