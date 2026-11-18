"""Small shared helper for polite requests to Bangor's ArcGIS REST service."""
import json
import time
import urllib.parse
import urllib.request

SERVICE = ("https://mapping.bangormaine.gov/server/rest/services/"
           "ParcelViewer/Parcels/MapServer")
USER_AGENT = "parcel-research-script/1.0"


def get_json(url, params=None, retries=4):
    q = urllib.parse.urlencode({**(params or {}), "f": "json"})
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(f"{url}: {d['error']}")
            return d
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
