"""Offline stand-in for the Parliament APIs: serves tests/sample_api.json and applies
the same date filters and paging the real APIs do."""
import json
from pathlib import Path

DATA = json.loads((Path(__file__).parent / "sample_api.json").read_text())
CALLS: list[tuple[str, dict]] = []


def _page(rows, params, take_key="take", skip_key="skip"):
    skip = int(params.get(skip_key, 0))
    take = int(params.get(take_key, 20))
    return rows[skip:skip + take]


def fake_get_json(url: str, params: dict):
    CALLS.append((url, dict(params)))
    if url.endswith("/writtenquestions/questions"):
        rows = DATA["writtenquestions"]
        if "tabledWhenFrom" in params:
            rows = [r for r in rows if r["dateTabled"][:10] >= params["tabledWhenFrom"]]
        if "answeredWhenFrom" in params:
            rows = [r for r in rows if (r["dateAnswered"] or "")[:10] >= params["answeredWhenFrom"]]
        return {"totalResults": len(rows), "results": [{"value": r} for r in _page(rows, params)]}
    if url.endswith("/writtenstatements/statements"):
        rows = [r for r in DATA["writtenstatements"] if r["dateMade"][:10] >= params["madeWhenFrom"]]
        return {"totalResults": len(rows), "results": [{"value": r} for r in _page(rows, params)]}
    if url.endswith("/api/v1/Sittings"):
        rows = [r for r in DATA["sittings"] if params["DateFrom"] <= r["date"][:10] <= params["DateTo"]]
        return {"items": _page(rows, params, "Take", "Skip"), "totalResults": len(rows)}
    if url.endswith("/api/v1/Bills"):
        want = set(params.get("BillIds", []))
        return {"items": [b for b in DATA["bills"] if b["billId"] in want]}
    if url.endswith("/divisions.json/search"):
        rows = [d for d in DATA["divisions"] if d["Date"][:10] >= params["queryParameters.startDate"]]
        return rows[: int(params.get("queryParameters.take", 25))]
    raise AssertionError(f"unexpected URL {url}")
