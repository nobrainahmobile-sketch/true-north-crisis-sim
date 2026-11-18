#!/usr/bin/env python3
"""STEP 2 - Download every parcel record and save data/parcels_raw.csv.

Pulls, with paging (resultOffset, page size = service maxRecordCount) and a
1-second pause between requests:
  * layer 0  Parcels                (parcel polygons: MAPLOTUNIT, TaxCardURL, area)
  * table 2  Parcel_Assessing_Data  (owner mailing address, year built, sale, class)
and joins them on account number (layer0.TAX_ACCT = table2.RE_ACCT).

One output row per assessing-table record (account + card). Nothing is filtered
here; all values are passed through as the city publishes them, except that
SALE_DATE (epoch ms) is converted to YYYY-MM-DD.
"""
import csv
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from arcgis import SERVICE, get_json  # noqa: E402

PAUSE = 1.0
OUT = "data/parcels_raw.csv"
LAYER0_FIELDS = ["TAX_ACCT", "MAPLOTUNIT", "TaxCardURL", "AreaSqFt", "Plan_Name"]
_last = [0.0]


def polite_get(url, params=None):
    wait = PAUSE - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    try:
        return get_json(url, params)
    finally:
        _last[0] = time.monotonic()


def download(layer_id, out_fields="*"):
    url = f"{SERVICE}/{layer_id}"
    meta = polite_get(url)
    page = meta.get("maxRecordCount") or 1000
    total = polite_get(f"{url}/query", {"where": "1=1", "returnCountOnly": "true"})["count"]
    rows, offset = [], 0
    while offset < total:
        d = polite_get(f"{url}/query", {
            "where": "1=1", "outFields": out_fields, "returnGeometry": "false",
            "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": page,
        })
        feats = d.get("features", [])
        if not feats:
            break
        rows += [f["attributes"] for f in feats]
        offset += len(feats)
        print(f"  layer {layer_id} ({meta.get('name')}): {offset}/{total}", file=sys.stderr)
    if len(rows) != total:
        sys.exit(f"layer {layer_id}: got {len(rows)} rows, service reports {total}")
    return rows


def main():
    parcels = download(0, ",".join(LAYER0_FIELDS))
    assess = download(2)

    # layer 0 can hold several polygons per account; keep first, count the rest
    by_acct = {}
    for p in parcels:
        if p["TAX_ACCT"] is None:
            continue
        acct = int(p["TAX_ACCT"])
        if acct in by_acct:
            by_acct[acct]["polygon_count"] += 1
        else:
            by_acct[acct] = {**p, "polygon_count": 1}

    a_fields = [k for k in assess[0] if k not in ("OBJECTID", "GlobalID")]
    p_fields = ["MAPLOTUNIT", "TaxCardURL", "AreaSqFt", "Plan_Name", "polygon_count"]
    os.makedirs("data", exist_ok=True)
    unmatched = 0
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(a_fields + p_fields)
        for r in sorted(assess, key=lambda r: (r["RE_ACCT"] or 0, r["CARD"] or 0)):
            if r.get("SALE_DATE"):
                r["SALE_DATE"] = dt.datetime.fromtimestamp(
                    r["SALE_DATE"] / 1000, dt.timezone.utc).date().isoformat()
            p = by_acct.get(r["RE_ACCT"])
            unmatched += p is None
            w.writerow([r.get(k) for k in a_fields] +
                       [(p or {}).get(k) for k in p_fields])
    print(f"wrote {len(assess)} rows to {OUT} "
          f"({unmatched} assessing records with no parcel polygon)", file=sys.stderr)


if __name__ == "__main__":
    main()
