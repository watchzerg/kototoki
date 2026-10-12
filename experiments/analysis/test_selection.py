"""Synthetic tests for the already frozen policy's numeric ordering."""

import copy
import unittest

from .development_selection import dominates, role_key


def route():
    return {"route_id": "test", "configuration_id": "test-config", "summary": {
        "text": {"CER": .2, "deletion_rate": .05, "I": 5, "reference_characters": 100},
        "timing": {"boundary_complete_count": 90, "denominator": 100, "measurable_coverage": .8,
                   "success": {key: {"lower": .6} for key in ("0.5", "2.0", "5.0")}}}}


class SelectionTests(unittest.TestCase):
    def test_equal_does_not_dominate(self):
        self.assertFalse(dominates(route(), route()))

    def test_timing_gain_and_coverage_loss_are_not_dominance(self):
        old, new = route(), route()
        new["summary"]["timing"]["success"]["0.5"]["lower"] = .7
        new["summary"]["timing"]["measurable_coverage"] = .7
        self.assertFalse(dominates(new, old))
        self.assertFalse(dominates(old, new))
        self.assertLess(role_key(new, "timing"), role_key(old, "timing"))

    def test_content_role_prioritizes_deletions_before_cer(self):
        old, new = route(), route()
        new["summary"]["text"].update(deletion_rate=.04, CER=.3)
        self.assertLess(role_key(new, "content_preservation"), role_key(old, "content_preservation"))

    def test_conditional_tails_are_not_pareto_axes(self):
        old, new = route(), copy.deepcopy(route())
        new["summary"]["timing"]["conditional_p95"] = .1
        self.assertFalse(dominates(new, old))
        new["summary"]["text"]["CER"] = .1
        self.assertTrue(dominates(new, old))


if __name__ == "__main__":
    unittest.main()
