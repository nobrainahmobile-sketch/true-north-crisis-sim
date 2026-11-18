#!/usr/bin/env python3
"""STEP 3 - Filter data/parcels_raw.csv to owner-occupied single-family homes and duplexes.

Rules (applied in order; the first rule a parcel fails is recorded as its reason):
  1. LAND_TYPE must be 'Residential'
  2. building type + unit count must be a single-family dwelling (1 unit) or a
     duplex (2 units) - see SINGLE_FAMILY_TYPES / DUPLEX_TYPES below
  3. owner is not a government body, nonprofit/religious org, bank/lender,
     or business entity (LLC, INC, ...)
  4. property is not fully tax-exempt
  5. owner-occupied: normalized owner mailing street address == normalized site
     address, and the mailing city is BANGOR

Outputs:
  data/step3_targets.csv   parcels that pass (all raw columns + normalized addresses
                           + homestead flag)
  data/step3_excluded.csv  every other parcel with the rule that excluded it
"""
import csv
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

RAW = "data/parcels_raw.csv"

# --- 1/2. property class -----------------------------------------------------
LAND_TYPES = {"Residential"}
DWELLING_TYPES = {  # the city's residential dwelling building types
    "2S Frame Dwlg", "1S Fr Dwelling", "1 1/2 S Fr Dwlg", "1S w/Attic Frame",
    "Split Level Fr.", "1S Ma Dwelling", "2S Msnry Dwlg", "1 1/2 S Msnry",
}
SINGLE_FAMILY = {(t, 1) for t in DWELLING_TYPES}
DUPLEX = {(t, 2) for t in DWELLING_TYPES} | {("Apartment Frame", 2), ("Apartment Msnry", 2)}

# --- 3. owner type (whole-word matches on the owner name) --------------------
OWNER_EXCLUDE = {
    "government": [r"\bCITY OF\b", r"\bTOWN OF\b", r"INHABITANTS", r"\bSTATE OF\b",
                   r"\bCOUNTY OF\b", r"UNITED STATES", r"\bUSA\b", r"HOUSING AUTHORITY",
                   r"\bSCHOOLS?\b",
                   r"SECRETARY OF", r"\bHUD\b", r"VETERANS AFFAIRS", r"MAINE STATE"],
    "nonprofit/religious": [r"\bCHURCH\b", r"\bPARISH\b", r"DIOCESE", r"CATHOLIC BISHOP",
                            r"\bMINISTR",
                            r"CONGREGATION", r"FOUNDATION", r"HABITAT FOR HUMANITY",
                            r"\bYMCA\b", r"\bYWCA\b", r"UNIVERSITY", r"COLLEGE",
                            r"HOSPITAL", r"SOCIETY", r"ASSOCIATION", r"\bASSN\b",
                            r"COMMUNITY", r"SHELTER", r"SERVICES"],
    "bank/lender": [r"\bBANK\b", r"CREDIT UNION", r"MORTGAGE", r"FEDERAL NATIONAL",
                    r"FEDERAL HOME LOAN", r"FANNIE", r"FREDDIE", r"SAVINGS",
                    r"\bLOAN\b", r"TRUST COMPANY", r"NATIONAL ASSOCIATION", r"\bN\.?A\.?$",
                    r"FINANCIAL", r"LENDING", r"SERVICING"],
    "business entity": [r"\bL\.?L\.?C\b", r"\bINC\b", r"\bINCORPORATED\b", r"\bCORP",
                        r"\bCOMPANY\b", r"\bCO\b$", r"\bL\.?P\b", r"\bLTD\b",
                        r"PROPERTIES", r"HOLDINGS", r"REALTY", r"INVESTMENT",
                        r"PARTNERS", r"ENTERPRISES", r"MANAGEMENT", r"RENTALS"],
}
OWNER_RX = {k: re.compile("|".join(v)) for k, v in OWNER_EXCLUDE.items()}

# --- 5. address normalization ------------------------------------------------
SUFFIX = {
    "STREET": "ST", "STR": "ST", "ROAD": "RD", "AVENUE": "AVE", "AV": "AVE",
    "DRIVE": "DR", "DRV": "DR", "LANE": "LN", "BOULEVARD": "BLVD", "COURT": "CT",
    "PLACE": "PL", "TERRACE": "TER", "TERR": "TER", "CIRCLE": "CIR", "PARKWAY": "PKWY",
    "HIGHWAY": "HWY", "EXTENSION": "EXT", "EXTN": "EXT", "HEIGHTS": "HTS",
    "SQUARE": "SQ", "TRAIL": "TRL", "POINT": "PT", "LANDING": "LNDG", "RIDGE": "RDG",
    "CROSSING": "XING", "MOUNT": "MT", "MOUNTAIN": "MTN", "HILL": "HL", "WAY": "WAY",
    "ROW": "ROW", "ALLEY": "ALY", "COMMONS": "CMNS", "PK": "PARK",
}
DIRECTION = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}
ORDINAL = {"FIRST": "1ST", "SECOND": "2ND", "THIRD": "3RD", "FOURTH": "4TH",
           "FIFTH": "5TH", "SIXTH": "6TH", "SEVENTH": "7TH", "EIGHTH": "8TH",
           "NINTH": "9TH", "TENTH": "10TH"}
UNIT_RX = re.compile(r"\s+(?:APT|APARTMENT|UNIT|STE|SUITE|#|NO)\.?\s*\S+$")


def norm_street(s):
    s = (s or "").upper().replace(".", " ").replace(",", " ")
    s = re.sub(r"^\s*C/O\b[^0-9]*(?=\d)", "", s)  # 'C/O JANE DOE 12 MAIN ST' -> '12 MAIN ST'
    s = UNIT_RX.sub("", " ".join(s.split()))
    out = []
    for w in s.split():
        w = SUFFIX.get(w, w)
        w = DIRECTION.get(w, w)
        w = ORDINAL.get(w, w)
        out.append(w)
    return " ".join(out)


def same_address_typo(site, mail):
    """Same house number and suffix, street name differs only by a typo
    (e.g. PARKVIEW / PARKVEIW, KENDUSKEAG / KENUSKEAG)."""
    a, b = site.split(), mail.split()
    if len(a) < 2 or len(a) != len(b) or a[0] != b[0] or not a[0][0].isdigit():
        return False
    if a[-1] != b[-1]:
        return False
    return SequenceMatcher(None, " ".join(a[1:]), " ".join(b[1:])).ratio() >= 0.85


def mail_city(add2):
    """'BANGOR ME 04401' -> 'BANGOR'."""
    m = re.match(r"\s*(.*?)\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$", (add2 or "").upper())
    return " ".join(m.group(1).split()) if m else ""


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def classify(r):
    if r["LAND_TYPE"] not in LAND_TYPES:
        return f"land type: {r['LAND_TYPE'] or 'blank'}", None
    key = (r["BLDG_TYPE"], int(num(r["RES_UNITS"])))
    if key in SINGLE_FAMILY:
        kind = "single-family"
    elif key in DUPLEX:
        kind = "duplex"
    else:
        return f"building: {key[0]} / {key[1]} units", None
    owner = f"{r['OWNER']} {r['OWNER2']}".upper()
    for label, rx in OWNER_RX.items():
        if rx.search(owner):
            return f"owner: {label}", None
    if num(r["EXEMPTION"]) > 0 and num(r["EXEMPTION"]) >= num(r["VALUE_TOT"]):
        return "fully tax-exempt", None
    site, mail = norm_street(r["PROP_LOC"]), norm_street(r["OWN_ADD1"])
    if mail.startswith("PO BOX") or mail.startswith("P O BOX"):
        return "not owner-occupied: PO box mailing", None
    if site != mail and not same_address_typo(site, mail):
        return "not owner-occupied: mailing address differs", None
    if mail_city(r["OWN_ADD2"]) != "BANGOR":
        return "not owner-occupied: mailing city not Bangor", None
    return None, kind


def main():
    with open(RAW, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    keep, drop = [], []
    for r in rows:
        reason, kind = classify(r)
        r["site_norm"] = norm_street(r["PROP_LOC"])
        r["mail_norm"] = norm_street(r["OWN_ADD1"])
        r["homestead_exempt"] = "Y" if num(r["EXEMPTION"]) >= 25000 and num(r["EXEMPTION"]) < num(r["VALUE_TOT"]) else ""
        if reason:
            r["exclude_reason"] = reason
            drop.append(r)
        else:
            r["home_type"] = kind
            keep.append(r)

    base = list(rows[0].keys())
    for path, data, extra in (("data/step3_targets.csv", keep, ["home_type"]),
                              ("data/step3_excluded.csv", drop, ["exclude_reason"])):
        cols = [c for c in base if c not in ("home_type", "exclude_reason")] + extra
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)

    print(f"input parcels: {len(rows)}")
    print("excluded by rule:")
    order = Counter()
    for r in drop:
        order[r["exclude_reason"].split(":")[0] + (":" + r["exclude_reason"].split(":")[1]
              if r["exclude_reason"].startswith(("owner", "not owner")) else "")] += 1
    for k, n in order.most_common():
        print(f"  {n:>6}  {k}")
    print(f"KEPT: {len(keep)}  ({Counter(r['home_type'] for r in keep)})")
    print("wrote data/step3_targets.csv and data/step3_excluded.csv", file=sys.stderr)


if __name__ == "__main__":
    main()
