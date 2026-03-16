# tests/test_frame_builder.py
# ── FrameBuilder ─────────────────────────────────────────────────────────────
#
# Ensures every supported Function Code produces a correctly structured frame.
# Tests verify byte-level structure, field positions, and boundary conditions.
# An incorrect frame would be silently misinterpreted by real devices.

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from query import FrameBuilder
from crc   import verify_crc, calculate_crc16


def with_crc(frame: bytes) -> bytes:
    return frame + calculate_crc16(frame)


class TestFrameBuilderReadFunctions(unittest.TestCase):
    """FC01, FC02, FC03, FC04 all share the same [addr][qty] format."""

    def _assert_read_frame(self, fc, slave_id, address, quantity):
        frame = FrameBuilder.build(slave_id=slave_id, fc=fc, address=address, quantity=quantity)
        self.assertEqual(len(frame), 6)
        self.assertEqual(frame[0], slave_id)
        self.assertEqual(frame[1], fc)
        self.assertEqual(struct.unpack(">H", frame[2:4])[0], address)
        self.assertEqual(struct.unpack(">H", frame[4:6])[0], quantity)

    def test_fc01_read_coils_structure(self):
        self._assert_read_frame(0x01, 1, 0, 8)

    def test_fc02_read_discrete_inputs_structure(self):
        self._assert_read_frame(0x02, 5, 100, 16)

    def test_fc03_read_holding_registers_structure(self):
        self._assert_read_frame(0x03, 1, 0, 1)

    def test_fc04_read_input_registers_structure(self):
        self._assert_read_frame(0x04, 247, 1000, 125)

    def test_read_address_boundary_zero(self):
        frame = FrameBuilder.build(1, 0x03, address=0, quantity=1)
        self.assertEqual(struct.unpack(">H", frame[2:4])[0], 0)

    def test_read_address_boundary_max(self):
        frame = FrameBuilder.build(1, 0x03, address=0xFFFF, quantity=1)
        self.assertEqual(struct.unpack(">H", frame[2:4])[0], 0xFFFF)

    def test_read_quantity_minimum(self):
        frame = FrameBuilder.build(1, 0x03, quantity=1)
        self.assertEqual(struct.unpack(">H", frame[4:6])[0], 1)

    def test_read_quantity_maximum(self):
        frame = FrameBuilder.build(1, 0x03, quantity=125)
        self.assertEqual(struct.unpack(">H", frame[4:6])[0], 125)

    def test_read_quantity_zero_raises(self):
        with self.assertRaises(ValueError):
            FrameBuilder.build(1, 0x03, quantity=0)

    def test_read_quantity_over_max_raises(self):
        with self.assertRaises(ValueError):
            FrameBuilder.build(1, 0x03, quantity=2001)

    def test_all_valid_slave_ids(self):
        for sid in [1, 127, 247]:
            frame = FrameBuilder.build(sid, 0x03, address=0, quantity=1)
            self.assertEqual(frame[0], sid)


class TestFrameBuilderWriteSingle(unittest.TestCase):

    def test_fc05_write_coil_on_value(self):
        """Coil ON = 0xFF00."""
        frame = FrameBuilder.build(1, 0x05, address=0, values=[1])
        self.assertEqual(struct.unpack(">H", frame[4:6])[0], 0xFF00)

    def test_fc05_write_coil_off_value(self):
        """Coil OFF = 0x0000."""
        frame = FrameBuilder.build(1, 0x05, address=0, values=[0])
        self.assertEqual(struct.unpack(">H", frame[4:6])[0], 0x0000)

    def test_fc05_default_values_is_on(self):
        """No values arg → coil ON."""
        frame = FrameBuilder.build(1, 0x05, address=0)
        self.assertEqual(struct.unpack(">H", frame[4:6])[0], 0xFF00)

    def test_fc05_address_encoded_correctly(self):
        frame = FrameBuilder.build(1, 0x05, address=0x0042, values=[1])
        self.assertEqual(struct.unpack(">H", frame[2:4])[0], 0x0042)

    def test_fc06_write_register_value(self):
        frame = FrameBuilder.build(1, 0x06, address=5, values=[1234])
        self.assertEqual(frame[0], 1)
        self.assertEqual(frame[1], 0x06)
        self.assertEqual(struct.unpack(">H", frame[2:4])[0], 5)
        self.assertEqual(struct.unpack(">H", frame[4:6])[0], 1234)

    def test_fc06_value_zero(self):
        frame = FrameBuilder.build(1, 0x06, address=0, values=[0])
        self.assertEqual(struct.unpack(">H", frame[4:6])[0], 0)

    def test_fc06_value_max_uint16(self):
        frame = FrameBuilder.build(1, 0x06, address=0, values=[0xFFFF])
        self.assertEqual(struct.unpack(">H", frame[4:6])[0], 0xFFFF)

    def test_fc06_value_over_max_raises(self):
        with self.assertRaises(ValueError):
            FrameBuilder.build(1, 0x06, address=0, values=[0x10000])

    def test_fc06_negative_value_raises(self):
        """Negative values are rejected — registers are unsigned 0-65535."""
        with self.assertRaises(ValueError):
            FrameBuilder.build(1, 0x06, address=0, values=[-1])


class TestFrameBuilderWriteMultiple(unittest.TestCase):

    def test_fc0f_coil_byte_packing(self):
        """8 coils: [1,0,1,1,0,1,0,1] → 0xAD."""
        coils = [1, 0, 1, 1, 0, 1, 0, 1]
        frame = FrameBuilder.build(1, 0x0F, address=0, values=coils)
        byte_count = frame[6]
        self.assertEqual(byte_count, 1)
        self.assertEqual(frame[7], 0b10101101)   # LSB first: bit0=val[0], bit1=val[1]…

    def test_fc0f_coil_count_in_frame(self):
        coils = [1] * 8
        frame = FrameBuilder.build(1, 0x0F, address=0, values=coils)
        self.assertEqual(struct.unpack(">H", frame[4:6])[0], 8)

    def test_fc0f_partial_byte_coils(self):
        """4 coils → still 1 byte (padded with zeros)."""
        coils = [1, 0, 1, 1]
        frame = FrameBuilder.build(1, 0x0F, address=0, values=coils)
        byte_count = frame[6]
        self.assertEqual(byte_count, 1)
        self.assertEqual(frame[7] & 0x0F, 0b1101)   # only lower 4 bits matter

    def test_fc0f_empty_values_raises(self):
        with self.assertRaises(ValueError):
            FrameBuilder.build(1, 0x0F, address=0, values=[])

    def test_fc10_register_data_encoding(self):
        values = [100, 200, 300]
        frame  = FrameBuilder.build(1, 0x10, address=0, values=values)
        byte_count = frame[6]
        self.assertEqual(byte_count, 6)         # 3 registers × 2 bytes
        # parse values from frame
        parsed = [struct.unpack(">H", frame[7 + i*2: 9 + i*2])[0] for i in range(3)]
        self.assertEqual(parsed, values)

    def test_fc10_register_count_in_frame(self):
        values = [1, 2, 3, 4, 5]
        frame  = FrameBuilder.build(1, 0x10, address=0, values=values)
        self.assertEqual(struct.unpack(">H", frame[4:6])[0], 5)

    def test_fc10_single_register(self):
        frame = FrameBuilder.build(1, 0x10, address=10, values=[42])
        self.assertEqual(struct.unpack(">H", frame[2:4])[0], 10)
        self.assertEqual(struct.unpack(">H", frame[7:9])[0], 42)

    def test_fc10_empty_values_raises(self):
        with self.assertRaises(ValueError):
            FrameBuilder.build(1, 0x10, address=0, values=[])


class TestFrameBuilderSpecialFunctions(unittest.TestCase):

    def test_fc11_report_slave_id(self):
        frame = FrameBuilder.build(1, 0x11)
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame[0], 1)
        self.assertEqual(frame[1], 0x11)

    def test_fc17_read_write_structure(self):
        frame = FrameBuilder.build(1, 0x17, address=0, quantity=2, values=[10, 20])
        self.assertEqual(frame[0], 1)
        self.assertEqual(frame[1], 0x17)

    def test_fc17_empty_write_values_raises(self):
        with self.assertRaises(ValueError):
            FrameBuilder.build(1, 0x17, address=0, quantity=2, values=[])

    def test_unsupported_fc_raises(self):
        with self.assertRaises(ValueError):
            FrameBuilder.build(1, 0xFF)


class TestFrameBuilderValidation(unittest.TestCase):

    def test_slave_id_zero_allowed(self):
        """Slave ID 0 = broadcast — valid."""
        frame = FrameBuilder.build(0, 0x03, address=0, quantity=1)
        self.assertEqual(frame[0], 0)

    def test_slave_id_247_allowed(self):
        frame = FrameBuilder.build(247, 0x03, address=0, quantity=1)
        self.assertEqual(frame[0], 247)

    def test_slave_id_negative_raises(self):
        with self.assertRaises(ValueError):
            FrameBuilder.build(-1, 0x03)

    def test_slave_id_248_raises(self):
        with self.assertRaises(ValueError):
            FrameBuilder.build(248, 0x03)

    def test_address_negative_raises(self):
        with self.assertRaises(ValueError):
            FrameBuilder.build(1, 0x03, address=-1)

    def test_address_over_65535_raises(self):
        with self.assertRaises(ValueError):
            FrameBuilder.build(1, 0x03, address=0x10000)

    def test_all_fc_produce_bytes(self):
        for fc, kwargs in [
            (0x01, dict(quantity=8)),
            (0x03, dict(quantity=1)),
            (0x05, dict(values=[1])),
            (0x06, dict(values=[100])),
            (0x0F, dict(values=[1,0,1,1])),
            (0x10, dict(values=[100,200])),
            (0x11, {}),
        ]:
            result = FrameBuilder.build(1, fc, address=0, **kwargs)
            self.assertIsInstance(result, bytes, f"FC={fc:#04x} did not return bytes")
            self.assertGreater(len(result), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
