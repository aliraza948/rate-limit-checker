```
██████╗  █████╗ ████████╗███████╗    ██╗     ██╗███╗   ███╗██╗████████╗
██╔══██╗██╔══██╗╚══██╔══╝██╔════╝    ██║     ██║████╗ ████║██║╚══██╔══╝
██████╔╝███████║   ██║   █████╗      ██║     ██║██╔████╔██║██║   ██║
██╔══██╗██╔══██║   ██║   ██╔══╝      ██║     ██║██║╚██╔╝██║██║   ██║
██║  ██║██║  ██║   ██║   ███████╗    ███████╗██║██║ ╚═╝ ██║██║   ██║
╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝    ╚══════╝╚═╝╚═╝     ╚═╝╚═╝   ╚═╝

 ██████╗██╗  ██╗███████╗ ██████╗██╗  ██╗███████╗██████╗     ██████╗  ██████╗ ████████╗
██╔════╝██║  ██║██╔════╝██╔════╝██║ ██╔╝██╔════╝██╔══██╗    ██╔══██╗██╔═══██╗╚══██╔══╝
██║     ███████║█████╗  ██║     █████╔╝ █████╗  ██████╔╝    ██████╔╝██║   ██║   ██║
██║     ██╔══██║██╔══╝  ██║     ██╔═██╗ ██╔══╝  ██╔══██╗    ██╔══██╗██║   ██║   ██║
╚██████╗██║  ██║███████╗╚██████╗██║  ██╗███████╗██║  ██║    ██████╔╝╚██████╔╝   ██║
 ╚═════╝╚═╝  ╚═╝╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝    ╚═════╝  ╚═════╝    ╚═╝
```

<div align="center">

**A multithreaded HTTP rate-limit prober with switchable engines**
`curl_cffi` · `Playwright/Chromium` · `Playwright (any browser)`

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)](https://python.org)
[![Engine](https://img.shields.io/badge/Engines-curl__cffi%20%7C%20Playwright-blueviolet)](#engines)
[![License](https://img.shields.io/badge/License-MIT-green)](#)

</div>

---

## ✨ What It Does

Rate Limit Checker Bot fires concurrent HTTP requests at one or more URLs, tracks responses across **five rolling time windows** (minute / hour / day / week / month), and writes a live JSON stats snapshot — all without touching a single extra dependency beyond your chosen HTTP engine.

```
┌──────────────────────────────────────────────────────────────┐
│                      rate_limit_bot.py                       │
│                                                              │
│   ┌──────────┐   ┌────────────┐   ┌──────────────────────┐  │
│   │  config  │──▶│  engine    │──▶│   Worker threads     │  │
│   │  .ini    │   │  selector  │   │   (round-robin)      │  │
│   └──────────┘   └────────────┘   └──────────┬───────────┘  │
│                        │                      │              │
│              ┌─────────┴──────────┐           ▼              │
│              │  curl_cffi  │  Playwright      │              │
│              │  (fast/TLS) │  (real browser)  │              │
│              └──────────────────────┘         │              │
│                                               ▼              │
│                              ┌─────────────────────────┐     │
│                              │  [VERIFICATION]         │     │
│                              │  CSS selector + timeout │     │
│                              │  curl → bs4             │     │
│                              │  browser → wait_for_sel │     │
│                              └────────────┬────────────┘     │
│                                           ▼                  │
│                              ┌─────────────────────────┐     │
│                              │  WindowCounter          │     │
│                              │  MIN/HR/DAY/WK/MO       │     │
│                              └────────────┬────────────┘     │
│                                           ▼                  │
│                              ┌─────────────────────────┐     │
│                              │  logs/  &  stats/       │     │
│                              └─────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
```

---

## 🚀 Feature Highlights

| Feature | Detail |
|---------|--------|
| 🔄 **Switchable engine** | `curl_cffi`, `chromium`, or `playwright` — one config line |
| 🌐 **Multi-URL** | Round-robin across unlimited URLs |
| 🧵 **Concurrent threads** | Configurable count with staggered ramp-up |
| 📊 **5 rate windows** | Per-minute, per-hour, per-day, per-week, per-month |
| 🎭 **Browser fingerprinting** | TLS/HTTP2 impersonation via curl_cffi |
| 🖥️ **Real browser** | Full JS execution with Playwright (Chromium/Firefox/WebKit) |
| 🔁 **Auto-retry** | Configurable retry on 429 / 503 (any codes) |
| ✅ **Response verification** | CSS selector check after every 200 — works on all engines |
| 📁 **Organised output** | Logs → `logs/`  ·  JSON stats → `stats/` |
| 📈 **Live JSON stats** | Machine-readable, updated every N seconds |
| 🛑 **Graceful shutdown** | Ctrl+C flushes stats and marks `"status": "stopped"` |

---

## 📋 Requirements

- **Python 3.8+**
- At least **one** of the engines below:

```bash
# Engine 1 – curl_cffi (lightweight, fastest)
pip install curl_cffi

# Engine 2 & 3 – Playwright (real browser)
pip install playwright
playwright install chromium    # for chromium / playwright engines
playwright install firefox     # optional – for engine=playwright + pw_browser=firefox
playwright install webkit      # optional – for engine=playwright + pw_browser=webkit
```

- **Optional** — only needed if `[VERIFICATION] enabled = true` with `curl_cffi`:

```bash
pip install beautifulsoup4
```

---

## ⚙️ Installation

```bash
git clone https://github.com/aliraza948/rate-limit-checker.git
cd rate-limit-checker

# Install the engine(s) you want
pip install curl_cffi playwright beautifulsoup4
playwright install chromium

# Copy and edit the config
cp config.example.ini config.ini
```

---

## 🔧 Configuration

All settings live in `config.ini` (default) or any `.ini` file you pass as the first argument.

```bash
python main.py              # uses config.ini
python main.py prod.ini     # uses prod.ini
```

---

### `[DRIVER]` — Engine Selection

```ini
[DRIVER]
engine = curl_cffi   # curl_cffi | chromium | playwright
```

| Value | Description | Speed | JS support |
|-------|-------------|-------|------------|
| `curl_cffi` | TLS/HTTP2 fingerprinting, no real browser | ⚡⚡⚡ Fast | ❌ |
| `chromium` | Playwright locked to Chromium | ⚡ Moderate | ✅ Full |
| `playwright` | Playwright with `pw_browser` of your choice | ⚡ Moderate | ✅ Full |

---

### `[URLS]`

```ini
[URLS]
urls =
    https://example.com/api/endpoint-1
    https://example.com/api/endpoint-2
    # comment lines are ignored
```

All threads share this list and cycle through it **round-robin**. Per-URL stats are always tracked independently.

---

### `[REQUEST]`

```ini
[REQUEST]
method  = GET           # GET | POST | HEAD
body    =               # Raw JSON body for POST (leave blank for GET/HEAD)
headers =               # Comma-separated Key:Value pairs
                        # e.g. Authorization:Bearer abc123, X-Custom:value
```

---

### `[RATE_LIMITS]`

```ini
[RATE_LIMITS]
per_minute    = 60        # 0 = unlimited
per_hour      = 1000
per_day       = 10000
per_week      = 50000
per_month     = 150000
request_delay = 1.0       # seconds between requests per thread
```

All window counters are enforced **across all URLs combined**.

---

### `[THREADS]`

```ini
[THREADS]
count   = 10     # concurrent workers
                 # curl_cffi: up to 25–50 is fine
                 # Playwright: keep at 5–10 (browsers are heavy)
ramp_up = 0.5   # seconds between starting each thread
```

---

### `[BEHAVIOR]`

```ini
[BEHAVIOR]
run_duration       = 0        # seconds (0 = run forever)
stop_on_rate_limit = false    # halt all threads on first 429
retry_codes        = 429, 503
retry_delay        = 5.0
max_retries        = 3
```

---

### `[IMPERSONATION]`

```ini
[IMPERSONATION]
# curl_cffi fingerprint (ignored when engine = playwright/chromium)
browser    = chrome110

# Playwright browser (only used when engine = playwright)
# Options: chromium | firefox | webkit
pw_browser = chromium

# Hide the browser window (set false to debug visually)
headless   = true

# Rotate User-Agent strings across threads
rotate_ua  = true
```

**curl_cffi browser profiles:**

| Chrome | Safari | Firefox |
|--------|--------|---------|
| `chrome110` | `safari15_3` | `firefox102` |
| `chrome107` | `safari15_5` | `firefox104` |
| `chrome104` | `safari17_0` | |
| `chrome101` | | |
| `chrome100` | | |
| `chrome99`  | | |

---

### `[VERIFICATION]` ⭐ new

Verify the response actually contains the expected content after every successful (HTTP 200) request. Works across **all three engines** — no code changes needed when you switch engines.

```ini
[VERIFICATION]

# Master on/off switch — set false to skip entirely without removing the section
enabled  = true

# CSS selector to look for in the response page.
# Both engines support standard CSS selectors:
#   div.my-class            element with class
#   #main-content           element by ID
#   h1                      tag name
#   .rate-limit-remaining   class selector
#   [data-testid=status]    attribute selector
#
# curl_cffi engine : XPath (//...) is NOT supported — use CSS only.
# playwright / chromium : XPath IS supported (e.g. //h1[@class='title']).
selector = div.content

# (Optional) Text the matched element must contain — case-insensitive substring.
# Leave blank to only verify the element is present.
contains =

# Timeout in seconds.
#   curl_cffi / bs4  : not used for waiting (HTML is already downloaded).
#   playwright       : the driver waits up to this long for the selector to
#                      appear in the DOM — essential for JS-rendered pages.
timeout  = 10

# Control log verbosity
log_pass = true    # log a line on every PASS
log_fail = true    # log a line on every FAIL
```

#### How it works under each engine

| Engine | Library | Selector support | Timeout behaviour |
|--------|---------|-----------------|-------------------|
| `curl_cffi` | BeautifulSoup 4 (`pip install beautifulsoup4`) | CSS only | N/A — HTML already downloaded |
| `chromium` | Playwright `wait_for_selector` | CSS + XPath | Waits up to `timeout` seconds in live DOM |
| `playwright` | Playwright `wait_for_selector` | CSS + XPath | Waits up to `timeout` seconds in live DOM |

#### Verification flow

```
Request sent
     │
     ▼
HTTP 200?  ──── NO ──▶  skip verification (retry/error path as normal)
     │
    YES
     │
     ▼
enabled = true AND selector set?  ──── NO ──▶  pass through silently
     │
    YES
     │
     ├─ curl_cffi ──▶ bs4.select_one(selector)
     │                     │
     └─ browser   ──▶ page.wait_for_selector(selector, timeout=N*1000ms)
                           │
                    element found?
                     ├── NO  ──▶ [VERIFY FAIL] logged
                     └── YES ──▶ contains check (if set)
                                      ├── NO  ──▶ [VERIFY FAIL] logged
                                      └── YES ──▶ [VERIFY OK]  logged
```

> **Note:** A verification failure is **informational only** — it does not count as a request error or trigger a retry. The request has already been recorded against your rate-limit windows.

#### Log output examples

```
2026-07-19 09:12:03 [INFO]  Worker-00  │ [VERIFY OK]  'div.content' found at https://example.com/
2026-07-19 09:12:05 [WARN]  Worker-01  │ [VERIFY FAIL] selector 'div.content' not found in response from https://example.com/
2026-07-19 09:12:07 [WARN]  Worker-02  │ [VERIFY FAIL] 'Welcome' not in element text at https://example.com/
```

#### Common selector examples

```ini
# Confirm the main app shell loaded (not a login wall or error page)
selector = main#app
contains =

# Verify a specific heading is present on a JS-rendered page (browser engines)
selector  = h1.page-title
contains  = Welcome

# Check a rate-limit badge element is present
selector = span[data-testid="rate-limit-remaining"]
contains =

# XPath — browser engines only
selector = //div[@class='product-card']
contains = Add to Cart

# Completely disabled
enabled = false
```

---

### `[LOGGING]`

```ini
[LOGGING]
log_file        = rate_limit_bot.log   # written to logs/ folder
stat_file       = bot_stats.json       # written to stats/ folder
log_level       = INFO                 # DEBUG | INFO | WARNING | ERROR
stats_interval  = 10                   # live summary every N seconds
log_errors_only = false                # true = only log non-200 responses
```

> **Note:** You don't need to include the folder path. The bot always writes logs to `logs/` and stats to `stats/` automatically.

---

## 📁 Output Folder Structure

```
rate-limit-checker/
├── main.py
├── config.ini
├── logs/
│   └── rate_limit_bot.log      ← all log output
└── stats/
    └── bot_stats.json          ← live JSON stats snapshot
```

---

## ▶️ Running the Bot

```bash
# Default config
python main.py

# Custom config file
python main.py my_config.ini
```

**Engine quick-switch examples:**

```bash
# Switch engine on the fly by editing config.ini
engine = curl_cffi    # lightweight + fast
engine = chromium     # real Chromium, full JS
engine = playwright   # Playwright with pw_browser choice
```

---

## 💻 Terminal Output

```
╔══════════════════════════════════════════════╗
║        Rate Limit Checker Bot  v2            ║
╚══════════════════════════════════════════════╝
  Engine    : curl_cffi  (chrome110)
  URLs      : 1
    1. https://www.goat.com/sneakers/...
  Threads   : 10
  Limits    : MIN: 0/60  HOU: 0/1000  DAY: 0/10000
  Duration  : ∞
  Logs dir  : /path/to/logs
  Stats dir : /path/to/stats
  Stat file : bot_stats.json
  Press Ctrl+C to stop

2026-07-19 09:12:01 [INFO] Worker-00  │ [200] GET https://... (843ms)
2026-07-19 09:12:01 [INFO] Worker-00  │ [VERIFY OK] 'div.content' found at https://...
2026-07-19 09:12:02 [INFO] Worker-01  │ [200] GET https://... (911ms)
2026-07-19 09:12:02 [WARN] Worker-01  │ [VERIFY FAIL] selector 'div.content' not found in response

──────────────────────────────────────────────────────────────────────
  STATS   │ uptime 10s │ total=18 │ rps=1.80 │ engine=curl_cffi
  Windows  │ MIN: 18/60  HOU: 18/1000
  Codes    │ 200: 18
  goat.com/sneakers/...                             18 req  1.80/s  200:18
──────────────────────────────────────────────────────────────────────
```

---

## 📊 JSON Stats File

Written to `stats/bot_stats.json`, updated every `stats_interval` seconds and once more on shutdown. Safe to read at any time (written atomically).

### Schema

```
stats/bot_stats.json
├── meta/
│   ├── urls[]          List of target URLs
│   ├── url_count       Number of URLs
│   ├── threads         Configured thread count
│   ├── engine          Active engine (curl_cffi | chromium | playwright)
│   ├── status          "running" | "stopped"
│   ├── started_at      ISO-8601 start timestamp
│   ├── updated_at      ISO-8601 last flush timestamp
│   └── uptime_sec      Elapsed seconds
├── throughput/
│   ├── total_requests
│   └── req_per_sec
├── windows/
│   ├── minute/  { count, limit, pct, status }
│   ├── hour/    { count, limit, pct, status }
│   ├── day/     { count, limit, pct, status }
│   ├── week/    { count, limit, pct, status }
│   └── month/   { count, limit, pct, status }
├── status_codes/
│   └── <code>   count
└── urls/
    └── <url>/
        ├── total_requests
        ├── req_per_sec
        └── status_codes/ { <code>: count }
```

### Example Output

```json
{
  "meta": {
    "urls": ["https://www.goat.com/sneakers/air-jordan-7-retro-miro-2026-iq6573-100"],
    "url_count": 1,
    "threads": 10,
    "engine": "curl_cffi",
    "status": "stopped",
    "started_at": "2026-07-13T16:49:06.587593+00:00",
    "updated_at": "2026-07-13T16:49:18.605074+00:00",
    "uptime_sec": 12.0
  },
  "throughput": {
    "total_requests": 18,
    "req_per_sec": 1.500
  },
  "windows": {
    "minute": { "count": 18, "limit": 60,   "pct": 30.0, "status": "ok" },
    "hour":   { "count": 18, "limit": 1000, "pct": 1.8,  "status": "ok" }
  },
  "status_codes": { "200": 18 },
  "urls": {
    "https://www.goat.com/...": {
      "total_requests": 18,
      "req_per_sec": 1.500,
      "status_codes": { "200": 18 }
    }
  }
}
```

### Useful `jq` one-liners

```bash
# Live minute window usage
watch -n 2 "jq '.windows.minute | \"\(.count)/\(.limit) (\(.pct)%)\"' stats/bot_stats.json"

# Requests per second
jq '.throughput.req_per_sec' stats/bot_stats.json

# All status codes
jq '.status_codes' stats/bot_stats.json

# Active engine
jq -r '.meta.engine' stats/bot_stats.json

# CSV: timestamp, total, minute count
jq -r '[.meta.updated_at, .throughput.total_requests, .windows.minute.count] | @csv' \
  stats/bot_stats.json
```

---

## 🛑 Stopping the Bot

Press **Ctrl+C** at any time. The bot will:

1. Signal all worker threads to stop
2. Wait for in-flight requests to complete (up to 10 s)
3. Shut down each Playwright browser instance
4. Write a final `stats/bot_stats.json` with `"status": "stopped"`
5. Print a full final summary to the terminal

---

## 🧠 Engine Decision Guide

```
Do you need JS to render the page / bypass JS-based bot protection?
 ├── YES → use  chromium  or  playwright
 │           chromium   = simple, locked to Chromium
 │           playwright = flexible, pick firefox/webkit too
 └── NO  → use  curl_cffi
                Fastest option. TLS fingerprinting fools most CDN checks.
                Supports Chrome, Safari, Firefox profiles.

Do you want to verify page content after each request?
 ├── curl_cffi  → CSS selectors via BeautifulSoup 4  (pip install beautifulsoup4)
 │                No DOM wait — HTML is already downloaded.
 └── browser    → CSS or XPath via Playwright wait_for_selector
                  Waits up to `timeout` seconds for JS-rendered elements.
```

---

## 💡 Tips & Tricks

**Find the exact rate-limit threshold**
Set all window limits to `0` (unlimited) and watch the terminal for the first 429. Note `windows.minute.count` in the JSON at that moment.

**Stop on first 429 automatically**
```ini
stop_on_rate_limit = true
retry_codes =
```

**Verify a page element to confirm you're not being rate-limited silently**
Some APIs return HTTP 200 but serve a CAPTCHA or error page instead of real content. Use `[VERIFICATION]` to catch this:
```ini
[VERIFICATION]
enabled  = true
selector = div.product-detail
contains =
timeout  = 5
log_fail = true
```

**Avoid detection during long runs**
```ini
engine        = curl_cffi
browser       = chrome110
rotate_ua     = true
request_delay = 2.0
```

**Debug Playwright visually**
```ini
engine   = chromium
headless = false
count    = 1
```

**Silence verify logs on clean runs**
```ini
[VERIFICATION]
enabled  = true
selector = main#app
log_pass = false   # only log failures, skip the [VERIFY OK] noise
log_fail = true
```

**Monitor from a second terminal**
```bash
watch -n 2 "jq '.windows, .throughput' stats/bot_stats.json"
```

**Multiple targets**
```ini
[URLS]
urls =
    https://example.com/api/product-1
    https://example.com/api/product-2
    https://example.com/api/product-3
```
The bot round-robins across them and reports per-URL stats in the JSON.

---

## 🗂️ Project Layout

```
rate-limit-checker/
├── rate_limit_bot.py        ← main script
├── config.ini               ← your local config (git-ignored)
├── config.example.ini       ← template to copy from
├── README.md
├── logs/
│   └── rate_limit_bot.log   ← created automatically
└── stats/
    └── bot_stats.json       ← created automatically
```

---

<div align="center">
Made with ☕ — contributions welcome
</div>