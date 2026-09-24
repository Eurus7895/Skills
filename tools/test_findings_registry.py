#!/usr/bin/env python3
"""`findings.py` against the scripts it describes.

A registry nothing checks drifts the same way the comments it replaced did, and it drifts
worse: a list that is wrong is consulted and believed, where an absent list is at least
known to be absent. So every claim the registry makes is checked here.

The severity check is the one that earns its place. Seven consumers filter findings for the
exact string `"error"`, and three vocabularies exist in the scripts. A validator that wrote
`severity="warning"` would raise a finding that fails nothing, report `passed`, and look
entirely correct in its own output.
"""
import ast
import os
import re
import sys
import unittest

from component_scripts import component_paths
sys.path[:0] = component_paths()
import findings

CODE = re.compile(r"^[A-Z][0-9]{3}$")
SEVERITY_KEYS = ("severity",)
# Not a family, and not raised by a script: these come from a person's review record, which
# `review_records.py` reads rather than produces.
REVIEW_VOCABULARY = findings.SEVERITIES["review"]


def script_root():
    """The canonical tree, which is the one the registry describes."""
    for base in component_paths():
        candidate = os.path.dirname(os.path.abspath(base))
        if os.path.isfile(os.path.join(candidate, "findings.py")):
            return candidate
    raise AssertionError("could not locate the scripts directory")


def sources():
    root = script_root()
    for base, _, names in os.walk(root):
        if "__pycache__" in base:
            continue
        for name in sorted(names):
            if not name.endswith(".py") or name == "findings.py":
                continue
            path = os.path.join(base, name)
            with open(path, encoding="utf-8") as fh:
                yield os.path.relpath(path, root).replace(os.sep, "/"), fh.read()


def codes_in(text):
    """Every finding code the file mentions, however it is written.

    A literal scan rather than a scan of `finding(...)` call sites, and deliberately so: the
    `V010`-`V014` codes are selected through a dictionary and the whole `D` family is built
    as literal dicts, so a call-site scan misses six codes. It was written that way first and
    missed them, which is the argument for the blunter instrument.
    """
    found = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and CODE.match(node.value):
            found.add(node.value)
    return found


def severities_in(text):
    """Every severity string the file assigns: a call keyword, a dict value, or a default.

    **The default is the one that matters most, and it was the one missing.** The validators
    raise most of their findings through a helper declared
    `def finding(self, code, message, ..., severity="error")`, so the severity of an ordinary
    finding is written once, in a signature, and never at a call site. A first version of this
    scanned keywords and dict values only: changing that default to `"warning"` left it
    unchanged and the whole conformance suite passing, while every consumer filtering for
    `error` silently stopped blocking. That is the exact bug this file exists to catch, and it
    walked straight through the check named for it.
    """
    found = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spec = node.args
            names = list(spec.args) + list(spec.kwonlyargs)
            defaults = ([None] * (len(spec.args) - len(spec.defaults))
                        + list(spec.defaults) + list(spec.kw_defaults))
            for name, default in zip(names, defaults):
                if name.arg in SEVERITY_KEYS and isinstance(default, ast.Constant) \
                        and isinstance(default.value, str):
                    found.add(default.value)
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in SEVERITY_KEYS and isinstance(keyword.value, ast.Constant) \
                        and isinstance(keyword.value.value, str):
                    found.add(keyword.value.value)
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value in SEVERITY_KEYS \
                        and isinstance(value, ast.Constant) \
                        and isinstance(value.value, str):
                    found.add(value.value)
    return found


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = dict(sources())
        cls.used = {}
        for path, text in cls.files.items():
            for code in codes_in(text):
                cls.used.setdefault(code, set()).add(path)

    def test_the_scripts_raise_something(self):
        """A scan that found nothing would pass every test below for the wrong reason."""
        self.assertGreater(len(self.used), 50, "the code scan found almost nothing")

    # -- the registry against the scripts ----------------------------------------

    def test_every_code_a_script_mentions_is_declared(self):
        undeclared = sorted(set(self.used) - set(findings.CODES)
                            - set(findings.FOREIGN_CODES))
        self.assertEqual(undeclared, [],
                         "raised but not declared in findings.py: %s" % undeclared)

    def test_a_foreign_code_is_declared_as_foreign_rather_than_filtered_quietly(self):
        """`F401` is Ruff's, and matches the shape of ours exactly.

        Skipping it without saying so would also skip one of ours that collided with another
        tool's numbering, so it is named -- and it must still be a code some script mentions,
        or the exemption outlives its reason.
        """
        for code, why in sorted(findings.FOREIGN_CODES.items()):
            self.assertIn(code, self.used, "%s is exempted and mentioned nowhere" % code)
            self.assertNotIn(code, findings.CODES, "%s cannot be both ours and foreign" % code)
            self.assertGreater(len(why.split()), 4, code)

    def test_every_declared_code_is_still_used(self):
        """A code nobody raises is one a reader looks up and never sees."""
        dead = sorted(set(findings.CODES) - set(self.used))
        self.assertEqual(dead, [],
                         "declared in findings.py but raised nowhere: %s" % dead)

    def test_every_code_has_a_meaning_that_says_something(self):
        thin = sorted(code for code, means in findings.CODES.items()
                      if len(means.split()) < 5)
        self.assertEqual(thin, [], "these say too little to be a definition: %s" % thin)

    # -- the families --------------------------------------------------------------

    def test_every_code_belongs_to_a_declared_family(self):
        orphans = sorted(code for code in findings.CODES
                         if code[0] not in findings.FAMILIES)
        self.assertEqual(orphans, [], "no family declared for: %s" % orphans)

    def test_every_family_has_codes(self):
        empty = sorted(prefix for prefix in findings.FAMILIES
                       if not any(code[0] == prefix for code in findings.CODES))
        self.assertEqual(empty, [], "families with no codes: %s" % empty)

    def test_every_family_names_a_vocabulary_that_exists(self):
        for prefix, family in sorted(findings.FAMILIES.items()):
            self.assertIn(family["severities"], findings.SEVERITIES, prefix)

    def test_every_family_names_the_file_that_owns_it(self):
        for prefix, family in sorted(findings.FAMILIES.items()):
            for owner in family["owner"].split(", "):
                self.assertIn(owner, self.files, "%s: %s is not a script" % (prefix, owner))

    def test_every_code_appears_in_a_file_its_family_names(self):
        """The owner is a claim about where a code comes from, so it is checked.

        One direction only: every code has to appear in an owner. The reverse -- that no
        other file mentions it -- is not true and must not be asserted, because consumers
        read codes by design: `quality_docs.py` reads `A016` to decide whether the gate
        fails, and an earlier version of this test called that a violation.

        `G` names two files on purpose: a class diagram and a sequence diagram are checked
        against different sources, and the kinds of disagreement are the same.
        """
        for code, paths in sorted(self.used.items()):
            if code in findings.FOREIGN_CODES:
                continue
            owners = set(findings.FAMILIES[code[0]]["owner"].split(", "))
            self.assertTrue(paths & owners,
                            "%s appears only in %s, and its family names %s"
                            % (code, sorted(paths), sorted(owners)))

    # -- the vocabularies, which is what this is for ------------------------------

    def test_no_script_uses_a_severity_outside_its_families_vocabularies(self):
        """The silent-pass bug this registry exists to make impossible.

        Consumers filter for the exact string `error`. A validator writing `warning` raises
        a finding that blocks nothing and reports `passed`.
        """
        for path, text in sorted(self.files.items()):
            used = severities_in(text)
            if not used:
                continue
            prefixes = {code[0] for code in codes_in(text)
                        if code[0] in findings.FAMILIES}
            allowed = set(REVIEW_VOCABULARY)
            for prefix in prefixes:
                allowed |= set(
                    findings.SEVERITIES[findings.FAMILIES[prefix]["severities"]])
            stray = sorted(used - allowed)
            self.assertEqual(stray, [],
                             "%s uses %s, which no family it raises defines (allowed: %s)"
                             % (path, stray, sorted(allowed)))

    def test_the_vocabularies_do_not_overlap(self):
        """Two vocabularies sharing a word would make the check above unable to tell them
        apart, and `error` in particular has to mean one thing."""
        seen = {}
        for name, words in sorted(findings.SEVERITIES.items()):
            for word in words:
                self.assertNotIn(word, seen,
                                 "%r is in both %s and %s" % (word, seen.get(word), name))
                seen[word] = name

    def test_error_is_the_word_every_consumer_filters_for(self):
        """Renaming it would silently stop seven filters from matching anything."""
        self.assertIn("error", findings.SEVERITIES["validator"])

    def test_the_registry_declares_its_version(self):
        self.assertIsInstance(findings.FINDINGS_VERSION, int)


if __name__ == "__main__":
    unittest.main()
