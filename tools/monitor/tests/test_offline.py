"""Offline end-to-end tests. Run from the repo root:  python -m unittest discover tests -v"""
import datetime as dt
import json
import sys
import tempfile
import tomllib
import types
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import anthropic  # real SDK, used only for its response types
import fake_api
import monitor

PROFILE = tomllib.loads((HERE.parent / "profile.toml").read_text())
ASSESSMENTS = json.loads((HERE / "sample_assessments.json").read_text())["assessments"]
TODAY = dt.date(2026, 11, 27)  # a Friday; the sample data covers 23-27 Nov


class FakeClaude:
    """Stands in for anthropic.Anthropic: checks the request and replies with a real
    ToolUseBlock, the same shape the live API returns."""
    calls: list = []
    fail_batches: set = set()
    reply_as_text = False

    def __init__(self, *a, **k):
        self.messages = self

    def create(self, **kw):
        FakeClaude.calls.append(kw)
        if len(FakeClaude.calls) in FakeClaude.fail_batches:
            raise RuntimeError("simulated API outage")
        assert kw["tool_choice"] == {"type": "auto"}, "forced tool choice is rejected by the live model"
        assert kw["tools"][0]["name"] == "record_assessments"
        assert kw["model"] == PROFILE["model"]["name"]
        content = kw["messages"][0]["content"]
        assert "OFFICE PROFILE" in content and "Pembrokeshire" in content
        ids = [i["id"] for i in json.loads(content.split("ITEMS:\n", 1)[1].split("\n\nAssess", 1)[0])]
        out = [a for a in ASSESSMENTS if a["id"] in ids]
        if FakeClaude.reply_as_text:
            text = anthropic.types.TextBlock(type="text", text="Here you go:\n" + json.dumps({"assessments": out}))
            return types.SimpleNamespace(content=[text])
        block = anthropic.types.ToolUseBlock(id="toolu_test", type="tool_use",
                                             name="record_assessments", input={"assessments": out})
        return types.SimpleNamespace(content=[block])


class Base(unittest.TestCase):
    def setUp(self):
        monitor.get_json = fake_api.fake_get_json
        monitor.get_text = lambda url: ""   # no Senedd pages unless a test supplies one
        self.tmp = Path(tempfile.mkdtemp())
        monitor.OUT = self.tmp / "monitor"
        FakeClaude.calls, FakeClaude.fail_batches, FakeClaude.reply_as_text = [], set(), False
        anthropic.Anthropic = FakeClaude


class TestKeywords(unittest.TestCase):
    def match(self, kws, text):
        return [k for k, p in monitor.compile_keywords(kws) if p.search(text)]

    def test_whole_words_and_plurals(self):
        self.assertEqual(self.match(["GP"], "More GPs in rural areas"), ["GP"])
        self.assertEqual(self.match(["GP"], "GPS tracking"), [])
        self.assertEqual(self.match(["port"], "ports and harbours"), ["port"])

    def test_no_false_positives_inside_words(self):
        text = "staff transferred, support offered, report preferred, passport, important"
        self.assertEqual(self.match(["ferry", "ferries", "port", "GP", "farm*"], text), [])

    def test_prefix(self):
        self.assertEqual(self.match(["farm*"], "Farmers and farming"), ["farm*"])
        self.assertEqual(self.match(["devol*"], "the devolution settlement"), ["devol*"])

    def test_phrases(self):
        self.assertEqual(self.match(["Milford Haven"], "the port of Milford Haven"), ["Milford Haven"])


class TestSources(Base):
    def test_collect(self):
        items = monitor.collect(PROFILE, "2026-11-23", "2026-11-27")
        by_id = {i["id"]: i for i in items}
        self.assertNotIn("wq-9000001", by_id, "withdrawn questions must be skipped")
        ws = [i for i in items if i["type"] == "Ministerial statement"]
        self.assertEqual(len(ws), 5, "Lords repeats of Commons statements must be removed")
        self.assertTrue(all(i["house"] == "Commons" for i in ws))
        self.assertIn("£450 million", by_id["wq-1961924"]["text"], "HTML entities must be decoded")
        self.assertNotIn("<p>", by_id["wq-1961924"]["text"])
        self.assertEqual(by_id["wq-1961924"]["url"],
                         "https://questions-statements.parliament.uk/written-questions/detail/2026-11-18/HL5568")
        self.assertEqual(by_id["ws-1964557"]["url"],
                         "https://questions-statements.parliament.uk/written-statements/detail/2026-11-26/hcws510")
        self.assertEqual(by_id["wq-1961924"]["who"], "Baroness Wilcox of Newport (Lab, Life peer)")

    def test_bills_from_sittings(self):
        bills = monitor.fetch_bills("2026-11-23", "2026-11-27")
        by_title = {b["title"]: b for b in bills}
        self.assertEqual(len(bills), 4)
        hw = by_title["Highways (Financing) Bill"]
        self.assertEqual(hw["date"], "2026-11-26")
        self.assertEqual(hw["text"], "Sittings: Committee stage (Commons) on 2026-11-24; Committee stage (Commons) on 2026-11-26.")
        self.assertIn("Bill 4163", by_title, "unknown bills fall back to their id")
        self.assertIn("2nd reading (Commons)", by_title["Bill 4163"]["text"])
        # ids are requested in batches through the BillIds parameter
        bill_calls = [p for u, p in fake_api.CALLS if u.endswith("/api/v1/Bills")]
        self.assertTrue(bill_calls and all(isinstance(p["BillIds"], list) for p in bill_calls))

    def test_window(self):
        items = monitor.collect(PROFILE, "2026-11-26", "2026-11-27")
        self.assertFalse(any(i["date"] < "2026-11-26" for i in items if i["type"] != "Written question"))


class TestPipeline(Base):
    def run_pipeline(self, use_ai=True):
        monitor.run(PROFILE, TODAY, 4, use_ai)
        return (monitor.OUT / "index.html").read_text()

    def test_full_run_with_ai(self):
        html = self.run_pipeline()
        self.assertEqual(len(FakeClaude.calls), 1, "6 shortlisted items fit in one batch")
        # strictness: only items scoring 6+ appear; 9+ go under "Act today"
        self.assertIn("Needs you today", html)
        self.assertIn("Public Sector: Wales", html)
        self.assertIn("Transport: Wales", html)
        self.assertNotIn("Scottish Government", html)        # scored 2
        self.assertNotIn("Local Government Finance", html)   # scored 5
        self.assertNotIn("TEST ONLY", html)
        self.assertNotIn("Armed Forces Bill", html)          # filtered before the AI
        self.assertEqual(html.count('<article class="item'), 4)
        self.assertIn("<b>23</b>updates read", html)
        self.assertIn("<b>6</b>matched your issues", html)
        self.assertIn('content="noindex,nofollow"', html)
        self.assertNotIn('class="note"', html)

    def test_outputs_and_links(self):
        self.run_pipeline()
        out = monitor.OUT
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["archive.html", "digests", "index.html"])
        index = (out / "index.html").read_text()
        self.assertIn('href="./archive.html"', index)
        self.assertNotIn(">Latest<", index)
        archived = (out / "digests" / "2026-11-27.html").read_text()
        self.assertIn('href="../archive.html"', archived, "archived copies link back up a level")
        self.assertIn('<a href="../">Latest</a>', archived)
        self.assertIn('href="./digests/2026-11-27.html"', (out / "archive.html").read_text())

    def test_branding(self):
        html = self.run_pipeline()
        self.assertEqual(html.count('class="wm"'), 2, "Eglur wordmark in header and footer")
        self.assertIn('<a class="brand" href="/" aria-label="Eglur, home">', html)
        self.assertIn("@font-face{font-family:'DM Serif Display'", html)
        self.assertIn("--teal:#286A6C", html)
        self.assertIn('<link rel="icon" href="/favicon.svg" type="image/svg+xml">', html)
        self.assertIn('<meta name="theme-color" content="#286A6C">', html)
        self.assertIn('What needs you today<span class="stop">.</span>', html)
        self.assertIn('<p class="label decide">Needs you today</p>', html)
        self.assertIn('<p class="label">Worth knowing</p>', html)
        self.assertEqual(html.count("AI-drafted · check the source"), 4)
        self.assertIn("clarity for public servants", html)
        self.assertIn("Eglur is Welsh for clear", html)
        self.assertIn("Morning briefing · Friday 27 November 2026", html)
        self.assertIn("since Monday 23 November 2026", html)

    def test_empty_day(self):
        out = monitor.render_digest([], 0, "Example office", "2026-11-27", "2026-11-26", 6, "./")
        self.assertIn('Nothing needs you today<span class="stop">.</span>', out)

    def test_ai_outage_falls_back(self):
        FakeClaude.fail_batches = {1}
        html = self.run_pipeline()
        self.assertIn("AI step failed", html)
        self.assertIn("Matched:", html)

    def test_json_text_reply_is_accepted(self):
        FakeClaude.reply_as_text = True
        html = self.run_pipeline()
        self.assertNotIn("AI step failed", html)
        self.assertEqual(html.count("AI-drafted · check the source"), 4)

    def test_keyword_only_mode(self):
        html = self.run_pipeline(use_ai=False)
        self.assertEqual(FakeClaude.calls, [])
        self.assertIn("Keyword-only mode", html)
        self.assertIn("Keyword match", html)
        self.assertNotIn("AI-drafted", html)
        self.assertNotIn("TEST ONLY", html)

    def test_escaping(self):
        it = {"id": "x", "type": "T", "house": "H", "title": "<script>alert(1)</script>", "who": "", "body": "",
              "date": "2026-11-27", "text": "", "url": "https://e.x/?a=1&b=2", "score": 9, "summary": "a & b", "why": "", "action": ""}
        out = monitor.card(it)
        self.assertNotIn("<script>", out)
        self.assertIn("&amp;b=2", out)


class TestQuickFixes(Base):
    def test_untitled_question_gets_department_title(self):
        row = dict(fake_api.DATA["writtenquestions"][1], id=777, heading=None, dateAnswered=None)
        orig = fake_api.DATA["writtenquestions"]
        fake_api.DATA["writtenquestions"] = [row]
        try:
            items = monitor.fetch_written_questions("2026-11-01", "2026-11-27")
        finally:
            fake_api.DATA["writtenquestions"] = orig
        self.assertEqual(items[0]["title"], "Question to DWP")

    def test_related_questions_grouped(self):
        items = monitor.collect(PROFILE, "2026-11-23", "2026-11-27")
        gly = [i for i in items if i["title"] == "Glyphosate"]
        self.assertEqual(len(gly), 1)
        self.assertEqual(gly[0]["related"], 2)
        self.assertIn("councils", gly[0]["text"]); self.assertIn("rainwater", gly[0]["text"])
        html = monitor.card(dict(gly[0], score=6, summary="s", why="", action="", ai=True))
        self.assertIn("2 related questions · 6/10", html)

    def test_department_name_does_not_match(self):
        it = {"title": "Water: Cambridgeshire", "text": "Asks about reservoir timetables.", "who": "A Member (Lab, Ely)",
              "body": "Department for Environment, Food and Rural Affairs"}
        self.assertEqual(monitor.prefilter([it], ["rural"], 10), [])

    def test_stage_tracker(self):
        commons = monitor.stage_track({"origin": "Commons", "stage_id": 8, "stage": "Committee stage", "house": "Commons", "is_act": False})
        self.assertIn("Now: <b>Committee, Commons</b> · stage 3 of 12", commons)
        self.assertEqual(commons.count('class="seg done'), 2)
        self.assertEqual(commons.count('class="seg now'), 1)
        lords_first = monitor.stage_track({"origin": "Lords", "stage_id": 8, "stage": "Committee stage", "house": "Commons", "is_act": False})
        self.assertIn("stage 8 of 12", lords_first)
        self.assertLess(lords_first.index("h-lords"), lords_first.index("h-commons"))
        act = monitor.stage_track({"origin": "Commons", "stage_id": 99, "stage": "Royal Assent", "house": "", "is_act": True})
        self.assertIn("Now: <b>Royal Assent</b> · stage 12 of 12", act)

    def test_bill_items_carry_stage(self):
        bills = {b["title"]: b for b in monitor.fetch_bills("2026-11-23", "2026-11-27")}
        self.assertEqual(bills["Financial Services and Markets Bill [HL]"]["bill"]["origin"], "Lords")
        self.assertEqual(bills["Highways (Financing) Bill"]["bill"]["stage_id"], 8)


SENEDD_HTML = (HERE / "sample_senedd.html").read_text()


class TestSenedd(Base):
    def test_parse_page(self):
        items = monitor.parse_senedd_questions(SENEDD_HTML, "https://record.senedd.wales/OrderPaper/WrittenQuestions/25-11-2026")
        by_ref = {i["ref"]: i for i in items}
        self.assertEqual(sorted(by_ref), ["WQ101431", "WQ101457", "WQ101461"], "the WQ inside a script is ignored")
        a = by_ref["WQ101461"]
        self.assertEqual((a["type"], a["house"], a["answered"], a["tabled"], a["date"]),
                         ("Written answer", "Senedd", "2026-11-20", "2026-11-18", "2026-11-20"))
        self.assertEqual(a["who"], "Iain McIntosh (Brycheiniog Tawe Nedd)")
        self.assertEqual(a["body"], "Cabinet Minister for Government Effectiveness & the Constitution")
        self.assertIn("ANSWER: The Welsh Government’s plans", a["text"])
        self.assertNotIn("Cabinet Minister for Health and Care", a["text"], "next minister heading isn't part of the answer")
        q = by_ref["WQ101431"]
        self.assertEqual((q["type"], q["body"], q["answered"]), ("Written question", "Cabinet Minister for Health and Care", ""))
        self.assertEqual(q["title"], "What steps is the Welsh Government taking to improve accident and emergency…")
        last = by_ref["WQ101457"]
        self.assertNotIn("Contact us", last["text"]); self.assertNotIn("Copyright", last["text"])

    def test_window_and_pages(self):
        asked = []
        def fake(url):
            asked.append(url)
            return SENEDD_HTML if url.endswith("/25-11-2026") else ""
        monitor.get_text = fake
        self.assertEqual({i["ref"] for i in monitor.fetch_senedd_written_questions("2026-11-19", "2026-11-27")}, {"WQ101461"},
                         "only the answer given on 20 Nov is new since 19 Nov")
        self.assertEqual(len(monitor.fetch_senedd_written_questions("2026-11-18", "2026-11-27")), 3)
        self.assertTrue(all("/OrderPaper/WrittenQuestions/" in u for u in asked))
        self.assertFalse(any(dt.date(int(u[-4:]), int(u[-7:-5]), int(u[-10:-8])).weekday() > 4 for u in asked), "weekdays only")

    def test_senedd_card_labels(self):
        it = monitor.parse_senedd_questions(SENEDD_HTML, "u")[1]
        html = monitor.card(dict(it, score=7, summary="s", why="w", action="", ai=True))
        self.assertIn('class="item c-senedd"', html)
        self.assertIn('<span class="chamber ch-senedd"><i></i>Senedd</span>', html)
        self.assertIn("Written question · awaiting answer · WQ101431", html)


class TestChamberLabels(unittest.TestCase):
    def test_westminster_tags(self):
        base = {"id": "x", "title": "t", "who": "", "body": "", "date": "2026-11-26", "text": "", "url": "u",
                "score": 6, "summary": "s", "why": "", "action": "", "ai": True}
        lords = monitor.card(dict(base, type="Written answer", house="Lords"))
        self.assertIn('class="item c-lords"', lords)
        self.assertIn("Westminster · Lords", lords)
        commons = monitor.card(dict(base, type="Written question", house="Commons"))
        self.assertIn("Westminster · Commons", commons)
        self.assertIn("Written question · awaiting answer", commons)


class TestBatching(Base):
    def test_batches_of_30(self):
        items = [{"id": f"i{n}", "type": "t", "house": "h", "title": "t", "who": "", "body": "",
                  "date": "d", "text": "x" * 2000} for n in range(65)]
        monitor.assess(items, PROFILE)
        self.assertEqual(len(FakeClaude.calls), 3)
        sent = json.loads(FakeClaude.calls[0]["messages"][0]["content"].split("ITEMS:\n", 1)[1].split("\n\nAssess", 1)[0])
        self.assertEqual(len(sent[0]["text"]), 900, "item text is trimmed to control cost")
        self.assertTrue(all(i["score"] == 0 for i in items), "unassessed items default to 0, so they're dropped")


if __name__ == "__main__":
    unittest.main(verbosity=2)
