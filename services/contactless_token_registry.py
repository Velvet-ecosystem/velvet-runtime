# SPDX-License-Identifier: GPL-3.0-only
"""Private pseudonymous registry for contactless verification factors."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional


REGISTRY_SCHEMA = "velvet.contactless_token_registry.v1"
_REFERENCE_PREFIX = "hmac-sha256:"


class ContactlessRegistryError(ValueError):
    """Raised when secret or registry material is unsafe or malformed."""


@dataclass(frozen=True)
class ContactlessTokenRecord:
    token_ref: str
    principal_ref: str
    label: str
    role_hint: str
    enabled: bool


class ContactlessTokenRegistry:
    def __init__(self, records: Mapping[str, ContactlessTokenRecord]) -> None:
        self._records = dict(records)

    def resolve(self, token_ref: str) -> Optional[ContactlessTokenRecord]:
        return self._records.get(token_ref)

    @classmethod
    def load(cls, path: Path) -> "ContactlessTokenRegistry":
        raw = _read_private_file(path, max_bytes=256 * 1024)
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContactlessRegistryError("contactless registry is not valid UTF-8 JSON") from exc
        if not isinstance(document, dict) or document.get("schema") != REGISTRY_SCHEMA:
            raise ContactlessRegistryError("unsupported contactless registry schema")
        tokens = document.get("tokens")
        if not isinstance(tokens, list) or len(tokens) > 1024:
            raise ContactlessRegistryError("contactless registry tokens must be a bounded list")

        records = {}  # type: Dict[str, ContactlessTokenRecord]
        for item in tokens:
            if not isinstance(item, dict):
                raise ContactlessRegistryError("contactless registry entry must be an object")
            token_ref = _required_text(item, "token_ref")
            if not token_ref.startswith(_REFERENCE_PREFIX) or len(token_ref) != len(_REFERENCE_PREFIX) + 64:
                raise ContactlessRegistryError("contactless token_ref must be a SHA-256 HMAC reference")
            try:
                int(token_ref[len(_REFERENCE_PREFIX):], 16)
            except ValueError as exc:
                raise ContactlessRegistryError("contactless token_ref digest is not hexadecimal") from exc
            record = ContactlessTokenRecord(
                token_ref=token_ref,
                principal_ref=_required_text(item, "principal_ref"),
                label=_required_text(item, "label"),
                role_hint=_required_text(item, "role_hint"),
                enabled=_required_bool(item, "enabled"),
            )
            if token_ref in records:
                raise ContactlessRegistryError("duplicate contactless token_ref")
            records[token_ref] = record
        return cls(records)


def load_hmac_secret(path: Path) -> bytes:
    secret = _read_private_file(path, max_bytes=4096)
    if len(secret) < 32:
        raise ContactlessRegistryError("contactless HMAC secret must contain at least 32 bytes")
    return secret


def derive_token_reference(secret: bytes, reader_id: str, data_hex: str) -> str:
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("contactless HMAC secret must contain at least 32 bytes")
    if not isinstance(reader_id, str) or not reader_id.strip():
        raise ValueError("reader_id must be non-empty")
    if not isinstance(data_hex, str) or len(data_hex) != 10:
        raise ValueError("RDM6300 data_hex must contain ten characters")
    normalized = data_hex.upper()
    try:
        bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError("RDM6300 data_hex must be hexadecimal") from exc
    message = b"velvet-contactless-v1\x00" + reader_id.strip().encode("utf-8") + b"\x00" + normalized.encode("ascii")
    digest = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return _REFERENCE_PREFIX + digest


def _read_private_file(path: Path, max_bytes: int) -> bytes:
    candidate = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(candidate), flags)
    except OSError as exc:
        raise ContactlessRegistryError("cannot open private contactless file: %s" % exc)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise ContactlessRegistryError("private contactless path must be a regular file")
        if stat.S_IMODE(details.st_mode) & 0o077:
            raise ContactlessRegistryError("private contactless file must not permit group or other access")
        if details.st_size <= 0 or details.st_size > max_bytes:
            raise ContactlessRegistryError("private contactless file size is outside bounds")
        content = os.read(descriptor, max_bytes + 1)
        if len(content) > max_bytes:
            raise ContactlessRegistryError("private contactless file exceeds configured bound")
        return content.rstrip(b"\r\n")
    finally:
        os.close(descriptor)


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise ContactlessRegistryError("%s must be bounded non-empty text" % key)
    return value.strip()


def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ContactlessRegistryError("%s must be boolean" % key)
    return value
