"""Checks for tools/build.py: clean editions pass, and planted problems are refused.

Run from the repository root: python3 -m unittest discover -s tests/build -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))
import build  # noqa: E402

# A made-up private word list, standing in for the one a maintainer keeps outside the repository.
DENY_WORDS = "# test list\nnova\n*acme23\n*blue harbor\n"


def staged(edition, tmp):
    dest = Path(tmp) / "pkg"
    dest.mkdir()
    build.stage(edition, dest)
    return dest


class BuildScan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        deny = Path(self._tmp.name) / "deny.txt"
        deny.write_text(DENY_WORDS, encoding="utf-8")
        self._old = os.environ.get("QA_TOOLKIT_DENYLIST")
        os.environ["QA_TOOLKIT_DENYLIST"] = str(deny)

    def tearDown(self):
        if self._old is None: os.environ.pop("QA_TOOLKIT_DENYLIST", None)
        else: os.environ["QA_TOOLKIT_DENYLIST"] = self._old
        self._tmp.cleanup()

    def test_no_private_list_means_no_terms(self):
        os.environ.pop("QA_TOOLKIT_DENYLIST")
        self.assertEqual(build.deny_terms(), [])

    def editions(self):
        return sorted(p.name for p in build.EDITIONS.iterdir() if p.is_dir())

    def test_three_editions_exist(self):
        self.assertEqual(self.editions(), ["dedicated-mac", "hosted-bot", "local"])

    def test_every_edition_scans_clean(self):
        for edition in self.editions():
            with tempfile.TemporaryDirectory() as tmp:
                problems, _ = build.scan(staged(edition, tmp))
                self.assertEqual(problems, [], edition)

    def test_environment_note_is_the_editions_own(self):
        for edition in self.editions():
            with tempfile.TemporaryDirectory() as tmp:
                dest = staged(edition, tmp)
                got = (dest / "skills" / "qa-standards" / "environment.md").read_text(encoding="utf-8")
                want = (build.EDITIONS / edition / "environment.md").read_text(encoding="utf-8")
                self.assertEqual(got, want)

    def test_sender_ships_only_with_the_hosted_bot(self):
        for edition in self.editions():
            with tempfile.TemporaryDirectory() as tmp:
                has = (staged(edition, tmp) / "extras" / "qa-send").exists()
                self.assertEqual(has, edition == "hosted-bot", edition)

    def planted(self, rel, content):
        with tempfile.TemporaryDirectory() as tmp:
            dest = staged("local", tmp)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes): target.write_bytes(content)
            else: target.write_text(content, encoding="utf-8")
            return build.scan(dest)[0]

    def test_denied_name_is_refused(self):
        term = build.deny_terms()[0][0]
        self.assertTrue(any("denied term" in p for p in self.planted("skills/qa-release/notes.md", f"Ask {term.title()} first.\n")))

    def test_denied_name_inside_identifier_is_refused(self):
        term = build.deny_terms()[0][0]
        self.assertTrue(any("denied term" in p for p in self.planted("skills/qa-release/notes.md", f"run {term}_qa-submit now\n")))

    def test_name_variants_are_refused(self):
        first = build.deny_terms()[0][0]          # a whole-word term
        starred = "acme23"                         # a term refused anywhere
        cases = (f"{first.title()}s ran it\n", f"{first.title()}'s notes\n", f"{first.upper()}_QA_CONFIG\n",
                 f"x{starred}x\n", "Blue-Harbor ran it\n", "blue_harbor\n", "the blue\nharbor run\n")
        for text in cases:
            self.assertTrue(any("denied term" in p for p in self.planted("skills/qa-release/notes.md", text)), text)

    def test_ordinary_words_are_not_refused(self):
        self.assertEqual(self.planted("skills/qa-release/notes.md", "novel innovation novation supernova\n"), [])

    def test_denied_name_in_a_file_path_is_refused(self):
        first = build.deny_terms()[0][0]
        self.assertTrue(any("file path" in p for p in self.planted(f"skills/qa-release/{first}-notes.md", "fine\n")))
        self.assertTrue(any("file path" in p for p in self.planted(f"skills/{first}/notes.md", "fine\n")))

    def test_home_folder_paths_are_refused(self):
        for text in ("see C:\\Users\\someone\n", "in /home/dev/project\n", "open /Volumes/Backup/x\n", "HOME=/Users/alice\n", "home: /home/alice\n",
                     "run it from `/Users/alice`\n", "(/home/alice)\n", "see /Users/alice.\n", "<string>/Users/alice</string>\n"):
            self.assertTrue(any("machine path" in p for p in self.planted("skills/qa-release/notes.md", text)), text)

    def test_system_paths_are_not_refused(self):
        text = "~/Library/LaunchAgents/x.plist\n/opt/homebrew/bin\nshow State:/Users/ConsoleUser\n/Users/Shared/tools/x\n"
        self.assertEqual(self.planted("skills/qa-release/notes.md", text), [])

    def test_paths_inside_urls_are_not_refused(self):
        self.assertEqual(self.planted("skills/qa-release/notes.md", "open https://example.com/home/ and example.com/opt/x\n"), [])

    def test_zero_width_character_does_not_hide_a_name(self):
        first = build.deny_terms()[0][0]
        text = first[:2] + "\u200b" + first[2:] + " ran it\n"
        self.assertTrue(any("denied term" in p for p in self.planted("skills/qa-release/notes.md", text)))

    def test_secret_pattern_is_refused(self):
        self.assertTrue(any("secret" in p for p in self.planted("skills/qa-release/notes.md", "Authorization: Bear" + "er abcdefghijklmnop1234\n")))

    def test_same_source_gives_the_same_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = staged("hosted-bot", tmp)
            first = build.write_zip(dest, "pkg", Path(tmp) / "a")[1]
            second = build.write_zip(dest, "pkg", Path(tmp) / "b")[1]
            self.assertEqual(first, second)

    def test_machine_path_is_refused(self):
        self.assertTrue(any("machine path" in p for p in self.planted("skills/qa-release/notes.md", "see /Users/someone/runs\n")))

    def test_real_email_is_refused_but_example_is_allowed(self):
        self.assertTrue(any("email" in p for p in self.planted("skills/qa-release/notes.md", "mail person@" + "company.co.uk\n")))
        allowed = "type qa-test@example.com\nssh worker@qa-worker.local\njo@mail.example.co.uk\ncookie _ga@127.0.0.1\nx@host.test\n"
        self.assertEqual(self.planted("skills/qa-release/notes.md", allowed), [])
        for sneaky in ("a@not" + "example.com", "person@company.test" + ".com", "person@example.com" + ".evil.org", "x@example.com" + "-real.io"):
            self.assertTrue(any("email" in p for p in self.planted("skills/qa-release/notes.md", f"mail {sneaky}\n")), sneaky)
        self.assertEqual(self.planted("skills/qa-release/notes.md", "Write to qa-test@example.com.\n"), [])

    def test_leak_patterns_apply_to_file_paths(self):
        self.assertTrue(any("file path" in p for p in self.planted("skills/qa-release/person@" + "company.com.md", "fine\n")))

    def test_run_artefacts_are_refused(self):
        for rel, content in (("skills/qa-site-audit/findings.json", "{}"), ("examples/report.pdf", b"%PDF"),
                             ("skills/qa-site-audit/scripts/__pycache__/x.pyc", b"\x00"), ("shot.png", b"\x89PNG")):
            self.assertTrue(self.planted(rel, content), rel)

    def test_wrong_skill_name_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = staged("local", tmp)
            md = dest / "skills" / "qa-release" / "SKILL.md"
            md.write_text(md.read_text(encoding="utf-8").replace("name: qa-release", "name: Release QA"), encoding="utf-8")
            self.assertTrue(any("name must be" in p for p in build.scan(dest)[0]))


if __name__ == "__main__":
    unittest.main()
