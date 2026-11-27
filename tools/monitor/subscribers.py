#!/usr/bin/env python3
"""Eglur Daily: one personal briefing per subscriber.

Reads active subscribers from the sign-up sheet (via its Apps Script), works out each
person's council and constituency from their postcode, collects official business once,
ranks it for each person and sends them a short email through the same script.

Usage (from the website repo root):
  python tools/monitor/subscribers.py --dry-run          # build emails into daily-email/preview, send nothing
  python tools/monitor/subscribers.py --only you@x.com   # send to one subscriber only
  python tools/monitor/subscribers.py                    # send to everyone due today

Needs SUBSCRIBERS_URL, SUBSCRIBERS_TOKEN and ANTHROPIC_API_KEY in the environment.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import monitor  # noqa: E402

# ModernGov council sites we can read. Add councils here as they're checked.
COUNCIL_SITES = {
    "Pembrokeshire": "https://mgenglish.pembrokeshire.gov.uk",
    "Ceredigion": "https://council.ceredigion.gov.uk",
}

TOPIC_KEYWORDS = {
    "Planning": ["planning", "planning application*", "development management", "local development plan"],
    "Schools": ["school*", "pupil*", "teacher*", "education"],
    "Health and the NHS": ["NHS", "hospital*", "GP", "health board", "dentist*", "dental", "ambulance*", "A&E"],
    "Transport and roads": ["transport", "road*", "bus", "buses", "rail", "railway*", "train*", "station*", "pothole*", "speed limit*"],
    "Housing": ["housing", "homes", "homeless*", "tenant*", "affordable home*", "second home*"],
    "Environment": ["environment*", "sewage", "water quality", "flood*", "climate", "pollution", "nature", "biodiversity"],
    "Farming": ["farm*", "agricultur*", "livestock", "bovine TB", "sustainable farming"],
    "Business and jobs": ["business*", "jobs", "employment", "high street*", "town centre*", "economy"],
    "Council tax and budgets": ["council tax", "budget*", "precept", "funding settlement"],
    "Welsh language": ["Welsh language", "Cymraeg", "Welsh-medium"],
    "Culture and sport": ["culture", "sport*", "arts", "museum*", "librar*", "tourism", "leisure"],
    "Social care": ["social care", "care home*", "carer*", "domiciliary"],
}

SYSTEM = """You write a personal civic briefing for a member of the public in the UK.
You read official updates from their council, their devolved parliament (if any) and Westminster, and keep only what
genuinely touches where they live or what they follow. Be strict: a short email is a good email.
Write plainly for a non-expert. "summary": one sentence on what happened. "why": one sentence
starting "You" or naming their place or interest, on why it matters to them. "action": only when
there's a real, practical step (comment on a planning application, watch a meeting, contact a
representative); otherwise empty. Never tell them what to think or how to vote, never favour a party,
and never state anything that is not in the item text. Leave "post" and "link" empty. British English."""

POSTCODE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$", re.I)
UA = monitor.UA


# ------------------------------------------------------------- subscribers

def sheet_request(params: dict | None = None, body: dict | None = None) -> dict:
    url = os.environ["SUBSCRIBERS_URL"] + "?" + urllib.parse.urlencode({"token": os.environ["SUBSCRIBERS_TOKEN"], **(params or {})})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8", "replace")
    try:
        return json.loads(text)
    except ValueError:
        return {"ok": False, "error": f"unexpected reply: {text[:120]}"}


def mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}…@{domain}"


def due_today(sub: dict, today: dt.date) -> bool:
    return sub.get("frequency") != "weekly" or today.weekday() == 4   # weekly ones go out on Fridays


# ---------------------------------------------------------------- geography

def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def locate(area: str) -> dict:
    """Postcode or place name -> council area, constituency and country (postcodes.io, free and open)."""
    area = (area or "").strip()
    geo = {"area": area, "council": "", "constituency": "", "country": ""}
    try:
        m = POSTCODE.match(area)
        if m:
            r = get_json("https://api.postcodes.io/postcodes/" + urllib.parse.quote(f"{m.group(1)} {m.group(2)}"))["result"]
            geo.update(council=r.get("admin_district") or "", country=r.get("country") or "",
                       constituency=r.get("parliamentary_constituency_2024") or r.get("parliamentary_constituency") or "")
        elif area:
            res = get_json("https://api.postcodes.io/places?" + urllib.parse.urlencode({"q": area, "limit": 1})).get("result") or []
            if res:
                geo.update(council=res[0].get("county_unitary") or res[0].get("district_borough") or "",
                           country=res[0].get("country") or "")
    except Exception as e:  # a lookup failure just means less local targeting
        print(f"  location lookup failed for an area: {e}", file=sys.stderr)
    return geo


# ------------------------------------------------------------------ profile

def split_list(s: str, on_and: bool = True) -> list[str]:
    pattern = r"[,;\n]| and " if on_and else r"[,;\n]"
    return [x.strip() for x in re.split(pattern, s or "") if len(x.strip()) >= 3]


TITLES = re.compile(r"^(cllr\.?|councillor|sir|dame|dr\.?|lord|baroness|rt hon)\s+|\s+(ms|mp|mbe|obe|cbe|ks|kc)$", re.I)


def person_name(s: str) -> str:
    """'Cllr Jane Smith' / 'Paul Davies MS' -> the name as it appears in records."""
    prev = None
    while prev != s:
        prev, s = s, TITLES.sub("", s.strip())
    return s


def build_profile(sub: dict, geo: dict) -> dict:
    topics = split_list(sub.get("topics", ""), on_and=False) + split_list(sub.get("topics_other", ""), on_and=False)
    places = split_list(sub.get("places", ""))
    people = [person_name(p) for p in split_list(sub.get("people", ""))]
    keywords: list[str] = []
    for t in topics:
        keywords += TOPIC_KEYWORDS.get(t, [t])
    for p in places + people:
        keywords.append(p)
    for k in (geo.get("council"), geo.get("constituency")):
        if k:
            keywords.append(k)
    area = geo.get("area", "")
    if area and not POSTCODE.match(area.replace(" ", "")):
        keywords.append(area)
    where = ", ".join(x for x in (area, f"{geo['council']} council area" if geo.get("council") else "",
                                  f"Westminster constituency {geo['constituency']}" if geo.get("constituency") else "",
                                  geo.get("country")) if x)
    description = (f"A member of the public living in {where or 'the UK'}.\n"
                   f"Topics they follow: {', '.join(topics) or 'none given'}.\n"
                   f"Other places they follow: {', '.join(places) or 'none'}.\n"
                   f"People they follow: {', '.join(people) or 'none'}.\n"
                   "Council items are from their own council. Devolved-parliament items are from the parliament for where they live.")
    return {
        "office": {"name": "Eglur Daily", "description": description},
        "filter": {"keywords": list(dict.fromkeys(keywords)), "max_items": 60, "min_score": 6},
        "model": {"name": os.environ.get("BRIEFING_MODEL", "claude-sonnet-5-5")},
        "member": {"social_drafts": False},
    }


# -------------------------------------------------------------------- email

LEVEL = {"council": ("Council", "#8A6A3B"), "senedd": ("Senedd", "#2F6690"), "holyrood": ("Holyrood", "#2F6690"),
         "stormont": ("Stormont", "#2F6690"), "commons": ("Westminster", "#3F7F5F"), "lords": ("Westminster", "#3F7F5F")}
NATION_HOUSE = {nation: house for house, (_, nation) in monitor.DEVOLVED.items()}   # "Wales" -> "senedd"


def esc(s) -> str:
    return html.escape(str(s or ""))


def where_label(it: dict) -> str:
    c = monitor.chamber(it)
    if c == "council":
        return f"{it.get('council', '')} Council".strip()
    if c in monitor.DEVOLVED:
        return monitor.DEVOLVED[c][0]
    return "Westminster, House of Lords" if c == "lords" else "Westminster, House of Commons"


def email_item(it: dict) -> str:
    colour = LEVEL[monitor.chamber(it)][1]
    when = monitor.when_label(it) if it.get("upcoming") else ""
    meta = where_label(it) + (f" &middot; {esc(when)}" if when else "")
    why = f'<p style="margin:8px 0 0;font-size:15px;line-height:1.5;color:#1E5153">{esc(it["why"])}</p>' if it.get("why") else ""
    action = (f'<p style="margin:8px 0 0;font-size:14px;line-height:1.5;color:#7A5410"><b>You could:</b> {esc(it["action"])}</p>'
              if it.get("action") else "")
    return (f'<tr><td style="padding:18px 0;border-top:1px solid #E3E8E6">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td width="3" style="background:{colour};border-radius:3px"></td><td style="padding-left:16px">'
            f'<p style="margin:0;font-size:12px;font-weight:bold;color:{colour}">{meta}</p>'
            f'<p style="margin:4px 0 0;font-size:17px;line-height:1.35;font-weight:bold"><a href="{esc(it["url"])}" style="color:#101A1A;text-decoration:none">{esc(it["title"])}</a></p>'
            f'<p style="margin:6px 0 0;font-size:15px;line-height:1.55;color:#3D4A49">{esc(it["summary"])}</p>{why}{action}'
            f'<p style="margin:8px 0 0;font-size:13px"><a href="{esc(it["url"])}" style="color:#5F6B6A">Official record</a></p>'
            f'</td></tr></table></td></tr>')


def section(title: str, items: list[dict]) -> str:
    if not items:
        return ""
    rows = "".join(email_item(i) for i in items)
    return (f'<p style="margin:28px 0 0;font-family:\'DM Serif Display\',Georgia,serif;font-size:22px;color:#101A1A">{esc(title)}</p>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>')


def subject_line(items: list[dict]) -> str:
    first = items[0]["title"].rstrip(".…")
    first = first if len(first) <= 60 else first[:57].rsplit(" ", 1)[0] + "…"
    return first if len(items) == 1 else f"{first}, and {len(items) - 1} more"


def render_email(items: list[dict], sub: dict, geo: dict, today: dt.date) -> tuple[str, str, str]:
    keep = sorted(items, key=lambda i: (-i["score"], i["title"]))
    ahead = sorted([i for i in keep if i.get("upcoming")], key=lambda i: (i["date"], i.get("time", "")))
    now = [i for i in keep if not i.get("upcoming")]
    n = len(keep)
    day = f"{today:%A} {today.day} {today:%B}"
    headline = f"{n} thing{'s' if n != 1 else ''} for you today" if sub.get("frequency") != "weekly" else f"Your week: {n} thing{'s' if n != 1 else ''} for you"
    place = geo.get("council") or geo.get("area") or ""
    sub_line = f"From {levels(geo)}{f', for {place}' if place else ''}."
    body = (f'<p style="margin:0;font-size:14px;color:#5F6B6A">{esc(day)}</p>'
            f'<h1 style="margin:6px 0 6px;font-family:\'DM Serif Display\',Georgia,serif;font-weight:400;font-size:34px;line-height:1.08;color:#101A1A">'
            f'{esc(headline)}<span style="color:#286A6C">.</span></h1>'
            f'<p style="margin:0;font-size:15px;color:#3D4A49">{esc(sub_line)}</p>'
            + section("Today", now) + section("Coming up", ahead) +
            '<p style="margin:30px 0 0;font-size:13px;line-height:1.6;color:#5F6B6A">Summaries are written by AI and can be wrong, so every item links to the official record. '
            'Reply to this email to change what you follow.</p>')
    council_note = ""
    if geo.get("council") and geo["council"] not in COUNCIL_SITES:
        council_note = (f'<p style="margin:10px 0 0;font-size:13px;line-height:1.6;color:#5F6B6A">Coverage of {esc(geo["council"])} Council is coming soon. '
                        f'For now your briefing covers {esc(levels(geo, council=False))}.</p>')
    html_doc = frame(body + council_note, f"{subject_line(keep)}" if keep else "Your briefing")
    text = "\n".join([f"{day}: {headline}.", ""] + [
        f"- {where_label(i)}: {i['title']}\n  {i['summary']}\n  {i.get('why', '')}\n  {i['url']}" for i in keep
    ] + ["", "Reply to change what you follow. Unsubscribe: {{UNSUBSCRIBE}}"])
    return subject_line(keep), html_doc, text


def frame(inner: str, preheader: str) -> str:
    return ('<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="color-scheme" content="light"><link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&display=swap" rel="stylesheet"></head>'
            '<body style="margin:0;padding:0;background:#F1F6F5">'
            f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{esc(preheader)}</div>'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1F6F5"><tr><td align="center" style="padding:32px 14px">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px">'
            '<tr><td style="padding:0 6px 22px"><span style="font-family:\'DM Serif Display\',Georgia,serif;font-size:26px;line-height:1;color:#101A1A">eglur<span style="color:#286A6C">.</span></span></td></tr>'
            f'<tr><td style="background:#FFFFFF;border-radius:16px;padding:36px 34px;font-family:Arial,Helvetica,sans-serif">{inner}</td></tr>'
            '<tr><td style="padding:22px 6px;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.6;color:#5F6B6A">'
            'Eglur Technologies. Eglur is Welsh for clear.<br>Built from official records published by UK Parliament (Open Parliament Licence), '
            'the Senedd, the Scottish Parliament, the Northern Ireland Assembly and councils under their open licences. <a href="{{UNSUBSCRIBE}}" style="color:#5F6B6A">Unsubscribe</a></td></tr>'
            '</table></td></tr></table></body></html>')


# --------------------------------------------------------------------- main

def collect_all(subs_geo: list[tuple[dict, dict]], today: dt.date, days: int) -> list[dict]:
    monitor.OUT = Path("daily-email")
    monitor.OUT.mkdir(exist_ok=True)
    monitor.load_state()
    monitor.COUNCILS[:] = [{"name": c, "url": COUNCIL_SITES[c]} for c in sorted({g["council"] for _, g in subs_geo if g.get("council") in COUNCIL_SITES})]
    profile = {"sources": {k: True for k in monitor.SOURCES}}
    since = (today - dt.timedelta(days=days)).isoformat()
    items = monitor.collect(profile, since, today.isoformat())
    (monitor.OUT / "state.json").write_text(json.dumps(monitor.STATE, indent=0) + "\n")
    return items


def relevant_place(it: dict, geo: dict) -> bool:
    """Council items only from their own council; devolved items only from their own nation's parliament."""
    c = monitor.chamber(it)
    if c == "council":
        return it.get("council") == geo.get("council")
    if c in monitor.DEVOLVED:
        return NATION_HOUSE.get(geo.get("country", "")) == c
    return True


def levels(geo: dict, council: bool = True) -> str:
    house = NATION_HOUSE.get(geo.get("country", ""))
    parts = (["your council"] if council else []) + (["the " + monitor.DEVOLVED[house][0]] if house else []) + ["Westminster"]
    return ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]


def for_subscriber(items: list[dict], sub: dict, geo: dict, use_ai: bool) -> list[dict]:
    prof = build_profile(sub, geo)
    mine = [i for i in items if relevant_place(i, geo)]
    shortlist = monitor.prefilter(copy.deepcopy(mine), prof["filter"]["keywords"], prof["filter"]["max_items"])
    if not shortlist:
        return []
    if use_ai:
        monitor.assess(shortlist, prof, [], system=SYSTEM)
    else:
        monitor.assess_without_ai(shortlist)
    return [i for i in shortlist if i["score"] >= prof["filter"]["min_score"]][:12]


def main() -> None:
    ap = argparse.ArgumentParser(description="Send Eglur Daily briefings")
    ap.add_argument("--dry-run", action="store_true", help="build emails into daily-email/preview, send nothing")
    ap.add_argument("--only", help="send only to this subscriber's email")
    ap.add_argument("--no-ai", action="store_true", help="keyword matching only (free)")
    args = ap.parse_args()

    today = dt.date.today()
    if not (os.environ.get("SUBSCRIBERS_URL") and os.environ.get("SUBSCRIBERS_TOKEN")):
        print("SUBSCRIBERS_URL / SUBSCRIBERS_TOKEN not set yet: nothing to do (see tools/waitlist/SETUP.md).", file=sys.stderr)
        return
    reply = sheet_request({"action": "list"})
    if not reply.get("ok"):
        sys.exit(f"Couldn't read subscribers: {reply.get('error')}")
    subs = [s for s in reply["subscribers"] if due_today(s, today)]
    if args.only:
        subs = [s for s in subs if s["email"].lower() == args.only.lower()]
    limit = min(int(os.environ.get("MAX_SUBSCRIBERS", "80")), int(reply.get("quota", 100)))
    subs = subs[:limit]
    print(f"{len(subs)} subscribers due today (email quota left: {reply.get('quota')})", file=sys.stderr)
    if not subs:
        return

    subs_geo = [(s, locate(str(s.get("area", "")))) for s in subs]
    days = 7 if today.weekday() == 4 and any(s.get("frequency") == "weekly" for s in subs) else (3 if today.weekday() == 0 else 1)
    items = collect_all(subs_geo, today, days)
    use_ai = not args.no_ai and bool(os.environ.get("ANTHROPIC_API_KEY"))
    preview = Path("daily-email/preview")
    sent = skipped = 0
    for n, (sub, geo) in enumerate(subs_geo, 1):
        picked = for_subscriber(items, sub, geo, use_ai)
        if not picked and sub.get("frequency") != "weekly":
            skipped += 1
            print(f"  {mask(sub['email'])}: nothing relevant today, not sending", file=sys.stderr)
            continue
        subject, html_doc, text = render_email(picked, sub, geo, today)
        if args.dry_run:
            preview.mkdir(parents=True, exist_ok=True)
            tag = hashlib.sha256(sub["email"].encode()).hexdigest()[:8]   # no addresses in file names
            (preview / f"{n:02d}-{tag}.html").write_text(html_doc.replace("{{UNSUBSCRIBE}}", "#"))
            print(f"  {mask(sub['email'])}: {len(picked)} items, preview written", file=sys.stderr)
            continue
        res = sheet_request(body={"action": "send", "to": sub["email"], "subject": subject, "html": html_doc, "text": text})
        if res.get("ok"):
            sent += 1
        print(f"  {mask(sub['email'])}: {len(picked)} items, {'sent' if res.get('ok') else 'FAILED: ' + str(res.get('error'))}", file=sys.stderr)
    print(f"done: {sent} sent, {skipped} skipped (nothing relevant)", file=sys.stderr)


if __name__ == "__main__":
    main()
