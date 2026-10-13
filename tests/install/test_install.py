"""Checks for install.sh: dry run by default, never overwrites, installs the right edition.

Run from the repository root: python3 -m unittest discover -s tests/install -v
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = ("qa-standards", "qa-site-audit", "qa-release")


def run(*args):
    return subprocess.run(["bash", str(ROOT / "install.sh"), *args], capture_output=True, text=True)


class Install(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.target = Path(self._tmp.name) / "skills"

    def tearDown(self):
        self._tmp.cleanup()

    def test_help_exits_zero(self):
        r = run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--edition", r.stdout)

    def test_missing_or_unknown_options_exit_two(self):
        for args in ([], ["--edition", "local"], ["--target", str(self.target)],
                     ["--edition", "nope", "--target", str(self.target)],
                     ["--edition", "local", "--target", str(self.target), "--bogus"]):
            self.assertEqual(run(*args).returncode, 2, args)

    def test_dry_run_writes_nothing(self):
        r = run("--edition", "local", "--target", str(self.target))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Dry run", r.stdout)
        self.assertFalse(self.target.exists())

    def test_apply_installs_each_edition_with_its_own_environment_note(self):
        for edition in ("local", "hosted-bot", "dedicated-mac"):
            target = self.target / edition
            r = run("--edition", edition, "--target", str(target), "--apply")
            self.assertEqual(r.returncode, 0, r.stderr)
            for skill in SKILLS:
                self.assertTrue((target / skill / "SKILL.md").is_file(), f"{edition}/{skill}")
            got = (target / "qa-standards" / "environment.md").read_text(encoding="utf-8")
            want = (ROOT / "editions" / edition / "environment.md").read_text(encoding="utf-8")
            self.assertEqual(got, want, edition)
            self.assertFalse(list(target.rglob("__pycache__")))

    def test_existing_skill_is_not_overwritten(self):
        (self.target / "qa-release").mkdir(parents=True)
        (self.target / "qa-release" / "mine.txt").write_text("keep me", encoding="utf-8")
        r = run("--edition", "local", "--target", str(self.target), "--apply")
        self.assertEqual(r.returncode, 2)
        self.assertEqual((self.target / "qa-release" / "mine.txt").read_text(encoding="utf-8"), "keep me")
        self.assertFalse((self.target / "qa-standards").exists(), "nothing else may be installed either")

    def test_replace_moves_the_old_folder_aside(self):
        (self.target / "qa-release").mkdir(parents=True)
        (self.target / "qa-release" / "mine.txt").write_text("keep me", encoding="utf-8")
        r = run("--edition", "local", "--target", str(self.target), "--apply", "--replace")
        self.assertEqual(r.returncode, 0, r.stderr)
        backups = list(self.target.glob("qa-release.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "mine.txt").read_text(encoding="utf-8"), "keep me")
        self.assertTrue((self.target / "qa-release" / "SKILL.md").is_file())

    def test_dot_dot_in_target_is_refused_and_nothing_moves(self):
        (self.target / "qa-release").mkdir(parents=True)
        (self.target / "qa-release" / "mine.txt").write_text("keep me", encoding="utf-8")
        sneaky = str(self.target / "missing" / "..")
        for extra in ([], ["--apply"]):
            r = run("--edition", "local", "--target", sneaky, *extra)
            self.assertEqual(r.returncode, 2, extra)
        self.assertEqual((self.target / "qa-release" / "mine.txt").read_text(encoding="utf-8"), "keep me")
        self.assertFalse((self.target / "missing").exists())
        self.assertFalse(list(self.target.glob("*.bak-*")))

    def test_target_with_spaces(self):
        target = Path(self._tmp.name) / "my skills folder"
        r = run("--edition", "local", "--target", str(target), "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((target / "qa-standards" / "environment.md").is_file())


if __name__ == "__main__":
    unittest.main()
