"""The Python scripts against demo-site/: every fault its README assigns to copy_freshness.py or similarity.py is reported,
and the clean control page raises none of those flags."""
import functools
import json
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import qa_support as qs

DEMO = qs.ROOT / "demo-site"
COPY = qs.SITE_SCRIPTS / "copy_freshness.py"
SIM = qs.SITE_SCRIPTS / "similarity.py"
PAGES = ["index.html", "brindlemere.html", "oakhaven.html", "mobile-service.html", "pricing.html", "contact.html",
         "privacy.html", "chain-care-guide.html"]


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class DemoSiteCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(Quiet, directory=str(DEMO))
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls._tmp.cleanup()

    @classmethod
    def run_script(cls, script, name, pages, *args):
        out = cls.tmp / f"{name}.json"
        r = qs.run_script(script, ",".join(f"{cls.base}/{p}" for p in pages), "--out", out, *args, cwd=cls.tmp)
        return r, json.loads(out.read_text())

    def page(self, data, name):
        return next(p for p in data["pages"] if p["url"] == f"{self.base}/{name}")


class CopyFreshnessOnDemoSite(DemoSiteCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result, cls.data = cls.run_script(COPY, "copy", PAGES, "--today", "2026-07-15", "--timezone", "Europe/London")

    def types(self, name):
        return [f["type"] for f in self.page(self.data, name)["flags"]]

    def test_run_completed(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        self.assertTrue(self.data["complete"])
        self.assertEqual((self.data["timezone_in_force"], self.data["timezone_out_of_season"]), ("BST", ["GMT"]))

    def test_row_14_stale_quarter_old_year_and_copyright_year_on_pricing(self):
        flags = self.page(self.data, "pricing.html")["flags"]
        by_type = {t: [f["text"] for f in flags if f["type"] == t] for t in ("stale-quarter", "old-year", "copyright-year")}
        self.assertTrue(any("Q1 2024" in t for t in by_type["stale-quarter"]), by_type)
        self.assertTrue(any("2022" in t for t in by_type["old-year"]), by_type)
        self.assertTrue(any("2021" in t for t in by_type["copyright-year"]), by_type)

    def test_row_15_gmt_label_in_summer_on_contact(self):
        hits = [f for f in self.page(self.data, "contact.html")["flags"] if f["type"] == "timezone-label"]
        self.assertTrue(hits and all("GMT" in f["text"] for f in hits), hits)

    def test_row_16_lorem_ipsum_on_contact(self):
        hits = [f for f in self.page(self.data, "contact.html")["flags"] if f["type"] == "placeholder"]
        self.assertTrue(any("lorem ipsum" in f["text"].lower() for f in hits), hits)

    def test_row_18_title_slug_mismatch_on_mobile_service(self):
        hits = [f for f in self.page(self.data, "mobile-service.html")["flags"] if f["type"] == "title-slug-mismatch"]
        self.assertEqual(len(hits), 1, self.page(self.data, "mobile-service.html")["flags"])
        self.assertEqual(hits[0]["title"], "Workshop opening hours")
        self.assertEqual(hits[0]["slug"], "mobile-service")

    def test_no_other_page_gets_a_title_slug_flag(self):
        for name in ("oakhaven.html", "brindlemere.html", "chain-care-guide.html"):
            with self.subTest(name):
                self.assertEqual(self.types(name).count("title-slug-mismatch"), 0, self.page(self.data, name)["flags"])

    def test_control_page_has_no_flags(self):
        page = self.page(self.data, "chain-care-guide.html")
        self.assertEqual(page["flags"], [])
        self.assertEqual(page["coverage"], "full")

    def test_personal_email_and_token_like_reference_on_pricing_never_reach_the_output(self):
        raw = (self.tmp / "copy.json").read_text() + self.result.stdout
        self.assertNotIn("workshop.lead", raw)
        self.assertNotIn("QX7R2M9KLP4W8ZC3VB6N5A", raw)
        self.assertGreaterEqual(self.page(self.data, "pricing.html")["personal_emails_seen"], 1)


class SimilarityOnDemoSite(DemoSiteCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result, cls.data = cls.run_script(SIM, "similarity", ["brindlemere.html", "oakhaven.html", "mobile-service.html"],
                                              "--mask", "Brindlemere,Oakhaven")

    def pair(self, a, b):
        want = {f"{self.base}/{a}", f"{self.base}/{b}"}
        return next(p for p in self.data["pairs"] if {p["a"], p["b"]} == want)

    def test_row_17_only_the_two_location_pages_are_flagged(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        twin = self.pair("brindlemere.html", "oakhaven.html")
        self.assertEqual((twin["status"], twin["flag"]), ("compared", True), twin)
        flagged = [p for p in self.data["pairs"] if p["flag"]]
        self.assertEqual(len(flagged), 1, self.data["pairs"])
        for other in (("brindlemere.html", "mobile-service.html"), ("oakhaven.html", "mobile-service.html")):
            p = self.pair(*other)
            self.assertEqual((p["status"], p["flag"]), ("compared", False), p)


if __name__ == "__main__":
    unittest.main()
