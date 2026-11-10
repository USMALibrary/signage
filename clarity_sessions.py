#!/usr/bin/env python3
"""
Pull yesterday's website sessions from the Microsoft Clarity Data Export API
and keep a running history for the signage dashboards.

Clarity only returns the last 1-3 days and allows 10 requests/project/day, so
this runs once a day, takes the "Traffic" metric for numOfDays=1 (the last
24 hours, UTC), and appends it to data/clarity-history.json. Human sessions =
total sessions minus Clarity's bot sessions.

Writes:
  data/clarity-history.json   every day recorded so far (the source of truth)
  data/website-sessions.json  what the signs read

Requires env var CLARITY_API_TOKEN (project admin: Settings > Data Export).
Optional: CLARITY_API_BASE (testing), CLARITY_TREND_DAYS (default 30).
Stdlib only; never prints the token.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API_URL = os.environ.get(
    "CLARITY_API_BASE", "https://www.clarity.ms/export-data/api/v1/project-live-insights"
)
TREND_DAYS = int(os.environ.get("CLARITY_TREND_DAYS", "30"))
HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY = os.path.join(HERE, "data", "clarity-history.json")
OUTPUT = os.path.join(HERE, "data", "website-sessions.json")


def fetch_traffic(token):
    req = Request(
        API_URL + "?numOfDays=1",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except HTTPError as e:
        print(f"HTTP {e.code} {e.reason} from Clarity")
        raise


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def parse_traffic(payload):
    """Return (total_sessions, bot_sessions) from the Traffic metric."""
    total = bots = 0
    found = False
    for metric in payload if isinstance(payload, list) else []:
        if metric.get("metricName") != "Traffic":
            continue
        found = True
        for row in metric.get("information", []):
            total += to_int(row.get("totalSessionCount"))
            bots += to_int(row.get("totalBotSessionCount"))
    if not found:
        raise ValueError("no Traffic metric in Clarity response")
    return total, bots


def load_history():
    try:
        with open(HISTORY) as f:
            return {d["date"]: d for d in json.load(f)}
    except (FileNotFoundError, ValueError):
        return {}


def main():
    token = os.environ.get("CLARITY_API_TOKEN", "")
    if not token:
        print("Error: CLARITY_API_TOKEN must be set")
        sys.exit(1)

    total, bots = parse_traffic(fetch_traffic(token))
    human = max(0, total - bots)

    # The call covers the 24 hours before now (UTC); record it as "yesterday".
    now = datetime.now(timezone.utc)
    day = (now.date() - timedelta(days=1)).isoformat()

    history = load_history()
    history[day] = {"date": day, "sessions": total, "bots": bots, "human": human}
    days = sorted(history)

    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w") as f:
        json.dump([history[d] for d in days], f, indent=1)

    as_of = datetime.strptime(days[-1], "%Y-%m-%d").date()
    month_days = [d for d in days if d.startswith(as_of.strftime("%Y-%m"))]
    out = {
        "updated": now.isoformat(),
        "asOfDate": days[-1],
        "yesterday": history[days[-1]]["human"],
        "month": {
            "label": as_of.strftime("%B %Y"),
            "total": sum(history[d]["human"] for d in month_days),
            "days": len(month_days),
        },
        "daily": [
            {
                "date": d,
                "dateDisplay": datetime.strptime(d, "%Y-%m-%d").strftime("%b ") + str(int(d[-2:])),
                "count": history[d]["human"],
            }
            for d in days[-TREND_DAYS:]
        ],
    }
    with open(OUTPUT, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Website sessions {days[-1]}: {human} human ({total} total, {bots} bot); month {out['month']['total']} over {len(month_days)} days")


if __name__ == "__main__":
    main()
