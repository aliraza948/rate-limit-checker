#!/usr/bin/env python3
"""
Rate Limit Checker Bot
======================
Checks minutely / hourly / daily / weekly / monthly rate limits
for a list of URLs using curl_cffi with multi-threading.

URLs are cycled round-robin across threads.
Per-URL stats are tracked independently and written to the stat file.

Config: config.ini  |  Requires: curl_cffi
"""

import configparser
import itertools
import json
import logging
import os
import signal
import sys
import time
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    sys.exit("[FATAL] curl_cffi not installed. Run: pip install curl_cffi")

# ─────────────────────────────────────────────
#  Colour helpers
# ─────────────────────────────────────────────
_USE_COLOUR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text

RED    = lambda t: _c("91", t)
GREEN  = lambda t: _c("92", t)
YELLOW = lambda t: _c("93", t)
CYAN   = lambda t: _c("96", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)

# ─────────────────────────────────────────────
#  Config loader
# ─────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "config.ini"

def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if not CONFIG_FILE.exists():
        sys.exit(f"[FATAL] config.ini not found at {CONFIG_FILE}")
    cfg.read(CONFIG_FILE)
    return cfg

def parse_urls(cfg: configparser.ConfigParser) -> list[str]:
    raw = cfg.get("URLS", "urls", fallback="").strip()
    urls = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not urls:
        sys.exit("[FATAL] No URLs found in [URLS] urls = ...")
    return urls

# ─────────────────────────────────────────────
#  Logging setup
# ─────────────────────────────────────────────

def setup_logging(cfg: configparser.ConfigParser) -> logging.Logger:
    level_name = cfg.get("LOGGING", "log_level", fallback="INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(threadName)s │ %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_file = cfg.get("LOGGING", "log_file", fallback="").strip()
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers)
    return logging.getLogger("RateLimitBot")

# ─────────────────────────────────────────────
#  Sliding-window rate-limit tracker (global)
# ─────────────────────────────────────────────

class WindowCounter:
    WINDOWS = {
        "minute": 60,
        "hour":   3600,
        "day":    86400,
        "week":   604800,
        "month":  2592000,
    }

    def __init__(self, limits: dict[str, int]):
        self._limits = limits
        self._ts: deque[float] = deque()
        self._lock = threading.Lock()

    def record(self) -> None:
        with self._lock:
            self._ts.append(time.time())
            self._trim()

    def _trim(self) -> None:
        cutoff = time.time() - max(self.WINDOWS.values())
        while self._ts and self._ts[0] < cutoff:
            self._ts.popleft()

    def counts(self) -> dict[str, int]:
        now = time.time()
        with self._lock:
            self._trim()
            return {name: sum(1 for t in self._ts if t > now - secs)
                    for name, secs in self.WINDOWS.items()}

    def counts_raw(self) -> dict[str, dict]:
        now = time.time()
        with self._lock:
            self._trim()
            result = {}
            for name, secs in self.WINDOWS.items():
                cnt   = sum(1 for t in self._ts if t > now - secs)
                limit = self._limits.get(name, 0)
                result[name] = {
                    "count": cnt,
                    "limit": limit,
                    "pct":   round(cnt / limit * 100, 1) if limit > 0 else None,
                    "status": (
                        "ok"      if limit == 0 or cnt < limit * 0.8 else
                        "warning" if cnt < limit else
                        "exceeded"
                    ),
                }
        return result

    def is_limit_reached(self) -> tuple[bool, str]:
        counts = self.counts()
        for name, limit in self._limits.items():
            if limit > 0 and counts.get(name, 0) >= limit:
                return True, name
        return False, ""

    def snapshot(self) -> str:
        counts = self.counts()
        parts = []
        for name in ["minute", "hour", "day", "week", "month"]:
            limit = self._limits.get(name, 0)
            count = counts.get(name, 0)
            if limit > 0:
                pct = count / limit * 100
                colour = RED if pct >= 100 else YELLOW if pct >= 80 else GREEN
                parts.append(f"{name[:3].upper()}: {colour(f'{count}/{limit}')}")
        return "  ".join(parts) if parts else "no limits configured"

# ─────────────────────────────────────────────
#  Per-URL + global status stats
# ─────────────────────────────────────────────

class StatusStats:
    """Tracks status codes both globally and per URL."""

    def __init__(self, urls: list[str]):
        self._global: dict[int, int] = {}
        self._per_url: dict[str, dict[int, int]] = {u: {} for u in urls}
        self._lock = threading.Lock()

    def record(self, url: str, code: int) -> None:
        with self._lock:
            self._global[code] = self._global.get(code, 0) + 1
            bucket = self._per_url.setdefault(url, {})
            bucket[code] = bucket.get(code, 0) + 1

    def global_snapshot(self) -> dict[int, int]:
        with self._lock:
            return dict(sorted(self._global.items()))

    def per_url_snapshot(self) -> dict[str, dict[int, int]]:
        with self._lock:
            return {u: dict(sorted(v.items())) for u, v in self._per_url.items()}

    def total(self) -> int:
        with self._lock:
            return sum(self._global.values())

    def url_total(self, url: str) -> int:
        with self._lock:
            return sum(self._per_url.get(url, {}).values())

# ─────────────────────────────────────────────
#  URL round-robin dispatcher (thread-safe)
# ─────────────────────────────────────────────

class URLDispatcher:
    def __init__(self, urls: list[str]):
        self._urls  = urls
        self._cycle = itertools.cycle(urls)
        self._lock  = threading.Lock()

    def next(self) -> str:
        with self._lock:
            return next(self._cycle)

    @property
    def urls(self) -> list[str]:
        return list(self._urls)

# ─────────────────────────────────────────────
#  Stat file writer
# ─────────────────────────────────────────────

def write_stat_file(
    path: Path,
    counter: WindowCounter,
    stats: StatusStats,
    dispatcher: URLDispatcher,
    start_time: float,
    thread_count: int,
    status: str = "running",
) -> None:
    elapsed = time.time() - start_time
    total   = stats.total()
    per_url = stats.per_url_snapshot()

    url_stats = {}
    for url in dispatcher.urls:
        codes = per_url.get(url, {})
        tot   = sum(codes.values())
        url_stats[url] = {
            "total_requests": tot,
            "req_per_sec":    round(tot / elapsed, 3) if elapsed > 0 else 0,
            "status_codes":   codes,
        }

    payload = {
        "meta": {
            "urls":        dispatcher.urls,
            "url_count":   len(dispatcher.urls),
            "threads":     thread_count,
            "status":      status,
            "started_at":  datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
            "updated_at":  datetime.now(tz=timezone.utc).isoformat(),
            "uptime_sec":  round(elapsed, 1),
        },
        "throughput": {
            "total_requests": total,
            "req_per_sec":    round(total / elapsed, 3) if elapsed > 0 else 0,
        },
        "windows":      counter.counts_raw(),
        "status_codes": stats.global_snapshot(),
        "urls":         url_stats,
    }

    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass

# ─────────────────────────────────────────────
#  Global stop event
# ─────────────────────────────────────────────

_stop_event = threading.Event()

def _handle_sigint(*_):
    print(f"\n{YELLOW('[!] Ctrl+C received – shutting down…')}")
    _stop_event.set()

signal.signal(signal.SIGINT,  _handle_sigint)
signal.signal(signal.SIGTERM, _handle_sigint)

# ─────────────────────────────────────────────
#  Browser user-agent pool
# ─────────────────────────────────────────────

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_2) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) "
    "Gecko/20100101 Firefox/110.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13.2; rv:109.0) "
    "Gecko/20100101 Firefox/110.0",
]

# ─────────────────────────────────────────────
#  Worker thread
# ─────────────────────────────────────────────

def worker(
    thread_id: int,
    cfg: configparser.ConfigParser,
    counter: WindowCounter,
    stats: StatusStats,
    dispatcher: URLDispatcher,
    log: logging.Logger,
) -> None:
    method      = cfg.get("REQUEST", "method", fallback="GET").upper()
    body        = cfg.get("REQUEST", "body",   fallback="").strip() or None
    raw_headers = cfg.get("REQUEST", "headers", fallback="").strip()

    extra_headers: dict[str, str] = {}
    for pair in (p.strip() for p in raw_headers.split(",") if ":" in p):
        k, _, v = pair.partition(":")
        extra_headers[k.strip()] = v.strip()

    browser     = cfg.get("IMPERSONATION", "browser",   fallback="chrome110")
    rotate_ua   = cfg.getboolean("IMPERSONATION", "rotate_ua", fallback=True)
    delay       = cfg.getfloat("RATE_LIMITS", "request_delay", fallback=1.0)
    stop_on_429 = cfg.getboolean("BEHAVIOR", "stop_on_rate_limit", fallback=True)
    retry_codes = {int(c.strip()) for c in cfg.get("BEHAVIOR", "retry_codes", fallback="429,503").split(",") if c.strip()}
    retry_delay = cfg.getfloat("BEHAVIOR", "retry_delay",  fallback=5.0)
    max_retries = cfg.getint("BEHAVIOR",   "max_retries",  fallback=3)
    log_errors  = cfg.getboolean("LOGGING","log_errors_only", fallback=False)

    ua_index = thread_id % len(_UA_POOL)
    session  = cffi_requests.Session(impersonate=browser)

    log.debug(f"Thread-{thread_id} started │ browser={browser}")

    while not _stop_event.is_set():

        # ── Global rate-limit check ─────────────────────────────────
        reached, window = counter.is_limit_reached()
        if reached:
            log.warning(YELLOW(f"[LIMIT] {window} limit reached – pausing thread {thread_id}"))
            if stop_on_429:
                log.warning(YELLOW("[LIMIT] stop_on_rate_limit=true → stopping all threads"))
                _stop_event.set()
                break
            time.sleep(10)
            continue

        # ── Pick next URL round-robin ───────────────────────────────
        url = dispatcher.next()

        # ── Build headers ───────────────────────────────────────────
        headers = dict(extra_headers)
        if rotate_ua:
            headers["User-Agent"] = _UA_POOL[ua_index % len(_UA_POOL)]
            ua_index += 1

        # ── Send request (with retry) ───────────────────────────────
        attempt = 0
        while attempt <= max_retries and not _stop_event.is_set():
            try:
                t0   = time.perf_counter()
                resp = session.request(method, url, headers=headers, data=body, timeout=15)
                ms   = (time.perf_counter() - t0) * 1000

                code = resp.status_code
                stats.record(url, code)
                counter.record()

                if code == 200:
                    if not log_errors:
                        log.info(GREEN(f"[{code}]") + f" {method} {url} " + DIM(f"({ms:.0f}ms)"))

                elif code == 429:
                    retry_after = resp.headers.get("Retry-After", "?")
                    log.warning(RED(f"[429 RATE LIMITED]") + f" {url} " + YELLOW(f"Retry-After: {retry_after}s"))
                    if stop_on_429:
                        _stop_event.set()
                        return
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                        attempt += 1
                        continue

                elif code in retry_codes:
                    log.warning(YELLOW(f"[{code}]") + f" retryable – waiting {retry_delay}s")
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                        attempt += 1
                        continue
                    else:
                        log.error(RED(f"[{code}]") + " max retries exhausted")

                else:
                    log.warning(YELLOW(f"[{code}]") + f" {method} {url} " + DIM(f"({ms:.0f}ms)"))

                break

            except Exception as exc:
                log.error(RED(f"[ERR]") + f" Thread-{thread_id} {url}: {exc}")
                attempt += 1
                if attempt <= max_retries:
                    time.sleep(retry_delay)
                else:
                    break

        time.sleep(delay)

    session.close()
    log.debug(f"Thread-{thread_id} exited.")

# ─────────────────────────────────────────────
#  Stats printer
# ─────────────────────────────────────────────

def stats_printer(
    cfg: configparser.ConfigParser,
    counter: WindowCounter,
    stats: StatusStats,
    dispatcher: URLDispatcher,
    log: logging.Logger,
    start_time: float,
    stat_file: Optional[Path],
    thread_count: int,
) -> None:
    interval = cfg.getint("LOGGING", "stats_interval", fallback=10)

    if interval <= 0:
        if stat_file:
            while not _stop_event.is_set():
                write_stat_file(stat_file, counter, stats, dispatcher, start_time, thread_count)
                time.sleep(5)
        return

    while not _stop_event.is_set():
        time.sleep(interval)
        if _stop_event.is_set():
            break

        elapsed = time.time() - start_time
        total   = stats.total()
        rps     = total / elapsed if elapsed > 0 else 0

        print("\n" + BOLD("─" * 64))
        print(BOLD("  STATS  ") + DIM(f"│ uptime {elapsed:.0f}s │ total={total} │ rps={rps:.2f}"))
        print(f"  Windows  │ {counter.snapshot()}")

        # Global codes
        g = stats.global_snapshot()
        code_parts = []
        for code, cnt in g.items():
            col = GREEN if code == 200 else RED if code >= 400 else YELLOW
            code_parts.append(f"{col(str(code))}: {cnt}")
        print(f"  Codes    │ " + "  ".join(code_parts))

        # Per-URL breakdown
        per = stats.per_url_snapshot()
        for url in dispatcher.urls:
            codes = per.get(url, {})
            utot  = sum(codes.values())
            urps  = utot / elapsed if elapsed > 0 else 0
            short = url.split("//", 1)[-1][:50]
            parts = []
            for code, cnt in sorted(codes.items()):
                col = GREEN if code == 200 else RED if code >= 400 else YELLOW
                parts.append(f"{col(str(code))}:{cnt}")
            print(f"  {DIM(short):<52} {utot:>5} req  {urps:.2f}/s  " + " ".join(parts))

        if stat_file:
            write_stat_file(stat_file, counter, stats, dispatcher, start_time, thread_count)
            print(DIM(f"  → {stat_file}"))

        print(BOLD("─" * 64) + "\n")

# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def main() -> None:
    cfg          = load_config()
    log          = setup_logging(cfg)
    urls         = parse_urls(cfg)
    dispatcher   = URLDispatcher(urls)

    limits = {
        "minute": cfg.getint("RATE_LIMITS", "per_minute", fallback=0),
        "hour":   cfg.getint("RATE_LIMITS", "per_hour",   fallback=0),
        "day":    cfg.getint("RATE_LIMITS", "per_day",    fallback=0),
        "week":   cfg.getint("RATE_LIMITS", "per_week",   fallback=0),
        "month":  cfg.getint("RATE_LIMITS", "per_month",  fallback=0),
    }
    counter      = WindowCounter(limits)
    stats        = StatusStats(urls)

    thread_count = cfg.getint("THREADS",  "count",        fallback=5)
    ramp_up      = cfg.getfloat("THREADS","ramp_up",      fallback=0.5)
    run_duration = cfg.getint("BEHAVIOR", "run_duration", fallback=0)

    stat_file_str = cfg.get("LOGGING", "stat_file", fallback="bot_stats.json").strip()
    stat_file     = Path(stat_file_str) if stat_file_str else None

    print(BOLD(CYAN("\n╔══════════════════════════════════════════╗")))
    print(BOLD(CYAN("║       Rate Limit Checker Bot             ║")))
    print(BOLD(CYAN("╚══════════════════════════════════════════╝")))
    print(f"  URLs     : {len(urls)}")
    for i, u in enumerate(urls, 1):
        print(f"    {DIM(str(i)+'.')} {CYAN(u)}")
    print(f"  Threads  : {thread_count}")
    print(f"  Limits   : {counter.snapshot()}")
    print(f"  Duration : {'∞' if run_duration == 0 else f'{run_duration}s'}")
    print(f"  Browser  : {cfg.get('IMPERSONATION', 'browser', fallback='chrome110')}")
    if stat_file:
        print(f"  Stat file: {CYAN(str(stat_file))}")
    print(DIM("  Press Ctrl+C to stop\n"))

    start_time = time.time()

    sp = threading.Thread(
        target=stats_printer,
        args=(cfg, counter, stats, dispatcher, log, start_time, stat_file, thread_count),
        name="StatsPrinter",
        daemon=True,
    )
    sp.start()

    threads: list[threading.Thread] = []
    for i in range(thread_count):
        t = threading.Thread(
            target=worker,
            args=(i, cfg, counter, stats, dispatcher, log),
            name=f"Worker-{i}",
            daemon=True,
        )
        threads.append(t)
        t.start()
        log.info(f"Started Worker-{i}")
        if ramp_up > 0 and i < thread_count - 1:
            time.sleep(ramp_up)

    try:
        if run_duration > 0:
            deadline = start_time + run_duration
            while time.time() < deadline and not _stop_event.is_set():
                time.sleep(0.5)
            _stop_event.set()
        else:
            while not _stop_event.is_set():
                time.sleep(0.5)
    except KeyboardInterrupt:
        _stop_event.set()

    for t in threads:
        t.join(timeout=5)

    if stat_file:
        write_stat_file(stat_file, counter, stats, dispatcher, start_time, thread_count, status="stopped")
        print(f"\n  Stat file saved → {CYAN(str(stat_file))}")

    elapsed   = time.time() - start_time
    total     = stats.total()
    per_url   = stats.per_url_snapshot()
    code_snap = stats.global_snapshot()

    print(BOLD(CYAN("\n╔══════════════ FINAL SUMMARY ═════════════╗")))
    print(f"  Elapsed   : {elapsed:.1f}s")
    print(f"  Total Req : {total}  ({total/elapsed:.2f} req/s)")
    print(f"  Windows   : {counter.snapshot()}")
    print(f"  Global codes:")
    for code, cnt in code_snap.items():
        col = GREEN if code == 200 else RED if code >= 400 else YELLOW
        pct = cnt / total * 100 if total else 0
        print(f"    {col(str(code))}: {cnt:>6} ({pct:.1f}%)")
    print(f"  Per-URL:")
    for url in urls:
        codes = per_url.get(url, {})
        utot  = sum(codes.values())
        urps  = utot / elapsed if elapsed > 0 else 0
        short = url.split("//", 1)[-1]
        parts = [f"{code}:{cnt}" for code, cnt in sorted(codes.items())]
        print(f"    {CYAN(short)}")
        print(f"      {utot} req  {urps:.2f}/s  codes: {' '.join(parts) or 'none'}")
    print(BOLD(CYAN("╚══════════════════════════════════════════╝\n")))


if __name__ == "__main__":
    main()