"""report_export.py: self-contained HTML, refusal on missing images, and a PDF that really carries its screenshots."""
import os
import base64
import contextlib
import io
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import qa_support as qs

REPORT_FIXTURES = qs.FIXTURES / "report"
sys.path.insert(0, str(REPORT_FIXTURES))
import images as img  # noqa: E402

SCRIPTS = qs.ROOT / "skills" / "qa-standards" / "scripts"
SCRIPT = SCRIPTS / "report_export.py"
sys.path.insert(0, str(SCRIPTS))
import report_export as EX  # noqa: E402

CHROME_OK = os.path.isfile(EX.CHROME) and os.access(EX.CHROME, os.X_OK)
CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"


class Export(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.run = self.root / "run"
        (self.run / "screenshots").mkdir(parents=True)
        shutil.copy(REPORT_FIXTURES / "sample_report.md", self.run / "report.md")
        self.shot("home.png", rgb=(255, 0, 0))
        self.shot("contact.png", rgb=(0, 0, 255))

    def shot(self, name, rgb=(0, 255, 0), data=None):
        p = self.run / "screenshots" / name
        p.write_bytes(img.png(rgb) if data is None else data)
        return p

    def write(self, text):
        (self.run / "report.md").write_text(text, encoding="utf-8")

    def cli(self, *args, env=None):
        return qs.run_script(SCRIPT, *args, env=env, cwd=self.root)

    def export_html(self, text=None, *extra):
        if text is not None:
            self.write(text)
        out = self.root / "out.html"
        r = self.cli(self.run / "report.md", "--html", out, *extra)
        return r, (out.read_text(encoding="utf-8") if out.exists() else None)


class HtmlOutput(Export):
    def test_sample_report_exports_with_inlined_figures_and_captions(self):
        r, page = self.export_html()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("2 distinct images inlined", r.stdout)
        self.assertEqual(len(re.findall(r'<img src="data:image/png;base64,[A-Za-z0-9+/=]+"', page)), 2)
        self.assertIn("<figcaption>Booking button missing at 375 px wide</figcaption>", page)
        self.assertIn("<figcaption>Contact form after submitting an empty email field</figcaption>", page)
        self.assertEqual(page.count("<figure>"), 2)
        self.assertRegex(page, r'<figure><img [^>]+><figcaption>')

    def test_markdown_features_are_rendered(self):
        r, page = self.export_html("# Title *here*\n\nA **bold** and *italic* word with `code` and a [link](https://example.com/page).\n\n"
                                   "- one\n- two\n\nThen in order:\n\n1. first\n2. second\n\n| a | b |\n|---|---:|\n| 1 | 2 |\n\n```python\nprint('<x> & y')\n```\n\n> quoted\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        for fragment in ("<h1>Title <em>here</em></h1>", "<strong>bold</strong>", "<em>italic</em>", "<code>code</code>", "<ul>", "<ol>",
                         "<table>", "<th", "<td", "<pre>", "<blockquote>", '<a href="https://example.com/page"'):
            self.assertIn(fragment, page)
        self.assertIn("print('&lt;x&gt; &amp; y')", page.replace("&#x27;", "'"))
        self.assertIn("<title>Title here</title>", page)

    def test_the_page_is_self_contained(self):
        r, page = self.export_html()
        self.assertIn(f'<meta http-equiv="Content-Security-Policy" content="{CSP}">', page)
        self.assertNotRegex(page, r'(?i)\ssrc="(?!data:image/)')
        self.assertNotRegex(page, r"(?i)<(script|link|iframe|object|embed|form|style[^>]*src)")
        self.assertNotRegex(page, r"(?i)url\(|@import")
        self.assertNotRegex(re.sub(r'<a href="[^"]*"', "", page), r"(?i)https?:|(?:src|href)=.?//")   # no remote reference outside text links
        self.assertIn("max-width: 100%", page)
        self.assertRegex(page, r"figure \{[^}]*break-inside: avoid")

    def test_raw_html_is_escaped_not_passed_through(self):
        r, page = self.export_html("# R\n\nHello <script>alert(1)</script> and <img src=http://tracker.example/p.gif> and <b onclick=\"x()\">bold</b>\n\n"
                                   "<div><script>alert(2)</script></div>\n\n<iframe src=\"http://tracker.example\"></iframe>\n\n<!-- comment -->\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        body = page.split("<body>")[1]
        self.assertNotIn("<script", body)
        self.assertNotIn("<iframe", body)
        self.assertNotIn("<img", body)
        self.assertNotIn("<b ", body)
        self.assertNotRegex(body, r"<[^>]*onclick")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertIn("&lt;img src=http://tracker.example/p.gif&gt;", body)

    def test_only_http_https_mailto_and_fragment_links_survive(self):
        r, page = self.export_html("[a](https://example.com) [b](mailto:team@example.com) [c](#top) [d](javascript:alert(1)) [e](data:text/html,x) [f](file:///etc/passwd)\n")
        hrefs = re.findall(r'href="([^"]*)"', page)
        self.assertEqual(hrefs, ["https://example.com", "mailto:team@example.com", "#top"])
        self.assertIn(" d e f", page)   # the text of a refused link stays as plain text

    def test_adjacent_images_each_get_their_own_figure(self):
        r, page = self.export_html("![First](screenshots/home.png)\n![Second](screenshots/contact.png)\n")
        self.assertEqual(page.count("<figure>"), 2)

    def test_the_same_image_embedded_twice_counts_once_as_distinct(self):
        r, page = self.export_html("![One](screenshots/home.png)\n\n![Again](screenshots/home.png)\n")
        self.assertIn("1 distinct images inlined", r.stdout)
        self.assertEqual(page.count("<figure>"), 2)

    def test_output_is_deterministic_and_does_not_modify_the_report(self):
        before = (self.run / "report.md").read_bytes()
        _, one = self.export_html()
        _, two = self.export_html()
        self.assertEqual(one, two)
        self.assertEqual((self.run / "report.md").read_bytes(), before)


class TargetForms(Export):
    def test_angle_brackets_title_dot_slash_and_percent_encoding_all_inline(self):
        r, page = self.export_html('![One](<screenshots/home.png>)\n\n![Two](./screenshots/home.png "A title")\n\n![Three](screenshots/%68ome.png)\n\n'
                                   '![Four](<screenshots/contact.png> "T")\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(page.count("<figure>"), 4)
        self.assertNotIn('class="unavailable"', page)
        self.assertIn("2 distinct images inlined", r.stdout)

    def test_an_image_in_a_spaced_filename_inlines(self):
        self.shot("my shot.png", rgb=(9, 9, 9))
        r, page = self.export_html("![Spaced](<screenshots/my shot.png>)\n\n![Encoded](screenshots/my%20shot.png)\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(page.count("<figure>"), 2)

    def test_checker_and_exporter_agree_on_what_an_image_is(self):
        docs = ["`![a](screenshots/home.png)`", "```\n![a](screenshots/home.png)\n```", "    ![a](screenshots/home.png)", "\\![a](screenshots/home.png)",
                "![a](screenshots/home.png)", "![a][r]\n\n[r]: screenshots/home.png", "| t |\n|---|\n| ![a](screenshots/home.png) |",
                "<!-- ![a](screenshots/home.png) -->", "<div>![a](screenshots/home.png)</div>", "> ![a](screenshots/home.png)", "- ![a](screenshots/home.png)",
                "![a](screenshots/home.png)![b](screenshots/contact.png)"]
        for doc in docs:
            with self.subTest(doc):
                self.write(doc + "\n")
                res = EX.report_check.check(self.run / "report.md")
                page, rend = EX.build_html(doc + "\n", {e["src"]: {"path": e["path"], "mime": e["mime"]} for e in res.embedded if e["path"]})
                self.assertEqual(len(res.embedded), rend.figures + rend.unavailable)
                self.assertEqual(page.count("<img "), rend.figures)

    def test_exporter_refuses_when_a_validated_image_is_not_inlined(self):
        self.write("![Home](screenshots/home.png)\n")
        real = EX.report_check.check(self.run / "report.md")
        real.embedded[0]["src"] = "something/else.png"   # simulate the checker and the renderer disagreeing about the target
        out = self.root / "o.html"
        with mock.patch.object(EX.report_check, "check", return_value=real), contextlib.redirect_stdout(io.StringIO()) as printed:
            code = EX.main([str(self.run / "report.md"), "--html", str(out)])
        self.assertEqual(code, 1)
        self.assertIn("validated 1 embedded images but only 0 were inlined", printed.getvalue())
        self.assertFalse(out.exists())
        with mock.patch.object(EX.report_check, "check", return_value=real), contextlib.redirect_stdout(io.StringIO()):
            code = EX.main([str(self.run / "report.md"), "--html", str(out), "--allow-missing"])
        self.assertEqual(code, 0)
        self.assertIn("image unavailable", out.read_text(encoding="utf-8"))

    def test_the_printed_image_count_comes_from_what_was_inlined(self):
        r, page = self.export_html("![A](screenshots/home.png)\n\n![B](screenshots/home.png)\n\n![C](screenshots/contact.png)\n")
        self.assertIn("2 distinct images inlined", r.stdout)
        self.assertEqual(page.count("data:image/png"), 3)


class LocalFilesOutsideTheReportFolder(Export):
    """Can a report make the exporter read a file outside the report's folder? No: only validated regular files under it are inlined."""

    def setUp(self):
        super().setUp()
        self.secret = self.root / "secret.png"
        self.secret.write_bytes(img.png((7, 77, 177)))
        self.secret_b64 = base64.b64encode(self.secret.read_bytes()).decode()
        (self.root / "elsewhere").mkdir()
        (self.root / "elsewhere" / "s.png").write_bytes(self.secret.read_bytes())

    def attack_report(self):
        links = []
        for name, target in (("link.png", self.secret), ("dirlink", self.root / "elsewhere")):
            try:
                os.symlink(target, self.run / name)
                links.append(name)
            except (OSError, NotImplementedError):
                pass
        lines = ["![dotdot](../secret.png)", f"![absolute]({self.secret})", f"![fileurl]({self.secret.as_uri()})", "![ref][r]\n\n[r]: ../secret.png",
                 "![deep](screenshots/../../secret.png)", "![encoded](..%2Fsecret.png)", "![encoded2](%2e%2e/secret.png)"]
        if "link.png" in links: lines.append("![symlink](link.png)")
        if "dirlink" in links: lines.append("![dirlink](dirlink/s.png)")
        return "\n\n".join(lines) + "\n"

    def test_every_route_out_of_the_folder_is_refused(self):
        r, page = self.export_html(self.attack_report())
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIsNone(page)
        self.assertIn("refusing to export", r.stdout)

    def test_even_with_allow_missing_none_of_the_outside_bytes_reach_the_page(self):
        r, page = self.export_html(self.attack_report(), "--allow-missing")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn(self.secret_b64, page)
        self.assertNotIn("data:image", page)
        self.assertEqual(page.count("<figure>"), 0)
        self.assertGreaterEqual(page.count('class="unavailable"'), 7)

    def test_a_directory_or_a_non_regular_file_is_not_inlined(self):
        (self.run / "screenshots" / "folder.png").mkdir()
        r, page = self.export_html("![dir](screenshots/folder.png)\n", "--allow-missing")
        self.assertNotIn("data:image", page)


class DecodeNote(Export):
    def test_html_only_export_of_non_png_images_says_they_were_not_decoded(self):
        self.shot("a.jpg", data=img.JPEG)
        r, page = self.export_html("![A](screenshots/a.jpg)\n\n![B](screenshots/home.png)\n")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("note: 1 JPEG/GIF/WebP image(s) were checked structurally only, not decoded; a --pdf export has Chrome load them.", r.stdout)

    def test_png_only_html_export_has_no_such_note(self):
        r, page = self.export_html()
        self.assertNotIn("structurally only", r.stdout)

    def test_help_states_the_limit(self):
        h = self.cli("--help").stdout
        self.assertIn("JPEG, GIF and WebP get structural checks only", h)
        self.assertIn("do\nnot prove the image decodes", h)


class Refusals(Export):
    def test_missing_image_refuses_and_writes_nothing(self):
        (self.run / "screenshots" / "contact.png").unlink()
        r, page = self.export_html()
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(page)
        self.assertIn("refusing to export", r.stdout)
        self.assertIn("image file does not exist: screenshots/contact.png", r.stdout)

    def test_invalid_or_unsafe_images_refuse_too(self):
        for label, target, data in (("not an image", "screenshots/bad.png", img.NOT_AN_IMAGE), ("empty", "screenshots/empty.png", b""),
                                    ("url", "https://example.com/a.png", None), ("absolute", "/etc/a.png", None), ("escape", "../x.png", None)):
            with self.subTest(label):
                if data is not None:
                    (self.run / target).write_bytes(data)
                r, page = self.export_html(f"![x]({target})\n")
                self.assertEqual((r.returncode, page), (1, None))

    def test_allow_missing_exports_with_a_visible_unavailable_box(self):
        (self.run / "screenshots" / "contact.png").unlink()
        r, page = self.export_html(None, "--allow-missing")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("1 distinct images inlined", r.stdout)
        self.assertIn('<figure class="unavailable"><figcaption>image unavailable: Contact form after submitting an empty email field</figcaption></figure>', page)

    def test_allow_missing_never_emits_a_remote_image(self):
        r, page = self.export_html("![Remote](https://tracker.example/a.png)\n![Local](screenshots/home.png)\n", "--allow-missing")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("tracker.example", page)
        self.assertEqual(len(re.findall(r"<img ", page)), 1)

    def test_unembedded_references_alone_do_not_block_the_export(self):
        r, page = self.export_html("Evidence: screenshots/home.png\n")
        self.assertEqual(r.returncode, 0)
        self.assertIn("referenced but not embedded", r.stdout)
        self.assertNotIn("<img", page)

    def test_never_overwrites_the_report_or_one_output_with_the_other(self):
        report = self.run / "report.md"
        before = report.read_bytes()
        self.assertEqual(self.cli(report, "--html", report).returncode, 2)
        self.assertEqual(self.cli(report, "--pdf", report).returncode, 2)
        self.assertEqual(self.cli(report, "--html", self.root / "x", "--pdf", self.root / "x").returncode, 2)
        self.assertEqual(report.read_bytes(), before)

    def test_an_output_is_required(self):
        self.assertEqual(self.cli(self.run / "report.md").returncode, 2)

    def test_missing_report_is_a_usage_error(self):
        self.assertEqual(self.cli(self.run / "absent.md", "--html", self.root / "o.html").returncode, 2)

    def test_missing_markdown_package_exits_2_before_doing_anything(self):
        blocker = self.root / "blocker" / "markdown"
        blocker.mkdir(parents=True)
        (blocker / "__init__.py").write_text('raise ImportError("blocked for this test", name="markdown")\n', encoding="utf-8")
        out = self.root / "o.html"
        r = self.cli(self.run / "report.md", "--html", out, env={"PYTHONPATH": str(blocker.parent)})
        self.assertEqual(r.returncode, 2)
        self.assertIn("markdown", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse(out.exists())

    def test_missing_chrome_exits_2_with_a_clear_message_and_writes_nothing(self):
        out = self.root / "o.pdf"
        r = self.cli(self.run / "report.md", "--pdf", out, env={"CHROME_PATH": str(self.root / "no-chrome")})
        self.assertEqual(r.returncode, 2)
        self.assertIn("Chrome/Chromium not found", r.stderr)
        self.assertFalse(out.exists())

    def test_only_the_given_paths_are_written(self):
        out_dir = self.root / "outputs"
        out_dir.mkdir()
        before = {p for p in self.root.rglob("*")}
        r = self.cli(self.run / "report.md", "--html", out_dir / "r.html")
        self.assertEqual(r.returncode, 0)
        self.assertEqual({p for p in self.root.rglob("*")} - before, {out_dir / "r.html"})


def pdf_bytes(*objects):
    """A hand-built PDF body: each object is (number, dictionary text). Enough structure for the object-level counting."""
    return b"%PDF-1.7\n" + b"".join(f"{n} 0 obj\n<< {d} >>\nstream\nXX\nendstream\nendobj\n".encode() for n, d in objects) + b"%%EOF\n"


IMG = "/Type /XObject /Subtype /Image /Width 1 /Height 1"


class VerifyPdf(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def pdf(self, body, head=b"%PDF-1.7\n"):
        p = self.tmp / "t.pdf"
        p.write_bytes(head + body)
        return p

    def objs(self, *objects):
        p = self.tmp / "t.pdf"
        p.write_bytes(pdf_bytes(*objects))
        return p

    def test_enough_image_objects_pass_whatever_the_spacing(self):
        p = self.objs((1, IMG), (2, "/Subtype/Image/Width 1"), (3, "/Subtype   /Image"))
        ok, msg, found = EX.verify_pdf(p, 3)
        self.assertEqual((ok, found), (True, 3))
        self.assertTrue(EX.verify_pdf(p, 2)[0])

    def test_too_few_image_objects_fail_with_exact_numbers(self):
        ok, msg, found = EX.verify_pdf(self.objs((1, IMG)), 2)
        self.assertEqual((ok, found), (False, 1))
        self.assertEqual(msg, "PDF verification failed: expected at least 2 image objects, found 1")

    def test_soft_masks_of_transparent_images_do_not_count(self):
        # one transparent screenshot = an image (/SMask 6) plus its mask image: ONE screenshot, not two
        one_transparent = self.objs((5, IMG + " /SMask 6 0 R"), (6, IMG + " /ColorSpace /DeviceGray"))
        self.assertEqual(EX.count_pdf(one_transparent.read_bytes())[0], 1)
        ok, msg, found = EX.verify_pdf(one_transparent, 2)   # two screenshots expected, one of them missing: must be rejected
        self.assertEqual((ok, found), (False, 1))
        self.assertIn("expected at least 2 image objects, found 1", msg)

    def test_two_transparent_screenshots_count_two_and_a_hard_mask_is_excluded_too(self):
        two = self.objs((5, IMG + " /SMask 6 0 R"), (6, IMG), (7, IMG + " /SMask 8 0 R"), (8, IMG), (9, IMG + " /Mask 10 0 R"), (10, IMG))
        self.assertEqual(EX.count_pdf(two.read_bytes())[0], 3)
        self.assertTrue(EX.verify_pdf(two, 3)[0])
        self.assertFalse(EX.verify_pdf(two, 4)[0])

    def test_opaque_and_transparent_screenshots_mix(self):
        mixed = self.objs((1, IMG), (2, IMG + " /SMask 3 0 R"), (3, IMG))
        self.assertEqual(EX.count_pdf(mixed.read_bytes())[0], 2)

    def test_other_subtypes_do_not_count(self):
        self.assertEqual(EX.verify_pdf(self.objs((1, "/Subtype /Form"), (2, "/Subtype /Imagery")), 1)[:1], (False,))

    def test_missing_file_and_wrong_header(self):
        self.assertFalse(EX.verify_pdf(self.tmp / "nope.pdf", 0)[0])
        ok, msg, _ = EX.verify_pdf(self.pdf(pdf_bytes((1, IMG))[8:], head=b"<html>"), 1)
        self.assertFalse(ok)
        self.assertIn("does not start with %PDF", msg)

    def test_zero_expected_images_passes_for_any_pdf(self):
        self.assertTrue(EX.verify_pdf(self.pdf(b"no images here"), 0)[0])

    def test_page_count_helper(self):
        self.assertEqual(EX.count_pdf(pdf_bytes((1, "/Type /Pages"), (2, "/Type /Page"), (3, "/Type/Page")))[1], 2)


@unittest.skipUnless(CHROME_OK, f"Chrome not found at {EX.CHROME}; set CHROME_PATH to run the real PDF test")
class RealPdf(Export):
    def test_pdf_with_two_screenshots_verifies_and_a_stripped_pdf_fails(self):
        out_pdf, out_html = self.root / "report.pdf", self.root / "report.html"
        r = self.cli(self.run / "report.md", "--html", out_html, "--pdf", out_pdf)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"PDF written: .*report\.pdf \(\d+ pages, \d+ image objects found, 2 images verified\)")
        data = out_pdf.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        found, _ = EX.count_pdf(data)
        print(f"\n[real PDF] Chrome produced {found} image objects for 2 embedded images", file=sys.stderr)
        self.assertGreaterEqual(found, 2)
        self.assertTrue(EX.verify_pdf(out_pdf, 2)[0])

        stripped_html = self.root / "stripped.html"
        stripped_html.write_text(re.sub(r"<figure>.*?</figure>", "", out_html.read_text(encoding="utf-8"), flags=re.S), encoding="utf-8")
        self.assertNotIn("data:image", stripped_html.read_text(encoding="utf-8"))
        stripped_pdf = self.root / "stripped.pdf"
        ok, err = EX.print_pdf(stripped_html, stripped_pdf)
        self.assertTrue(ok, err)
        verdict, msg, found_stripped = EX.verify_pdf(stripped_pdf, 2)
        self.assertFalse(verdict, msg)
        self.assertEqual(found_stripped, 0)
        self.assertIn("expected at least 2 image objects, found 0", msg)

    def test_transparent_screenshots_are_counted_once_each_and_a_missing_one_is_caught(self):
        self.shot("home.png", data=img.png((255, 0, 0), alpha=True))
        self.shot("contact.png", data=img.png((0, 0, 255), alpha=True))
        out_pdf, out_html = self.root / "alpha.pdf", self.root / "alpha.html"
        r = self.cli(self.run / "report.md", "--html", out_html, "--pdf", out_pdf)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = out_pdf.read_bytes()
        raw = len(re.findall(rb"/Subtype\s*/Image\b", data))
        counted = EX.count_pdf(data)[0]
        smask = len(re.findall(rb"/SMask\s+\d+", data))
        print(f"\n[real PDF, alpha] raw /Subtype /Image objects: {raw}; counted without soft masks: {counted}; /SMask references: {smask}", file=sys.stderr)
        self.assertGreater(smask, 0, "Chrome should have written soft masks for the transparent screenshots")
        self.assertEqual(counted, 2)
        self.assertGreaterEqual(raw, counted)
        self.assertTrue(EX.verify_pdf(out_pdf, 2)[0])
        one_html = self.root / "one.html"
        one_html.write_text(re.sub(r"<figure>.*?</figure>", "", out_html.read_text(encoding="utf-8"), count=1, flags=re.S), encoding="utf-8")
        one_pdf = self.root / "one.pdf"
        ok, err = EX.print_pdf(one_html, one_pdf)
        self.assertTrue(ok, err)
        verdict, msg, found = EX.verify_pdf(one_pdf, 2)
        self.assertFalse(verdict, msg)
        self.assertEqual(found, 1)

    def test_real_images_of_all_four_types_export_to_pdf_and_pass_the_load_probe(self):
        for name, data in (("a.jpg", img.JPEG), ("b.gif", img.GIF), ("c.webp", img.WEBP), ("d.png", img.png((5, 90, 5)))):
            self.shot(name, data=data)
        self.write("![P](screenshots/a.jpg)\n\n![G](screenshots/b.gif)\n\n![W](screenshots/c.webp)\n\n![N](screenshots/d.png)\n")
        r = self.cli(self.run / "report.md", "--pdf", self.root / "all.pdf")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"4 images verified")

    def test_a_structurally_plausible_but_undecodable_image_is_stopped_by_the_chrome_load_probe(self):
        import struct
        payload = b"\x2f" + b"\xff" * 60
        chunk = b"VP8L" + struct.pack("<I", len(payload)) + payload
        garbage = b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk
        self.assertEqual(EX.report_check.validate_image(garbage), ("image/webp", None))   # passes the structural check
        self.shot("bad.webp", data=garbage)
        self.write("![Fine](screenshots/home.png)\n\n![Broken](screenshots/bad.webp)\n")
        out = self.root / "x.pdf"
        r = self.cli(self.run / "report.md", "--pdf", out)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('cannot be loaded by Chrome: image 2 ("Broken")', r.stdout)
        self.assertFalse(out.exists())

    def test_review_regression_a_repeated_undecodable_image_counts_once_under_allow_missing(self):
        # One good PNG plus the same undecodable WebP embedded twice: two distinct images, one of them bad. The PDF must
        # still be required to contain the good one (target 1, not 0).
        import struct
        payload = b"\x2f" + b"\xff" * 60
        chunk = b"VP8L" + struct.pack("<I", len(payload)) + payload
        self.shot("bad.webp", data=b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk)
        self.write("![Fine](screenshots/home.png)\n\n![Broken](screenshots/bad.webp)\n\n![Broken again](screenshots/bad.webp)\n")
        out = self.root / "rep.pdf"
        r = self.cli(self.run / "report.md", "--pdf", out, "--allow-missing")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("2 embedded image(s) cannot be loaded by Chrome", r.stdout)
        self.assertRegex(r.stdout, r"\b1 images verified")

    def test_why_counting_pdf_image_objects_alone_is_not_a_decode_check(self):
        # Evidence for the probe: Chrome draws a broken-image icon for an undecodable image, and that icon is an image object.
        import struct
        payload = b"\x2f" + b"\xff" * 60
        chunk = b"VP8L" + struct.pack("<I", len(payload)) + payload
        garbage = b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk
        page, rend = EX.build_html("![Broken](screenshots/bad.webp)\n", {"screenshots/bad.webp": {"path": self._write(garbage), "mime": "image/webp"}})
        ok, bad, err = EX.probe_decode(page)
        self.assertEqual((ok, bad), (True, [0]), err)
        html = self.root / "bad.html"
        html.write_text(page, encoding="utf-8")
        pdf = self.root / "bad.pdf"
        self.assertTrue(EX.print_pdf(html, pdf)[0])
        self.assertTrue(EX.verify_pdf(pdf, 1)[0], "if this fails, Chrome stopped drawing a placeholder and the probe may no longer be needed")

    def _write(self, data):
        p = self.root / "garbage.bin"
        p.write_bytes(data)
        return p

    def test_probe_reports_no_bad_images_for_valid_ones(self):
        page, rend = EX.build_html("![A](a.png)\n\n![B](b.jpg)\n", {"a.png": {"path": self._write(img.png()), "mime": "image/png"},
                                                                       "b.jpg": {"path": self._write(img.JPEG), "mime": "image/jpeg"}})
        self.assertEqual(EX.probe_decode(page), (True, [], ""))
        self.assertNotIn("<script", page)   # the deliverable carries no script; only the throwaway probe copy does

    def test_no_profile_folder_is_left_behind(self):
        before = {p.name for p in Path(tempfile.gettempdir()).glob("qa-export-*")}
        self.cli(self.run / "report.md", "--pdf", self.root / "r.pdf")
        after = {p.name for p in Path(tempfile.gettempdir()).glob("qa-export-*")}
        self.assertEqual(after - before, set())


if __name__ == "__main__":
    unittest.main()
