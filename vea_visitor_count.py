#!/usr/bin/env python3
"""
Fetch today's Vea (SenSource) entrance traffic and write data/visitor-count.json
for the signage dashboard.

Requires env vars:
  VEA_CLIENT_ID
  VEA_CLIENT_SECRET

Run with --debug to dump the raw traffic response and the per-zone breakdown
without writing the output file.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

TOKEN_URL = "https://auth.sensourceinc.com/oauth/token"
TRAFFIC_URL = "https://vea.sensourceinc.com/api/data/traffic"
TRAFFIC_PARAMS = {
    "relativeDate": "today",
    "dateGroupings": "day",
    "entityType": "zone",
    "metrics": "ins,outs",
}
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "visitor-count.json")

# Keys the Vea response may use for each field, in preference order.
ZONE_NAME_KEYS = ("zoneName", "name", "entityName", "locationName", "zone")
INS_KEYS = ("ins", "sumins", "totalins")
OUTS_KEYS = ("outs", "sumouts", "totalouts")


class AuthError(RuntimeError):
    """Raised when Vea rejects our credentials or token."""


def http_json(url, data=None, headers=None, method=None, attempts=2):
    """Request JSON, retrying once on transient errors. Auth failures never retry."""
    if method is None:
        method = "POST" if data is not None else "GET"

    last_err = None
    for attempt in range(1, attempts + 1):
        req = Request(url, data=data, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            print(f"HTTP {e.code} {e.reason} on {method} {url}")
            if body:
                print(f"Response body: {body[:1000]}")
            if e.code in (400, 401, 403):
                raise AuthError(f"Vea rejected the request with HTTP {e.code}") from e
            last_err = e
        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"Request failed on {method} {url}: {e}")
            last_err = e

        if attempt < attempts:
            print(f"Retrying (attempt {attempt + 1} of {attempts})...")
            time.sleep(3)

    raise last_err


def get_token(client_id, client_secret):
    """Authenticate via OAuth client_credentials grant."""
    body = urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()
    resp = http_json(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = resp.get("access_token")
    if not token:
        raise AuthError(f"No access_token in token response: {list(resp)}")
    return token


def fetch_traffic(token):
    """Fetch today's per-zone in/out traffic."""
    url = TRAFFIC_URL + "?" + urlencode(TRAFFIC_PARAMS)
    return http_json(url, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token,
    })


def extract_records(payload):
    """Pull the list of zone records out of whatever envelope Vea wraps them in."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "data", "records", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise RuntimeError(f"Unrecognized traffic response shape: {type(payload).__name__} {str(payload)[:300]}")


def pick(record, keys, default=None):
    """First matching key in `record`, compared case-insensitively."""
    lowered = {str(k).lower(): v for k, v in record.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return default


def summarize(records):
    """Return (zones, total_ins, total_outs, recognized) where zones is (name, ins, outs).

    `recognized` counts records we could actually read a metric off, so a schema
    change shows up as an error instead of a zeroed-out visitor count on the sign.
    """
    zones = []
    recognized = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        name = pick(rec, ZONE_NAME_KEYS, "(unnamed)")
        raw_ins = pick(rec, INS_KEYS)
        raw_outs = pick(rec, OUTS_KEYS)
        if raw_ins is not None or raw_outs is not None:
            recognized += 1
        zones.append((str(name), int(raw_ins or 0), int(raw_outs or 0)))
    return zones, sum(z[1] for z in zones), sum(z[2] for z in zones), recognized


def main():
    debug = "--debug" in sys.argv

    client_id = os.environ.get("VEA_CLIENT_ID", "")
    client_secret = os.environ.get("VEA_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("Error: VEA_CLIENT_ID and VEA_CLIENT_SECRET must be set")
        sys.exit(1)

    try:
        token = get_token(client_id, client_secret)
        payload = fetch_traffic(token)
    except AuthError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if debug:
        print("--- raw traffic response ---")
        print(json.dumps(payload, indent=2)[:8000])
        print("--- end raw response ---")

    records = extract_records(payload)
    zones, total_ins, total_outs, recognized = summarize(records)

    print(f"Zones returned: {len(zones)}")
    for name, ins, outs in zones:
        print(f"  {name}: ins={ins} outs={outs}")

    if not recognized:
        sample = sorted(records[0]) if records and isinstance(records[0], dict) else []
        print(f"Error: no ins/outs metric found on any of {len(records)} record(s).")
        print(f"Keys on the first record: {sample}")
        print(f"Expected one of {INS_KEYS} / {OUTS_KEYS} -- the API schema likely changed.")
        sys.exit(1)

    occupancy = max(0, total_ins - total_outs)
    print(f"Totals: ins={total_ins} outs={total_outs} occupancy={occupancy}")

    if debug:
        print("Debug run, not writing output file.")
        return

    output = {
        "count": total_ins,
        "occupancy": occupancy,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"Wrote {OUTPUT}: {json.dumps(output, separators=(',', ':'))}")


if __name__ == "__main__":
    main()
