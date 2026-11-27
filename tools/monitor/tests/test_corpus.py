"""Offline tests for reading Eglur's shared public corpus (corpus.py). No network."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import corpus  # noqa: E402
import monitor  # noqa: E402
import subscribers  # noqa: E402

BASE = {"document_date": "2026-11-26T00:00:00", "language": "en", "member_party": None, "member_area": None}


def row(**kw):
    return {**BASE, **kw}


ROWS = [
    # A Senedd written question, answered.
    row(document_id="senedd:wq:WQ1", institution_id="senedd", title="Class sizes in secondary schools",
        document_url="https://senedd.example/wq1", passage_id="senedd:wq:WQ1:question", kind="question",
        speaker="Sarah Edwards MS", member_id="senedd:member:1", member_name="Sarah Edwards", member_party="Plaid Cymru",
        passage_date="2026-11-24", text="What will the Cabinet Secretary do to improve class sizes?", passage_url="https://senedd.example/wq1#q",
        written_question={"number": "WQ1", "status": "answered", "tabled": "2026-11-24", "answered": "2026-11-26", "askedBy": "senedd:member:1"}),
    row(document_id="senedd:wq:WQ1", institution_id="senedd", title="Class sizes in secondary schools",
        document_url="https://senedd.example/wq1", passage_id="senedd:wq:WQ1:answer", kind="answer", speaker="Lynne Neagle MS",
        member_id="senedd:member:2", member_name="Lynne Neagle", passage_date="2026-11-26", text="We are investing in teachers.",
        passage_url="https://senedd.example/wq1#a",
        written_question={"number": "WQ1", "status": "answered", "tabled": "2026-11-24", "answered": "2026-11-26", "askedBy": "senedd:member:1"}),
    # A Commons debate: two speeches by the MP, one by someone else, one procedural.
    *[row(document_id="commons:debate:9", institution_id="commons", title="Fishing Industry", document_url="https://hansard.example/9",
          passage_id=f"commons:debate:9:{n}", kind=kind, speaker=sp, member_id=mid, member_name=name, member_party=party,
          passage_date="2026-11-25", text=text, passage_url=f"https://hansard.example/9#{n}", written_question=None)
      for n, (kind, sp, mid, name, party, text) in enumerate([
          ("speech", "Henry Tufnell", "commons:member:5", "Henry Tufnell", "Labour", "Milford Haven's fleet needs certainty."),
          ("speech", "Someone Else", "commons:member:6", "Someone Else", "Conservative", "I agree."),
          ("speech", "Henry Tufnell", "commons:member:5", "Henry Tufnell", "Labour", "Quotas must reflect local catches."),
          ("procedural", "Madam Deputy Speaker", None, None, None, "Order."),
      ])],
    # A written statement.
    row(document_id="commons:statement:3", institution_id="commons", title="Ports update", document_url="https://hansard.example/s3",
        passage_id="commons:statement:3:0", kind="statement", speaker="Minister for Ports", member_id="commons:member:7",
        member_name="A Minister", passage_date="2026-11-25", text="The Government will publish a ports strategy.",
        passage_url="https://hansard.example/s3", written_question=None),
]


class Shapes(unittest.TestCase):
    def setUp(self):
        self.items = {i["id"]: i for i in corpus.items_from_rows(ROWS)}

    def test_written_question_with_its_answer(self):
        q = self.items["corpus-senedd:wq:WQ1"]
        self.assertEqual((q["house"], q["type"], q["ref"], q["date"]), ("Senedd", "Written answer", "WQ1", "2026-11-26"))
        self.assertEqual(q["who"], "Sarah Edwards (Plaid Cymru)")
        self.assertIn("ANSWER: We are investing in teachers.", q["text"])
        self.assertEqual(q["url"], "https://senedd.example/wq1#a")
        self.assertEqual(monitor.chamber(q), "senedd")

    def test_speeches_grouped_by_member_and_procedure_dropped(self):
        mp = self.items["corpus-commons:debate:9-commons:member:5"]
        self.assertEqual((mp["type"], mp["house"], mp["member_id"]), ("Spoke in the chamber", "Commons", "commons:member:5"))
        self.assertIn("Milford Haven's fleet needs certainty. Quotas must reflect local catches.", mp["text"])
        self.assertTrue(mp["title"].startswith("Henry Tufnell spoke: Fishing Industry"))
        self.assertIn("corpus-commons:debate:9-commons:member:6", self.items)
        self.assertFalse(any("Order." in i["text"] for i in self.items.values()))

    def test_statement(self):
        s = self.items["corpus-commons:statement:3:0"]
        self.assertEqual((s["type"], s["house"]), ("Written statement", "Commons"))


class Switching(unittest.TestCase):
    def test_dormant_without_all_three_settings(self):
        with mock.patch.dict(os.environ, {"EGLUR_CORPUS_URL": "https://x.supabase.co", "EGLUR_CORPUS_KEY": "sb_publishable_x"}, clear=True):
            self.assertIsNone(corpus.settings())
            self.assertEqual(corpus.sources(), monitor.SOURCES)

    def test_refuses_a_secret_key(self):
        env = {"EGLUR_CORPUS_URL": "https://x.supabase.co", "EGLUR_CORPUS_KEY": "sb_secret_x", "READER_TOKEN": "t"}
        with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
            corpus.settings()

    def test_when_configured_the_corpus_replaces_senedd_and_commons_but_keeps_the_lords(self):
        env = {"EGLUR_CORPUS_URL": "https://x.supabase.co", "EGLUR_CORPUS_KEY": "sb_publishable_x", "READER_TOKEN": "t"}
        with mock.patch.dict(os.environ, env, clear=True):
            src = corpus.sources()
        self.assertIn("eglur_corpus", src)
        self.assertNotIn("senedd_written_questions", src)
        self.assertIn("holyrood_written_questions", src)
        both = [{"house": "Commons", "id": "c"}, {"house": "Lords", "id": "l"}]
        with mock.patch.object(monitor, "fetch_written_questions", return_value=both):
            self.assertEqual([i["id"] for i in corpus.lords_only(monitor.fetch_written_questions)("a", "b")], ["l"])

    def test_fetch_keeps_the_window(self):
        with mock.patch.object(corpus, "rpc", return_value=ROWS):
            got = corpus.fetch("2026-11-25", "2026-11-25")
        self.assertEqual({i["date"] for i in got}, {"2026-11-25"})


class YourMP(unittest.TestCase):
    MEMBERS = [{"id": "commons:member:5", "institution_id": "commons", "name": "Henry Tufnell", "area_name": "Mid and South Pembrokeshire"},
               {"id": "commons:member:6", "institution_id": "commons", "name": "Someone Else", "area_name": "Elsewhere"}]

    def test_my_mp_by_constituency(self):
        self.assertEqual(corpus.my_representatives({"constituency": "Mid and South Pembrokeshire"}, self.MEMBERS), {"commons:member:5"})
        self.assertEqual(corpus.my_representatives({"constituency": ""}, self.MEMBERS), set())

    def test_my_mps_speech_always_included_and_marked(self):
        items = corpus.items_from_rows(ROWS) + [
            {"id": f"x{n}", "house": "Commons", "type": "Written question", "title": "Schools", "who": "Other",
             "body": "DfE", "date": "2026-11-25", "text": "schools schools", "url": "u"} for n in range(70)]
        geo = {"country": "Wales", "council": "Pembrokeshire", "constituency": "Mid and South Pembrokeshire", "codes": []}
        with mock.patch.object(subscribers, "MEMBERS", self.MEMBERS):
            got = subscribers.for_subscriber(items, {"topics": "Schools", "frequency": "daily"}, geo, use_ai=False)
        mine = next(i for i in got if i["id"] == "corpus-commons:debate:9-commons:member:5")
        self.assertIn("your MP", mine["who"])
        self.assertGreaterEqual(mine["score"], 7)


if __name__ == "__main__":
    unittest.main()
