"""similarity.py: duplicate-content pass, run as a subprocess against a local fixture server."""
import json
import tempfile
import time
import unittest
from pathlib import Path

import qa_support as qs

SCRIPT = qs.SITE_SCRIPTS / "similarity.py"
EAST, WEST, VARIANT, DIFFERENT = "/loc_eastbrook.html", "/loc_westmere.html", "/loc_variant.html", "/loc_different.html"
SHORT_A, SHORT_B, CSR = "/short_a.html", "/short_b.html", "/csr_shell.html"


class SimilarityCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / "evidence" / "similarity.json"
        self.addCleanup(self._tmp.cleanup)
        self.server = qs.FixtureServer()
        self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)

    def run_it(self, paths, *args, urls_arg=None):
        urls = urls_arg if urls_arg is not None else ",".join(self.server.url(p) for p in paths)
        r = qs.run_script(SCRIPT, urls, "--out", self.out, *args, cwd=self.tmp)
        data = json.loads(self.out.read_text()) if self.out.exists() else None
        return r, data

    def pair(self, data, a, b):
        pa, pb = self.server.url(a), self.server.url(b)
        for p in data["pairs"]:
            if {p["a"], p["b"]} == {pa, pb}:
                return p
        self.fail(f"no pair for {a} / {b}")


class Comparison(SimilarityCase):
    def test_masking_place_names_turns_a_template_clone_into_a_flagged_pair(self):
        r, d = self.run_it([EAST, WEST, DIFFERENT])
        self.assertEqual(r.returncode, 0, r.stderr)
        p = self.pair(d, EAST, WEST)
        self.assertFalse(p["flag"])           # town names differ throughout, so unmasked it falls under the threshold
        self.assertLess(p["jaccard5"], 0.9)
        self.assertEqual(d["masked_names"], [])

        r, d = self.run_it([EAST, WEST, DIFFERENT], "--mask", "Eastbrook, Westmere")
        p = self.pair(d, EAST, WEST)
        self.assertTrue(p["flag"])
        self.assertEqual((p["jaccard5"], p["seq_ratio"]), (1.0, 1.0))
        self.assertEqual(p["decided_on"], "max(jaccard5, seq_ratio)")
        self.assertEqual(d["masked_names"], ["Eastbrook", "Westmere"])
        self.assertFalse(self.pair(d, EAST, DIFFERENT)["flag"])
        self.assertIn("flagged pairs: 1 of 3", r.stdout)

    def test_mask_file_and_mask_are_combined_and_matching_ignores_case(self):
        names = self.tmp / "names.txt"
        names.write_text("EASTBROOK\n\nwestmere\n", encoding="utf-8")
        r, d = self.run_it([EAST, WEST], "--mask-file", names)
        self.assertTrue(self.pair(d, EAST, WEST)["flag"])
        self.assertEqual(d["masked_names"], ["EASTBROOK", "westmere"])

    def test_threshold_decides_the_flag(self):
        # East vs variant: 4 of 20 sentences rewritten, so moderately similar
        r, d = self.run_it([EAST, VARIANT], "--mask", "Eastbrook", "--threshold", "0.5")
        p = self.pair(d, EAST, VARIANT)
        self.assertTrue(p["flag"])
        score = max(p["jaccard5"], p.get("seq_ratio", 0))
        self.assertGreaterEqual(score, 0.5)
        self.assertLess(score, 0.99)
        r, d = self.run_it([EAST, VARIANT], "--mask", "Eastbrook", "--threshold", "0.99")
        self.assertFalse(self.pair(d, EAST, VARIANT)["flag"])
        self.assertEqual(d["threshold"], 0.99)

    def test_threshold_is_inclusive_at_one(self):
        r, d = self.run_it([EAST, WEST], "--mask", "Eastbrook,Westmere", "--threshold", "1")
        self.assertTrue(self.pair(d, EAST, WEST)["flag"])

    def test_pages_record_root_words_and_coverage(self):
        r, d = self.run_it([EAST, WEST])
        page = d["pages"][0]
        self.assertEqual((page["status"], page["root"], page["coverage"], page["error"]), (200, "main", "full", None))
        self.assertGreater(page["words"], 300)
        self.assertTrue(d["complete"])
        self.assertIn("5-word shingle", d["method"])


class Inconclusive(SimilarityCase):
    def test_pages_under_the_minimum_word_count_are_never_flagged(self):
        r, d = self.run_it([SHORT_A, SHORT_B], "--mask", "Eastbrook,Westmere")   # identical once masked, but only ~16 words
        p = self.pair(d, SHORT_A, SHORT_B)
        self.assertEqual((p["status"], p["flag"]), ("inconclusive", False))
        self.assertIn("fewer than 150 words", p["reason"])
        self.assertNotIn("jaccard5", p)
        self.assertIn("inconclusive: 1", r.stdout)

    def test_min_words_option_changes_what_counts_as_short(self):
        r, d = self.run_it([SHORT_A, SHORT_B], "--mask", "Eastbrook,Westmere", "--min-words", "5")
        p = self.pair(d, SHORT_A, SHORT_B)
        self.assertEqual(p["status"], "compared")
        self.assertTrue(p["flag"])

    def test_client_rendered_shell_makes_every_pair_with_it_inconclusive(self):
        r, d = self.run_it([EAST, CSR], "--min-words", "5")
        page = next(p for p in d["pages"] if p["url"].endswith(CSR))
        self.assertTrue(page["csr_hint"])
        self.assertEqual(page["coverage"], "limited (client-rendered)")
        p = self.pair(d, EAST, CSR)
        self.assertEqual((p["status"], p["flag"]), ("inconclusive", False))
        self.assertIn("client-rendered", p["reason"])
        self.assertIn(self.server.url(CSR), p["reason"])

    def test_served_text_far_below_rendered_text_is_limited_coverage(self):
        rendered = self.tmp / "overflow.json"
        rendered.write_text(json.dumps({"results": [{"url": self.server.url(EAST), "renderedWords": 345},
                                                    {"url": self.server.url(WEST), "renderedWords": 2000}]}), encoding="utf-8")
        r, d = self.run_it([EAST, WEST], "--mask", "Eastbrook,Westmere", "--rendered", rendered)
        cov = {p["url"].rsplit("/", 1)[1]: p["coverage"] for p in d["pages"]}
        self.assertEqual(cov, {"loc_eastbrook.html": "full", "loc_westmere.html": "limited (client-rendered)"})
        self.assertEqual(self.pair(d, EAST, WEST)["status"], "inconclusive")


class FailuresAndAliases(SimilarityCase):
    def test_failed_url_gives_exit_1_but_output_is_still_written(self):
        r, d = self.run_it([EAST, "/nope", WEST], "--mask", "Eastbrook,Westmere")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED:", r.stdout)
        missing = next(p for p in d["pages"] if p["url"].endswith("/nope"))
        self.assertEqual((missing["status"], missing["error"]), (404, "HTTP 404"))
        self.assertTrue(self.pair(d, EAST, WEST)["flag"])   # the other pages are still compared
        self.assertTrue(d["complete"])

    def test_two_urls_ending_on_the_same_page_are_not_compared_with_each_other(self):
        self.server.routes["/old-east"] = (301, {"Location": EAST}, b"")
        r, d = self.run_it(["/old-east", EAST, DIFFERENT])
        self.assertEqual(r.returncode, 0, r.stderr)
        first = next(p for p in d["pages"] if p["url"].endswith("/old-east"))
        self.assertEqual(first["redirects"], [f"301 {self.server.url('/old-east')}"])
        self.assertNotIn("alias_of", first)
        second = next(p for p in d["pages"] if p["url"].endswith(EAST))
        self.assertTrue(second["alias_of"].endswith("/old-east"), second)
        self.assertEqual(len(d["pairs"]), 1)   # the alias is left out: only old-east vs different remain
        self.assertEqual(self.pair(d, "/old-east", DIFFERENT)["status"], "compared")

    def test_redirect_to_another_host_is_a_failed_url_and_is_never_requested(self):
        with qs.FixtureServer({"/east": qs.fixture_bytes("loc_eastbrook.html")}) as other:
            self.server.routes["/moved"] = (302, {"Location": other.url("/east")}, b"")
            r, d = self.run_it([EAST, "/moved", WEST], "--mask", "Eastbrook,Westmere")
            self.assertEqual(other.requests, [])
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED:", r.stdout)
        self.assertIn("redirect to a host outside the input URLs", r.stdout)
        moved = next(p for p in d["pages"] if p["url"].endswith("/moved"))
        self.assertIn("outside the input URLs", moved["error"])
        self.assertTrue(self.pair(d, EAST, WEST)["flag"])   # the remaining pages are still compared

    def test_max_pages_skips_the_rest(self):
        r, d = self.run_it([EAST, WEST, DIFFERENT], "--max-pages", "2")
        self.assertTrue(d["pages"][2]["status"].startswith("skipped (over --max-pages 2)"))
        self.assertEqual(len(d["pairs"]), 1)

    def test_url_list_from_a_file_with_comments(self):
        f = self.tmp / "urls.txt"
        f.write_text(f"# group\n{self.server.url(EAST)}\n\n{self.server.url(WEST)}\n", encoding="utf-8")
        r, d = self.run_it(None, urls_arg=str(f))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(d["pages"]), 2)


class BoundedWork(SimilarityCase):
    def repetitive(self, name, repeats=700, tail=""):
        text = ("alpha beta gamma delta epsilon zeta eta theta " * repeats) + tail
        self.server.routes[name] = qs.html(f"<p>{text}</p>", title=name.strip("/"))

    def test_long_repetitive_pages_finish_quickly_and_skip_the_quadratic_comparison(self):
        self.repetitive("/rep-a", tail="omega")
        self.repetitive("/rep-b", repeats=690, tail="omega")   # ~32,000 characters each, nearly identical
        t0 = time.time()
        r, d = self.run_it(["/rep-a", "/rep-b"])
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p = self.pair(d, "/rep-a", "/rep-b")
        self.assertTrue(p["seq_limited"])
        self.assertNotIn("seq_ratio", p)
        self.assertNotIn("seq_ratio_prefix", p)
        self.assertEqual(p["decided_on"], "jaccard5 only (seq_limited)")
        self.assertTrue(p["flag"])   # the cheap score still catches the duplicate

    def test_max_chars_default_is_low_and_can_be_raised(self):
        self.repetitive("/rep-a", repeats=100)    # ~4,600 characters: under the default limit
        self.repetitive("/rep-b", repeats=100, tail="sigma")
        r, d = self.run_it(["/rep-a", "/rep-b"], "--min-words", "5")
        p = self.pair(d, "/rep-a", "/rep-b")
        self.assertNotIn("seq_limited", p)
        self.assertIn("seq_ratio", p)
        r, d = self.run_it(["/rep-a", "/rep-b"], "--min-words", "5", "--max-chars", "1000")
        self.assertTrue(self.pair(d, "/rep-a", "/rep-b")["seq_limited"])

    def test_exhausted_time_budget_skips_the_remaining_pairs_and_exits_1(self):
        r, d = self.run_it([EAST, WEST, DIFFERENT], "--time-budget", "1e-9")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(len(d["pairs"]), 3)
        for p in d["pairs"]:
            self.assertEqual((p["status"], p["flag"]), ("skipped (time budget)", False))
        self.assertIn("skipped (time budget)", r.stdout)
        self.assertTrue(d["complete"])
        self.assertEqual(d["time_budget"], 1e-9)

    def test_generous_budget_changes_nothing(self):
        r, d = self.run_it([EAST, WEST], "--mask", "Eastbrook,Westmere", "--time-budget", "600")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.pair(d, EAST, WEST)["flag"])

    def test_bad_time_budget_is_a_usage_error(self):
        for value in ("0", "-1", "nan", "inf", "soon"):
            r = qs.run_script(SCRIPT, self.server.url(EAST) + "," + self.server.url(WEST), "--time-budget", value, "--out", self.out, cwd=self.tmp)
            self.assertEqual(r.returncode, 2, value)


class UsageErrors(SimilarityCase):
    def assert_usage_error(self, *args, urls=None):
        r = qs.run_script(SCRIPT, urls or self.server.url(EAST) + "," + self.server.url(WEST), "--out", self.out, *args, cwd=self.tmp)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.server.requests, [], "nothing may be fetched after a usage error")

    def test_bad_options_exit_2_before_any_request(self):
        for args in (["--threshold", "0"], ["--threshold", "1.5"], ["--threshold", "nan"], ["--delay", "0.1"], ["--delay", "inf"],
                     ["--min-words", "0"], ["--max-pages", "1"], ["--max-chars", "10"], ["--unknown-option"], ["--threshold", "high"]):
            with self.subTest(args):
                self.assert_usage_error(*args)

    def test_bad_urls_exit_2_before_any_request(self):
        for urls in ("ftp://example.com/a", "https://user:pw@example.com/", "not a url", ""):
            with self.subTest(urls):
                r = qs.run_script(SCRIPT, urls, "--out", self.out, cwd=self.tmp)
                self.assertEqual(r.returncode, 2)

    def test_help_works(self):
        r = qs.run_script(SCRIPT, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--threshold", r.stdout)


if __name__ == "__main__":
    unittest.main()
