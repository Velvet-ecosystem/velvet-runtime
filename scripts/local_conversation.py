#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Founder bench console for Velvet's grounded local conversation path."""

from __future__ import annotations

import argparse
from pathlib import Path

from services.local_conversation import (
    LocalConversationError,
    build_local_conversation_gateway,
    configured_body_snapshot_path,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Talk to Velvet through the local Core/Language body-state path."
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help="Runtime body-state snapshot path (defaults to VELVET_BODY_SNAPSHOT_PATH or /run/velvet/body-state.json)",
    )
    parser.add_argument(
        "--conversation-id",
        default="founder-bench-conversation",
        help="ephemeral local conversation id",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="show turn metadata after each reply",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot = args.snapshot or configured_body_snapshot_path()
    try:
        gateway = build_local_conversation_gateway(
            snapshot_path=snapshot,
            conversation_id=args.conversation_id,
        )
    except (LocalConversationError, ImportError, ValueError) as exc:
        print("Velvet local conversation could not start: %s" % exc)
        return 2

    print("Velvet local grounded conversation")
    print("Body state: %s" % snapshot)
    print("Commands: /quit exits, /debug toggles turn details")
    debug = bool(args.debug)

    while True:
        try:
            text = input("You> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        command = text.strip().casefold()
        if command in {"/quit", "/exit"}:
            break
        if command == "/debug":
            debug = not debug
            print("Debug %s." % ("on" if debug else "off"))
            continue
        if not text.strip():
            continue

        try:
            exchange = gateway.submit(text)
        except Exception as exc:
            # Bench surface only. Never turn a resolver/runtime failure into a fabricated answer.
            print("Velvet> I couldn't verify that turn: %s" % exc)
            continue

        print("Velvet> %s" % exchange.reply.text)
        if debug:
            request = exchange.request
            reply = exchange.reply
            print(
                "[turn %s | act=%s | strategy=%s | authority_check=%s | generator=%s]"
                % (
                    request.turn_number,
                    request.act.value,
                    request.strategy.value,
                    request.requires_authority_check,
                    reply.generator,
                )
            )
            source_refs = tuple(getattr(reply, "source_refs", ()))
            evidence_texts = tuple(getattr(reply, "evidence_texts", ()))
            source_label = getattr(reply, "source_label", None)
            source_labels = tuple(getattr(reply, "source_labels", ()))
            if source_refs or evidence_texts or source_label or source_labels:
                display_source = source_label or ", ".join(source_labels) or "grounded source"
                print(
                    "[grounding | source=%s | refs=%s | exact_evidence=%s]"
                    % (display_source, len(source_refs), len(evidence_texts))
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
