#!/usr/bin/env python3
"""The authoring rules the validator enforces beyond structure.

A long reference opens with a table of contents; every skill says when not to use it; and
a skill with siblings hands the competing cases off to them.
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import validate


def frontmatter(name, description):
    return "---\nname: %s\ndescription: %s\n---\n\n# %s\n" % (name, description, name)


class Rules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugins = self.root / "plugins"
        for target, value in (("REPO", str(self.root)), ("PLUGINS", str(self.plugins)),
                              ("FAILURES", []), ("WARNINGS", [])):
            patcher = patch.object(validate, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def skill(self, plugin, name, body, description="Does a thing. Use when asked."):
        directory = self.plugins / plugin / "skills" / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(frontmatter(name, description) + body)
        return directory

    def check(self, directory):
        validate.check_skill(directory.parts[-3], str(directory), str(directory / "SKILL.md"))
        return "\n".join(validate.FAILURES)


class WhenNotToUse(Rules):
    def test_a_skill_without_the_section_fails(self):
        failures = self.check(self.skill("p", "a", "## Steps\n\n1. Do it.\n"))
        self.assertIn("When not to use", failures)

    def test_the_section_satisfies_it(self):
        failures = self.check(self.skill("p", "a", "## When not to use this skill\n\n- X.\n"))
        self.assertEqual(failures, "")


class ReferenceContents(Rules):
    BODY = "## When not to use this skill\n\n- X.\n"

    def reference(self, directory, text):
        (directory / "references").mkdir()
        (directory / "references" / "long.md").write_text(text)

    def test_a_long_reference_without_contents_fails(self):
        directory = self.skill("p", "a", self.BODY)
        self.reference(directory, "# Long\n\n" + "line\n" * 320)
        self.assertIn("no `## Contents`", self.check(directory))

    def test_contents_near_the_top_satisfies_it(self):
        directory = self.skill("p", "a", self.BODY)
        self.reference(directory, "# Long\n\n## Contents\n\n- [Part](#part)\n\n## Part\n\n"
                       + "line\n" * 320)
        self.assertEqual(self.check(directory), "")

    def test_a_broken_contents_anchor_fails(self):
        directory = self.skill("p", "a", self.BODY)
        self.reference(directory, "# Long\n\n## Contents\n\n- [Gone](#gone)\n\n"
                       + "line\n" * 320)
        self.assertIn("#gone", self.check(directory))

    def test_a_short_reference_needs_none(self):
        directory = self.skill("p", "a", self.BODY)
        self.reference(directory, "# Short\n\n" + "line\n" * 50)
        self.assertEqual(self.check(directory), "")


class HandOff(Rules):
    BODY = "## When not to use this skill\n\n- X.\n"

    def test_a_sibling_with_no_hand_off_warns(self):
        self.skill("p", "write-x", self.BODY, "Write x. Use when asked to write x.")
        self.skill("p", "review-x", self.BODY,
                   "Review x. Use when asked to review x. To write x, use write-x instead.")
        validate.check_skill_collisions()
        warnings = "\n".join(validate.WARNINGS)
        self.assertIn("write-x", warnings)
        self.assertIn("hands nothing off", warnings)
        self.assertNotIn("review-x/SKILL.md: description hands", warnings)

    def test_a_lone_skill_needs_no_hand_off(self):
        self.skill("solo", "only", self.BODY, "Do the only thing. Use when asked.")
        validate.check_skill_collisions()
        self.assertEqual(validate.WARNINGS, [])


if __name__ == "__main__":
    unittest.main()
