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


def local_name(tag):
    return tag.split("}")[-1]


def strip_type_prefix(value):
    """'xsd:date' -> 'date'. Type attribute values are QName strings, not
    Clark-notation tags, so this is a plain colon-split, not local_name()."""
    return value.split(":")[-1] if value else value


def parse_rows(rowset):
    """Extract {date, count} from each Row, identifying which ColumnN is
    which by its XSD type rather than by name.

    This Alma Analytics instance's schema carries no columnHeading (or
    equivalent) attribute at all — only saw-sql:displayFormula and a type.
    The date column is whichever is typed xsd:date; the count column is
    whichever numeric column is xsd:double (the report also includes a
    constant int column that isn't real data).
    """
    col_types = {}
    for el in rowset.iter():
        if local_name(el.tag) != "element":
            continue
        name = el.get("name")
        if not name or not name.startswith("Column"):
            continue
        col_types[name] = strip_type_prefix(el.get("type", ""))

    date_col = next((c for c, t in col_types.items() if t == "date"), None)
    numeric_cols = [c for c, t in col_types.items() if t in ("double", "float", "decimal")]
    count_col = numeric_cols[0] if numeric_cols else next(
        (c for c, t in col_types.items() if t == "int" and c != date_col), None
    )

    rows = []
    for row in rowset.iter():
        if local_name(row.tag) != "Row":
            continue
        record = {}
        for child in row:
            record[local_name(child.tag)] = (child.text or "").strip()
        rows.append({"date": record.get(date_col), "count": record.get(count_col)})
    return rows


DEBUG_DUMP = os.path.join(os.path.dirname(__file__), "data", ".alma-debug-response.xml")


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
        date_str = record.get("date")
        count_str = record.get("count")
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
