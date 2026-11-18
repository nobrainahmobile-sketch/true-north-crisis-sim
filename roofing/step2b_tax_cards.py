#!/usr/bin/env python3
"""STEP 2b - Download and parse Bangor property record cards (tax card PDFs).

The GIS service has no roof or heating fields, but each parcel's TaxCardURL
points to a PDF record card that does. This script fetches those PDFs slowly
(at most 1 request every 2 seconds), caches them in data/taxcards/, and parses
the building page(s) with `pdftotext -layout`.

Output: data/tax_cards.csv, one row per building card. Values the card does not
show are left blank - nothing is inferred.

Usage:
  python3 roofing/step2b_tax_cards.py --sample 10       # test run on 10 parcels
  python3 roofing/step2b_tax_cards.py --accounts 3525 518
  python3 roofing/step2b_tax_cards.py                   # every parcel with a card URL
"""
import argparse
import csv
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from arcgis import USER_AGENT  # noqa: E402

RAW = "data/parcels_raw.csv"
CACHE = "data/taxcards"
MIN_INTERVAL = 2.0

# label on the card -> output column. Each is "<label> <code> <description>".
CODED = {
    "Building Style": "building_style",
    "Stories": "stories",
    "Exterior Walls": "exterior_walls",
    "Roof Surface": "roof_surface",
    "Heat Type": "heat_type",
    "Cool Type": "cool_type",
    "Condition": "condition",
    "Grade & Factor": "grade",
    "Foundation": "foundation",
    "Basement": "basement",
    "Zone/Land Use": "zone_land_use",
}
PLAIN = {
    "Dwelling Units": "dwelling_units",
    "Year Built": "year_built",
    "Year Remodeled": "year_remodeled",
    "SQFT \\(Footprint\\)": "sqft_footprint",
    "Date Inspected": "date_inspected",
}
COLUMNS = (["account", "card", "of_cards", "status", "heat_pct"]
           + list(CODED.values()) + list(PLAIN.values()))

_last = [0.0]


def fetch_pdf(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return "cached"
    wait = MIN_INTERVAL - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
        if not body.startswith(b"%PDF"):
            return "not_pdf"
        with open(path + ".part", "wb") as fh:
            fh.write(body)
        os.replace(path + ".part", path)
        return "downloaded"
    except Exception as e:
        return f"error: {e}"
    finally:
        _last[0] = time.monotonic()


def coded(page, label):
    """'Roof Surface 1 Asphalt Shingles   ...' -> 'Asphalt Shingles' (code dropped)."""
    m = re.search(rf"{label}[ \t]+(?:\d+%[ \t]+)?(\d+)[ \t]+(\S.*?)(?:[ \t]{{2,}}|[ \t]+\d+\.|$)",
                  page, re.M)
    return m.group(2).strip() if m else ""


def plain(page, label):
    m = re.search(rf"{label}[ \t]+(\d[\d/]*)(?=[ \t]|$)", page, re.M)
    return m.group(1) if m else ""


def parse(pdf_path, account):
    text = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                          capture_output=True, text=True, check=True).stdout
    pages = text.split("\f")
    first = pages[0]
    zone = coded(first, "Zone/Land Use")
    rows = []
    for page in pages:
        if "Roof Surface" not in page and "Building Style" not in page:
            continue
        card = re.search(r"Card\s+(\d+)\s+Of\s+(\d+)", page)
        row = {"account": account, "status": "ok",
               "card": card.group(1) if card else "", "of_cards": card.group(2) if card else ""}
        for label, col in CODED.items():
            row[col] = coded(page, label)
        row["zone_land_use"] = zone
        hp = re.search(r"Heat Type[ \t]+(\d+)%", page)
        row["heat_pct"] = hp.group(1) if hp else ""
        for label, col in PLAIN.items():
            row[col] = plain(page, label)
        if not (row["building_style"] or row["year_built"] or row["roof_surface"]):
            row["status"] = "no_dwelling"  # e.g. outbuilding-only card
        rows.append(row)
    if not rows:  # land-only card: no building page
        rows.append({"account": account, "status": "no_building_page", "zone_land_use": zone})
    return rows


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sample", type=int, help="random residential sample of N parcels")
    g.add_argument("--accounts", nargs="+", help="specific account numbers")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("-o", "--output", default="data/tax_cards.csv")
    a = ap.parse_args()

    with open(RAW, newline="", encoding="utf-8") as fh:
        parcels = [r for r in csv.DictReader(fh) if r["TaxCardURL"]]
    if a.accounts:
        parcels = [r for r in parcels if r["RE_ACCT"] in set(a.accounts)]
    elif a.sample:
        res = [r for r in parcels if r["LAND_TYPE"] == "Residential"]
        parcels = random.Random(a.seed).sample(res, a.sample)

    os.makedirs(CACHE, exist_ok=True)
    out = []
    for i, p in enumerate(parcels, 1):
        acct = p["RE_ACCT"]
        path = os.path.join(CACHE, f"{acct}.pdf")
        status = fetch_pdf(p["TaxCardURL"], path)
        if status in ("cached", "downloaded"):
            try:
                out += parse(path, acct)
            except Exception as e:
                out.append({"account": acct, "status": f"parse_error: {e}"})
        else:
            out.append({"account": acct, "status": status})
        if i % 50 == 0 or i == len(parcels):
            print(f"  {i}/{len(parcels)} cards", file=sys.stderr)

    with open(a.output, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, COLUMNS)
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} rows to {a.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
