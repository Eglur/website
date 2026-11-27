"""Build a preview briefing from the sample data, without touching the network.
Run from the website repo root:  python tools/monitor/tests/make_preview.py OUTPUT_FOLDER"""
import datetime as dt
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import anthropic
import fake_api
import monitor
from test_offline import FakeClaude

monitor.get_json = fake_api.fake_get_json
monitor.OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "preview")
anthropic.Anthropic = FakeClaude

profile = tomllib.loads((HERE / "example_profile.toml").read_text())
monitor.run(profile, dt.date(2026, 11, 27), 4, use_ai=True, extra_note=(
    "Preview: real Parliament items from 23 to 26 November 2026, with the text shortened. "
    "Claude wrote the rankings and explanations in the build chat, following the live instructions. "
    "Live runs write their own."))
print(monitor.OUT / "index.html")
