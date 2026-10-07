#!/usr/bin/env python3
"""Navigation grouped by reader purpose, and an index this pipeline wrote staying wirable."""
from pathlib import Path
import sys
import tempfile
import unittest

from component_scripts import component_paths
sys.path[:0] = component_paths()
import manual
import render_docs
import wire_toctree


class GroupingTests(unittest.TestCase):
    def test_groups_come_from_the_page_id_prefix(self):
        """Not from a new field: the template already encodes the group in the id, and a
        second declaration of the same fact is one that can disagree with the first."""
        groups = render_docs.grouped(
            ["getting_started/intro", "usage/invoking", "architecture/overview",
             "appendix/faq", "development/testing"])
        self.assertEqual([caption for caption, _ in groups],
                         ["Getting Started", "Architecture", "Usage", "Development",
                          "Appendix"])

    def test_ungrouped_pages_keep_the_single_toctree(self):
        """Every non-manual preset has ids with no group prefix."""
        groups = render_docs.grouped(["overview", "key_modules", "limitations"])
        self.assertEqual(groups, [("Contents", ["overview", "key_modules",
                                                "limitations"])])

    def test_a_mixed_index_keeps_the_leftovers_last(self):
        groups = render_docs.grouped(["usage/invoking", "stray", "appendix/faq"])
        self.assertEqual([caption for caption, _ in groups],
                         ["Usage", "Appendix", "Contents"])
        self.assertEqual(groups[-1][1], ["stray"])

    def test_grouping_changes_presentation_not_which_pages_appear(self):
        ids = [p["id"] for p in manual.GENERATED] + [p["id"] for p in manual.AUTHORED]
        listed = [e for _, entries in render_docs.grouped(ids) for e in entries]
        self.assertEqual(sorted(listed), sorted(ids))
        self.assertEqual(len(listed), len(ids))

    def test_order_inside_a_group_is_preserved(self):
        groups = dict(render_docs.grouped(
            ["usage/z", "usage/a", "usage/m"]))
        self.assertEqual(groups["Usage"], ["usage/z", "usage/a", "usage/m"])


class RenderedIndexTests(unittest.TestCase):
    def index(self, emitter):
        pages = [{"id": p["id"], "order": i} for i, p
                 in enumerate(manual.GENERATED[1:] + manual.GENERATED[:1], 1)]
        authored = [{"id": p["id"], "order": 100 + i}
                    for i, p in enumerate(manual.AUTHORED)]
        doc = {"preset": "manual", "source_revision": "abc", "pages": pages}
        return render_docs.render_index(doc, pages, emitter, authored), pages, authored

    def test_every_group_is_captioned_in_rst(self):
        text, pages, authored = self.index(render_docs.Rst())
        for caption in ("Getting Started", "Architecture", "Usage", "Development",
                        "Appendix"):
            self.assertIn(":caption: %s" % caption, text)
        self.assertNotIn(":caption: Contents", text)
        for page in pages + authored:
            self.assertIn(page["id"], text)

    def test_every_group_is_captioned_in_myst(self):
        text, _, _ = self.index(render_docs.Myst())
        self.assertIn(":caption: Getting Started", text)
        self.assertIn(":caption: Appendix", text)


class WiringTests(unittest.TestCase):
    """A grouped index is now what this pipeline itself writes, so a second run has to be
    able to wire into the index the first run produced."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "index.rst"
        pages = [{"id": p["id"], "order": i} for i, p
                 in enumerate(manual.GENERATED[1:] + manual.GENERATED[:1], 1)]
        self.path.write_text(render_docs.render_index(
            {"preset": "manual", "source_revision": "a", "pages": pages},
            pages, render_docs.Rst(), []))

    def test_a_caption_names_which_toctree(self):
        changed, note = wire_toctree.wire(str(self.path),
                                          ["architecture/key_modules"], "Architecture")
        self.assertTrue(changed, note)
        lines = self.path.read_text().splitlines()
        at = lines.index("   :caption: Architecture")
        after = lines[at:at + 10]
        self.assertIn("   architecture/key_modules", after)

    def test_a_caption_that_matches_nothing_still_refuses(self):
        with self.assertRaises(wire_toctree.Refused) as caught:
            wire_toctree.wire(str(self.path), ["x/y"], "Nonexistent")
        self.assertIn("no toctree is captioned", str(caught.exception))

    def test_several_toctrees_and_no_caption_still_refuses(self):
        """The refusal stands for the case it was written for."""
        with self.assertRaises(wire_toctree.Refused) as caught:
            wire_toctree.wire(str(self.path), ["x/y"])
        self.assertIn("nothing says which one", str(caught.exception))

    def test_wiring_twice_is_wiring_once(self):
        wire_toctree.wire(str(self.path), ["architecture/key_modules"], "Architecture")
        changed, note = wire_toctree.wire(str(self.path),
                                          ["architecture/key_modules"], "Architecture")
        self.assertFalse(changed)
        self.assertIn("already listed", note)

    def test_a_single_toctree_needs_no_caption(self):
        """The old behaviour, for an index somebody else wrote."""
        path = Path(self.tmp.name) / "plain.rst"
        path.write_text("Docs\n====\n\n.. toctree::\n   :maxdepth: 2\n\n   one\n")
        changed, _ = wire_toctree.wire(str(path), ["two"])
        self.assertTrue(changed)
        self.assertIn("   two", path.read_text())

    def test_a_page_id_is_not_mistaken_for_a_caption(self):
        """`_caption` stops at the first non-option line, so an entry cannot be read as
        the caption of a directive further down."""
        path = Path(self.tmp.name) / "odd.rst"
        path.write_text(
            "Docs\n====\n\n.. toctree::\n   :maxdepth: 2\n\n   a/b\n\n"
            ".. toctree::\n   :maxdepth: 2\n   :caption: Usage\n\n   usage/x\n")
        changed, _ = wire_toctree.wire(str(path), ["usage/y"], "Usage")
        self.assertTrue(changed)
        lines = path.read_text().splitlines()
        self.assertGreater(lines.index("   usage/y"),
                           lines.index("   :caption: Usage"))


if __name__ == "__main__":
    unittest.main()
