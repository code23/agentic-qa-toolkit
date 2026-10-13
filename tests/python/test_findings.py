"""findings.py: validation, fingerprints, coverage-aware scoring and regression diff."""
import json
import re
import tempfile
import unittest
from pathlib import Path

import qa_support as qs

SCRIPT = qs.SITE_SCRIPTS / "findings.py"
F = qs.load_module("qa_findings", SCRIPT)


def finding(fid="R-01", **kw):
    f = {"id": fid, "title": "Contrast too low in header", "severity": "S3", "verification": "evidence-reviewed", "label": "DET",
         "dimension": "accessibility", "template": "service", "url": "https://example.com/services/x/", "rule": "color-contrast:header",
         "status": "open"}
    f.update(kw)
    return f


def cov(status, checks=("c",), note=""):
    return {"status": status, "checks": list(checks), "note": note}


def run_doc(findings=(), checks_run=(), coverage=None, run_id="example-com-2026-01-10", date="2026-01-10", target="https://example.com", **kw):
    full = {d: cov("executed", ("walk: home",)) for d in F.DIMS}
    full.update(coverage or {})
    d = {"run_id": run_id, "target": target, "date": date, "scores": {}, "coverage": full, "checks_run": list(checks_run),
         "findings": list(findings), "improvements": []}
    d.update(kw)
    return d


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, doc):
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(doc if isinstance(doc, str) else json.dumps(doc, indent=1), encoding="utf-8")
        return p

    def cli(self, *args):
        return qs.run_script(SCRIPT, *args)


class Validation(unittest.TestCase):
    def test_a_complete_run_is_valid(self):
        self.assertEqual(F.validate(run_doc([finding()])), [])

    def test_template_output_is_valid_and_every_dimension_starts_not_executed(self):
        r = qs.run_script(SCRIPT, "template")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual(set(doc["coverage"]), set(F.DIMS))
        self.assertTrue(all(c["status"] == "not-executed" for c in doc["coverage"].values()))
        self.assertEqual(F.validate(doc), [])

    def test_each_problem_is_reported(self):
        cases = {
            "missing title": run_doc([finding(title="")]),
            "bad severity": run_doc([finding(severity="S9")]),
            "bad dimension": run_doc([finding(dimension="vibes")]),
            "bad scope": run_doc([finding(scope="galaxy")]),
            "duplicate id": run_doc([finding("R-01"), finding("R-01", rule="other")]),
            "page scope without url": run_doc([finding(scope="page", url="")]),
            "non-http url": run_doc([finding(url="ftp://example.com/x")]),
            "instances zero": run_doc([finding(instances=0)]),
            "instances bool": run_doc([finding(instances=True)]),
            "evidence not list": run_doc([finding(evidence="shot.png")]),
            "executed without checks": run_doc(coverage={"ux": cov("executed", checks=[])}),
            "partial without note": run_doc(coverage={"ux": cov("partial")}),
            "unknown coverage dimension": run_doc(coverage={"vibes": cov("executed")}),
            "bad coverage status": run_doc(coverage={"ux": cov("mostly")}),
            "bad target": run_doc(target="example.com"),
            "bad date": run_doc(date="13/10/2026"),
            "bad checks_run entry": run_doc(checks_run=[{"rule": "axe:*"}]),
        }
        for label, doc in cases.items():
            with self.subTest(label):
                self.assertTrue(F.validate(doc), f"{label} should be rejected")

    def test_missing_coverage_and_checks_run_are_errors_for_the_current_run_only(self):
        doc = run_doc([finding()])
        del doc["coverage"], doc["checks_run"]
        errs = F.validate(doc)
        self.assertTrue(any("coverage" in e for e in errs))
        self.assertTrue(any("checks_run" in e for e in errs))
        self.assertEqual(F.validate(doc, strict=False), [])

    def test_missing_dimension_in_coverage_is_an_error(self):
        doc = run_doc()
        del doc["coverage"]["ux"]
        self.assertTrue(any("coverage.ux" in e for e in F.validate(doc)))

    def test_non_object_and_bad_findings_do_not_crash(self):
        self.assertTrue(F.validate([]))
        self.assertTrue(F.validate({"findings": "no"}))
        self.assertTrue(F.validate(run_doc(["nope"])))


class CheckCommand(TempDirCase):
    def test_valid_file_gets_fingerprints_and_exit_0(self):
        p = self.write("run/findings.json", run_doc([finding(), finding("R-02", rule="other-rule")]))
        r = self.cli("check", p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = json.loads(p.read_text())
        self.assertEqual([f["fingerprint"] for f in d["findings"]], [F.fp(f) for f in d["findings"]])
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{12}", f["fingerprint"]) for f in d["findings"]))

    def test_invalid_file_exits_1_and_is_not_rewritten(self):
        text = json.dumps(run_doc([finding(severity="S9")]), indent=3)   # odd formatting: any rewrite would change the bytes
        p = self.write("findings.json", text)
        r = self.cli("check", p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("file not modified", r.stdout)
        self.assertEqual(p.read_text(), text)
        self.assertFalse((self.tmp / "findings.json.tmp").exists())

    def test_unparseable_and_missing_files_exit_1_untouched(self):
        p = self.write("broken.json", "{not json")
        self.assertEqual(self.cli("check", p).returncode, 1)
        self.assertEqual(p.read_text(), "{not json")
        self.assertEqual(self.cli("check", self.tmp / "nope.json").returncode, 1)

    def test_duplicate_fingerprints_are_refused_without_rewrite(self):
        p = self.write("findings.json", run_doc([finding("R-01"), finding("R-02", title="Another title")]))   # same rule + template
        before = p.read_text()
        r = self.cli("check", p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("duplicate fingerprint", r.stdout)
        self.assertEqual(p.read_text(), before)

    def test_page_scope_lets_one_rule_appear_on_two_pages(self):
        p = self.write("findings.json", run_doc([finding("R-01", scope="page", url="https://example.com/a/"),
                                                 finding("R-02", scope="page", url="https://example.com/b/")]))
        self.assertEqual(self.cli("check", p).returncode, 0)

    def test_changed_fingerprint_is_reported_and_rerun_is_idempotent(self):
        p = self.write("findings.json", run_doc([finding(fingerprint="aaaaaaaaaaaa")]))
        r = self.cli("check", p)
        self.assertEqual(r.returncode, 0)
        self.assertIn("WARNING fingerprint changed", r.stdout)
        first = p.read_text()
        r2 = self.cli("check", p)
        self.assertNotIn("WARNING", r2.stdout)
        self.assertEqual(p.read_text(), first)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.cli().returncode, 2)
        self.assertEqual(self.cli("frobnicate").returncode, 2)
        self.assertEqual(self.cli("check").returncode, 2)
        self.assertEqual(self.cli("diff", "x.json", "--bogus").returncode, 2)

    def test_help_works(self):
        r = self.cli("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("fingerprint", r.stdout)


class Fingerprints(unittest.TestCase):
    def test_stable_across_cosmetic_edits(self):
        base = F.fp(finding())
        edits = {"title": {"title": "Totally different wording"}, "id": {"id": "Z-99"}, "severity": {"severity": "S1"},
                 "dimension": {"dimension": "ux"}, "status": {"status": "fixed"},
                 "url": {"url": "https://example.com/services/other/?x=1"},
                 "rule case and punctuation": {"rule": "COLOR-Contrast:Header"}, "template case": {"template": " SERVICE "}}
        for label, edit in edits.items():
            with self.subTest(label):
                self.assertEqual(F.fp(finding(**edit)), base)

    def test_rule_or_template_change_gives_a_new_fingerprint(self):
        base = F.fp(finding())
        self.assertNotEqual(F.fp(finding(rule="color-contrast:footer")), base)
        self.assertNotEqual(F.fp(finding(template="blog")), base)

    def test_page_scope_depends_on_url_path_only(self):
        a = F.fp(finding(scope="page", url="https://example.com/a/"))
        self.assertEqual(a, F.fp(finding(scope="page", url="https://www.example.com/a/?utm=1#top")))
        self.assertNotEqual(a, F.fp(finding(scope="page", url="https://example.com/b/")))
        self.assertNotEqual(a, F.fp(finding()))   # template scope ignores the path

    def test_sitewide_ignores_template_and_url(self):
        a = F.fp(finding(scope="sitewide", template="home"))
        self.assertEqual(a, F.fp(finding(scope="sitewide", template="blog", url="https://example.com/z/")))

    def test_files_without_scope_read_as_template_scope(self):
        self.assertEqual(F.scope_of(finding()), "template")
        self.assertEqual(F.fp(finding()), F.fp(finding(scope="template")))


class HostOf(unittest.TestCase):
    def test_only_a_leading_www_label_is_removed(self):
        self.assertEqual(F.host_of("https://www.example.com/x"), "example.com")
        self.assertEqual(F.host_of("https://WWW.Example.com"), "example.com")
        self.assertEqual(F.host_of("https://mywww.example.com"), "mywww.example.com")
        self.assertEqual(F.host_of("https://example.www.example.org"), "example.www.example.org")
        self.assertNotEqual(F.host_of("https://mywww.example.com"), F.host_of("https://myexample.com"))

    def test_ports_stay_and_bad_input_is_empty(self):
        self.assertEqual(F.host_of("http://www.example.com:8080/"), "example.com:8080")
        self.assertEqual(F.host_of("not a url"), "")
        self.assertEqual(F.host_of(None), "")
        self.assertEqual(F.host_of("http://[::1/"), "")

    def test_ipv6_hosts_with_and_without_a_port_stay_different(self):
        with_port, without = F.host_of("http://[2001:db8::1]:8080/"), F.host_of("http://[2001:db8::1:8080]/")
        self.assertEqual(with_port, "[2001:db8::1]:8080")
        self.assertEqual(without, "[2001:db8::1:8080]")
        self.assertNotEqual(with_port, without)


class Scoring(unittest.TestCase):
    def score(self, findings=(), **coverage):
        return F.suggested_scores(run_doc(findings, coverage=coverage))

    def test_clean_executed_dimension_scores_10(self):
        self.assertEqual(self.score()["accessibility"]["score"], 10)

    def test_severity_penalties_and_caps(self):
        self.assertEqual(self.score([finding(severity="S4")])["accessibility"]["score"], 9.5)
        self.assertEqual(self.score([finding(severity="S3")])["accessibility"]["score"], 8)
        self.assertEqual(self.score([finding(severity="S2")])["accessibility"]["score"], 5)
        self.assertEqual(self.score([finding(severity="S1")])["accessibility"]["score"], 3)

    def test_caps_apply_even_when_the_arithmetic_is_higher(self):
        # a provisional S2 costs 2 (10 -> 8) but still caps the dimension at 5
        self.assertEqual(self.score([finding(severity="S2", verification="provisional")])["accessibility"]["score"], 5)

    def test_provisional_findings_deduct_half(self):
        s = self.score([finding("A", severity="S4", verification="provisional", rule="a"),
                        finding("B", severity="S4", verification="provisional", rule="b")])
        self.assertEqual(s["accessibility"]["score"], 9.5)   # 2 x 0.25 = 0.5

    def test_score_never_goes_below_zero(self):
        fs = [finding(f"R-{i}", severity="S1", rule=f"r{i}") for i in range(4)]
        self.assertEqual(self.score(fs)["accessibility"]["score"], 0)

    def test_fixed_findings_do_not_deduct(self):
        self.assertEqual(self.score([finding(severity="S1", status="fixed")])["accessibility"]["score"], 10)

    def test_open_accepted_wontfix_and_notretested_all_deduct(self):
        for status in ("open", "accepted-risk", "wont-fix", "not-retested"):
            with self.subTest(status):
                self.assertEqual(self.score([finding(severity="S2", status=status)])["accessibility"]["score"], 5)

    def test_not_retested_makes_the_dimension_partial_and_capped(self):
        s = self.score([finding(severity="S4", status="not-retested")])["accessibility"]
        self.assertEqual(s["status"], "partial")
        self.assertEqual(s["score"], 8)
        self.assertIn("1 not re-tested", s["note"])

    def test_partial_coverage_is_capped_at_8(self):
        s = self.score(accessibility=cov("partial", note="no keyboard walk"))["accessibility"]
        self.assertEqual(s["score"], 8)
        self.assertIn("no keyboard walk", s["note"])

    def test_improvements_and_other_dimensions_do_not_deduct(self):
        s = self.score([finding(dimension="ux", severity="S1"), finding("R-02", severity="IMP", rule="x")])
        self.assertEqual(s["accessibility"]["score"], 10)
        self.assertEqual(s["ux"]["score"], 3)

    def test_blocked_not_in_scope_and_not_executed_are_not_scored(self):
        s = self.score(accessibility=cov("blocked", checks=[]), ux=cov("not-in-scope", checks=[]), performance=cov("not-executed", checks=[]))
        for dim, status in (("accessibility", "blocked"), ("ux", "not-in-scope"), ("performance", "not-executed")):
            self.assertIsNone(s[dim]["score"])
            self.assertEqual(s[dim]["status"], status)

    def test_unscored_dimensions_ignore_their_findings(self):
        self.assertIsNone(self.score([finding(severity="S1")], accessibility=cov("blocked", checks=[]))["accessibility"]["score"])

    def test_executed_without_checks_is_not_scored(self):
        s = self.score(accessibility={"status": "executed", "checks": []})["accessibility"]
        self.assertIsNone(s["score"])
        self.assertIn("no checks", s["status"])

    def test_missing_coverage_entry_is_not_scored(self):
        doc = run_doc()
        del doc["coverage"]["ux"]
        self.assertIsNone(F.suggested_scores(doc)["ux"]["score"])


class ScoreCommand(TempDirCase):
    def test_prints_scores_and_not_scored_lines(self):
        doc = run_doc([finding(severity="S2")], coverage={"ux": cov("blocked", checks=[], note="login wall"),
                                                         "performance": cov("not-in-scope", checks=[])})
        r = self.cli("score", self.write("findings.json", doc))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"Accessibility\s+5\.0\s+Needs work")
        self.assertRegex(r.stdout, r"User experience\s+not scored \(blocked\)")
        self.assertIn("login wall", r.stdout)
        self.assertRegex(r.stdout, r"Speed and performance\s+not scored \(not in scope\)")
        self.assertRegex(r.stdout, r"Content quality\s+10\.0\s+Strong")

    def test_invalid_file_exits_1(self):
        self.assertEqual(self.cli("score", self.write("findings.json", {"findings": "x"})).returncode, 1)


class DiffCommand(TempDirCase):
    def diff(self, prev, cur, *extra):
        pp = self.write("prev/findings.json", prev)
        cp = self.write("cur/findings.json", cur)
        r = self.cli("diff", cp, "--previous", pp, *extra)
        regp = cp.parent / "regression.json"
        return r, (json.loads(regp.read_text()) if regp.exists() else None), cp

    @staticmethod
    def fps(*fs):
        return [F.fp(f) for f in fs]

    def test_fixed_requires_the_rule_and_template_to_have_been_rerun(self):
        a = finding("A", rule="axe:color-contrast", template="service")
        b = finding("B", rule="overflow-x:1024", template="service")
        c = finding("C", rule="axe:label", template="blog")
        cur = run_doc([], checks_run=[{"rule": "axe:color-contrast", "template": "service"},
                                      {"rule": "overflow-x:1024", "template": "blog"},   # right rule, wrong template
                                      {"rule": "axe:label", "template": "blog"}])
        r, reg, _ = self.diff(run_doc([a, b, c]), cur)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(reg["fixed"]), sorted(self.fps(a, c)))
        self.assertEqual(reg["not_retested"], self.fps(b))
        self.assertEqual(reg["still_open"], [])

    def test_missing_finding_without_checks_run_is_not_retested_with_warning(self):
        a = finding("A")
        r, reg, _ = self.diff(run_doc([a]), run_doc([]))
        self.assertEqual(reg["fixed"], [])
        self.assertEqual(reg["not_retested"], self.fps(a))
        self.assertIn("no checks_run entries", r.stdout)

    def test_wildcards_in_checks_run(self):
        a = finding("A", rule="axe:color-contrast", template="service")
        b = finding("B", rule="axe:label", template="blog")
        _, reg, _ = self.diff(run_doc([a, b]), run_doc([], checks_run=[{"rule": "axe:*", "template": "*"}]))
        self.assertEqual(sorted(reg["fixed"]), sorted(self.fps(a, b)))
        # a prefix wildcard must not match a different family of rules
        _, reg, _ = self.diff(run_doc([a]), run_doc([], checks_run=[{"rule": "overflow*", "template": "*"}]))
        self.assertEqual(reg["not_retested"], self.fps(a))

    def test_page_scoped_finding_needs_a_check_naming_the_same_path(self):
        a = finding("A", scope="page", url="https://example.com/a/", rule="axe:x", template="service")
        cases = (("same path", {"rule": "axe:x", "template": "service", "url": "https://example.com/a/?q=1"}, "fixed"),
                 ("other path", {"rule": "axe:x", "template": "service", "url": "https://example.com/b/"}, "not_retested"),
                 ("no url", {"rule": "axe:x", "template": "service"}, "not_retested"))
        for label, check, expect in cases:
            with self.subTest(label):
                _, reg, _ = self.diff(run_doc([a]), run_doc([], checks_run=[check]))
                self.assertEqual(reg[expect], self.fps(a))

    def test_sitewide_finding_needs_sitewide_or_star_template(self):
        a = finding("A", scope="sitewide", rule="hsts-missing", template="home")
        _, reg, _ = self.diff(run_doc([a]), run_doc([], checks_run=[{"rule": "hsts-missing", "template": "sitewide"}]))
        self.assertEqual(reg["fixed"], self.fps(a))
        _, reg, _ = self.diff(run_doc([a]), run_doc([], checks_run=[{"rule": "hsts-missing", "template": "home"}]))
        self.assertEqual(reg["not_retested"], self.fps(a))

    def test_still_open_new_and_status_changes(self):
        still = finding("A", rule="r-still")
        gone_wf = finding("B", rule="r-wontfix")
        gone_ar = finding("C", rule="r-accepted")
        marked_fixed = finding("D", rule="r-markedfixed")
        new = finding("N", rule="r-new")
        cur = run_doc([finding("A2", rule="r-still", severity="S2"), finding("B2", rule="r-wontfix", status="wont-fix"),
                       finding("C2", rule="r-accepted", status="accepted-risk"), finding("D2", rule="r-markedfixed", status="fixed"), new])
        r, reg, _ = self.diff(run_doc([still, gone_wf, gone_ar, marked_fixed]), cur)
        self.assertEqual(reg["still_open"], self.fps(still))
        self.assertEqual(reg["wont_fix"], self.fps(gone_wf))
        self.assertEqual(reg["accepted_risk"], self.fps(gone_ar))
        self.assertEqual(reg["fixed"], self.fps(marked_fixed))
        self.assertEqual(reg["new"], self.fps(new))
        self.assertIn("[S3→S2]", r.stdout)
        self.assertEqual(reg["status"], "compared")

    def test_previous_findings_that_were_not_open_are_not_compared(self):
        prev = run_doc([finding("A", status="fixed", rule="r-old")])
        _, reg, _ = self.diff(prev, run_doc([finding("A", rule="r-old")]))
        self.assertEqual(reg["new"], self.fps(finding(rule="r-old")))   # reappearing after "fixed" counts as new
        self.assertEqual(reg["still_open"], [])

    def test_previous_non_fixed_findings_keep_their_disposition_when_absent_and_not_rerun(self):
        nr = finding("A", rule="r-notretested", status="not-retested")
        ar = finding("B", rule="r-accepted", status="accepted-risk")
        wf = finding("C", rule="r-wontfix", status="wont-fix")
        _, reg, _ = self.diff(run_doc([nr, ar, wf]), run_doc([], checks_run=[{"rule": "unrelated", "template": "*"}]))
        self.assertEqual(reg["not_retested"], self.fps(nr))
        self.assertEqual(reg["accepted_risk"], self.fps(ar))
        self.assertEqual(reg["wont_fix"], self.fps(wf))
        self.assertEqual((reg["fixed"], reg["new"], reg["still_open"]), ([], [], []))

    def test_previous_non_fixed_findings_that_are_present_and_open_are_still_open_not_new(self):
        old = [finding("A", rule="r-notretested", status="not-retested"), finding("B", rule="r-accepted", status="accepted-risk"),
               finding("C", rule="r-wontfix", status="wont-fix")]
        cur = [finding(f"N{i}", rule=f["rule"]) for i, f in enumerate(old)]
        _, reg, _ = self.diff(run_doc(old), run_doc(cur))
        self.assertEqual(sorted(reg["still_open"]), sorted(self.fps(*old)))
        self.assertEqual(reg["new"], [])

    def test_previous_non_fixed_findings_that_were_rerun_and_are_gone_count_as_fixed(self):
        old = [finding("A", rule="r-notretested", status="not-retested"), finding("B", rule="r-accepted", status="accepted-risk"),
               finding("C", rule="r-wontfix", status="wont-fix")]
        _, reg, _ = self.diff(run_doc(old), run_doc([], checks_run=[{"rule": "r-*", "template": "*"}]))
        self.assertEqual(sorted(reg["fixed"]), sorted(self.fps(*old)))
        self.assertEqual((reg["wont_fix"], reg["accepted_risk"], reg["not_retested"]), ([], [], []))

    def test_dispositions_appear_in_the_markdown_report(self):
        out = self.tmp / "regression.md"
        r, _, _ = self.diff(run_doc([finding("A", status="wont-fix")]), run_doc([]), "--out", str(out))
        self.assertRegex(out.read_text(), r"## Won't fix\n- A ")

    def test_out_file_and_regression_json_are_written_next_to_findings(self):
        a = finding("A")
        out = self.tmp / "regression.md"
        r, reg, cp = self.diff(run_doc([a]), run_doc([a]), "--out", str(out))
        self.assertEqual(r.returncode, 0)
        self.assertTrue(out.read_text().startswith("# Regression vs previous run"))
        self.assertEqual(reg["still_open"], self.fps(a))
        self.assertTrue((cp.parent / "regression.json").is_file())

    def test_baseline_run_when_no_previous_exists(self):
        cp = self.write("runs/cur/findings.json", run_doc([finding()]))
        out = self.tmp / "reg.md"
        r = self.cli("diff", cp, "--runs-root", self.tmp / "runs", "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("baseline run", r.stdout)
        self.assertIn("baseline run", out.read_text())
        reg = json.loads((cp.parent / "regression.json").read_text())
        self.assertEqual(reg["status"], "baseline")
        self.assertEqual(reg["fixed"], [])

    def test_previous_run_is_found_under_runs_root(self):
        a = finding("A", rule="r-one")
        self.write("runs/old/findings.json", run_doc([a], run_id="example-com-2025-06-01", date="2025-06-01"))
        self.write("runs/older/findings.json", run_doc([finding("X", rule="r-ancient")], run_id="example-com-2025-01-01", date="2025-01-01"))
        self.write("runs/other-site/findings.json", run_doc([finding("Y", rule="r-other")], run_id="other-2025-09-01", date="2025-09-01",
                                                            target="https://other.example.org"))
        self.write("runs/future/findings.json", run_doc([finding("Z", rule="r-future")], run_id="example-com-2027-01-01", date="2027-01-01"))
        cp = self.write("runs/cur/findings.json", run_doc([], checks_run=[{"rule": "r-one", "template": "*"}]))
        r = self.cli("diff", cp, "--runs-root", self.tmp / "runs")
        self.assertEqual(r.returncode, 0, r.stderr)
        reg = json.loads((cp.parent / "regression.json").read_text())
        self.assertTrue(reg["previous"].endswith("old/findings.json"), reg["previous"])
        self.assertEqual(reg["fixed"], self.fps(a))

    def test_previous_for_another_site_is_refused(self):
        r, _, _ = self.diff(run_doc([finding()], target="https://other.example.org"), run_doc([finding()]))
        self.assertEqual(r.returncode, 1)
        self.assertIn("previous run", r.stdout)

    def test_older_previous_files_missing_newer_fields_are_accepted(self):
        slim = {k: v for k, v in finding().items() if k in ("id", "title", "rule", "template", "severity", "status")}
        prev = run_doc([slim])
        del prev["coverage"], prev["checks_run"]
        r, reg, _ = self.diff(prev, run_doc([finding()]))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(reg["still_open"]), 1)

    def test_lookalike_hosts_are_not_the_same_site(self):
        r, reg, _ = self.diff(run_doc([finding()], target="https://myexample.com"), run_doc([finding()], target="https://mywww.example.com"))
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(reg)

    def test_www_and_apex_count_as_the_same_site(self):
        r, reg, _ = self.diff(run_doc([finding()], target="https://www.example.com"), run_doc([finding()]))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(len(reg["still_open"]), 1)

    def test_invalid_current_run_exits_1_and_writes_nothing(self):
        r, reg, _ = self.diff(run_doc([finding()]), {"findings": "x"})
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(reg)


if __name__ == "__main__":
    unittest.main()
