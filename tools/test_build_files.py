#!/usr/bin/env python3
"""Build files for a project that has never used Sphinx, written once and never again."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from component_scripts import component_paths
sys.path[:0] = component_paths()
import sphinx_support

MAKE = shutil.which("make")


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "docs"

    def test_all_three_are_written(self):
        results = sphinx_support.write_build_files(str(self.out))
        self.assertEqual([name for name, _, _ in results],
                         ["Makefile", "make.bat", os.path.join("_static", "README.md")])
        self.assertTrue(all(state == "written" for _, state, _ in results))
        self.assertTrue((self.out / "Makefile").is_file())
        self.assertTrue((self.out / "make.bat").is_file())
        self.assertTrue((self.out / "_static" / "README.md").is_file())

    def test_nothing_is_ever_overwritten(self):
        """A build file is the project's once it exists, the same as conf.py."""
        self.out.mkdir(parents=True)
        (self.out / "Makefile").write_text("# mine\n")
        results = dict((name, state) for name, state, _ in
                       sphinx_support.write_build_files(str(self.out)))
        self.assertEqual(results["Makefile"], "exists")
        self.assertEqual(results["make.bat"], "written")
        self.assertEqual((self.out / "Makefile").read_text(), "# mine\n")

    def test_running_twice_changes_nothing(self):
        sphinx_support.write_build_files(str(self.out))
        before = (self.out / "Makefile").read_text()
        results = sphinx_support.write_build_files(str(self.out))
        self.assertTrue(all(state == "exists" for _, state, _ in results))
        self.assertEqual((self.out / "Makefile").read_text(), before)

    def test_a_dangling_symlink_is_refused_not_followed(self):
        """`lexists`, not `isfile`: writing through one creates its target outside the
        only directory this writes to."""
        self.out.mkdir(parents=True)
        target = Path(self.tmp.name) / "elsewhere"
        os.symlink(str(target), str(self.out / "Makefile"))
        results = dict((name, state) for name, state, _ in
                       sphinx_support.write_build_files(str(self.out)))
        self.assertEqual(results["Makefile"], "exists")
        self.assertFalse(target.exists(), 'wrote through the symlink')

    # -- content -----------------------------------------------------------------

    def test_optional_targets_carry_their_install_line(self):
        """An absent target tells a reader nothing; one that names its dependency does."""
        sphinx_support.write_build_files(str(self.out),
                                        optional=("spelling", "livehtml"))
        body = (self.out / "Makefile").read_text()
        self.assertIn("sphinxcontrib-spelling", body)
        self.assertIn("sphinx-autobuild", body)
        self.assertIn("spelling:", body)
        self.assertIn("livehtml:", body)

    def test_optional_targets_are_absent_when_not_asked_for(self):
        sphinx_support.write_build_files(str(self.out))
        body = (self.out / "Makefile").read_text()
        self.assertNotIn("spelling:", body)
        self.assertNotIn("livehtml:", body)
        self.assertIn("html:", body)

    def test_the_strict_target_treats_a_warning_as_an_error(self):
        """An unreachable page and a broken reference are both warnings by default."""
        sphinx_support.write_build_files(str(self.out))
        self.assertIn("-W", (self.out / "Makefile").read_text())

    def test_the_batch_file_has_no_doubled_percent_signs(self):
        """The template escapes `%` for Python formatting; the output must not carry it."""
        sphinx_support.write_build_files(str(self.out))
        body = (self.out / "make.bat").read_text()
        self.assertNotIn("%%", body)
        self.assertIn('if "%SPHINXBUILD%" == ""', body)
        self.assertIn("set SOURCEDIR=.", body)

    @unittest.skipIf(not MAKE, "make is not installed")
    def test_the_makefile_actually_parses_and_every_target_resolves(self):
        sphinx_support.write_build_files(str(self.out),
                                        optional=("spelling", "livehtml"))
        listing = subprocess.run([MAKE, "-qp"], cwd=str(self.out),
                                 capture_output=True, text=True).stdout
        for target in ("html", "strict", "clean", "linkcheck", "spelling", "livehtml"):
            self.assertIn("\n%s:" % target, listing, "no %s target" % target)

    @unittest.skipIf(not MAKE, "make is not installed")
    def test_make_html_invokes_sphinx_build_on_the_right_directories(self):
        sphinx_support.write_build_files(str(self.out))
        result = subprocess.run([MAKE, "-n", "html"], cwd=str(self.out),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sphinx-build -b html", result.stdout)
        self.assertIn('"_build/html"', result.stdout)


if __name__ == "__main__":
    unittest.main()
