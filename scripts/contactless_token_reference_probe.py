#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read one contactless frame and print only its private HMAC reference."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from services.contactless_token_registry import derive_token_reference, load_hmac_secret
from services.rdm6300_reader import ReadOnlyRdm6300Serial


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe one RDM6300 presentation without printing its raw identifier"
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("VELVET_CONTACTLESS_DEVICE", "/dev/ttyUSB0"),
    )
    parser.add_argument(
        "--reader-id",
        default=os.environ.get("VELVET_CONTACTLESS_READER_ID", "rdm6300-main"),
    )
    parser.add_argument(
        "--secret",
        type=Path,
        default=Path(
            os.environ.get(
                "VELVET_CONTACTLESS_HMAC_KEY_PATH",
                "/etc/velvet/contactless-token.key",
            )
        ),
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    reader = None
    try:
        secret = load_hmac_secret(args.secret)
        reader = ReadOnlyRdm6300Serial(args.device, timeout=args.timeout)
        frame = reader.read_frame()
        if frame is None:
            raise RuntimeError("no contactless presentation arrived before timeout")
        token_ref = derive_token_reference(secret, args.reader_id, frame.data_hex)
        print(
            json.dumps(
                {
                    "schema": "velvet.contactless_token_reference.v1",
                    "reader_id": args.reader_id,
                    "token_ref": token_ref,
                    "raw_identifier_printed": False,
                    "verification_only": True,
                    "grants_authority": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        print("Contactless reference probe blocked: %s" % exc, file=sys.stderr)
        return 2
    finally:
        if reader is not None:
            reader.close()


if __name__ == "__main__":
    raise SystemExit(main())
