# tests/test_response_parser.py
# ── ResponseParser ───────────────────────────────────────────────────────────
#
# Verifies that raw byte responses are decoded into correct structured data.
# Tests use real Modbus frame bytes (with valid CRC) to mimic actual device
# behaviour as closely as possible.

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from query import ResponseParser, format_parsed
from crc   import calculate_crc16


def make_frame(payload: bytes) -> bytes:
    return payload + calculate_crc16(payload)


class TestResponseParserFC01FC02(unittest.TestCase):
    """FC01 Read Coils / FC02 Read Discrete Inputs — same response format."""

    def _make_coil_response(self, slave_id, coil_byte):
        payload = bytes([slave_id, 0x01, 0x01, coil_byte])
        return make_frame(payload)

    def test_fc01_parses_coil_count(self):
        resp   = self._make_coil_response(1, 0xFF)
        parsed = ResponseParser.parse(0x01, resp)
        self.assertEqual(parsed["coil_count"], 8)

    def test_fc01_all_on(self):
        resp   = self._make_coil_response(1, 0xFF)
        parsed = ResponseParser.parse(0x01, resp)
        self.assertTrue(all(parsed["coils"]))

    def test_fc01_all_off(self):
        resp   = self._make_coil_response(1, 0x00)
        parsed = ResponseParser.parse(0x01, resp)
        self.assertFalse(any(parsed["coils"]))

    def test_fc01_alternating_coils(self):
        """0b10110101 decoded LSB-first: bit0=1,bit1=0,bit2=1,bit3=0,bit4=1,bit5=1,bit6=0,bit7=1."""
        resp   = self._make_coil_response(1, 0b10110101)
        parsed = ResponseParser.parse(0x01, resp)
        expected = [True, False, True, False, True, True, False, True]
        self.assertEqual(parsed["coils"], expected)

    def test_fc01_byte_count_stored(self):
        resp   = self._make_coil_response(1, 0xAA)
        parsed = ResponseParser.parse(0x01, resp)
        self.assertEqual(parsed["byte_count"], 1)

    def test_fc02_discrete_inputs_same_format(self):
        payload = bytes([1, 0x02, 0x01, 0x55])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x02, resp)
        self.assertIn("coils", parsed)
        self.assertEqual(parsed["coil_count"], 8)


class TestResponseParserFC03FC04(unittest.TestCase):
    """FC03 Read Holding / FC04 Read Input Registers."""

    def _make_register_response(self, slave_id, fc, values):
        data    = b"".join(struct.pack(">H", v) for v in values)
        payload = bytes([slave_id, fc, len(data)]) + data
        return make_frame(payload)

    def test_fc03_single_register(self):
        resp   = self._make_register_response(1, 0x03, [100])
        parsed = ResponseParser.parse(0x03, resp)
        self.assertEqual(parsed["registers"], [100])
        self.assertEqual(parsed["register_count"], 1)

    def test_fc03_multiple_registers(self):
        values = [100, 200, 300, 400, 500]
        resp   = self._make_register_response(1, 0x03, values)
        parsed = ResponseParser.parse(0x03, resp)
        self.assertEqual(parsed["registers"], values)
        self.assertEqual(parsed["register_count"], 5)

    def test_fc03_zero_value(self):
        resp   = self._make_register_response(1, 0x03, [0])
        parsed = ResponseParser.parse(0x03, resp)
        self.assertEqual(parsed["registers"], [0])

    def test_fc03_max_uint16_value(self):
        resp   = self._make_register_response(1, 0x03, [0xFFFF])
        parsed = ResponseParser.parse(0x03, resp)
        self.assertEqual(parsed["registers"], [0xFFFF])

    def test_fc03_signed_positive(self):
        resp   = self._make_register_response(1, 0x03, [100])
        parsed = ResponseParser.parse(0x03, resp)
        self.assertEqual(parsed["registers_signed"], [100])

    def test_fc03_signed_negative(self):
        """0x8000 = -32768 in signed 16-bit."""
        resp   = self._make_register_response(1, 0x03, [0x8000])
        parsed = ResponseParser.parse(0x03, resp)
        self.assertEqual(parsed["registers_signed"], [-32768])

    def test_fc03_signed_minus_one(self):
        resp   = self._make_register_response(1, 0x03, [0xFFFF])
        parsed = ResponseParser.parse(0x03, resp)
        self.assertEqual(parsed["registers_signed"], [-1])

    def test_fc03_crc_valid_set(self):
        resp   = self._make_register_response(1, 0x03, [100])
        parsed = ResponseParser.parse(0x03, resp)
        self.assertTrue(parsed["crc_valid"])

    def test_fc03_crc_invalid_detected(self):
        resp      = bytearray(self._make_register_response(1, 0x03, [100]))
        resp[-1] ^= 0xFF   # corrupt CRC
        parsed    = ResponseParser.parse(0x03, bytes(resp))
        self.assertFalse(parsed["crc_valid"])

    def test_fc04_same_format_as_fc03(self):
        resp   = self._make_register_response(1, 0x04, [999])
        parsed = ResponseParser.parse(0x04, resp)
        self.assertEqual(parsed["registers"], [999])


class TestResponseParserWriteEchoFC05FC06(unittest.TestCase):

    def test_fc05_coil_on_echo(self):
        payload = bytes([1, 0x05, 0x00, 0x00, 0xFF, 0x00])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x05, resp)
        self.assertTrue(parsed["coil_on"])
        self.assertEqual(parsed["address"], 0)

    def test_fc05_coil_off_echo(self):
        payload = bytes([1, 0x05, 0x00, 0x00, 0x00, 0x00])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x05, resp)
        self.assertFalse(parsed["coil_on"])

    def test_fc05_address_echo(self):
        payload = bytes([1, 0x05, 0x00, 0x0A, 0xFF, 0x00])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x05, resp)
        self.assertEqual(parsed["address"], 10)

    def test_fc06_register_value_echo(self):
        payload = bytes([1, 0x06, 0x00, 0x05, 0x04, 0xD2])  # addr=5, value=1234
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x06, resp)
        self.assertEqual(parsed["address"], 5)
        self.assertEqual(parsed["value"],   1234)

    def test_fc06_signed_positive(self):
        payload = bytes([1, 0x06, 0x00, 0x00, 0x00, 0x64])  # value=100
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x06, resp)
        self.assertEqual(parsed["value_signed"], 100)

    def test_fc06_signed_negative(self):
        payload = bytes([1, 0x06, 0x00, 0x00, 0xFF, 0xFF])  # value=65535 → -1 signed
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x06, resp)
        self.assertEqual(parsed["value_signed"], -1)


class TestResponseParserWriteMultipleEcho(unittest.TestCase):

    def test_fc0f_echo_address_and_quantity(self):
        payload = bytes([1, 0x0F, 0x00, 0x00, 0x00, 0x08])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x0F, resp)
        self.assertEqual(parsed["address"],          0)
        self.assertEqual(parsed["quantity_written"], 8)

    def test_fc10_echo_address_and_quantity(self):
        payload = bytes([1, 0x10, 0x00, 0x0A, 0x00, 0x03])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x10, resp)
        self.assertEqual(parsed["address"],          10)
        self.assertEqual(parsed["quantity_written"], 3)


class TestResponseParserReportSlaveID(unittest.TestCase):

    def test_fc11_slave_id_reported(self):
        payload = bytes([1, 0x11, 0x02, 0x01, 0xFF])  # slave_id=1, run=0xFF
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x11, resp)
        self.assertEqual(parsed["slave_id_reported"], 1)
        self.assertEqual(parsed["run_status"],        0xFF)

    def test_fc11_byte_count(self):
        payload = bytes([1, 0x11, 0x02, 0x01, 0xFF])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x11, resp)
        self.assertEqual(parsed["byte_count"], 2)


class TestResponseParserExceptions(unittest.TestCase):

    def test_exception_flag_detected(self):
        payload = bytes([1, 0x83, 0x02])   # FC03 + 0x80 = 0x83
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x03, resp)
        self.assertTrue(parsed["is_exception"])

    def test_exception_code_extracted(self):
        for exc_code in [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x0A, 0x0B]:
            payload = bytes([1, 0x83, exc_code])
            resp    = make_frame(payload)
            parsed  = ResponseParser.parse(0x03, resp)
            self.assertEqual(parsed["exception_code"], exc_code,
                             f"Wrong exc_code for {exc_code:#04x}")

    def test_exception_description_present(self):
        payload = bytes([1, 0x83, 0x02])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x03, resp)
        self.assertIn("exception_desc", parsed)
        self.assertIn("Illegal Data Address", parsed["exception_desc"])

    def test_exception_original_fc_stored(self):
        payload = bytes([1, 0x83, 0x02])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x03, resp)
        self.assertEqual(parsed["original_fc"], 0x03)

    def test_all_standard_exception_fcs(self):
        for fc in [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x0F, 0x10]:
            payload = bytes([1, fc | 0x80, 0x01])
            resp    = make_frame(payload)
            parsed  = ResponseParser.parse(fc, resp)
            self.assertTrue(parsed["is_exception"])


class TestResponseParserEdgeCases(unittest.TestCase):

    def test_too_short_frame_returns_error(self):
        parsed = ResponseParser.parse(0x03, b"\x01\x03")
        self.assertIn("error", parsed)

    def test_empty_frame_returns_error(self):
        parsed = ResponseParser.parse(0x03, b"")
        self.assertIn("error", parsed)

    def test_slave_id_always_in_result(self):
        payload = bytes([7, 0x03, 0x02, 0x00, 0x64])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x03, resp)
        self.assertEqual(parsed["slave_id"], 7)

    def test_is_exception_false_for_normal_response(self):
        payload = bytes([1, 0x03, 0x02, 0x00, 0x64])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x03, resp)
        self.assertFalse(parsed["is_exception"])


class TestFormatParsed(unittest.TestCase):
    """format_parsed() produces human-readable one-line summaries."""

    def test_fc03_shows_registers(self):
        payload = bytes([1, 0x03, 0x04, 0x00, 0x64, 0x00, 0xC8])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x03, resp)
        text    = format_parsed(parsed)
        self.assertIn("100", text)
        self.assertIn("200", text)

    def test_exception_shows_code_and_description(self):
        payload = bytes([1, 0x83, 0x02])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x03, resp)
        text    = format_parsed(parsed)
        self.assertIn("EXCEPTION", text)
        self.assertIn("0x02", text)

    def test_empty_dict_returns_non_empty_string(self):
        text = format_parsed({})
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)

    def test_crc_ok_shown_for_valid_frame(self):
        payload = bytes([1, 0x03, 0x02, 0x00, 0x64])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x03, resp)
        text    = format_parsed(parsed)
        self.assertIn("CRC OK", text)

    def test_coils_shown_for_fc01(self):
        payload = bytes([1, 0x01, 0x01, 0xFF])
        resp    = make_frame(payload)
        parsed  = ResponseParser.parse(0x01, resp)
        text    = format_parsed(parsed)
        self.assertIn("Coil", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
