"""Live check of the new devolved sources (runs on GitHub Actions)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor

for fn in (monitor.fetch_holyrood_written_questions, monitor.fetch_stormont_written_questions):
    items = fn("2026-11-24", "2026-11-27")
    ans = [i for i in items if i["answered"]]
    print(f"=== {fn.__name__}: {len(items)} items, {len(ans)} answered")
    for it in items[:2] + ans[:2]:
        print(json.dumps({k: (v[:160] if isinstance(v, str) else v) for k, v in it.items()}, ensure_ascii=False, indent=1))
