#!/usr/bin/env python3
"""`readability.py` against prose written to fail it, and prose written not to.

Two fixtures and nothing else would prove little: a checker that flags everything passes
the first and a checker that flags nothing passes the second. Both are here, and the
defects this found in itself are pinned as cases, because each one made the report say
zero where the answer was not zero.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from component_scripts import component_paths, script
sys.path[:0] = component_paths()
import readability


BAD = """Configuration
=============

This section describes the configuration system and how settings are resolved.

The loader, which reads from several sources including environment variables, a file whose
location depends on whether a profile was supplied on the command line, and a set of
built-in defaults that apply when nothing else does, merges them in a precedence order and
validates each entry before the application starts. Each entry is checked. The check is
strict. Failures are reported. The reporting goes through the logger. The logger is
configured separately.

Logging
=======

This section describes the logging system.

Events are written to the sink.

Storage
=======

This section describes the storage layer.

Records are written to disk.
"""

GOOD = """Configuration
=============

Settings come from three places, and the last to speak wins: built-in defaults, then the
configuration file, then environment variables.

A missing file is not an error. The defaults apply, and the run says which it used.

Logging
=======

Every event goes to stderr by default. Set ``LOG_FILE`` to send it to a file instead.
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def page(self, name, body):
        path = self.root / name
        path.write_text(body)
        return path

    def report(self):
        return readability.report(str(self.root))

    def counts(self):
        return self.report()["counts"]


class BadProseTests(Fixture):
    """It has to find what is there."""

    def setUp(self):
        Fixture.setUp(self)
        self.page("bad.rst", BAD)

    def test_the_long_sentence_is_found(self):
        self.assertEqual(self.counts()["long_sentences"], 1)

    def test_the_wall_of_text_is_found(self):
        self.assertEqual(self.counts()["long_paragraphs"], 1)

    def test_every_announcing_opening_is_found(self):
        """Measured at 0 before the heading was excluded from its own section's prose."""
        self.assertEqual(self.counts()["announcing_openings"], 3)

    def test_the_repeated_shape_is_found(self):
        """Also 0 before that: three headings differ, so nothing looked repeated."""
        self.assertEqual(self.counts()["repeated_openings"], 1)

    def test_the_worst_passage_is_first(self):
        """A list nobody finishes is no use, so the order is the deliverable."""
        rows = readability.worst_first(self.report(), 5)
        self.assertEqual(rows[0][0], max(row[0] for row in rows), rows)
        self.assertGreater(rows[0][0], readability.LONG_SENTENCE_WORDS)

    def test_a_finding_names_the_file_and_line(self):
        rows = readability.worst_first(self.report(), 1)
        _, path, line, section, detail, _text = rows[0]
        self.assertEqual(path, "bad.rst")
        self.assertGreater(line, 0)
        self.assertEqual(section, "Configuration")
        self.assertIn("-word sentence", detail)


class GoodProseTests(Fixture):
    """And it has to stay quiet when there is nothing there."""

    def setUp(self):
        Fixture.setUp(self)
        self.page("ok.rst", GOOD)

    def test_nothing_is_reported(self):
        counts = self.counts()
        for key in ("long_sentences", "long_paragraphs", "announcing_openings",
                    "repeated_openings"):
            self.assertEqual(counts[key], 0, key)

    def test_the_sections_were_still_read(self):
        """Zero findings because the prose is sound, not because nothing was parsed."""
        counts = self.counts()
        self.assertEqual(counts["sections"], 2)
        self.assertGreater(counts["sentences"], 4)


class CodeIsNotProseTests(Fixture):
    """The defect that made this unusable on a real tree.

    Measured against this skill's own references before the fix: 257 long sentences and
    sections titled `}`. A JSON body is not prose, an 80-word span across a schema block is
    not a sentence, and a `---` inside a fence was read as a heading rule -- so the
    worst-first list, which is the whole point, was a list of code.
    """

    def test_a_fenced_block_is_not_measured(self):
        self.page("fenced.md", "# Page\n\nShort prose here.\n\n```json\n{\n  \"a\": \""
                               + " ".join(["word"] * 60) + "\"\n}\n```\n")
        self.assertEqual(self.counts()["long_sentences"], 0)

    def test_a_rule_inside_a_fence_is_not_a_heading(self):
        self.page("fenced.md", "# Page\n\nProse.\n\n```\nnot a heading\n-------------\n```\n")
        titles = [s["section"] for p in self.report()["pages"] for s in p["sections"]]
        self.assertNotIn("not a heading", titles)

    def test_an_indented_block_is_not_measured(self):
        self.page("literal.rst", "Page\n====\n\nRun it::\n\n    "
                  + " ".join(["word"] * 60) + "\n")
        self.assertEqual(self.counts()["long_sentences"], 0)

    def test_prose_after_a_code_block_is_still_measured(self):
        """Blanking code must not swallow what follows it."""
        self.page("after.md", "# Page\n\n```\ncode\n```\n\n"
                  + " ".join(["word"] * 40) + ".\n")
        self.assertEqual(self.counts()["long_sentences"], 1)


class ShareTests(Fixture):
    """A bare count reads as a crisis at 232 and as nothing at 12."""

    def test_the_share_is_reported_beside_the_count(self):
        self.page("bad.rst", BAD)
        counts = self.counts()
        self.assertGreater(counts["long_sentence_share"], 0)
        self.assertLessEqual(counts["long_sentence_share"], 1)

    def test_an_empty_share_does_not_divide_by_zero(self):
        self.page("empty.rst", "Page\n====\n\n::\n\n    only code\n")
        report = readability.report(str(self.root))
        if report["pages"]:
            self.assertGreaterEqual(report["counts"]["long_sentence_share"], 0)


class CommandTests(Fixture):
    """It runs on a tree with none of the rest of the pipeline beside it."""

    def run_it(self, *args):
        return subprocess.run(
            [sys.executable, script("readability.py")] + list(args),
            capture_output=True, text=True)

    def test_a_missing_directory_is_an_input_error(self):
        result = self.run_it(str(self.root / "nope"))
        self.assertEqual(result.returncode, 2)

    def test_a_tree_with_no_pages_is_an_input_error(self):
        result = self.run_it(str(self.root))
        self.assertEqual(result.returncode, 2)
        self.assertIn("no .rst or .md", result.stderr)

    def test_it_reports_and_never_refuses(self):
        """The measurements describe a shape, and a shape is not a verdict."""
        self.page("bad.rst", BAD)
        result = self.run_it(str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("worst first", result.stdout)

    def test_json_is_machine_readable(self):
        self.page("bad.rst", BAD)
        result = self.run_it(str(self.root), "--format", "json")
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["readability_version"], 1)

    def test_it_writes_only_where_told(self):
        self.page("bad.rst", BAD)
        before = sorted(os.listdir(str(self.root)))
        out = self.root / "out.json"
        self.run_it(str(self.root), "--out", str(out))
        self.assertTrue(out.is_file())
        self.assertEqual(sorted(os.listdir(str(self.root))),
                         sorted(before + ["out.json"]))

    def test_it_imports_nothing_from_the_pipeline(self):
        """Standalone on purpose: a reviewer who cannot run it cannot use it.

        The other scripts are absent on the machine this is most needed -- a `docs/` tree
        with no build directory, no index and no seal -- and improving how a document reads
        is not a step in the publication lifecycle.
        """
        source = open(script("readability.py"), encoding="utf-8").read()
        for forbidden in ("import manual", "import build_dir", "import findings",
                          "import sphinx_support", "import pipeline"):
            self.assertNotIn(forbidden, source, forbidden)


class ReviewHandoffTests(Fixture):
    """The join between what code measures and what only a reading can settle.

    The script finds shape. Whether a 30-word sentence is tangled or merely long is a
    reading, and two defects are invisible to it entirely: a term used before it is defined,
    and a procedure given out of order. Both clear every measurement here.
    """

    def test_the_passages_are_quoted_not_just_located(self):
        """A line number is enough to find a sentence and not enough to judge one."""
        self.page("bad.rst", BAD)
        rows = readability.worst_first(self.report(), 1)
        self.assertTrue(rows[0][5], "no text carried with the finding")
        self.assertIn("loader", rows[0][5])

    def test_a_quote_is_bounded(self):
        """Reprinting the page would make the handoff the thing nobody reads."""
        self.page("bad.rst", BAD)
        rows = readability.worst_first(self.report(), 1)
        self.assertLessEqual(len(rows[0][5].split()),
                             readability.QUOTE_WORDS + 1)

    def test_the_handoff_asks_what_shape_cannot_answer(self):
        self.page("bad.rst", BAD)
        text = readability.for_review(self.report(), 5)
        self.assertIn("clear as it stands", text)
        self.assertIn("before it is defined", text)
        self.assertIn("out of order", text)

    def test_the_handoff_gives_the_passages_to_judge(self):
        self.page("bad.rst", BAD)
        text = readability.for_review(self.report(), 5)
        self.assertIn("bad.rst:", text)
        self.assertIn("The loader", text)

    def test_a_clean_document_still_hands_over_the_questions(self):
        """Zero findings by shape is not zero to read: the two blind spots remain."""
        self.page("ok.rst", GOOD)
        text = readability.for_review(self.report(), 5)
        self.assertIn("Nothing was flagged by shape", text)
        self.assertIn("before it is defined", text)

    def test_prose_that_is_short_and_unreadable_is_not_flagged(self):
        """Pinned as a limit, not a defect: this is what the reading is for.

        Jargon with nothing defined, and a procedure taught backwards. Short sentences,
        short paragraphs, no repetition -- clean by every measure this has.
        """
        self.page("opaque.rst",
                  "Reconciliation\n==============\n\n"
                  "The reconciler idempotently converges divergent state. Conflicts "
                  "resolve via LWW semantics keyed on the vector clock.\n\n"
                  "Ordering\n========\n\n"
                  "Call flush after write. Call write after open.\n")
        counts = self.counts()
        for key in ("long_sentences", "long_paragraphs", "announcing_openings",
                    "repeated_openings"):
            self.assertEqual(counts[key], 0, key)


if __name__ == "__main__":
    unittest.main()
