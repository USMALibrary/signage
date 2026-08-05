#!/usr/bin/env python3
"""
Fetch instruction calendar events from LibCal and write summary stats
to data/instruction-stats.json for the signage dashboard.

Requires env vars:
  LIBCAL_CLIENT_ID
  LIBCAL_CLIENT_SECRET

Optionally:
  LIBCAL_INSTRUCTION_CAL_ID  (default: 20048)
  SEMESTER_START              (default: auto-detect Aug 1 or Jan 15)
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

BASE = "https://usma.libcal.com/api/1.1"
CAL_ID = int(os.environ.get("LIBCAL_INSTRUCTION_CAL_ID", "20048"))
OUTPUT = os.path.join(os.path.dirname(__file__), "data", "instruction-stats.json")


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
            print(f"Response body: {body[:1000]}")
        raise


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


def fetch_events(token, cal_id, date_str, days=0, limit=500):
    """Fetch events from a calendar for a date range. Paginates if needed."""
    all_events = []
    page = 1
    while True:
        params = {
            "cal_id": cal_id,
            "date": date_str,
            "days": days,
            "limit": limit,
            "page": page,
        }
        url = BASE + "/events?" + urlencode(params)
        result = api_request(url, headers={"Authorization": "Bearer " + token})

        # The API may return {"events": [...]} or just [...]
        events = result
        if isinstance(result, dict):
            events = result.get("events", result.get("data", []))
            if isinstance(events, dict):
                # Sometimes keyed by calendar ID
                flat = []
                for k, v in events.items():
                    if isinstance(v, list):
                        flat.extend(v)
                events = flat

        if not events:
            break
        all_events.extend(events)
        if len(events) < limit:
            break
        page += 1

    return all_events


def get_semester_start(today):
    """Auto-detect semester start: Aug 1 for fall, Jan 15 for spring."""
    override = os.environ.get("SEMESTER_START", "")
    if override:
        return override

    # Fall semester (including summer instruction): Jul 1 – Dec 31
    # Spring semester: Jan 15 – Jun 30
    if today.month >= 7:
        return f"{today.year}-07-01"
    else:
        return f"{today.year}-01-15"


def fmt_time_12h(iso_str):
    """Parse ISO datetime and return '9:00 AM' format."""
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
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    # ── TODAY'S EVENTS ──
    print(f"Fetching today's events ({today_str}) from calendar {CAL_ID}...")
    today_events = fetch_events(token, CAL_ID, today_str, days=0)
    print(f"  Found {len(today_events)} events today")

    # ── THIS WEEK ──
    # Monday of this week
    monday = today - timedelta(days=today.weekday())
    monday_str = monday.strftime("%Y-%m-%d")
    days_left = 4 - today.weekday()  # Mon=0, Fri=4
    if days_left < 0:
        days_left = 0
    # Fetch Mon through Fri (4 days from Monday)
    print(f"Fetching this week ({monday_str} + 4 days)...")
    week_events = fetch_events(token, CAL_ID, monday_str, days=4)
    print(f"  Found {len(week_events)} events this week")

    # ── SEMESTER TOTAL ──
    semester_start = get_semester_start(today)
    days_since_start = (today - datetime.strptime(semester_start, "%Y-%m-%d")).days
    if days_since_start < 0:
        days_since_start = 0
    print(f"Fetching semester events ({semester_start} + {days_since_start} days)...")
    semester_events = fetch_events(token, CAL_ID, semester_start, days=days_since_start)
    print(f"  Found {len(semester_events)} events this semester")

    # ── BUILD TODAY'S SESSION LIST ──
    now = datetime.now()
    sessions_today = []
    for ev in today_events:
        title = ev.get("title", "Untitled")
        start = ev.get("start", ev.get("date", {}).get("start", ""))
        end = ev.get("end", ev.get("date", {}).get("end", ""))
        location = ""
        if isinstance(ev.get("location"), dict):
            location = ev["location"].get("name", "")
        elif isinstance(ev.get("location"), str):
            location = ev["location"]
        campus_location = ev.get("campus", {}).get("name", "") if isinstance(ev.get("campus"), dict) else ""

        # Determine status
        status = "upcoming"
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            if now >= start_dt and now < end_dt:
                status = "now"
            elif now >= end_dt:
                status = "done"
        except Exception:
            pass

        sessions_today.append({
            "title": title,
            "start": start,
            "end": end,
            "startDisplay": fmt_time_12h(start),
            "endDisplay": fmt_time_12h(end),
            "location": location or campus_location,
            "status": status,
        })

    # Sort by start time
    sessions_today.sort(key=lambda x: x["start"])

    # Find next upcoming
    next_session = None
    for s in sessions_today:
        if s["status"] in ("upcoming", "now"):
            next_session = {
                "title": s["title"],
                "time": s["startDisplay"],
                "status": s["status"],
            }
            break

    # ── SEMESTER LABEL ──
    semester_label = "Fall" if today.month >= 8 else "Spring"
    semester_label += f" {today.year}"

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "calendarId": CAL_ID,
        "today": {
            "date": today_str,
            "count": len(today_events),
            "sessions": sessions_today,
            "next": next_session,
        },
        "thisWeek": {
            "startDate": monday_str,
            "count": len(week_events),
        },
        "semester": {
            "label": semester_label,
            "startDate": semester_start,
            "count": len(semester_events),
        },
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSummary: {len(today_events)} today, {len(week_events)} this week, "
          f"{len(semester_events)} {semester_label}")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
