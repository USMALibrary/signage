#!/usr/bin/env python3
"""
Fetch today's LibCal space bookings for Jefferson Hall and write to
data/room-reservations.json for the signage dashboard.

Requires env vars:
  LIBCAL_CLIENT_ID
  LIBCAL_CLIENT_SECRET

Optionally:
  LIBCAL_LOCATION_NAME  (default: "Jefferson Hall")
"""

import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

BASE = "https://usma.libcal.com/api/1.1"
LOCATION_ID = int(os.environ.get("LIBCAL_LOCATION_ID", "7099"))  # Jefferson Hall
LOCATION_NAME = os.environ.get("LIBCAL_LOCATION_NAME", "Jefferson Hall")
OUTPUT = os.path.join(os.path.dirname(__file__), "data", "room-reservations.json")


def api_request(url, data=None, headers=None, method=None):
    """Make an HTTP request with error-body logging."""
    if method is None:
        method = "POST" if data is not None else "GET"
    req = Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        print(f"HTTP {e.code} {e.reason} on {method} {url}")
        if body:
            print(f"Response body: {body}")
        raise


def api_get(path, token, params=None):
    """GET with Bearer auth, return parsed JSON."""
    url = BASE + path
    if params:
        url += "?" + urlencode(params)
    return api_request(url, headers={"Authorization": "Bearer " + token})


def get_token(client_id, client_secret):
    """Authenticate via OAuth client_credentials grant."""
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    body = urlencode(data).encode()
    return api_request(
        BASE + "/oauth/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )["access_token"]


def find_location(token, name):
    """Find a space location by name, return its lid."""
    locations = api_get("/space/locations", token)
    for loc in locations:
        if loc.get("name", "").strip().lower() == name.strip().lower():
            return loc["lid"]
    # Fallback: partial match
    for loc in locations:
        if name.strip().lower() in loc.get("name", "").strip().lower():
            return loc["lid"]
    # Last resort: return first location
    if locations:
        print(f"Warning: '{name}' not found. Using '{locations[0]['name']}' (lid={locations[0]['lid']})")
        return locations[0]["lid"]
    raise RuntimeError("No space locations found in LibCal")


def fetch_bookings(token, lid, date_str):
    """Fetch all confirmed bookings for a location on a given date.

    The API paginates at 500 max per page. We loop until we have them all.
    """
    all_bookings = []
    page = 1
    while True:
        params = {
            "lid": lid,
            "date": date_str,
            "days": 0,           # just this date
            "limit": 500,
            "page": page,
            "include_tentative": 1,
            "include_cancel": 0,
            "include_denied": 0,
        }
        batch = api_get("/space/bookings", token, params)
        if not batch:
            break
        all_bookings.extend(batch)
        if len(batch) < 500:
            break
        page += 1
    return all_bookings


def fmt_time_12h(iso_str):
    """'2026-08-04T09:00:00-04:00' -> '9:00 AM'"""
    try:
        dt = datetime.fromisoformat(iso_str)
        h = dt.hour
        ampm = "AM" if h < 12 else "PM"
        h = h % 12 or 12
        return f"{h}:{dt.minute:02d} {ampm}"
    except Exception:
        return iso_str


def main():
    client_id = os.environ.get("LIBCAL_CLIENT_ID", "")
    client_secret = os.environ.get("LIBCAL_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("Error: LIBCAL_CLIENT_ID and LIBCAL_CLIENT_SECRET must be set")
        sys.exit(1)

    token = get_token(client_id, client_secret)
    lid = LOCATION_ID
    print(f"Using location: {LOCATION_NAME} (lid={lid})")

    today = datetime.now().strftime("%Y-%m-%d")
    raw = fetch_bookings(token, lid, today)
    print(f"Fetched {len(raw)} bookings for {today}")

    # Build clean booking list sorted by start time
    bookings = []
    for b in raw:
        status = (b.get("status") or "").strip()
        # Skip anything that's not confirmed/approved/tentative
        if status.lower() in ("cancelled", "denied", "canceled"):
            continue

        event_title = ""
        event = b.get("event")
        if isinstance(event, dict):
            event_title = event.get("title", "")
        elif isinstance(event, list) and event:
            event_title = event[0].get("title", "")

        bookings.append({
            "room": b.get("item_name", "Unknown"),
            "category": b.get("category_name", ""),
            "from": b.get("fromDate", ""),
            "to": b.get("toDate", ""),
            "fromDisplay": fmt_time_12h(b.get("fromDate", "")),
            "toDisplay": fmt_time_12h(b.get("toDate", "")),
            "title": event_title or b.get("nickname", ""),
            "nickname": b.get("nickname", ""),
            "status": status,
        })

    # Sort by start time, then room name
    bookings.sort(key=lambda x: (x["from"], x["room"]))

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "location": LOCATION_NAME,
        "lid": lid,
        "count": len(bookings),
        "bookings": bookings,
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(bookings)} bookings to {OUTPUT}")


if __name__ == "__main__":
    main()
