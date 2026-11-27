"""Offline tests for the Eglur Daily subscriber emails. Run from tools/monitor: python -m unittest discover tests"""
import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import monitor
import subscribers as S

SUB = {"email": "jane@example.com", "area": "SA43 1AB", "topics": "Planning, Health and the NHS",
       "topics_other": "bus routes", "places": "Cardigan, Fishguard", "people": "Cllr Jane Smith, Paul Davies MS",
       "frequency": "daily"}
GEO = {"area": "SA43 1AB", "council": "Ceredigion", "constituency": "Ceredigion Preseli", "country": "Wales", "codes": ["W06000008"]}


def item(**kw):
    base = {"id": "x", "type": "Written answer", "house": "Senedd", "title": "A title", "who": "", "body": "", "date": "2026-11-26",
            "text": "", "url": "https://example.org/a", "score": 7, "summary": "What happened.", "why": "Why it matters to you.",
            "action": "", "ai": True}
    base.update(kw)
    return base


class TestProfile(unittest.TestCase):
    def test_keywords_and_description(self):
        p = S.build_profile(SUB, GEO)
        kw = p["filter"]["keywords"]
        for k in ("planning", "hospital*", "bus routes", "Cardigan", "Fishguard", "Jane Smith", "Paul Davies", "Ceredigion", "Ceredigion Preseli"):
            self.assertIn(k, kw)
        self.assertNotIn("SA43 1AB", kw, "postcodes aren't searched for")
        self.assertIn("Ceredigion council area", p["office"]["description"])
        self.assertFalse(p["member"]["social_drafts"])

    def test_person_names(self):
        self.assertEqual(S.person_name("Cllr Jane Smith"), "Jane Smith")
        self.assertEqual(S.person_name("Paul Davies MS"), "Paul Davies")
        self.assertEqual(S.person_name("Rt Hon Sir Keir Starmer KC MP"), "Keir Starmer")

    def test_due_today(self):
        fri, tue = dt.date(2026, 11, 27), dt.date(2026, 11, 24)
        self.assertTrue(S.due_today({"frequency": "daily"}, tue))
        self.assertFalse(S.due_today({"frequency": "weekly"}, tue))
        self.assertTrue(S.due_today({"frequency": "weekly"}, fri))


class TestSelection(unittest.TestCase):
    def setUp(self):
        self.items = [
            item(id="c1", house="Council", council="Ceredigion", title="Planning committee: new homes in Cardigan", text="planning Cardigan"),
            item(id="c2", house="Council", council="Pembrokeshire", title="Planning committee: Haverfordwest", text="planning"),
            item(id="s1", title="Hospital services", text="hospital waiting times"),
            item(id="w1", house="Commons", title="Defence procurement", text="ships"),
        ]

    def test_only_their_council_and_their_interests(self):
        got = S.for_subscriber(self.items, SUB, GEO, use_ai=False)
        ids = {i["id"] for i in got}
        self.assertIn("c1", ids)
        self.assertNotIn("c2", ids, "other councils are excluded")
        self.assertIn("s1", ids)
        self.assertNotIn("w1", ids, "no matching interest")
        self.assertEqual(self.items[0].get("score"), 7, "shared items aren't modified per subscriber")


class TestEmail(unittest.TestCase):
    def test_render(self):
        items = [item(title="Planning committee meets on Tuesday", house="Council", council="Ceredigion", upcoming=True,
                      date="2026-12-01", time="10.00am", score=9, action="Comment on the application by Monday."),
                 item(title="New station plans", score=7)]
        subject, html, text = S.render_email(items, SUB, GEO, dt.date(2026, 11, 27))
        self.assertEqual(subject, "Planning committee meets on Tuesday, and 1 more")
        self.assertIn("2 things for you today", html)
        self.assertIn("Ceredigion Council &middot; Tue 1 Dec · 10.00am", html)
        self.assertIn("You could:</b> Comment on the application by Monday.", html)
        self.assertIn("{{UNSUBSCRIBE}}", html)
        self.assertIn("{{UNSUBSCRIBE}}", text)
        self.assertLess(html.index("Today"), html.index("Coming up"))
        self.assertNotIn("jane@example.com", html)

    def test_council_not_yet_covered(self):
        _, html, _ = S.render_email([item()], SUB, dict(GEO, council="Cardiff", codes=["W06000015"]), dt.date(2026, 11, 27))
        self.assertIn("Coverage of Cardiff Council is coming soon", html)

    def test_escaping(self):
        _, html, _ = S.render_email([item(title="<script>x</script>", url='https://e.x/?a=1&b="2"')], SUB, GEO, dt.date(2026, 11, 27))
        self.assertNotIn("<script>x", html)
        self.assertIn("&amp;b=&quot;2&quot;", html)


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = Path.cwd()
        import os
        os.chdir(self.tmp)
        self.sent = []
        S.sheet_request = self.fake_sheet
        S.locate = lambda area: dict(GEO, area=area)
        S.collect_all = lambda subs_geo, today, days: [
            item(id="c1", house="Council", council="Ceredigion", title="Planning committee: Cardigan homes", text="planning Cardigan")]
        S.dt = type("D", (), {"date": type("Date", (dt.date,), {"today": staticmethod(lambda: dt.date(2026, 11, 24))}),
                              "timedelta": dt.timedelta})

    def tearDown(self):
        import os
        os.chdir(self.cwd)
        S.dt = dt

    def fake_sheet(self, params=None, body=None):
        if params and params.get("action") == "list":
            return {"ok": True, "quota": 99, "subscribers": [SUB, dict(SUB, email="weekly@example.com", frequency="weekly"),
                                                            dict(SUB, email="bored@example.com", topics="Farming", places="", people="")]}
        self.sent.append(body)
        return {"ok": True}

    def run_main(self, *argv):
        import os
        os.environ.setdefault("SUBSCRIBERS_URL", "https://script.example/exec"); os.environ.setdefault("SUBSCRIBERS_TOKEN", "t")
        sys.argv = ["subscribers.py", "--no-ai", *argv]
        S.main()

    def test_quiet_without_secrets(self):
        import os
        saved = {k: os.environ.pop(k, None) for k in ("SUBSCRIBERS_URL", "SUBSCRIBERS_TOKEN")}
        try:
            sys.argv = ["subscribers.py"]; S.main()
            self.assertEqual(self.sent, [])
        finally:
            for k, v in saved.items():
                if v is not None: os.environ[k] = v

    def test_sends_to_due_subscribers_with_something_relevant(self):
        self.run_main()
        self.assertEqual([b["to"] for b in self.sent], ["jane@example.com"],
                         "weekly subscriber not due on a Tuesday; the farming-only one has nothing relevant")
        self.assertEqual(self.sent[0]["action"], "send")
        self.assertIn("{{UNSUBSCRIBE}}", self.sent[0]["html"])

    def test_dry_run_writes_previews_and_sends_nothing(self):
        self.run_main("--dry-run")
        self.assertEqual(self.sent, [])
        files = list(Path("daily-email/preview").glob("*.html"))
        self.assertEqual(len(files), 1)
        self.assertNotIn("jane", files[0].name)

    def test_only(self):
        self.run_main("--only", "nobody@example.com")
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
