#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Validate the fixed Audio Studio endpoint used by Founder speech deployment."""

from __future__ import annotations

import argparse
import ipaddress
import json
from typing import Any, Dict, Optional
from urllib.parse import urlparse


EXPECTED_PATH = "/v1/speech-expressions"


def validate_speech_endpoint(endpoint: str) -> Dict[str, Any]:
    text = str(endpoint).strip()
    if not text:
        raise ValueError("speech endpoint cannot be empty")

    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("speech endpoint scheme must be http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("speech endpoint must not contain URL credentials")
    if not parsed.hostname:
        raise ValueError("speech endpoint must include a host")
    if parsed.query or parsed.fragment or parsed.params:
        raise ValueError("speech endpoint must not contain params, query, or fragment")
    if parsed.path != EXPECTED_PATH:
        raise ValueError("speech endpoint path must be %s" % EXPECTED_PATH)

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("speech endpoint port is invalid") from exc
    if port is None:
        raise ValueError("speech endpoint must include an explicit port")
    if port < 1 or port > 65535:
        raise ValueError("speech endpoint port must be between 1 and 65535")

    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError(
            "Founder speech endpoint must use an IP literal, not DNS or MagicDNS"
        ) from exc

    normalized_host = address.compressed
    host_for_url = "[%s]" % normalized_host if address.version == 6 else normalized_host
    normalized_endpoint = "%s://%s:%d%s" % (
        parsed.scheme,
        host_for_url,
        port,
        EXPECTED_PATH,
    )
    return {
        "endpoint": normalized_endpoint,
        "host": normalized_host,
        "port": port,
        "scheme": parsed.scheme,
        "ip_version": address.version,
        "loopback": address.is_loopback,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument(
        "--field",
        choices=("endpoint", "host", "port", "scheme", "ip_version", "loopback"),
        default=None,
    )
    args = parser.parse_args(argv)

    try:
        result = validate_speech_endpoint(args.endpoint)
    except ValueError as exc:
        parser.error(str(exc))

    if args.field is None:
        print(json.dumps(result, sort_keys=True))
    else:
        value = result[args.field]
        if isinstance(value, bool):
            print("true" if value else "false")
        else:
            print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
