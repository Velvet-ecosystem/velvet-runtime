"""
velvet-runtime: receipts/validator.py
======================================
JSONL-backed receipt validator for the Velvet runtime.

HARDENING DOCTRINE (Phase B):
- Fails CLOSED on every error condition — no exceptions propagate to caller.
- Explicitly logs every validation failure with reason.
- Validates receipt_id format before file access.
- Skips malformed JSONL lines gracefully; logs at DEBUG level.
- Read-only. Does not write receipts.

FAIL-CLOSED CONDITIONS:
  - receipt_id is None, empty, non-string, or contains only whitespace
  - receipt_id contains control characters or is suspiciously long (>512 chars)
  - Receipt store file does not exist
  - Receipt store file cannot be opened or read (OSError)
  - receipt_id not found after full scan

FILE FORMAT (receipts.jsonl):
  One JSON object per line. Each object MUST contain a "receipt_id" field.
  Example:
    {"receipt_id": "abc-123", "timestamp": "...", "action": "..."}

THREAD SAFETY:
  validate() reads the file on each call for correctness against a
  live-updated store. A read cache may be added if profiling warrants it.
"""

import json
import os
import re

from velvet_logging.logger import get_logger

logger = get_logger("velvet.receipts.validator")

# Receipts IDs must be non-empty printable ASCII strings, max 512 chars.
# Rejects None, empty string, whitespace-only, control characters, and
# strings that are too long to be legitimate.
_RECEIPT_ID_MAX_LEN = 512
_RECEIPT_ID_PATTERN = re.compile(r'^[\x20-\x7E]+$')  # printable ASCII only


def _is_valid_receipt_id_format(receipt_id) -> tuple[bool, str]:
    """
    Validate the format of a receipt_id before any file access.

    Returns (True, "") if valid, or (False, reason) if not.
    """
    if receipt_id is None:
        return False, "receipt_id is None"
    if not isinstance(receipt_id, str):
        return False, f"receipt_id is not a string (got {type(receipt_id).__name__})"
    if not receipt_id.strip():
        return False, "receipt_id is empty or whitespace-only"
    if len(receipt_id) > _RECEIPT_ID_MAX_LEN:
        return False, f"receipt_id exceeds max length ({len(receipt_id)} > {_RECEIPT_ID_MAX_LEN})"
    if not _RECEIPT_ID_PATTERN.match(receipt_id):
        return False, "receipt_id contains non-printable or non-ASCII characters"
    return True, ""


class JsonlReceiptValidator:
    """
    Validates receipt_ids against a JSONL-backed receipt store.
    Fails closed on every error condition.
    """

    def __init__(self, receipts_path: str):
        self.receipts_path = receipts_path
        logger.info(
            f"[BOOT] JsonlReceiptValidator initialized. Path: '{self.receipts_path}'"
        )

    def validate(self, receipt_id: str) -> bool:
        """
        Check whether receipt_id exists in the JSONL receipt store.

        Returns:
          True  — receipt_id found and valid.
          False — any error condition (fail closed). Reason is logged.
        """
        # Step 1: Format validation
        ok, reason = _is_valid_receipt_id_format(receipt_id)
        if not ok:
            logger.warning(
                f"[VALIDATION FAILURE] receipt_id format invalid: {reason}. "
                f"Returning False (fail closed)."
            )
            return False

        # Step 2: File existence check
        if not os.path.isfile(self.receipts_path):
            logger.warning(
                f"[VALIDATION FAILURE] Receipt store not found: "
                f"'{self.receipts_path}'. Returning False (fail closed)."
            )
            return False

        # Step 3: Scan store
        try:
            with open(self.receipts_path, "r", encoding="utf-8") as f:
                for line_number, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as je:
                        logger.debug(
                            f"[VALIDATOR] Malformed JSON on line {line_number} "
                            f"in '{self.receipts_path}': {je}. Skipping line."
                        )
                        continue

                    if not isinstance(record, dict):
                        logger.debug(
                            f"[VALIDATOR] Line {line_number} is not a JSON object. "
                            f"Skipping."
                        )
                        continue

                    if record.get("receipt_id") == receipt_id:
                        logger.debug(
                            f"[VALIDATOR] receipt_id '{receipt_id}' validated."
                        )
                        return True

        except OSError as e:
            logger.error(
                f"[VALIDATION FAILURE] Could not read receipt store "
                f"'{self.receipts_path}': {e}. Returning False (fail closed)."
            )
            return False

        logger.warning(
            f"[VALIDATION FAILURE] receipt_id '{receipt_id}' not found in store "
            f"'{self.receipts_path}'. Returning False (fail closed)."
        )
        return False
