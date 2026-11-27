#!/usr/bin/env python3
"""Eglur morning briefing (prototype).

Pulls recent official Westminster updates, filters them against an office
profile, has Claude score and explain what matters, and publishes an
Eglur-branded briefing page plus an archive of past briefings.

Usage (from the website repo root):
  python tools/monitor/monitor.py --out monitor          # live run (needs ANTHROPIC_API_KEY)
  python tools/monitor/monitor.py --out monitor --no-ai  # keyword matching only (free)
  python tools/monitor/monitor.py --out monitor --days 3 # look back 3 days
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
BRAND = ROOT / "brand"
OUT = Path("site")  # set by --out; the briefing is published here (index, archive, digests/)
UA = "EglurBriefing/0.1 (+https://www.eglurtech.com)"


# ----------------------------------------------------------------- fetching

def get_json(url: str, params: dict):
    q = urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def clean(s: str | None) -> str:
    """Strip HTML tags and entities, collapse whitespace."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def day(s: str | None) -> str:
    return (s or "")[:10]


def member_label(m: dict | None) -> str:
    if not m or not m.get("name"):
        return ""
    extra = ", ".join(x for x in (m.get("partyAbbreviation"), m.get("memberFrom")) if x)
    return f"{m['name']} ({extra})" if extra else m["name"]


SHORT_BODIES = {
    "Department for Environment, Food and Rural Affairs": "DEFRA",
    "Department for Work and Pensions": "DWP",
    "Department of Health and Social Care": "DHSC",
    "Ministry of Housing, Communities and Local Government": "MHCLG",
    "Department for Science, Innovation and Technology": "DSIT",
    "Department for Digital, Culture, Media and Sport": "DCMS",
    "Department for Culture, Media and Sport": "DCMS",
    "Department for Energy Security and Net Zero": "DESNZ",
    "Department for Business and Trade": "DBT",
    "Department for Education": "DfE",
    "Department for Transport": "DfT",
    "Foreign, Commonwealth and Development Office": "FCDO",
    "Ministry of Defence": "MoD",
    "Ministry of Justice": "MoJ",
}


def short_body(name: str) -> str:
    return SHORT_BODIES.get(name, name)


def fetch_written_questions(since: str, until: str) -> list[dict]:
    """Questions tabled OR answered since `since`, both Houses."""
    base = "https://questions-statements-api.parliament.uk/api/writtenquestions/questions"
    seen: dict[int, dict] = {}
    for date_param in ("tabledWhenFrom", "answeredWhenFrom"):
        skip = 0
        while skip < 3000:
            data = get_json(base, {date_param: since, "expandMember": "true", "take": 100, "skip": skip})
            rows = data.get("results", [])
            for r in rows:
                seen[r["value"]["id"]] = r["value"]
            if len(rows) < 100:
                break
            skip += 100
    items = []
    for v in seen.values():
        if v.get("isWithdrawn"):
            continue
        answered = bool(v.get("dateAnswered"))
        tabled = day(v.get("dateTabled"))
        text = clean(v.get("questionText"))
        if answered:
            text += " ANSWER: " + clean(v.get("answerText"))
        items.append({
            "id": f"wq-{v['id']}",
            "type": "Written answer" if answered else "Written question",
            "house": v.get("house", ""),
            "title": v.get("heading") or (f"Question to {short_body(v['answeringBodyName'])}"
                                          if v.get("answeringBodyName") else "Written question"),
            "who": member_label(v.get("askingMember")),
            "body": v.get("answeringBodyName") or "",
            "date": day(v.get("dateAnswered")) if answered else tabled,
            "text": text,
            "url": f"https://questions-statements.parliament.uk/written-questions/detail/{tabled}/{v.get('uin')}",
        })
    return group_related(items)


def group_related(items: list[dict]) -> list[dict]:
    """One card for a set of questions from the same member, on the same heading, to the same department."""
    groups: dict[tuple, list[dict]] = {}
    for it in items:
        groups.setdefault((it["who"], it["title"], it["body"], it["type"]), []).append(it)
    out = []
    for members in groups.values():
        first = dict(members[0])
        if len(members) > 1:
            first["related"] = len(members)
            first["text"] = " | ".join(m["text"] for m in members)
            first["date"] = max(m["date"] for m in members)
        out.append(first)
    return out


def fetch_written_statements(since: str, until: str) -> list[dict]:
    base = "https://questions-statements-api.parliament.uk/api/writtenstatements/statements"
    data = get_json(base, {"madeWhenFrom": since, "expandMember": "true", "take": 100})
    items = []
    for r in data.get("results", []):
        v = r["value"]
        m = v.get("member") or {}
        date = day(v.get("dateMade"))
        who = ", ".join(x for x in (m.get("name"), v.get("memberRole")) if x)
        items.append({
            "id": f"ws-{v['id']}",
            "type": "Ministerial statement",
            "house": v.get("house", ""),
            "title": v.get("title") or "Written statement",
            "who": who,
            "body": v.get("answeringBodyName") or "",
            "date": date,
            "text": clean(v.get("text")),
            "url": f"https://questions-statements.parliament.uk/written-statements/detail/{date}/{(v.get('uin') or '').lower()}",
        })
    # The Lords usually repeats the Commons statement word for word. Keep one (Commons).
    uniq: dict[tuple, dict] = {}
    for it in items:
        key = (it["title"].strip().lower(), it["date"])
        if key not in uniq or it["house"] == "Commons":
            uniq[key] = it
    return list(uniq.values())


# Standard stage ids in the Bills API (used only when the bill's current stage doesn't match).
STAGE_NAMES = {1: "1st reading (Lords)", 2: "2nd reading (Lords)", 3: "Committee stage (Lords)",
               4: "Report stage (Lords)", 5: "3rd reading (Lords)", 6: "1st reading (Commons)",
               7: "2nd reading (Commons)", 8: "Committee stage (Commons)", 9: "Report stage (Commons)",
               10: "3rd reading (Commons)"}


def fetch_bills(since: str, until: str) -> list[dict]:
    """Bills that had a stage sitting in the window (e.g. second reading, committee)."""
    sittings, skip = [], 0
    while skip < 1000:
        data = get_json("https://bills-api.parliament.uk/api/v1/Sittings",
                        {"DateFrom": since, "DateTo": until, "Take": 100, "Skip": skip})
        rows = data.get("items", [])
        sittings += rows
        if len(rows) < 100:
            break
        skip += 100
    by_bill: dict[int, list[dict]] = {}
    for s in sittings:
        by_bill.setdefault(s["billId"], []).append(s)

    bills: dict[int, dict] = {}
    ids = list(by_bill)
    for i in range(0, len(ids), 20):
        data = get_json("https://bills-api.parliament.uk/api/v1/Bills", {"BillIds": ids[i:i + 20], "Take": 100})
        for b in data.get("items", []):
            bills[b["billId"]] = b

    items = []
    for bill_id, sits in by_bill.items():
        b = bills.get(bill_id, {})
        cur = b.get("currentStage") or {}
        stages = []
        for s in sorted(sits, key=lambda s: s["date"]):
            if cur.get("stageId") == s["stageId"] and cur.get("description"):
                name = f"{cur['description']} ({cur.get('house', '')})".replace(" ()", "")
            else:
                name = STAGE_NAMES.get(s["stageId"], "a stage")
            stages.append(f"{name} on {day(s['date'])}")
        latest = max(day(s["date"]) for s in sits)
        items.append({
            "id": f"bill-{bill_id}-{latest}",
            "type": "Bill stage",
            "house": b.get("currentHouse", ""),
            "title": b.get("shortTitle") or f"Bill {bill_id}",
            "bill": {"origin": b.get("originatingHouse") or ("Lords" if "[HL]" in (b.get("shortTitle") or "") else "Commons"),
                     "stage_id": cur.get("stageId"), "stage": cur.get("description", ""),
                     "house": cur.get("house", ""), "is_act": bool(b.get("isAct"))},
            "who": "",
            "body": "",
            "date": latest,
            "text": "Sittings: " + "; ".join(dict.fromkeys(stages)) + "."
                    + (" Now an Act." if b.get("isAct") else ""),
            "url": f"https://bills.parliament.uk/bills/{bill_id}",
        })
    return items


def fetch_commons_divisions(since: str, until: str) -> list[dict]:
    base = "https://commonsvotes-api.parliament.uk/data/divisions.json/search"
    data = get_json(base, {"queryParameters.startDate": since, "queryParameters.take": 50})
    return [{
        "id": f"div-{d['DivisionId']}",
        "type": "Commons vote",
        "house": "Commons",
        "title": d.get("Title") or "Division",
        "who": "",
        "body": "",
        "date": day(d.get("Date")),
        "text": f"Division: Ayes {d.get('AyeCount')}, Noes {d.get('NoCount')}.",
        "url": f"https://votes.parliament.uk/votes/commons/division/{d['DivisionId']}",
    } for d in data]


SOURCES = {
    "written_questions": fetch_written_questions,
    "written_statements": fetch_written_statements,
    "bills": fetch_bills,
    "commons_divisions": fetch_commons_divisions,
}


# ---------------------------------------------------------------- filtering

def compile_keywords(keywords: list[str]) -> list[tuple[str, re.Pattern]]:
    """'GP' matches GP/GPs (not GPS) as a whole word; 'farm*' matches farm, farmer, farming…"""
    pats = []
    for k in (k.strip() for k in keywords):
        if not k:
            continue
        if k.endswith("*"):
            pats.append((k, re.compile(r"\b" + re.escape(k[:-1]), re.I)))
        else:  # the plural ending is case-sensitive, so "GPS" isn't read as "GPs"
            pats.append((k, re.compile(r"\b" + re.escape(k) + r"(?-i:s|es)?\b", re.I)))
    return pats


def prefilter(items: list[dict], keywords: list[str], cap: int) -> list[dict]:
    pats = compile_keywords(keywords)
    if not pats:
        return items[:cap]
    out = []
    for it in items:
        hay = " ".join((it["title"], it["text"], it["who"]))  # not the department name: "Rural Affairs" isn't a rural story
        hits = [k for k, p in pats if p.search(hay)]
        if hits:
            it["hits"] = hits
            out.append(it)
    out.sort(key=lambda i: len(i["hits"]), reverse=True)
    return out[:cap]


# ------------------------------------------------------------------- the AI

TOOL = {
    "name": "record_assessments",
    "description": "Record a relevance assessment for every item provided.",
    "input_schema": {
        "type": "object",
        "properties": {
            "assessments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "score": {"type": "integer", "minimum": 0, "maximum": 10,
                                  "description": "Relevance to THIS office. 9-10: needs the office today. 6-8: should know. 0-5: noise."},
                        "summary": {"type": "string", "description": "One plain sentence: what happened. Facts only."},
                        "why": {"type": "string", "description": "One sentence: why it matters to this office specifically. Empty if score < 6."},
                        "action": {"type": "string", "description": "Optional concrete next step, e.g. a follow-up written question or a line for a press release. Empty if none."},
                    },
                    "required": ["id", "score", "summary", "why"],
                },
            }
        },
        "required": ["assessments"],
    },
}

SYSTEM = """You are a parliamentary researcher in a UK elected representative's office.
You read official updates and decide which ones this office genuinely needs to know about.
Be strict: most items are noise, and a short briefing is a good briefing.
Never state anything that is not in the item text. Use British English."""


def assess(items: list[dict], profile: dict) -> int:
    """Score and explain items with Claude. Returns the number of failed batches."""
    import anthropic  # imported here so keyword-only runs don't need the package
    client = anthropic.Anthropic()
    model = profile["model"]["name"]
    failures = 0
    for i in range(0, len(items), 30):
        batch = items[i:i + 30]
        payload = [{k: it[k] for k in ("id", "type", "house", "title", "who", "body", "date")}
                   | {"text": it["text"][:900]} for it in batch]
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=8000,
                system=SYSTEM,
                tools=[TOOL],
                tool_choice={"type": "auto"},  # this model doesn't accept a forced tool choice
                messages=[{"role": "user", "content":
                           f"OFFICE PROFILE:\n{profile['office']['description'].strip()}\n\n"
                           f"ITEMS:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
                           "Assess every item by calling record_assessments once, with one entry per item."}],
            )
            block = next((b for b in msg.content if b.type == "tool_use"), None)
            if block is not None:
                data = block.input
            else:  # fallback: the model answered with JSON text instead of calling the tool
                text = "".join(getattr(b, "text", "") for b in msg.content)
                data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            by_id = {a["id"]: a for a in data["assessments"]}
        except Exception as e:  # keep going: a failed batch falls back to keyword matching
            print(f"WARNING: AI batch {i // 30 + 1} failed ({e}); using keyword matching for it.", file=sys.stderr)
            assess_without_ai(batch)
            failures += 1
            continue
        for it in batch:
            a = by_id.get(it["id"], {})
            it["score"] = int(a.get("score", 0))
            it["summary"] = a.get("summary", "")
            it["why"] = a.get("why", "")
            it["action"] = a.get("action", "")
            it["ai"] = True
    return failures


def assess_without_ai(items: list[dict]) -> None:
    for it in items:
        it["score"] = min(10, 5 + len(it.get("hits", [])))
        it["summary"] = it["text"][:260] + ("…" if len(it["text"]) > 260 else "")
        it["why"] = "Matched: " + ", ".join(it.get("hits", [])) if it.get("hits") else ""
        it["action"] = ""
        it["ai"] = False


# ---------------------------------------------------------------- rendering
# Eglur brand: the same tokens, fonts, wordmark and patterns as eglurtech.com.

CSS = """
:root{--teal:#286A6C;--teal-deep:#1E5153;--dot:#8FD1C6;--paper:#FCFFFE;--ground:#FAFBF9;
--ink:#101A1A;--ink-2:#3D4A49;--muted:#4E5B5A;--hair:#E2E7E5;--edge:#7D8B88;--decision:#9A5D0E;--ai:#5E43A8;
--serif:'DM Serif Display',Georgia,'Times New Roman',serif;
--sans:'Geist',system-ui,-apple-system,'Segoe UI',Arial,sans-serif;
--mono:'Geist Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);font-size:17px;line-height:1.6;
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:var(--teal-deep)}
.wrap{max-width:820px;margin:0 auto;padding:0 32px}
header.site{position:sticky;top:0;z-index:10;background:rgba(252,255,254,.94);backdrop-filter:blur(8px);
-webkit-backdrop-filter:blur(8px);border-bottom:1px solid var(--hair)}
.bar{display:flex;align-items:center;justify-content:space-between;height:72px;gap:24px}
.brand{display:block;flex:none;color:var(--ink)}
.wm{display:block;height:30px;width:auto;color:var(--ink)}.wm .dot{fill:var(--teal)}
nav{display:flex;align-items:center;gap:22px;font-size:15px}
nav a{color:var(--ink-2);text-decoration:none}nav a:hover{color:var(--teal-deep)}
.chip{font-family:var(--mono);font-size:11px;font-weight:500;letter-spacing:.14em;text-transform:uppercase;
color:var(--muted);border:1px solid var(--hair);border-radius:2px;padding:4px 8px}
.label{display:inline-flex;align-items:center;gap:12px;font-family:var(--mono);font-size:12px;font-weight:500;
letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin:0}
.label::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--teal);flex:none}
.label.decide::before{background:var(--decision)}
.hero{padding:56px 0 24px}
h1{font-family:var(--serif);font-weight:400;font-size:clamp(40px,6.4vw,64px);line-height:1;letter-spacing:-.02em;
margin:18px 0;text-wrap:balance}
.stop{color:var(--teal)}
.lede{margin:0;color:var(--ink-2);font-size:19px;max-width:52ch}
.note{margin:24px 0 0;padding:12px 16px;border:1px solid var(--hair);border-left:3px solid var(--decision);
border-radius:2px;background:var(--paper);font-size:15px;color:var(--ink-2)}
.stats{display:flex;flex-wrap:wrap;gap:14px 44px;margin:32px 0 0;padding:22px 0 0;border-top:1px solid var(--hair)}
.stats div{font-family:var(--mono);font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.stats b{display:block;font-family:var(--serif);font-weight:400;font-size:40px;line-height:1.05;letter-spacing:-.01em;
color:var(--ink);text-transform:none;margin-bottom:4px}
section.group{padding:28px 0 4px}
.item{background:var(--paper);border:1px solid var(--hair);border-radius:2px;padding:22px 24px;margin:14px 0}
.item.top{border-left:3px solid var(--decision)}
.row{display:flex;justify-content:space-between;gap:16px;font-family:var(--mono);font-size:12px;letter-spacing:.08em;
text-transform:uppercase;color:var(--muted)}
.score{flex:none;letter-spacing:.04em}
.item h3{font-family:var(--serif);font-weight:400;font-size:26px;line-height:1.15;margin:10px 0 6px;text-wrap:balance}
.item h3 a{color:var(--ink);text-decoration:none}
.item h3 a:hover{color:var(--teal-deep);text-decoration:underline;text-underline-offset:3px}
.who{font-size:15px;color:var(--muted)}
.item p{margin:12px 0 0}
.k{display:block;font-family:var(--mono);font-size:11px;font-weight:500;letter-spacing:.14em;text-transform:uppercase;margin-bottom:2px}
.why{color:var(--teal-deep);font-weight:500}.why .k{color:var(--teal)}
.next{color:var(--decision)}
.src{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px 14px;margin-top:16px;padding-top:12px;
border-top:1px solid var(--hair);font-family:var(--mono);font-size:12px;letter-spacing:.04em;color:var(--muted)}
.src .ai{color:var(--ai)}.src a{color:var(--teal-deep)}
.empty{color:var(--ink-2);font-size:19px}
.track{margin:14px 0 4px}
.segs{display:grid;grid-template-columns:repeat(12,1fr);gap:3px}
.seg{height:8px;border-radius:2px;background:var(--hair)}
.seg.done.h-commons{background:#4C8C6E}.seg.done.h-lords{background:#A2545F}.seg.done.h-both{background:var(--teal)}
.seg.now{background:var(--decision);box-shadow:0 0 0 2px rgba(154,93,14,.18)}
.tlabels{display:grid;grid-template-columns:5fr 5fr 2fr;gap:3px;margin-top:6px;font-family:var(--mono);font-size:11px;
letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.tlabels span{display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden}
.hd{width:7px;height:7px;border-radius:50%;flex:none}.hd.h-commons{background:#4C8C6E}.hd.h-lords{background:#A2545F}
.tnow{margin-top:6px;font-size:14px;color:var(--ink-2)}.tnow b{color:var(--decision);font-weight:600}
footer.site{border-top:1px solid var(--hair);padding:40px 0 52px;margin-top:56px;background:var(--paper)}
.foot{display:flex;flex-direction:column;gap:12px}
.fbrand{display:flex;align-items:center;gap:16px;margin-bottom:6px}.fbrand .wm{height:24px}
.fbrand small,.fine{font-size:13px;color:var(--muted);font-family:var(--mono);letter-spacing:.02em}
.fine{margin:0;max-width:72ch}.fine a{color:var(--muted)}
ul.archive{list-style:none;padding:0;margin:12px 0 0;border-top:1px solid var(--hair)}
ul.archive li{border-bottom:1px solid var(--hair)}
ul.archive a{display:flex;justify-content:space-between;gap:16px;padding:18px 0;font-family:var(--serif);font-size:26px;
line-height:1.15;color:var(--ink);text-decoration:none}
ul.archive a span{font-family:var(--mono);font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);align-self:center}
ul.archive a:hover{color:var(--teal-deep)}
@media (max-width:600px){.wrap{padding:0 20px}.bar{height:64px}.wm{height:26px}.hero{padding:36px 0 16px}
.lede{font-size:17px}.item{padding:18px}.item h3{font-size:23px}.stats{gap:14px 28px}.stats b{font-size:34px}
nav .chip{display:none}.row{letter-spacing:.04em;font-size:11px}ul.archive a{font-size:22px}}
"""


def esc(s: str) -> str:
    return html.escape(s or "")


def nice_date(iso: str, long: bool = False) -> str:
    try:
        d = dt.date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{d:%A} {d.day} {d:%B %Y}" if long else f"{d.day} {d:%b}"


def wordmark() -> str:
    return (BRAND / "wordmark.svg").read_text().strip()


HOUSE_STAGES = {"Commons": [(6, "1st reading"), (7, "2nd reading"), (8, "Committee"), (9, "Report"), (10, "3rd reading")],
                "Lords": [(1, "1st reading"), (2, "2nd reading"), (3, "Committee"), (4, "Report"), (5, "3rd reading")]}


def stage_track(bill: dict) -> str:
    """A coloured bar of the bill's journey: first House, second House, final stages, Royal Assent."""
    first = bill["origin"] if bill["origin"] in HOUSE_STAGES else "Commons"
    second = "Lords" if first == "Commons" else "Commons"
    steps = [(first, sid, name) for sid, name in HOUSE_STAGES[first]] + \
            [(second, sid, name) for sid, name in HOUSE_STAGES[second]] + \
            [("Both", "final", "Final stages"), ("Both", "assent", "Royal Assent")]
    if bill["is_act"] or "royal assent" in bill["stage"].lower():
        pos = len(steps) - 1
    else:
        ids = [s[1] for s in steps]
        pos = ids.index(bill["stage_id"]) if bill["stage_id"] in ids else len(steps) - 2
    segs = []
    for i, (house, _, name) in enumerate(steps):
        state = "done" if i < pos else "now" if i == pos else "todo"
        segs.append(f'<span class="seg {state} h-{house.lower()}" title="{esc(house)}: {esc(name)}"></span>')
    house, _, name = steps[pos]
    where = name if house == "Both" else f"{name}, {house}"
    return (f'<div class="track" aria-label="Bill stage: {esc(where)}">'
            f'<div class="segs">{"".join(segs)}</div>'
            f'<div class="tlabels"><span><i class="hd h-{first.lower()}"></i>{first}</span>'
            f'<span><i class="hd h-{second.lower()}"></i>{second}</span><span>Final</span></div>'
            f'<div class="tnow">Now: <b>{esc(where)}</b> · stage {pos + 1} of {len(steps)}</div></div>')


def related_label(it: dict) -> str:
    return f"{it['related']} related questions · " if it.get("related") else ""


def card(it: dict) -> str:
    who = " · ".join(x for x in (it["who"], it["body"]) if x)
    parts = [
        f'<article class="item{" top" if it["score"] >= 9 else ""}">',
        f'<div class="row"><span>{esc(it["type"])} · {esc(it["house"])} · {esc(nice_date(it["date"]))}</span>'
        f'<span class="score">{related_label(it)}{it["score"]}/10</span></div>',
        f'<h3><a href="{esc(it["url"])}" target="_blank" rel="noopener">{esc(it["title"])}</a></h3>',
    ]
    if who:
        parts.append(f'<div class="who">{esc(who)}</div>')
    if it.get("bill"):
        parts.append(stage_track(it["bill"]))
    parts.append(f'<p>{esc(it["summary"])}</p>')
    if it.get("why"):
        parts.append(f'<p class="why"><span class="k">Why it matters</span>{esc(it["why"])}</p>')
    if it.get("action"):
        parts.append(f'<p class="next"><span class="k">Next step</span>{esc(it["action"])}</p>')
    tag = ('<span class="ai">AI-drafted · check the source</span>' if it.get("ai")
           else "<span>Keyword match</span>")
    parts.append(f'<div class="src">{tag}<a href="{esc(it["url"])}" target="_blank" rel="noopener">Official record ↗</a></div>')
    parts.append("</article>")
    return "\n".join(parts)


def page(title: str, main: str, root: str) -> str:
    latest = f'<a href="{root}">Latest</a>' if root != "./" else ""
    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta name="theme-color" content="#286A6C">
<title>{esc(title)}</title>
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-48.png" type="image/png" sizes="48x48">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preload" href="/fonts/geist-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/fonts/dm-serif-display-latin.woff2" as="font" type="font/woff2" crossorigin>
<style>{(BRAND / "fonts.css").read_text()}{CSS}</style></head>
<body>
<header class="site"><div class="wrap bar">
<a class="brand" href="/" aria-label="Eglur, home">{wordmark()}</a>
<nav><span class="chip">Prototype</span>{latest}<a href="{root}archive.html">Past briefings</a></nav>
</div></header>
<main class="wrap">
{main}
</main>
<footer class="site"><div class="wrap foot">
<div class="fbrand">{wordmark()}<small>clarity for public servants</small></div>
<p class="fine">Built from public data published by UK Parliament under the
<a href="https://www.parliament.uk/site-information/copyright-parliament/open-parliament-licence/">Open Parliament Licence v3.0</a>.
Summaries are drafted by AI and can be wrong, so every item links to the official record.</p>
<p class="fine">Eglur Technologies · In development · Eglur is Welsh for clear</p>
</div></footer>
</body></html>
"""


def read_minutes(items: list[dict]) -> int:
    words = sum(len(" ".join((i["title"], i["summary"], i.get("why", ""), i.get("action", ""))).split()) for i in items)
    return max(1, round(words / 200))


def render_digest(items: list[dict], scanned: int, office: str, today: str, since: str,
                  min_score: int, root: str, note: str = "") -> str:
    keep = sorted((i for i in items if i["score"] >= min_score), key=lambda i: (-i["score"], i["title"]))
    top = [i for i in keep if i["score"] >= 9]
    rest = [i for i in keep if i["score"] < 9]
    groups = ""
    if top:
        groups += '<section class="group"><p class="label decide">Needs you today</p>\n' + "\n".join(card(i) for i in top) + "</section>\n"
    if rest:
        groups += '<section class="group"><p class="label">Worth knowing</p>\n' + "\n".join(card(i) for i in rest) + "</section>\n"
    headline = "What needs you today" if keep else "Nothing needs you today"
    lede = (f"{office}. Official Westminster business since {nice_date(since, long=True)}, "
            "filtered to your issues, ranked and explained.")
    stats = (f'<div><b>{scanned}</b>updates read</div><div><b>{len(items)}</b>matched your issues</div>'
             f'<div><b>{len(keep)}</b>in this briefing</div>'
             + (f'<div><b>{read_minutes(keep)} min</b>to read</div>' if keep else ""))
    main = f"""<section class="hero">
<p class="label">Morning briefing · {esc(nice_date(today, long=True))}</p>
<h1>{headline}<span class="stop">.</span></h1>
<p class="lede">{esc(lede)}</p>
{f'<div class="note">{esc(note)}</div>' if note else ''}
<div class="stats">{stats}</div>
</section>
{groups or '<p class="empty">Nothing in this period met the bar for this office.</p>'}"""
    return page(f"Morning briefing · {nice_date(today, long=True)} · Eglur", main, root)


def render_archive() -> str:
    files = sorted((OUT / "digests").glob("*.html"), reverse=True)
    links = "\n".join(f'<li><a href="./digests/{f.name}">{esc(nice_date(f.stem, long=True))}<span>Read</span></a></li>'
                      for f in files)
    main = f"""<section class="hero"><p class="label">Archive</p>
<h1>Past briefings<span class="stop">.</span></h1></section>
<ul class="archive">{links or '<li class="empty">None yet.</li>'}</ul>"""
    return page("Past briefings · Eglur", main, "./")


def publish(index_html: str, archived_html: str, today: str) -> None:
    (OUT / "digests").mkdir(parents=True, exist_ok=True)
    (OUT / "digests" / f"{today}.html").write_text(archived_html)
    (OUT / "index.html").write_text(index_html)
    (OUT / "archive.html").write_text(render_archive())


# --------------------------------------------------------------------- main

def collect(profile: dict, since: str, until: str) -> list[dict]:
    items = []
    for key, fn in SOURCES.items():
        if not profile["sources"].get(key, True):
            continue
        try:
            got = fn(since, until)
            print(f"{key}: {len(got)}", file=sys.stderr)
            items += got
        except Exception as e:  # one failing source shouldn't kill the briefing
            print(f"WARNING: {key} failed: {e}", file=sys.stderr)
    return items


def run(profile: dict, today: dt.date, days: int, use_ai: bool, extra_note: str = "") -> None:
    since = (today - dt.timedelta(days=days)).isoformat()
    items = collect(profile, since, today.isoformat())
    scanned = len(items)
    f = profile["filter"]
    shortlist = prefilter(items, f.get("keywords", []), f.get("max_items", 120))
    print(f"scanned {scanned}, keyword matches {len(shortlist)}", file=sys.stderr)

    note = ""
    if use_ai:
        if assess(shortlist, profile):
            note = "Part of today's AI step failed, so some items below are keyword matches only."
    else:
        assess_without_ai(shortlist)
        note = "Keyword-only mode: no AI ranking or explanations in this briefing yet."
    note = " ".join(x for x in (extra_note, note) if x)

    args = (shortlist, scanned, profile["office"]["name"], today.isoformat(), since, f.get("min_score", 6))
    publish(render_digest(*args, root="./", note=note),
            render_digest(*args, root="../", note=note), today.isoformat())
    print(f"Wrote {OUT / 'index.html'}", file=sys.stderr)


def main() -> None:
    global OUT
    ap = argparse.ArgumentParser(description="Eglur morning briefing (prototype)")
    ap.add_argument("--out", default="site", help="folder to publish into (the website's /monitor folder)")
    ap.add_argument("--days", type=int, help="look-back window in days (default 1, or 3 on Mondays)")
    ap.add_argument("--no-ai", action="store_true", help="skip Claude; keyword matching only")
    ap.add_argument("--profile", default=str(ROOT / "profile.toml"))
    args = ap.parse_args()

    OUT = Path(args.out)
    profile = tomllib.loads(Path(args.profile).read_text())
    today = dt.date.today()
    days = args.days or (3 if today.weekday() == 0 else 1)
    use_ai = not args.no_ai and bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not args.no_ai and not use_ai:
        print("No ANTHROPIC_API_KEY set: running in keyword-only mode.", file=sys.stderr)
    run(profile, today, days, use_ai)


if __name__ == "__main__":
    main()
