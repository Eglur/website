"""Offline end-to-end tests. Run from the repo root:  python -m unittest discover tests -v"""
import datetime as dt
import json
import sys
import tempfile
import tomllib
import types
import unittest
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import anthropic  # real SDK, used only for its response types
import fake_api
import monitor

PROFILE = tomllib.loads((HERE / "example_profile.toml").read_text())  # fixed test profile, independent of the live one
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
        monitor.STATE.clear()
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
        self.assertIn("<b>25</b>updates read", html)
        self.assertIn("<b>6</b>matched your issues", html)
        self.assertIn('content="noindex,nofollow"', html)
        self.assertNotIn('class="note"', html)

    def test_outputs_and_links(self):
        self.run_pipeline()
        out = monitor.OUT
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["archive.html", "digests", "index.html", "state.json"])
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


def html_escape(t):
    return t.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


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

    def test_parse_clipboard_format(self):
        text = ("Written Questions tabled on 03/11/2026 for answer on 10/11/2026\n\n"
                "Deputy First Minister and Cabinet Minister for Social Justice and Equality\n\n"
                "WQ101156(e)\nTabled on: 03/11/2026\nCai Parry-Jones (Caerdydd Ffynnon Taf)\n"
                "Does the Welsh Government encourage the wearing of the white poppy?\n\n"
                "Answered by Deputy First Minister and Cabinet Minister for Social Justice and Equality\n"
                "Answered on: 10/11/2026\nWe respect the choice of individuals to wear a white poppy.&#160; It is a symbol of peace.\n\n"
                "Cabinet Minister for Finance\n\nWQ101200(e)\nTabled on: 03/11/2026\nSteven Rodaway (G&#373;yr Abertawe)\n"
                "How will council tax premiums be reviewed?\nTo be answered by: Cabinet Minister for Finance\n")
        page = ('<main><a id="copy" class="button fullIcon" data-clipboard-text="' + html_escape(text) + '">Copy</a>'
                "<div>visible layout we don't rely on</div></main>")
        items = {i["ref"]: i for i in monitor.parse_senedd_questions(page, "u")}
        self.assertEqual(sorted(items), ["WQ101156", "WQ101200"])
        a = items["WQ101156"]
        self.assertEqual((a["answered"], a["who"]), ("2026-11-10", "Cai Parry-Jones (Caerdydd Ffynnon Taf)"))
        self.assertTrue(a["text"].endswith("ANSWER: We respect the choice of individuals to wear a white poppy. It is a symbol of peace."))
        self.assertEqual(items["WQ101200"]["who"], "Steven Rodaway (Gŵyr Abertawe)")
        self.assertEqual(items["WQ101200"]["type"], "Written question")

    def test_window_and_pages(self):
        asked = []
        def fake(url):
            asked.append(url)
            return SENEDD_HTML if url.endswith("/25-11-2026") else ""
        monitor.get_text = fake
        self.assertEqual({i["ref"] for i in monitor.fetch_senedd_written_questions("2026-11-21", "2026-11-27")}, {"WQ101461"},
                         "no memory yet: look back 2 days, so only the answer given on 20 Nov counts")
        monitor.STATE.clear()
        self.assertEqual(len(monitor.fetch_senedd_written_questions("2026-11-20", "2026-11-27")), 3)
        self.assertTrue(all("/OrderPaper/WrittenQuestions/" in u for u in asked))
        self.assertFalse(any(dt.date(int(u[-4:]), int(u[-7:-5]), int(u[-10:-8])).weekday() > 4 for u in asked), "weekdays only")

    def test_senedd_card_labels(self):
        it = monitor.parse_senedd_questions(SENEDD_HTML, "u")[1]
        html = monitor.card(dict(it, score=7, summary="s", why="w", action="", ai=True))
        self.assertIn('class="item c-senedd"', html)
        self.assertIn('<span class="chamber ch-senedd"><i></i>Senedd</span>', html)
        self.assertIn("Written question · awaiting answer · WQ101431", html)


class TestLookAhead(Base):
    def test_calendar_items(self):
        items = {i["id"]: i for i in monitor.fetch_calendar("2026-11-26", "2026-11-27")}
        self.assertEqual(sorted(items), ["cal-27668", "cal-28436"], "private meetings are skipped")
        ha = items["cal-27668"]
        self.assertEqual(ha["title"], "Home Affairs Committee: Police reform")
        self.assertEqual((ha["date"], ha["time"], ha["house"], ha["upcoming"]), ("2026-12-01", "14:00", "Commons", True))
        self.assertEqual(ha["url"], "https://committees.parliament.uk/committee/83/")
        self.assertTrue(ha["text"].startswith("Coming up on 2026-12-01 14:00."))
        self.assertEqual(ha["type"], "Select & Joint Committees · Oral evidence")

    def test_coming_up_section(self):
        ev = dict(monitor.fetch_calendar("2026-11-26", "2026-11-27")[0], score=7, summary="s", why="w", action="", ai=True)
        past = {"id": "p", "type": "Written answer", "house": "Lords", "title": "Past item", "who": "", "body": "", "date": "2026-11-26",
                "text": "", "url": "u", "score": 9, "summary": "s", "why": "w", "action": "", "ai": True}
        html = monitor.render_digest([past, ev], 2, "Office", "2026-11-27", "2026-11-26", 6, "./")
        self.assertIn('<p class="label">Coming up this week</p>', html)
        self.assertLess(html.index("Needs you today"), html.index("Coming up this week"))
        self.assertIn("Tue 1 Dec · 14:00", html)
        self.assertLess(html.index("Past item"), html.index("Home Affairs Committee"))


class TestSeneddMemory(Base):
    def test_shown_questions_are_not_repeated(self):
        monitor.get_text = lambda url: SENEDD_HTML if url.endswith("/25-11-2026") else ""
        first = monitor.fetch_senedd_written_questions("2026-11-20", "2026-11-27")
        self.assertEqual(len(first), 3, "first run (no memory) looks back 2 days")
        again = monitor.fetch_senedd_written_questions("2026-11-21", "2026-11-28")
        self.assertEqual(again, [], "already shown, so not repeated")
        self.assertIn("swq-101461:a", monitor.STATE["senedd_shown"])

    def test_late_answers_caught_with_memory(self):
        monitor.get_text = lambda url: SENEDD_HTML if url.endswith("/25-11-2026") else ""
        monitor.STATE["senedd_shown"] = ["swq-000001:q"]          # memory exists, so look back a week
        got = monitor.fetch_senedd_written_questions("2026-11-26", "2026-11-27")
        self.assertEqual({i["ref"] for i in got}, {"WQ101461"},
                         "an answer dated 20 Nov, first seen on the 27th, still appears; questions tabled 18 Nov are over a week old")

    def test_state_saved_with_briefing(self):
        monitor.run(PROFILE, TODAY, 4, False)
        self.assertIn("senedd_shown", json.loads((monitor.OUT / "state.json").read_text()))


NEWS_HTML = """<html><body><nav><a href="/news/category/Local-News">Local News</a></nav>
<div class="item"><a href="/news/paul-davies-presses-council-answers-over-millions-earmarked-pembroke"><img src="x.jpg"></a>
<h3><a href="/news/paul-davies-presses-council-answers-over-millions-earmarked-pembroke">Paul Davies presses council for answers over millions earmarked for Pembroke</a></h3>
<span class="date">Thursday, 12 November, 2026</span><span>Local News</span>
<a href="/news/paul-davies-presses-council-answers-over-millions-earmarked-pembroke">Read more</a></div>
<div class="item"><h3><a href="https://www.paul-davies.org.uk/news/totally-unacceptable-paul-davies-demands-answers-after-85-year-old-waits-over-16-hours">&#039;Totally unacceptable&#039;: Paul Davies demands answers after 85-year-old waits over 16 hours for ambulance</a></h3>
<span>11th November 2026</span></div>
<a href="/news?page=1">Next</a></body></html>"""


class TestMemberVoice(Base):
    def test_reads_member_news(self):
        monitor.get_text = lambda url: NEWS_HTML
        news = monitor.fetch_member_news("https://www.paul-davies.org.uk/news")
        self.assertEqual([n["date"] for n in news], ["2026-11-12", "2026-11-11"])
        self.assertEqual(news[0]["url"], "https://www.paul-davies.org.uk/news/paul-davies-presses-council-answers-over-millions-earmarked-pembroke")
        self.assertEqual(news[1]["title"], "'Totally unacceptable': Paul Davies demands answers after 85-year-old waits over 16 hours for ambulance")
        self.assertEqual(len(news), 2, "image links, 'Read more', categories and paging are skipped")

    def test_context_includes_statements_and_draft_flag(self):
        prof = dict(PROFILE, member={"social_drafts": True})
        ctx = monitor.context_block(prof, [{"title": "Ambulance waits", "date": "2026-11-11", "url": "u"}])
        self.assertIn("RECENT PUBLIC STATEMENTS", ctx); self.assertIn("11 Nov: Ambulance waits", ctx)
        self.assertIn("SOCIAL POST DRAFTS REQUESTED: yes", ctx)
        self.assertIn("SOCIAL POST DRAFTS REQUESTED: no", monitor.context_block(PROFILE, []))

    def test_post_and_link_on_card(self):
        it = {"id": "x", "type": "Written answer", "house": "Senedd", "title": "t", "who": "", "body": "", "date": "2026-11-26",
              "text": "", "url": "u", "score": 8, "summary": "s", "why": "w", "action": "", "ai": True,
              "link": "Your 11 Nov statement on ambulance waits", "post": 'Ambulance waits in "west Wales" must end.'}
        html = monitor.card(it)
        self.assertIn("Connects to</span>Your 11 Nov statement on ambulance waits", html)
        self.assertIn('data-copy="Ambulance waits in &quot;west Wales&quot; must end."', html)
        self.assertIn("Draft post · AI, edit before use", html)

    def test_statements_section_and_copy_script(self):
        html = monitor.render_digest([], 0, "Office", "2026-11-27", "2026-11-26", 6, "./",
                                     statements=[{"title": "Ambulance waits", "date": "2026-11-11", "url": "https://e.x/a"}],
                                     member="Paul Davies MS")
        self.assertIn("Recent statements from Paul Davies MS", html)
        self.assertIn('href="https://e.x/a"', html)
        self.assertIn("navigator.clipboard.writeText", html)

    def test_post_dropped_below_7(self):
        class Low(FakeClaude):
            def create(self, **kw):
                ids = [i["id"] for i in json.loads(kw["messages"][0]["content"].split("ITEMS:\n", 1)[1].split("\n\nAssess", 1)[0])]
                out = [{"id": i, "score": 6, "summary": "s", "why": "w", "post": "should not appear"} for i in ids]
                return types.SimpleNamespace(content=[anthropic.types.ToolUseBlock(id="t", type="tool_use", name="record_assessments", input={"assessments": out})])
        anthropic.Anthropic = Low
        items = [{"id": "a", "type": "t", "house": "Commons", "title": "t", "who": "", "body": "", "date": "d", "text": "x"}]
        monitor.assess(items, PROFILE, [])
        self.assertEqual(items[0]["post"], "")


MG_COMMITTEES = """<?xml version="1.0" encoding="utf-8"?> <committees> <committeescount> 3</committeescount>
<committee><committeeid>281</committeeid><committeetitle>Cabinet</committeetitle><committeedeleted>False</committeedeleted><committeeexpired>False</committeeexpired><committeecategory>Executive</committeecategory></committee>
<committee><committeeid>514</committeeid><committeetitle>Audit Committee</committeetitle><committeedeleted>False</committeedeleted><committeeexpired>False</committeeexpired><committeecategory>Defunct Committees</committeecategory></committee>
<committee><committeeid>290</committeeid><committeetitle>Planning Committee</committeetitle><committeedeleted>False</committeedeleted><committeeexpired>False</committeeexpired><committeecategory>Regulatory</committeecategory></committee>
</committees>"""
MG_MEETINGS = {
    "281": """<?xml version="1.0" encoding="utf-8"?><getmeetings><committee><committeemeetings>
<meeting><meetingid>6719</meetingid><meetingdate>25/11/2026</meetingdate><meetingstatus>Confirmed</meetingstatus><meetingtime>10.00a.m.</meetingtime></meeting>
<meeting><meetingid>6720</meetingid><meetingdate>30/11/2026</meetingdate><meetingstatus>Confirmed</meetingstatus><meetingtime>10.00a.m.</meetingtime></meeting>
</committeemeetings></committee></getmeetings>""",
    "290": """<?xml version="1.0" encoding="utf-8"?><getmeetings><committee><committeemeetings>
<meeting><meetingid>6800</meetingid><meetingdate>01/12/2026</meetingdate><meetingstatus>Cancelled</meetingstatus><meetingtime>10.00a.m.</meetingtime></meeting>
</committeemeetings></committee></getmeetings>""",
}
MG_MEETING = {
    "6719": """<?xml version="1.0" encoding="utf-8"?><meeting><meetingid>6719</meetingid><meetinglocation>County Hall, Haverfordwest</meetinglocation>
<agendapublished>True</agendapublished><decisionpublished>True</decisionpublished><agendaitems>
<agendaitem><agendaitemid>1</agendaitemid><agendaitemtitle>Apologies for Absence</agendaitemtitle><decisionnonemptyhtmlbody>&lt;p&gt;Apologies were received.&lt;/p&gt;</decisionnonemptyhtmlbody></agendaitem>
<agendaitem><agendaitemid>2</agendaitemid><agendaitemtitle>5. TEST: School transport policy review</agendaitemtitle><decisionnonemptyhtmlbody>&lt;p&gt;TEST decision: the revised policy was approved.&lt;/p&gt;</decisionnonemptyhtmlbody></agendaitem>
<agendaitem><agendaitemid>3</agendaitemid><agendaitemtitle>TEST: Item with no decision yet</agendaitemtitle><decisionnonemptyhtmlbody></decisionnonemptyhtmlbody></agendaitem>
</agendaitems></meeting>""",
    "6720": """<?xml version="1.0" encoding="utf-8"?><meeting><meetingid>6720</meetingid><meetinglocation>County Hall, Haverfordwest</meetinglocation>
<agendapublished>True</agendapublished><decisionpublished>False</decisionpublished><agendaitems>
<agendaitem><agendaitemid>9</agendaitemid><agendaitemtitle>TEST: Withybush parking charges</agendaitemtitle><agendatext>TEST report on car park charges.</agendatext></agendaitem>
<agendaitem><agendaitemid>10</agendaitemid><agendaitemtitle>Declarations of Interest</agendaitemtitle></agendaitem>
</agendaitems></meeting>""",
}


def fake_mg(url):
    q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1])) if "?" in url else {}
    if "/GetCommittees" in url: return MG_COMMITTEES
    if "/GetMeetings" in url:
        assert q["sFromDate"].count("/") == 2, "dates are sent as dd/mm/yyyy"
        return MG_MEETINGS.get(q["lCommitteeId"], "<getmeetings/>")
    if "/GetMeeting" in url: return MG_MEETING[q["lMeetingId"]]
    return ""


class TestCouncils(Base):
    def setUp(self):
        super().setUp()
        monitor.get_text = fake_mg
        monitor.COUNCILS[:] = [{"name": "Pembrokeshire", "url": "https://mgenglish.pembrokeshire.gov.uk"}]

    def tearDown(self):
        monitor.COUNCILS[:] = []

    def test_agenda_and_decisions(self):
        items = {i["title"]: i for i in monitor.fetch_councils("2026-11-26", "2026-11-27")}
        self.assertEqual(sorted(items), ["TEST: School transport policy review", "TEST: Withybush parking charges"],
                         "boilerplate, undecided items, defunct committees and cancelled meetings are skipped")
        d = items["TEST: School transport policy review"]
        self.assertEqual((d["type"], d["house"], d["council"], d["who"], d["date"], d["upcoming"]),
                         ("Council decision", "Council", "Pembrokeshire", "Cabinet", "2026-11-25", False))
        self.assertIn("DECISION: TEST decision: the revised policy was approved.", d["text"])
        self.assertEqual(d["url"], "https://mgenglish.pembrokeshire.gov.uk/ieListDocuments.aspx?CId=281&MId=6719")
        u = items["TEST: Withybush parking charges"]
        self.assertEqual((u["type"], u["upcoming"], u["time"], u["body"]), ("Meeting agenda", True, "10.00am", "Pembrokeshire · County Hall, Haverfordwest"))

    def test_not_repeated(self):
        self.assertEqual(len(monitor.fetch_councils("2026-11-26", "2026-11-27")), 2)
        self.assertEqual(monitor.fetch_councils("2026-11-26", "2026-11-27"), [], "remembered in state")

    def test_council_card_and_key(self):
        it = dict(monitor.fetch_councils("2026-11-26", "2026-11-27")[0], score=7, summary="s", why="w", action="", ai=True)
        html = monitor.card(it)
        self.assertIn('class="item c-council', html)
        self.assertIn("Council · Pembrokeshire", html)
        page = monitor.render_digest([], 0, "Office", "2026-11-27", "2026-11-26", 6, "./")
        self.assertIn("var(--council)\"></i>Council", page)
        self.assertIn("Official council, Senedd and Westminster business", page)

    def test_one_council_failing(self):
        monitor.COUNCILS[:] = [{"name": "Broken", "url": "https://x.invalid"}, {"name": "Pembrokeshire", "url": "https://mgenglish.pembrokeshire.gov.uk"}]
        real = monitor.get_text
        monitor.get_text = lambda url: (_ for _ in ()).throw(OSError("down")) if "x.invalid" in url else real(url)
        self.assertEqual(len(monitor.fetch_councils("2026-11-26", "2026-11-27")), 2)


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
