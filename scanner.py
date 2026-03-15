# scanner.py
# Orkestrasi scan otomatis untuk Serial, TCP, dan UDP.
#
# Scan serial: coba semua kombinasi port × baudrate × (bytesize,parity,stopbits)
# Scan TCP:    coba semua host × unit_id di subnet yang diberikan
# Scan UDP:    sama seperti TCP tapi via UDP

import ipaddress
import logging
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable

from config    import (
    DEFAULT_BAUDRATES, DEFAULT_SLAVE_IDS,
    SUB_FUNCTIONS, PADDING_VARIANTS,
    OTHER_FC, OTHER_FC_TEST_SIDS,
    MAX_WORKERS, COMMON_SERIAL_CONFIGS,
    TCP_MODBUS_PORT, TCP_TIMEOUT,
)
from tester    import ModbusTester
from transport import (
    SerialConfig, TcpConfig, UdpConfig,
    SerialTransport, TcpTransport, UdpTransport,
)


class ModbusScanner:
    """
    Jalankan semua tes Modbus — Serial, TCP, atau UDP — dan kumpulkan hasilnya.

    Semua komunikasi ke luar lewat callback supaya bisa dipakai oleh GUI,
    CLI, atau bahkan script otomasi tanpa perubahan.

    Scan bisa dihentikan kapan saja dengan stop().
    """

    def __init__(
        self,
        config:            dict,
        logger:            logging.Logger,
        result_callback:   Callable[[dict], None]            | None = None,
        progress_callback: Callable[[float, int, int], None] | None = None,
        done_callback:     Callable[[list[dict]], None]      | None = None,
    ):
        self.config            = config
        self.logger            = logger
        self.result_callback   = result_callback
        self.progress_callback = progress_callback
        self.done_callback     = done_callback

        self.results: list[dict] = []
        self._stop       = threading.Event()
        self._done_count = 0
        self._total      = 0

    def stop(self) -> None:
        self._stop.set()

    @property
    def is_running(self) -> bool:
        return not self._stop.is_set()

    # ------------------------------------------------------------------
    # Entri utama
    # ------------------------------------------------------------------

    def scan(self) -> list[dict]:
        """
        Jalankan scan sesuai config.

        Key config:
          protocol        — "serial", "tcp", "udp"
          ports           — list port serial (untuk protocol=serial)
          baudrates       — list baudrate
          serial_configs  — list (bytesize,parity,stopbits), atau None=semua umum
          mode            — "RTU" atau "ASCII"
          slave_ids       — list slave ID untuk FC03
          test_broadcast  — bool
          test_other_fc   — bool
          hosts           — list IP (untuk tcp/udp), atau string "192.168.1.0/24"
          tcp_port        — port TCP/UDP (default 502)
          unit_ids        — list unit ID untuk TCP/UDP scan
        """
        start_time = datetime.now()
        protocol   = self.config.get("protocol", "serial").lower()

        self.logger.info("=" * 60)
        self.logger.info("  NutShaker — Scan Dimulai")
        self.logger.info(f"  Protokol : {protocol.upper()}")
        self.logger.info(f"  Waktu    : {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 60)

        if protocol == "serial":
            self._scan_serial()
        elif protocol == "tcp":
            self._scan_network("tcp")
        elif protocol == "udp":
            self._scan_network("udp")
        else:
            self.logger.error(f"Protokol tidak dikenal: {protocol}")

        elapsed = (datetime.now() - start_time).total_seconds()
        self.logger.info(f"\n{'='*60}")
        self.logger.info(
            f"  Selesai — {len(self.results)} hasil dalam {elapsed:.1f} detik"
        )
        self.logger.info("=" * 60)

        if self.done_callback:
            self.done_callback(self.results)
        return self.results

    # ------------------------------------------------------------------
    # Scan Serial
    # ------------------------------------------------------------------

    def _scan_serial(self) -> None:
        cfg           = self.config
        ports         = cfg.get("ports",          [])
        baudrates     = cfg.get("baudrates",       DEFAULT_BAUDRATES)
        serial_cfgs   = cfg.get("serial_configs",  COMMON_SERIAL_CONFIGS[:1])  # default 8N1
        mode          = cfg.get("mode",            "RTU")
        slave_ids     = cfg.get("slave_ids",       DEFAULT_SLAVE_IDS)
        do_bcast      = cfg.get("test_broadcast",  True)
        do_other_fc   = cfg.get("test_other_fc",   True)

        # Hitung total task untuk progress
        combos = len(ports) * len(baudrates) * len(serial_cfgs)
        self._total = (
            combos * len(slave_ids)
            + (combos * len(SUB_FUNCTIONS) * len(PADDING_VARIANTS) if do_bcast else 0)
            + (combos * len(OTHER_FC_TEST_SIDS) * len(OTHER_FC) if do_other_fc else 0)
        )

        self.logger.info(
            f"  Port     : {ports}\n"
            f"  Baudrate : {baudrates}\n"
            f"  Konfig   : {serial_cfgs}\n"
            f"  Mode     : {mode}\n"
            f"  Total    : {self._total:,} task"
        )

        for port in ports:
            if self._stop.is_set(): break
            self.logger.info(f"\n{'─'*60}\nPort: {port}")

            for baud in baudrates:
                if self._stop.is_set(): break

                for (bytesize, parity, stopbits) in serial_cfgs:
                    if self._stop.is_set(): break

                    cfg_label = f"{baud},{bytesize},{parity},{stopbits} [{mode}]"
                    self.logger.info(f"  {cfg_label}")

                    serial_cfg = SerialConfig(
                        port=port, baudrate=baud,
                        bytesize=bytesize, parity=parity, stopbits=stopbits,
                        mode=mode,
                        dtr=cfg.get("dtr", False),
                        rts=cfg.get("rts", False),
                    )
                    transport = SerialTransport(serial_cfg, self.logger)

                    if not transport.open():
                        skip = len(slave_ids)
                        if do_bcast:    skip += len(SUB_FUNCTIONS) * len(PADDING_VARIANTS)
                        if do_other_fc: skip += len(OTHER_FC_TEST_SIDS) * len(OTHER_FC)
                        self._advance(skip)
                        continue

                    meta = {
                        "port": port, "baudrate": baud,
                        "bytesize": bytesize, "parity": parity,
                        "stopbits": stopbits, "mode": mode,
                        "protocol": "serial",
                    }

                    try:
                        tester = ModbusTester(transport, self.logger)
                        self._run_fc03(tester, meta, slave_ids)
                        if do_bcast and not self._stop.is_set():
                            self._run_broadcast(tester, meta)
                        if do_other_fc and not self._stop.is_set():
                            self._run_other_fc(tester, meta)
                    finally:
                        transport.close()

    # ------------------------------------------------------------------
    # Scan TCP / UDP
    # ------------------------------------------------------------------

    def _scan_network(self, protocol: str) -> None:
        cfg      = self.config
        hosts    = self._resolve_hosts(cfg.get("hosts", []))
        port_num = cfg.get("tcp_port", TCP_MODBUS_PORT)
        unit_ids = cfg.get("unit_ids", list(range(1, 10)))  # coba 1-9 secara default
        slave_ids  = cfg.get("slave_ids", DEFAULT_SLAVE_IDS)
        do_other_fc = cfg.get("test_other_fc", True)

        self._total = len(hosts) * len(unit_ids) * (
            len(slave_ids)
            + (len(OTHER_FC_TEST_SIDS) * len(OTHER_FC) if do_other_fc else 0)
        )

        self.logger.info(
            f"  Host     : {len(hosts)} host\n"
            f"  Port     : {port_num}\n"
            f"  Unit IDs : {unit_ids}\n"
            f"  Total    : {self._total:,} task"
        )

        for host in hosts:
            if self._stop.is_set(): break

            # Cek dulu apakah host merespons (hemat waktu untuk host yang mati)
            if not self._tcp_ping(host, port_num):
                self.logger.debug(f"Host tidak merespons: {host}:{port_num}")
                self._advance(len(unit_ids) * (len(slave_ids) + (len(OTHER_FC_TEST_SIDS)*len(OTHER_FC) if do_other_fc else 0)))
                continue

            self.logger.info(f"\nHost aktif: {host}:{port_num}")

            for uid in unit_ids:
                if self._stop.is_set(): break

                if protocol == "tcp":
                    net_cfg   = TcpConfig(host=host, port=port_num, unit_id=uid, timeout=TCP_TIMEOUT)
                    transport = TcpTransport(net_cfg, self.logger)
                else:
                    net_cfg   = UdpConfig(host=host, port=port_num, unit_id=uid)
                    transport = UdpTransport(net_cfg, self.logger)

                if not transport.open():
                    self._advance(len(slave_ids) + (len(OTHER_FC_TEST_SIDS)*len(OTHER_FC) if do_other_fc else 0))
                    continue

                meta = {
                    "host": host, "tcp_port": port_num,
                    "unit_id": uid, "protocol": protocol,
                }

                try:
                    tester = ModbusTester(transport, self.logger)
                    self._run_fc03(tester, meta, slave_ids)
                    if do_other_fc and not self._stop.is_set():
                        self._run_other_fc(tester, meta)
                finally:
                    transport.close()

    # ------------------------------------------------------------------
    # Tiga blok tes
    # ------------------------------------------------------------------

    def _run_fc03(self, tester: ModbusTester, meta: dict, slave_ids: list[int]) -> None:
        self.logger.info(f"  [1/3] FC03 — {len(slave_ids)} slave ID (paralel)")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(tester.test_read_holding, sid): sid
                for sid in slave_ids
                if not self._stop.is_set()
            }
            for future in as_completed(futures):
                if self._stop.is_set(): break
                try:
                    result = future.result()
                except Exception as e:
                    self.logger.error(f"Thread error SID={futures[future]}: {e}")
                    result = None
                self._advance()
                if result:
                    result.update(meta)
                    self._emit(result)

    def _run_broadcast(self, tester: ModbusTester, meta: dict) -> None:
        total = len(SUB_FUNCTIONS) * len(PADDING_VARIANTS)
        self.logger.info(f"  [2/3] Broadcast FC=0xE0 — {total} kombinasi")
        for sub in SUB_FUNCTIONS:
            for pad in PADDING_VARIANTS:
                if self._stop.is_set(): return
                result = tester.test_broadcast_e0(sub, pad)
                self._advance()
                if result:
                    result.update(meta)
                    self._emit(result)

    def _run_other_fc(self, tester: ModbusTester, meta: dict) -> None:
        self.logger.info(f"  [3/3] FC tambahan — SID {OTHER_FC_TEST_SIDS}")
        for sid in OTHER_FC_TEST_SIDS:
            for fc in OTHER_FC:
                if self._stop.is_set(): return
                result = tester.test_fc(sid, fc)
                self._advance()
                if result:
                    result.update(meta)
                    self._emit(result)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _emit(self, result: dict) -> None:
        self.results.append(result)
        if self.result_callback:
            self.result_callback(result)

    def _advance(self, n: int = 1) -> None:
        self._done_count += n
        if self.progress_callback and self._total > 0:
            pct = min(self._done_count / self._total * 100, 100.0)
            self.progress_callback(pct, self._done_count, self._total)

    @staticmethod
    def _resolve_hosts(hosts_input) -> list[str]:
        """Terima list IP, CIDR, atau range — kembalikan list IP string."""
        result = []
        if isinstance(hosts_input, str):
            hosts_input = [hosts_input]
        for h in hosts_input:
            try:
                # Coba parse sebagai CIDR network (192.168.1.0/24)
                net = ipaddress.ip_network(h, strict=False)
                result.extend(str(ip) for ip in net.hosts())
            except ValueError:
                result.append(h)
        return result

    @staticmethod
    def _tcp_ping(host: str, port: int, timeout: float = 0.3) -> bool:
        """Cek cepat apakah port TCP terbuka — lebih hemat dari langsung connect Modbus."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (OSError, socket.timeout):
            return False
