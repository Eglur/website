"""One-off probe of devolved-parliament data sources (runs on GitHub Actions)."""
import json, urllib.request, sys

URLS = [
    ("scot-questions", "https://data.parliament.scot/api/motionsquestionsanswersquestions?year=2026"),
    ("scot-questions-noyear", "https://data.parliament.scot/api/motionsquestionsanswersquestions"),
    ("scot-motions", "https://data.parliament.scot/api/motionsquestionsanswersmotions?year=2026"),
    ("scot-members", "https://data.parliament.scot/api/members"),
    ("ni-questions-json", "https://data.niassembly.gov.uk/questions_json.ashx?m=GetQuestionsForWrittenAnswer_ByDateRange&startDate=2026-11-20&endDate=2026-11-27"),
    ("ni-questions-asmx", "https://data.niassembly.gov.uk/questions.asmx/GetQuestionsForWrittenAnswer_ByDateRange_JSON?startDate=2026-11-20&endDate=2026-11-27"),
    ("ni-members", "https://data.niassembly.gov.uk/members_json.ashx?m=GetAllCurrentMembers"),
    ("ni-site", "https://data.niassembly.gov.uk/"),
    ("postcodes-scot", "https://api.postcodes.io/postcodes/EH991SP"),
    ("postcodes-ni", "https://api.postcodes.io/postcodes/BT48BS"),
]

for name, url in URLS:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "EglurMonitor/1.0 (+https://www.eglurtech.com/monitor/)", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            print(f"=== {name} {r.status} {r.headers.get('Content-Type')} {len(raw)} bytes")
            txt = raw.decode("utf-8-sig", "replace")
            try:
                data = json.loads(txt)
                if isinstance(data, list):
                    print(f"list len={len(data)}; last item:")
                    print(json.dumps(data[-1], indent=1)[:1500])
                else:
                    print("keys:", list(data)[:20] if isinstance(data, dict) else type(data))
                    print(json.dumps(data, indent=1)[:2000])
            except Exception:
                print(txt[:2000])
    except Exception as e:
        print(f"=== {name} FAILED {e}")
    sys.stdout.flush()
