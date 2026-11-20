import json
import os
import tempfile
import unittest
from pathlib import Path
from services.eleanor_workdesk_ghost import (
    append_diagnosis_ghost, build_diagnosis_work_item,
)
from services.founder_work_desk import SCHEMA, WorkDeskError, load_workdesk_file, workdesk_report
from tools.compose_founder_ghost_workdesk import _private_write, _read_doctor

URL = "https://github.com/Velvet-ecosystem/velvet-portable-android/actions/runs/43815656781"
STAMP = "2026-11-19T20:00:00Z"

def sample():
    return {
        "schema": "velvet.eleanor.build-diagnosis.v1", "source_url": URL,
        "read_only": True, "authority": "none", "diagnosis": "artifact_quota",
        "category": "infrastructure",
        "meaning": "GitHub Actions artifact storage quota prevents delivery.",
        "next_action": "Preserve v32 and free disposable storage.",
        "owner_review_required": True,
    }

def base():
    return {"schema": SCHEMA, "mode": "ghost", "generated_at": STAMP, "items": []}

class EleanorWorkDeskGhostTests(unittest.TestCase):
    def test_build_doctor_report_becomes_one_actionable_work_card(self):
        report = append_diagnosis_ghost(base(), sample(), observed_at=STAMP)
        rendered = workdesk_report(report)
        self.assertEqual(1, rendered["counts"]["blocked"])
        self.assertEqual(1, rendered["counts"]["owner_decisions"])
        self.assertEqual(URL, rendered["items"][0]["source_url"])
        self.assertEqual("ghost", rendered["mode"])

    def test_repeated_diagnosis_replaces_card_no_duplicate(self):
        first = append_diagnosis_ghost(base(), sample(), observed_at=STAMP)
        second = append_diagnosis_ghost(first, sample(), observed_at=STAMP)
        self.assertEqual(1, len(second["items"]))

    def test_untrusted_authority_or_unvalidated_schema_denied(self):
        for field, value in (("authority", "execute"), ("read_only", False),
                             ("owner_review_required", False), ("diagnosis", "install")):
            bad = sample()
            bad[field] = value
            with self.assertRaises(WorkDeskError):
                build_diagnosis_work_item(bad, observed_at=STAMP)

    def test_composer_private_atomic_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            imported = root / "doctor.json"
            imported.write_text(json.dumps({"ok": True, "report": sample()}), encoding="utf-8")
            report = _read_doctor(imported)
            document = append_diagnosis_ghost(base(), report, observed_at=STAMP)
            final = root / "workdesk.json"
            _private_write(final, document)
            self.assertEqual(SCHEMA, load_workdesk_file(final)["schema"])
            self.assertEqual(0, os.stat(final).st_mode & 0o077)

    def test_composer_rejects_output_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text("private", encoding="utf-8")
            alias = root / "alias.json"
            alias.symlink_to(target)
            with self.assertRaises(ValueError):
                _private_write(alias, base())

if __name__ == "__main__":
    unittest.main()
