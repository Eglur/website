"""Read the Senedd and the Commons from Eglur's shared public corpus, instead of fetching them again.

Eglur (the app for offices) already loads Senedd and Commons questions, answers, statements and
speeches into its corpus every day. Eglur Daily reads them through one narrow, read-only function,
daily_feed, using a token for the role eglur_public_reader: it can read public passages and nothing
else. Dormant until all three settings are present:

  EGLUR_CORPUS_URL   the Supabase project URL, e.g. https://abc.supabase.co
  EGLUR_CORPUS_KEY   its publishable key (sb_publishable_...), which is safe to be public
  READER_TOKEN       Eglur Daily's token (npm run reader:token in the app). A secret.

Until then, Eglur Daily keeps using its own fetchers. Never prints the token.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request
from collections import defaultdict

import monitor

HOUSE = {"senedd": "Senedd", "commons": "Commons"}


def settings() -> tuple[str, str, str] | None:
    url, key, token = (os.environ.get(k, "").strip() for k in ("EGLUR_CORPUS_URL", "EGLUR_CORPUS_KEY", "READER_TOKEN"))
    if not (url and key and token):
        return None
    if not key.startswith("sb_publishable_"):
        raise ValueError("EGLUR_CORPUS_KEY must be the publishable key, never a secret one.")
    return url.rstrip("/"), key, token


def rpc(name: str, args: dict, timeout: int = 60):
    s = settings()
    if not s:
        raise RuntimeError("the corpus is not configured")
    url, key, token = s
    req = urllib.request.Request(
        f"{url}/rest/v1/rpc/{name}", data=json.dumps(args).encode(), method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": monitor.UA if hasattr(monitor, "UA") else "EglurDaily/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def shorten(text: str, limit: int = 1800) -> str:
    text = monitor.clean(text or "")
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def items_from_rows(rows: list[dict]) -> list[dict]:
    """Turn daily_feed rows into Eglur Daily items: one per written question (with its answer), one per
    statement, and one per member per debate for speeches. Procedural passages are left out."""
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_doc[r["document_id"]].append(r)
    out = []
    for doc_id, ps in by_doc.items():
        d = ps[0]
        house = HOUSE.get(d["institution_id"], d["institution_id"].capitalize())
        wq = d.get("written_question")
        if wq:
            q = next((p for p in ps if p["kind"] == "question"), None)
            a = next((p for p in ps if p["kind"] == "answer"), None)
            if not q:
                continue
            answered = (wq.get("answered") or "")[:10]
            who = q.get("member_name") or q.get("speaker") or ""
            if who and q.get("member_party"):
                who = f"{who} ({q['member_party']})"
            out.append({
                "id": f"corpus-{doc_id}",
                "type": "Written answer" if a else "Written question",
                "house": house,
                "ref": wq.get("number", ""),
                "title": monitor.short_title(d["title"] or q["text"]),
                "who": who,
                "member_id": q.get("member_id") or wq.get("askedBy") or "",
                "body": wq.get("answeringBody") or wq.get("answeringMinister") or "",
                "date": answered or (wq.get("tabled") or "")[:10] or q["passage_date"],
                "tabled": (wq.get("tabled") or "")[:10],
                "answered": answered,
                "text": shorten(q["text"] + (" ANSWER: " + a["text"] if a else "")),
                "url": (a or q)["passage_url"] or d["document_url"],
            })
            continue
        for p in (p for p in ps if p["kind"] == "statement"):
            out.append({
                "id": f"corpus-{p['passage_id']}", "type": "Written statement", "house": house, "ref": "",
                "title": monitor.short_title(d["title"]), "who": p.get("member_name") or p.get("speaker") or "",
                "member_id": p.get("member_id") or "", "body": p.get("speaker") or "", "date": p["passage_date"],
                "text": shorten(p["text"]), "url": p["passage_url"] or d["document_url"],
            })
        speeches: dict[str, list[dict]] = defaultdict(list)
        for p in ps:
            if p["kind"] == "speech" and p.get("member_id"):
                speeches[p["member_id"]].append(p)
        for member_id, said in speeches.items():
            first = said[0]
            name = first.get("member_name") or first.get("speaker") or ""
            out.append({
                "id": f"corpus-{doc_id}-{member_id}",
                "type": "Spoke in the chamber",
                "house": house,
                "ref": "",
                "title": monitor.short_title(f"{name} spoke: {d['title']}"),
                "who": f"{name} ({first['member_party']})" if first.get("member_party") else name,
                "member_id": member_id,
                "body": d["title"],
                "date": first["passage_date"],
                "text": shorten(" ".join(p["text"] for p in said)),
                "url": first["passage_url"] or d["document_url"],
            })
    return out


def fetch(since: str, until: str) -> list[dict]:
    """Senedd and Commons items from the corpus for the window (daily_feed caps it at 8 days and 2,000 rows)."""
    rows = rpc("daily_feed", {"since": f"{since}T00:00:00Z", "institutions": ["senedd", "commons"], "max_rows": 2000})
    return [i for i in items_from_rows(rows) if i["date"] and since <= i["date"] <= until]


def current_members() -> list[dict]:
    return rpc("reader_members", {"institutions": ["senedd", "commons"]})


def lords_only(fn):
    """Daily's own Westminster fetchers, kept for the Lords only: the corpus holds the Commons."""
    def wrapped(since: str, until: str) -> list[dict]:
        return [i for i in fn(since, until) if i.get("house") == "Lords"]
    return wrapped


def sources() -> dict:
    """Eglur Daily's sources: from the corpus when it is configured, otherwise Daily's own fetchers."""
    src = dict(monitor.SOURCES)
    if not settings():
        return src
    src["written_questions"] = lords_only(monitor.fetch_written_questions)
    src["written_statements"] = lords_only(monitor.fetch_written_statements)
    src.pop("senedd_written_questions", None)
    src["eglur_corpus"] = fetch
    return src


def my_representatives(geo: dict, members: list[dict]) -> set[str]:
    """Member ids of the MP for their constituency. (Senedd constituencies are not yet in postcode data,
    so MSs come through the people a subscriber follows.)"""
    want = (geo.get("constituency") or "").strip().lower()
    return {m["id"] for m in members if m["institution_id"] == "commons" and (m.get("area_name") or "").strip().lower() == want and want}
