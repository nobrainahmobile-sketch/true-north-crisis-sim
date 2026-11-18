#!/usr/bin/env python3
"""STEP 1 - Discover what Bangor's public parcel service exposes.

Lists every field on the parcel layer (MapServer/0), every other layer/table in
the same service, and maps the fields we need for the roofing target list.
Writes a JSON report to data/step1_fields.json.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from arcgis import SERVICE, get_json  # noqa: E402

# What we need -> candidate field names (checked case-insensitively on every layer/table)
NEEDS = {
    "parcel ID": ["MAPLOTUNIT", "MAP_LOT", "TAX_ACCT", "RE_ACCT"],
    "site address": ["PROP_LOC"],
    "owner name": ["OWNER", "OWNER2"],
    "owner mailing address": ["OWN_ADD1", "OWN_ADD2"],
    "land use / property class": ["LAND_TYPE", "BLDG_TYPE", "OCCUPANCY", "USE_CODE", "LUC", "CLASS"],
    "year built": ["RES_YR_BLT", "COM_YR_BLT", "YR_BLT", "YEAR_BUILT"],
    "building style": ["BLDG_TYPE", "STYLE", "BLDG_STYLE"],
    "last sale date": ["SALE_DATE"],
    "last sale price": ["SALE_PRICE"],
    "roof type": ["ROOF", "ROOF_TYPE", "ROOF_COVER", "ROOF_MAT", "ROOFING"],
    "heating type": ["HEAT", "HEAT_TYPE", "HEATING", "FUEL", "HEAT_FUEL"],
}


def main():
    svc = get_json(SERVICE)
    layers = svc.get("layers", []) + svc.get("tables", [])
    report = {"service": SERVICE, "layers": {}}

    for L in layers:
        meta = get_json(f"{SERVICE}/{L['id']}")
        fields = [(f["name"], f["type"].replace("esriFieldType", ""), f.get("alias"))
                  for f in meta.get("fields", [])]
        report["layers"][L["id"]] = {
            "name": meta.get("name"), "type": meta.get("type"),
            "maxRecordCount": meta.get("maxRecordCount"),
            "capabilities": meta.get("capabilities"),
            "relationships": meta.get("relationships"),
            "fields": fields,
        }
        print(f"\n=== Layer {L['id']}: {meta.get('name')} ({meta.get('type')}), "
              f"maxRecordCount={meta.get('maxRecordCount')}, "
              f"relationships={meta.get('relationships') or 'none'}")
        for n, t, a in fields:
            print(f"   {n:<22}{t:<10}{a}")

    print("\n=== Coverage of required fields")
    coverage = {}
    for need, cands in NEEDS.items():
        hits = [f"layer {lid}.{n}"
                for lid, info in report["layers"].items()
                for n, _, _ in info["fields"]
                if n.upper() in cands]
        coverage[need] = hits
        print(f"   {need:<28}{', '.join(hits) if hits else 'MISSING'}")
    report["coverage"] = coverage

    os.makedirs("data", exist_ok=True)
    with open("data/step1_fields.json", "w") as fh:
        json.dump(report, fh, indent=1)
    print("\nwrote data/step1_fields.json")


if __name__ == "__main__":
    main()
