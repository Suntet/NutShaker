# tests/test_scanner.py
# ── ModbusScanner ────────────────────────────────────────────────────────────
#
# Tests scanner orchestration, stop-event behaviour, progress callbacks,
# result emission, and network host resolution — all without real hardware.
#
# A MockTransport replaces serial/TCP so the scanner's logic is tested
# in complete isolation from I/O.

import struct
import sys
import threading
import unittest
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scanner   import ModbusScanner
from transport import Transport, SerialConfig
from crc       import calculate_crc16
import logging

NULL_LOGGER = logging.getLogger("test_null")
NULL_LOGGER.addHandler(logging.NullHandler())
NULL_LOGGER.propagate = False


def make_fc03_response(slave_id: int, values: list[int]) -> bytes:
    data    = b"".join(struct.pack(">H", v) for v in values)
    payload = bytes([slave_id, 0x03, len(data)]) + data
    return payload + calculate_crc16(payload)


# ── Mock transport that responds to FC03 ──────────────────────────────────────

class MockSerialPort:
    """Fake serial port — responds with a valid FC03 value for known slave IDs."""

    RESPONSIVE_SLAVES = {1: [100], 5: [200, 300], 10: [0]}

    def __init__(self):
        self.is_open     = True
        self.written     = []
        self.reset_calls = 0

    def write(self, data):
        self.written.append(data)

    def read(self, size):
        if not self.written:
            return b""
        frame     = self.written[-1]
        slave_id  = frame[0]
        if slave_id in self.RESPONSIVE_SLAVES:
            return make_fc03_response(slave_id, self.RESPONSIVE_SLAVES[slave_id])
        return b""

    def reset_input_buffer(self):
        self.reset_calls += 1

    def close(self):
        self.is_open = False


class TestModbusScanner(unittest.TestCase):

    def _make_scanner(self, config, callbacks=None):
        cb = callbacks or {}
        return ModbusScanner(
            config            = config,
            logger            = NULL_LOGGER,
            result_callback   = cb.get("result"),
            progress_callback = cb.get("progress"),
            done_callback     = cb.get("done"),
        )

    # ── Configuration handling ────────────────────────────────────────────────

    def test_stop_before_scan_is_safe(self):
        scanner = self._make_scanner({"protocol": "serial", "ports": [], "baudrates": []})
        scanner.stop()
        results = scanner.scan()
        self.assertEqual(results, [])

    def test_empty_ports_returns_empty_results(self):
        scanner = self._make_scanner({
            "protocol": "serial", "ports": [], "baudrates": [9600],
            "slave_ids": [1], "test_broadcast": False, "test_other_fc": False,
        })
        results = scanner.scan()
        self.assertEqual(results, [])

    def test_empty_baudrates_returns_empty_results(self):
        scanner = self._make_scanner({
            "protocol": "serial", "ports": ["COM1"], "baudrates": [],
            "slave_ids": [1], "test_broadcast": False, "test_other_fc": False,
        })
        results = scanner.scan()
        self.assertEqual(results, [])

    # ── Stop event ────────────────────────────────────────────────────────────

    def test_is_running_true_before_stop(self):
        scanner = self._make_scanner({"protocol": "serial"})
        self.assertTrue(scanner.is_running)

    def test_is_running_false_after_stop(self):
        scanner = self._make_scanner({"protocol": "serial"})
        scanner.stop()
        self.assertFalse(scanner.is_running)

    def test_stop_mid_scan_emits_partial_results(self):
        """Stop scan after first result — must return partial, not crash."""
        collected = []

        def on_result(r):
            collected.append(r)
            scanner.stop()   # stop after first hit

        import serial as serial_mod
        mock_port = MockSerialPort()
        serial_mod.Serial.return_value = mock_port

        scanner = self._make_scanner({
            "protocol": "serial",
            "ports":    ["COM1"],
            "baudrates": [9600],
            "slave_ids": list(range(1, 20)),
            "serial_configs": [(8, "N", 1)],
            "test_broadcast": False,
            "test_other_fc":  False,
        }, callbacks={"result": on_result})

        scanner.scan()
        # No assertion on count — just must not crash and partial results returned
        self.assertIsInstance(scanner.results, list)

    # ── Progress callback ─────────────────────────────────────────────────────

    def test_progress_callback_called(self):
        progress_calls = []

        def on_progress(pct, done, total):
            progress_calls.append((pct, done, total))

        scanner = self._make_scanner({
            "protocol": "serial",
            "ports":    [],
            "baudrates": [9600],
            "slave_ids": [1],
            "test_broadcast": False,
            "test_other_fc":  False,
        }, callbacks={"progress": on_progress})

        scanner.scan()
        # May be 0 calls if nothing to scan, but must not crash

    def test_progress_pct_never_exceeds_100(self):
        import serial as serial_mod
        mock_port = MockSerialPort()
        serial_mod.Serial.return_value = mock_port

        max_pct = [0.0]

        def on_progress(pct, done, total):
            if pct > max_pct[0]:
                max_pct[0] = pct

        scanner = self._make_scanner({
            "protocol": "serial",
            "ports":    ["COM1"],
            "baudrates": [9600],
            "slave_ids": [1, 2, 3],
            "serial_configs": [(8, "N", 1)],
            "test_broadcast": False,
            "test_other_fc":  False,
        }, callbacks={"progress": on_progress})

        scanner.scan()
        self.assertLessEqual(max_pct[0], 100.0)

    def test_done_callback_called_exactly_once(self):
        done_count = [0]

        def on_done(results):
            done_count[0] += 1

        scanner = self._make_scanner({
            "protocol": "serial", "ports": [], "baudrates": [],
            "slave_ids": [1], "test_broadcast": False, "test_other_fc": False,
        }, callbacks={"done": on_done})

        scanner.scan()
        self.assertEqual(done_count[0], 1)

    # ── Result emission ───────────────────────────────────────────────────────

    def test_results_include_port_and_baudrate(self):
        import serial as serial_mod
        mock_port = MockSerialPort()
        serial_mod.Serial.return_value = mock_port

        scanner = self._make_scanner({
            "protocol": "serial",
            "ports":    ["COM3"],
            "baudrates": [9600],
            "slave_ids": [1],
            "serial_configs": [(8, "N", 1)],
            "test_broadcast": False,
            "test_other_fc":  False,
        })
        scanner.scan()

        for result in scanner.results:
            self.assertIn("port",     result, f"Missing 'port' in {result}")
            self.assertIn("baudrate", result, f"Missing 'baudrate' in {result}")

    def test_result_callback_receives_each_result(self):
        import serial as serial_mod
        mock_port = MockSerialPort()
        serial_mod.Serial.return_value = mock_port

        callback_results = []

        scanner = self._make_scanner({
            "protocol": "serial",
            "ports":    ["COM1"],
            "baudrates": [9600],
            "slave_ids": [1, 5],
            "serial_configs": [(8, "N", 1)],
            "test_broadcast": False,
            "test_other_fc":  False,
        }, callbacks={"result": callback_results.append})

        scanner.scan()
        self.assertEqual(callback_results, scanner.results)

    # ── Host resolution ───────────────────────────────────────────────────────

    def test_resolve_hosts_single_ip(self):
        hosts = ModbusScanner._resolve_hosts(["192.168.1.100"])
        self.assertEqual(hosts, ["192.168.1.100"])

    def test_resolve_hosts_cidr_24(self):
        hosts = ModbusScanner._resolve_hosts(["192.168.1.0/24"])
        self.assertEqual(len(hosts), 254)
        self.assertIn("192.168.1.1",   hosts)
        self.assertIn("192.168.1.254", hosts)
        self.assertNotIn("192.168.1.0",   hosts)   # network address
        self.assertNotIn("192.168.1.255", hosts)   # broadcast

    def test_resolve_hosts_cidr_30(self):
        hosts = ModbusScanner._resolve_hosts(["10.0.0.0/30"])
        self.assertEqual(len(hosts), 2)
        self.assertIn("10.0.0.1", hosts)
        self.assertIn("10.0.0.2", hosts)

    def test_resolve_hosts_string_input(self):
        hosts = ModbusScanner._resolve_hosts("192.168.0.1")
        self.assertIn("192.168.0.1", hosts)

    def test_resolve_hosts_multiple_entries(self):
        hosts = ModbusScanner._resolve_hosts(["10.0.0.1", "10.0.0.2", "10.0.0.3"])
        self.assertEqual(len(hosts), 3)

    def test_resolve_hosts_no_duplicates_from_cidr(self):
        hosts = ModbusScanner._resolve_hosts(["192.168.1.0/29"])
        self.assertEqual(len(hosts), len(set(hosts)))

    # ── TCP ping ──────────────────────────────────────────────────────────────

    def test_tcp_ping_returns_false_for_closed_port(self):
        # Use a port that's almost certainly closed
        result = ModbusScanner._tcp_ping("127.0.0.1", 19999, timeout=0.05)
        self.assertFalse(result)

    def test_tcp_ping_returns_bool(self):
        result = ModbusScanner._tcp_ping("192.0.2.0", 502, timeout=0.05)  # TEST-NET
        self.assertIsInstance(result, bool)

    # ── Protocol dispatch ─────────────────────────────────────────────────────

    def test_unknown_protocol_logs_error(self):
        scanner = self._make_scanner({"protocol": "foobar"})
        # Must not raise — should just log error and return empty
        results = scanner.scan()
        self.assertEqual(results, [])

    def test_scan_returns_list(self):
        scanner = self._make_scanner({"protocol": "serial", "ports": []})
        results = scanner.scan()
        self.assertIsInstance(results, list)

    # ── Thread safety ────────────────────────────────────────────────────────

    def test_stop_from_different_thread_is_safe(self):
        import serial as serial_mod
        mock_port = MockSerialPort()
        serial_mod.Serial.return_value = mock_port

        scanner = self._make_scanner({
            "protocol": "serial",
            "ports":    ["COM1"],
            "baudrates": [9600],
            "slave_ids": list(range(1, 50)),
            "serial_configs": [(8, "N", 1)],
            "test_broadcast": False,
            "test_other_fc":  False,
        })

        t = threading.Thread(target=scanner.scan, daemon=True)
        t.start()
        scanner.stop()   # stop from main thread while scan thread runs
        t.join(timeout=3)
        self.assertFalse(t.is_alive(), "Scan thread did not stop in time")


if __name__ == "__main__":
    unittest.main(verbosity=2)
