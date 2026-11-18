#!/usr/bin/env python3
"""STEP 4 - Score each target home 0-12 for roof-replacement likelihood and write
a lean mailing list.

Inputs
  data/step3_targets.csv        owner-occupied single-family/duplex homes (step 3)
  data/tax_cards*.csv           parsed record cards (step 2b)      [optional]
  data/public_permits.csv       city's public permits 2014-Jan 2020 (step 2c) [optional]
  data/roof_permits.csv         roof permits: account,permit_year  [optional]
                                (a permit_date column in any common date format
                                also works; a missing file = "no permit data")

Scoring (max 12)
  1. Estimated roof age (max 5) - 0 if the record card shows a metal or slate roof
       with a roof permit on file: roof year = latest permit year
         age 25+ -> 5, 20-24 -> 4, 18-19 -> 3, under 18 -> 0
       no permit on file: roof year unknown, so use year built
         built 2001-2008 -> 4 (original roof now ~18-25 yrs: first replacement wave)
         built <= 2000   -> 2 (old house, may already have been re-roofed)
         built 2009+     -> 0
       Note: when a permits file IS supplied, "no permit on file" is still scored
       by year built, as above.
     Possible re-roof flag: if there is no roof permit but the city's public
     permits show a "CONST EXIS" (work on an existing building) permit issued
     after the home was built, roof-age points drop by 2 (not below 0) and the
     home is flagged "possible re-roof <year> - verify". Those permits have no
     work description, so most will be decks/windows/renovations, not roofs.
  2. Record-card building condition (max 3): Poor 3, Fair 2, Avg- 1
  3. Years owned, from last sale date (max 2): 15+ -> 2, 10-14 -> 1
  4. No remodel since 2008, homes built 2008 or earlier only (max 1)
  5. Building value above the target list's median (max 1)

Output: data/mailing_list.csv (or -o), sorted by score, highest first.
"""
import argparse
import csv
import datetime as dt
import glob
import os
import re
import statistics

THIS_YEAR = dt.date.today().year
CONDITION_PTS = {"Poor": 3, "Fair": 2, "Avg-": 1, "Avg Minus": 1, "Below Avg": 1}
OUT_COLS = [
    "account", "score", "priority", "why", "possible_reroof",
    "name_line1", "name_line2", "mail_address", "mail_city", "mail_state", "mail_zip",
    "property_address", "home_type",
    "year_built", "roof_year_source", "roof_surface", "condition", "owned_since", "year_remodeled",
    "mail_flag",
]


# ---------- helpers ----------------------------------------------------------
def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def load_cards():
    """Best (first dwelling) card per account from every data/tax_cards*.csv."""
    cards = {}
    for path in sorted(glob.glob("data/tax_cards*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("status") == "ok" and r["account"] not in cards:
                    cards[r["account"]] = r
    return cards


def load_permits(path):
    if not os.path.exists(path):
        return None
    latest = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            acct = str(to_int(r.get("account")))
            yr = to_int(r.get("permit_year"))
            if not yr:
                m = re.search(r"(19|20)\d\d", r.get("permit_date", ""))
                yr = int(m.group(0)) if m else 0
            if acct != "0" and yr:
                latest[acct] = max(latest.get(acct, 0), yr)
    return latest


def load_public_permits(path="data/public_permits.csv"):
    """normalized address -> latest 'CONST EXIS' issue year (2014-2020 only)."""
    if not os.path.exists(path):
        return {}
    latest = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            yr = to_int(r["issuedate"][:4])
            if r["permittype"] == "CONST EXIS" and yr and r["address_norm"]:
                latest[r["address_norm"]] = max(latest.get(r["address_norm"], 0), yr)
    return latest


def tc(word):
    w = word.capitalize()
    w = re.sub(r"(?<=[-'])([a-z])", lambda m: m.group(1).upper(), w)  # Smith-Dubuisson, O'Connell
    if re.match(r"Mc[a-z]", w):
        w = "Mc" + w[2].upper() + w[3:]
    if w.upper() in ("II", "III", "IV", "JR", "SR"):
        w = w.upper() if w.upper() not in ("JR", "SR") else w
    return w


def person_name(raw):
    """City formats -> mail name.
    'DYSART  ETHAN J'                 -> 'Ethan J Dysart'
    'PAULETTE, ROBERT S & MARLENE M'  -> 'Robert S & Marlene M Paulette'
    anything else (trusts etc.)       -> title-cased as written
    """
    raw = re.sub(r"\s+\bJT\b\s*$", "", (raw or "").strip(), flags=re.I)  # joint tenant marker
    raw = re.sub(r"\s*\bDTD\b\s*[\d/]+", "", raw, flags=re.I)              # trust dates
    raw = " ".join(raw.replace("  ", "|").split()).strip()
    if not raw:
        return ""
    if re.search(r"TRUST|ESTATE|HEIRS|PER REP|\bDTD\b", raw, re.I):
        return " ".join(tc(w) for w in raw.replace("|", " ").split())
    if "|" in raw:
        last, first = raw.split("|", 1)
    elif "," in raw:
        last, first = raw.split(",", 1)
    else:
        m = re.match(r"(\S+ (?:JR|SR|II|III|IV))\s+(.+)$", raw, re.I)  # 'SPEIRS III GARRETT D'
        if not m:
            return " ".join(tc(w) for w in raw.split())
        last, first = m.groups()
    return " ".join(tc(w) for w in (first.strip() + " " + last.strip()).split())


def split_city(add2):
    m = re.match(r"\s*(.*?)\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$", (add2 or "").upper())
    return (m.group(1), m.group(2), m.group(3)) if m else ((add2 or "").strip(), "", "")


# ---------- scoring ----------------------------------------------------------
def score(r, card, permits, median_bldg, public_permits):
    pts, why = 0, []
    built = to_int(r["RES_YR_BLT"])

    # 1. roof age
    surface = (card or {}).get("roof_surface", "")
    long_life = re.search(r"Metal|Slate", surface, re.I)
    permit_yr = permits.get(r["RE_ACCT"]) if permits else None
    if permit_yr:
        age = THIS_YEAR - permit_yr
        p = 5 if age >= 25 else 4 if age >= 20 else 3 if age >= 18 else 0
        src = f"roof permit {permit_yr}"
        why.append(f"roof permit {permit_yr} ({age} yrs)")
    else:
        src = "year built (no permit data)" if permits is None else "year built (no permit on file)"
        if 2001 <= built <= 2008:
            p = 4
            why.append(f"built {built}: likely original roof ~{THIS_YEAR - built} yrs")
        elif 0 < built <= 2000:
            p = 2
            why.append(f"built {built}: roof age unknown")
        else:
            p = 0
            why.append(f"built {built or '?'}: newer home" if built else "year built unknown")
    reroof = ""
    pub_yr = public_permits.get(r.get("site_norm", ""))
    if not permit_yr and pub_yr and pub_yr > built and p:
        reroof = str(pub_yr)
        p = max(p - 2, 0)
        why.append(f"possible re-roof {pub_yr} (existing-bldg permit) - verify")
    if long_life and p:
        p = 0
        why.append(f"{surface.lower()} (40+ yr roof): no roof-age points")
    pts += p

    # 2. condition (record card)
    cond = (card or {}).get("condition", "")
    c = CONDITION_PTS.get(cond, 0)
    if c:
        why.append(f"condition {cond}")
    pts += c

    # 3. years owned
    sale = r.get("SALE_DATE") or ""
    since = to_int(sale[:4]) if sale else 0
    if since < 1900:  # city uses 1899-12-30 as a "no sale on record" placeholder
        since = 0
    if since:
        owned = THIS_YEAR - since
        o = 2 if owned >= 15 else 1 if owned >= 10 else 0
        if o:
            why.append(f"owned {owned} yrs")
        pts += o

    # 4. no remodel since 2008
    rmd = to_int(r["RES_YR_RMD"])
    if rmd < 2008:
        if 0 < built <= 2008:  # only meaningful for homes old enough to need a roof
            pts += 1
    else:
        why.append(f"remodeled {rmd}")

    # 5. building value
    if to_int(r["VALUE_BLDG"]) > median_bldg:
        pts += 1

    return pts, "; ".join(why), src, cond, since, rmd, reroof


def mail_flag(r):
    text = f"{r['OWNER']} {r['OWNER2']}".upper()
    flags = []
    if re.search(r"HEIRS|PER REP|ESTATE OF|DECEASED", text):
        flags.append("estate/heirs - owner may be deceased")
    if "TRUST" in text:
        flags.append("trust-owned")
    if r.get("occupancy_basis") == "homestead exemption":
        flags.append("mail goes to non-property address")
    return "; ".join(flags)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts-file", help="only score these accounts (whitespace-separated)")
    ap.add_argument("--permits", default="data/roof_permits.csv")
    ap.add_argument("-o", "--output", default="data/mailing_list.csv")
    a = ap.parse_args()

    with open("data/step3_targets.csv", newline="", encoding="utf-8") as fh:
        targets = list(csv.DictReader(fh))
    median_bldg = statistics.median(to_int(r["VALUE_BLDG"]) for r in targets)
    if a.accounts_file:
        keep = set(open(a.accounts_file).read().split())
        targets = [r for r in targets if r["RE_ACCT"] in keep]

    cards = load_cards()
    permits = load_permits(a.permits)
    public_permits = load_public_permits()

    out = []
    for r in targets:
        pts, why, src, cond, since, rmd, reroof = score(
            r, cards.get(r["RE_ACCT"]), permits, median_bldg, public_permits)
        city, state, zp = split_city(r["OWN_ADD2"])
        n1, n2 = person_name(r["OWNER"]), person_name(r["OWNER2"])
        out.append({
            "account": r["RE_ACCT"], "score": pts,
            "priority": "A" if pts >= 8 else "B" if pts >= 5 else "C",
            "why": why, "possible_reroof": reroof,
            "name_line1": n1, "name_line2": "" if n2 == n1 else n2,
            "mail_address": " ".join(r["OWN_ADD1"].upper().split()),
            "mail_city": city, "mail_state": state, "mail_zip": zp,
            "property_address": r["PROP_LOC"], "home_type": r["home_type"],
            "year_built": r["RES_YR_BLT"], "roof_year_source": src,
            "roof_surface": (cards.get(r["RE_ACCT"]) or {}).get("roof_surface", ""),
            "condition": cond or ("no card" if r["RE_ACCT"] not in cards else ""),
            "owned_since": since or "", "year_remodeled": rmd or "",
            "mail_flag": mail_flag(r),
        })
    out.sort(key=lambda x: (-x["score"], int(x["account"])))

    os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
    with open(a.output, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, OUT_COLS)
        w.writeheader()
        w.writerows(out)
    print(f"scored {len(out)} homes -> {a.output} "
          f"(permit data: {'none' if permits is None else len(permits)} accounts; "
          f"cards: {sum(1 for x in out if x['condition'] != 'no card')}; "
          f"median building value ${median_bldg:,.0f})")


if __name__ == "__main__":
    main()
