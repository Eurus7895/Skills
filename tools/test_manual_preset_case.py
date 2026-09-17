#!/usr/bin/env python3
"""Validate the manual-preset behavioral fixture and its acceptance contract."""

import json
from pathlib import Path
import unittest


REPO = Path(__file__).resolve().parents[1]
CASE = REPO / "tests/contracts/manual-preset-orderlog.json"


class ManualPresetCaseTests(unittest.TestCase):
    def setUp(self):
        self.case = json.loads(CASE.read_text())
        self.fixture = REPO / self.case["fixture"]

    def test_required_readings_exist_and_exclude_tests(self):
        readings = self.case["required_source_readings"]
        self.assertTrue(readings)
        self.assertFalse(any(Path(path).parts[0] == "tests" for path in readings))
        for relative in readings:
            self.assertTrue((self.fixture / relative).is_file(), relative)

    def test_case_exercises_project_specific_manual_content(self):
        joined = " ".join(self.case["required_prose_facts"])
        for token in ("OrderLog", "orderlog", "ORDERLOG_PATH", "OrderService.record",
                      "Store.put", "Handler.post", "ValueError"):
            self.assertIn(token, joined)
        self.assertGreaterEqual(len(self.case["reader_tasks"]), 5)

    def test_case_requires_both_diagram_families(self):
        self.assertTrue(self.case["required_class_nodes"])
        self.assertEqual(len(self.case["required_data_flows"]), 2)
        self.assertTrue(any("association" in relation for relation in
                            self.case["required_class_relationships"]))

    def test_acceptance_covers_both_reviews_and_rendered_output(self):
        acceptance = self.case["acceptance"]
        self.assertEqual(set(acceptance), {"analysis_review", "prose_review",
                                           "diagram_review", "final_review"})
        self.assertIn("fresh confirmed reviews", acceptance["final_review"])


if __name__ == "__main__":
    unittest.main()
