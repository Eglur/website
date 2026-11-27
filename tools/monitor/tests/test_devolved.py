"""Offline tests for the Scottish Parliament and NI Assembly sources, and nation routing in Eglur Daily."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor  # noqa: E402
import subscribers  # noqa: E402

HOLYROOD_Q = [
    {"EventID": "S7W-05611", "MSPID": 4987, "Party": "Scottish Conservative and Unionist Party",
     "ApprovedDate": "2026-11-26T16:59:31.597", "SubmissionDateTime": "2026-11-26T14:59:51.75",
     "ItemText": "To ask the Scottish Government what assessment it has made of allergy guidance in schools.",
     "AnswerText": "", "AnswerDate": None},
    {"EventID": "S7W-04000", "MSPID": 21331, "Party": "Scottish Labour",
     "ApprovedDate": "2026-10-01T10:00:00", "ItemText": "To ask the Scottish Government how many buses run in Fife.",
     "AnswerText": "<p>The Scottish Government does not hold this.</p>", "AnswerDate": "2026-11-25T00:00:00"},
    {"EventID": "S7W-03000", "MSPID": 1, "ApprovedDate": "2026-09-01T10:00:00", "ItemText": "Old question.",
     "AnswerText": "", "AnswerDate": None},
]
MSPS = [{"PersonID": 4987, "ParliamentaryName": "Smith, Jane", "PreferredName": "Jane"},
        {"PersonID": 21331, "ParliamentaryName": "Adams, James", "PreferredName": "James"}]

NI_TABLED = {"QuestionsList": {"Question": [
    {"DocumentId": "509275", "Reference": "AQW 57483/22-27", "TablerName": "Mr Nick Mathison",
     "TablerTitle": "MLA - Strangford", "TabledDate": "2026-11-20T00:00:00+00:00",
     "QuestionText": "To ask the Minister for Communities whether any assessment has been made of music services.",
     "Department": "Department for Communities"}]}}
NI_ANSWERED = {"QuestionsList": {"Question": {
    "DocumentId": "509585", "Reference": "AQO 4310/22-27", "TablerName": "Mr Gareth Wilson",
    "TablerTitle": "MLA - Newry and Armagh", "TabledDate": "2026-11-12T00:00:00+00:00",
    "AnsweredOnDate": "2026-11-23T00:00:00+00:00",
    "QuestionText": "To ask the Minister for Communities to outline any support for historic buildings in Armagh city.",
    "Department": "Department for Communities", "AnswerPlainText": "I recognise the heritage assets."}}}


def fake_get_json(url, params):
    if url.endswith("members"):
        return MSPS
    if "motionsquestionsanswersquestions" in url:
        return HOLYROOD_Q
    if "TabledInRange" in url:
        return NI_TABLED
    if "AnsweredInRange" in url:
        return NI_ANSWERED
    raise AssertionError(url)


class DevolvedSources(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(monitor, "get_json", side_effect=fake_get_json)
        p.start()
        self.addCleanup(p.stop)

    def test_holyrood_window_and_shape(self):
        items = {i["ref"]: i for i in monitor.fetch_holyrood_written_questions("2026-11-20", "2026-11-27")}
        self.assertEqual(set(items), {"S7W-05611", "S7W-04000"})     # the September one is outside the window
        q = items["S7W-05611"]
        self.assertEqual((q["house"], q["type"], q["who"]), ("Holyrood", "Written question", "Jane Smith (Scottish Conservative and Unionist Party)"))
        self.assertTrue(q["title"].startswith("What assessment it has made"))
        self.assertIn("ref=S7W-05611", q["url"])
        a = items["S7W-04000"]
        self.assertEqual((a["type"], a["date"]), ("Written answer", "2026-11-25"))
        self.assertIn("ANSWER: The Scottish Government does not hold this.", a["text"])

    def test_stormont_merges_both_feeds(self):
        items = {i["ref"]: i for i in monitor.fetch_stormont_written_questions("2026-11-20", "2026-11-27")}
        self.assertEqual(set(items), {"AQW 57483/22-27", "AQO 4310/22-27"})
        q = items["AQW 57483/22-27"]
        self.assertEqual((q["house"], q["who"], q["body"]), ("Stormont", "Mr Nick Mathison (Strangford)", "Department for Communities"))
        self.assertTrue(q["title"].startswith("Whether any assessment"))
        a = items["AQO 4310/22-27"]
        self.assertEqual((a["type"], a["date"]), ("Written answer", "2026-11-23"))
        self.assertTrue(a["title"].startswith("To outline any support"))
        self.assertIn("docid=509585", a["url"])

    def test_chamber_and_tag(self):
        self.assertEqual(monitor.chamber({"house": "Holyrood"}), "holyrood")
        self.assertIn("Scottish Parliament", monitor.chamber_tag({"house": "Holyrood"}))
        self.assertIn("NI Assembly", monitor.chamber_tag({"house": "Stormont"}))


class NationRouting(unittest.TestCase):
    ITEMS = [{"house": h, "council": c} for h, c in
             [("Senedd", ""), ("Holyrood", ""), ("Stormont", ""), ("Commons", ""), ("Council", "Fife"), ("Council", "Ceredigion")]]

    def kept(self, country, council):
        return [(i["house"], i["council"]) for i in self.ITEMS if subscribers.relevant_place(i, {"country": country, "council": council})]

    def test_scotland(self):
        self.assertEqual(self.kept("Scotland", "Fife"), [("Holyrood", ""), ("Commons", ""), ("Council", "Fife")])

    def test_wales(self):
        self.assertEqual(self.kept("Wales", "Ceredigion"), [("Senedd", ""), ("Commons", ""), ("Council", "Ceredigion")])

    def test_ni(self):
        self.assertEqual(self.kept("Northern Ireland", "Belfast"), [("Stormont", ""), ("Commons", "")])

    def test_england_gets_no_devolved_items(self):
        self.assertEqual(self.kept("England", "Leeds"), [("Commons", "")])

    def test_email_wording(self):
        _, html_doc, _ = subscribers.render_email(
            [{"house": "Holyrood", "title": "Buses in Fife", "summary": "s", "why": "w", "score": 8, "date": "2026-11-25", "url": "u"}],
            {"frequency": "daily"}, {"country": "Scotland", "council": "Fife", "area": "KY1"}, monitor.dt.date(2026, 11, 27))
        self.assertIn("From your council, the Scottish Parliament and Westminster, for Fife.", html_doc)
        self.assertIn("Coverage of Fife Council is coming soon. For now your briefing covers the Scottish Parliament and Westminster.", html_doc)


if __name__ == "__main__":
    unittest.main()


class EmailQuality(unittest.TestCase):
    def test_plain_headline_used_for_title_and_subject(self):
        it = {"house": "Council", "council": "Pembrokeshire", "title": "Review of Decant Feasibility Options Relating to Tenby VC School",
              "headline": "Tenby school: where pupils go during building work", "summary": "s", "score": 8, "date": "2026-11-30", "url": "u"}
        subject, html_doc, text = subscribers.render_email([it], {"frequency": "daily"}, {"country": "Wales", "council": "Pembrokeshire"},
                                                           monitor.dt.date(2026, 11, 27))
        self.assertEqual(subject, "Tenby school: where pupils go during building work")
        self.assertIn(">Tenby school: where pupils go during building work</a>", html_doc)
        self.assertNotIn("Decant", html_doc + text)

    def test_logo_is_an_image(self):
        _, html_doc, _ = subscribers.render_email(
            [{"house": "Commons", "title": "t", "summary": "s", "score": 8, "date": "2026-11-27", "url": "u"}],
            {"frequency": "daily"}, {"country": "England"}, monitor.dt.date(2026, 11, 27))
        self.assertIn('src="https://www.eglurtech.com/img/email-wordmark.png"', html_doc)
        self.assertIn('alt="eglur."', html_doc)

    def test_followed_person_always_included(self):
        items = [{"id": f"x{n}", "house": "Commons", "type": "Written question", "title": "Schools funding", "who": "Someone Else (Labour)",
                  "body": "DfE", "date": "2026-11-27", "text": "schools schools", "url": "u"} for n in range(70)]
        items.append({"id": "mine", "house": "Commons", "type": "Written question", "title": "Fishing quotas",
                      "who": "Henry Tufnell (Labour, Mid and South Pembrokeshire)", "body": "Defra", "date": "2026-11-27",
                      "text": "fish", "url": "u"})
        sub = {"topics": "Schools", "people": "Henry Tufnell MP", "frequency": "daily"}
        got = subscribers.for_subscriber(items, sub, {"country": "Wales", "council": "Pembrokeshire"}, use_ai=False)
        self.assertIn("mine", [i["id"] for i in got])
        self.assertGreaterEqual(next(i for i in got if i["id"] == "mine")["score"], 7)
