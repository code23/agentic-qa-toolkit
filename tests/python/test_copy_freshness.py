"""copy_freshness.py: stale-copy heuristics, run as a subprocess against a local fixture server."""
import json
import tempfile
import unittest
from pathlib import Path

import qa_support as qs

SCRIPT = qs.SITE_SCRIPTS / "copy_freshness.py"
TODAY = "2026-10-13"   # Q4 2026, the UK is on GMT


class CopyCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / "evidence" / "copy.json"
        self.addCleanup(self._tmp.cleanup)
        self.server = qs.FixtureServer()
        self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)

    def run_it(self, paths, *args, today=TODAY):
        urls = ",".join(self.server.url(p) for p in paths)
        extra = ["--today", today] if today else []
        r = qs.run_script(SCRIPT, urls, "--out", self.out, *extra, *args, cwd=self.tmp)
        return r, (json.loads(self.out.read_text()) if self.out.exists() else None)

    @staticmethod
    def flags(page, kind):
        return [f for f in page["flags"] if f["type"] == kind]


class StaleDates(CopyCase):
    def test_quarters_with_and_without_a_year(self):
        r, d = self.run_it(["/copy_stale.html"])
        self.assertEqual(r.returncode, 0, r.stderr)
        page = d["pages"][0]
        stale = self.flags(page, "stale-quarter")
        texts = " | ".join(f["text"] for f in stale)
        self.assertIn("Q1 2025", texts)
        self.assertIn("Q3 2026", texts)       # earlier than the current quarter (Q4 2026)
        self.assertNotIn("Q4 2026", texts)    # the current quarter is fine
        bare = [f for f in stale if f.get("note") == "no year given"]
        self.assertEqual(len(bare), 1)
        self.assertIn("minutes for Q2", bare[0]["text"])
        ambiguous = self.flags(page, "quarter-ambiguous")
        self.assertEqual(len(ambiguous), 1)   # "Booking for Q2" looks forward and may mean next year
        self.assertIn("Booking for Q2", ambiguous[0]["text"])

    def test_old_year_needs_an_updated_or_reviewed_phrase_and_a_year_before_last_year(self):
        r, d = self.run_it(["/copy_stale.html"])
        old = self.flags(d["pages"][0], "old-year")
        self.assertEqual(len(old), 1)
        self.assertIn("March 2023", old[0]["text"])   # "reviewed 2025" is last year, so it is not flagged

    def test_stale_year_in_a_copyright_line(self):
        r, d = self.run_it(["/copy_stale.html"])
        hits = self.flags(d["pages"][0], "copyright-year")
        self.assertEqual(len(hits), 1)
        self.assertIn("2019", hits[0]["text"])

    def test_copyright_range_is_judged_by_its_end_year(self):
        r, d = self.run_it(["/copy_copyright_range.html"])
        hits = self.flags(d["pages"][0], "copyright-year")
        self.assertEqual(len(hits), 1)
        self.assertIn("2021-2024", hits[0]["text"])
        r, d = self.run_it(["/copy_copyright_current.html"])
        self.assertEqual(self.flags(d["pages"][0], "copyright-year"), [])

    def test_the_reference_date_moves_the_verdict(self):
        r, d = self.run_it(["/copy_copyright_current.html"], today="2027-03-01")
        self.assertEqual(len(self.flags(d["pages"][0], "copyright-year")), 1)   # 2020-2026 ended last year

    def test_clean_page_has_no_flags(self):
        self.server.routes["/garden-planning-guide"] = qs.fixture_bytes("copy_clean.html")   # slug matches the title
        r, d = self.run_it(["/garden-planning-guide"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(d["pages"][0]["flags"], [])
        self.assertEqual(d["pages"][0]["coverage"], "full")


class Timezone(CopyCase):
    """timezone-label: out-of-season abbreviations of the zone given with --timezone; no zone, no check."""

    def labels(self, today, zone, path="/copy_tz.html", *args):
        r, d = self.run_it([path], "--timezone", zone, *args, today=today)
        self.assertEqual(r.returncode, 0, r.stderr)
        return d, [f["text"] for f in self.flags(d["pages"][0], "timezone-label")]

    def page_with(self, text, path="/tz-page"):
        self.server.routes[path] = qs.html(f"<p>{text}</p>", title="Opening times")
        return path

    def test_london_gmt_is_wrong_in_summer_and_bst_is_wrong_in_winter(self):
        d, summer = self.labels("2026-07-01", "Europe/London")
        self.assertEqual((d["timezone"], d["timezone_in_force"], d["timezone_out_of_season"]), ("Europe/London", "BST", ["GMT"]))
        self.assertTrue(d["timezone_check"].startswith("run: BST in force on 2026-07-01"))
        self.assertEqual(len(summer), 1)
        self.assertIn("GMT", summer[0])
        d, winter = self.labels("2026-01-15", "Europe/London")
        self.assertEqual((d["timezone_in_force"], d["timezone_out_of_season"]), ("GMT", ["BST"]))
        self.assertEqual(len(winter), 1)
        self.assertIn("BST", winter[0])
        flag = self.flags(d["pages"][0], "timezone-label")[0]
        self.assertIn("Europe/London is currently on GMT", flag["note"])

    def test_london_clock_change_days_2026(self):
        # BST runs from the last Sunday of March (29 March 2026) up to the last Sunday of October (25 October 2026)
        expect = {"2026-03-28": "GMT", "2026-03-29": "BST", "2026-10-24": "BST", "2026-10-25": "GMT"}
        for day, in_force in expect.items():
            with self.subTest(day):
                d, _ = self.labels(day, "Europe/London")
                self.assertEqual(d["timezone_in_force"], in_force)

    def test_new_york_est_and_edt(self):
        path = self.page_with("Call us 9am EST or 10am EDT on weekdays.")
        d, summer = self.labels("2026-07-01", "America/New_York", path)
        self.assertEqual((d["timezone_in_force"], d["timezone_out_of_season"]), ("EDT", ["EST"]))
        self.assertEqual(len(summer), 1)
        self.assertIn("EST", summer[0])
        d, winter = self.labels("2026-01-15", "America/New_York", path)
        self.assertEqual(len(winter), 1)
        self.assertIn("EDT", winter[0])

    def test_paris_cet_and_cest(self):
        path = self.page_with("Open 9:00 CET to 17:00 CEST.")
        d, summer = self.labels("2026-07-01", "Europe/Paris", path)
        self.assertEqual((d["timezone_in_force"], d["timezone_out_of_season"]), ("CEST", ["CET"]))
        self.assertEqual(len(summer), 1)
        self.assertIn("CET", summer[0])
        d, winter = self.labels("2026-01-15", "Europe/Paris", path)
        self.assertEqual(len(winter), 1)
        self.assertIn("CEST", winter[0])

    def test_sydney_seasons_are_reversed(self):
        path = self.page_with("Support runs 9am AEST and 9am AEDT.")
        d, january = self.labels("2026-01-15", "Australia/Sydney", path)
        self.assertEqual((d["timezone_in_force"], d["timezone_out_of_season"]), ("AEDT", ["AEST"]))
        self.assertIn("AEST", january[0])
        d, july = self.labels("2026-07-15", "Australia/Sydney", path)
        self.assertEqual((d["timezone_in_force"], d["timezone_out_of_season"]), ("AEST", ["AEDT"]))
        self.assertIn("AEDT", july[0])

    def test_abbreviations_match_whole_words_only(self):
        path = self.page_with("See GMTX, xGMT, GMT0 and the text BSTRING. A real one: 9am GMT.")
        d, found = self.labels("2026-07-01", "Europe/London", path)
        self.assertEqual(len(found), 1)
        self.assertIn("9am GMT", found[0])

    def test_zones_without_a_seasonal_pair_are_not_applicable_and_flag_nothing(self):
        path = self.page_with("Open 9am JST, 10am GMT, 11am BST, 12 +03.")
        for zone in ("Asia/Tokyo", "Asia/Dubai", "Etc/UTC", "America/Sao_Paulo"):
            with self.subTest(zone):
                d, found = self.labels("2026-07-01", zone, path)
                self.assertEqual(found, [])
                self.assertTrue(d["timezone_check"].startswith("not applicable"), d["timezone_check"])
                self.assertIn(zone, d["timezone_check"])
                self.assertEqual(d["timezone_out_of_season"], [])

    def test_no_timezone_means_not_run_and_says_so(self):
        r, d = self.run_it(["/copy_tz.html"], today="2026-07-01")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(d["timezone_check"], "not run (no --timezone given)")
        self.assertIsNone(d["timezone"])
        self.assertIsNone(d["timezone_in_force"])
        self.assertEqual(self.flags(d["pages"][0], "timezone-label"), [])
        self.assertIn("not run (no --timezone given)", d["note"])
        self.assertNotIn("market", d)
        self.assertNotIn("uk_bst", d)

    def test_unknown_zone_exits_2_before_any_request(self):
        for zone in ("Mars/Olympus", "Europe/Londonn", "", "../../etc/passwd", "UK time"):
            with self.subTest(zone):
                r = qs.run_script(SCRIPT, self.server.url("/copy_clean.html"), "--timezone", zone, "--out", self.out, cwd=self.tmp)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
                self.assertIn("time zone", r.stderr)
        self.assertEqual(self.server.requests, [])
        self.assertFalse(self.out.exists())

    def test_missing_time_zone_data_exits_2_before_any_request(self):
        empty = self.tmp / "no-tzdata"
        empty.mkdir()
        r = qs.run_script(SCRIPT, self.server.url("/copy_clean.html"), "--timezone", "Europe/London", "--out", self.out,
                          env={"PYTHONTZPATH": str(empty)}, cwd=self.tmp)
        if r.returncode == 0:
            self.skipTest("the tzdata package supplies zones even without system data")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("no time zone data", r.stderr)
        self.assertEqual(self.server.requests, [])

    def test_abbreviations_that_are_english_words_only_count_next_to_a_time(self):
        # Europe/Lisbon is WET in winter and WEST in summer, so in July "WET" is the out-of-season label
        path = self.page_with("WET weather closes the garden. Phone lines open 9am WET and also WET 10:00.")
        d, found = self.labels("2026-07-01", "Europe/Lisbon", path)
        self.assertEqual(d["timezone_out_of_season"], ["WET"])
        self.assertEqual(len(found), 2)   # "9am WET" and "WET 10:00"; the capitalised word "WET weather" is not a label

    def test_est_dot_year_is_not_a_time_zone_label(self):
        path = self.page_with("Family run since EST. 1994 in New York. Call 9am EST.")
        d, found = self.labels("2026-07-01", "America/New_York", path)
        self.assertEqual(len(found), 1)
        self.assertIn("9am EST", found[0])


class OtherChecks(CopyCase):
    def test_placeholders_and_repeated_sentences(self):
        r, d = self.run_it(["/copy_placeholder.html"])
        page = d["pages"][0]
        found = " | ".join(f["text"] for f in self.flags(page, "placeholder")).lower()
        self.assertIn("lorem ipsum", found)
        self.assertIn("coming soon", found)
        rep = self.flags(page, "repeated-sentence")
        self.assertEqual([f["count"] for f in rep], [3])
        self.assertIn("repeats on this page", rep[0]["text"])

    def test_title_and_slug_mismatch(self):
        self.server.routes["/spring-offers-banner"] = qs.html("<p>Benches and tables for the garden patio.</p>", title="Garden furniture")
        r, d = self.run_it(["/spring-offers-banner"])
        hit = self.flags(d["pages"][0], "title-slug-mismatch")
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["title"], "Garden furniture")

    def test_matching_title_and_slug_is_fine(self):
        self.server.routes["/garden-furniture"] = qs.html("<p>Benches and tables for the garden patio.</p>", title="Garden furniture | Example")
        r, d = self.run_it(["/garden-furniture"])
        self.assertEqual(self.flags(d["pages"][0], "title-slug-mismatch"), [])

    def test_personal_email_addresses_are_counted_never_stored(self):
        r, d = self.run_it(["/copy_emails.html"])
        raw = self.out.read_text()
        self.assertNotIn("jane.doe", raw)
        self.assertEqual(d["pages"][0]["personal_emails_seen"], 1)

    def test_cross_page_variants(self):
        r, d = self.run_it(["/copy_emails.html", "/copy_emails_b.html"])
        v = d["cross_page_variants"]
        self.assertNotIn("jane.doe", self.out.read_text())
        self.assertEqual(set(v["email"]), {"info@example.com", "hello@example.com"})
        self.assertEqual(set(v["established"]), {"1994", "1998"})
        self.assertEqual(set(v["stat:customers"]), {"25", "30"})
        self.assertEqual(len(v["phone"]), 2)
        for kind in v.values():
            for urls in kind.values():
                self.assertTrue(all("?" not in u for u in urls))

    def test_identical_facts_are_not_variants(self):
        r, d = self.run_it(["/copy_emails.html", "/copy_emails.html"])
        self.assertEqual(d["cross_page_variants"], {})


class SlugHandling(CopyCase):
    """title-slug-mismatch: the slug is the last URL segment without its file extension or a trailing index."""

    def slug_flag(self, path, title):
        self.server.routes[path] = qs.html("<p>Body text for the slug test page.</p>", title=title)
        r, d = self.run_it([path])
        self.assertEqual(r.returncode, 0, r.stderr)
        hits = self.flags(d["pages"][0], "title-slug-mismatch")
        return hits[0] if hits else None

    def test_file_extension_is_not_part_of_the_slug(self):
        for ext in (".html", ".htm", ".php", ".aspx"):
            with self.subTest(ext):
                self.assertIsNone(self.slug_flag("/chain-care-guide" + ext, "Chain care guide | Example"))
                self.assertEqual(self.slug_flag("/chain-care-guide" + ext, "Zebra mountains")["slug"], "chain-care-guide")

    def test_trailing_slash(self):
        self.assertEqual(self.slug_flag("/chain-care-guide/", "Zebra mountains")["slug"], "chain-care-guide")
        self.assertIsNone(self.slug_flag("/chain-care-guide/", "Chain care guide"))

    def test_a_trailing_index_segment_is_dropped(self):
        self.assertIsNone(self.slug_flag("/guides/chain-care-guide/index.html", "Chain care guide"))
        self.assertEqual(self.slug_flag("/guides/chain-care-guide/index.html", "Zebra mountains")["slug"], "chain-care-guide")
        self.assertEqual(self.slug_flag("/chain-care-guide/index.php", "Zebra mountains")["slug"], "chain-care-guide")

    def test_dots_that_are_not_an_extension_stay_in_the_slug(self):
        self.assertIsNone(self.slug_flag("/v2.1-release-notes", "v2.1 release notes"))
        self.assertIsNone(self.slug_flag("/v2.1-release-notes.html", "v2.1 release notes"))
        self.assertEqual(self.slug_flag("/v2.1-release-notes", "Zebra mountains")["slug"], "v2-1-release-notes")

    def test_one_word_slugs_are_skipped(self):
        for path in ("/pricing.html", "/pricing", "/guides/index.html", "/index.html", "/oakhaven.html"):
            with self.subTest(path):
                self.assertIsNone(self.slug_flag(path, "Zebra mountains"))

    def test_stop_words_do_not_count_towards_the_two_word_minimum(self):
        self.assertIsNone(self.slug_flag("/how-to-pricing", "Zebra mountains"))   # "how" and "to" are stop words


class RunBehaviour(CopyCase):
    def test_failed_url_exits_1_and_is_listed(self):
        r, d = self.run_it(["/copy_clean.html", "/nope"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED:", r.stdout)
        bad = d["pages"][1]
        self.assertEqual((bad["status"], bad["error"], bad["flags"]), (404, "HTTP 404", []))
        self.assertTrue(d["complete"])

    def test_redirect_to_another_host_is_a_failed_url_and_is_never_requested(self):
        with qs.FixtureServer({"/page": qs.fixture_bytes("copy_clean.html")}) as other:
            self.server.routes["/moved"] = (301, {"Location": other.url("/page")}, b"")
            r, d = self.run_it(["/copy_clean.html", "/moved"])
            self.assertEqual(other.requests, [])
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED:", r.stdout)
        self.assertIn("redirect to a host outside the input URLs", r.stdout)
        self.assertIn("outside the input URLs", d["pages"][1]["error"])
        self.assertEqual(d["pages"][1]["flags"], [])

    def test_query_strings_never_reach_the_evidence_file(self):
        self.server.routes["/q"] = qs.html("<p>Plain page for the query test.</p>")
        urls = self.server.url("/q") + "?session=abcdef1234567890abcdef"
        r = qs.run_script(SCRIPT, urls, "--out", self.out, "--today", TODAY, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("abcdef1234567890", self.out.read_text())
        self.assertNotIn("abcdef1234567890", r.stdout)

    def test_max_pages_skips_the_rest_without_fetching_them(self):
        r, d = self.run_it(["/copy_clean.html", "/copy_stale.html"], "--max-pages", "1")
        self.assertTrue(d["pages"][1]["status"].startswith("skipped (over --max-pages 1)"))
        self.assertEqual(len(self.server.hits("/copy_stale.html")), 0)

    def test_url_list_from_a_file(self):
        f = self.tmp / "urls.txt"
        f.write_text(f"# one page\n{self.server.url('/copy_clean.html')}\n", encoding="utf-8")
        r = qs.run_script(SCRIPT, f, "--out", self.out, "--today", TODAY, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(json.loads(self.out.read_text())["pages"]), 1)

    def test_default_output_path_is_evidence_copy_json_in_the_working_folder(self):
        r = qs.run_script(SCRIPT, self.server.url("/copy_clean.html"), "--today", TODAY, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "evidence" / "copy.json").is_file())


class UsageErrors(CopyCase):
    def test_bad_options_exit_2_before_any_request(self):
        url = self.server.url("/copy_clean.html")
        for args in ([url, "--today", "13/10/2026"], [url, "--today", "2026-13-40"], [url, "--delay", "0.1"], [url, "--delay", "nan"],
                     [url, "--max-pages", "0"], [url, "--bogus"], ["ftp://example.com/x"],
                     ["https://user:pw@example.com/"], [""]):
            with self.subTest(args):
                r = qs.run_script(SCRIPT, *args, "--out", self.out, cwd=self.tmp)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.server.requests, [])
        self.assertFalse(self.out.exists())

    def test_help_works(self):
        r = qs.run_script(SCRIPT, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("stale-quarter", r.stdout)


if __name__ == "__main__":
    unittest.main()
