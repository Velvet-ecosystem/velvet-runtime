# SPDX-License-Identifier: GPL-3.0-only

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "up2_prepare.py"
SPEC = importlib.util.spec_from_file_location("up2_prepare", MODULE_PATH)
up2_prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(up2_prepare)


class FounderEcosystemSyncTests(unittest.TestCase):
    def test_founder_dependencies_include_current_integrated_repos(self):
        self.assertIn("velvet-communications", up2_prepare.DEPENDENCIES)
        self.assertIn("velours_library", up2_prepare.DEPENDENCIES)
        self.assertIn("velvet-interface", up2_prepare.DEPENDENCIES)
        self.assertIn("velvet-language", up2_prepare.DEPENDENCIES)

    @mock.patch.object(up2_prepare, "run")
    @mock.patch.object(up2_prepare, "repository_is_clean", return_value=False)
    def test_dirty_repository_is_preserved(self, _clean, run):
        result = up2_prepare.sync_existing_repository(Path("/tmp/repo"), "repo")
        self.assertFalse(result)
        run.assert_not_called()

    @mock.patch.object(up2_prepare, "run")
    @mock.patch.object(up2_prepare, "repository_is_clean", return_value=True)
    @mock.patch.object(up2_prepare, "output")
    def test_clean_repository_fast_forwards_upstream(self, output, _clean, run):
        output.side_effect = ["main", "origin/main"]
        result = up2_prepare.sync_existing_repository(Path("/tmp/repo"), "repo")
        self.assertTrue(result)
        self.assertEqual(
            run.call_args_list,
            [
                mock.call(["git", "fetch", "--prune", "origin"], cwd=Path("/tmp/repo")),
                mock.call(["git", "merge", "--ff-only", "origin/main"], cwd=Path("/tmp/repo")),
            ],
        )

    @mock.patch.object(up2_prepare, "run")
    @mock.patch.object(up2_prepare, "repository_is_clean", return_value=True)
    @mock.patch.object(up2_prepare, "output")
    def test_missing_upstream_is_preserved(self, output, _clean, run):
        output.side_effect = ["main", subprocess.CalledProcessError(1, ["git"])]
        result = up2_prepare.sync_existing_repository(Path("/tmp/repo"), "repo")
        self.assertFalse(result)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
