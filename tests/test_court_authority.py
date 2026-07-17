# SPDX-License-Identifier: GPL-3.0-only

import unittest
from types import SimpleNamespace

from services.court_authority import authority_rank, hierarchy, resolve_authority


class TestCourtAuthority(unittest.TestCase):
    def test_hierarchy_is_explicit_and_stable(self):
        self.assertEqual(
            hierarchy(),
            ("emergency", "medical", "owner", "service", "guest", "oem", "remote", "unknown"),
        )
        self.assertGreater(authority_rank("emergency"), authority_rank("medical"))
        self.assertGreater(authority_rank("medical"), authority_rank("owner"))
        self.assertGreater(authority_rank("owner"), authority_rank("guest"))

    def test_single_active_authority_resolves(self):
        result = resolve_authority(SimpleNamespace(authority_profile="owner"))
        self.assertTrue(result.valid)
        self.assertEqual(result.selected_profile, "owner")
        self.assertEqual(result.selected_rank, 600)
        self.assertEqual(result.candidates, ("owner",))

    def test_highest_candidate_must_match_active_authority(self):
        result = resolve_authority(SimpleNamespace(
            authority_profile="owner",
            authority_profiles=("owner", "emergency"),
        ))
        self.assertFalse(result.valid)
        self.assertEqual(result.state, "authority_conflict")
        self.assertEqual(result.selected_profile, "emergency")
        self.assertIn("does not match", result.detail)

    def test_highest_active_candidate_resolves(self):
        result = resolve_authority(SimpleNamespace(
            authority_profile="medical",
            authority_profiles=("guest", "medical", "remote"),
        ))
        self.assertTrue(result.valid)
        self.assertEqual(result.selected_profile, "medical")
        self.assertEqual(result.selected_rank, 700)

    def test_unknown_duplicate_and_empty_candidates_fail_closed(self):
        contexts = (
            SimpleNamespace(authority_profile="wizard"),
            SimpleNamespace(authority_profile="owner", authority_profiles=("owner", "wizard")),
            SimpleNamespace(authority_profile="owner", authority_profiles=("owner", "owner")),
            SimpleNamespace(authority_profile="owner", authority_profiles=()),
            SimpleNamespace(authority_profile="unknown"),
        )
        for context in contexts:
            with self.subTest(context=context):
                self.assertFalse(resolve_authority(context).valid)


if __name__ == "__main__":
    unittest.main()
