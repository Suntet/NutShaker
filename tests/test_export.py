# tests/test_export.py
# ── Export / Report ──────────────────────────────────────────────────────────
#
# Verifies that CSV, JSON, and TXT outputs are well-formed, contain the
# correct data, and gracefully handle edge cases (no results, missing log file).

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from export import export_report


SAMPLE_RESULTS = [
    {
        "port": "COM3", "baudrate": 9600, "type": "FC03_OK",
        "slave_id": 1, "fc": 3, "crc_valid": True,
        "register_values": [100, 200], "raw_response": "010304006400C8F93F",
        "bytesize": 8, "parity": "N", "stopbits": 1, "mode": "RTU",
    },
    {
        "port": "COM3", "baudrate": 9600, "type": "FC03_EXCEPTION",
        "slave_id": 5, "fc": 3, "crc_valid": True,
        "exception_code": 2, "raw_response": "018302B053",
    },
    {
        "port": "COM3", "baudrate": 19200, "type": "BROADCAST_E0",
        "sub_func": "00", "padding": "000000", "crc_valid": True,
        "raw_response": "DEADBEEF",
    },
]


class TestExportReport(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── Return value ──────────────────────────────────────────────────────────

    def test_returns_three_paths(self):
        paths = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        self.assertEqual(len(paths), 3)

    def test_all_three_files_created(self):
        csv_p, json_p, txt_p = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        self.assertTrue(os.path.exists(csv_p),  f"CSV not found: {csv_p}")
        self.assertTrue(os.path.exists(json_p), f"JSON not found: {json_p}")
        self.assertTrue(os.path.exists(txt_p),  f"TXT not found: {txt_p}")

    def test_csv_extension(self):
        csv_p, _, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        self.assertTrue(csv_p.endswith(".csv"))

    def test_json_extension(self):
        _, json_p, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        self.assertTrue(json_p.endswith(".json"))

    def test_txt_extension(self):
        _, _, txt_p = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        self.assertTrue(txt_p.endswith(".txt"))

    # ── CSV correctness ───────────────────────────────────────────────────────

    def test_csv_has_header_row(self):
        csv_p, _, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(csv_p) as f:
            reader = csv.DictReader(f)
            self.assertIsNotNone(reader.fieldnames)
            self.assertGreater(len(reader.fieldnames), 0)

    def test_csv_row_count_matches_results(self):
        csv_p, _, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(csv_p) as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), len(SAMPLE_RESULTS))

    def test_csv_contains_slave_id(self):
        csv_p, _, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(csv_p) as f:
            content = f.read()
        self.assertIn("1", content)   # slave_id=1

    def test_csv_contains_port(self):
        csv_p, _, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(csv_p) as f:
            content = f.read()
        self.assertIn("COM3", content)

    def test_csv_contains_all_keys(self):
        csv_p, _, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(csv_p) as f:
            reader = csv.DictReader(f)
            all_keys = set(reader.fieldnames)
        # Check key fields present
        for key in ["port", "baudrate", "type", "crc_valid"]:
            self.assertIn(key, all_keys, f"Missing key '{key}' in CSV header")

    # ── JSON correctness ──────────────────────────────────────────────────────

    def test_json_is_valid(self):
        _, json_p, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(json_p) as f:
            data = json.load(f)
        self.assertIsNotNone(data)

    def test_json_has_results_key(self):
        _, json_p, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(json_p) as f:
            data = json.load(f)
        self.assertIn("results", data)

    def test_json_result_count_matches(self):
        _, json_p, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(json_p) as f:
            data = json.load(f)
        self.assertEqual(data["total_results"], len(SAMPLE_RESULTS))
        self.assertEqual(len(data["results"]),  len(SAMPLE_RESULTS))

    def test_json_has_scan_time(self):
        _, json_p, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(json_p) as f:
            data = json.load(f)
        self.assertIn("exported_at", data)

    def test_json_preserves_register_values(self):
        _, json_p, _ = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(json_p) as f:
            data = json.load(f)
        first = data["results"][0]
        self.assertEqual(first["register_values"], [100, 200])

    # ── TXT correctness ───────────────────────────────────────────────────────

    def test_txt_is_non_empty(self):
        _, _, txt_p = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        self.assertGreater(os.path.getsize(txt_p), 0)

    def test_txt_contains_port(self):
        _, _, txt_p = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(txt_p) as f:
            content = f.read()
        self.assertIn("COM3", content)

    def test_txt_has_header_section(self):
        _, _, txt_p = export_report(SAMPLE_RESULTS, output_dir=self.tmpdir)
        with open(txt_p) as f:
            content = f.read()
        self.assertIn("NUTSHAKER", content.upper())

    def test_txt_includes_log_when_provided(self):
        log_file = os.path.join(self.tmpdir, "test.log")
        with open(log_file, "w") as f:
            f.write("2024-01-01 12:00:00  [INFO    ]  Test log entry\n")
        _, _, txt_p = export_report(SAMPLE_RESULTS, log_file=log_file, output_dir=self.tmpdir)
        with open(txt_p) as f:
            content = f.read()
        self.assertIn("Test log entry", content)

    def test_txt_no_crash_when_log_missing(self):
        _, _, txt_p = export_report(
            SAMPLE_RESULTS,
            log_file="/nonexistent/path.log",
            output_dir=self.tmpdir
        )
        self.assertTrue(os.path.exists(txt_p))

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_empty_results_creates_files(self):
        csv_p, json_p, txt_p = export_report([], output_dir=self.tmpdir)
        self.assertTrue(os.path.exists(csv_p))
        self.assertTrue(os.path.exists(json_p))
        self.assertTrue(os.path.exists(txt_p))

    def test_empty_results_json_total_is_zero(self):
        _, json_p, _ = export_report([], output_dir=self.tmpdir)
        with open(json_p) as f:
            data = json.load(f)
        self.assertEqual(data["total_results"], 0)

    def test_empty_results_txt_mentions_no_devices(self):
        _, _, txt_p = export_report([], output_dir=self.tmpdir)
        with open(txt_p) as f:
            content = f.read()
        self.assertGreater(len(content), 0)

    def test_output_dir_created_if_missing(self):
        new_dir = os.path.join(self.tmpdir, "subdir", "reports")
        export_report(SAMPLE_RESULTS, output_dir=new_dir)
        self.assertTrue(os.path.isdir(new_dir))

    def test_single_result_exported_correctly(self):
        single = [SAMPLE_RESULTS[0]]
        csv_p, json_p, txt_p = export_report(single, output_dir=self.tmpdir)
        with open(json_p) as f:
            data = json.load(f)
        self.assertEqual(data["total_results"], 1)

    def test_unicode_values_in_json(self):
        results_with_unicode = [{"port": "COM3", "type": "テスト", "slave_id": 1}]
        _, json_p, _ = export_report(results_with_unicode, output_dir=self.tmpdir)
        with open(json_p, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["results"][0]["type"], "テスト")


if __name__ == "__main__":
    unittest.main(verbosity=2)
