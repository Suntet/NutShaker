#!/usr/bin/env python3
"""
run_tests.py — Jalankan seluruh test suite NutShaker.

Cara pakai:
    python run_tests.py              # semua test
    python run_tests.py -v           # verbose (nama tiap test case)
    python run_tests.py -m crc       # hanya modul test_crc
    python run_tests.py -m crc,ascii # beberapa modul sekaligus
    python run_tests.py -f           # stop di test pertama yang gagal

Tidak butuh pytest — murni stdlib unittest.
"""

# ── pyserial mock (must happen before any nutshaker module is imported) ───────
import sys as _sys
import unittest.mock as _mock

_sm = _mock.MagicMock()
_sm.EIGHTBITS = 8;  _sm.PARITY_NONE = "N";  _sm.PARITY_EVEN = "E"
_sm.PARITY_ODD = "O"; _sm.PARITY_MARK = "M"; _sm.PARITY_SPACE = "S"
_sm.STOPBITS_ONE = 1; _sm.STOPBITS_TWO = 2; _sm.STOPBITS_ONE_POINT_FIVE = 1.5
_sm.SerialException = OSError
_lm = _mock.MagicMock(); _lm.comports.return_value = []
_sys.modules.setdefault("serial",                  _sm)
_sys.modules.setdefault("serial.tools",            _mock.MagicMock())
_sys.modules.setdefault("serial.tools.list_ports", _lm)
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import sys
import time
import unittest
from pathlib import Path


# ── Warna ANSI ────────────────────────────────────────────────────────────────
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    DIM    = "\033[2m"

    @staticmethod
    def ok(s):   return f"{C.GREEN}{C.BOLD}{s}{C.RESET}"
    @staticmethod
    def fail(s): return f"{C.RED}{C.BOLD}{s}{C.RESET}"
    @staticmethod
    def warn(s): return f"{C.YELLOW}{s}{C.RESET}"
    @staticmethod
    def info(s): return f"{C.CYAN}{s}{C.RESET}"
    @staticmethod
    def dim(s):  return f"{C.DIM}{s}{C.RESET}"


# ── Custom Result Printer ─────────────────────────────────────────────────────

class ColourResult(unittest.TextTestResult):
    """Overrides the default result to add colour and progress dots."""

    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.success_count = 0
        if not hasattr(self, 'verbosity'): self.verbosity = verbosity

    def addSuccess(self, test):
        super().addSuccess(test)
        self.success_count += 1
        if self.verbosity > 1:
            self.stream.writeln(C.ok("  PASS") + f"  {self.getDescription(test)}")
        else:
            self.stream.write(C.ok("."))
            self.stream.flush()

    def addError(self, test, err):
        super().addError(test, err)
        if self.verbosity > 1:
            self.stream.writeln(C.fail("  ERROR") + f" {self.getDescription(test)}")
        else:
            self.stream.write(C.fail("E"))
            self.stream.flush()

    def addFailure(self, test, err):
        super().addFailure(test, err)
        if self.verbosity > 1:
            self.stream.writeln(C.fail("  FAIL") + f"  {self.getDescription(test)}")
        else:
            self.stream.write(C.fail("F"))
            self.stream.flush()

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        if self.verbosity > 1:
            self.stream.writeln(C.warn("  SKIP") + f"  {self.getDescription(test)}  ({reason})")
        else:
            self.stream.write(C.warn("s"))
            self.stream.flush()


class ColourRunner(unittest.TextTestRunner):
    resultclass = ColourResult


# ── Modul yang tersedia ────────────────────────────────────────────────────────

MODULES = {
    "crc":          "tests.test_crc",
    "ascii":        "tests.test_ascii_codec",
    "frame":        "tests.test_frame_builder",
    "parser":       "tests.test_response_parser",
    "transport":    "tests.test_transport",
    "scanner":      "tests.test_scanner",
    "export":       "tests.test_export",
    "query":        "tests.test_query_sender",
    "integration":  "tests.test_integration",
}

MODULE_DESCRIPTIONS = {
    "crc":         "CRC-16 Modbus — kalkulasi & verifikasi",
    "ascii":       "Modbus ASCII — LRC, encode, decode",
    "frame":       "FrameBuilder — semua FC",
    "parser":      "ResponseParser — semua FC + exception",
    "transport":   "Transport — Serial, TCP, UDP configs & lifecycle",
    "scanner":     "ModbusScanner — orchestration & stop event",
    "export":      "Export — CSV, JSON, TXT report",
    "query":       "QuerySender — send/recv & factory methods",
    "integration": "Integration — pipeline end-to-end",
}


def main():
    # ── Ensure project root is on path ─────────────────────────────────────────
    root = Path(__file__).parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # ── Args ───────────────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(description="NutShaker Test Suite")
    parser.add_argument("-v", "--verbose",  action="store_true",
                        help="Tampilkan nama setiap test case")
    parser.add_argument("-m", "--modules",  default="",
                        help=f"Modul yang dijalankan, pisah koma. Tersedia: {','.join(MODULES)}")
    parser.add_argument("-f", "--failfast", action="store_true",
                        help="Berhenti di test pertama yang gagal")
    parser.add_argument("-l", "--list",     action="store_true",
                        help="Tampilkan daftar modul test yang tersedia")
    args = parser.parse_args()

    if args.list:
        print(C.info("\nModul test yang tersedia:"))
        for name, desc in MODULE_DESCRIPTIONS.items():
            print(f"  {C.BOLD}{name:<14}{C.RESET} {desc}")
        print()
        return

    # ── Pilih modul ────────────────────────────────────────────────────────────
    if args.modules:
        selected = [m.strip() for m in args.modules.split(",")]
        unknown  = [m for m in selected if m not in MODULES]
        if unknown:
            print(C.fail(f"Modul tidak dikenal: {unknown}"))
            print(f"Yang tersedia: {list(MODULES.keys())}")
            sys.exit(1)
        module_list = [(name, MODULES[name]) for name in selected]
    else:
        module_list = list(MODULES.items())

    # ── Header ─────────────────────────────────────────────────────────────────
    bar = "━" * 62
    print(f"\n{C.info(bar)}")
    print(f"  {C.BOLD}NutShaker — Test Suite{C.RESET}")
    print(f"  {len(module_list)} modul  ·  {C.dim('python ' + sys.version.split()[0])}")
    print(f"{C.info(bar)}\n")

    # ── Jalankan setiap modul ──────────────────────────────────────────────────
    total_run = total_fail = total_error = total_skip = 0
    failed_modules = []
    t_start = time.perf_counter()

    for short_name, module_path in module_list:
        desc = MODULE_DESCRIPTIONS.get(short_name, module_path)
        print(f"  {C.info('▶')} {C.BOLD}{short_name:<14}{C.RESET}  {C.dim(desc)}")

        try:
            suite = unittest.TestLoader().loadTestsFromName(module_path)
        except ModuleNotFoundError as e:
            print(C.fail(f"     Gagal load modul: {e}\n"))
            failed_modules.append(short_name)
            continue

        runner = ColourRunner(
            stream      = sys.stdout,
            verbosity   = 2 if args.verbose else 1,
            failfast    = args.failfast,
        )
        result = runner.run(suite)

        if not args.verbose:
            print()   # newline after dots

        total_run   += result.testsRun
        total_fail  += len(result.failures)
        total_error += len(result.errors)
        total_skip  += len(result.skipped)

        if result.failures or result.errors:
            failed_modules.append(short_name)
            if args.failfast:
                break
        print()

    elapsed = time.perf_counter() - t_start

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"{C.info(bar)}")
    print(f"  {C.BOLD}RINGKASAN{C.RESET}")
    print(f"{C.info(bar)}")

    passed = total_run - total_fail - total_error
    print(f"  Dijalankan : {total_run}")
    print(f"  {C.ok('Lulus')}     : {passed}")

    if total_fail:
        print(f"  {C.fail('Gagal')}     : {total_fail}")
    if total_error:
        print(f"  {C.fail('Error')}     : {total_error}")
    if total_skip:
        print(f"  {C.warn('Dilewati')}  : {total_skip}")
    if failed_modules:
        print(f"\n  Modul bermasalah: {C.fail(', '.join(failed_modules))}")

    print(f"\n  Waktu : {elapsed:.2f} detik")

    if not total_fail and not total_error and not failed_modules:
        print(f"\n  {C.ok('✅ Semua test lulus!')}")
    else:
        print(f"\n  {C.fail('❌ Ada test yang gagal.')}")

    print(f"{C.info(bar)}\n")

    sys.exit(0 if not total_fail and not total_error and not failed_modules else 1)


if __name__ == "__main__":
    main()
