#!/usr/bin/env python3
"""Export residential parcels from the City of Bangor, ME ArcGIS parcel service to CSV.

Source: ParcelViewer/Parcels/MapServer, table 2 "Parcel_Assessing_Data" -- a nightly
extract of the city's TRIO assessment database. The service's item info states
"Permission must be obtained from the City of Bangor, Maine" for use of the data.

Residential = LAND_TYPE 'Residential' (the city's own land classification). Pass
--include-trailer-parks to also include LAND_TYPE 'Trailer Park'.

One row per assessment card (an account with several buildings has several cards,
each with its own year built).

Usage: python3 tools/bangor_parcels_export.py [-o data/bangor_residential_parcels.csv]
"""
import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request

URL = ("https://mapping.bangormaine.gov/server/rest/services/"
       "ParcelViewer/Parcels/MapServer/2/query")
PAGE = 2000  # service maxRecordCount

# (source field, CSV column)
COLUMNS = [
    ("RE_ACCT", "account"),
    ("CARD", "card"),
    ("MAP_LOT", "map_lot"),
    ("PROP_LOC", "property_location"),
    ("OWNER", "owner"),
    ("OWNER2", "owner2"),
    ("OWN_ADD1", "mailing_address_1"),
    ("OWN_ADD2", "mailing_address_2"),
    ("RES_YR_BLT", "year_built"),
    ("LAND_TYPE", "land_type"),
    ("BLDG_TYPE", "building_type"),
    ("RES_UNITS", "residential_units"),
]


def fetch(params, retries=4):
    data = urllib.parse.urlencode({**params, "f": "json"}).encode()
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(URL, data=data, timeout=60) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:  # network blips: back off and retry
            if attempt == retries - 1:
                raise
            print(f"retry after error: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)


def clean(v):
    if v is None:
        return ""
    if isinstance(v, str):
        v = " ".join(v.split())
        return "" if v == "0" else v
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="data/bangor_residential_parcels.csv")
    ap.add_argument("--include-trailer-parks", action="store_true")
    a = ap.parse_args()

    types = ["Residential"] + (["Trailer Park"] if a.include_trailer_parks else [])
    where = "LAND_TYPE IN (" + ",".join(f"'{t}'" for t in types) + ")"
    out_fields = ",".join(f for f, _ in COLUMNS)

    expected = fetch({"where": where, "returnCountOnly": "true"})["count"]
    rows, offset = [], 0
    while True:
        d = fetch({
            "where": where, "outFields": out_fields, "returnGeometry": "false",
            "orderByFields": "OBJECTID", "resultOffset": offset,
            "resultRecordCount": PAGE,
        })
        feats = d.get("features", [])
        rows += [f["attributes"] for f in feats]
        offset += len(feats)
        print(f"fetched {offset}/{expected}", file=sys.stderr)
        if not feats or not d.get("exceededTransferLimit") and offset >= expected:
            break

    if len(rows) != expected:
        sys.exit(f"row count mismatch: got {len(rows)}, expected {expected}")

    rows.sort(key=lambda r: (str(r["RE_ACCT"]), r["CARD"] or 0))
    import os
    os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
    with open(a.output, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([c for _, c in COLUMNS])
        for r in rows:
            vals = [clean(r.get(f)) for f, _ in COLUMNS]
            yb = COLUMNS.index(("RES_YR_BLT", "year_built"))
            if vals[yb] in (0, "0"):
                vals[yb] = ""  # 0 = unknown / no dwelling
            w.writerow(vals)
    print(f"wrote {len(rows)} rows to {a.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
