# Rate Limit Checker Bot

A multithreaded Python tool for probing HTTP rate limits on one or more URLs. It fires concurrent requests, tracks responses across five rolling time windows (minute / hour / day / week / month), impersonates real browsers via `curl_cffi`, and writes a live JSON stats file so you can monitor progress without reading the terminal.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
  - [\[URLS\]](#urls)
  - [\[REQUEST\]](#request)
  - [\[RATE\_LIMITS\]](#rate_limits)
  - [\[THREADS\]](#threads)
  - [\[BEHAVIOR\]](#behavior)
  - [\[IMPERSONATION\]](#impersonation)
  - [\[LOGGING\]](#logging)
- [Running the Bot](#running-the-bot)
- [Terminal Output](#terminal-output)
- [JSON Stats File](#json-stats-file)
  - [Schema Reference](#schema-reference)
  - [Example Output](#example-output)
- [Stopping the Bot](#stopping-the-bot)
- [Tips & Tricks](#tips--tricks)

---

## Features

| Feature | Detail |
|---|---|
| Multi-URL support | Round-robin distribution across all configured URLs |
| Concurrent threads | Configurable worker count with a staggered ramp-up |
| Five rate-limit windows | Per-minute, per-hour, per-day, per-week, per-month |
| Browser impersonation | `curl_cffi` fingerprints (Chrome, Safari, Firefox) |
| User-agent rotation | Different UA per thread to reduce fingerprinting |
| Auto-retry | Configurable retry on 429 / 503 (or any chosen codes) |
| Live JSON stats | Machine-readable snapshot updated every N seconds |
| Graceful shutdown | Ctrl+C flushes stats and marks status as `stopped` |

---

## Requirements

- Python 3.8+
- [`curl_cffi`](https://github.com/yifeikong/curl_cffi) — browser-impersonating HTTP client
- Standard library only for everything else (`threading`, `configparser`, `json`, `logging`, …)

Install the one non-stdlib dependency:

```bash
pip install curl_cffi
```

---

## Installation

```bash
git clone https://github.com/aliraza948/rate-limit-checker.git
cd rate-limit-checker
pip install curl_cffi
```

Copy the sample config and edit it:

```bash
cp config.example.ini config.ini
```

---

## Configuration

All settings live in a single `.ini` file (default: `config.ini`).  
Pass a different path as the first CLI argument: `python rate_limit_bot.py my_config.ini`.

---

### [URLS]

```ini
[URLS]
urls =
    https://example.com/api/product-1
    https://example.com/api/product-2
```

| Key | Description |
|---|---|
| `urls` | One URL per line. Blank lines and `#` comments are ignored. All threads share the list and cycle through it round-robin. |

---

### [REQUEST]

```ini
[REQUEST]
method  = GET
body    =
headers =
```

| Key | Type | Description |
|---|---|---|
| `method` | string | HTTP verb for every URL: `GET`, `POST`, or `HEAD`. |
| `body` | string | Request body for POST requests (raw JSON string). Leave empty for GET/HEAD. |
| `headers` | string | Extra headers as comma-separated `Key:Value` pairs. Example: `Authorization:Bearer abc123, X-Custom:value` |

---

### [RATE_LIMITS]

```ini
[RATE_LIMITS]
per_minute    = 60
per_hour      = 1000
per_day       = 10000
per_week      = 50000
per_month     = 150000
request_delay = 1.0
```

| Key | Type | Description |
|---|---|---|
| `per_minute` | int | Max requests in any 60-second window (0 = unlimited). |
| `per_hour` | int | Max requests in any 60-minute window. |
| `per_day` | int | Max requests in any 24-hour window. |
| `per_week` | int | Max requests in any 7-day window. |
| `per_month` | int | Max requests in any 30-day window. |
| `request_delay` | float | Pause in seconds between successive requests **within a single thread**. Use this to throttle individual thread cadence independent of the window limits. |

All window limits are enforced across **all URLs combined**.

---

### [THREADS]

```ini
[THREADS]
count   = 25
ramp_up = 0.5
```

| Key | Type | Description |
|---|---|---|
| `count` | int | Number of concurrent worker threads. |
| `ramp_up` | float | Seconds to wait between spawning each thread. A value of `0.5` with 25 threads means all workers are running after ~12 s, avoiding a burst on startup. |

---

### [BEHAVIOR]

```ini
[BEHAVIOR]
run_duration       = 0
stop_on_rate_limit = false
retry_codes        = 429, 503
retry_delay        = 5.0
max_retries        = 3
```

| Key | Type | Description |
|---|---|---|
| `run_duration` | int | How long to run in seconds. `0` means run indefinitely until Ctrl+C. |
| `stop_on_rate_limit` | bool | If `true`, all threads halt the moment any 429 response is received. |
| `retry_codes` | list | Comma-separated HTTP status codes that trigger a retry (e.g. `429, 503`). |
| `retry_delay` | float | Seconds to wait before each retry attempt. |
| `max_retries` | int | Maximum retry attempts per request before giving up and logging an error. |

---

### [IMPERSONATION]

```ini
[IMPERSONATION]
browser   = chrome110
rotate_ua = true
```

| Key | Type | Description |
|---|---|---|
| `browser` | string | `curl_cffi` browser profile to use for TLS and HTTP/2 fingerprinting. See supported values below. |
| `rotate_ua` | bool | When `true`, each thread gets a different User-Agent string to reduce detection. |

**Supported `browser` values:**

| Chrome | Safari | Firefox |
|---|---|---|
| `chrome110` | `safari15_3` | `firefox102` |
| `chrome107` | `safari15_5` | `firefox104` |
| `chrome104` | `safari17_0` | |
| `chrome101` | | |
| `chrome100` | | |
| `chrome99` | | |

---

### [LOGGING]

```ini
[LOGGING]
log_file        = rate_limit_bot.log
stat_file       = bot_stats.json
log_level       = INFO
stats_interval  = 10
log_errors_only = false
```

| Key | Type | Description |
|---|---|---|
| `log_file` | string | Path to the plain-text log file. Leave blank to disable file logging. |
| `stat_file` | string | Path to the JSON stats snapshot. Updated every `stats_interval` seconds and on shutdown. |
| `log_level` | string | Verbosity: `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| `stats_interval` | int | Print a live summary to the terminal every N seconds. `0` disables periodic summaries. |
| `log_errors_only` | bool | When `true`, only non-200 responses are logged (reduces terminal noise during long runs). |

---

## Running the Bot

```bash
# Use default config.ini
python rate_limit_bot.py

# Use a custom config file
python rate_limit_bot.py my_config.ini
```

---

## Terminal Output

On startup the bot prints a summary header, then streams one log line per request:

```
 Rate Limit Checker Bot

 URLs      : 1
   1. https://www.goat.com/sneakers/air-jordan-7-retro-miro-2026-iq6573-100
 Threads   : 25
 Limits    : MIN: 0/60  HOU: 0/1000  DAY: 0/10000  WEE: 0/50000  MON: 0/150000
 Duration  : ∞
 Browser   : chrome110
 Stat file : bot_stats.json
 Press Ctrl+C to stop

2026-07-13 21:49:06 [INFO] MainThread  | Started Worker-0
2026-07-13 21:49:07 [INFO] MainThread  | Started Worker-1
2026-07-13 21:49:07 [INFO] Worker-0    | [200] GET https://www.goat.com/... (1270ms)
2026-07-13 21:49:08 [INFO] Worker-1    | [200] GET https://www.goat.com/... (1071ms)
```

### Header fields

| Field | Description |
|---|---|
| **URLs** | Number of target URLs and their addresses. |
| **Threads** | Total worker thread count. |
| **Limits** | Live counters `current/limit` for each time window (MIN / HOU / DAY / WEE / MON). |
| **Duration** | `∞` for unlimited, or the countdown in seconds. |
| **Browser** | Active `curl_cffi` browser profile. |
| **Stat file** | Path of the JSON output file. |

### Log line format

```
YYYY-MM-DD HH:MM:SS [LEVEL] ThreadName | [STATUS_CODE] METHOD URL (response_time_ms)
```

- **`[200]`** — HTTP status code of the response (green for success, red/yellow for errors).
- **`(1270ms)`** — Round-trip time for that request.

---

## JSON Stats File

The bot writes (and overwrites) `bot_stats.json` every `stats_interval` seconds and once more on shutdown. This file is safe to read at any time — it is written atomically.

### Schema Reference

```
bot_stats.json
├── meta/
│   ├── urls[]            List of target URLs
│   ├── url_count         Number of URLs
│   ├── threads           Configured thread count
│   ├── status            "running" | "stopped"
│   ├── started_at        ISO-8601 timestamp of bot start
│   ├── updated_at        ISO-8601 timestamp of last stats flush
│   └── uptime_sec        Elapsed seconds since start
├── throughput/
│   ├── total_requests    All requests sent since start
│   └── req_per_sec       Rolling average requests/second
├── windows/
│   ├── minute/
│   │   ├── count         Requests in this window
│   │   ├── limit         Configured limit (0 = unlimited)
│   │   ├── pct           count / limit × 100 (% of limit consumed)
│   │   └── status        "ok" | "warning" | "limit_hit"
│   ├── hour/   …same fields…
│   ├── day/    …same fields…
│   ├── week/   …same fields…
│   └── month/  …same fields…
├── status_codes/
│   └── <code>            Count of responses with this HTTP status code
└── urls/
    └── <url>/
        ├── total_requests  Requests sent to this specific URL
        ├── req_per_sec     Per-URL rolling average
        └── status_codes/   Per-URL status code breakdown
            └── <code>
```

### Example Output

```json
{
  "meta": {
    "urls": [
      "https://www.goat.com/sneakers/air-jordan-7-retro-miro-2026-iq6573-100"
    ],
    "url_count": 1,
    "threads": 25,
    "status": "stopped",
    "started_at": "2026-07-13T16:49:06.587593+00:00",
    "updated_at": "2026-07-13T16:49:18.605074+00:00",
    "uptime_sec": 12.0
  },
  "throughput": {
    "total_requests": 10,
    "req_per_sec": 0.832
  },
  "windows": {
    "minute": { "count": 10, "limit": 60,     "pct": 16.7, "status": "ok" },
    "hour":   { "count": 10, "limit": 1000,   "pct": 1.0,  "status": "ok" },
    "day":    { "count": 10, "limit": 10000,  "pct": 0.1,  "status": "ok" },
    "week":   { "count": 10, "limit": 50000,  "pct": 0.0,  "status": "ok" },
    "month":  { "count": 10, "limit": 150000, "pct": 0.0,  "status": "ok" }
  },
  "status_codes": {
    "200": 10
  },
  "urls": {
    "https://www.goat.com/sneakers/air-jordan-7-retro-miro-2026-iq6573-100": {
      "total_requests": 10,
      "req_per_sec": 0.832,
      "status_codes": { "200": 10 }
    }
  }
}
```

Reading the stats from a shell script:

```bash
# Current minute window usage
jq '.windows.minute | "\(.count)/\(.limit) (\(.pct)%)"' bot_stats.json

# Overall requests per second
jq '.throughput.req_per_sec' bot_stats.json

# All status codes seen
jq '.status_codes' bot_stats.json
```

---

## Stopping the Bot

Press **Ctrl+C** at any time. The bot will:

1. Signal all worker threads to stop.
2. Wait for in-flight requests to complete.
3. Write a final `bot_stats.json` with `"status": "stopped"`.
4. Print a shutdown summary to the terminal.

If `run_duration` is set to a non-zero value, the bot also stops automatically after that many seconds.

---

## Tips & Tricks

**Find the exact rate limit threshold**
Start with generous window limits (`0` = unlimited) and a moderate thread count. Watch the terminal for the first 429 response and note the `minute.count` value in the JSON file at that moment.

**Avoid detection during long runs**
Set `rotate_ua = true`, choose a realistic `browser` profile (e.g. `chrome110`), and set `request_delay` to something human-like (1–3 seconds) rather than zero.

**Stop automatically on first rate-limit hit**
Set `stop_on_rate_limit = true` and `retry_codes =` (empty) so the bot halts and records exactly how many requests triggered the 429.

**Monitor from another terminal**
```bash
watch -n 2 "jq '.windows, .throughput' bot_stats.json"
```

**Combine with `jq` for CSV export**
```bash
jq -r '[.meta.updated_at, .throughput.total_requests, .windows.minute.count] | @csv' bot_stats.json
```

**Multiple targets**
Add more URLs under `[URLS]` — the bot round-robins across them automatically and reports per-URL stats in the `urls` section of the JSON file.