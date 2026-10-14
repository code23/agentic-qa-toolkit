"""Brand packs: brand_check.py validation and the exporter's cover, colours, fonts, footer and safety rules."""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
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
sys.path.insert(0, str(SCRIPTS))
import brand_check as BC  # noqa: E402
import report_export as EX  # noqa: E402

CHECK = SCRIPTS / "brand_check.py"
EXPORT = SCRIPTS / "report_export.py"
CHROME_OK = os.path.isfile(EX.CHROME) and os.access(EX.CHROME, os.X_OK)
PDFTOTEXT = shutil.which("pdftotext")
PDFFONTS = shutil.which("pdffonts")
FAKE_WOFF2 = b"wOF2" + b"\x00" * 64
GOOD_BRAND = {
    "name": "Example Agency",
    "colours": {"accent": "#0a5c36", "ink": "#112233", "muted": "#667788", "paper": "#fffef8"},
    "logo": "logo.png",
    "fonts": {"heading": {"family": "Example Serif", "file": "fonts/serif.woff2"}, "body": {"family": "Example Sans", "file": "fonts/sans.woff2"}},
    "cover": {"prepared_by": "Pat Example", "contact": "hello@example.com", "confidentiality": "Confidential - client use only"},
    "footer": "Example Agency | example.com | Confidential",
}


class BrandCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.brand = self.root / "brand"

    def make(self, spec=None, files=True, **extra_files):
        """Write a brand folder: brand.json from spec (a dict, a raw string or None for GOOD_BRAND) plus the files it names."""
        spec = json.loads(json.dumps(GOOD_BRAND)) if spec is None else spec
        shutil.rmtree(self.brand, ignore_errors=True)
        (self.brand / "fonts").mkdir(parents=True, exist_ok=True)
        (self.brand / "brand.json").write_text(spec if isinstance(spec, str) else json.dumps(spec), encoding="utf-8")
        if files:
            (self.brand / "logo.png").write_bytes(img.png((10, 90, 54), size=48))
            (self.brand / "fonts" / "serif.woff2").write_bytes(FAKE_WOFF2)
            (self.brand / "fonts" / "sans.woff2").write_bytes(FAKE_WOFF2 + b"x")
        for name, data in extra_files.items():
            p = self.brand / name.replace("__", "/")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return self.brand

    def spec(self, **changes):
        s = json.loads(json.dumps(GOOD_BRAND))
        s.update(changes)
        return s

    def problems(self, spec=None, **files):
        self.make(spec, **files)
        return BC.check_brand(self.brand).problems

    def assertOneProblem(self, text, spec=None, **files):
        probs = self.problems(spec, **files)
        self.assertEqual(len(probs), 1, probs)
        self.assertIn(text, probs[0])

    def symlink(self, target, name):
        try:
            os.symlink(target, self.brand / name)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available here")


class Schema(BrandCase):
    def test_a_complete_fictional_brand_is_clean(self):
        self.make()
        res = BC.check_brand(self.brand)
        self.assertEqual((res.problems, res.notes), ([], []))
        self.assertEqual(res.brand["name"], "Example Agency")
        self.assertEqual(len(res.brand["fonts"]), 2)

    def test_a_minimal_brand_needs_only_a_name(self):
        self.make({"name": "Example Agency"}, files=False)
        self.assertEqual(BC.check_brand(self.brand).problems, [])

    def test_unknown_keys_are_errors_at_every_level(self):
        for label, spec, expect in (
                ("top", self.spec(colors={"accent": "#fff"}), "unknown key 'colors'"),
                ("colours", self.spec(colours={"accent": "#fff", "primary": "#000"}), "unknown key 'primary'"),
                ("fonts", self.spec(fonts={"heading": GOOD_BRAND["fonts"]["heading"], "mono": {}}), "unknown key 'mono'"),
                ("font entry", self.spec(fonts={"body": {"family": "X", "file": "fonts/sans.woff2", "weight": 400}}), "unknown key 'weight'"),
                ("cover", self.spec(cover={"author": "x"}), "unknown key 'author'")):
            with self.subTest(label):
                probs = self.problems(spec)
                self.assertTrue(any(expect in p for p in probs), probs)

    def test_name_is_required_plain_text(self):
        spec = self.spec(); del spec["name"]
        self.assertOneProblem("name: is required", spec)
        for bad in ("", "   ", 5, None, ["x"], "<b>Agency</b>", "line\nbreak", "x" * 101):
            with self.subTest(repr(bad)[:20]):
                self.assertTrue(any(p.startswith("name:") for p in self.problems(self.spec(name=bad))))

    def test_colours_accept_only_rgb_and_rrggbb_hex(self):
        self.assertEqual(self.problems(self.spec(colours={"accent": "#fff", "ink": "#AbC123", "muted": "#000", "paper": "#FFFFFF"})), [])
        for bad in ("#ffff", "fff", "red", "#12345g", "rgb(0,0,0)", "#12", "", 7, None, "#fff;}"):
            with self.subTest(repr(bad)):
                self.assertOneProblem("colours.accent", self.spec(colours={"accent": bad}))

    def test_cover_and_footer_must_be_plain_text(self):
        for bad in ("", "a\nb", "<script>", "x" * 301, 5):
            with self.subTest(repr(bad)[:15]):
                self.assertTrue(any(p.startswith("cover.contact") for p in self.problems(self.spec(cover={"contact": bad}))))
                self.assertTrue(any(p.startswith("footer") for p in self.problems(self.spec(footer=bad))))

    def test_brand_json_must_be_a_json_object(self):
        for text, expect in (("{nope", "cannot be read as JSON"), ("[]", "must hold a JSON object"), ('"text"', "must hold a JSON object")):
            with self.subTest(text):
                self.assertOneProblem(expect, text, files=False)
        shutil.rmtree(self.brand)
        self.brand.mkdir()
        self.assertEqual(BC.check_brand(self.brand).problems, ["brand.json: file does not exist: brand.json"])

    def test_brand_md_is_ignored_even_when_it_is_odd(self):
        self.make(**{"brand.md": b"\xff\xfe not utf-8 \x00"})
        self.assertEqual(BC.check_brand(self.brand).problems, [])


class Files(BrandCase):
    def test_missing_logo_and_font_files(self):
        self.make()
        (self.brand / "logo.png").unlink(); (self.brand / "fonts" / "sans.woff2").unlink()
        probs = BC.check_brand(self.brand).problems
        self.assertEqual(len(probs), 2)
        self.assertTrue(any(p.startswith("logo: file does not exist") for p in probs))
        self.assertTrue(any(p.startswith("fonts.body.file: file does not exist") for p in probs))

    def test_paths_must_stay_inside_the_folder(self):
        (self.root / "outside.png").write_bytes(img.png())
        for bad in ("../outside.png", "fonts/../../outside.png", "/etc/hosts", str(self.root / "outside.png"), "C:/x.png", "a\\\\b.png"):
            with self.subTest(bad):
                self.assertTrue(any(p.startswith("logo:") for p in self.problems(self.spec(logo=bad))), bad)

    def test_symlinked_files_and_folders_are_refused(self):
        self.make()
        outside = self.root / "outside.png"; outside.write_bytes(img.png())
        self.symlink(outside, "linked.png")
        self.assertTrue(any("symlink" in p for p in BC.check_brand(self._with(logo="linked.png")).problems))
        real = self.root / "realfonts"; real.mkdir(); (real / "f.woff2").write_bytes(FAKE_WOFF2)
        self.symlink(real, "linkedfonts")
        self.assertTrue(any("symlink" in p for p in BC.check_brand(self._with(logo="logo.png", fonts={"body": {"family": "X", "file": "linkedfonts/f.woff2"}})).problems))

    def _with(self, **changes):
        spec = self.spec(**changes)
        (self.brand / "brand.json").write_text(json.dumps(spec), encoding="utf-8")
        return self.brand

    def test_a_directory_is_not_a_file(self):
        (self.brand / "logo.png").unlink() if (self.brand / "logo.png").exists() else None
        self.make(files=False)
        (self.brand / "fonts" / "serif.woff2").write_bytes(FAKE_WOFF2); (self.brand / "fonts" / "sans.woff2").write_bytes(FAKE_WOFF2)
        (self.brand / "logo.png").mkdir()
        self.assertTrue(any("not a regular file" in p for p in BC.check_brand(self.brand).problems))

    def test_logo_images_pass_the_same_structural_check_as_screenshots(self):
        for name, data in (("logo.png", img.png()), ("logo.jpg", img.JPEG), ("logo.webp", img.WEBP)):
            with self.subTest(name):
                self.assertEqual(self.problems(self.spec(logo=name), **{name: data}), [])
        for name, data in (("logo.png", img.TRUNCATED["png-no-iend"]), ("logo.jpg", img.TRUNCATED["jpeg-no-scan-data"]),
                           ("logo.webp", img.TRUNCATED["webp-empty-vp8-chunk"]), ("logo.png", img.NOT_AN_IMAGE)):
            with self.subTest("bad " + name):
                probs = self.problems(self.spec(logo=name), **{name: bytes(data)})
                self.assertEqual(len(probs), 1, probs)
                self.assertTrue(probs[0].startswith("logo:"))

    def svg_problems(self, text):
        return self.problems(self.spec(logo="logo.svg"), **{"logo.svg": text})

    def test_logo_extension_rule(self):
        self.assertOneProblem("logo: must be one of", self.spec(logo="logo.gif"), **{"logo.gif": img.GIF})

    def test_a_real_svg_is_accepted_with_or_without_a_namespace(self):
        self.assertEqual(self.svg_problems('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>'), [])
        self.assertEqual(self.svg_problems('<?xml version="1.0" encoding="UTF-8"?>\n<svg width="4" height="4"><rect width="4" height="4"/></svg>'), [])

    def test_svg_lookalikes_are_refused(self):
        cases = {
            "text that merely mentions svg": ("not XML <svg", "not well-formed XML"),
            "svg-like root name": ("<svg-not-real/>", "root element is 'svg-not-real'"),
            "html page containing an svg": ("<html><body><svg/></body></html>", "root element is 'html'"),
            "wrong namespace": ('<svg xmlns="http://example.com/not-svg"/>', "root element"),
            "unclosed": ('<svg xmlns="http://www.w3.org/2000/svg"><g>', "not well-formed XML"),
            "empty": ("", "not well-formed XML"),
            "binary": (b"\xff\xfe<svg/>", "not UTF-8"),
        }
        for label, (text, expect) in cases.items():
            with self.subTest(label):
                probs = self.svg_problems(text)
                self.assertEqual(len(probs), 1, probs)
                self.assertTrue(probs[0].startswith("logo:") and expect in probs[0], probs)

    def test_doctype_and_entity_declarations_are_refused_before_any_parsing(self):
        import time
        laughs = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">' + "".join(f'<!ENTITY lol{n+1} "{"&lol%s;" % (n if n else "") * 10}">' for n in range(1, 9))
                  + ']><svg xmlns="http://www.w3.org/2000/svg"><text>&lol9;</text></svg>')
        for label, text in (("billion laughs", laughs), ("doctype only", '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://example.com/svg11.dtd"><svg/>'),
                            ("entity", '<!ENTITY a "b"><svg/>'), ("spaced and mixed case", '<! DocType svg><svg/>')):
            with self.subTest(label):
                t0 = time.time()
                probs = self.svg_problems(text)
                self.assertLess(time.time() - t0, 1)
                self.assertEqual(len(probs), 1, probs)
                self.assertIn("DOCTYPE or ENTITY declaration, which is not allowed", probs[0])

    def test_an_svg_with_script_or_external_references_is_accepted_with_a_note(self):
        self.make(self.spec(logo="logo.svg"), **{"logo.svg": '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><image href="http://example.com/x.png"/></svg>'})
        res = BC.check_brand(self.brand)
        self.assertEqual(res.problems, [])
        self.assertEqual(len(res.notes), 1)
        self.assertIn("inert because the logo is embedded as an image", res.notes[0])

    def test_font_signature_extension_and_family(self):
        for name, ok in (("a.woff2", b"wOF2" + b"\0" * 8), ("a.woff", b"wOFF" + b"\0" * 8), ("a.ttf", b"\x00\x01\x00\x00" + b"\0" * 8),
                         ("a.ttf", b"true" + b"\0" * 8), ("a.otf", b"OTTO" + b"\0" * 8)):
            with self.subTest("ok " + name):
                self.assertEqual(self.problems(self.spec(fonts={"body": {"family": "X Y", "file": "fonts/" + name}}), **{"fonts__" + name: ok}), [])
        self.assertOneProblem("does not have a woff2 font signature", self.spec(fonts={"body": {"family": "X", "file": "fonts/a.woff2"}}), **{"fonts__a.woff2": b"MZ\x90\x00 an executable"})
        self.assertOneProblem("must be .woff2", self.spec(fonts={"body": {"family": "X", "file": "fonts/a.exe"}}), **{"fonts__a.exe": b"wOF2"})
        for bad in ('Evil"; } body { x: y', "A;B", "{x}", "", "x" * 61, "</style>", 5):
            with self.subTest(repr(bad)[:20]):
                self.assertTrue(any("fonts.body.family" in p for p in self.problems(self.spec(fonts={"body": {"family": bad, "file": "fonts/sans.woff2"}}))))
        self.assertOneProblem("fonts.body", self.spec(fonts={"body": {"family": "X"}}))


class Unreadable(BrandCase):
    def lock(self, rel):
        p = self.brand / rel
        p.chmod(0)
        self.addCleanup(lambda: p.chmod(0o644))
        try:
            p.read_bytes()
        except OSError:
            return
        self.skipTest("this account can read files with no permissions (running as root?)")

    def test_files_that_exist_but_cannot_be_read_are_problems_not_crashes(self):
        for rel, key in (("logo.png", "logo"), ("fonts/serif.woff2", "fonts.heading.file"), ("fonts/sans.woff2", "fonts.body.file"),
                         ("cover.md", "cover.md"), ("brand.json", "brand.json")):
            with self.subTest(rel):
                self.make(None, **{"cover.md": "# {title}\n"})
                self.lock(rel)
                probs = BC.check_brand(self.brand).problems
                self.assertEqual(len(probs), 1, probs)
                self.assertTrue(probs[0].startswith(key + ":"), probs)
                self.assertIn(Path(rel).name, probs[0])
                self.assertIn("PermissionError", probs[0])
                (self.brand / rel).chmod(0o644)

    def test_the_cli_reports_it_and_exits_1(self):
        self.make()
        self.lock("logo.png")
        r = qs.run_script(CHECK, self.brand)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("logo: cannot read logo.png", r.stdout)

    def test_an_unreadable_folder_is_a_problem_too(self):
        self.make()
        d = self.brand / "fonts"
        d.chmod(0)
        self.addCleanup(lambda: d.chmod(0o755))
        try:
            list(d.iterdir())
            self.skipTest("this account can read folders with no permissions (running as root?)")
        except OSError:
            pass
        probs = BC.check_brand(self.brand).problems
        self.assertEqual(len(probs), 2, probs)
        self.assertTrue(all(p.startswith("fonts.") for p in probs))


class NoReportCss(BrandCase):
    def test_a_report_css_in_the_pack_is_a_problem_whatever_it_holds(self):
        for label, content in (("harmless", "h2 { color: red }"), ("empty", ""), ("print rule", "@media print { figure { display: none } }"), ("binary", b"\xff\xfe\x00")):
            with self.subTest(label):
                probs = self.problems(None, **{"report.css": content})
                self.assertEqual(len(probs), 1, probs)
                self.assertEqual(probs[0], "report.css: report.css is not supported: brand styling comes from brand.json colours and fonts only (the exporter never reads it)")

    def test_an_unreadable_or_symlinked_report_css_gives_the_same_single_problem(self):
        self.make()
        real = self.root / "real.css"; real.write_text("a{}", encoding="utf-8")
        self.symlink(real, "report.css")
        probs = BC.check_brand(self.brand).problems
        self.assertEqual(len(probs), 1, probs)
        self.assertIn("report.css is not supported", probs[0])

    def test_the_exporter_never_reads_a_css_key_even_if_one_is_smuggled_in(self):
        self.make()
        brand = BC.check_brand(self.brand).brand
        brand["css"] = "figure { display: none; } /* SMUGGLED */"
        css, _ = EX.brand_stylesheet(brand)
        self.assertNotIn("SMUGGLED", css)
        page, _ = EX.build_html("# R\n", {}, brand, "2026-10-14")
        self.assertNotIn("SMUGGLED", page)

    def test_the_only_stylesheet_is_ours_plus_values_generated_from_brand_json(self):
        self.make()
        brand = BC.check_brand(self.brand).brand
        page, _ = EX.build_html("# R\n", {}, brand, "2026-10-14")
        style = page[page.index("<style>") + 7:page.index("</style>")]
        generated, _ = EX.brand_stylesheet(brand)
        self.assertEqual(style, EX.CSS + generated)
        self.assertEqual(page.count("<style>"), 1)


class CoverMdRules(BrandCase):
    def test_other_text_file_rules(self):
        self.assertOneProblem("cover.md: is not UTF-8", None, **{"cover.md": b"\xff\xfe"})
        self.assertOneProblem("larger than", None, **{"cover.md": "a" * (200 * 1024 + 1)})
        self.assertOneProblem("must not contain images", None, **{"cover.md": "![Logo](logo.png)\n"})
        self.assertEqual(self.problems(None, **{"cover.md": "# {title}\n\nPrepared by {prepared_by}\n"}), [])

    def test_symlinked_cover_md_is_refused(self):
        self.make()
        real = self.root / "real.md"; real.write_text("# x", encoding="utf-8")
        self.symlink(real, "cover.md")
        self.assertTrue(any("symlink" in p for p in BC.check_brand(self.brand).problems))


class Cli(BrandCase):
    def run_check(self, *args):
        return qs.run_script(CHECK, *args)

    def test_clean_pack_exits_0_with_a_summary(self):
        self.make()
        r = self.run_check(self.brand)
        self.assertEqual((r.returncode, r.stdout), (0, "brand pack Example Agency: 0 problems\n"))

    def test_every_problem_is_printed_and_exit_is_1(self):
        self.make(self.spec(colours={"accent": "red"}, footer="<x>"), **{"report.css": "a { color: red }"})
        r = self.run_check(self.brand)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(r.stdout.strip().splitlines()), 4)
        self.assertTrue(r.stdout.strip().endswith("3 problems"))
        for part in ("colours.accent", "footer", "report.css: report.css is not supported"):
            self.assertIn(part, r.stdout)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.run_check().returncode, 2)
        self.assertEqual(self.run_check(self.root / "nope").returncode, 2)
        self.assertEqual(self.run_check(self.root / "brand" / "brand.json").returncode, 2)
        self.assertEqual(self.run_check("--help").returncode, 0)

    def test_missing_markdown_package_exits_2(self):
        self.make()
        blocker = self.root / "blocker" / "markdown"; blocker.mkdir(parents=True)
        (blocker / "__init__.py").write_text('raise ImportError("blocked", name="markdown")\n', encoding="utf-8")
        r = qs.run_script(CHECK, self.brand, env={"PYTHONPATH": str(blocker.parent)})
        self.assertEqual(r.returncode, 2)
        self.assertIn("markdown", r.stderr)


class ExportCase(BrandCase):
    def setUp(self):
        super().setUp()
        self.run_dir = self.root / "run"
        (self.run_dir / "screenshots").mkdir(parents=True)
        shutil.copy(REPORT_FIXTURES / "sample_report.md", self.run_dir / "report.md")
        (self.run_dir / "screenshots" / "home.png").write_bytes(img.png((255, 0, 0)))
        (self.run_dir / "screenshots" / "contact.png").write_bytes(img.png((0, 0, 255)))

    def export(self, *args, env=None, pdf=False):
        out = self.root / ("o.pdf" if pdf else "o.html")
        r = qs.run_script(EXPORT, self.run_dir / "report.md", "--pdf" if pdf else "--html", out, "--date", "2026-10-14", *args, env=env, cwd=self.root)
        return r, (out.read_bytes() if out.exists() else None)

    def page(self, *args, **kw):
        r, data = self.export(*args, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return data.decode("utf-8")


class HtmlWithBrand(ExportCase):
    def test_without_a_brand_the_page_is_exactly_the_plain_page(self):
        text = (self.run_dir / "report.md").read_text(encoding="utf-8")
        res = EX.report_check.check(self.run_dir / "report.md")
        imgs = {e["src"]: {"path": e["path"], "mime": e["mime"]} for e in res.embedded if e["path"]}
        page, rend = EX.build_html(text, imgs)
        body = EX.Renderer(imgs).render(EX.parse_html(EX.report_check.render_markdown(text)))
        legacy = (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
                  f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">\n'
                  f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>Example Garden Centre: QA report</title>\n'
                  f'<style>{EX.CSS}</style></head>\n<body>\n{body}\n</body></html>\n')
        self.assertEqual(page, legacy)
        self.assertEqual(page, EX.build_html(text, imgs, None, "2026-10-14")[0])   # a date alone changes nothing
        for marker in ("cover", "brand", "font-src", "--accent"):
            self.assertNotIn(marker, page)

    def test_a_brand_adds_cover_colours_fonts_and_footer(self):
        self.make()
        page = self.page("--brand", self.brand)
        cover = page.index('<section class="cover">')
        self.assertLess(cover, page.index("Verdict:"))
        self.assertRegex(page, r'<img class="brand-logo" src="data:image/png;base64,[A-Za-z0-9+/=]+" alt="Example Agency logo">')
        self.assertIn('<p class="cover-title">Example Garden Centre: QA report</p>', page)
        self.assertIn('<p class="cover-brand">Example Agency</p>', page)
        self.assertIn('<p class="cover-date">2026-10-14</p>', page)
        for label, value in (("Prepared by", "Pat Example"), ("Contact", "hello@example.com"), ("Confidentiality", "Confidential - client use only")):
            self.assertIn(f"<dt>{label}</dt><dd>{value}</dd>", page)
        self.assertIn("--accent: #0a5c36; --ink: #112233; --muted: #667788; --paper: #fffef8;", page)
        self.assertIn('@font-face { font-family: "Example Serif"; src: url(data:font/woff2;base64,', page)
        self.assertIn('format("woff2")', page)
        self.assertIn('h1, h2, h3, h4, .cover .cover-title { font-family: "Example Serif"', page)
        self.assertIn('<footer class="brand-footer">Example Agency | example.com | Confidential</footer>', page)
        self.assertIn("font-src data:", page)
        self.assertEqual(page.count("<figure>"), 2)   # the logo is not a figure

    def test_font_src_is_added_only_when_fonts_are_used(self):
        self.make(self.spec(fonts={}), files=True)
        page = self.page("--brand", self.brand)
        self.assertNotIn("font-src", page)
        self.assertIn("img-src data:;", page)

    def test_colours_default_to_the_plain_look_when_not_given(self):
        self.make({"name": "Example Agency"}, files=False)
        page = self.page("--brand", self.brand)
        self.assertIn("--accent: #1b1f24;", page)
        self.assertNotIn('<img class="brand-logo"', page)
        self.assertNotIn("<footer", page)
        self.assertNotIn("cover-fields", page)

    def test_nothing_in_the_brand_page_points_at_the_network(self):
        self.make()
        page = self.page("--brand", self.brand)
        self.assertNotRegex(re.sub(r'<a href="[^"]*"', "", page), r"(?i)https?:|(?:src|href)=.?//|@import")
        self.assertNotRegex(page, r"(?i)url\((?!data:)")
        self.assertNotRegex(page, r"(?i)<(script|link|iframe|object|embed)")

    def test_user_text_cannot_break_out_of_html_or_css(self):
        spec = self.spec(name='A&B "Co" \\ <i>', footer='He said "hi" \\ ok')
        spec["name"] = 'A&B "Co" \\'
        self.make(spec)
        page = self.page("--brand", self.brand)
        self.assertEqual(page.count("</style>"), 1)
        self.assertIn("A&amp;B &quot;Co&quot; \\", page)
        footer_rule = re.search(r'@bottom-center \{ content: "([^\n]*?)";', page).group(1)
        self.assertNotIn('"', footer_rule)
        self.assertIn("\\22 ", footer_rule)
        self.assertIn("\\5c ", footer_rule)


class FooterFont(ExportCase):
    def footer_rule(self, page):
        return re.search(r"@page \{ @bottom-center \{ ([^}]*) \} \}", page).group(1)

    def test_footer_uses_the_report_font_stack_by_default(self):
        self.make(self.spec(fonts={}))
        rule = self.footer_rule(self.page("--brand", self.brand))
        self.assertIn("font-family: -apple-system, Helvetica, Arial, sans-serif;", rule)
        self.assertIn("font-size: 9px;", rule)
        self.assertIn("color: #667788;", rule)

    def test_footer_uses_the_brand_body_font_first_when_one_is_given(self):
        self.make()
        rule = self.footer_rule(self.page("--brand", self.brand))
        self.assertIn('font-family: "Example Sans", -apple-system, Helvetica, Arial, sans-serif;', rule)

    def test_footer_colour_falls_back_to_the_plain_muted_colour(self):
        self.make({"name": "Example Agency", "footer": "Example Agency footer"}, files=False)
        self.assertIn("color: #4a5056;", self.footer_rule(self.page("--brand", self.brand)))

    def test_the_headline_fonts_use_the_same_stack(self):
        self.make()
        page = self.page("--brand", self.brand)
        self.assertIn('h1, h2, h3, h4, .cover .cover-title { font-family: "Example Serif", -apple-system, Helvetica, Arial, sans-serif; }', page)


class ChromeVersion(ExportCase):
    def test_version_strings(self):
        for text, major in (("Google Chrome 155.0.8059.40 \n", 155), ("Google Chrome 131.0.6778.85", 131), ("Chromium 120.0.6099.109 built on Debian 12.4, running on Debian 12.5", 120),
                            ("Google Chrome for Testing 130.0.6723.58", 130), ("Chromium 99.0.4844.84 snap", 99), ("", None), (None, None), ("Chrome beta", None)):
            with self.subTest(text):
                self.assertEqual(EX.parse_chrome_major(text), major)

    def run_with_chrome_version(self, major, brand_has_footer=True, pdf_fails=True):
        spec = self.spec() if brand_has_footer else self.spec(footer=None)
        if not brand_has_footer: del spec["footer"]
        self.make(spec)
        out, buf = self.root / "x.pdf", io.StringIO()
        with mock.patch.object(EX, "chrome_major_version", return_value=major), mock.patch.object(EX, "probe_decode", return_value=(True, [], "")), \
                mock.patch.object(EX, "print_pdf", return_value=(False, "stopped for the test")), mock.patch.object(EX.os.path, "isfile", return_value=True), \
                mock.patch.object(EX.os, "access", return_value=True), contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            EX.main([str(self.run_dir / "report.md"), "--pdf", str(out), "--brand", str(self.brand)])
        return buf.getvalue()

    def test_old_chrome_with_a_footer_gets_a_one_line_note(self):
        text = self.run_with_chrome_version(120)
        notes = [l for l in text.splitlines() if "brand footer will be missing" in l]
        self.assertEqual(notes, ["note: Chrome 120 is older than 131: the brand footer will be missing from the PDF (page margin boxes need Chrome 131 or later)."])

    def test_no_note_for_chrome_131_or_newer_unknown_versions_or_brands_without_a_footer(self):
        for major, footer in ((131, True), (155, True), (None, True), (120, False)):
            with self.subTest(major=major, footer=footer):
                self.assertNotIn("brand footer will be missing", self.run_with_chrome_version(major, footer))

    def test_the_version_is_asked_once_and_remembered(self):
        EX._chrome_major.clear()
        with mock.patch.object(EX.subprocess, "run", return_value=mock.Mock(stdout="Google Chrome 130.0.1.2")) as run:
            self.assertEqual((EX.chrome_major_version(), EX.chrome_major_version()), (130, 130))
        self.assertEqual(run.call_count, 1)
        EX._chrome_major.clear()
        with mock.patch.object(EX.subprocess, "run", side_effect=OSError("no chrome")):
            self.assertIsNone(EX.chrome_major_version())
        EX._chrome_major.clear()


class ShippedExample(unittest.TestCase):
    def test_the_example_brand_pack_passes_brand_check(self):
        example = qs.ROOT / "skills" / "qa-standards" / "brand-example"
        r = qs.run_script(CHECK, example)
        self.assertEqual((r.returncode, r.stdout.strip().splitlines()[-1]), (0, "brand pack Example Agency: 0 problems"), r.stdout + r.stderr)


class CoverMarkdown(ExportCase):
    def test_placeholders_are_substituted_as_escaped_text_through_the_safe_pipeline(self):
        spec = self.spec(cover={"prepared_by": "*Pat* [Example](http://evil.example/x) `code` ![x](y.png)", "contact": "a_b_c@example.com",
                                "confidentiality": "# not a heading"}, name="Example Agency")
        self.make(spec, **{"cover.md": "# {title}\n\nBy {brand} on {date}\n\nPrepared by: {prepared_by}\n\nContact: {contact}\n\n{confidentiality}\n\n{unknown}\n\n<script>alert(2)</script>\n"})
        page = self.page("--brand", self.brand)
        cover = page[page.index('<section class="cover">'):page.index("</section>")]
        self.assertIn("<h1>Example Garden Centre: QA report</h1>", cover)
        self.assertIn("By Example Agency on 2026-10-14", cover)
        self.assertIn("Prepared by: *Pat* [Example](http://evil.example/x) `code` ![x](y.png)", cover)
        self.assertIn("Contact: a_b_c@example.com", cover)
        self.assertIn("<p># not a heading</p>", cover)
        self.assertIn("{unknown}", cover)
        self.assertIn("&lt;script&gt;alert(2)&lt;/script&gt;", cover)
        for bad in ("<script", "<a ", "<em>", "<strong>"):
            self.assertNotIn(bad, cover)
        self.assertIn('class="brand-logo"', cover)   # the logo is placed above a custom cover too
        self.assertNotIn("cover-title", cover)

    def test_a_value_cannot_inject_another_placeholder(self):
        self.make(self.spec(cover={"prepared_by": "{contact}", "contact": "SECRET"}), **{"cover.md": "{prepared_by}\n"})
        page = self.page("--brand", self.brand)
        self.assertIn("<p>{contact}</p>", page)
        self.assertNotIn("SECRET</p>\n</section>", page)


class BrandSelection(ExportCase):
    def test_flag_env_and_no_brand(self):
        self.make()
        other = self.root / "other"; other.mkdir()
        (other / "brand.json").write_text(json.dumps({"name": "Other Agency"}), encoding="utf-8")
        env = {"QA_BRAND": str(self.brand)}
        self.assertIn("Example Agency", self.page(env=env))
        self.assertIn("Other Agency", self.page("--brand", other, env=env))   # the flag beats the variable
        self.assertNotIn('class="cover"', self.page("--no-brand", env=env))   # --no-brand ignores the variable
        r, _ = self.export("--brand", self.brand, "--no-brand")
        self.assertEqual(r.returncode, 2)

    def test_unusable_brand_folders(self):
        r, data = self.export("--brand", self.root / "missing")
        self.assertEqual((r.returncode, data), (2, None))
        r, data = self.export(env={"QA_BRAND": str(self.root / "missing")})
        self.assertEqual((r.returncode, data), (2, None))

    def test_a_bad_brand_refuses_the_export_and_writes_nothing(self):
        self.make(self.spec(colours={"accent": "red"}), **{"report.css": "a { color: red }"})
        r, data = self.export("--brand", self.brand)
        self.assertEqual((r.returncode, data), (1, None))
        self.assertIn("brand: colours.accent", r.stdout)
        self.assertIn("brand: report.css: report.css is not supported", r.stdout)
        self.assertIn("refusing to export: the brand pack has 2 problem(s)", r.stdout)

    def test_date_option(self):
        self.make()
        r, _ = self.export("--brand", self.brand, "--date", "14/10/2026")
        self.assertEqual(r.returncode, 2)
        out = self.root / "d.html"
        r = qs.run_script(EXPORT, self.run_dir / "report.md", "--html", out, "--brand", self.brand, cwd=self.root)
        import datetime
        self.assertIn(f'<p class="cover-date">{datetime.date.today()}</p>', out.read_text(encoding="utf-8"))


class ScreenshotsStayDistinctFromBrandImages(ExportCase):
    def test_report_figures_ignore_the_cover_logo(self):
        self.make()
        page = self.page("--brand", self.brand)
        self.assertEqual(len(EX.report_figures(page)), 2)
        self.assertEqual(page.count("<img "), 3)
        self.assertEqual([alt for _, alt in EX.report_figures(page)],
                         ["Booking button missing at 375 px wide", "Contact form after submitting an empty email field"])


@unittest.skipUnless(CHROME_OK, f"Chrome not found at {EX.CHROME}; set CHROME_PATH to run the real PDF tests")
class HiddenScreenshots(ExportCase):
    """Defence in depth: report.css is gone, so only our own stylesheet applies; the probe still has to notice a figure that is not shown,
    whatever the cause, so these tests inject rules into the page directly."""

    def inject(self, text, rules):
        self.make()
        brand = BC.check_brand(self.brand).brand
        (self.run_dir / "report.md").write_text(text, encoding="utf-8")
        check = EX.report_check.check(self.run_dir / "report.md")
        imgs = {e["src"]: {"path": e["path"], "mime": e["mime"]} for e in check.embedded if e["path"]}
        page, rend = EX.build_html(text, imgs, brand, "2026-10-14")
        return page.replace("</style>", rules + "\n</style>", 1), rend

    def test_a_pack_with_report_css_that_tries_to_hide_figures_is_refused_at_validation(self):
        self.make(None, **{"report.css": "@media print { figure { display: none } }"})
        r, data = self.export("--brand", self.brand)
        self.assertEqual((r.returncode, data), (1, None))
        self.assertIn("brand: report.css: report.css is not supported", r.stdout)

    def test_the_probe_reports_each_way_of_hiding_a_figure_and_leaves_a_normal_one_alone(self):
        hiding = ["display: none", "visibility: hidden", "opacity: 0", "width: 0; height: 0", "max-height: 0; overflow: hidden", "transform: scale(0)",
                  "clip-path: inset(100%)", "position: absolute; left: -9999px", "filter: opacity(0)", "content-visibility: hidden"]
        text = "\n\n".join(f"![Shot {n}](screenshots/home.png)" for n in range(1, len(hiding) + 2)) + "\n"
        page, _ = self.inject(text, "\n".join(f"figure:nth-of-type({n}) {{ {rule}; }}" for n, rule in enumerate(hiding, start=1)))
        ok, not_loaded, not_shown, err = EX.probe_details(page)
        self.assertEqual((ok, not_loaded), (True, []), err)
        self.assertEqual(not_shown, list(range(len(hiding))), "every hiding rule must be caught; the last figure (no rule) must pass")

    def test_the_probe_reports_a_hidden_figure_by_number(self):
        page, _ = self.inject("# R\n\n![Only screenshot](screenshots/home.png)\n", "figure { display: none; }")
        self.assertEqual(EX.probe_decode(page)[:2], (True, [0]))

    def test_main_stops_before_printing_when_the_probe_finds_a_hidden_screenshot(self):
        (self.run_dir / "report.md").write_text("# R\n\n![Only screenshot](screenshots/home.png)\n", encoding="utf-8")
        self.make()
        original = EX.build_html
        patched = lambda *a, **k: (lambda r: (r[0].replace("</style>", "figure { display: none; }</style>", 1), r[1]))(original(*a, **k))
        buf, out = io.StringIO(), self.root / "x.pdf"
        with mock.patch.object(EX, "build_html", side_effect=patched), contextlib.redirect_stdout(buf):
            code = EX.main([str(self.run_dir / "report.md"), "--pdf", str(out), "--brand", str(self.brand)])
        self.assertEqual(code, 1)
        self.assertIn("loaded but are not visibly shown in the page", buf.getvalue())
        self.assertIn('image 1 ("Only screenshot")', buf.getvalue())
        self.assertFalse(out.exists())

    def test_a_logo_only_pdf_fails_verification_because_the_measured_logo_is_added_to_the_target(self):
        pdf = self.root / "logo-only.pdf"
        pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /XObject /Subtype /Image /Width 1 /Height 1 >>\nstream\nX\nendstream\nendobj\n%%EOF\n")
        self.assertEqual(EX.verify_pdf(pdf, 2)[:1], (False,))   # one screenshot + one logo image
        self.assertTrue(EX.verify_pdf(pdf, 1)[0])

    def test_a_logo_that_is_byte_identical_to_a_screenshot_is_not_double_counted(self):
        self.make()
        (self.brand / "logo.png").write_bytes((self.run_dir / "screenshots" / "home.png").read_bytes())
        r, data = self.export("--brand", self.brand, pdf=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@unittest.skipUnless(CHROME_OK, f"Chrome not found at {EX.CHROME}; set CHROME_PATH to run the real PDF tests")
class RealPdfWithBrand(ExportCase):
    LOGOS = {
        "png": ("logo.png", lambda: img.png((10, 90, 54), size=48)),
        "vector svg": ("logo.svg", lambda: b'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="30"><rect width="80" height="30" fill="#0a5"/><circle cx="15" cy="15" r="8" fill="#fff"/></svg>'),
        "svg embedding a png": ("logo.svg", lambda: (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="48" height="48"><image width="48" height="48" xlink:href="data:image/png;base64,'
                                                      + __import__("base64").b64encode(img.png((200, 30, 90), size=48)) + b'"/></svg>')),
    }

    def single_screenshot_report(self):
        text = "# R\n\n![Only screenshot](screenshots/home.png)\n"
        (self.run_dir / "report.md").write_text(text, encoding="utf-8")
        return text

    def logo_brand(self, name, data):
        self.make(self.spec(logo=name, fonts={}), **{name: data})
        return BC.check_brand(self.brand).brand

    def test_the_target_is_the_screenshots_plus_the_measured_logo_images_for_every_kind_of_logo(self):
        measured_by = {}
        for label, (name, make) in self.LOGOS.items():
            with self.subTest(label):
                text = self.single_screenshot_report()
                brand = self.logo_brand(name, make())
                measured = measured_by[label] = EX.measure_logo_images(brand, "R", "2026-10-14")
                print(f"\n[logo] {label}: the cover adds {measured} image object(s) to a PDF", file=sys.stderr)
                # the full export passes with the bound screenshots + measured logo images
                r, data = self.export("--brand", self.brand, pdf=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                found = EX.count_pdf(data)[0]
                self.assertGreaterEqual(found, 1 + measured)
                # a PDF that lost the screenshot is refused in every case: only the logo's images remain
                check = EX.report_check.check(self.run_dir / "report.md")
                imgs = {e["src"]: {"path": e["path"], "mime": e["mime"]} for e in check.embedded if e["path"]}
                page, _ = EX.build_html(text, imgs, brand, "2026-10-14")
                stripped = self.root / "stripped.html"
                stripped.write_text(re.sub(r"<figure>.*?</figure>", "", page, flags=re.S), encoding="utf-8")
                pdf = self.root / "stripped.pdf"
                self.assertTrue(EX.print_pdf(stripped, pdf)[0])
                ok, msg, got = EX.verify_pdf(pdf, 1 + measured)
                self.assertFalse(ok, msg)
                self.assertEqual(got, measured)
        self.assertEqual(measured_by["png"], 1)
        self.assertEqual(measured_by["vector svg"], 0)
        self.assertGreaterEqual(measured_by["svg embedding a png"], 1)

    def test_a_logo_that_cannot_be_measured_stops_the_export_and_a_brand_without_a_logo_is_not_measured(self):
        # Failing closed: a guessed 0 would let the logo stand in for a missing screenshot.
        brand = self.logo_brand("logo.png", img.png())
        with mock.patch.object(EX, "print_pdf", return_value=(False, "no chrome")):
            self.assertIsNone(EX.measure_logo_images(brand, "R", "2026-10-14"))
        self.make()
        err = io.StringIO()
        with mock.patch.object(EX, "measure_logo_images", return_value=None), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            code = EX.main([str(self.run_dir / "report.md"), "--pdf", str(self.root / "m.pdf"), "--date", "2026-10-14", "--brand", str(self.brand)])
        self.assertEqual(code, 1)
        self.assertIn("could not print the brand cover on its own", err.getvalue())
        self.make({"name": "Example Agency"}, files=False)
        with mock.patch.object(EX, "measure_logo_images") as measure:
            r, _ = self.export("--brand", self.brand, pdf=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        measure.assert_not_called()

    def test_the_measuring_leaves_no_temporary_files_behind(self):
        before = {p.name for p in Path(tempfile.gettempdir()).glob("qa-export-logo-*")}
        brand = self.logo_brand("logo.png", img.png())
        EX.measure_logo_images(brand, "R", "2026-10-14")
        self.assertEqual({p.name for p in Path(tempfile.gettempdir()).glob("qa-export-logo-*")} - before, set())

    def test_pdf_with_a_brand_verifies_only_the_screenshots_and_carries_the_footer_on_every_page(self):
        self.make()
        r, data = self.export("--brand", self.brand, pdf=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"PDF written: .* \((\d+) pages, \d+ image objects found, 2 images verified\)")
        pages = int(re.search(r"\((\d+) pages", r.stdout).group(1))
        self.assertGreaterEqual(pages, 2)   # a cover page plus the report
        self.assertGreaterEqual(EX.count_pdf(data)[0], 3)   # two screenshots and the logo
        if not PDFTOTEXT:
            self.skipTest("pdftotext not installed: cannot read the footer text back out of the PDF")
        out = self.root / "o.pdf"
        text = subprocess.run([PDFTOTEXT, "-layout", str(out), "-"], capture_output=True, text=True).stdout
        self.assertEqual(text.count("Example Agency | example.com | Confidential"), pages, "the footer must appear once on every page")
        self.assertIn("Prepared by", text.split("\f")[0])   # the cover is the first page

    @unittest.skipUnless(PDFFONTS, "pdffonts not installed: the footer's CSS rule is asserted in FooterFont instead")
    def test_the_footer_is_printed_in_the_report_font_not_the_browser_default_serif(self):
        self.make(self.spec(fonts={}))
        r, data = self.export("--brand", self.brand, pdf=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        listing = subprocess.run([PDFFONTS, str(self.root / "o.pdf")], capture_output=True, text=True).stdout
        self.assertNotRegex(listing, r"(?i)times|serif", "a serif font in the PDF means the footer fell back to Chrome's default")

    def test_a_broken_screenshot_next_to_a_logo_is_named_correctly(self):
        import struct
        payload = b"\x2f" + b"\xff" * 60
        chunk = b"VP8L" + struct.pack("<I", len(payload)) + payload
        (self.run_dir / "screenshots" / "bad.webp").write_bytes(b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk)
        (self.run_dir / "report.md").write_text("# R\n\n![Fine](screenshots/home.png)\n\n![Broken](screenshots/bad.webp)\n", encoding="utf-8")
        self.make()
        r, data = self.export("--brand", self.brand, pdf=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('cannot be loaded by Chrome: image 2 ("Broken")', r.stdout)   # not image 3, and the logo is not in the list
        self.assertIsNone(data)

    def test_a_logo_that_chrome_cannot_load_does_not_count_as_a_screenshot_failure(self):
        # the logo is checked by brand_check, not by the screenshot probe; the screenshots still verify
        self.make()
        r, data = self.export("--brand", self.brand, pdf=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_an_svg_logo_with_script_and_external_references_runs_and_fetches_nothing(self):
        with qs.FixtureServer({"/pixel.png": img.png()}) as server:
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><script>fetch("{server.url("/script-ran")}")</script>'
                   f'<image href="{server.url("/pixel.png")}" width="10" height="10"/><rect width="40" height="20" fill="#0a5"/></svg>')
            self.make(self.spec(logo="logo.svg"), **{"logo.svg": svg})
            r, data = self.export("--brand", self.brand, pdf=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("note:", subprocess.run([sys.executable, str(CHECK), str(self.brand)], capture_output=True, text=True).stdout)
            html_out = self.root / "o.html"
            self.assertEqual(qs.run_script(EXPORT, self.run_dir / "report.md", "--html", html_out, "--brand", self.brand, cwd=self.root).returncode, 0)
            page = html_out.read_text(encoding="utf-8")
            self.assertIn('<img class="brand-logo" src="data:image/svg+xml;base64,', page)
            self.assertNotIn("<svg", page)
            ok, bad, err = EX.probe_decode(page)
            self.assertEqual((ok, bad), (True, []), err)
            self.assertEqual(server.requests, [], "no request may leave the page")


if __name__ == "__main__":
    unittest.main()
