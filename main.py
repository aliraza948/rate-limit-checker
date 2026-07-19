#!/usr/bin/env python3
"""
Rate Limit Checker Bot
======================
Checks minutely / hourly / daily / weekly / monthly rate limits
for a list of URLs using a switchable HTTP driver:

  • curl_cffi   – lightweight, TLS/HTTP2 fingerprinting (fastest)
  • playwright  – full Playwright browser automation (chromium/firefox/webkit)
  • chromium    – Playwright locked to Chromium only (default browser)

Driver is selected via [DRIVER] engine = curl_cffi | playwright | chromium

All logs go to  logs/
All JSON stats go to  stats/

Config : config.ini
Requires:
  pip install curl_cffi playwright
  playwright install chromium   # (or firefox / webkit if needed)
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
MAGENTA= lambda t: _c("95", t)

# ─────────────────────────────────────────────
#  Driver constants
# ─────────────────────────────────────────────
DRIVER_CURL      = "curl_cffi"
DRIVER_PLAYWRIGHT= "playwright"
DRIVER_CHROMIUM  = "chromium"
VALID_DRIVERS    = {DRIVER_CURL, DRIVER_PLAYWRIGHT, DRIVER_CHROMIUM}

# ─────────────────────────────────────────────
#  Paths
# ─────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
LOGS_DIR   = BASE_DIR / "logs"
STATS_DIR  = BASE_DIR / "stats"

LOGS_DIR.mkdir(exist_ok=True)
STATS_DIR.mkdir(exist_ok=True)

CONFIG_FILE = BASE_DIR / "config.ini"

# ─────────────────────────────────────────────
#  Config loader
# ─────────────────────────────────────────────

def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else CONFIG_FILE
    if not path.exists():
        sys.exit(f"[FATAL] config.ini not found at {path}")
    cfg.read(path)
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

def resolve_driver(cfg: configparser.ConfigParser) -> str:
    engine = cfg.get("DRIVER", "engine", fallback=DRIVER_CURL).strip().lower()
    if engine not in VALID_DRIVERS:
        sys.exit(
            f"[FATAL] [DRIVER] engine = '{engine}' is not valid.\n"
            f"        Choose one of: {', '.join(sorted(VALID_DRIVERS))}"
        )
    return engine

# ─────────────────────────────────────────────
#  Logging setup
# ─────────────────────────────────────────────

def setup_logging(cfg: configparser.ConfigParser, engine: str) -> logging.Logger:
    level_name = cfg.get("LOGGING", "log_level", fallback="INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(threadName)-14s │ %(message)s"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    # Log file always goes inside logs/
    raw_log = cfg.get("LOGGING", "log_file", fallback="rate_limit_bot.log").strip()
    if raw_log:
        log_path = LOGS_DIR / Path(raw_log).name
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers)
    log = logging.getLogger("RateLimitBot")
    log.info(f"Log file → {LOGS_DIR / Path(raw_log).name}" if raw_log else "File logging disabled")
    return log

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
                    "count":  cnt,
                    "limit":  limit,
                    "pct":    round(cnt / limit * 100, 1) if limit > 0 else None,
                    "status": (
                        "ok"       if limit == 0 or cnt < limit * 0.8 else
                        "warning"  if cnt < limit else
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
    def __init__(self, urls: list[str]):
        self._global:   dict[int, int]            = {}
        self._per_url:  dict[str, dict[int, int]] = {u: {} for u in urls}
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
#  Stat file writer  (always inside stats/)
# ─────────────────────────────────────────────

def write_stat_file(
    path: Path,
    counter: WindowCounter,
    stats: StatusStats,
    dispatcher: URLDispatcher,
    start_time: float,
    thread_count: int,
    engine: str,
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
            "urls":       dispatcher.urls,
            "url_count":  len(dispatcher.urls),
            "threads":    thread_count,
            "engine":     engine,
            "status":     status,
            "started_at": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            "uptime_sec": round(elapsed, 1),
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
#  Global stop event + signal handlers
# ─────────────────────────────────────────────

_stop_event = threading.Event()

# Shared Playwright state (populated only when engine != curl_cffi)
_browser         = None
_playwright_ctx  = None

def _handle_sigint(*_):
    print(f"\n{YELLOW('[!] Ctrl+C received – shutting down…')}")
    _stop_event.set()

signal.signal(signal.SIGINT,  _handle_sigint)
signal.signal(signal.SIGTERM, _handle_sigint)

# ─────────────────────────────────────────────
#  User-agent pool
# ─────────────────────────────────────────────

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_6) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ─────────────────────────────────────────────
#  Verification config loader
# ─────────────────────────────────────────────

def load_verification(cfg: configparser.ConfigParser) -> dict:
    """
    Parse [VERIFICATION] section.
    Returns a dict with all settings; enabled=False means skip entirely.
    """
    enabled   = cfg.getboolean("VERIFICATION", "enabled",  fallback=False)
    selector  = cfg.get("VERIFICATION", "selector",        fallback="").strip()
    contains  = cfg.get("VERIFICATION", "contains",        fallback="").strip()
    timeout_s = cfg.getfloat("VERIFICATION", "timeout",    fallback=10.0)
    log_pass  = cfg.getboolean("VERIFICATION", "log_pass", fallback=True)
    log_fail  = cfg.getboolean("VERIFICATION", "log_fail", fallback=True)
    return {
        "enabled":   enabled,
        "selector":  selector,   # CSS selector (both engines) or XPath if starts with //
        "contains":  contains,   # optional text the element must contain
        "timeout":   timeout_s,  # seconds; used as pw wait_for_selector timeout and bs4 poll
        "log_pass":  log_pass,
        "log_fail":  log_fail,
    }

# ─────────────────────────────────────────────
#  Verification helpers (per engine)
# ─────────────────────────────────────────────

def _verify_bs4(html: str, vfy: dict, url: str, log: logging.Logger) -> bool:
    """
    Parse response HTML with BeautifulSoup and check selector / text.
    Returns True if verification passes (or is disabled).
    """
    if not vfy["enabled"] or not vfy["selector"]:
        return True
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log.warning(YELLOW("[VERIFY] bs4 not installed – skipping. Run: pip install beautifulsoup4"))
        return True

    soup = BeautifulSoup(html, "html.parser")
    sel  = vfy["selector"]

    # XPath not supported by bs4 – fall back to CSS
    if sel.startswith("//"):
        log.warning(YELLOW(f"[VERIFY] XPath selectors not supported for curl engine – use CSS selector"))
        return True

    el = soup.select_one(sel)
    if el is None:
        if vfy["log_fail"]:
            log.warning(RED(f"[VERIFY FAIL] selector '{sel}' not found in response from {url}"))
        return False

    if vfy["contains"]:
        text = el.get_text(separator=" ", strip=True)
        if vfy["contains"].lower() not in text.lower():
            if vfy["log_fail"]:
                log.warning(RED(f"[VERIFY FAIL] '{vfy['contains']}' not in element text at {url}"))
            return False

    if vfy["log_pass"]:
        log.info(GREEN(f"[VERIFY OK] '{sel}' found at {url}"))
    return True


def _verify_playwright(page, vfy: dict, url: str, log: logging.Logger) -> bool:
    """
    Use Playwright's wait_for_selector to verify the element appears within timeout.
    Returns True if verification passes (or is disabled).
    """
    if not vfy["enabled"] or not vfy["selector"]:
        return True

    sel     = vfy["selector"]
    timeout = int(vfy["timeout"] * 1000)   # Playwright uses milliseconds

    try:
        el = page.wait_for_selector(sel, timeout=timeout)
        if el is None:
            raise Exception("element is None")

        if vfy["contains"]:
            text = el.inner_text()
            if vfy["contains"].lower() not in text.lower():
                if vfy["log_fail"]:
                    log.warning(RED(f"[VERIFY FAIL] '{vfy['contains']}' not in element text at {url}"))
                return False

        if vfy["log_pass"]:
            log.info(GREEN(f"[VERIFY OK] '{sel}' found at {url}"))
        return True

    except Exception as exc:
        if vfy["log_fail"]:
            log.warning(RED(f"[VERIFY FAIL] '{sel}' timeout/error at {url}: {exc}"))
        return False


# ─────────────────────────────────────────────
#  Shared request logic (engine-agnostic)
# ─────────────────────────────────────────────

def _handle_response(
    code: int,
    ms: float,
    url: str,
    method: str,
    attempt: int,
    max_retries: int,
    retry_codes: set,
    retry_delay: float,
    stop_on_429: bool,
    log_errors: bool,
    log: logging.Logger,
) -> tuple[bool, bool]:
    """
    Returns (should_break, should_stop_all).
    should_break  → exit the retry loop
    should_stop_all → set _stop_event
    """
    if code == 200:
        if not log_errors:
            log.info(GREEN(f"[{code}]") + f" {method} {url} " + DIM(f"({ms:.0f}ms)"))
        return True, False

    if code == 429:
        log.warning(RED("[429 RATE LIMITED]") + f" {url}")
        if stop_on_429:
            return True, True
        if attempt < max_retries:
            time.sleep(retry_delay)
            return False, False   # retry
        return True, False

    if code in retry_codes:
        log.warning(YELLOW(f"[{code}]") + f" retryable – waiting {retry_delay}s")
        if attempt < max_retries:
            time.sleep(retry_delay)
            return False, False   # retry
        log.error(RED(f"[{code}]") + " max retries exhausted")
        return True, False

    log.warning(YELLOW(f"[{code}]") + f" {method} {url} " + DIM(f"({ms:.0f}ms)"))
    return True, False

# ─────────────────────────────────────────────
#  Worker – curl_cffi driver
# ─────────────────────────────────────────────

def worker_curl(
    thread_id: int,
    cfg: configparser.ConfigParser,
    counter: WindowCounter,
    stats: StatusStats,
    dispatcher: URLDispatcher,
    log: logging.Logger,
) -> None:
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        log.error(RED("[FATAL] curl_cffi not installed. Run: pip install curl_cffi"))
        _stop_event.set()
        return

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
    stop_on_429 = cfg.getboolean("BEHAVIOR", "stop_on_rate_limit", fallback=False)
    retry_codes = {int(c.strip()) for c in cfg.get("BEHAVIOR", "retry_codes", fallback="429,503").split(",") if c.strip()}
    retry_delay = cfg.getfloat("BEHAVIOR", "retry_delay",  fallback=5.0)
    max_retries = cfg.getint("BEHAVIOR",   "max_retries",  fallback=3)
    log_errors  = cfg.getboolean("LOGGING","log_errors_only", fallback=False)
    vfy         = load_verification(cfg)

    ua_index = thread_id % len(_UA_POOL)
    session  = cffi_requests.Session(impersonate=browser)

    log.debug(f"curl_cffi Thread-{thread_id} started │ browser={browser} │ verify={vfy['enabled']}")

    while not _stop_event.is_set():
        reached, window = counter.is_limit_reached()
        if reached:
            log.warning(YELLOW(f"[LIMIT] {window} limit reached – pausing thread {thread_id}"))
            if stop_on_429:
                _stop_event.set()
                break
            time.sleep(10)
            continue

        url = dispatcher.next()
        headers = dict(extra_headers)
        if rotate_ua:
            headers["User-Agent"] = _UA_POOL[ua_index % len(_UA_POOL)]
            ua_index += 1

        attempt = 0
        while attempt <= max_retries and not _stop_event.is_set():
            try:
                t0   = time.perf_counter()
                resp = session.request(method, url, headers=headers, data=body, timeout=15)
                ms   = (time.perf_counter() - t0) * 1000
                code = resp.status_code

                stats.record(url, code)
                counter.record()

                # ── Selector verification (bs4) ──────────────────────
                if code == 200 and vfy["enabled"]:
                    _verify_bs4(resp.text, vfy, url, log)

                brk, stop = _handle_response(
                    code, ms, url, method, attempt, max_retries,
                    retry_codes, retry_delay, stop_on_429, log_errors, log
                )
                if stop:
                    _stop_event.set()
                    return
                if brk:
                    break
                attempt += 1

            except Exception as exc:
                log.error(RED("[ERR]") + f" Thread-{thread_id} {url}: {exc}")
                attempt += 1
                if attempt <= max_retries:
                    time.sleep(retry_delay)
                else:
                    break

        time.sleep(delay)

    session.close()
    log.debug(f"curl_cffi Thread-{thread_id} exited.")

# ─────────────────────────────────────────────
#  Worker – Playwright driver
# ─────────────────────────────────────────────

def worker_playwright(
    thread_id: int,
    cfg: configparser.ConfigParser,
    counter: WindowCounter,
    stats: StatusStats,
    dispatcher: URLDispatcher,
    log: logging.Logger,
) -> None:
    """
    Each worker thread owns its own Playwright instance + browser + context.
    Playwright's sync_api is NOT thread-safe, so sharing a single _browser
    across threads causes 'Connection closed while reading from the driver'.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error(RED("[FATAL] playwright not installed."))
        _stop_event.set()
        return

    method      = cfg.get("REQUEST", "method", fallback="GET").upper()
    body        = cfg.get("REQUEST", "body",   fallback="").strip() or None
    raw_headers = cfg.get("REQUEST", "headers", fallback="").strip()

    extra_headers: dict[str, str] = {}
    for pair in (p.strip() for p in raw_headers.split(",") if ":" in p):
        k, _, v = pair.partition(":")
        extra_headers[k.strip()] = v.strip()

    rotate_ua   = cfg.getboolean("IMPERSONATION", "rotate_ua", fallback=True)
    delay       = cfg.getfloat("RATE_LIMITS", "request_delay", fallback=1.0)
    stop_on_429 = cfg.getboolean("BEHAVIOR", "stop_on_rate_limit", fallback=False)
    retry_codes = {int(c.strip()) for c in cfg.get("BEHAVIOR", "retry_codes", fallback="429,503").split(",") if c.strip()}
    retry_delay = cfg.getfloat("BEHAVIOR", "retry_delay",  fallback=5.0)
    max_retries = cfg.getint("BEHAVIOR",   "max_retries",  fallback=3)
    log_errors  = cfg.getboolean("LOGGING","log_errors_only", fallback=False)
    headless    = cfg.getboolean("IMPERSONATION", "headless", fallback=True)
    engine      = cfg.get("DRIVER", "engine", fallback=DRIVER_CHROMIUM).strip().lower()
    pw_browser  = cfg.get("IMPERSONATION", "pw_browser", fallback="chromium").strip().lower()
    vfy         = load_verification(cfg)

    ua = _UA_POOL[thread_id % len(_UA_POOL)] if rotate_ua else _UA_POOL[0]

    log.debug(f"playwright Thread-{thread_id} started │ ua={ua[:50]}… │ verify={vfy['enabled']}")

    # Each thread owns its own playwright + browser + context
    pw_ctx  = sync_playwright().start()
    launcher = getattr(pw_ctx, pw_browser if engine == DRIVER_PLAYWRIGHT else "chromium")
    browser = launcher.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = browser.new_context(
        user_agent=ua,
        extra_http_headers=extra_headers,
        viewport={"width": 1280, "height": 800},
        java_script_enabled=True,
    )

    try:
        while not _stop_event.is_set():
            reached, window = counter.is_limit_reached()
            if reached:
                log.warning(YELLOW(f"[LIMIT] {window} limit reached – pausing thread {thread_id}"))
                if stop_on_429:
                    _stop_event.set()
                    break
                time.sleep(10)
                continue

            url = dispatcher.next()

            attempt = 0
            while attempt <= max_retries and not _stop_event.is_set():
                try:
                    t0 = time.perf_counter()

                    if method in ("GET", "HEAD"):
                        page = context.new_page()
                        try:
                            response = page.goto(url, timeout=15_000, wait_until="domcontentloaded")
                            code = response.status if response else 0
                            # ── Selector verification (Playwright wait_for_selector) ──
                            if code == 200 and vfy["enabled"]:
                                _verify_playwright(page, vfy, url, log)
                        finally:
                            page.close()
                    else:
                        api_resp = context.request.fetch(url, method=method, data=body, timeout=15_000)
                        code = api_resp.status

                    ms = (time.perf_counter() - t0) * 1000

                    stats.record(url, code)
                    counter.record()

                    brk, stop = _handle_response(
                        code, ms, url, method, attempt, max_retries,
                        retry_codes, retry_delay, stop_on_429, log_errors, log
                    )
                    if stop:
                        _stop_event.set()
                        return
                    if brk:
                        break
                    attempt += 1

                except Exception as exc:
                    log.error(RED("[ERR]") + f" Thread-{thread_id} {url}: {exc}")
                    attempt += 1
                    if attempt <= max_retries:
                        time.sleep(retry_delay)
                    else:
                        break

            time.sleep(delay)

    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw_ctx.stop()
        except Exception:
            pass
        log.debug(f"playwright Thread-{thread_id} exited.")

# ─────────────────────────────────────────────
#  Driver initialisation
# ─────────────────────────────────────────────

def init_playwright_browser(cfg: configparser.ConfigParser, engine: str, log: logging.Logger):
    """
    No-op: each worker_playwright thread now owns its own Playwright instance,
    browser, and context. This avoids the 'Connection closed while reading from
    the driver' crash that occurs when the sync_api browser is shared across threads.
    """
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401 – verify install
    except ImportError:
        sys.exit(
            "[FATAL] playwright not installed.\n"
            "  Run: pip install playwright && playwright install chromium"
        )
    pw_browser = cfg.get("IMPERSONATION", "pw_browser", fallback="chromium").strip().lower()
    headless   = cfg.getboolean("IMPERSONATION", "headless", fallback=True)
    log.info(f"Playwright engine ready – each worker will launch its own {pw_browser} (headless={headless})")

def shutdown_playwright(log: logging.Logger):
    global _browser, _playwright_ctx
    try:
        if _browser:
            _browser.close()
        if _playwright_ctx:
            _playwright_ctx.stop()
    except Exception as e:
        log.debug(f"Playwright shutdown warning: {e}")

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
    engine: str,
) -> None:
    interval = cfg.getint("LOGGING", "stats_interval", fallback=10)

    if interval <= 0:
        if stat_file:
            while not _stop_event.is_set():
                write_stat_file(stat_file, counter, stats, dispatcher, start_time, thread_count, engine)
                time.sleep(5)
        return

    while not _stop_event.is_set():
        time.sleep(interval)
        if _stop_event.is_set():
            break

        elapsed = time.time() - start_time
        total   = stats.total()
        rps     = total / elapsed if elapsed > 0 else 0

        print("\n" + BOLD("─" * 70))
        print(BOLD("  STATS  ") + DIM(f"│ uptime {elapsed:.0f}s │ total={total} │ rps={rps:.2f} │ engine={engine}"))
        print(f"  Windows  │ {counter.snapshot()}")

        g = stats.global_snapshot()
        code_parts = []
        for code, cnt in g.items():
            col = GREEN if code == 200 else RED if code >= 400 else YELLOW
            code_parts.append(f"{col(str(code))}: {cnt}")
        print(f"  Codes    │ " + "  ".join(code_parts))

        per = stats.per_url_snapshot()
        for url in dispatcher.urls:
            codes = per.get(url, {})
            utot  = sum(codes.values())
            urps  = utot / elapsed if elapsed > 0 else 0
            short = url.split("//", 1)[-1][:55]
            parts = []
            for code, cnt in sorted(codes.items()):
                col = GREEN if code == 200 else RED if code >= 400 else YELLOW
                parts.append(f"{col(str(code))}:{cnt}")
            print(f"  {DIM(short):<57} {utot:>5} req  {urps:.2f}/s  " + " ".join(parts))

        if stat_file:
            write_stat_file(stat_file, counter, stats, dispatcher, start_time, thread_count, engine)
            print(DIM(f"  → {stat_file}"))

        print(BOLD("─" * 70) + "\n")

# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def main() -> None:
    cfg        = load_config()
    engine     = resolve_driver(cfg)
    log        = setup_logging(cfg, engine)
    urls       = parse_urls(cfg)
    dispatcher = URLDispatcher(urls)

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

    # Stats file always inside stats/
    raw_stat = cfg.get("LOGGING", "stat_file", fallback="bot_stats.json").strip()
    stat_file = STATS_DIR / Path(raw_stat).name if raw_stat else None

    # ── Initialise browser if needed ───────────────────────────────
    if engine in (DRIVER_PLAYWRIGHT, DRIVER_CHROMIUM):
        init_playwright_browser(cfg, engine, log)
        worker_fn = worker_playwright
    else:
        worker_fn = worker_curl

    # ── Startup banner ─────────────────────────────────────────────
    engine_label = {
        DRIVER_CURL:       CYAN("curl_cffi") + DIM(f"  ({cfg.get('IMPERSONATION','browser',fallback='chrome110')})"),
        DRIVER_PLAYWRIGHT: MAGENTA("Playwright") + DIM(f"  ({cfg.get('IMPERSONATION','pw_browser',fallback='chromium')})"),
        DRIVER_CHROMIUM:   MAGENTA("Playwright/Chromium"),
    }[engine]

    print(BOLD(CYAN("\n╔══════════════════════════════════════════════╗")))
    print(BOLD(CYAN("║        Rate Limit Checker Bot  v2            ║")))
    print(BOLD(CYAN("╚══════════════════════════════════════════════╝")))
    print(f"  Engine    : {engine_label}")
    print(f"  URLs      : {len(urls)}")
    for i, u in enumerate(urls, 1):
        print(f"    {DIM(str(i)+'.')} {CYAN(u)}")
    print(f"  Threads   : {thread_count}")
    print(f"  Limits    : {counter.snapshot()}")
    print(f"  Duration  : {'∞' if run_duration == 0 else f'{run_duration}s'}")
    print(f"  Logs dir  : {CYAN(str(LOGS_DIR))}")
    if stat_file:
        print(f"  Stats dir : {CYAN(str(STATS_DIR))}")
        print(f"  Stat file : {CYAN(stat_file.name)}")
    print(DIM("  Press Ctrl+C to stop\n"))

    start_time = time.time()

    sp = threading.Thread(
        target=stats_printer,
        args=(cfg, counter, stats, dispatcher, log, start_time, stat_file, thread_count, engine),
        name="StatsPrinter",
        daemon=True,
    )
    sp.start()

    threads: list[threading.Thread] = []
    for i in range(thread_count):
        t = threading.Thread(
            target=worker_fn,
            args=(i, cfg, counter, stats, dispatcher, log),
            name=f"Worker-{i:02d}",
            daemon=True,
        )
        threads.append(t)
        t.start()
        log.info(f"Started Worker-{i:02d}  (engine={engine})")
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
        t.join(timeout=10)

    # Workers clean up their own browser instances in their finally blocks.

    if stat_file:
        write_stat_file(stat_file, counter, stats, dispatcher, start_time, thread_count, engine, status="stopped")
        print(f"\n  Stat file saved → {CYAN(str(stat_file))}")

    elapsed   = time.time() - start_time
    total     = stats.total()
    per_url   = stats.per_url_snapshot()
    code_snap = stats.global_snapshot()

    print(BOLD(CYAN("\n╔══════════════════ FINAL SUMMARY ══════════════════╗")))
    print(f"  Engine    : {engine}")
    print(f"  Elapsed   : {elapsed:.1f}s")
    print(f"  Total Req : {total}  ({total/elapsed:.2f} req/s)" if elapsed > 0 else f"  Total Req : {total}")
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
    print(BOLD(CYAN("╚════════════════════════════════════════════════════╝\n")))


if __name__ == "__main__":
    main()