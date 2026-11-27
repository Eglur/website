"""One-off probe of devolved-parliament data sources (runs on GitHub Actions)."""
import json, urllib.request, sys

B = "https://data.niassembly.gov.uk/questions.asmx/"
URLS = [
    ("ni-tabled-1", B + "GetQuestionsForWrittenAnswer_TabledInRange_JSON?startDate=2026-11-20&endDate=2026-11-27"),
    ("ni-tabled-2", B + "GetQuestionsForWrittenAnswer_TabledInRange_JSON?startDate=20/11/2026&endDate=27/11/2026"),
    ("ni-answered", B + "GetQuestionsForWrittenAnswer_AnsweredInRange_JSON?startDate=2026-11-20&endDate=2026-11-27"),
    ("ni-wsdl", "https://data.niassembly.gov.uk/questions.asmx?WSDL"),
    ("postcodes-ni", "https://api.postcodes.io/postcodes/BT15GS"),
    ("postcodes-scot", "https://api.postcodes.io/postcodes/EH991SP"),
    ("scot-constits", "https://data.parliament.scot/api/constituencies"),
    ("scot-mecs", "https://data.parliament.scot/api/memberelectionconstituencystatuses"),
    ("scot-regions", "https://data.parliament.scot/api/regions"),
]

for name, url in URLS:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "EglurMonitor/1.0 (+https://www.eglurtech.com/monitor/)", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            print(f"=== {name} {r.status} {r.headers.get('Content-Type')} {len(raw)} bytes")
            txt = raw.decode("utf-8-sig", "replace")
            if name == "ni-wsdl":
                import re
                i = txt.find('TabledInRange_JSON">')
                print(txt[i-200:i+800]); continue
            try:
                data = json.loads(txt)
                if isinstance(data, list):
                    print(f"list len={len(data)}; last items:")
                    print(json.dumps(data[-2:], indent=1)[:1500])
                elif name.startswith("postcodes"):
                    res = data["result"]; print({k: v for k, v in res.items() if k != "codes"}); print(res.get("codes"))
                else:
                    print(json.dumps(data, indent=1)[:2500])
            except Exception:
                print(txt[:1500])
    except Exception as e:
        body = ""
        if hasattr(e, "read"):
            try: body = e.read().decode("utf-8", "replace")[:600]
            except Exception: pass
        print(f"=== {name} FAILED {e} {body}")
    sys.stdout.flush()
