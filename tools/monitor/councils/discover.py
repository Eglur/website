#!/usr/bin/env python3
"""Find which UK councils publish meetings through ModernGov, and where.

For every current council in mySociety's register (uk_local_authorities.csv), look up its website on
GOV.UK, try the usual ModernGov addresses, and keep the first that answers mgWebService GetCommittees.
Writes councils.json: {gss_code: {"name", "url", "nation", "type"}}. Run on GitHub Actions (needs open internet):
  python tools/monitor/councils/discover.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
UA = "EglurMonitor/1.0 (+https://www.eglurtech.com/monitor/; council discovery)"
SUBDOMAINS = ["democracy", "moderngov", "mgenglish", "committees", "councillors", "meetings", "mg", "modgov",
              "democraticservices", "decisions", "decisionmaking", "cmis", "minutes", "council", "public", "www",
              "mycouncil", "minutes1", "minutes2", "minutes3", "democratic", "moderngovwebpublic", "cmttpublic",
              "councilmeetings", "governance", "mgov", "modgovwebsite", "moderngovpublic", "democracy-cymraeg"]
# Councils GOV.UK has no homepage for (newer unitaries and renamed slugs).
HOMEPAGES = {
    "Bournemouth, Christchurch and Poole": "https://www.bcpcouncil.gov.uk", "Buckinghamshire": "https://www.buckinghamshire.gov.uk",
    "Cumberland": "https://www.cumberland.gov.uk", "Dorset Council": "https://www.dorsetcouncil.gov.uk",
    "East Suffolk": "https://www.eastsuffolk.gov.uk", "Folkestone and Hythe": "https://www.folkestone-hythe.gov.uk",
    "North Northamptonshire": "https://www.northnorthants.gov.uk", "North Yorkshire": "https://www.northyorks.gov.uk",
    "Somerset": "https://www.somerset.gov.uk", "St. Helens": "https://www.sthelens.gov.uk",
    "West Northamptonshire": "https://www.westnorthants.gov.uk", "West Suffolk": "https://www.westsuffolk.gov.uk",
    "Westmorland and Furness": "https://www.westmorlandandfurness.gov.uk",
}
PATHS = ["", "/moderngov", "/mgov", "/democracy"]


def get(url: str, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(400_000).decode("utf-8", "replace")
    except Exception:
        return 0, ""


def is_moderngov(base: str) -> bool:
    status, body = get(base + "/mgWebService.asmx/GetCommittees?lCommitteeType=0")
    return status == 200 and "<committee" in body.lower()


def homepage(slug: str) -> str:
    status, body = get(f"https://www.gov.uk/api/local-authority/{slug}")
    if status != 200:
        return ""
    try:
        return json.loads(body)["local_authority"]["homepage_url"]
    except (ValueError, KeyError):
        return ""


def candidates(home: str, slug: str) -> list[str]:
    host = urllib.parse.urlparse(home).netloc.lower()
    domain = re.sub(r"^www\.", "", host)
    first = domain.split(".")[0]
    out = [f"https://{sub}.{domain}{p}" for sub in SUBDOMAINS for p in (PATHS if sub == "www" else [""])]
    out += [f"https://{domain}{p}" for p in PATHS[1:]]
    out += [f"https://{name}.moderngov.co.uk" for name in dict.fromkeys([first, slug.replace("-", "")])]
    return list(dict.fromkeys(out))


def discover(row: dict) -> tuple[str, dict | None, str]:
    slug, name = row["gov-uk-slug"], row["nice-name"]
    home = HOMEPAGES.get(name) or (homepage(slug) if slug else "")
    if not home:
        return row["gss-code"], None, f"{name}: no GOV.UK homepage"
    for base in candidates(home, slug):
        if is_moderngov(base):
            return row["gss-code"], {"name": name, "url": base, "nation": row["nation"], "type": row["local-authority-type"]}, f"{name}: {base}"
    return row["gss-code"], None, f"{name}: not ModernGov ({home})"


def main() -> None:
    rows = [r for r in csv.DictReader(open(HERE / "uk_local_authorities.csv", encoding="utf-8"))
            if r["current-authority"] == "True" and r["gss-code"] and r["local-authority-type"] not in ("COMB", "SRA")]
    try:   # keep what earlier runs found; only look again for the rest
        found = json.loads((HERE / "councils.json").read_text())
    except (OSError, ValueError):
        found = {}
    total = len(rows)
    rows = [r for r in rows if r["gss-code"] not in found]
    print(f"{len(rows)} of {total} councils to check", file=sys.stderr)
    missing = []
    with ThreadPoolExecutor(max_workers=24) as pool:
        for gss, hit, note in pool.map(discover, rows):
            print(note, file=sys.stderr)
            if hit:
                found[gss] = hit
            else:
                missing.append(note)
    (HERE / "councils.json").write_text(json.dumps(dict(sorted(found.items())), indent=1, ensure_ascii=False) + "\n")
    (HERE / "not_found.txt").write_text("\n".join(sorted(missing)) + "\n")
    print(f"ModernGov: {len(found)} of {total}", file=sys.stderr)


if __name__ == "__main__":
    main()
