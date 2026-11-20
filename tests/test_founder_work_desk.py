import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from services.founder_work_desk import (
    SCHEMA, WorkDeskError, load_workdesk_file, validate_workdesk, workdesk_report,
)

def snapshot():
    return {
        "schema": SCHEMA, "mode": "ghost", "generated_at": "2026-11-19T20:00:00Z",
        "items": [
            {
                "id": "android-v33-quota", "source": "github", "priority": "high",
                "state": "blocked", "title": "Android v33 artifact upload blocked",
                "change": "Signed build verified, artifact quota blocked delivery",
                "why": "The APK is not downloadable", "next_action": "Free disposable artifact storage",
                "source_url": "https://github.com/Velvet-ecosystem/velvet-portable-android/actions/runs/43815656781",
                "updated_at": "2026-11-16T06:22:10Z", "owner_decision": True,
            },
            {
                "id": "old-merged", "source": "github", "priority": "low", "state": "resolved",
                "title": "Previously merged issue", "change": "Already resolved",
                "why": "Routine noise", "next_action": "No action required",
                "source_url": None, "updated_at": "2026-11-15T06:22:10Z",
                "owner_decision": False,
            },
        ],
    }

class WorkDeskTests(unittest.TestCase):
    def test_prioritizes_actionable_item_and_marks_ghost(self):
        report = workdesk_report(snapshot(), now=datetime(2026, 11, 19, tzinfo=timezone.utc))
        self.assertEqual("ghost", report["mode"])
        self.assertEqual("none", report["authority"])
        self.assertFalse(report["stale"])
        self.assertEqual(["android-v33-quota"], [i["id"] for i in report["items"]])
        self.assertEqual(1, report["counts"]["owner_decisions"])

    def test_unchanged_work_is_suppressed(self):
        report = workdesk_report(snapshot(), previous=snapshot())
        self.assertEqual([], report["items"])

    def test_state_change_shows_up_once(self):
        previous = snapshot()
        updated = snapshot()
        updated["items"][0]["state"] = "needs_owner"
        report = workdesk_report(updated, previous=previous)
        self.assertEqual(1, report["counts"]["new_or_changed"])

    def test_stale_data_is_marked_not_upgraded_to_live(self):
        report = workdesk_report(snapshot(), now=datetime(2026, 12, 5, tzinfo=timezone.utc))
        self.assertTrue(report["stale"])
        self.assertEqual("ghost", report["mode"])

    def test_rejects_duplicates_invalid_source_and_untrusted_links(self):
        for mutation in ("duplicate", "source", "url", "future"):
            record = snapshot()
            if mutation == "duplicate":
                record["items"].append(dict(record["items"][0]))
            elif mutation == "source":
                record["items"][0]["source"] = "execute"
            elif mutation == "url":
                record["items"][0]["source_url"] = "https://user:password@github.com/a/b"
            else:
                record["items"][0]["updated_at"] = "2026-12-01T01:00:00Z"
            with self.assertRaises(WorkDeskError):
                validate_workdesk(record)

    def test_regular_file_only(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "fixture.json"
            path.write_text(json.dumps(snapshot()), encoding="utf-8")
            self.assertEqual(SCHEMA, load_workdesk_file(path)["schema"])
            alias = Path(raw) / "link.json"
            alias.symlink_to(path)
            with self.assertRaises(OSError):
                load_workdesk_file(alias)

if __name__ == "__main__":
    unittest.main()
