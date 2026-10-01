#!/usr/bin/env python3
"""
papercut_status.py

Polls the PaperCut NG/MF System Health API for printer status and writes a
compact JSON feed (papercut-status.json) in the same shape the Staff
Operations dashboard's Print Queue panel expects.

Intended to run on a schedule (cron / Task Scheduler / GitHub Actions runner
with network access to the PaperCut server) right alongside whatever already
produces hours-today.json, on-call.json, etc.

--------------------------------------------------------------------------
SETUP
--------------------------------------------------------------------------
1. Find your Health API key in the PaperCut admin console:
     Options -> Advanced -> "System health monitoring" section
     (or ask PaperCut support for the config key "health.api.key" if it's
     not surfaced in your version's UI - it can also be read with
     server-command: `server-command get-config-value health.api.key`)

2. Set the environment variables below (or hardcode for a quick test):
     PAPERCUT_HOST           e.g. papercut.westpoint.edu (or its IP, 10.0.16.14)
     PAPERCUT_HEALTH_PORT    usually 9191 (http) or 9192 (https)
     PAPERCUT_HEALTH_KEY     the health.api.key value from step 1
     PAPERCUT_STATS_MINUTES  window for the pages-printed stat (default 60)
     PAPERCUT_PRINTER_FILTER optional comma-separated allowlist of
                              "server\\printer" names to include (all
                              printers are included if unset)
     OUTPUT_PATH             where to write papercut-status.json

3. This script only WRITES the file locally. If your other feeds are
   published to usmalibrary.github.io/signage/data/ via a git repo, add a
   `git add / commit / push` step after this script runs (or drop the
   output file directly into whatever syncs that folder today).
--------------------------------------------------------------------------
"""

import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime, timezone

PAPERCUT_HOST = os.environ.get("PAPERCUT_HOST", "papercut.westpoint.edu")
PAPERCUT_HEALTH_PORT = os.environ.get("PAPERCUT_HEALTH_PORT", "9192")
PAPERCUT_HEALTH_KEY = os.environ.get("PAPERCUT_HEALTH_KEY", "")
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "papercut-status.json")

# Window (in minutes) for the "recent pages printed" stat.
PAPERCUT_STATS_MINUTES = os.environ.get("PAPERCUT_STATS_MINUTES", "60")

# Optional allowlist of printers to include in the feed, comma-separated,
# matched exactly against the "server\\printer" name PaperCut reports
# (e.g. "wppss6print\WPPRLIBADM,wppss6print\WPPRLIBREF01"). Leave unset
# to include all printers.
_filter_raw = os.environ.get("PAPERCUT_PRINTER_FILTER", "")
PAPERCUT_PRINTER_FILTER = (
    {p.strip() for p in _filter_raw.split(",") if p.strip()}
    if _filter_raw else None
)

# Set to False if your PaperCut server uses a self-signed cert and you
# haven't installed it in your trust store. Only disable on a trusted
# internal network.
VERIFY_TLS = os.environ.get("PAPERCUT_VERIFY_TLS", "true").lower() != "false"


def fetch_printer_health():
    url = f"https://{PAPERCUT_HOST}:{PAPERCUT_HEALTH_PORT}/api/health/printers?json"
    req = urllib.request.Request(url, headers={"Authorization": PAPERCUT_HEALTH_KEY})

    ctx = None
    if not VERIFY_TLS:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_pages_last_60_min():
    """
    Fetches the "recent pages printed" real-time stat via:
      /api/stats/recent-pages-count?minutes=<N>&Authorization=<key>
    Returns None on any error - this stat is optional and shouldn't block
    the printer status feed from being written.
    """
    url = (
        f"https://{PAPERCUT_HOST}:{PAPERCUT_HEALTH_PORT}"
        f"/api/stats/recent-pages-count"
        f"?minutes={PAPERCUT_STATS_MINUTES}&Authorization={PAPERCUT_HEALTH_KEY}"
    )

    ctx = None
    if not VERIFY_TLS:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw_text = resp.read().decode("utf-8").strip()

            # Some PaperCut versions return a plain number as text, not JSON
            try:
                return int(raw_text)
            except ValueError:
                pass
            try:
                return float(raw_text)
            except ValueError:
                pass

            # Otherwise try parsing as JSON
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                return raw_text  # Return whatever text it is

            # If it's already a number, return it
            if isinstance(data, (int, float)):
                return data

            # If it's a dict, try known key names
            if isinstance(data, dict):
                for key in ("value", "pagesPrinted", "pages", "count",
                            "result", "data", "total", "recentPagesCount"):
                    if key in data:
                        val = data[key]
                        if isinstance(val, (int, float)):
                            return val
                # Last resort: return the first numeric value found
                for val in data.values():
                    if isinstance(val, (int, float)):
                        return val

            # If it's a list with one item, try to extract from it
            if isinstance(data, list) and len(data) == 1:
                item = data[0]
                if isinstance(item, (int, float)):
                    return item

            print(f"WARNING: unexpected pages stat response shape: {raw_text[:200]}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"WARNING: could not fetch recent-pages-count stat: {e}", file=sys.stderr)
        return None


def build_feed(raw, pages_60min=None):
    """
    Normalizes the PaperCut health API response into the shape the
    dashboard's loadPrintQueue() expects:

    {
      "updated": "2026-07-21T20:31:00Z",
      "printers": [
        {"name": "...", "status": "OK"|"WARNING"|"ERROR",
         "detail": "Low toner (25%)" or null, "heldJobsCount": 0}
      ]
    }
    """
    printers = raw.get("printers", raw) if isinstance(raw, dict) else raw
    out = []
    for p in printers:
        name = p.get("name", "Unknown printer")
        if PAPERCUT_PRINTER_FILTER is not None and name not in PAPERCUT_PRINTER_FILTER:
            continue
        status = (p.get("status") or "OK").upper()
        out.append({
            "name": name,
            "status": status,
            "detail": p.get("detail") or p.get("message"),
            "heldJobsCount": p.get("heldJobsCount", 0),
        })

    if PAPERCUT_PRINTER_FILTER is not None:
        matched_names = {p["name"] for p in out}
        unmatched = PAPERCUT_PRINTER_FILTER - matched_names
        if unmatched:
            print(f"WARNING: PAPERCUT_PRINTER_FILTER names not found in "
                  f"health API response: {sorted(unmatched)}", file=sys.stderr)

    return {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pagesLast60Min": pages_60min,
        "printers": out,
    }


def main():
    if not PAPERCUT_HEALTH_KEY:
        print("ERROR: PAPERCUT_HEALTH_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    try:
        raw = fetch_printer_health()
    except Exception as e:
        print(f"ERROR fetching PaperCut health API: {e}", file=sys.stderr)
        sys.exit(1)

    pages_60min = fetch_pages_last_60_min()
    feed = build_feed(raw, pages_60min)

    with open(OUTPUT_PATH, "w") as f:
        json.dump(feed, f, indent=2)

    print(f"Wrote {OUTPUT_PATH}: {len(feed['printers'])} printers, "
          f"{sum(p['heldJobsCount'] for p in feed['printers'])} held jobs.")


if __name__ == "__main__":
    main()
