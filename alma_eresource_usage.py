#!/usr/bin/env python3
"""
Fetch monthly e-resource usage totals from an Alma Analytics report and
write a monthly trend series to data/eresource-usage.json for the
signage dashboard.

Requires env vars:
  ALMA_API_KEY               (read-only Analytics API key)

Optionally:
  ALMA_ERESOURCE_REPORT_PATH  (default: the Signage/E-Resource Usage Monthly report)
  ALMA_API_BASE                (default: NA region Alma API host)
  ALMA_ERESOURCE_TREND_MONTHS  (default: 12)
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
    "ALMA_ERESOURCE_REPORT_PATH",
    "/shared/United States Military Academy (West Point) 01USMA_INST/Reports/Signage/E-Resource Usage Monthly",
)
TREND_MONTHS = int(os.environ.get("ALMA_ERESOURCE_TREND_MONTHS", "12"))
OUTPUT = os.path.join(os.path.dirname(__file__), "data", "eresource-usage.json")

ROWSET_NS = "urn:schemas-microsoft-com:xml-analysis:rowset"

# "Usage Date Year-Month" has shown up as plain "YYYY-MM" in this Alma
# instance; the other formats are kept as a safety net in case the
# report's display format ever changes.
MONTH_FORMATS = ("%Y-%m", "%Y-%m-%d", "%b %Y", "%B %Y", "%m/%Y", "%Y%m")


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


def local_name(tag):
    return tag.split("}")[-1]


def parse_rows(rowset):
    """Extract raw {ColumnN: value} records from each Row.

    Deliberately doesn't use the schema's declared XSD type to tell the
    month column from the count column — that approach broke silently
    for the circulation report (whose schema carries no reliable type
    info at all) and produced all-zero counts here, so column roles are
    decided from the actual values instead, in main().
    """
    rows = []
    for row in rowset.iter():
        if local_name(row.tag) != "Row":
            continue
        record = {}
        for child in row:
            record[local_name(child.tag)] = (child.text or "").strip()
        rows.append(record)
    return rows


def looks_numeric(value):
    if not value:
        return False
    try:
        float(value)
        return True
    except ValueError:
        return False


def detect_columns(raw_rows):
    """Pick the count column as whichever ColumnN parses as a number in
    every non-empty row, and the month column as whichever other column
    remains."""
    if not raw_rows:
        return None, None
    col_names = sorted(raw_rows[0].keys())
    numeric_cols = [
        c for c in col_names
        if any(r.get(c) for r in raw_rows) and all(looks_numeric(r.get(c)) for r in raw_rows if r.get(c))
    ]
    count_col = numeric_cols[0] if numeric_cols else None
    month_col = next((c for c in col_names if c != count_col), None)
    return month_col, count_col


DEBUG_DUMP = os.path.join(os.path.dirname(__file__), "data", ".alma-eresource-debug-response.xml")


def fetch_all_rows(api_key, path):
    """Fetch every row of the report, following ResumptionToken pages."""
    all_rows = []
    params = {"apikey": api_key, "path": path, "limit": 1000, "col_names": "false"}
    first_page = True

    while True:
        xml_bytes = api_get(params)
        if first_page:
            with open(DEBUG_DUMP, "wb") as f:
                f.write(xml_bytes)
            first_page = False
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


def parse_month(value):
    value = (value or "").strip()
    for fmt in MONTH_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().replace(day=1)
        except ValueError:
            continue
    return None


def fmt_month_display(d):
    return d.strftime("%b %Y")


def main():
    api_key = os.environ.get("ALMA_API_KEY", "")
    if not api_key:
        print("Error: ALMA_API_KEY must be set")
        sys.exit(1)

    print(f"Fetching report: {REPORT_PATH}")
    raw_rows = fetch_all_rows(api_key, REPORT_PATH)
    print(f"  Found {len(raw_rows)} rows")
    if raw_rows:
        print(f"  Sample row: {raw_rows[0]}")

    month_col, count_col = detect_columns(raw_rows)
    print(f"  Detected columns: month={month_col}, count={count_col}")

    monthly = {}
    for record in raw_rows:
        month_str = record.get(month_col)
        count_str = record.get(count_col)
        if not month_str:
            continue
        m = parse_month(month_str)
        if m is None:
            continue
        try:
            count = int(float(count_str)) if count_str else 0
        except ValueError:
            count = 0
        monthly[m] = monthly.get(m, 0) + count

    if not monthly:
        print("Error: no usable rows parsed from Analytics response")
        sys.exit(1)

    sorted_months = sorted(monthly.keys())
    as_of = sorted_months[-1]

    trend_months = sorted_months[-TREND_MONTHS:]
    monthly_series = [
        {
            "month": m.isoformat()[:7],
            "monthDisplay": fmt_month_display(m),
            "count": monthly[m],
        }
        for m in trend_months
    ]

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "asOfMonth": as_of.isoformat()[:7],
        "month": {
            "label": fmt_month_display(as_of),
            "total": monthly[as_of],
        },
        "monthly": monthly_series,
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Latest month ({output['month']['label']}): {monthly[as_of]} requests")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
