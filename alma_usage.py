#!/usr/bin/env python3
"""
Fetch daily circulation totals from an Alma Analytics report and write
a monthly running total + daily trend series to data/circulation-usage.json
for the signage dashboard.

Requires env vars:
  ALMA_API_KEY          (read-only Analytics API key)

Optionally:
  ALMA_REPORT_PATH       (default: the Signage/Circulation Daily Totals report)
  ALMA_API_BASE           (default: NA region Alma API host)
  ALMA_TREND_DAYS         (default: 30)
"""

import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

API_BASE = os.environ.get(
    "ALMA_API_BASE", "https://api-na.hosted.exlibrisgroup.com/almaws/v1/analytics/reports"
)
REPORT_PATH = os.environ.get(
    "ALMA_REPORT_PATH",
    "/shared/United States Military Academy (West Point) 01USMA_INST/Reports/Signage/Circulation Daily Totals",
)
TREND_DAYS = int(os.environ.get("ALMA_TREND_DAYS", "30"))
OUTPUT = os.path.join(os.path.dirname(__file__), "data", "circulation-usage.json")

ROWSET_NS = "urn:schemas-microsoft-com:xml-analysis:rowset"
XSD_NS = "http://www.w3.org/2001/XMLSchema"
SAW_NS = "urn:saw-sql"

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S")


def api_get(params):
    """GET the Analytics API with error-body logging, return raw XML bytes."""
    url = API_BASE + "?" + urlencode(params)
    req = Request(url, headers={"Accept": "application/xml"})
    try:
        with urlopen(req) as resp:
            return resp.read()
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        print(f"HTTP {e.code} {e.reason} on GET {url}")
        if body:
            print(f"Response body: {body[:1000]}")
        raise


def get_rowset_element(root):
    """Find the <rowset> node inside <ResultXml>, handling both the
    normal embedded-XML shape and the escaped-text shape some Alma
    instances return."""
    result_xml = root.find(".//ResultXml")
    if result_xml is None:
        return None

    rowset = result_xml.find(f"{{{ROWSET_NS}}}rowset")
    if rowset is not None:
        return rowset

    if result_xml.text and result_xml.text.strip():
        inner = ET.fromstring(result_xml.text.strip())
        if inner.tag.endswith("rowset"):
            return inner
        return inner.find(f"{{{ROWSET_NS}}}rowset")

    return None


def parse_rows(rowset):
    """Map Column0/Column1/... to their saw-sql:columnHeading names and
    return a list of {heading: value} dicts."""
    headings = {}
    for el in rowset.iter(f"{{{XSD_NS}}}element"):
        name = el.get("name")
        heading = el.get(f"{{{SAW_NS}}}columnHeading")
        if name and heading and name.startswith("Column"):
            headings[name] = heading

    rows = []
    for row in rowset.iter(f"{{{ROWSET_NS}}}Row"):
        record = {}
        for child in row:
            tag = child.tag.split("}")[-1]
            key = headings.get(tag, tag)
            record[key] = (child.text or "").strip()
        rows.append(record)
    return rows


def fetch_all_rows(api_key, path):
    """Fetch every row of the report, following ResumptionToken pages."""
    all_rows = []
    params = {"apikey": api_key, "path": path, "limit": 1000, "col_names": "false"}

    while True:
        xml_bytes = api_get(params)
        root = ET.fromstring(xml_bytes)

        rowset = get_rowset_element(root)
        if rowset is not None:
            all_rows.extend(parse_rows(rowset))

        finished_el = root.find(".//IsFinished")
        is_finished = finished_el is not None and (finished_el.text or "").strip().lower() == "true"
        if is_finished:
            break

        token_el = root.find(".//ResumptionToken")
        if token_el is None or not (token_el.text or "").strip():
            break
        params = {"apikey": api_key, "token": token_el.text.strip()}

    return all_rows


def find_value(record, wanted):
    """Look up a column by exact heading, falling back to a case-insensitive
    substring match since report column labels can shift slightly."""
    if wanted in record:
        return record[wanted]
    wanted_lower = wanted.lower()
    for key, value in record.items():
        if wanted_lower in key.lower():
            return value
    return None


def parse_date(value):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def fmt_date_display(d):
    return f"{d.strftime('%b')} {d.day}"


def main():
    api_key = os.environ.get("ALMA_API_KEY", "")
    if not api_key:
        print("Error: ALMA_API_KEY must be set")
        sys.exit(1)

    print(f"Fetching report: {REPORT_PATH}")
    raw_rows = fetch_all_rows(api_key, REPORT_PATH)
    print(f"  Found {len(raw_rows)} rows")

    daily = {}
    for record in raw_rows:
        date_str = find_value(record, "Loan Date")
        count_str = find_value(record, "Loans (In House + Not In House)")
        if not date_str:
            continue
        d = parse_date(date_str)
        if d is None:
            continue
        try:
            count = int(float(count_str)) if count_str else 0
        except ValueError:
            count = 0
        daily[d] = daily.get(d, 0) + count

    if not daily:
        print("Error: no usable rows parsed from Analytics response")
        sys.exit(1)

    sorted_dates = sorted(daily.keys())
    as_of = sorted_dates[-1]

    month_days = [d for d in sorted_dates if d.year == as_of.year and d.month == as_of.month]
    month_total = sum(daily[d] for d in month_days)
    month_start = as_of.replace(day=1)

    trend_dates = sorted_dates[-TREND_DAYS:]
    daily_series = [
        {
            "date": d.isoformat(),
            "dateDisplay": fmt_date_display(d),
            "count": daily[d],
        }
        for d in trend_dates
    ]

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "asOfDate": as_of.isoformat(),
        "month": {
            "label": as_of.strftime("%B %Y"),
            "startDate": month_start.isoformat(),
            "total": month_total,
            "days": len(month_days),
        },
        "daily": daily_series,
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Month to date ({output['month']['label']}): {month_total} loans over {len(month_days)} days")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
