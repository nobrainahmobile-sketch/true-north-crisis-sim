#!/usr/bin/env python3
"""STEP 2c - Download Bangor's public permit records ("Code Documents" layer).

Source: ParcelViewer/Documents/MapServer/1 - permits issued 2014 to Jan 2020.
The layer has permit type, number, address, dates and owner, but NO description
of the work, and no roofing permit type: a re-roof would be filed as
"CONST EXIS" (construction on an existing building) along with decks,
additions, windows, siding, renovations, etc.

So these records can only say "some exterior/structural work was permitted",
which step 4 uses as a "possible re-roof - verify" flag, not as proof.

Output: data/public_permits.csv (all permit types, addresses normalized the
same way as step 3 so they join to step3_targets.site_norm).
"""
import csv
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from arcgis import SERVICE, get_json  # noqa: E402
from step3_filter import norm_street  # noqa: E402

URL = SERVICE.replace("Parcels/MapServer", "Documents/MapServer") + "/1"
OUT = "data/public_permits.csv"
FIELDS = ["permitnumber", "permittype", "permitaddress", "applicationdate",
          "issuedate", "ownername", "status"]


def iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date().isoformat() if ms else ""


def main():
    page = get_json(URL).get("maxRecordCount") or 1000
    total = get_json(URL + "/query", {"where": "1=1", "returnCountOnly": "true"})["count"]
    rows, offset = [], 0
    while offset < total:
        time.sleep(1)
        d = get_json(URL + "/query", {
            "where": "1=1", "outFields": ",".join(FIELDS), "returnGeometry": "false",
            "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": page,
        })
        feats = d.get("features", [])
        if not feats:
            break
        rows += [f["attributes"] for f in feats]
        offset += len(feats)
        print(f"  permits: {offset}/{total}", file=sys.stderr)

    os.makedirs("data", exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS + ["address_norm"])
        for r in rows:
            vals = [(" ".join(str(r.get(k) or "").split())) for k in FIELDS]
            vals[3], vals[4] = iso(r.get("applicationdate")), iso(r.get("issuedate"))
            w.writerow(vals + [norm_street(r.get("permitaddress"))])
    print(f"wrote {len(rows)} permits to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
