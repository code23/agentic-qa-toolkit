"""report_check.py: a QA report must carry its screenshots (embedded Markdown images, safe paths, real image files)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import qa_support as qs

REPORT_FIXTURES = qs.FIXTURES / "report"
sys.path.insert(0, str(REPORT_FIXTURES))
import images as img  # noqa: E402

SCRIPT = qs.ROOT / "skills" / "qa-standards" / "scripts" / "report_check.py"
RC = qs.load_module("qa_report_check", SCRIPT)


class RunFolder(unittest.TestCase):
    """A temp run folder with report.md and a screenshots/ folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.run = self.root / "run"
        (self.run / "screenshots").mkdir(parents=True)
        self.outside = self.root / "outside.png"
        self.outside.write_bytes(img.png((1, 2, 3)))

    def shot(self, name="home.png", data=None, rgb=(255, 0, 0)):
        p = self.run / "screenshots" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(img.png(rgb) if data is None else data)
        return p

    def report(self, text):
        p = self.run / "report.md"
        p.write_text(text, encoding="utf-8")
        return p

    def check(self, text, **kw):
        return RC.check(self.report(text), **kw)

    def kinds(self, res):
        return [k for _, k, _ in res.problems]

    def cli(self, *args):
        return qs.run_script(SCRIPT, *args)


class Embedded(RunFolder):
    def test_a_clean_report_has_no_problems(self):
        self.shot()
        res = self.check("# R\n\n![Home page at 375 px](screenshots/home.png)\n")
        self.assertEqual((len(res.embedded), res.problems, res.notes), (1, [], []))

    def test_all_four_image_types_are_accepted(self):
        for name, data in (("a.png", img.png()), ("b.jpg", img.JPEG), ("c.jpeg", img.JPEG), ("d.webp", img.WEBP), ("e.gif", img.GIF)):
            self.shot(name, data)
        res = self.check("\n".join(f"![shot {n}](screenshots/{n})" for n in ("a.png", "b.jpg", "c.jpeg", "d.webp", "e.gif")))
        self.assertEqual(res.problems, [])
        self.assertEqual([e["mime"] for e in res.embedded], ["image/png", "image/jpeg", "image/jpeg", "image/webp", "image/gif"])

    def test_missing_file(self):
        res = self.check("![Gone](screenshots/gone.png)\n")
        self.assertEqual(self.kinds(res), ["missing"])
        self.assertEqual(res.problems[0][0], 1)

    def test_empty_file_and_files_that_are_not_images(self):
        self.shot("empty.png", b"")
        self.shot("page.png", img.NOT_AN_IMAGE)
        self.shot("short.png", b"\x89PNG")
        res = self.check("![a](screenshots/empty.png)\n\n![b](screenshots/page.png)\n\n![c](screenshots/short.png)\n")
        self.assertEqual(self.kinds(res), ["invalid", "invalid", "invalid"])
        self.assertIn("empty", res.problems[0][2])
        self.assertIn("not a real", res.problems[1][2])

    def test_a_target_that_is_not_an_image_file(self):
        (self.run / "screenshots" / "notes.pdf").write_bytes(b"%PDF-1.4")
        res = self.check("![notes](screenshots/notes.pdf)\n")
        self.assertEqual(self.kinds(res), ["invalid"])

    def test_absolute_paths(self):
        for target in ("/etc/screen.png", "~/screen.png", "C:/Users/x/screen.png", "C:\\Users\\x\\screen.png", str(self.outside)):
            with self.subTest(target):
                res = self.check(f"![x]({target})\n")
                self.assertEqual(self.kinds(res), ["unsafe"], res.problems)

    def test_urls_of_every_scheme(self):
        for target in ("http://example.com/a.png", "https://example.com/a.png", "data:image/png;base64,AAAA", "file:///tmp/a.png", "ftp://example.com/a.png"):
            with self.subTest(target):
                res = self.check(f"![x]({target})\n")
                self.assertEqual(self.kinds(res), ["unsafe"], res.problems)

    def test_dotdot_escape_is_refused_even_when_the_file_exists(self):
        res = self.check("![x](../outside.png)\n\n![y](screenshots/../../outside.png)\n")
        self.assertEqual(self.kinds(res), ["unsafe", "unsafe"])
        self.assertIn("outside the run folder", res.problems[0][2])

    def test_dotdot_that_stays_inside_the_run_folder_is_fine(self):
        self.shot()
        self.assertEqual(self.check("![x](screenshots/../screenshots/home.png)\n").problems, [])

    def test_symlink_pointing_outside_is_refused(self):
        link = self.run / "screenshots" / "link.png"
        try:
            os.symlink(self.outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available here")
        res = self.check("![x](screenshots/link.png)\n")
        self.assertEqual(self.kinds(res), ["unsafe"])

    def test_symlink_inside_the_run_folder_is_accepted(self):
        real = self.shot("real.png")
        link = self.run / "screenshots" / "alias.png"
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available here")
        self.assertEqual(self.check("![x](screenshots/alias.png)\n").problems, [])

    def test_symlinked_folder_pointing_outside_is_refused(self):
        outdir = self.root / "elsewhere"
        outdir.mkdir()
        (outdir / "s.png").write_bytes(img.png())
        try:
            os.symlink(outdir, self.run / "linked")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available here")
        self.assertEqual(self.kinds(self.check("![x](linked/s.png)\n")), ["unsafe"])

    def test_empty_alt_text(self):
        self.shot()
        res = self.check("![](screenshots/home.png)\n\n![   ](screenshots/home.png)\n")
        self.assertEqual(self.kinds(res), ["alt", "alt"])

    def test_title_attribute_dot_slash_percent_encoding_and_angle_brackets(self):
        self.shot("my shot.png")
        self.shot("plain.png", rgb=(0, 1, 0))
        res = self.check('![a](./screenshots/plain.png "A title")\n\n![b](screenshots/my%20shot.png)\n\n![c](<screenshots/my shot.png>)\n')
        self.assertEqual(res.problems, [])
        self.assertEqual(len(res.embedded), 3)

    def test_escaped_brackets_in_alt_text(self):
        self.shot()
        res = self.check(r"![Menu \[open\] state](screenshots/home.png)" + "\n")
        self.assertEqual((len(res.embedded), res.problems), (1, []))


class ParsedDocument(RunFolder):
    """What counts as an image is decided by the Markdown parser, the same one the exporter uses."""

    def not_an_image(self, text, expect_line):
        self.shot()
        res = self.check(text)
        self.assertEqual(len(res.embedded), 0, text)
        self.assertEqual([(l, k) for l, k, _ in res.problems], [(expect_line, "unembedded")], text)
        r = self.cli(self.run / "report.md", "--strict")
        self.assertEqual(r.returncode, 1, text)
        self.assertTrue(r.stdout.endswith("0 images embedded, 1 problems\n"), r.stdout)

    def test_image_syntax_inside_inline_code_is_text(self):
        self.not_an_image("# R\n\n`![Home](screenshots/home.png)`\n", 3)
        self.not_an_image("# R\n\nSee ``![Home](screenshots/home.png)`` here.\n", 3)

    def test_image_syntax_inside_a_fenced_block_is_text_and_not_even_a_mention(self):
        res = self.check("```\n![Home](screenshots/home.png)\n```\n")
        self.assertEqual((len(res.embedded), res.problems), (0, []))

    def test_image_syntax_inside_an_indented_code_block_is_text(self):
        self.not_an_image("# R\n\n    ![Home](screenshots/home.png)\n", 3)

    def test_an_escaped_bang_makes_a_link_not_an_image(self):
        self.not_an_image("# R\n\n\\![Home](screenshots/home.png)\n", 3)

    def test_a_real_image_next_to_code_samples_is_still_found(self):
        self.shot()
        res = self.check("`![x](screenshots/home.png)` and then ![Home](screenshots/home.png)\n")
        self.assertEqual((len(res.embedded), res.problems), (1, []))
        self.assertEqual(res.embedded[0]["line"], 1)

    def test_reference_style_images_are_images(self):
        self.shot()
        res = self.check("![Home page][home]\n\n[home]: screenshots/home.png\n")
        self.assertEqual((len(res.embedded), res.problems), (1, []))
        self.assertEqual(res.embedded[0]["src"], "screenshots/home.png")

    def test_image_inside_a_table_cell_is_an_image(self):
        self.shot()
        res = self.check("| shot |\n|---|\n| ![Home](screenshots/home.png) |\n")
        self.assertEqual((len(res.embedded), res.problems, res.embedded[0]["line"]), (1, [], 3))

    def test_target_forms_all_resolve_to_the_same_src(self):
        self.shot()
        res = self.check('![a](<screenshots/home.png>)\n\n![b](./screenshots/home.png "Title")\n\n![c](screenshots/%68ome.png)\n')
        self.assertEqual(res.problems, [])
        self.assertEqual([e["src"] for e in res.embedded], ["screenshots/home.png", "./screenshots/home.png", "screenshots/%68ome.png"])
        self.assertTrue(all(e["path"] for e in res.embedded))

    def test_missing_markdown_package_exits_2(self):
        blocker = self.root / "blocker" / "markdown"
        blocker.mkdir(parents=True)
        (blocker / "__init__.py").write_text('raise ImportError("blocked for this test", name="markdown")\n', encoding="utf-8")
        p = self.report("![x](screenshots/home.png)\n")
        r = qs.run_script(SCRIPT, p, env={"PYTHONPATH": str(blocker.parent)})
        self.assertEqual(r.returncode, 2)
        self.assertIn("markdown", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.stdout, "")


class StructuralValidation(RunFolder):
    def test_every_truncated_or_hollow_file_is_rejected_with_a_clear_message(self):
        for name, data in img.TRUNCATED.items():
            with self.subTest(name):
                ext = {"png": ".png", "jpeg": ".jpg", "gif": ".gif", "webp": ".webp"}[name.split("-")[0]]
                self.shot(name + ext, bytes(data))
                res = self.check(f"![x](screenshots/{name}{ext})\n")
                self.assertEqual(self.kinds(res), ["invalid"], res.problems)
                kind = name.split("-")[0].upper().replace("JPEG", "JPEG").replace("WEBP", "WebP")
                self.assertTrue(res.problems[0][2].startswith(kind), res.problems[0][2])
                self.assertIn(f"screenshots/{name}{ext}", res.problems[0][2])

    def test_the_eight_byte_png_signature_alone_is_rejected(self):
        self.shot("sig.png", b"\x89PNG\r\n\x1a\n")
        self.assertEqual(self.kinds(self.check("![x](screenshots/sig.png)\n")), ["invalid"])

    def test_real_small_images_of_each_type_pass(self):
        for name, data in (("a.png", img.png()), ("alpha.png", img.png(alpha=True)), ("b.jpg", img.JPEG), ("c.gif", img.GIF), ("d.webp", img.WEBP)):
            with self.subTest(name):
                self.assertEqual(RC.validate_image(data)[1], None)

    def test_review_regression_webp_with_an_empty_vp8_chunk_is_rejected(self):
        data = bytes.fromhex("524946460c000000574542505650382000000000")
        self.assertEqual(RC.validate_image(data)[0], None)
        self.shot("empty.webp", data)
        self.assertEqual(self.kinds(self.check("![x](screenshots/empty.webp)\n")), ["invalid"])

    def test_review_regression_gif_with_header_and_trailer_only_is_rejected(self):
        data = b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"
        mime, err = RC.validate_image(data)
        self.assertIsNone(mime)
        self.assertIn("no image block", err)

    def test_png_with_a_pixel_stream_that_does_not_match_its_header_is_rejected(self):
        mime, err = RC.validate_image(img.png_from_raw(4, 4, b"\x00" * 51))
        self.assertIsNone(mime)
        self.assertIn("incomplete (51 of 52", err)

    def test_valid_pngs_of_every_colour_type_and_interlace_pass(self):
        z = lambda n: b"\x00" * n
        cases = {
            "gray8": img.png_from_raw(5, 3, z(3 * (1 + 5)), ctype=0),
            "gray1": img.png_from_raw(9, 2, z(2 * (1 + 2)), ctype=0, depth=1),
            "rgb16": img.png_from_raw(2, 2, z(2 * (1 + 12)), ctype=2, depth=16),
            "palette4": img.png_from_raw(5, 2, z(2 * (1 + 3)), ctype=3, depth=4, palette=True),
            "gray-alpha": img.png_from_raw(3, 3, z(3 * (1 + 6)), ctype=4),
            "rgba": img.png_from_raw(3, 3, z(3 * (1 + 12)), ctype=6),
            # Adam7, 8x8 RGB: pass sizes (rows x pixels) 1x1, 1x1, 1x2, 2x2, 2x4, 4x4, 4x8 -> 4+4+7+14+26+52+100 bytes
            "adam7-8x8": img.png_from_raw(8, 8, z(207), interlace=1),
        }
        for name, data in cases.items():
            with self.subTest(name):
                self.assertEqual(RC.validate_image(data), ("image/png", None))
        mime, err = RC.validate_image(img.png_from_raw(8, 8, z(206), interlace=1))
        self.assertIsNone(mime)
        self.assertIn("incomplete", err)

    def test_decompression_bomb_is_refused_quickly_without_inflating_it(self):
        import time, zlib
        comp, chunks = zlib.compressobj(9), []
        for _ in range(200):
            chunks.append(comp.compress(b"\x00" * (1024 * 1024)))   # 200 MB of zeros, a few hundred KB compressed
        chunks.append(comp.flush())
        bomb = img.png_from_raw(100, 100, b"", idat=b"".join(chunks))   # the header implies only 30,100 bytes
        t0 = time.time()
        mime, err = RC.validate_image(bomb)
        self.assertLess(time.time() - t0, 2)
        self.assertIsNone(mime)
        self.assertIn("longer than its header implies", err)

    def test_enormous_declared_dimensions_are_refused_before_any_decompression(self):
        for w, h, expect in ((60000, 60000, "over the 256 MB limit"), (70000, 10, "per side limit")):
            with self.subTest(w=w):
                mime, err = RC.validate_image(img.png_from_raw(w, h, b"\x00", ctype=6))
                self.assertIsNone(mime)
                self.assertIn(expect, err)

    def test_the_limit_is_stated_in_help_and_in_the_output_for_non_png_images(self):
        h = self.cli("--help").stdout
        self.assertIn("PNG            decoded in full", h)
        self.assertIn("structural checks only", h)
        self.assertIn("does NOT prove the image decodes", h)
        self.shot("a.jpg", img.JPEG)
        p = self.report("![A photo](screenshots/a.jpg)\n")
        r = self.cli(p)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("note: PNG files are decoded in full. JPEG, GIF and WebP are checked structurally only: that does not prove the image decodes", r.stdout)
        self.assertTrue(r.stdout.endswith("1 images embedded, 0 problems\n"))
        self.assertEqual(self.cli(p, "--strict").returncode, 0)   # the statement is not a problem

    def test_png_only_reports_carry_no_limit_note(self):
        self.shot("a.png")
        r = self.cli(self.report("![A](screenshots/a.png)\n"))
        self.assertEqual(r.stdout, "1 images embedded, 0 problems\n")

    def test_jpeg_with_trailing_zero_padding_is_accepted(self):
        self.assertIsNone(RC.validate_image(img.JPEG + b"\x00\x00")[1])

    def test_webp_with_trailing_bytes_after_the_riff_is_accepted_but_a_short_riff_is_not(self):
        self.assertIsNone(RC.validate_image(img.WEBP + b"\x00")[1])
        self.assertIsNotNone(RC.validate_image(img.WEBP[:30])[1])


class Mentions(RunFolder):
    def test_paths_named_but_not_embedded_are_errors_with_line_numbers(self):
        for n in ("a.png", "b.png", "c.png", "d.png"):
            self.shot(n, rgb=(len(n), 0, 0))
        res = self.check("# R\n\nEvidence: screenshots/a.png\n\nSee `screenshots/b.png` for detail.\n\n| x | y |\n|---|---|\n| row | screenshots/c.png |\n\n"
                         "[open](screenshots/d.png)\n")
        self.assertEqual([(l, k) for l, k, _ in res.problems], [(3, "unembedded"), (5, "unembedded"), (9, "unembedded"), (11, "unembedded")])
        self.assertIn("referenced but not embedded: screenshots/a.png", res.problems[0][2])

    def test_a_path_that_is_also_embedded_is_not_an_error(self):
        self.shot()
        res = self.check("![Home](screenshots/home.png)\n\nEvidence: `screenshots/home.png`, home.png, ./screenshots/home.png\n")
        self.assertEqual(res.problems, [])

    def test_mention_of_a_missing_file_is_still_reported(self):
        res = self.check("Evidence: screenshots/never-taken.png\n")
        self.assertEqual(self.kinds(res), ["unembedded"])

    def test_remote_image_urls_in_prose_are_not_treated_as_local_mentions(self):
        res = self.check("Compare with https://example.com/design/mock.png and <img src=http://example.com/x.png>.\n")
        self.assertEqual(res.problems, [])

    def test_extensions_are_case_insensitive_and_trailing_punctuation_is_fine(self):
        res = self.check("See screenshots/Shot.PNG. And (screenshots/two.jpeg), also `screenshots/three.webp`;\n")
        self.assertEqual(len(res.problems), 3)

    def test_non_image_words_are_ignored(self):
        self.assertEqual(self.check("Open report.md and findings.json, then see pngs, a.png.txt and gif.\n").problems, [])


class CodeFences(RunFolder):
    def test_image_syntax_and_paths_inside_fences_are_ignored(self):
        res = self.check("# R\n\n```markdown\n![example](screenshots/nope.png)\nEvidence: screenshots/other.png\n```\n\n~~~\n![x](http://e.com/a.png)\n~~~\n")
        self.assertEqual((len(res.embedded), res.problems), (0, []))

    def test_text_after_a_closed_fence_is_checked_again(self):
        res = self.check("```\n![x](a.png)\n```\n\n![after](screenshots/gone.png)\n")
        self.assertEqual([(l, k) for l, k, _ in res.problems], [(5, "missing")])

    def test_a_longer_fence_is_not_closed_by_a_shorter_one(self):
        res = self.check("````\n```\n![x](screenshots/nope.png)\n```\n````\n")
        self.assertEqual((len(res.embedded), res.problems), (0, []))


class FindingsCrossCheck(RunFolder):
    def findings(self, items):
        p = self.run / "findings.json"
        p.write_text(json.dumps({"findings": items}), encoding="utf-8")
        return p

    def test_evidence_image_that_is_not_embedded(self):
        self.shot("a.png"); self.shot("b.png", rgb=(0, 9, 0))
        fj = self.findings([{"id": "QA-01", "evidence": ["screenshots/a.png"]}, {"id": "QA-02", "evidence": ["screenshots/b.png (mobile)"]}])
        res = self.check("![A](screenshots/a.png)\n", findings=fj)
        self.assertEqual(self.kinds(res), ["finding"])
        self.assertIn("QA-02", res.problems[0][2])
        self.assertIn("screenshots/b.png", res.problems[0][2])

    def test_embedded_evidence_passes_and_non_image_evidence_is_ignored(self):
        self.shot()
        fj = self.findings([{"id": "QA-01", "evidence": ["screenshots/home.png", "console log", "https://example.com/x.png"]}, {"id": "QA-02"}])
        self.assertEqual(self.check("![Home](screenshots/home.png)\n", findings=fj).problems, [])

    def test_the_shipped_sample_report_and_findings_are_clean(self):
        shutil.copy(REPORT_FIXTURES / "sample_report.md", self.run / "report.md")
        shutil.copy(REPORT_FIXTURES / "sample_findings.json", self.run / "findings.json")
        self.shot("home.png"); self.shot("contact.png", rgb=(0, 0, 255))
        res = RC.check(self.run / "report.md", findings=self.run / "findings.json")
        self.assertEqual((len(res.embedded), res.problems, res.notes), (2, [], []))


class Notes(RunFolder):
    def test_unreferenced_image_files_are_notes_not_errors(self):
        self.shot("used.png"); self.shot("orphan.png", rgb=(5, 5, 5))
        (self.run / "evidence").mkdir()
        (self.run / "evidence" / "orphan2.jpg").write_bytes(img.JPEG)
        res = self.check("![Used](screenshots/used.png)\n")
        self.assertEqual(res.problems, [])
        self.assertEqual(sorted(m for _, m in res.notes), ["image file never referenced: evidence/orphan2.jpg", "image file never referenced: screenshots/orphan.png"])

    def test_findings_but_no_embedded_images(self):
        fj = self.run / "findings.json"
        fj.write_text(json.dumps({"findings": [{"id": "QA-01", "evidence": []}]}), encoding="utf-8")
        res = self.check("# Report with no pictures\n", findings=fj)
        self.assertEqual(res.problems, [])
        self.assertIn("1 findings but no embedded images", res.notes[0][1])

    def test_strict_turns_notes_into_errors(self):
        self.shot("used.png"); self.shot("orphan.png", rgb=(5, 5, 5))
        res = self.check("![Used](screenshots/used.png)\n", strict=True)
        self.assertEqual(self.kinds(res), ["note"])
        self.assertEqual(res.notes, [])

    def test_a_referenced_file_is_not_an_orphan(self):
        self.shot("used.png")
        self.assertEqual(self.check("Evidence: screenshots/used.png\n").notes, [])


class Cli(RunFolder):
    def test_clean_run_exit_0_and_summary_line(self):
        self.shot()
        p = self.report("![Home page](screenshots/home.png)\n")
        r = self.cli(p)
        self.assertEqual((r.returncode, r.stdout), (0, "1 images embedded, 0 problems\n"))

    def test_problems_exit_1_with_line_numbers(self):
        p = self.report("# R\n\n![Gone](screenshots/gone.png)\n\nEvidence: screenshots/x.png\n")
        r = self.cli(p)
        self.assertEqual(r.returncode, 1)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "report.md:3: image file does not exist: screenshots/gone.png")
        self.assertTrue(lines[1].startswith("report.md:5: image referenced but not embedded: screenshots/x.png"))
        self.assertEqual(lines[-1], "1 images embedded, 2 problems")

    def test_strict_flag_changes_the_exit_code(self):
        self.shot("used.png"); self.shot("orphan.png", rgb=(5, 5, 5))
        p = self.report("![Used](screenshots/used.png)\n")
        r = self.cli(p)
        self.assertEqual(r.returncode, 0)
        self.assertIn("note: image file never referenced: screenshots/orphan.png", r.stdout)
        self.assertEqual(self.cli(p, "--strict").returncode, 1)

    def test_findings_option(self):
        self.shot()
        p = self.report("![Home](screenshots/home.png)\n")
        fj = self.run / "findings.json"
        fj.write_text(json.dumps({"findings": [{"id": "QA-09", "evidence": ["screenshots/other.png"]}]}), encoding="utf-8")
        r = self.cli(p, "--findings", fj)
        self.assertEqual(r.returncode, 1)
        self.assertIn("finding QA-09", r.stdout)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.cli().returncode, 2)
        self.assertEqual(self.cli(self.run / "absent.md").returncode, 2)
        p = self.report("# R\n")
        self.assertEqual(self.cli(p, "--findings", self.run / "absent.json").returncode, 2)
        bad = self.run / "findings.json"
        bad.write_text("{nope", encoding="utf-8")
        self.assertEqual(self.cli(p, "--findings", bad).returncode, 2)
        self.assertEqual(self.cli(p, "--bogus").returncode, 2)

    def test_help_works(self):
        r = self.cli("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--strict", r.stdout)


if __name__ == "__main__":
    unittest.main()
